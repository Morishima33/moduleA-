# A02先收集可追溯候选；未确定筛选规则时禁止交接为正式疾病集合。
import csv  # 解析明确指定格式的原始资料。
import hashlib  # 固定原始来源与条目身份。
import io  # 从上传字节读取，不访问用户提供的任意路径。
import json  # 读取数据库响应与历史快照。
import math  # 拒绝非有限的原始评分。
import re  # 检查标识格式，不用大小写转换冒充基因校准。
from collections import defaultdict  # 汇总各库原始候选与来源。
from pathlib import Path  # 定位当前项目内的共享资料。
from contracts import require, fingerprint  # 沿用统一错误与指纹。
from storage import read_json, write_json, file_record, verified_file, write_lock, now  # 使用同一归档和并发体系。
DATABASES = ("GeneCards", "OMIM", "TTD", "DisGeNET", "OTP")  # 默认五库保持不变，兼容COPD历史与既有模板。
SUPPORTED_DATABASES = DATABASES + ("PharmGKB",)  # 研究级方案可以启用PharmGKB，但不改默认组合。
SOURCE_PROFILES = {"A02.source_profile.default.1": DATABASES, "A02.source_profile.1": ("GeneCards", "OMIM", "TTD", "PharmGKB", "OTP"), "A02.source_profile.2": ("GeneCards", "OMIM", "TTD", "PharmGKB", "OTP"), "A02.source_profile.3": ("GeneCards", "OMIM", "TTD", "PharmGKB", "OTP")}  # v3增加流程测试缺库例外，历史方案保持不变。
PROFILE_STUDIES = {"A02.source_profile.1": {"study_3c0c6805cc5a47d0a1722160988df238"}}  # 本次例外只授权给明确研究。
FORMATS = {"omim_xlsx_v2": "OMIM Gene Map Excel（新版完整性校验，.xlsx）", "genecards_csv": "GeneCards官方搜索结果CSV", "ttd_snapshot": "TTD官方双文件原始快照", "names": "逐行标识名单（无分数）", "omim": "OMIM Gene Map TSV", "omim_xlsx": "OMIM Gene Map Excel（.xlsx）", "detailed_txt": "详细候选TXT（制表符分隔）", "otp_legacy": "Kimi OTP历史结果JSON", "disgenet_legacy": "Kimi DisGeNET对照JSON", "tsv": "通用候选TSV（保留原始评分）", "otp_api": "OTP直接关联API快照", "pharmgkb_api": "ClinPGx官方API精确疾病快照", "source_failure": "自动来源查询失败记录"}  # 详细TXT执行严格表头校验。
CONFIG = {"version": "A02.collect.2", "stage": "candidate_collection", "score_filter": None, "handoff_blocked": True}  # null表示尚未制定规则，不是score≥0。
SCOPES = {"pending": "待核验", "direct": "本病直接条目", "subtype": "疾病亚型（首版不纳入）", "outside": "不属于本研究范围"}  # 专业人员决定范围，不自动遍历纳入。
TABLE_LABELS = {"source_summary": "五库资料情况", "candidate_records": "原始候选与评分", "scope_groups": "疾病条目范围复核", "raw_union": "原始标识并集对照（非正式疾病集合）", "raw_reference": "原四库并集与OTP交集对照", "scope_history": "疾病范围复核留痕"}  # 不把候选写作正式靶点。
FIELD_LABELS = {"clinical_status": "原始临床状态", "target_name": "原始靶点名称", "raw_uniprot": "原始UniProt条目名", "source_record_id": "来源记录编号", "evidence_url": "证据网址", "database": "来源库", "record_id": "候选记录编号", "source_row": "源表行或记录号", "raw_symbol": "原始基因或靶点名称", "raw_id": "原始稳定标识", "raw_score": "原始评分", "score_name": "评分名称", "disease_term": "原始疾病或表型条目", "disease_id": "原始疾病编号", "scope_id": "范围条目编号", "scope": "范围复核决定", "identity_status": "身份核验提示", "records": "候选记录数", "distinct_raw_symbols": "不同原始名称数", "missing_score": "缺评分记录数", "availability": "资料情况", "sources": "来源库", "source_count": "收录库数（非独立实验数）", "reviewer": "复核人", "note": "理由及依据", "created_at": "保存时间（UTC）", "query": "检索词", "version": "数据库版本", "source_url": "来源说明", "retrieved_at": "获取日期", "format": "资料格式", "relation_type": "来源报告的关系范围"}  # 内部键固定，展示单独翻译。

def scope_policy(include_subtypes=False):  # 为后续亚型扩展保留明确参数接口。
    require(include_subtypes is False, "首版仅纳入本病；亚型扩展尚未启用")  # 当前不能通过改参数绕过授权范围。
    return {"version": "A02.scope.1", "include_subtypes": False, "included_scopes": ["direct"], "excluded_scopes": ["subtype", "outside"], "unresolved_scopes": ["pending"]}  # 科学范围与复核标签分离。

