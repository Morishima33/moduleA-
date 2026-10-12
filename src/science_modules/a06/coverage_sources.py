"""A06候选原件获取：官方身份、序列、参考配体及原文逐份归档，不代签选择。"""

from pathlib import Path
import json, urllib.request, hashlib, re
from contracts import require
from storage import write_json, file_record
from science_modules.a06.source_inspection import inspect_experimental_source
from science_modules.a06.coverage_geometry import atoms, distance


def fetch(url, path):
    """保存每次官方响应和URL，错误明确记录，不以空内容代替。"""
    path = Path(path)
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    require(
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and parsed.hostname
        in {
            "files.rcsb.org",
            "data.rcsb.org",
            "search.rcsb.org",
            "alphafold.ebi.ac.uk",
            "rest.uniprot.org",
        },
        "只允许无凭据的官方结构和身份来源",
    )
    if path.exists():
        raw = path.read_bytes()
        proof = json.loads(
            path.with_suffix(path.suffix + ".source.json").read_text("utf-8")
        )
        require(
            proof["url"] == url and proof["sha256"] == hashlib.sha256(raw).hexdigest(),
            "来源缓存原件或URL校验失败",
        )
        return raw
    if url in _SOURCE_CACHE:
        from storage import verified_file

        old_root, raw_record, proof_record = _SOURCE_CACHE[url]
        raw = verified_file(old_root, raw_record).read_bytes()
        proof = verified_file(old_root, proof_record).read_bytes()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.with_suffix(path.suffix + ".source.json").write_bytes(proof)
        return raw
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "ModuleA/1.0"}), timeout=45
    ) as response:
        raw = response.read(30_000_001)
    require(0 < len(raw) <= 30_000_000, "官方原件为空或超过限制")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    write_json(
        path.with_suffix(path.suffix + ".source.json"),
        {"url": url, "sha256": hashlib.sha256(raw).hexdigest()},
    )
    return raw


