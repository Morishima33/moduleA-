"""既有候选不足时的同身份分页检索与有限网络重试；错误原样留存。"""

import json
from urllib.parse import quote

from storage import write_json

from .coverage_sources import experimental, fetch


def fetch_retry(url, path):
    """下载失败最多重试三次，不把网络失败视作查询无命中。"""
    errors = []
    for attempt in range(3):
        try:
            return fetch(url, path)
        except (OSError, ValueError) as error:
            errors.append(
                {
                    "attempt": attempt + 1,
                    "type": type(error).__name__,
                    "reason": str(error),
                }
            )
    write_json(
        path.with_name(path.name + ".failed.json"), {"url": url, "failures": errors}
    )
    raise ValueError("官方下载三次失败，原始诊断已保留")


def pages(uniprot, folder):
    """同一人类、无报告突变实体分页返回，保留官方总数与每页原件。"""
    folder.mkdir(parents=True, exist_ok=False)
    start, seen = 0, set()
    nodes = [
        {
            "type": "terminal",
            "service": "text",
            "parameters": {"attribute": field, "operator": op, "value": value},
        }
        for field, op, value in (
            (
                "rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession",
                "exact_match",
                uniprot,
            ),
            ("entity_poly.rcsb_mutation_count", "equals", 0),
            ("rcsb_entity_source_organism.ncbi_taxonomy_id", "equals", 9606),
        )
    ]
    while True:
        query = {
            "query": {"type": "group", "logical_operator": "and", "nodes": nodes},
            "return_type": "polymer_entity",
            "request_options": {"paginate": {"start": start, "rows": 100}},
        }
        response = json.loads(
            fetch_retry(
                "https://search.rcsb.org/rcsbsearch/v2/query?json="
                + quote(json.dumps(query)),
                folder / f"page_{start:06d}.json",
            )
        )
        rows = response.get("result_set", [])
        for row in rows:
            pdb = row["identifier"].split("_")[0]
            if pdb not in seen:
                seen.add(pdb)
                yield pdb
        start += len(rows)
        if not rows or start >= response.get("total_count", start):
            break


def supplemental(root, row, folder):
    """逐个完整核验链身份与非共价来源；先固定结构与位点，之后才计算成分。"""
    accession = row["attempts"][0]["spec"]["uniprot"]
    known = {a["spec"].get("pdb_id") for a in row["attempts"]}
    for pdb in pages(accession, folder / "query"):
        if pdb in known:
            continue
        for pocket in ("reference", "p2rank"):
            work = folder / (pdb + "_" + pocket)
            for attempt in range(3):
                try:
                    origin = experimental(
                        root, {"uniprot": accession}, pdb, work, pocket
                    )
                    yield {
                        "spec": origin["spec"],
                        "source_file": origin["file"],
                        "source_audit": origin["audit"],
                        "files": origin["files"],
                    }
                    break
                except (OSError, ValueError) as error:
                    write_json(
                        folder / f"{pdb}_{pocket}_failure_{attempt}.json",
                        {"reason_zh": str(error)},
                    )
                    if not isinstance(error, (OSError, TimeoutError)):
                        break