def scope_membership(scope, include_subtypes=False):  # 供疾病集合生产者调用统一范围判断。
    policy = scope_policy(include_subtypes)  # 使用固定版本政策。
    require(scope in SCOPES, "未知疾病范围标签")  # 不把未知状态视为排除。
    if scope in policy["unresolved_scopes"]:  # 待核验不能默认放入或删除。
        return None  # 调用方须处理未决问题再发布集合。
    return scope in policy["included_scopes"]  # 首版只有本病直接条目可纳入。

FIELD_LABELS.update(gene_category="GeneCards原始基因分类", gifts="GeneCards原始Gifts字段", query_quoted="检索词是否加引号", export_completeness="搜索结果导出完整性")  # 原生字段中文展示不改科学值。

def source_profile(version="A02.source_profile.default.1"):  # 返回经过校验的有序来源方案。
    require(version in SOURCE_PROFILES, "未知A02数据库方案")  # 不接受浏览器自造库名单。
    return {"version": version, "databases": list(SOURCE_PROFILES[version])}  # 保存版本和顺序供网页及复算使用。


def metadata(item):  # 校验和收紧单份上传资料的元信息。
    require(item.get("database") in SUPPORTED_DATABASES and item.get("format") in FORMATS, "请选择支持的数据库与文件格式")  # 不自动把未知格式当名单。
    require(item.get("encoding", "utf-8-sig") in ("utf-8-sig", "gbk"), "仅支持明确指定的UTF-8或GBK编码")  # 不忽略乱码。
    result = {key: str(item.get(key, "")).strip() for key in ("database", "format", "query", "retrieved_at", "version", "source_url", "name", "source_status")}  # 只保存已定义来源字段。
    require(all(0 < len(result[key]) <= 2000 for key in ("query", "retrieved_at", "version", "source_url")), "请填写检索词、获取日期、版本（可填未知）和来源说明")  # 缺来源不能假装可追溯。
    result.update({key: str(item.get(key, "unknown")).strip() for key in ("query_quoted", "export_completeness")})  # 完整性与引号状态据实留存，不默认全量。
    require(result["query_quoted"] in ("yes", "no", "unknown") and result["export_completeness"] in ("complete", "partial", "unknown"), "检索引号或导出完整性状态无效")  # 不接受含义不明的状态。
    result["encoding"] = item.get("encoding", "utf-8-sig")  # 保留原编码说明。
    return result  # 上传文件名只作说明，不用于磁盘路径。

