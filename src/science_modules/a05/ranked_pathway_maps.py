"""复用pathview生成当前A05两种排名的首位命中图，不重新计算ORA/BH。"""

from copy import deepcopy
import csv
from hashlib import sha256
import re
import shutil
import subprocess
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET

from contracts import require
from storage import file_record, now, write_json
from modulea.core.ranked_pathway_workflow import SEMANTICS


def download_source(pathway_id, kind, destination):
    """保存官方原始字节并记录下载证据；空文件或联网失败明确失败。"""
    require(re.fullmatch(r"hsa\d{5}", pathway_id) is not None, "当前仅支持人类KEGG标准编号")
    url = f"https://rest.kegg.jp/get/{pathway_id}/{kind}"
    request = urllib.request.Request(url, headers={"User-Agent": "ModuleA-ranked-pathway-maps/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read(10_000_001)
    require(0 < len(raw) <= 10_000_000, "KEGG图源为空或超过10MB")
    if kind == "kgml":
        require(ET.fromstring(raw).tag == "pathway", "KEGG返回的KGML不是通路结构")
    else:
        require(raw.startswith(b"\x89PNG\r\n\x1a\n"), "KEGG返回的底图不是PNG")
    with destination.open("xb") as stream:
        stream.write(raw)
    return {
        "url": url,
        "file": destination.name,
        "sha256": sha256(raw).hexdigest(),
        "retrieved_at": now(),
    }


def generate_ranked_maps(workflow, study_id, expected_a05, rscript, progress=None):
    """新目录制作并锁内发布；失败草案保留，已归档同源图件直接复用。"""
    manifest, binding, facts = workflow.ranked_map_source(study_id, expected_a05)
    old = workflow.ranked_maps_for(manifest, expected_a05)
    if old:
        return old
    require(facts, "当前确认范围没有显著KEGG通路，不补图")
    require(Path(rscript).is_file(), "未配置有效Rscript程序")
    folder = workflow.ranked_map_workspace(study_id, expected_a05)
    script = Path(__file__).with_name("ranked_pathway_maps.R")
    shutil.copyfile(script, folder / script.name)
    unique = {}
    for item in facts:
        unique.setdefault(item["id"], deepcopy(item))
    for index, item in enumerate(unique.values(), 1):
        pid = item["id"]
        item["sources"] = [
            download_source(pid, kind, folder / (pid + suffix))
            for kind, suffix in (("kgml", ".xml"), ("image", ".png"))
        ]
        xml_ids = {
            name.removeprefix("hsa:")
            for entry in ET.parse(folder / (pid + ".xml")).getroot().findall("entry")
            if entry.get("type") == "gene"
            for name in entry.get("name", "").split()
        }
        item["not_in_current_kgml"] = sorted(set(item["entrez_ids"]) - xml_ids)
        with (folder / (pid + "_hit_genes.tsv")).open("x", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t")
            writer.writerow(["entrez_id", "symbol", "present_in_current_kgml"])
            writer.writerows(
                (g, symbol, g in xml_ids) for g, symbol in zip(item["entrez_ids"], item["symbols"])
            )
        if progress:
            progress(index, len(unique) + 1, "已保存KEGG官方原件和命中身份")
    write_json(
        folder / "map_input.json",
        {"binding": binding, "semantics_zh": SEMANTICS, "pathways": list(unique.values())},
    )
    process = subprocess.run(
        [str(rscript), "--vanilla", script.name, "map_input.json", "."],
        cwd=folder,
        capture_output=True,
        timeout=360,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    (folder / "pathview_stdout.txt").write_bytes(process.stdout)
    (folder / "pathview_stderr.txt").write_bytes(process.stderr)
    require(
        process.returncode == 0,
        "pathview出图失败：" + process.stderr.decode("utf-8", errors="replace")[-1800:],
    )
    root = workflow.location(study_id)
    files = [
        file_record(root, path, "ranked_pathway_evidence")
        for path in sorted(folder.iterdir())
        if path.is_file()
    ]
    by_name = {Path(r["path"]).name: r for r in files}
    for item in unique.values():
        for source in item["sources"]:
            require(
                by_name[source["file"]]["sha256"] == source["sha256"], "KEGG原件字节在制作期间改变"
            )
    items = []
    for fact in facts:
        item = dict(
            fact,
            sources=unique[fact["id"]]["sources"],
            not_in_current_kgml=unique[fact["id"]]["not_in_current_kgml"],
        )
        pid = item["id"]
        require(
            pid + ".ranked.png" in by_name and pid + "_node_mapping.tsv" in by_name,
            "pathview缺少成品图或节点映射",
        )
        item["png"] = by_name[pid + ".ranked.png"]
        item["node_mapping"] = by_name[pid + "_node_mapping.tsv"]
        label = (
            "统计显著性首位" if item["ranking"] == "statistical_significance" else "命中基因数首位"
        )
        item["caption_zh"] = (
            f"KEGG{label}：{item['name_zh']}（{item['name_en']}，{pid}），Count={item['count']}，BH校正后P值={float(item['adjusted_p']):.3e}。"
            + SEMANTICS
        )
        if item["not_in_current_kgml"]:
            item["caption_zh"] += (
                f"本次命中中{len(item['not_in_current_kgml'])}个Entrez编号未出现在当前官方KGML，缺口按原编号归档。"
            )
        items.append(item)
    result = workflow.publish_ranked_maps(study_id, expected_a05, binding, items, files)
    if progress:
        progress(len(unique) + 1, len(unique) + 1, "两种排名首位命中通路图已归档")
    return result