def experimental(root, metadata, pdb_id, folder, pocket="reference"):
    """核对同一人类UniProt及非共价来源，挑选有目标接触的候选位点供最终采纳。"""
    import gemmi

    folder.mkdir(parents=True, exist_ok=True)
    existing = folder / ("inspection_" + pocket + ".json")
    if existing.exists():
        value = json.loads(existing.read_text("utf-8"))
        require(
            value["spec"]["uniprot"] == metadata["uniprot"]
            and value["spec"]["pdb_id"] == pdb_id,
            "独立候选缓存身份不符",
        )
        from storage import verified_file

        for record in value["files"]:
            verified_file(root, record)
        return value
    original = folder / (pdb_id + ".cif")
    text = fetch(
        "https://files.rcsb.org/download/" + pdb_id + ".cif", original
    ).decode()
    entry = json.loads(
        fetch(
            "https://data.rcsb.org/rest/v1/core/entry/" + pdb_id, folder / "entry.json"
        )
    )
    entities = []
    for eid in entry["rcsb_entry_container_identifiers"]["polymer_entity_ids"]:
        entities.append(
            json.loads(
                fetch(
                    "https://data.rcsb.org/rest/v1/core/polymer_entity/"
                    + pdb_id
                    + "/"
                    + eid,
                    folder / ("entity_" + eid + ".json"),
                )
            )
        )
    matched = [
        e
        for e in entities
        if metadata["uniprot"]
        in e.get("rcsb_polymer_entity_container_identifiers", {}).get("uniprot_ids", [])
    ]
    require(matched, "候选不对应目标UniProt")
    chain = matched[0]["rcsb_polymer_entity_container_identifiers"]["auth_asym_ids"][0]
    block = gemmi.cif.read_string(text).sole_block()
    structure = gemmi.make_structure_from_block(block)
    require(len(structure) == 1, "多模型来源未明确选定")
    locations = sorted(
        {
            a.altloc
            for c in structure[0]
            if c.name == chain
            for r in c
            for a in r
            if a.has_altloc()
        }
    )
    alt = "A" if "A" in locations else locations[0] if locations else None
    spec = {
        "source_type": "experimental",
        "uniprot": metadata["uniprot"],
        "chains": [chain],
        "pdb_id": pdb_id,
        "pocket": pocket,
        "altloc": alt,
    }
    proteins = [
        a
        for c in structure[0]
        if c.name == chain
        for r in c
        if r.entity_type == gemmi.EntityType.Polymer
        for a in atoms(r, alt)
    ]
    if pocket == "reference":
        possible = []
        for c in structure[0]:
            for r in c:
                if r.entity_type == gemmi.EntityType.Polymer or r.is_water():
                    continue
                if len(atoms(r, alt)) < 8 or distance(atoms(r, alt), proteins) > 5:
                    continue
                try:
                    ccd = json.loads(
                        fetch(
                            "https://data.rcsb.org/rest/v1/core/chemcomp/" + r.name,
                            folder / ("chemcomp_" + r.name + ".json"),
                        )
                    )
                    # 添加剂、离子及共价参考通过原件检查；有机配体仍只作为待采纳候选。
                    if not re.search(
                        r"\bC(?:\d|\s|$)", ccd.get("chem_comp", {}).get("formula", "")
                    ):
                        continue
                    candidate = dict(
                        spec,
                        reference_code=r.name,
                        reference_chain=c.name,
                        reference_sequence=str(r.seqid),
                    )
                    audit = inspect_experimental_source(
                        text, metadata, candidate, entities, ccd
                    )
                    require(
                        audit["reference"]["noncovalent_use_prechecked"],
                        "参考配体缺原子或为共价连接",
                    )
                    possible.append(
                        (
                            ccd["rcsb_chem_comp_info"]["atom_count_heavy"],
                            candidate,
                            audit,
                        )
                    )
                except (ValueError, KeyError):
                    continue
        require(possible, "未取得可核查的目标非共价共晶参考配体")
        _, spec, audit = max(possible, key=lambda r: r[0])
    else:
        audit = inspect_experimental_source(text, metadata, spec, entities)
    require(
        all(i["identity_check"] == "matched" for i in audit["identity"]),
        "候选人类蛋白身份核查未通过",
    )
    value = {
        "spec": spec,
        "audit": audit,
        "file": file_record(root, original, "source_original"),
        "entities": entities,
        "entry_title_zh": entry.get("struct", {}).get("title", ""),
        "sequence_range_evidence": block.get_mmcif_category("_struct_ref_seq."),
        "proposal_note_zh": "技术候选；结构域、参考位点与构象选择集中确认后才正式采用",
        "files": [
            file_record(root, p, "source_evidence")
            for p in folder.rglob("*")
            if p.is_file()
        ],
    }
    write_json(folder / ("inspection_" + pocket + ".json"), value)
    return value


def alphafold(root, metadata, folder):
    """只读取已发布模型、官方序列及PAE；不运行模型，不截取低置信部分。"""
    import gemmi

    folder.mkdir(parents=True, exist_ok=True)
    accession = metadata["uniprot"]
    records = json.loads(
        fetch(
            "https://alphafold.ebi.ac.uk/api/prediction/" + accession,
            folder / "model_metadata.json",
        )
    )
    require(isinstance(records, list) and records, "数据库尚无目标已发布模型")
    records = [r for r in records if r.get("uniprotAccession") == accession]
    require(len(records) == 1, "同一UniProt有多段模型，需要明确完整范围后再采用")
    info = records[0]
    official = json.loads(
        fetch(
            "https://rest.uniprot.org/uniprotkb/" + accession + ".json",
            folder / "uniprot.json",
        )
    )
    require(official["organism"]["taxonId"] == 9606, "目标不是人类蛋白")
    require(info["uniprotAccession"] == accession, "预测模型UniProt不符")
    text = fetch(info["cifUrl"], folder / "model.cif").decode()
    pae = json.loads(fetch(info["paeDocUrl"], folder / "pae.json"))
    block = gemmi.cif.read_string(text).sole_block()
    st = gemmi.make_structure_from_block(block)
    require(len(st) == 1 and len(st[0]) == 1, "预测模型链范围不完整")
    c = st[0][0]
    residues = [r for r in c if r.entity_type == gemmi.EntityType.Polymer]
    sequence = "".join(
        gemmi.find_tabulated_residue(r.name).one_letter_code for r in residues
    )
    start, end = info["uniprotStart"], info["uniprotEnd"]
    require(
        sequence == official["sequence"]["value"][start - 1 : end],
        "预测坐标与目标序列不一致",
    )
    require(len(residues) == end - start + 1, "预测残基映射不完整")
    scores = [next(a.b_iso for a in r if a.name == "CA") for r in residues]
    matrix = pae[0]["predicted_aligned_error"]
    spec = {
        "source_type": "alphafold",
        "uniprot": accession,
        "chains": [c.name],
        "model_id": info["entryId"],
        "sequence_start": start,
        "sequence_end": end,
        "pocket": "p2rank",
        "altloc": None,
    }
    value = {
        "spec": spec,
        "audit": {"identity": [{"identity_check": "matched", "uniprot": accession}]},
        "file": file_record(root, folder / "model.cif", "source_original"),
        "confidence": {"plddt": scores, "pae": matrix},
        "sequence": sequence,
        "proposal_note_zh": "已发布预测模型；仅探索，不能代替必要复合物环境",
        "files": [
            file_record(root, p, "source_evidence")
            for p in folder.rglob("*")
            if p.is_file()
        ],
    }
    write_json(folder / "inspection.json", value)
    return value