def parse_source(meta, data):  # 所有获取方式进入同一候选解析函数。
    require(isinstance(data, bytes) and 0 < len(data) <= 16 * 1024 * 1024, "来源文件为空或超过16MB，请按数据库拆分")  # 大小是工程限制，不截断科研记录。
    fmt, db = meta["format"], meta["database"]  # 使用用户明确选择的适配器。
    require(fmt not in ("omim", "omim_xlsx", "omim_xlsx_v2", "otp_legacy", "otp_api", "disgenet_legacy", "pharmgkb_api") or db == {"omim": "OMIM", "omim_xlsx": "OMIM", "omim_xlsx_v2": "OMIM", "otp_legacy": "OTP", "otp_api": "OTP", "disgenet_legacy": "DisGeNET", "pharmgkb_api": "PharmGKB"}[fmt], "文件格式与数据库不匹配")  # 防止跨库误用。
    try:  # 文本编码错误要作为可处理的输入问题显示。
        text = "" if fmt in ("omim_xlsx", "omim_xlsx_v2") else data.decode(meta["encoding"], errors="strict")  # Excel按工作簿读取，文本仍严格解码。
    except UnicodeDecodeError as error:  # 不让乱码进入候选或只显示内部异常。
        raise ValueError("资料文件无法按所选编码读取；请确认UTF-8或GBK后重新上传") from error  # 用户可以直接修正编码。
    entries = []  # 中间条目保留原始名称、评分和疾病字段。
    if fmt == "source_failure":  # 自动获取失败只保存诊断，不生成伪零记录。
        value = json.loads(text)  # 诊断快照由固定采集器生成。
        require(value.get("database") == db and value.get("status") == "query_failed" and value.get("error"), "自动来源失败记录不完整")  # 不允许手写空来源冒充失败。
        entries = []  # 失败与有效空查询严格区分。
    elif fmt == "ttd_snapshot":  # 重新下载的TTD完整双文件来源。
        from ttd_source import parse_snapshot  # 适配器不读取Kimi。
        require(db == "TTD", "TTD快照不能用于其他数据库")  # 限定来源。
        entries, versions = parse_snapshot(json.loads(text))  # 保留真实文件头版本及证据。
    elif fmt == "names":  # 老名单没有评分，不能补0。
        entries = [{"raw_symbol": value.strip(), "source_row": index, "relation_type": "原名单未说明"} for index, value in enumerate(text.splitlines(), 1) if value.strip()]  # 空白分隔行不当靶点。
    elif fmt == "genecards_csv":  # 解析官方CSV，不要求用户手动换表头。
        require(db == "GeneCards", "GeneCards CSV只能用于GeneCards来源")  # 拒绝错库导入。
        reader = csv.DictReader(io.StringIO(text), strict=True)  # 使用官方逗号格式及严格引号解析。
        headers = [str(name).strip() for name in (reader.fieldnames or [])]  # 官方链接列可能带一个前导空格。
        if not {"Gene Symbol", "Relevance score", "GC Id", "Uniprot ID", "Category"} <= set(headers):
            from genecards_source import parse_search_export
            entries = parse_search_export(text)  # 搜索导出使用明确的新字段集，不补造稳定ID。
        else:  # 原格式和原定位规则保持。
            require(headers and len(headers) == len(set(headers)) and all(headers), "GeneCards CSV存在空表头或重复字段")  # 不任取重复列。
            reader.fieldnames = headers  # 后续以唯一原生字段名读取。
            try:  # 严格CSV语法错误需要给用户可处理提示。
                source_rows = list(reader)  # 完整解析成功后才进入候选，不发布半表。
            except csv.Error as error:  # 引号损坏不显示无法理解的内部错误。
                raise ValueError("GeneCards CSV格式损坏：请重新导出并检查引号与分隔符") from error  # 不猜测修复原文件。
            for index, row in enumerate(source_rows, 2):  # 所有行保留原始定位。
                require(None not in row and all(value is not None for value in row.values()), "GeneCards CSV行列不完整：第" + str(index) + "行")  # 不接纳截断或多余列。
                require(row["Gene Symbol"].strip(), "GeneCards CSV存在空基因名称：第" + str(index) + "行")  # 空符号不伪造记录。
                try:  # 只检查评分格式，不修改原始精度。
                    score = float(row["Relevance score"])  # 原始关联评分不是纳入阈值。
                except ValueError as error:  # 报告可定位的输入错误。
                    raise ValueError("GeneCards原始评分无效：第" + str(index) + "行") from error  # 不将缺评分补零。
                require(math.isfinite(score), "GeneCards原始评分必须为有限数值")  # 禁止NaN或无穷值。
                entries.append({"raw_symbol": row["Gene Symbol"], "raw_id": row["GC Id"], "raw_score": row["Relevance score"], "score_name": "GeneCards Relevance score", "raw_uniprot": row["Uniprot ID"], "gene_category": row["Category"], "target_name": row.get("Description", ""), "gifts": row.get("Gifts", ""), "evidence_url": row.get("GeneCards Link", ""), "source_row": index, "relation_type": "GeneCards搜索关联；非逐条实验确认的疾病致病证据"})  # 疾病词来自用户确认的实际检索元信息。
    elif fmt == "detailed_txt":  # 详细人工导出使用固定制表符和明确表头。
        require(db in ("GeneCards", "TTD", "PharmGKB"), "详细候选TXT仅用于GeneCards、TTD或PharmGKB")  # OMIM继续使用专用适配器。
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")  # 不依据文件后缀或内容猜分隔符。
        headers = reader.fieldnames or []  # 空文件没有合法表头。
        require(len(headers) == len(set(headers)), "详细候选TXT存在重复字段名，请修正表头")  # 重复含义列不能任取其一。
        require({"raw_symbol", "disease_term"} <= set(headers), "详细候选TXT须包含raw_symbol和disease_term字段")  # 两个必需字段缺一即停止。
        require(all(str(name).strip() == name and name for name in headers), "详细候选TXT表头不能留空或带首尾空格")  # 避免看似相同的字段混入。
        entries = [dict(row, source_row=index) for index, row in enumerate(reader, 2) if row and any(str(value or "").strip() for value in row.values())]  # 未知附加列只随原文件保留，不作推断。
    elif fmt == "omim":  # 表型行逐条保留，不将整张命中表自动归为COPD。
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")  # 按已知Gene Map字段读取。
        require({"Approved Symbol", "Phenotype", "Phenotype MIM number"} <= set(reader.fieldnames or []), "OMIM导出缺少基因或表型字段")  # 不猜列位置。
        entries = [{"raw_symbol": row["Approved Symbol"] or "", "raw_id": row.get("Entrez Gene ID", "") or "", "disease_term": row["Phenotype"] or "", "disease_id": row["Phenotype MIM number"] or "", "source_row": index, "relation_type": "Gene Map表型行"} for index, row in enumerate(reader, 2) if row]  # 缺标准符号的行也留存。
    elif fmt == "omim_xlsx_v2":
        require(str(meta.get("name", "")).lower().endswith(".xlsx"), "OMIM Excel只支持.xlsx")
        from omim_source_v2 import parse_excel
        entries = parse_excel(data)
    elif fmt == "omim_xlsx":  # Excel保持原工作簿字节，不经过文本编码转换。
        require(str(meta.get("name", "")).lower().endswith(".xlsx"), "OMIM Excel只支持.xlsx；旧.xls请先另存为.xlsx")  # 不用后缀不明文件猜格式。
        from openpyxl import load_workbook  # 使用项目已有依赖只读解析工作簿。
        try:  # 损坏文件给出明确输入错误。
            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)  # 不执行宏、不修改原文件。
        except Exception as error:  # openpyxl异常不暴露内部堆栈给使用者。
            raise ValueError("OMIM Excel无法读取或文件已损坏，请重新导出.xlsx") from error  # 不退回文本解码。
        required = {"Approved Symbol", "Phenotype", "Phenotype MIM number"}  # 唯一可接受的OMIM表头依据。
        matches = []  # 收集所有工作表前50行中的合法表头。
        for sheet in workbook.worksheets:  # 不凭工作表名称猜数据位置。
            for row_number, values in enumerate(sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 50), values_only=True), 1):
                labels = [str(value).strip() if value is not None else "" for value in values]  # 保留列顺序。
                if required <= set(labels):  # 只认包含全部必需列的表头。
                    matches.append((sheet, row_number, labels))  # 稍后要求全工作簿唯一。
        require(len(matches) == 1, "OMIM Excel须且只能有一个包含Approved Symbol、Phenotype、Phenotype MIM number的表头")  # 多处匹配也不任选。
        sheet, header_row, labels = matches[0]  # 唯一表头可以安全解析。
        entries = []  # 每一非空数据行完整保留为候选。
        for row_number, values in enumerate(sheet.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1):
            row = {labels[index]: value for index, value in enumerate(values) if index < len(labels) and labels[index]}  # 以原列名定位字段。
            if not any(value not in (None, "") for value in values):  # 纯空行不形成伪记录。
                continue
            entries.append({"raw_symbol": row.get("Approved Symbol", "") or "", "raw_id": row.get("Entrez Gene ID", "") or "", "disease_term": row.get("Phenotype", "") or "", "disease_id": row.get("Phenotype MIM number", "") or "", "source_row": sheet.title + "!" + str(row_number), "relation_type": "Gene Map Excel表型行"})  # 其余列仍保存在原工作簿中。
    elif fmt in ("otp_legacy", "disgenet_legacy"):  # 旧输出仅作为历史候选，不冒称新下载。
        value = json.loads(text)  # 不执行旧脚本或读取旧凭据。
        if fmt == "otp_legacy":  # 原OTP记录中有分数和Ensembl标识。
            require(isinstance(value.get("records"), list), "旧OTP文件没有records记录")  # 不用汇总数伪造明细。
            entries = [{"raw_symbol": row.get("symbol", ""), "raw_id": row.get("ensg", ""), "raw_score": row.get("score"), "score_name": "OTP association score", "disease_id": value.get("disease_id", ""), "source_row": index, "relation_type": "旧记录未区分直接/间接"} for index, row in enumerate(value["records"], 1)]  # 不按分数过滤任何已保存记录。
        else:  # DisGeNET这里只能从旧交叉表恢复已保存名单。
            cross = value.get("cross_check", {})  # 不读取OTP记录作为DisGeNET证据。
            require(cross.get("source") == "DisGeNET" and isinstance(cross.get("intersection"), list) and isinstance(cross.get("disgenet_only"), list), "旧文件缺少DisGeNET对照明细")  # 不从数量猜名单。
            symbols = sorted(set(cross["intersection"]) | set(cross["disgenet_only"]))  # 恢复旧对照文件能支持的候选集合。
            require(len(symbols) == cross.get("disgenet_count"), "DisGeNET旧对照数量不一致")  # 不掩盖旧文件损坏。
            entries = [{"raw_symbol": symbol, "source_row": index, "relation_type": "旧交叉对照恢复名单；原始评分与证据缺失"} for index, symbol in enumerate(symbols, 1)]  # 明确是派生名单。
    elif fmt == "otp_api":  # 在线采集器与上传快照使用相同解析方式。
        from disease_io import ENDPOINT, OTP_RELEASE_PROTOCOL, QUERY, otp_release, otp_release_label
        value = json.loads(text)  # 完整响应分页已经保存在这个快照中。
        require(value.get("enableIndirect") is False and isinstance(value.get("pages"), list), "OTP快照没有明确关闭间接关联")  # 不默许API默认范围。
        versioned = (value.get("collection_version") == OTP_RELEASE_PROTOCOL or "release" in value
                     or any("meta" in response.get("data", {}) for response in value["pages"]))
        if versioned:
            require(value.get("collection_version") == OTP_RELEASE_PROTOCOL and value["pages"],
                    "OTP版本化快照缺少正式协议或响应页")
            require(value.get("endpoint") == ENDPOINT and value.get("query") == QUERY,
                    "OTP版本化快照的官方接口或直接关联查询不一致")
            release = otp_release(value["pages"][0])
            require(value.get("release") == release and meta.get("version") == otp_release_label(release),
                    "OTP快照发布版本与来源登记不一致")
        unique, locations = {}, {}  # 相同稳定ID仅在内容完全一致时合并，原响应保留。
        for page_index, response in enumerate(value["pages"], 1):  # 逐页核查实际响应。
            require(not response.get("errors") and response.get("data", {}).get("disease"), "OTP响应不完整或含错误")  # 失败不是空集合。
            if versioned:
                require(otp_release(response) == release, "OTP原件包含不同发布版本的响应页")
            disease = response["data"]["disease"]  # 响应中的真实疾病。
            require(disease["id"] == value["disease_id"] and disease["associatedTargets"]["count"] == value["total"], "OTP返回疾病或总数不一致")  # 不拼接不同来源。
            for row_index, row in enumerate(disease["associatedTargets"]["rows"], 1):  # 保留每个候选的原始定位。
                key = row["target"]["id"]  # 按稳定标识去重，不按名称。
                require(key not in unique or unique[key] == row, "OTP同一稳定ID出现冲突内容")  # 不任取旧值或新值。
                unique[key] = row  # 原始重复行仍存在于来源JSON中。
                locations.setdefault(key, []).append(str(page_index) + ":" + str(row_index))  # 保存响应序号与页内记录号。
        require(len(unique) == value["total"], "OTP唯一标识数未达到接口总数，不能发布为完整候选")  # 不通过简单去重掩盖遗漏。
        entries = [{"raw_symbol": row["target"]["approvedSymbol"], "raw_id": key, "raw_score": row.get("score"), "score_name": "OTP association score", "disease_id": value["disease_id"], "disease_term": value["disease_name"], "source_row": ";".join(locations[key]), "relation_type": "API本病直接关联（研究范围仍待复核）"} for key, row in unique.items()]  # 所有定位及原分数保留，不筛分。
    elif fmt == "pharmgkb_api":  # ClinPGx只接收适配器保存的精确疾病结果。
        value = json.loads(text)  # 原查询词、响应和零结果原因均保存在快照。
        require(value.get("api") == "https://api.clinpgx.org/v1" and isinstance(value.get("official_terms"), list) and isinstance(value.get("records"), list), "ClinPGx快照结构不完整")  # 不接受手写简化JSON。
        require(value.get("status") in ("queried_zero_exact", "queried_exact"), "ClinPGx来源状态无效")  # 失败快照不能冒充零结果。
        disease = value.get("exact_disease") or {}  # 没有精确实体时记录集必须为空。
        require(disease or not value["records"], "ClinPGx无精确疾病实体时不能包含基因")  # 防止宽泛Rhinitis混入。
        entries = [{"raw_symbol": row.get("symbol", ""), "raw_id": row.get("id", ""), "disease_term": disease.get("name", ""), "disease_id": disease.get("id", ""), "source_row": index, "relation_type": "ClinPGx疾病直接连接基因：" + ";".join(map(str, row.get("connectionTypes", [])))} for index, row in enumerate(value["records"], 1)]  # 不经药物或变异间接扩展。
    else:  # 通用TSV用于其他疾病的带评分导入，不依赖COPD。
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")  # 格式明确，不从后缀猜测。
        require("raw_symbol" in (reader.fieldnames or []), "通用TSV须有raw_symbol列；请下载页面上的字段模板")  # 不把第一行数据误当表头。
        entries = [dict(row, source_row=index) for index, row in enumerate(reader, 2) if row]  # 原文件完整留存，未知列不作科学推断。
    require(len(entries) <= 100000, "候选记录超过单源处理上限，请联系维护者；未截断资料")  # 工程容量限制明确失败。
    digest = hashlib.sha256(data).hexdigest()  # 记录身份与原文件内容绑定。
    records = []  # 规范化只整理字段，不自动完成科学纳入。
    for entry in entries:  # 空基因和异常基因均可回查。
        symbol = str(entry.get("raw_symbol") or "").strip()  # 只去首尾空白，保留原大小写和别名。
        term, did = str(entry.get("disease_term", meta["query"]) or ""), str(entry.get("disease_id") or "")  # 原表存在疾病字段但为空时保持空缺，不用检索词冒充表型。
        hint = "原始标识待标准化核验" if symbol else "缺基因符号；保留原行待映射"  # 格式通过不是权威身份确认。
        if symbol and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", symbol):  # 可疑命名单列提示，但不武断删除。
            hint = "名称或多值字段待人工映射，未自动拆分"  # 例如p38 alpha不能直接改写。
        if symbol.casefold() == meta["query"].casefold():  # 匹配检索词只作为异常提示。
            hint = "与检索词相同，疑似表头或疾病位点，待核验"  # 不凭文本相同就永久删除。
        scope_id = fingerprint([db, digest, term, did])[:24]  # 相同来源及疾病条目复用同一范围决定。
        records.append({"record_id": fingerprint([db, digest, entry["source_row"]])[:24], "database": db, "source_row": entry["source_row"], "raw_symbol": symbol, "raw_id": str(entry.get("raw_id") or ""), "raw_score": entry.get("raw_score") if entry.get("raw_score") is not None else "", "score_name": str(entry.get("score_name") or ""), "disease_term": term, "disease_id": did, "scope_id": scope_id, "scope": "pending", "identity_status": hint, "relation_type": str(entry.get("relation_type") or "上传资料，范围待核验")})  # 原分数缺失保持空值。
        if fmt in ("ttd_snapshot", "detailed_txt", "genecards_csv"):  # 原生状态与身份字段也可在网页追溯。
            records[-1].update({key: str(entry.get(key) or "") for key in ("clinical_status", "target_name", "raw_uniprot", "source_record_id", "evidence_url", "gene_category", "gifts")})
            if "knowledge" in entry:
                records[-1]["knowledge"] = str(entry["knowledge"])  # 独立保留，不替代Gifts。  # 未知附加列仍只保存在原文件。
    return records  # 只返回候选，不返回正式疾病基因集合。

