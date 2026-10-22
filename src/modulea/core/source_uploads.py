"""分库上传的展示与模板；仅使用标准库，科学解析留给后台任务。"""
from __future__ import annotations

import io
import json
import zipfile
from xml.sax.saxutils import escape
from disease import FORMATS
from storage import read_json, verified_file
from .source_catalog import source_databases, SOURCE_LABELS

A02_FORMATS = {
    "GeneCards": ("genecards_csv", "detailed_txt", "tsv"),
    "OMIM": ("omim_xlsx_v2", "omim_xlsx", "omim", "tsv"),
    "TTD": ("ttd_snapshot", "detailed_txt", "tsv"),
    "PharmGKB": ("pharmgkb_api", "detailed_txt", "tsv"),
    "OTP": ("otp_api", "tsv"),
    "DisGeNET": ("tsv", "names", "disgenet_legacy"),
}
TSV = "raw_symbol\traw_id\traw_score\tscore_name\tdisease_term\tdisease_id\trelation_type\n"
DETAILED = "raw_symbol\tdisease_term\traw_id\tdisease_id\ttarget_name\traw_uniprot\traw_score\tscore_name\tclinical_status\trelation_type\tsource_record_id\tevidence_url\n"
OMIM = "Approved Symbol\tPhenotype\tPhenotype MIM number\tEntrez Gene ID\n"
A01_HINTS = {
    "TCMSP": "ZIP内放当前完整处方的references/tcmsp_snapshot.tsv，保留原OB/DL、物种及靶点字段；不覆盖共享快照。",
    "HERB": "ZIP内放官方成分身份总表、各药味.xlsx、完整靶点命名表和成分已有关系详情；模板说明药味绑定方式。",
    "BATMAN": "ZIP内放官方药味成分总表及known_target_proteins压缩关系表；按官方拼音条目绑定药味，不导入预测表。",
}

# 同一格式列表用于展示、模板下载及请求校验，避免前后端各自猜格式。
def formats(module_id, database):
    return ("source_zip",) if module_id == "A01" and database in A01_HINTS else A02_FORMATS.get(database, ())

# 上传清单与原始文件都来自当前研究；没有绑定到当前A00的旧清单仅显示为过期。
def staging(workflow, manifest):
    record = manifest.get("current_component_uploads")
    return read_json(verified_file(workflow.location(manifest["study_id"]), record)) if record else None

