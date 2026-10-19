"""将官方BRITE原件转为固定分类资料；更新须显式指定原件，不在页面访问时联网。"""
import argparse
import hashlib
import html
import json
import re
from datetime import date
from pathlib import Path


# 解析官方A/B/C层级，重复编号保留全部分类，防止跨分类信息被覆盖。
def parse(raw, snapshot_date):
    rows = {}
    category = subcategory = ""
    for line in raw.decode("utf-8").splitlines():
        if line.startswith("A"):
            category = html.unescape(re.sub("<[^>]*>", "", line[1:])).strip()
        elif line.startswith("B"):
            subcategory = html.unescape(re.sub("<[^>]*>", "", line[1:])).strip()
        elif line.startswith("C"):
            match = re.match(r"C\s+(\d{5})\s+(.+)", line)
            if match:
                number, name = match.groups()
                name = html.unescape(re.sub("<[^>]*>", "", name)).strip()
                rows.setdefault(number, []).append({"category": category, "subcategory": subcategory, "name": name})
    if not rows or not any(x["category"] == "Human Diseases" for values in rows.values() for x in values):
        raise ValueError("官方目录缺少通路或人类疾病分类")
    return {"schema_version": "KEGG.br08901.snapshot.1", "source_url": "https://www.kegg.jp/kegg/pathway.html", "download_url": "https://www.kegg.jp/kegg-bin/download_htext?htext=br08901.keg&format=htext&filedir=", "source_sha256": hashlib.sha256(raw).hexdigest(), "snapshot_date": date.fromisoformat(snapshot_date).isoformat(), "pathways": rows}


# 输出是可审阅的固定资料；不修改任何研究或人工决定。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-date", required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(parse(args.source.read_bytes(), args.snapshot_date), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