def organize(datasets, decisions, databases=DATABASES, profile_version="A02.source_profile.default.1"):  # 汇总当前研究启用的来源版本。
    require(tuple(databases) == SOURCE_PROFILES.get(profile_version), "A02数据库方案与版本不一致")  # 研究级例外不能漂移。
    records, source_rows = [], []  # 分别汇集候选行与五库资料状态。
    for db in databases:  # 缺库有明确状态，不能等同零靶点。
        item = next((item for item in datasets if item["database"] == db), None)  # 每库当前只采用明确选定的一份来源。
        rows = parse_source(item, item["data"]) if item else []  # 资料存在时解析，缺失不伪造来源。
        records.extend(rows)  # 重复证据行先保留供核验。
        availability = "尚未提供资料" if not item else ("查询失败，等待重试或上传" if item.get("source_status") == "query_failed" else ("已查询但0条精确记录" if not rows else "已有候选资料，待核验"))  # 失败、零结果和缺库三者分开。
        source_rows.append({"database": db, "availability": availability, "records": len(rows), "distinct_raw_symbols": len({r["raw_symbol"] for r in rows if r["raw_symbol"]}), "missing_score": sum(r["raw_score"] == "" for r in rows), "query": item["query"] if item else "", "version": item["version"] if item else "", "retrieved_at": item["retrieved_at"] if item else ""})  # 不把未采集和成功空集混淆。
    ids = {row["scope_id"] for row in records}  # 来源替换后旧范围决定不自动套用。
    applicable = [decision for decision in decisions if decision["scope_id"] in ids]  # 历史仍在旧运行，本版本只用当前来源的决定。
    current = {decision["scope_id"]: decision for decision in applicable}  # 按保存顺序确定最新范围意见。
    grouped, symbols = {}, defaultdict(set)  # 原始名称并集仅作核查对照。
    for row in records:  # 更新当前范围标签，原行不删除。
        row["scope"] = current.get(row["scope_id"], {}).get("scope", "pending")  # 未复核保持待定。
        group = grouped.setdefault(row["scope_id"], {key: row[key] for key in ("scope_id", "database", "disease_term", "disease_id", "scope")})  # 按源文件和表型分组。
        group["records"] = group.get("records", 0) + 1  # 明确范围决定影响多少行。
        if row["raw_symbol"]:  # 无名称记录仍在原始候选表中。
            symbols[row["raw_symbol"]].add(row["database"])  # 不做大写合并或未经确认的别名转换。
    union = [{"raw_symbol": symbol, "sources": ";".join(sorted(sources)), "source_count": len(sources)} for symbol, sources in sorted(symbols.items())]  # 未标准化候选并集，不作基因数。
    reference = [row for row in union if "OTP" in symbols[row["raw_symbol"]] and len(symbols[row["raw_symbol"]]) > 1]  # 原四库并集交OTP仅作原始名称对照。
    summary = {"资料阶段": "候选整理；评分规则与标准化尚待核定", "handoff_blocked": True, "source_profile": profile_version, "databases": list(databases), "已有来源库数": len([row for row in source_rows if row["availability"] in ("已有候选资料，待核验", "已查询但0条精确记录")]), "失败来源库数": len([row for row in source_rows if row["availability"] == "查询失败，等待重试或上传"]), "候选记录数": len(records), "不同原始名称数（非正式基因数）": len(union), "缺原始名称记录数": sum(not row["raw_symbol"] for row in records), "缺评分记录数": sum(row["raw_score"] == "" for row in records), "待范围复核条目数": sum(row["scope"] == "pending" for row in grouped.values()), "已记录范围意见条目数": len(current), "原始四库并集交OTP对照名称数": len(reference), "正式疾病主集合": "尚未生成，不供A03使用"}  # 查询失败不计为已有来源。
    tables = {"source_summary": source_rows, "candidate_records": records, "scope_groups": list(grouped.values()), "raw_union": union, "raw_reference": reference, "scope_history": applicable}  # 数量与网页采用同一事实。
    anomalies = ["本阶段未制定评分筛选规则，候选不得直接纳入A03。", "原始名称并集未做权威基因标准化；收录库数不是独立实验证据数。", "本病与亚型需逐条目复核；范围意见不替代基因身份及评分筛选。", "旧无分数名单与旧DisGeNET派生对照仅作历史资料，不能冒称完整原始下载。"]  # 明确所有候选结果边界。
    if any(row["availability"] == "查询失败，等待重试或上传" for row in source_rows):  # 失败必须在异常区突出。
        anomalies.append("存在自动来源查询失败；该状态不是0条记录，须重试或上传后才能完成A02。")  # 不允许其余来源掩盖失败。
    return summary, tables, anomalies  # 传给统一结果归档。