# 构造真实资料状态及可用操作，历史、回收站和活动任务均禁止写入。
def context(workflow, manifest, module_id, result, historical=False, active=False):
    if module_id not in ("A01", "A02"):
        return None
    sid = manifest["study_id"]
    a00 = manifest["current"].get("A00", "")
    enabled = not historical and not manifest.get("trashed") and not active and bool(a00) and workflow.approved(manifest, a00)
    reason = "历史版本只读" if historical else ("研究在回收站中，只读" if manifest.get("trashed") else ("当前研究已有后台任务，请等待完成" if active else ("请先复核通过A00研究登记" if not enabled else "")))
    current = staging(workflow, manifest) if module_id == "A01" else None
    valid = bool(current and current.get("a00_run_id") == a00)
    uploaded = {item["database"]: item for item in current.get("datasets", [])} if valid else {}
    current_a01 = manifest["current"].get("A01")
    processed = bool(valid and current_a01 and (workflow.run(manifest, current_a01).get("inputs", {}).get("staging_file") or {}).get("sha256") == (manifest.get("current_component_uploads") or {}).get("sha256"))
    rows = ((result or {}).get("tables") or {}).get("source_summary") or []
    states = {r["database"]: r for r in rows}
    databases = ["TCMSP", "HERB", "BATMAN"] if module_id == "A01" else source_databases(module_id, manifest, result)
    available_sources = {}
    if module_id == "A02" and result:
        record = next((r for r in result.get("sources", []) if r.get("role") == "source_manifest"), None)
        if record:
            available_sources = {r["database"]: r for r in read_json(verified_file(workflow.location(sid), record)).get("datasets", [])}
    sources = []
    for database in databases:
        item = uploaded.get(database) if module_id == "A01" else available_sources.get(database)
        options = []
        for fmt in formats(module_id, database):
            if fmt == "omim_xlsx":  # 旧接口继续接收，网页只列新版。
                continue
            accept = ".zip" if fmt == "source_zip" else (".xlsx" if fmt in ("omim_xlsx", "omim_xlsx_v2") else (".json" if fmt.endswith("api") or fmt.endswith("snapshot") or fmt.endswith("legacy") else (".csv" if fmt == "genecards_csv" else ".txt,.tsv")))
            options.append({"value": fmt, "label_zh": "官方原始资料ZIP（按模板包装）" if fmt == "source_zip" else FORMATS[fmt], "accept": accept,
                            "template_url": f"/api/v1/studies/{sid}/modules/{module_id}/sources/{database}/template?format={fmt}"})
        if module_id == "A01":
            status = ("资料已进入当前A01版本，复核状态见结果" if processed else "已上传，待整理；尚未进入当前结果") if item else ("旧上传绑定已过期，请重新上传" if current and not valid else "尚未上传；已有归档结果不自动作为新上传包")
        else:
            row = states.get(database)
            status = row.get("availability", "尚未提供资料") if row else "尚未提供资料"
            if row and (item or {}).get("source_status") != "query_failed":
                status += "；归档候选记录 " + str(row.get("records", "—")) + " 条"
        sources.append({"database": database, "label_zh": SOURCE_LABELS.get(database, database), "status_zh": status,
                        "can_retry": bool(enabled and module_id == "A02" and database in ("OTP", "TTD", "PharmGKB") and (item or {}).get("source_status") == "query_failed"),
                        "formats": options, "hint_zh": ("支持Gene Symbol旧格式及Symbol/Name/Type/Relevance Score/Knowledge搜索导出；保留标题和版权说明即可，无需手动改列名。" if database == "GeneCards" else A01_HINTS.get(database, "按所选格式解析，原始评分、疾病条目及文件字节保留；不新增筛选阈值。")),
                        "uploaded_name": (item or {}).get("name"), "sha256": ((item or {}).get("source_record") or {}).get("sha256"),
                        "download_url": f"/api/v1/studies/{sid}/modules/{module_id}/sources/{database}/file" if item else None})
    complete = valid and set(uploaded) == {"TCMSP", "HERB", "BATMAN"}
    a02 = manifest["current"].get("A02")
    mapping_available = bool(a02 and workflow.run(manifest, a02).get("inputs", {}).get("mapping_file")) or (workflow.root / "references/hgnc_complete_set_20260913.json").is_file()
    can_process = module_id == "A01" and enabled and complete and mapping_available and not processed
    from .source_previews import latest
    acquisition = {"enabled": enabled, "databases": [db for db in databases if db not in uploaded],
                   "latest": latest(workflow, manifest, "acquisition")} if module_id == "A01" else None
    verification = None
    if module_id == "A01" and (result or {}).get("summary", {}).get("component_source_profile") == "A01.multisource.collect.1":
        verification = {"enabled": enabled and processed, "version": "A01.multisource.collect.1",
                        "coverage": (result or {}).get("tables", {}).get("source_coverage", []),
                        "issues_count": (result or {}).get("summary", {}).get("未决身份组数", 0)}
    mapping_preview = {"enabled": enabled, "latest": latest(workflow, manifest, "mapping")} if module_id == "A02" else None
    return {"enabled": enabled, "disabled_reason_zh": reason, "expected_a00": a00,
            "acquisition": acquisition, "verification": verification, "mapping_preview": mapping_preview,
            "expected_run": manifest["current"].get(module_id, ""), "expected_staging": (manifest.get("current_component_uploads") or {}).get("sha256", "") if module_id == "A01" else "",
            "note_zh": "三库按库上传留存；完整来源与共同HGNC依据齐备后，点击整理生成新的待复核结果。上传本身不改变当前A01。" if module_id == "A01" else "每次上传只替换所选库，生成新的A02候选；范围、身份与总体复核仍按原流程确认。",
            "can_process": can_process, "process_reason_zh": "" if can_process else ("本批资料已整理，可核查当前结果；补充或替换后再整理" if processed else ("请先上传完整三库资料" if not complete else "尚无共同HGNC依据，请先准备身份快照或完成A02标准化")),
            "query_zh": ((workflow.result(manifest, a00) or {}).get("summary", {}).get("herbs", "") if module_id == "A01" else (workflow.result(manifest, a00) or {}).get("summary", {}).get("mesh_verification", {}).get("preferred_term", "")) if a00 else "",
            "sources": sources}

