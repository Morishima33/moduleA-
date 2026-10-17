# OMIM Excel新解析分支：保留基因/表型原行，官方页尾说明不构成候选。
import io
from contracts import require


def parse_excel(data):
    """只在后台使用openpyxl；旧omim_xlsx分支继续保留历史行为。"""
    from openpyxl import load_workbook
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        headers = []
        required = {"Approved Symbol", "Phenotype", "Phenotype MIM number"}
        for sheet in workbook:
            for number, values in enumerate(sheet.iter_rows(max_row=min(sheet.max_row or 50, 50), values_only=True), 1):
                labels = [str(x).strip() if x is not None else "" for x in values]
                if required <= set(labels):
                    headers.append((sheet, number, labels))
        require(len(headers) == 1, "OMIM Excel须且只能有一个合法表头")
        sheet, header, labels = headers[0]
        nonempty = [x for x in labels if x]
        require(len(nonempty) == len(set(nonempty)), "OMIM Excel存在重复表头")
        entries, footer = [], False
        fields = ("Gene/Locus", "Gene/Locus name", "Gene/Locus MIM number", "Approved Symbol", "Entrez Gene ID", "Ensembl Gene ID", "Phenotype", "Phenotype MIM number")
        for number, values in enumerate(sheet.iter_rows(min_row=header + 1, values_only=True), header + 1):
            if not any(x not in (None, "") for x in values):
                continue
            row = {labels[i]: x for i, x in enumerate(values) if i < len(labels) and labels[i]}
            if values[0] in ("Phenotype Mapping Key", "Inheritance Abbreviations") and not any(x not in (None, "") for x in values[1:]):
                footer = True
                continue
            has_data = any(row.get(key) not in (None, "") for key in fields)
            require(not footer or not has_data, "OMIM说明区后出现基因或表型数据：" + sheet.title + "!" + str(number))
            if footer:
                continue
            require(has_data, "OMIM非数据行未识别：" + sheet.title + "!" + str(number))
            entries.append({"raw_symbol": row.get("Approved Symbol") or "", "raw_id": row.get("Entrez Gene ID") or "", "disease_term": row.get("Phenotype") or "", "disease_id": row.get("Phenotype MIM number") or "", "source_row": sheet.title + "!" + str(number), "relation_type": "Gene Map Excel表型行"})
        return entries
    finally:
        workbook.close()