def validate_disease(run, summary, tables, anomalies, outcome):  # A02候选产物必须始终受交接门控。
    require(run["config"] == CONFIG and summary.get("handoff_blocked") is True, "A02候选不能伪装成正式疾病集合")  # 禁止调用者解除门控。
    require(set(tables) == set(TABLE_LABELS), "A02候选结果表不完整")  # 保证来源与原记录都有输出。
    rows = tables["candidate_records"]  # 逐条核对候选身份。
    require(len(rows) == summary["候选记录数"] and len({r["record_id"] for r in rows}) == len(rows), "A02候选记录数或身份重复")  # 不静默重复计数。
    require(all(r["database"] in summary.get("databases", DATABASES) and r["scope"] in SCOPES for r in rows), "A02来源或范围状态无效")  # 只接受该运行启用的来源。
    require(summary["不同原始名称数（非正式基因数）"] == len({r["raw_symbol"] for r in rows if r["raw_symbol"]}) == len(tables["raw_union"]), "A02原始名称数量不一致")  # 不把多个表的计数混用。
    require(outcome == ("success" if rows else "empty"), "A02候选空集状态错误")  # 空资料不伪装查询失败或反过来。

def legacy_sources(root):  # 显式导入项目内固定COPD历史快照，不读取Kimi目录。
    items = read_json(Path(root) / "references" / "disease_copd_sources.json")["datasets"]  # 清单包含真实来源版本。
    result = []  # 五库条目各有独立的来源说明。
    for item in items:  # 相同旧文件可分别提供OTP和派生DisGeNET资料。
        path = verified_file(Path(root) / "references", item)  # 逐个校验共享快照。
        result.append(dict(metadata(dict(item, name=path.name)), data=path.read_bytes()))  # 保留原字节，不自动标准化。
    return result  # 网页必须明确确认本研究为COPD后才可导入。

