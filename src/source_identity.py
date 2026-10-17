# 来源检索身份校验：仅标准库读取已上传文件内的检索标题，不访问其他研究。
import csv
import io
import re
import zipfile
from xml.etree import ElementTree as ET
from contracts import require

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def normal(term):
    """仅统一大小写、首尾空白及成对查询引号，不作疾病模糊匹配。"""
    value = str(term or "").strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value.casefold()


def embedded_query(item, data):
    """读取明确的GeneCards/OMIM标题；其他格式或无标题返回空，不猜疾病。"""
    fmt = item.get("format")
    if fmt == "genecards_csv":
        reader = csv.reader(io.StringIO(data.decode(item.get("encoding", "utf-8-sig"))))
        for index, row in enumerate(reader):
            if index >= 20:
                break
            if len(row) == 1 and row[0].startswith("GeneCards - GeneCards - Search results for "):
                return row[0].split("Search results for ", 1)[1].strip()
    if fmt in ("omim_xlsx", "omim_xlsx_v2"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            require(sum(x.file_size for x in archive.infolist()) <= 64 * 1024 * 1024, "OMIM工作簿解压体积超出核验容量，未接纳文件")
            shared = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared = ["".join(x.itertext()) for x in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", NS)]
            queries = set()
            for name in archive.namelist():
                if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
                    continue
                for _, row in ET.iterparse(io.BytesIO(archive.read(name)), events=("end",)):
                    if row.tag != "{" + NS["m"] + "}row":
                        continue
                    if int(row.get("r", "0")) > 50:
                        break
                    for cell in row.findall("m:c", NS):
                        value = cell.findtext("m:v", "", NS)
                        if cell.get("t") == "s":
                            value = shared[int(value)]
                        elif cell.get("t") == "inlineStr":
                            node = cell.find("m:is", NS)
                            value = "".join(node.itertext()) if node is not None else ""
                        match = re.fullmatch(r"Gene Map Search\s*-\s*['\"](.*)['\"]", value.strip())
                        if match:
                            queries.add(match.group(1))
                    row.clear()
            require(len(queries) <= 1, "OMIM文件含多个不同检索标题，请重新导出单次检索文件")
            return next(iter(queries), "")
    return ""


def identity_warning(a00, item, data):
    """给出现有归档警告；不替用户更改来源或疾病范围。"""
    query = embedded_query(item, data)
    if not query:
        return "", "文件未提供可识别检索标题，无法自动核对来源疾病；请结合原始条目核查。"
    official = a00.get("mesh_verification") or {}
    terms = {normal(x) for x in [official.get("preferred_term"), *official.get("entry_terms", []), a00.get("mesh_term")] if x}
    mismatch = normal(query) != normal(item.get("query")) and not ({normal(query), normal(item.get("query"))} <= terms)
    mismatch = mismatch or bool(terms and normal(query) not in terms)
    return query, ("来源检索身份不匹配：文件内为“" + query + "”，当前研究为“" + str(a00.get("mesh_term") or item.get("query")) + "”。请更换文件，不能按本病纳入。") if mismatch else ""


def validate_source_identity(a00, item, data):
    """新上传文件存在明确不匹配标题时拒绝，保持原研究版本。"""
    query, warning = identity_warning(a00, item, data)
    require(not query or not warning, warning)
