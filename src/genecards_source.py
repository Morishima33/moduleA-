# GeneCards搜索页CSV适配：仅识别明确表头和导出说明，保留原评分与物理行号。
import csv
import io
import math
from contracts import require, ContractError

HEADER = ["Symbol", "Name", "Type", "Relevance Score", "Knowledge"]
COPYRIGHT = "Copyright LifeMap Sciences Inc. May not be used for any non-academic research purpose without explicit written permission from LifeMap Sciences."


def parse_search_export(text):
    """读取搜索导出格式；未知行或损坏行明确失败，不能跳行后发布半表。"""
    reader = csv.reader(io.StringIO(text), strict=True)
    entries, found, footer, previous = [], False, False, 0
    try:
        for row in reader:
            line, previous = previous + 1, reader.line_num
            if not row or not any(value.strip() for value in row):
                continue
            if not found:
                if [value.strip() for value in row] == HEADER:
                    found = True
                elif len(row) == 1 and (row[0].strip() == COPYRIGHT or row[0].strip().startswith("GeneCards - GeneCards - Search results for ")):
                    continue
                else:
                    raise ContractError("GeneCards CSV表头未识别：须为Gene Symbol/Relevance score等旧格式，或Symbol,Name,Type,Relevance Score,Knowledge；第" + str(line) + "行")
                continue
            if len(row) == 1 and row[0].strip() == COPYRIGHT:
                footer = True
                continue
            require(not footer, "GeneCards CSV版权尾注后仍有数据：第" + str(line) + "行")
            require(len(row) == len(HEADER), "GeneCards CSV行列不完整：第" + str(line) + "行")
            symbol, name, category, score, knowledge = row
            require(bool(symbol.strip()), "GeneCards CSV存在空基因名称：第" + str(line) + "行")
            try:
                valid = math.isfinite(float(score))
            except ValueError:
                valid = False
            require(valid, "GeneCards原始评分无效：第" + str(line) + "行")
            entries.append({"raw_symbol": symbol, "target_name": name, "gene_category": category,
                            "raw_score": score, "score_name": "GeneCards Relevance score", "knowledge": knowledge,
                            "source_row": line, "relation_type": "GeneCards搜索关联；非逐条实验确认的疾病致病证据"})
    except csv.Error as error:
        raise ContractError("GeneCards CSV格式损坏：第" + str(reader.line_num) + "行，请核对引号和分隔符") from error
    require(found, "GeneCards CSV缺少可识别表头：Symbol,Name,Type,Relevance Score,Knowledge")
    return entries