def supplemental_candidates(root, metadata, folder, minimum_length=0):
    """从官方全量同身份检索补齐候选，不用先前按分辨率截取的小清单限制补救。"""
    from urllib.parse import quote

    nodes = [
        {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession",
                "operator": "exact_match",
                "value": metadata["uniprot"],
            },
        },
        {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "entity_poly.rcsb_mutation_count",
                "operator": "equals",
                "value": 0,
            },
        },
    ]
    if minimum_length:
        nodes.append(
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "entity_poly.rcsb_sample_sequence_length",
                    "operator": "greater",
                    "value": minimum_length,
                },
            }
        )
    query = {
        "query": {"type": "group", "logical_operator": "and", "nodes": nodes},
        "return_type": "polymer_entity",
        "request_options": {"paginate": {"start": 0, "rows": 40}},
    }
    response = json.loads(
        fetch(
            "https://search.rcsb.org/rcsbsearch/v2/query?json="
            + quote(json.dumps(query)),
            folder / "same_target_search.json",
        )
    )
    rows = []
    known = {c["pdb_id"] for c in metadata["candidates"]}
    for item in response.get("result_set", []):
        pdb, eid = item["identifier"].split("_")
        if pdb in known:
            continue
        entity = json.loads(
            fetch(
                "https://data.rcsb.org/rest/v1/core/polymer_entity/" + pdb + "/" + eid,
                folder / (pdb + "_" + eid + ".json"),
            )
        )
        species = {
            x.get("ncbi_taxonomy_id")
            for x in entity.get("rcsb_entity_source_organism", [])
        }
        if species != {9606}:
            continue
        identifiers = entity.get("rcsb_polymer_entity_container_identifiers", {})
        poly = entity["entity_poly"]
        if metadata["uniprot"] not in identifiers.get("uniprot_ids", []) or poly.get(
            "rcsb_conflict_count", 0
        ):
            continue
        rows.append(
            {
                "pdb_id": pdb,
                "target_chains": [
                    {
                        "length": poly["rcsb_sample_sequence_length"],
                        "mutation_count": 0,
                        "chains": identifiers["auth_asym_ids"],
                    }
                ],
                "ligands": [{"code": "待核对"}],
                "blocked_previous_failure": False,
            }
        )
        known.add(pdb)
    return rows


# 仅由本轮Workflow显式传入已索引来源，不能在磁盘搜索其他研究或旧项目。
_SOURCE_CACHE = {}


def source_cache(root, records):
    """按URL与原字节指纹复用已归档官方响应；准备输入和质控仍独立核对。"""
    global _SOURCE_CACHE
    from storage import verified_file

    indexed = {r["path"]: r for r in records}
    cached = {}
    for name, record in indexed.items():
        if not name.endswith(".source.json"):
            continue
        proof = json.loads(verified_file(root, record).read_text("utf-8"))
        raw_name = name[: -len(".source.json")]
        if raw_name not in indexed:
            continue
        raw_record = indexed[raw_name]
        require(raw_record["sha256"] == proof["sha256"], "来源缓存与已归档原件指纹不符")
        cached[proof["url"]] = (root, raw_record, record)
    _SOURCE_CACHE = cached