def run_disease(workflow, study_id, expected_a00, expected_a02, updates, reason, scope_change=None, profile_version=None):  # 获取、上传、范围复核共用一个版本入口。
    require(isinstance(reason, str) and reason.strip(), "请填写本次资料更新或复核原因")  # 每次版本变化可追溯。
    require(len({item["database"] for item in updates}) == len(updates), "一次更新不能提供同库多份竞争资料")  # 同库替换必须明确。
    with write_lock(workflow.root):  # 锁内固定上游、当前来源和复核决定。
        manifest = workflow.load(study_id)  # 不从页面缓存决定当前版本。
        require(not manifest.get("trashed", False), "研究在回收站中，请先恢复")  # 保持回收站只读。
        require(manifest["current"].get("A00") == expected_a00 and manifest["current"].get("A02", "") == expected_a02, "页面版本已改变，请刷新后重试")  # 阻止重复提交和旧页面覆盖。
        require(workflow.approved(manifest, expected_a00), "请先复核通过A00研究登记")  # 不依赖A01，疾病分支可独立整理。
        root, datasets, decisions, comparison_baseline = workflow.location(study_id), {}, [], None  # 每次只使用当前研究资料。
        selected_profile = source_profile(profile_version or "A02.source_profile.default.1")  # 新研究未指定时保持旧默认。
        if expected_a02 and workflow.active(manifest, expected_a02):  # 上游失效时不自动沿用旧来源和范围决定。
            prior_result = workflow.result(manifest, expected_a02)  # 先核查已有来源和结果完整性。
            prior = read_json(verified_file(root, next(record for record in prior_result["sources"] if record["role"] == "source_manifest")))  # 使用完整归档来源清单，不修改run快照。
            if profile_version is None:  # 普通更新沿用当前运行的研究级方案。
                selected_profile = source_profile(prior.get("source_profile", {}).get("version", "A02.source_profile.default.1"))  # 历史清单没有字段时仍是旧默认。
            for item in prior["datasets"]:  # 复用当前原始文件引用，不复制一套漂移的current文件。
                if item["database"] in selected_profile["databases"]:  # 切换方案时只移除不再启用的来源。
                    datasets[item["database"]] = dict(item, data=verified_file(root, item["source_record"]).read_bytes())  # 同一来源可回查原始归档。
            comparison_baseline = prior.get("comparison_baseline")  # 后续范围复核不丢失补库前基线。
            decisions = list(prior.get("scope_decisions", []))  # 保留此前范围意见的保存顺序。
            if prior.get("source_exception") and any(item.get("database") == "GeneCards" for item in updates):  # 补库后旧流程测试必须整体重算。
                comparison_baseline = {"a02_run_id": expected_a02, "source_exception": prior["source_exception"], **(prior.get("comparison_baseline") or {}), "current_runs": dict(manifest["current"]), "run_records": {key: dict(manifest["runs"][value]) for key, value in manifest["current"].items() if value in manifest["runs"]}}  # 旧的简版基线也补足完整模块指针。
        require(selected_profile["version"] == "A02.source_profile.default.1" or (selected_profile["version"] == "A02.source_profile.1" and study_id in PROFILE_STUDIES.get(selected_profile["version"], set())) or (selected_profile["version"] == "A02.source_profile.2" and manifest.get("workflow_profile") == "A00.preupload.1") or (selected_profile["version"] == "A02.source_profile.3" and manifest.get("workflow_profile") == "A00.preupload.2"), "当前研究未获授权使用此A02数据库方案")  # v3只用于显式用途的新研究。
        for item in updates:  # 新上传替换同库当前版本，旧运行不覆盖。
            require(item.get("database") in selected_profile["databases"], "当前研究数据库方案不包含此来源")  # 研究级例外不扩散到其他库。
            from source_identity import validate_source_identity
            validate_source_identity(workflow.result(manifest, expected_a00)["summary"], item, item["data"])  # 文件内检索词必须与本次研究绑定，错文件不得发布。
            datasets[item["database"]] = dict(metadata(item), data=item["data"])  # 清除旧源引用，准备归档新原始文件。
        require(bool(datasets), "尚无疾病资料，请先导入或上传")  # 没取到资料不能生成成功空查询。
        if scope_change:  # 支持单条兼容及全表一次提交。
            groups = organize(list(datasets.values()), decisions, selected_profile["databases"], selected_profile["version"])[1]["scope_groups"]  # 锁内核对完整当前条目。
            valid_ids = {g["scope_id"] for g in groups}  # 不接受其他研究或旧来源条目。
            batch = scope_change if isinstance(scope_change, list) else [scope_change]  # 保留原单条入口兼容性。
            ids = [change.get("scope_id") for change in batch]  # 校验重复及遗漏。
            require(len(ids) == len(set(ids)), "批次含重复范围条目")  # 防止重复决定覆盖。
            if isinstance(scope_change, list):  # 全表提交必须覆盖当前全部条目。
                require(set(ids) == valid_ids, "全表范围条目不完整或已改变，请刷新")  # 不把筛选后的局部当作全量。
            from source_identity import validate_source_identity
            for change in batch:  # CLI、旧网页和新网页同样禁止把错疾病来源纳入本病。
                if change.get("scope") == "direct":
                    require(change.get("scope_id") in valid_ids, "范围条目不属于当前研究")
                    group = next(g for g in groups if g["scope_id"] == change["scope_id"])
                    item = datasets[group["database"]]
                    validate_source_identity(workflow.result(manifest, expected_a00)["summary"], item, item["data"])
            timestamp = now()  # 同批决定共享保存时间。
            for change in batch:  # 全批校验完成前不发布任何运行。
                require(change.get("scope_id") in valid_ids and change.get("scope") in SCOPES, "范围条目或决定不合法")  # 检查合法决定。
                require(all(isinstance(change.get(key), str) and change[key].strip() for key in ("reviewer", "note")), "范围复核须填写复核人和依据")  # 人工身份与依据必填。
                decisions.append({key: change[key].strip() for key in ("scope_id", "scope", "reviewer", "note")} | {"created_at": timestamp})  # 每条留痕，一次产生新版本。
        summary, tables, anomalies = organize(list(datasets.values()), decisions, selected_profile["databases"], selected_profile["version"])  # 所有候选先完成解析检查。
        if comparison_baseline:  # 只提示真实发生的GeneCards补库。
            summary["补库前后稳定性比较"] = "等待A03、PPI、GO/KEGG及对接候选重新运行后生成"  # 当前A02阶段不能提前伪造下游差异。
            anomalies.append("GeneCards已补入；旧A03及下游自动失效，完成重算后比较疾病基因数、交集靶点、PPI前列基因、GO/KEGG方向和对接候选。")  # 明确后续动作。
        outcome = "success" if tables["candidate_records"] else "empty"  # 与正式疾病集合是否为空无关。
        validate_disease({"config": CONFIG}, summary, tables, anomalies, outcome)  # 写入前拒绝不完整结果。
        inputs = {"datasets": [{key: value for key, value in item.items() if key != "data"} | {"sha256": hashlib.sha256(item["data"]).hexdigest()} for item in datasets.values()], "scope_decisions": decisions, "previous_a02": expected_a02, "scope_policy": scope_policy(), "source_profile": selected_profile, "comparison_baseline": comparison_baseline}  # 固定来源、研究级方案与补库前比较基线。
        run = workflow._begin(manifest, "A02", inputs, dict(CONFIG), reason)  # 统一内核创建新版本。
        for index, item in enumerate(inputs["datasets"]):  # 只归档本次新上传字节，旧来源沿用其校验引用。
            if "source_record" not in item:  # 不重复复制旧原始资料。
                suffix = ".csv" if item["format"] == "genecards_csv" else (".txt" if item["format"] == "names" else (".xlsx" if item["format"] in ("omim_xlsx", "omim_xlsx_v2") else (".tsv" if item["format"] in ("omim", "tsv", "detailed_txt") else ".json")))  # 按明确格式保留原文件类型。
                path = root / "raw" / run["run_id"] / (item["database"].lower() + suffix)  # 路径只由数据库白名单和格式决定。
                path.parent.mkdir(parents=True, exist_ok=True)  # 新运行的原始资料目录。
                with path.open("xb") as stream:  # 不覆盖历史来源。
                    stream.write(datasets[item["database"]]["data"])  # 原样保存上传或API响应字节。
                item["source_record"] = file_record(root, path, "source")  # 新源记录只写入独立来源清单。
        source_path = root / "raw" / run["run_id"] / "disease_sources.json"  # 保存本次所有来源的完整引用。
        write_json(source_path, inputs)  # inputs原运行快照不覆盖，来源清单含实际归档引用。
        sources = [item["source_record"] for item in inputs["datasets"]] + [file_record(root, source_path, "source_manifest")]  # 所有原始文件均参与验证。
        result = workflow._finish(manifest, run["run_id"], summary, tables, anomalies, outcome, sources=sources)  # 发布候选及异常，不自动通过。
        workflow.save(manifest)  # 最后发布完整当前指针。
        return result  # 网页从磁盘读取已保存事实。