# 下载字段模板或包装规范，不填入虚构科学记录。
def template(module_id, database, fmt, herbs):
    if fmt == "source_zip":
        value = {"version": "A01.source_package.1", "database": database, "herbs": herbs}
        members = {}
        if database == "TCMSP":
            value["encoding"] = "utf-8-sig"
            members["references/tcmsp_snapshot.tsv"] = "Chinesename\tMOLID\tmoleculename\tob\tdl\tUniProtAC\tGeneNames\tOrganism\n"
        elif database == "HERB":
            value["herb_files"] = {h: f"herb_{i + 1}.xlsx" for i, h in enumerate(herbs)}
            members["HERB_ingredient_info_v2.txt"] = "Ingredient_id\tIngredient_name\tIngredient_alias_name\tInChIKey\tMolecular_formula\tTCMSP_id\tPubChem_id\n"
        else:
            value["herb_names"] = {f"填写官方拼音条目{i + 1}": h for i, h in enumerate(herbs)}
            members["BATMAN_herb_browse.txt"] = "Pinyin.Name\tChinese.Name\tLatin.Name\tIngredients\n"
        members["modulea_source.json"] = json.dumps(value, ensure_ascii=False, indent=2)
        members["上传包装说明.txt"] = ("这只是包装模板，必须替换为真实官方资料，不可直接作为研究数据上传。\n" + A01_HINTS[database] + "\n"
            "HERB还需HERB_target_browse_page001.json完整命名表及HERB_existing_details/HBIN编号.json详情；工作簿前两列表头为Ingredient id和Ingredient name。\n"
            "BATMAN还需BATMAN_known_browse_by_ingredients.txt.gz，解压表含PubChem_CID、IUPAC_name、known_target_proteins；可选PubChem快照按现有复用清单一起包装。\n"
            "同一库包装当前处方全部药味，药味及顺序必须与本研究登记一致。\n")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, text in members.items():
                archive.writestr(name, text.encode("utf-8"))
        return stream.getvalue(), database + "_来源包装模板.zip", "application/zip"
    if fmt in ("omim_xlsx", "omim_xlsx_v2"):
        headers = OMIM.strip().split("\t")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
            archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
            archive.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Gene Map" sheetId="1" r:id="rId1"/></sheets></workbook>')
            archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
            cells = ''.join(f'<c r="{chr(65 + i)}1" t="inlineStr"><is><t>{escape(h)}</t></is></c>' for i, h in enumerate(headers))
            archive.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">' + cells + '</row></sheetData></worksheet>')
        return stream.getvalue(), "OMIM_字段模板.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if fmt == "genecards_csv":
        text = "Gene Symbol,Relevance score,GC Id,Uniprot ID,Category,Description,GeneCards Link\n"
    elif fmt == "omim":
        text = OMIM
    elif fmt == "detailed_txt":
        text = DETAILED
    elif fmt == "tsv":
        text = TSV
    else:
        text = "请提供该库真实原始资料，不要用空示例代替查询。\n" + ("逐行填写实际原始基因标识，缺评分不会补零。" if fmt == "names" else "JSON快照沿用现有适配器格式，保留完整原始响应、疾病身份、查询信息及记录，不接收自行拼写的零结果。")
    return text.encode("utf-8-sig"), database + ("_字段模板.csv" if fmt == "genecards_csv" else "_格式说明.txt" if fmt not in ("omim", "tsv", "detailed_txt") else "_字段模板.tsv"), "text/plain; charset=utf-8"
