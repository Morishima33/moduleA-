# 本文件提供仅供本机访问的网页，所有业务规则仍由统一内核执行。
from http.server import BaseHTTPRequestHandler, HTTPServer  # 标准库提供轻量本地网页服务。
from html import escape  # 防止输入文字被误当网页代码。
from urllib.parse import parse_qs, urlsplit, quote  # 解析网址和表单。
import json  # 输出接口数据和详细信息。
import secrets  # 为表单生成随机校验令牌。
from contracts import MODULES, ContractError, require  # 统一模块中文名称与错误处理。
from storage import read_json, verified_file  # 校验并读取归档内容。
from workflow import Workflow  # 网页调用同一个衔接内核。
from components import TABLE_LABELS, FIELD_LABELS, run_components, validate_components  # A01使用统一计算与中文标签。
from disease import TABLE_LABELS as DISEASE_TABLES, FIELD_LABELS as DISEASE_FIELDS, FORMATS as DISEASE_FORMATS, legacy_sources, run_disease, validate_disease  # 接入A02候选整理。
from normalization import TABLE_NAMES as NORMALIZATION_TABLES, FIELD_NAMES as NORMALIZATION_FIELDS, validator as normalization_validator, review_page as normalization_page, publish as publish_normalization  # 标准化预览与正式候选校验分开。
from ttd_source import fetch_ttd  # 从官方重新下载TTD完整资料。
from disease_io import multipart, fetch_otp  # 上传与官方读取使用明确入口。
from pharmgkb_source import fetch_pharmgkb  # ClinPGx只查询MeSH官方词的精确疾病实体。
from disease_ui import controls as disease_controls, detail_page as disease_page, COPD_NAMES  # A02中文页面不另建状态体系。

from intersection_flow import TABLE_LABELS as INTERSECTION_TABLES, FIELD_LABELS as INTERSECTION_FIELDS, run_intersection, run_selection, validate_intersection, validate_selection  # 接入A03计算与选择。
from ppi_flow import run_ppi, validator as ppi_validator  # A04来源和归档复算。
from enrichment_flow import run_enrichment, validator as enrichment_validator  # A05统一计算。
from enrichment_ui import controls as enrichment_controls, detail_page as enrichment_page, TABLES as ENRICHMENT_TABLES, FIELDS as ENRICHMENT_FIELDS  # 富集中文入口。
from docking_ui import preview_link as docking_preview_link, preview_page as docking_preview_page, load_preview as load_docking_preview  # 对接准备只读预览。
from docking_formal import prep_validator as docking_prep_validator, formal_validator as docking_formal_validator  # A06准备与正式结果使用专用校验。
from ppi_ui import controls as ppi_controls, TABLES as PPI_TABLES, FIELDS as PPI_FIELDS  # 中文PPI入口。
from intersection_ui import controls as intersection_controls, detail_page as intersection_page  # A03网页沿用统一卡片。
from report_dispatch import run_reports, validator as report_validator  # A07双报告只读取已批准上游。
from pathway_ui import card as pathway_card, review_page as pathway_page, figure_file as pathway_figure # 当前研究通路图、解释与人工审核。
from pathway_review import review_selection as review_pathway, request_recommendation # 只保存明确请求及人工决定。
from report_dispatch import publish_approved as publish_pathway_report # 认可后生成专业报告新修订。
from report_ui import TABLES as REPORT_TABLES, controls as report_controls, focus as report_focus  # A07网页突出结论复核与下载。
from docking_automation_ui import controls as docking_automation_controls, settings_page as docking_automation_page, submit as submit_docking_plan  # 原研究卡片接入通用自动化。
from docking_automation import start_job as start_docking_job  # 后台执行由统一入口启动。
from auto_continue import continue_after_review, message as auto_continue_message  # 通过后按既定规则自动运行到下一人工关口。
from mesh_identity import verify_mesh_identity  # 新研究保存前核对用户提供的MeSH标准词和编号。
from intake_sources import PROFILE as PREUPLOAD_PROFILE, COMPATIBLE_PROFILES as PREUPLOAD_PROFILES, current as current_staging, identity as staging_identity, stage as stage_intake_source  # A00暂存疾病来源但不提前生成A02。

LABELS = {"waiting": "等待上游资料", "ready": "可开始", "not_connected": "条件已满足，科学模块尚未接入", "running": "运行中或尚未完整提交", "stale": "上游已改变，本结果失效", "failed": "执行失败", "awaiting_review": "待复核", "approved": "已复核通过", "rejected": "已退回修改", "pending": "暂存待定"}  # 科研状态不使用模糊的“完成”。

def text(value):  # 所有用户文字进入网页前先安全转义。
    return escape("是" if value is True else "否" if value is False else "—" if value is None else str(value), quote=True)  # 引号和尖括号均按普通文字显示。

def hidden(name, value):  # 将当前版本编号带回提交接口。
    return '<input type="hidden" name="' + text(name) + '" value="' + text(value or "") + '">'  # 隐藏字段仍在服务端重新校验。

def page(title, body):  # 生成所有页面共用的简洁中文布局。
    head = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + text(title) + '</title>'  # 支持中文和窄屏。
    style = '<style>html,body{max-width:100%;overflow-x:hidden}body{font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;background:#f4f7f9;color:#203342;margin:0;overflow-x:hidden}main{max-width:1080px;margin:auto;padding:28px;box-sizing:border-box}section,article{min-width:0}h1{font-size:28px}h2{font-size:21px}a{color:#1a6180;overflow-wrap:anywhere}section,article{background:white;border:1px solid #d9e3e9;border-radius:12px;padding:22px;margin:18px 0}label{display:block;margin:12px 0}input,textarea,select{box-sizing:border-box;width:100%;padding:10px;border:1px solid #9eb2be;border-radius:6px;font:inherit}textarea{min-height:76px}button{background:#225f77;color:white;border:0;border-radius:6px;padding:10px 20px;font:inherit;cursor:pointer}summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f8;padding:12px;font-size:13px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #d9e3e9;padding:8px;text-align:left;overflow-wrap:anywhere}.muted{color:#526b7a}.tag{display:inline-block;padding:3px 12px;background:#e5eef3;border-radius:20px}.notice{border-left:5px solid #337f9e;padding:12px 18px;background:#edf5f8}.scroll{overflow:auto}</style>'  # 样式独立于数据和计算规则。
    return head + style + '<body><main><a href="/">Module A · 研究工作台</a><h1>' + text(title) + '</h1>' + body + '</main></body></html>'  # 页面只展示内核提供的事实。

def fields(values=None):  # 新建和修订使用同一组研究信息字段。
    values = dict(values or {})  # 新研究显示空表单，历史摘要复制后也不原地修改。
    values.setdefault("disease_scope", "仅本病，不纳入亚型")  # 使用用户已批准的首版范围，仍允许明确修改文字。
    labels = (("formula", "方剂名称"), ("herbs", "药味清单"), ("disease", "中文疾病名称"), ("mesh_term", "MeSH标准词（官方英文首选词）"), ("mesh_id", "MeSH编号（例如D029424）"), ("disease_scope", "研究范围"), ("operator", "登记人"))  # 用户直接提供标准词和编号，不由程序猜疾病。
    inputs = "".join('<label>' + title + '<input required maxlength="' + ("16" if name == "mesh_id" else "2000") + '" name="' + name + '" value="' + text(values.get(name, "")) + '"></label>' for name, title in labels)  # 新建和修订都要求完整身份。
    purpose = values.get("analysis_purpose", "formal_research")  # 新研究默认正式，流程测试必须明确选择。
    select = '<label>研究用途<select name="analysis_purpose"><option value="formal_research"' + (' selected' if purpose == 'formal_research' else '') + '>正式研究</option><option value="workflow_test"' + (' selected' if purpose == 'workflow_test' else '') + '>流程测试</option></select></label>'  # 用途不再由MeSH身份自动推断。
    return select + inputs + '<p class="notice"><strong>保存时自动核对：</strong>程序会确认MeSH标准词与编号在NLM官方记录中精确对应，保存官方返回、年度、时间和指纹。核对失败或网络不可用时不会创建研究。</p><p class="muted">研究物种：人类；首版研究范围填写“仅本病，不纳入亚型”。各数据库实际检索词和原生编号仍在A02分别留存。</p>'  # 清楚说明用户任务和系统责任。

def intake_source_controls(workflow, view, token):  # 在A00卡片提前准备人工来源。
    manifest = view["manifest"]  # 暂存入口绑定当前研究和A00版本。
    if manifest.get("workflow_profile") not in PREUPLOAD_PROFILES or manifest.get("trashed") or not manifest["current"].get("A00"):
        return ""  # 历史研究和回收站页面保持原样。
    if view["modules"][0]["state"] == "approved":  # A00通过后资料变化应形成新的A02版本。
        return '<p class="muted">A00预上传阶段已结束；后续补充或替换疾病资料请在A02卡片操作，以便立即形成可追溯的新A02版本。</p>'  # 避免暂存后未进入结果。
    a00_id = manifest["current"]["A00"]  # 文件只能绑定当前登记。
    a00 = view["modules"][0]["result"]["summary"]  # 当前登记已包含MeSH核对证据。
    staged = current_staging(workflow, manifest)  # 读取指纹已核验的当前暂存清单。
    valid = bool(staged and staged.get("a00_run_id") == a00_id and staged.get("identity_hash") == staging_identity(a00))  # 修订后旧资料不自动复用。
    datasets = {item["database"]: item for item in staged.get("datasets", [])} if valid else {}  # 只展示当前有效来源。
    base = hidden("token", token) + hidden("study", manifest["study_id"]) + hidden("expected_a00", a00_id)  # 服务端再次检查版本。
    body = '<section><h3>A00 · 疾病数据库资料准备</h3><p>四个人工资料入口同层显示。文件会立即校验并留存，但在A00通过前不会形成A02。流程测试可在明确签署来源例外后缺GeneCards继续；正式研究仍要求资料完整。</p><p><a href="/disease-detailed-template">下载GeneCards、TTD、PharmGKB详细TXT模板</a></p>'  # 说明预上传不等于科学纳入。
    if staged and not valid:  # 旧暂存资料仍保留但不能使用。
        body += '<p class="notice"><strong>原暂存资料属于旧A00版本，已停止自动使用。</strong>请按当前研究对象重新上传。</p>'  # 不提供静默复用按钮。
    specs = {"GeneCards": (("genecards_csv", "detailed_txt"), "支持官方搜索结果CSV或详细TXT；评分原样保留，不新增阈值。"), "OMIM": (("omim_xlsx", "omim"), "支持OMIM Gene Map .xlsx或TSV。"), "TTD": (("detailed_txt",), "可上传人工检索的详细TXT；已上传时跳过自动查询。"), "PharmGKB": (("detailed_txt",), "可上传人工检索的详细TXT；已上传时跳过自动查询。") }  # 两个上传阶段共用解析器，不更改来源规则。
    for database, (formats, hint) in specs.items():  # 四个来源使用相同暂存契约。
        item = datasets.get(database)  # 当前A00已暂存状态。
        status = "已暂存：" + item["name"] + "；" + item["staged_at"] if item else "尚未暂存"  # 不把缺文件说成零结果。
        body += '<article><p><strong>' + database + '：' + text(status) + '</strong><br>' + hint + '</p><form method="post" enctype="multipart/form-data" action="/intake-source-upload">' + base + hidden("database", database)  # 每次只替换一个来源。
        body += '<label>文件格式<select name="format">' + ''.join('<option value="' + fmt + '">' + text(DISEASE_FORMATS[fmt]) + '</option>' for fmt in formats) + '</select></label><label>文件编码<select name="encoding"><option value="utf-8-sig">UTF-8</option><option value="gbk">GBK</option></select></label><label>资料文件<input type="file" name="upload" required></label>'  # Excel不会经过文本解码。
        if database == 'GeneCards':  # 记录真实检索语法与导出完整性。
            body += '<label>检索词是否加引号<select name="query_quoted"><option value="unknown">不确定</option><option value="no">未加引号</option><option value="yes">加引号</option></select></label><label>导出是否包含本次全部搜索结果<select name="export_completeness"><option value="unknown">不确定</option><option value="complete">已核对为全部搜索结果</option><option value="partial">仅部分搜索结果</option></select></label>'  # 未知不能自动标为全量。
        body += '<label>实际检索词<input name="query" required maxlength="2000" value="' + text(a00["mesh_verification"]["preferred_term"]) + '"></label><label>资料获取日期<input name="retrieved_at" required maxlength="2000"></label><label>数据库版本（未知填未知）<input name="version" required maxlength="2000"></label><label><input style="width:auto" type="checkbox" name="confirmed" value="yes" required>确认文件属于当前研究对象</label><button>暂存并校验' + database + '</button></form>'  # 来源地址和首次/替换原因由后台记录。
        body += '</article>'  # 四个入口视觉层级一致。
    missing = [database for database in ("GeneCards", "OMIM", "TTD", "PharmGKB") if database not in datasets]  # 缺口不阻止A00。
    body += '<p class="notice">' + ('尚未上传：' + '、'.join(missing) + '。TTD和PharmGKB未上传时将自动查询；GeneCards缺失只能按流程测试例外继续。' if missing else '四个人工来源均已暂存；A00通过后将与Open Targets一起生成A02。') + '</p><p>Open Targets始终在A00通过后自动获取；单库失败会显示失败状态，不会写成0条。</p></section>'  # 给出下一步影响。
    return body  # 保持在原A00卡片内。

def a01_a02_review_form(view, token):  # 原卡片不变，只合并两项复核提交。
    manifest = view["manifest"]  # 表单绑定当前两项运行。
    items = {item["module_id"]: item for item in view["modules"] if item["module_id"] in ("A01", "A02")}  # 只处理两个并行模块。
    if manifest.get("trashed") or any(not items.get(module) or not items[module].get("result") or items[module]["state"] in ("stale", "failed") for module in ("A01", "A02")):
        return ""  # 两项尚未形成时沿用各自状态提示，不显示半张表单。
    if all(items[module]["state"] == "approved" for module in ("A01", "A02")):
        return ""  # 两项已通过后由A03承接，不重复审核。
    body = '<section><h2>A01与A02一次复核</h2><p>两个模块仍分别形成决定。复核人只填一次，意见分别填写；两项都通过后系统自动生成A03。</p><form method="post" action="/review-a01-a02">' + hidden("token", token) + hidden("study", manifest["study_id"])  # 一个请求保存两条独立记录。
    body += '<label>本次复核人<input name="reviewer" required maxlength="200"></label>'  # 共用复核人。
    for module in ("A01", "A02"):  # 固定A01在前、A02在后。
        item = items[module]  # 读取当前运行与最近决定。
        review = item.get("review")  # 已通过项默认保留。
        body += hidden(module.lower() + "_run", item["run"]["run_id"]) + hidden(module.lower() + "_previous", review["review_id"] if review else "")  # 服务端执行双版本冲突检查。
        if item["state"] == "approved":  # 用户无需重复审核已通过模块。
            body += hidden(module.lower() + "_action", "preserve") + '<p><strong>' + module + '：保留现有“已复核通过”决定。</strong></p>'  # 不创建重复记录。
            continue
        body += hidden(module.lower() + "_action", "change") + '<h3>' + module + '决定</h3><label>' + module + '意见<textarea name="' + module.lower() + '_note" required maxlength="4000"></textarea></label><label>' + module + '决定<select name="' + module.lower() + '_decision"><option value="pending">暂存待定</option>'  # 每项意见独立。
        if not item["result"]["summary"].get("handoff_blocked", False):
            body += '<option value="approved">通过，允许下游使用</option>'  # A02缺库、失败或身份问题时不显示通过。
        body += '<option value="rejected">退回修改</option></select></label>'  # 允许两项选择不同决定。
    body += '<button>保存A01和A02复核决定</button></form></section>'  # 一次提交。
    return body  # 放在A02卡片之后，仍属于原研究页面。

def details(value):  # 用可展开区域显示实际保存的输入和参数。
    return '<pre>' + text(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre>'  # 文字转义后安全显示。

def information(value):  # 把常用研究和复核字段显示成中文，技术原文仍可展开。
    labels = {"formula": "方剂", "herbs": "药味", "disease": "中文疾病名称", "mesh_term": "MeSH标准词", "mesh_id": "MeSH编号", "mesh_verification": "NLM官方核对证据", "disease_scope": "研究范围", "analysis_purpose": "研究用途", "operator": "登记人", "species": "研究物种", "reviewer": "复核人", "note": "复核意见", "decision": "决定", "created_at": "记录时间（UTC）"}  # 中文字段名便于初学者理解。
    rows = []  # 收集可直接阅读的事实。
    for key, item in value.items():  # 摘要不由界面重新计算。
        if key in labels or any("\u4e00" <= char <= "\u9fff" for char in key):  # 已有中文科学摘要可直接阅读。
            display = ("已由NLM官方核对；" + str(item.get("mesh_year", "")) + "版；" + str(item.get("checked_at", ""))) if key == "mesh_verification" and isinstance(item, dict) else ("人类（9606）" if key == "species" else ({"approved": "通过", "rejected": "退回修改", "pending": "暂存待定"}.get(str(item), item) if key == "decision" else item))  # 核对证据在摘要中简写，完整响应留在追溯区。
            rows.append({"项目": labels.get(key, key), "内容": display})  # 保留对应关系。
    return (table(rows, ["项目", "内容"]) if rows else details(value)) + '<details><summary>展开原始字段与追溯信息</summary>' + details(value) + '</details>'  # 技术信息放在主动展开位置。

def table(rows, columns=None):  # 在网页显示结果明细，可指定中文展示列顺序。
    if not rows:  # 空表必须明确展示。
        return '<p>本表没有记录。</p>'  # 不把空表隐藏为“已完成”。
    columns = columns or sorted({key for row in rows for key in row})  # 明细默认稳定排序，摘要可先显示项目名称。
    header = '<tr>' + "".join('<th>' + text(key) + '</th>' for key in columns) + '</tr>'  # 输出列标题。
    body = "".join('<tr>' + "".join('<td>' + text(row.get(key, "")) + '</td>' for key in columns) + '</tr>' for row in rows)  # 展示完整记录。
    return '<div class="scroll"><table>' + header + body + '</table></div>'  # 宽表可横向滚动。

def review_focus(item, study_id, readonly=False):  # 每轮只列真正需要人工判断的重点。
    state, module = item["state"], item["module_id"]  # 使用统一状态。
    result = item.get("result")  # 不虚构已运行结果。
    if readonly:  # 回收站只读。
        return '<p>仅供查看：恢复后才能操作。</p>'  # 不催促签署。
    if state == "approved":  # 已签署版本不重复审核。
        return '<p style="color:#26734d"><strong>✓ 本版本已通过，无需重复复核。</strong></p>'  # 上游改变时由失效状态重新提示。
    if state in ("stale", "failed"):  # 不允许误批旧结果。
        return '<p class="notice"><strong>必须处理：结果失效或运行失败。</strong>请先核对原因并重跑，当前不能通过。</p>'  # 保留真实门控。
    if not result:  # 未运行时没有审核任务。
        return '<p>当前无需复核；先完成本模块运行或所需输入。</p>'  # 入口仍在下方。
    if module == "A07":  # A07使用专门的结论与双报告复核重点。
        return report_focus(item, study_id)  # 不让用户在完整结果中寻找核心审核内容。
    summary = result["summary"]  # 所有数量来自当前归档。
    if module == "A00" and summary.get("mesh_verification", {}).get("status") == "verified":  # 新登记突出正式疾病身份。
        mesh = summary["mesh_verification"]  # 使用服务器归档的官方核对事实。
        return '<div class="notice"><strong>✓ NLM官方MeSH身份已核对</strong><p>中文疾病：' + text(summary.get("disease")) + '<br>MeSH标准词：' + text(mesh.get("preferred_term")) + '<br>MeSH编号：' + text(mesh.get("mesh_id")) + '<br>MeSH年度：' + text(mesh.get("mesh_year")) + '<br>核对时间（UTC）：' + text(mesh.get("checked_at")) + '</p><p><strong>本轮只需确认：</strong>方剂、药味、中文疾病和上述MeSH身份是否属于本次研究对象。</p></div>'  # 用户无需展开技术JSON寻找编号。
    if summary.get("handoff_blocked"):  # 有阻断项先解决，不让用户翻全文找原因。
        if module == "A02":  # 首版仅本病，不再提示纳入亚型。
            return '<div class="notice"><strong>必须处理：确认本病范围及未查实基因的处理。</strong><p>只处理汇总中的例外，不逐条审核所有基因。</p><a href="/normalize?study=' + text(study_id) + '">进入结果汇总与交接准备</a></div>'  # 直接给出真实入口。
        return '<div class="notice"><strong>必须处理：尚有身份或交接问题，当前不能通过。</strong><p>展开下方“复核资料与完整结果”，只查看身份问题及交接说明；正常记录不需逐条确认。</p></div>'  # 不隐藏未处理问题。
    points = {"A00":["方剂、药味和疾病有没有登记错？"], "A01":["药味是否齐全，有没有取错药材？", "未采用或缺失的成分、靶点，是否有你认为必须保留的？已确认的处理不重复审批。"], "A02":["纳入的是否仅为本次疾病本病？首版不纳入亚型。", "资料缺口或未采用条目是否还有尚未处理的意见？已确认的处理不重复审批。"], "A03":["本次方剂和疾病对应是否正确？", "交集汇总是否有你已知的明显遗漏？无需逐个基因核算。"], "A03_SELECT":["主候选成分是否符合你的选择意图？并列或替换选择是否有明确理由？"], "A04":["查看第一轮主候选：有没有你认为需要提出异议或进一步核查的靶点？", "确认这份有覆盖缺口的PPI结果可作为本次初筛候选；无需逐个审核连边或重算指标。"], "A06_PREP":["确认本次列出的受体、结构质控结果和暂停原因可以用于后续对接。"], "A06":["确认本次实际完成的结合能矩阵与热图可以用于当前研究目的。", "确认失败或暂停组合及其原因已经如实记录，没有用零值或推测结果补齐。"]}.get(module,["核对本轮明确列出的关键例外及结果是否可用于下一步。"])  # A06不再固定某个疾病、受体或组合数。
    body = '<div class="notice"><strong>本轮你只需核对这些</strong><ol>' + ''.join('<li>'+text(x)+'</li>' for x in points) + '</ol>'  # 有限清单，不加新的复核关口。
    if module == "A05":  # 重点区只保留临床使用者需要的四列。
        labels={"BP":"生物过程（BP）","CC":"细胞组分（CC）","MF":"分子功能（MF）","KEGG":"通路（KEGG）"}  # 缩写可直接理解。
        rows=[{"类别":labels[r["group"]],"有效基因数":r["effective_count"],"显著条目数":r["significant_count"],"本类未注释数":r["missing_count"]} for r in result["tables"].get("group_summary",[])]  # 其余统计仍在完整表。
        body += '<p>只需确认本轮概览及注释缺口可用于初筛；无需现在选定重点通路，也无需逐条批准全部条目。</p>'+table(rows,["类别","有效基因数","显著条目数","本类未注释数"])  # 固定阅读顺序。
        missing=result["tables"].get("kegg_missing",[])  # 不重复审批正常基因。
        if missing:  # 缺口集中说明，非身份错误。
            body += '<details><summary>需要知悉：'+str(len(missing))+'个基因本次KEGG无注释（仍保留A03）</summary><p>'+text('、'.join(r.get("symbol") or r["entrez_id"] for r in missing))+'</p><p>这是当前通路注释覆盖缺口，不是基因编号错误；不计入本类有效分母。</p></details>'  # 所有缺口可一次看完。
    if module == "A04":  # 简要显示本轮真实结果。
        body += '<p>本轮：第一轮'+text(summary.get("第一轮主候选数",0))+'个；第二轮'+text(summary.get("第二轮参考数",0))+'个，仅供参考。已确认的'+text(summary.get("本次PPI暂不采用数",0))+'项PPI缺口无需再次逐项批准。</p>'  # 不要求再次选择算法参数。
        rows = [{"基因":r["symbol"],"Degree":r["degree"]} for r in result["tables"].get("round1",[])]  # 只展示主候选必要字段。
        body += '<details><summary><strong>① 查看本轮主候选名单</strong></summary>'+table(rows)+'</details>'  # 正文不展开52行。
    if module == "A06":  # 正式对接只在重点区显示实际矩阵和限制。
        source_matrix = result["tables"].get("score_matrix", [])  # 读取本次真实矩阵。
        targets = [key for key in (source_matrix[0].keys() if source_matrix else []) if key not in ("compound_id", "compound_name")]  # 受体列来自当前结果。
        columns = ["成分", "成分编号"] + [target + "（kcal/mol）" for target in targets]  # 动态生成显示列。
        matrix = [{"成分": row.get("compound_name"), "成分编号": row.get("compound_id"), **{target + "（kcal/mol）": row.get(target) if row.get(target) is not None else "未完成" for target in targets}} for row in source_matrix]  # 缺失项明确显示而不补零。
        body += '<p>计划'+text(summary.get("计划组合数", 0))+'组；完成'+text(summary.get("成功组合数", 0))+'组；失败或暂停'+text(summary.get("失败组合数", 0))+'组。</p>'+table(matrix, columns)  # 一屏查看实际核心输出。
    body += '<p><strong>没有异议：</strong>在下面填写复核人和意见，决定选择“通过，允许下游使用”，保存一次即可。算法、阈值计算和文件一致性由程序校验与开发验收负责；发现异常可退回，不需你手工重算。</p></div>'  # 说明责任与明确操作。
    return body  # 不自动代签。


def review_form(item, study_id, token, readonly):  # 复核入口紧随重点，不放在长表后。
    if readonly or not item.get("result") or item["state"] in ("stale", "failed"):  # 保留原权限边界。
        return ""  # 不提供无效操作。
    previous = item.get("review")  # 版本冲突校验沿用原表单。
    body = '<form method="post" action="/review">' + hidden("token",token) + hidden("study",study_id) + hidden("run",item["run"]["run_id"]) + hidden("previous",previous["review_id"] if previous else "")  # 绑定真实运行和上次决定。
    option = '' if item["result"]["summary"].get("handoff_blocked") else '<option value="approved">通过，允许下游使用</option>'  # 问题未解决不放行。
    body += '<label>复核人<input name="reviewer" required maxlength="200"></label><label>意见或处理理由<textarea name="note" required maxlength="4000"></textarea></label><label>决定<select aria-label="决定" name="decision"><option value="pending">暂存待定</option>'+option+'<option value="rejected">退回修改</option></select></label><button name="after_review" value="save">仅保存复核决定</button><button name="after_review" value="continue">保存并继续到下一人工关口</button></form>'  # 用户明确选择是否立即自动接续。
    return '<details><summary>需要更改已保存的复核决定时展开</summary>'+body+'</details>' if item["state"]=="approved" else body  # 已通过不反复展示空表。


def management_panel(workflow, manifest, token):  # 提供可恢复回收站入口，保留全部资料。
    study_id = manifest["study_id"]  # 管理操作绑定明确研究。
    trashed = manifest.get("trashed", False)  # 旧研究默认仍在正常列表。
    events = [read_json(verified_file(workflow.location(study_id), item)) for item in manifest.get("management_events", [])]  # 管理记录单独读取并校验。
    action, label = ("restore", "恢复研究") if trashed else ("trash", "移入回收站")  # 不提供永久删除按钮。
    explanation = "恢复后可继续复核和使用，原记录保留。" if trashed else "移入后从首页隐藏，资料和历史全部保留，可在回收站恢复。"  # 清楚说明实际效果。
    form = '<form method="post" action="/retention">' + hidden("token", token) + hidden("study", study_id) + hidden("action", action) + hidden("previous_action", events[-1]["action_id"] if events else "")  # 提交时校验页面看到的管理版本。
    form += '<label>管理人<input name="operator" required maxlength="200"></label><label>管理操作原因<textarea name="reason" required maxlength="4000"></textarea></label><label><input style="width:auto" type="checkbox" name="confirmed" value="yes" required>确认' + label + '当前研究</label><button>' + label + '</button></form>'  # 明确选择具体研究后才提交。
    rows = [{"时间（UTC）": item["created_at"].replace("T", " ").split(".")[0], "管理人": item["operator"], "操作": "移入回收站" if item["action"] == "trash" else "恢复研究", "原因": item["reason"]} for item in events]  # 用中文说明谁在何时做了什么。
    history = '<details><summary>研究管理历史</summary>' + (table(rows, ["时间（UTC）", "管理人", "操作", "原因"]) if rows else '<p>尚无管理操作。</p>') + '</details>'  # 不混入科学复核历史。
    return '<section><details><summary>研究管理</summary><p>' + explanation + '</p>' + form + history + '</details></section>'  # 默认折叠，避免误触。

def create_server(root, port=8765, mesh_verifier=verify_mesh_identity):  # 将服务限定在本机，并允许测试替换联网核对器。
    workflow = Workflow(root, {"A01": normalization_validator(root, validate_components), "A02": normalization_validator(root, validate_disease), "A03": validate_intersection, "A03_SELECT": validate_selection, "A04": ppi_validator(root), "A05": enrichment_validator(root), "A06_PREP": docking_prep_validator(root), "A06": docking_formal_validator(root), "A07": report_validator(root)})  # 已完成模块均接入统一校验和状态体系。
    token = secrets.token_urlsafe(32)  # 每次启动重新生成表单令牌。

    class Handler(BaseHTTPRequestHandler):  # 用同一处理器提供页面、表单和只读数据。
        def log_message(self, format, *args):  # 避免把表单或科研内容写进控制台。
            return  # 启动地址由入口明确显示。

        def send(self, content, status=200, mime="text/html; charset=utf-8", filename=None):  # 统一响应头。
            data = content.encode("utf-8") if isinstance(content, str) else content  # 同时支持网页和文件下载。
            self.send_response(status)  # 明确成功或错误。
            self.send_header("Content-Type", mime)  # 浏览器按指定类型解释。
            self.send_header("Content-Length", str(len(data)))  # 不使用不完整响应。
            self.send_header("Cache-Control", "no-store")  # 不让旧审核页面被当成最新结果。
            self.send_header("X-Content-Type-Options", "nosniff")  # 下载文件不被浏览器猜成脚本。
            self.send_header("Content-Security-Policy", "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")  # 只允许本机已归档图件，不加载第三方脚本或图片。
            if filename is not None:  # 下载时沿用归档名称，避免全部保存为同一个接口名。
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename, safe=""))  # 编码中文文件名，不直接拼接响应头。
            self.end_headers()  # 完成响应头。
            self.wfile.write(data)  # 发送完整内容。

        def valid_host(self):  # 防止外部网页借本机地址提交操作。
            return self.headers.get("Host") in ("127.0.0.1:" + str(self.server.server_port), "localhost:" + str(self.server.server_port))  # 主机名和端口必须对应当前服务。

        def redirect(self, target):  # 提交后重新读取最新页面。
            self.send_response(303)  # 刷新页面不会重复提交。
            self.send_header("Location", target)  # 只跳转服务内部地址。
            self.send_header("Content-Length", "0")  # 响应没有额外正文。
            self.end_headers()  # 结束跳转。

        def do_GET(self):  # 处理网页访问和只读接口。
            try:  # 将可预期的数据问题显示给用户。
                require(self.valid_host(), "访问地址不匹配")  # 不接受任意 Host。
                route = urlsplit(self.path)  # 分离路由和查询字段。
                query = parse_qs(route.query)  # 将查询值解析为列表。
                study_id = query.get("study", [""])[0]  # 所有研究操作仍由内核校验编号。
                if route.path in ("/", "/trash"):  # 首页与回收站分别列出研究。
                    trash_page = route.path == "/trash"  # 仅根据明确入口切换列表。
                    links = []  # 汇总现有研究链接。
                    for manifest in workflow.studies(trashed=trash_page):  # 正常研究与回收站分开显示。
                        view = workflow.view(manifest["study_id"])  # 获取真实登记摘要。
                        intake = view["modules"][0]["result"]["summary"]  # 不从文件夹名称猜研究对象。
                        links.append('<p><a href="/study?study=' + manifest["study_id"] + '">' + text(intake["formula"] + " · " + intake["disease"]) + '</a><br><small>' + manifest["study_id"] + '</small></p>')  # 显示名称和稳定编号。
                    body = '<p class="notice">当前支持研究登记、A01至A06科学流程、双报告生成、版本留存和网页复核。正式研究仍须使用按MeSH标准词重新获取并审核的疾病资料；流程测试结果不会自动变成正式研究结论。</p><section><h2>已有研究</h2>' + ("".join(links) or '<p>尚未创建研究。</p>') + '</section>'  # 准确说明当前能力和正式研究边界。
                    body += '<p><a href="/">正常研究</a> · <a href="/trash">回收站</a></p>'  # 两个列表之间可直接切换。
                    if not trash_page:  # 回收站不提供创建研究表单。
                        body += '<section><h2>创建研究</h2><form method="post" action="/create">' + hidden("token", token) + fields() + '<button>核对MeSH并保存登记</button></form></section>'  # 保存前完成官方核对。
                    self.send(page("回收站" if trash_page else "研究工作台", body))  # 页面标题明确区分。
                elif route.path in ("/study", "/api/study"):  # 页面与只读接口共享状态来源。
                    view = workflow.view(study_id)  # 每次请求重新核验磁盘资料。
                    if route.path == "/api/study":  # 接口便于测试和后续界面扩展。
                        self.send(json.dumps(view, ensure_ascii=False), mime="application/json; charset=utf-8")  # 不从客户端提交伪造状态。
                        return  # 接口不再生成 HTML。
                    body = '<p class="muted">研究编号：' + text(study_id) + '</p><p class="notice">通过复核表示本版本可交接给下游，不代表已经证明药效。选择“保存并继续”时，系统只运行已有明确规则的步骤，并在下一人工判断处暂停。</p>'  # 说明复核与自动接续边界。
                    if query.get("message", [""])[0]:  # 提交后直接显示本次自动接续结果。
                        body += '<p class="notice"><strong>本次处理：</strong>' + text(query["message"][0]) + '</p>'  # 用户无需从模块状态猜发生了什么。
                    trashed = view["manifest"].get("trashed", False)  # 回收站研究仍可查看但不可修改。
                    if trashed:  # 让用户明确知道当前处于只读状态。
                        body += '<p class="notice">本研究在回收站中，仅供查看。请通过“研究管理”恢复后继续操作。</p>'  # 不误导成研究资料丢失。
                    body += management_panel(workflow, view["manifest"], token)  # 在顶部提供管理入口。
                    pair_mode = view["manifest"].get("workflow_profile") in PREUPLOAD_PROFILES and all(next((entry.get("result") for entry in view["modules"] if entry["module_id"] == module), None) for module in ("A01", "A02"))  # 新流程在两项均生成后启用一次复核。
                    for item in view["modules"]:  # 所有步骤按同一模块表显示。
                        body += '<article><h2>' + text(item["module_id"] + " · " + item["title"]) + '</h2><span class="tag">' + LABELS[item["state"]] + '</span>'  # 显示真实状态。
                        if item["result"] and item["result"]["summary"].get("analysis_purpose")=="workflow_test":  # 用途标签始终可见。
                            body += '<p><strong>流程测试结果，非正式研究结论</strong></p>'  # 不因折叠资料隐藏用途。
                        if item["module_id"] in ("A05", "A07"): # 通路审核入口放在重点区，不藏进完整资料。
                            body += pathway_card(workflow, view["manifest"], token, item["module_id"]) # 真实区分推荐、批准、失效与报告纳入。
                        body += review_focus(item, study_id, trashed)  # 先显示会影响下游的处理重点。
                        if item["module_id"] == "A00":  # 新研究在A00复核前准备两个人工来源。
                            body += intake_source_controls(workflow, view, token)  # 上传不提前生成A02。
                        if not (pair_mode and item["module_id"] in ("A01", "A02")):  # 两项均生成后改用一次提交。
                            body += review_form(item, study_id, token, trashed)  # 其他模块保持原复核表单。
                        if pair_mode and item["module_id"] == "A02":  # 表单放在第二张卡片，查看两项后一次保存。
                            body += a01_a02_review_form(view, token)  # 后台仍生成两条独立记录。
                        if item["result"]:  # 资料完整保留但默认收起。
                            body += '<details><summary>复核资料与完整结果（需要时展开）</summary>'  # 减少首页信息负担。
                        if item["run"]:  # 只有真实运行才展示版本和输入。
                            body += '<details><summary>追溯资料：本次输入、参数和版本</summary>' + details(item["run"]) + '</details>'  # 保留人工查证入口。
                        if item["result"]:  # 展示已经完整归档的结果。
                            result = item["result"]  # 简化下文引用。
                            if (result["summary"].get("analysis_purpose") or result["summary"].get("分析用途")) == "workflow_test":  # 运行及下游始终显示测试用途。
                                body += '<p class="notice"><strong>流程测试结果，非正式研究结论</strong></p>'  # 防止误用旧资料结论。
                            body += '<p>结果类型：' + text({"success": "成功提交", "empty": "有效空结果", "failed": "执行失败", "partial": "部分完成，失败项保留NA"}[result["outcome"]]) + '</p><details><summary>结果摘要</summary>' + information(result["summary"]) + '</details>'  # 空结果与失败单独说明。
                            body += '<details><summary>需要知悉：异常与排除说明（随总体复核查看）</summary>' + table([{"说明": note} for note in result["anomalies"]], ["说明"]) + '</details>'  # 用中文说明异常，不强迫用户阅读JSON。
                            if item["module_id"] == "A06" and result["tables"].get("generic_docking"):  # 动态矩阵集中显示同源热图和结构限制。
                                from docking_ui import dynamic_result_section  # 不影响历史固定矩阵入口。
                                body += dynamic_result_section(result, study_id, workflow)  # 图后立即显示中文限制表及用户批准的图件修订。
                            for name, rows in result["tables"].items():  # 完整表在网页直接查看。
                                if isinstance(rows, dict):  # 嵌套对接事实不能当作普通表格迭代。
                                    body += '<details><summary>技术追溯：完整对接事实包</summary>' + details(rows) + '</details>'  # 普通使用者不需要读代码格式。
                                    continue  # 其他平面表仍正常显示。
                                labels = INTERSECTION_FIELDS if item["module_id"] in ("A03", "A03_SELECT") else (DISEASE_FIELDS if item["module_id"] == "A02" else FIELD_LABELS)  # 不混用两个科学模块的字段。
                                title = (INTERSECTION_TABLES if item["module_id"] in ("A03", "A03_SELECT") else (DISEASE_TABLES if item["module_id"] == "A02" else TABLE_LABELS)).get(name, name)  # 表名按模块翻译。
                                if item["module_id"] == "A04":  # PPI字段不混入成分表。
                                    title, labels = PPI_TABLES.get(name,name), PPI_FIELDS  # 明确两轮和异常类别。
                                if item["module_id"] == "A07":  # A07表格使用报告专用名称。
                                    title, labels = REPORT_TABLES.get(name, name), {}  # A07字段本身已是中文。
                                title, labels = NORMALIZATION_TABLES.get(name, title), dict(labels, **NORMALIZATION_FIELDS)  # 标准化明细同样提供中文展示。
                                if item["module_id"] == "A05":  # 富集大表不铺满首页。
                                    body += '<p><a href="/enrichment-table?study='+study_id+'&amp;run='+result["run_id"]+'&amp;table='+name+'">'+text(ENRICHMENT_TABLES.get(name,name))+'（'+str(len(rows))+'条）</a></p>'  # 完整数据分页查看。
                                elif item["module_id"] in ("A03", "A03_SELECT") and len(rows) > 50:  # 大表在网页分页检索。
                                    body += '<p><a href="/intersection-table?study=' + study_id + '&amp;run=' + result["run_id"] + '&amp;table=' + name + '">' + text(title) + '（' + str(len(rows)) + '条，可查询）</a></p>'  # 不截断归档数据。
                                elif item["module_id"] == "A02" and name != "source_summary":  # 大候选表使用可搜索分页，不一次挤进研究首页。
                                    body += '<p><a href="/disease?study=' + study_id + '&amp;table=' + name + '">' + text(title) + '（' + str(len(rows)) + '条）</a></p>'  # 全量仍可下载。
                                else:  # A01与小型资料摘要继续直接展开。
                                    display_rows = [{labels.get(key, key): value for key, value in row.items()} for row in rows]  # 翻译字段，不改变归档数值。
                                    body += '<details><summary>' + text(title) + '</summary>' + table(display_rows) + '</details>'  # 不由模型改写数据。
                            body += '<details><summary>追溯资料：下载本次原始资料与结果文件</summary>'  # 文件集中收起，保留全部下载入口。
                            for index, record in enumerate(result["files"]):  # 提供有索引和指纹的文件下载。
                                body += '<p><a href="/file?study=' + study_id + '&amp;run=' + result["run_id"] + '&amp;index=' + str(index) + '">下载 ' + text(record["path"].split("/")[-1]) + '</a></p>'  # URL 不暴露任意磁盘路径。
                            body += '</details>'  # 结束本次文件下载区。
                        if item["review"]:  # 最近决定直接展示在步骤中。
                            body += '<details><summary>最近复核记录</summary>' + information(item["review"]) + '</details>'  # 历史记录另有完整列表。
                        if item["result"]:  # 结束资料分组。
                            body += '</details><details><summary>其他操作：查看图表、补充资料或重新运行</summary>'  # 重跑操作不冒充通过入口。
                        if item["module_id"] == "A01" and item["available"] and not trashed:  # 登记通过后开放本地资料整理。
                            body += '<p class="notice">读取本地TCMSP提取快照，使用OB≥30%、DL≥0.18，仅纳入可明确映射的人类靶点。数据库发布版本未知，运行后需专业复核。药味请用顿号或逗号分隔，不自动替换药材。处理期间请等待，不要重复点击。</p>'  # 说明实际范围和来源限制。
                            body += '<form method="post" action="/components">' + hidden("token", token) + hidden("study", study_id) + hidden("expected_a00", view["manifest"]["current"]["A00"]) + hidden("expected_a01", view["manifest"]["current"].get("A01", "")) + '<label>A01运行或重跑原因<input name="reason" required maxlength="4000"></label><button>运行A01成分与靶点整理</button></form>'  # 每次新运行固定版本并留下理由。
                        if item["module_id"] == "A02":  # 在原模块卡片接入候选资料操作。
                            body += disease_controls(workflow, view, token)  # 回收站和上游门控由该入口共同检查。
                        if item["module_id"] in ("A03", "A03_SELECT"):  # 独立显示交集和选择入口。
                            body += intersection_controls(workflow, view, item, token)  # 不另建状态体系。
                        if item["module_id"] == "A06_PREP":  # 在统一准备关口查看进度。
                            body += docking_automation_controls(workflow, study_id, token)  # 必审事项与后台状态直接可见。
                            body += docking_preview_link(workflow,study_id)  # 只读预览不改变审核状态。
                        if item["module_id"] == "A05":  # 富集独立依赖A03。
                            body += enrichment_controls(view,item,token)  # 图形与运行沿用同一卡片。
                        if item["module_id"] == "A04":  # A04入口接入原卡片。
                            body += ppi_controls(view,item,token)  # 不另建状态。
                        if item["module_id"] == "A07":  # A07在统一卡片生成和下载双报告。
                            body += report_controls(view, item, token)  # 不另建并行发布状态。
                        if item["result"]:  # 与其他操作分组配对。
                            body += '</details>'  # 默认收起已完成模块的操作。
                        body += '</article>'   # 结束当前模块卡片。
                    manifest = view["manifest"]  # 读取已核验的研究索引。
                    history = [read_json(verified_file(workflow.location(study_id), record)) for record in manifest["reviews"]]  # 完整历史不会被最近决定遮蔽。
                    runs = sorted([workflow.run(manifest, run_id) for run_id in manifest["runs"]], key=lambda item: (item["created_at"], item["run_id"]))  # 按创建顺序展示，不把随机编号当作先后顺序。
                    numbers = {run["run_id"]: index + 1 for index, run in enumerate(runs)}  # 为阅读提供“第几次运行”，原编号继续保留。
                    run_map = {run["run_id"]: run for run in runs}  # 让每条复核对应到明确模块。
                    review_rows = []  # 中文历史表只展示有记录依据的事实。
                    for index, review in enumerate(history, 1):  # 保留原始审核先后顺序。
                        run = run_map[review["run_id"]]  # 获取该条复核实际针对的运行。
                        review_rows.append({"序号": index, "复核时间（UTC）": review["created_at"].replace("T", " ").split(".")[0], "模块": MODULES[run["module_id"]][0], "对应运行": "第" + str(numbers[review["run_id"]]) + "次运行", "复核人": review["reviewer"], "决定": {"approved": "通过", "rejected": "退回修改", "pending": "暂存待定"}[review["decision"]], "意见": review["note"]})  # 不用当前决定覆盖历史决定。
                    run_rows = []  # 将技术索引转换为可阅读的版本列表。
                    state_map = {item["module_id"]: item["state"] for item in view["modules"]}  # 当前模块状态已在本次view中完成全链核验。
                    for run in runs:  # 按时间顺序逐项展示历史运行。
                        result_record = manifest["runs"][run["run_id"]].get("result_file")  # 历史索引只需核验标准结果文件本身。
                        result = read_json(verified_file(workflow.location(study_id), result_record)) if result_record else None  # 当前版本附件已由view完整核验，历史附件按需下载时再核验。
                        current = manifest["current"].get(run["module_id"]) == run["run_id"]  # 区分当前指针和保留的旧版本。
                        usage = ("当前版本，上游已失效" if state_map[run["module_id"]] == "stale" else "当前版本") if current else "历史版本（保留追溯）"  # 复用刚完成的当前状态判断。
                        outcome = {"success": "成功提交", "empty": "有效空结果", "failed": "执行失败", "partial": "部分完成，失败项保留NA"}[result["outcome"]] if result else "尚未完整提交"  # 提交情况与人工批准分开显示。
                        run_rows.append({"运行次序": "第" + str(numbers[run["run_id"]]) + "次运行", "创建时间（UTC）": run["created_at"].replace("T", " ").split(".")[0], "模块": MODULES[run["module_id"]][0], "创建或修改原因": run["reason"], "提交情况": outcome, "版本用途": usage})  # 用中文说明每次运行的意义。
                    body += '<section><details><summary>全部复核历史</summary>' + (table(review_rows, ["序号", "复核时间（UTC）", "模块", "对应运行", "复核人", "决定", "意见"]) if review_rows else '<p>尚无复核记录。</p>') + '<details><summary>查看原始复核记录（技术追溯）</summary>' + details(history) + '</details></details>'  # 原始数据只放入第二层展开区。
                    body += '<details><summary>全部运行版本索引</summary>' + table(run_rows, ["运行次序", "创建时间（UTC）", "模块", "创建或修改原因", "提交情况", "版本用途"]) + '<details><summary>查看原始运行索引（技术追溯）</summary>' + details(manifest["runs"]) + '</details></details></section>'  # 中文列表与原始索引并存，不改存档。
                    intake = view["modules"][0]["result"]["summary"]  # 使用当前登记填入修订表单。
                    if not trashed:  # 回收站中不提供登记修订入口。
                        body += '<section><details><summary>修订研究登记（保存后下游需重新核验）</summary><form method="post" action="/revise">' + hidden("token", token) + hidden("study", study_id) + hidden("expected_run", manifest["current"]["A00"]) + fields(intake) + '<label>修改原因<textarea name="reason" required maxlength="4000"></textarea></label><button>保存新的登记版本</button></form></details></section>'  # 不直接修改原始输入。
                    self.send(page("研究与逐模块复核", body))  # 显示完整工作页。
                elif route.path == '/docking-automation':  # 本研究结构方案和任务进度。
                    self.send(page('分子对接自动化', docking_automation_page(workflow, study_id, token)))  # 只读显示，不自动代签。
                elif route.path == "/docking-preview":  # 本研究固定上游的准备资料。
                    self.send(docking_preview_page(workflow,study_id))  # 只读，不代签。
                elif route.path == "/docking-preview-file":  # 准备证据按清单下载。
                    preview = load_docking_preview(workflow,study_id)  # 校验研究、上游和所有文件。
                    number = int(query.get("index",["-1"])[0])  # 只接受清单序号。
                    require(0 <= number < len(preview["evidence"]),"准备资料编号不合法")  # 不接收用户指定路径。
                    path = verified_file(workflow.root,preview["evidence"][number])  # 验证实际下载文件。
                    self.send(path.read_bytes(),mime="application/octet-stream",filename=path.name)  # 下载保留归档名称，不执行内容。
                elif route.path == "/pathway-review": # 当前研究通路推荐和人工审核。
                    self.send(pathway_page(workflow, study_id, token)) # GET只查看资料，不产生批准。
                elif route.path == "/pathway-file": # 图件只按选择版本下载。
                    path = pathway_figure(workflow, study_id, query.get("selection", [""])[0]) # 拒绝旧版本和任意文件路径。
                    self.send(path.read_bytes(), mime="image/png") # 保持图源原始字节。
                elif route.path == "/enrichment-table":  # 富集完整结果分页。
                    self.send(enrichment_page(workflow,study_id,query))  # 同一运行只读数据。
                elif route.path == "/intersection-table":  # A03大表只读查询。
                    self.send(intersection_page(workflow, study_id, query))  # 同次运行的完整表分页。
                elif route.path == "/normalize":  # 只读集中预览。
                    self.send(normalization_page(workflow, study_id, token))  # 不在GET中签署或修改数据。
                elif route.path == "/disease":  # 查询候选与范围复核页面。
                    self.send(disease_page(workflow, study_id, query, token))  # 使用统一研究状态与中文页面。
                elif route.path == "/disease-template":  # 返回通用原始候选的字段模板，不填写假数据。
                    self.send("raw_symbol\traw_id\traw_score\tscore_name\tdisease_term\tdisease_id\trelation_type\n", mime="text/tab-separated-values; charset=utf-8")  # 缺字段保持空白，不填0。
                elif route.path == "/disease-detailed-template":  # 返回严格详细TXT模板，只含字段名。
                    self.send("raw_symbol\tdisease_term\traw_id\tdisease_id\ttarget_name\traw_uniprot\traw_score\tscore_name\tclinical_status\trelation_type\tsource_record_id\tevidence_url\n", mime="text/tab-separated-values; charset=utf-8")  # 未知值留空，不生成示例基因。
                elif route.path == '/docking-figure':  # 展示纯图件修订，不改A06运行及分数。
                    from docking_grouped_heatmap import current_display  # 严格核验来源与指纹。
                    manifest = workflow.load(study_id)  # 当前科学版本。
                    run_id = manifest['current'].get('A06')  # 唯一当前A06。
                    require(run_id and workflow.active(manifest, run_id), '当前A06尚未完成或已失效')  # 旧图不能冒充当前。
                    revised = current_display(workflow, workflow.result(manifest, run_id))  # 同一研究的展示修订。
                    require(revised is not None, '没有绑定当前结果的图件修订')  # 不随意读取路径。
                    self.send(revised[1].read_bytes(), mime='image/png')  # 只发送核验后的PNG。
                elif route.path == "/file":  # 下载仅限已归档且通过完整性检查的关联文件。
                    manifest = workflow.load(study_id)  # 核验研究身份。
                    run_id = query.get("run", [""])[0]  # 获取指定运行。
                    workflow.run(manifest, run_id)  # 阻止跨研究读取。
                    result = workflow.result(manifest, run_id)  # 校验结果全部文件。
                    index = int(query.get("index", ["-1"])[0])  # 文件必须来自结果清单。
                    require(result and 0 <= index < len(result["files"]), "文件编号不合法")  # 拒绝任意文件路径。
                    path = verified_file(workflow.location(study_id), result["files"][index])  # 再次确认下载对象。
                    self.send(path.read_bytes(), mime="application/octet-stream", filename=path.name)  # 浏览器按归档文件名下载，不执行内容。
                else:  # 未定义路由不会映射到项目文件系统。
                    self.send(page("页面不存在", '<p><a href="/">返回首页</a></p>'), 404)  # 不泄露任意文件。
            except (ContractError, ValueError) as error:  # 已知校验问题可直接说明。
                self.send(page("需要处理的问题", '<p>' + text(error) + '</p><p><a href="/">返回工作台</a></p>'), 400)  # 不自动修复或补数据。
            except Exception:  # 未预料异常不得伪装成操作成功。
                self.send(page("操作未完成", '<p>发生未预料错误，当前操作未确认完成。请保留资料并联系维护者核查。</p>'), 500)  # 不暴露内部凭据或堆栈。

        def do_POST(self):  # 处理创建、修订和复核表单。
            try:  # 所有变更都先做来源和参数检查。
                require(self.valid_host(), "访问地址不匹配")  # 禁止错误主机来源。
                origin = self.headers.get("Origin")  # 浏览器提交时通常带来源。
                require(not origin or origin in ("http://127.0.0.1:" + str(self.server.server_port), "http://localhost:" + str(self.server.server_port)), "不接受其他网页发起的操作")  # 限定本机工作台来源。
                length = int(self.headers.get("Content-Length", "0"))  # 读取明确的请求大小。
                require(0 < length <= (17 * 1024 * 1024 if self.path in ("/disease-upload", "/ppi-upload", "/intake-source-upload") else (2 * 1024 * 1024 if self.path == "/disease-scope-batch" else 65536)), "表单内容大小不合适")  # 文件上传路由允许较大请求。
                uploads = {}  # 文件与普通字段分开保存。
                if self.path in ("/disease-upload", "/ppi-upload", "/intake-source-upload"):  # 浏览器文件上传使用标准multipart。
                    require(self.headers.get_content_type() == "multipart/form-data", "请使用A02上传表单")  # 不猜二进制格式。
                    data, uploads = multipart(self.headers.get("Content-Type", ""), self.rfile.read(length))  # 文件名不作为保存路径。
                else:  # 原登记、审核和查询表单继续使用URL编码。
                    require(self.headers.get_content_type() == "application/x-www-form-urlencoded", "表单格式不支持")  # 保留原请求约束。
                    values = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)  # 按UTF-8读取。
                    require(all(len(items) == 1 for items in values.values()), "表单字段重复")  # 不从重复字段中任取首项。
                    data = {key: items[0] for key, items in values.items()}  # 每个字段恰好一个值。
                require(secrets.compare_digest(data.get("token", ""), token), "页面已过期或来源不正确，请刷新后重试")  # 旧进程的表单不能写入。
                if self.path in ("/create", "/revise"):  # 两个入口共用研究输入字段。
                    intake = {name: data.get(name, "").strip() for name in ("formula", "herbs", "disease", "mesh_term", "mesh_id", "disease_scope", "operator")}  # 不混入表单令牌。
                    intake["analysis_purpose"] = data.get("analysis_purpose", "formal_research").strip()  # 旧客户端缺字段时沿用此前正式研究语义。
                    intake["species"] = 9606  # 人类范围由服务器固定。
                    intake["mesh_id"] = intake["mesh_id"].upper()  # 网页显示和归档统一使用大写D编号。
                    intake["mesh_verification"] = mesh_verifier(intake["mesh_term"], intake["mesh_id"])  # 官方核对成功后才允许建立版本。
                    if self.path == "/create":  # 新建研究包。
                        study_id = workflow.create(intake)  # 返回独立研究编号。
                    else:  # 修订必须提交旧版本编号和理由。
                        study_id = data.get("study", "")  # 编号由内核再次校验。
                        workflow.revise_intake(study_id, intake, data.get("reason", ""), data.get("expected_run", ""))  # 不覆盖旧版本。
                elif self.path == "/intake-source-upload":  # A00阶段只暂存并校验来源。
                    study_id = data.get("study", "")  # 文件限定当前研究。
                    require(data.get("confirmed") == "yes", "请确认文件属于当前研究对象")  # 不自动套用其他研究下载。
                    if uploads["upload"]["name"].lower().endswith(".xls") and not uploads["upload"]["name"].lower().endswith(".xlsx"):
                        raise ContractError("不支持旧.xls，请在Excel中另存为.xlsx后上传")  # 旧二进制Excel不按文本猜测。
                    source = dict(data, name=uploads["upload"]["name"], data=uploads["upload"]["data"])  # 原始字节进入暂存内核。
                    stage_intake_source(workflow, study_id, data.get("expected_a00", ""), source)  # 不要求A00已通过。
                elif self.path == "/retention":  # 保存用户明确选择的移入或恢复动作。
                    study_id = data.get("study", "")  # 不允许批量或隐式选择研究。
                    require(data.get("action") in ("trash", "restore") and data.get("confirmed") == "yes", "请明确确认本次研究管理操作")  # 无确认或未知动作不能生效。
                    workflow.set_trashed(study_id, data["action"] == "trash", data.get("operator", ""), data.get("reason", ""), data.get("previous_action") or None)  # 内核再次校验当前状态及留存条件。
                    self.redirect("/trash" if data["action"] == "trash" else "/study?study=" + study_id)  # 移入后到回收站，恢复后回研究。
                    return  # 避免重复响应。
                elif self.path in ("/ppi", "/ppi-upload"):  # 自动和离线来源进入同一接口。
                    study_id = data.get("study", "")  # 限定当前研究。
                    bundle = json.loads(uploads["upload"]["data"].decode("utf-8-sig")) if self.path == "/ppi-upload" else None  # 不把上传文件名当路径。
                    run_ppi(workflow,study_id,data.get("expected_a03",""),data.get("expected_a04",""),data.get("reason",""),bundle)  # 重新核验上游与参数。
                elif self.path == "/intersection":  # 仅使用已批准的标准化上游。
                    study_id = data.get("study", "")  # 限定研究。
                    run_intersection(workflow, study_id, {key: data.get("expected_" + key.lower(), "") for key in ("A01", "A02", "A03")}, data.get("reason", ""))  # 服务端再核验。
                elif self.path == "/intersection-select":  # 保存独立候选版本。
                    study_id = data.get("study", "")  # 不接受隐式研究。
                    selected = [line.strip() for line in data.get("selected", "").splitlines() if line.strip()]  # 每行一个编号，不自动替换身份。
                    run_selection(workflow, study_id, data.get("expected_a03", ""), data.get("expected_select", ""), selected, data.get("reviewer", ""), data.get("reason", ""), data.get("confirmed") == "yes")  # 保留人工确认与理由。
                elif self.path == "/normalize":  # 明确接受测试范围及例外后才发布。
                    study_id = data.get("study", "")  # 限定当前研究。
                    publish_normalization(workflow, study_id, data.get("preview_stamp", ""), data.get("reviewer", ""), data.get("reason", ""), data.get("accept_scope") == "yes", data.get("accept_omit") == "yes", data.get("accept_source_exception") == "yes")  # 缺GeneCards例外必须单独签署。
                elif self.path == "/enrichment":  # A05不读取PPI子集。
                    study_id=data.get("study","")  # 绑定本研究。
                    run_enrichment(workflow,study_id,data.get("expected_a03",""),data.get("expected_a05",""),data.get("reason",""))  # 完整归档且不代签。
                elif self.path == "/pathway-request": # 请求准备推荐，不代替科学评价。
                    study_id = data.get("study", "") # 独立研究归档。
                    request_recommendation(workflow, study_id, data.get("expected_a05", ""), data.get("expected_request", ""), data.get("note", "")) # 防止旧页面重复保存。
                elif self.path == "/pathway-review": # 通路图与解释独立审核。
                    study_id = data.get("study", "") # 与A05、A07批准分开。
                    review_pathway(workflow, study_id, data.get("expected_a05", ""), data.get("expected_selection", ""), data.get("decision", ""), data.get("reviewer", ""), data.get("note", ""), data.get("confirmed", "")) # 不代签完整研究结论。
                elif self.path == "/pathway-report": # 已认可内容才纳入专业报告。
                    study_id = data.get("study", "") # 新修订归当前研究。
                    publish_pathway_report(workflow, data) # 保留旧报告及临床简略版。
                elif self.path == "/reports":  # A07从全部已批准必需模块生成双报告。
                    study_id = data.get("study", "")  # 绑定当前研究。
                    run_reports(workflow, study_id, data.get("expected_a07", ""), data.get("reason", ""))  # 新建报告修订且不自动批准结论。
                elif self.path == "/components":  # A01处理使用当前已批准登记。
                    study_id = data.get("study", "")  # 明确本次所属研究。
                    run_components(workflow, study_id, data.get("expected_a00", ""), data.get("expected_a01", ""), data.get("reason", ""))  # 执行和留存由统一模块入口完成。
                elif self.path in ("/disease-import", "/disease-upload", "/disease-otp", "/disease-scope", "/disease-ttd", "/disease-pharmgkb", "/disease-scope-batch"):  # A02所有输入共用一次版本提交。
                    study_id = data.get("study", "")  # 本次所属研究。
                    manifest = workflow.load(study_id)  # 获取明确当前登记。
                    require(not manifest.get("trashed", False) and manifest["current"].get("A00") == data.get("expected_a00") and manifest["current"].get("A02", "") == data.get("expected_a02", "") and workflow.approved(manifest, data.get("expected_a00", "")), "研究状态已改变或A00未通过，请刷新核对")  # 联网前也检查资格和旧页面。
                    current_a02 = workflow.result(manifest, data.get("expected_a02", "")) if data.get("expected_a02") else None  # 后台判断当前研究方案和首次/替换。
                    special_profile = bool(current_a02 and current_a02["summary"].get("source_profile") in ("A02.source_profile.1", "A02.source_profile.2", "A02.source_profile.3"))  # 新五库研究隐藏字段并自动留痕。
                    changes, scope = [], None  # 范围意见与来源替换分开。
                    if self.path == "/disease-scope-batch":  # 一次保存全表人工决定。
                        require(data.get("confirmed") == "yes", "请确认全表范围决定")  # 不默认批准全部。
                        default = data.get("batch_default", "")  # 用户明确指定未单独改动条目的处理。
                        current_groups = workflow.result(manifest, data["expected_a02"])["tables"]["scope_groups"]  # 取得当前完整范围。
                        existing = {row["scope_id"]: row["scope"] for row in current_groups}  # 保留已有决定选项。
                        scope = [{"scope_id": key[6:], "scope": (existing.get(key[6:]) if default == "keep" else default) if value == "inherit" else value, "reviewer": data.get("reviewer", ""), "note": data.get("note", "")} for key, value in data.items() if key.startswith("entry_")]  # 每条独立归档，后台再次校验全量。
                        require(bool(scope), "没有可提交的范围条目")  # 空批次不能伪装成功。
                        reason = "全表疾病范围复核：" + data.get("note", "")  # 一次提交一个运行。
                    elif self.path == "/disease-scope":  # 复核一个已存在疾病条目。
                        scope = {key: data.get(key, "") for key in ("scope_id", "scope", "reviewer", "note")}  # 保存明确人工决定。
                        reason = "疾病范围复核：" + data.get("note", "")  # 运行历史说明变更目的。
                    else:  # 获取资料必须由用户明确选择。
                        require(data.get("confirmed") == "yes", "请确认资料用于当前研究候选核查")  # 不自动套用其他病例。
                        reason = data.get("reason", "")  # 默认方案继续使用页面填写的原因。
                        if self.path == "/disease-import":  # 只导入明确COPD的历史快照。
                            require(workflow.result(manifest, manifest["current"]["A00"])["summary"]["disease"].strip().casefold() in COPD_NAMES, "COPD历史资料不能自动用于其他疾病")  # 阻止跨疾病隐式复用。
                            changes = [source for source in legacy_sources(workflow.root) if source["database"] in ("GeneCards", "OMIM", "DisGeNET")]  # 本次授权仅三库，OTP和TTD保持原来源。
                        elif self.path == "/disease-upload":  # 上传保留实际文件和元信息。
                            if uploads["upload"]["name"].lower().endswith(".xls") and not uploads["upload"]["name"].lower().endswith(".xlsx"):  # 旧二进制Excel没有可靠解析器。
                                raise ContractError("不支持旧.xls，请在Excel中另存为.xlsx后上传")  # 不尝试文本解码。
                            if special_profile:  # 两项隐藏字段由后台按实际来源生成。
                                database = data.get("database", "")  # 来源仍由专属表单明确提交。
                                urls = {"GeneCards": "https://www.genecards.org/", "OMIM": "https://www.omim.org/", "TTD": "https://ttd.idrblab.cn/", "PharmGKB": "https://api.clinpgx.org/v1", "OTP": "https://platform.opentargets.org/"}  # 固定对应官方地址。
                                data["source_url"] = urls.get(database, "")  # 未知库仍由metadata拒绝。
                                existing = {row["database"]: row["availability"] for row in current_a02["tables"]["source_summary"]}  # 根据当前版本判断首次或替换。
                                reason = "替换当前来源" if existing.get(database) != "尚未提供资料" else "本研究首次上传"  # 自动说明仍进入运行历史。
                            changes = [dict(data, name=uploads["upload"]["name"], data=uploads["upload"]["data"])]  # 来源元信息由专用校验收紧。
                        elif self.path == "/disease-ttd":  # 实时重新获取TTD双文件。
                            changes = [fetch_ttd(data.get("query", "").strip())]  # 不用历史名单补全。
                        elif self.path == "/disease-pharmgkb":  # 按A00官方身份核对ClinPGx。
                            require(special_profile, "当前研究未启用PharmGKB研究级方案")  # 默认研究不能由此改变五库。
                            intake = workflow.result(manifest, manifest["current"]["A00"])["summary"]  # 只读取已批准登记证据。
                            mesh = intake.get("mesh_verification", {})  # 正式研究应已有NLM核对记录。
                            require(mesh.get("status") == "verified", "A00缺少已核对的MeSH疾病身份")  # 不用自由文本查询。
                            terms = [mesh.get("preferred_term", "")] + list(mesh.get("entry_terms", []))  # 依次核对首选词及Entry Term。
                            changes = [fetch_pharmgkb(terms)]  # API失败时不会产生新运行。
                            reason = "重新核对PharmGKB精确疾病实体" if any(row["database"] == "PharmGKB" and row["availability"] != "尚未提供资料" for row in current_a02["tables"]["source_summary"]) else "首次核对PharmGKB精确疾病实体"  # 零结果也算已有来源。
                        else:  # 只读官方OTP接口。
                            changes = [fetch_otp(data.get("disease_id", "").strip())]  # 完整分页取得后才提交。
                    run_disease(workflow, study_id, data.get("expected_a00", ""), data.get("expected_a02", ""), changes, reason, scope)  # 发布候选仍受下游门控。
                elif self.path == '/docking-automation-plan':  # 保存本研究明确科学方案并自动准备。
                    study_id = data.get('study', '')  # 服务端核验研究归属。
                    submit_docking_plan(workflow, data)  # 不要求用户编辑JSON。
                    self.redirect('/docking-automation?study=' + study_id)  # 后台运行期间立即返回页面。
                    return  # 不走重复通用跳转。
                elif self.path == '/docking-automation-start':  # 重试或继续明确后台阶段。
                    study_id = data.get('study', '')  # 科学上游由内核核验。
                    start_docking_job(workflow, study_id, data.get('stage', ''))  # 未批准准备不能执行对接。
                    self.redirect('/docking-automation?study=' + study_id)  # 查看真实进度。
                    return  # 避免重复提交。
                elif self.path == "/review":  # 保存人工复核决定。
                    study_id = data.get("study", "")  # 限定复核所属研究。
                    workflow.review(study_id, data.get("run", ""), data.get("decision", ""), data.get("reviewer", ""), data.get("note", ""), data.get("previous") or None)  # 先保存真实复核决定，旧页面冲突由内核拒绝。
                    review_message = "复核决定已保存"  # 仅保存时不隐式运行下游。
                    manifest = workflow.load(study_id)  # 新流程A00通过后必须自动生成两项。
                    reviewed = workflow.run(manifest, data.get("run", ""))  # 判断本次复核所属模块。
                    automatic_a00 = reviewed["module_id"] == "A00" and manifest.get("workflow_profile") in PREUPLOAD_PROFILES  # 新研究不要求用户再点一次继续。
                    if (data.get("after_review") == "continue" or automatic_a00) and data.get("decision") == "approved":  # 新A00或用户明确继续时自动接续。
                        try:  # 复核保存与后续计算是两个阶段，后者失败不能把前者显示成未保存。
                            review_message = auto_continue_message(continue_after_review(workflow, study_id))  # 自动运行到下一人工关口并返回实际状态。
                        except Exception as error:  # 自动模块可因资料、网络或本地依赖暂时失败。
                            review_message = "复核决定已保存；自动生成A01/A02未完成，可在本页重试。原因：" + str(error)  # 保留真实状态并给出可处理原因。
                    self.redirect("/study?study=" + study_id + "&message=" + quote(review_message, safe=""))  # 页面首屏显示本次处理结果。
                    return  # 避免后面的通用跳转丢失提示。
                elif self.path == "/review-a01-a02":  # 一次提交两个独立决定。
                    study_id = data.get("study", "")  # 绑定当前研究。
                    entries = {module: {"run_id": data.get(module.lower() + "_run", ""), "expected_review": data.get(module.lower() + "_previous", "") or None, "action": data.get(module.lower() + "_action", ""), "decision": data.get(module.lower() + "_decision", ""), "note": data.get(module.lower() + "_note", "")} for module in ("A01", "A02")}  # 两项字段明确分开。
                    workflow.review_a01_a02(study_id, entries, data.get("reviewer", ""))  # 原子保存，任一失败则两项都不生效。
                    manifest = workflow.load(study_id)  # 保存后判断是否同时通过。
                    if all(workflow.approved(manifest, manifest["current"][module]) for module in ("A01", "A02")):
                        try:  # 两条复核记录成功保存后，A03生成失败不回滚已确认的科学决定。
                            review_message = auto_continue_message(continue_after_review(workflow, study_id))  # 两项均通过后自动生成A03并停在复核关口。
                        except Exception as error:  # 将下游异常显示为可重试任务，不误称复核未保存。
                            review_message = "A01和A02复核决定已分别保存；A03自动生成未完成，可重试。原因：" + str(error)  # 页面准确区分保存与计算。
                    else:
                        review_message = "A01和A02复核决定已分别保存；尚未同时通过，不启动A03"  # 不重复运行已通过模块。
                    self.redirect("/study?study=" + study_id + "&message=" + quote(review_message, safe=""))  # 返回同一研究页面。
                    return  # 避免通用跳转覆盖提示。
                else:  # 不接受未明确设计的写入接口。
                    raise ContractError("不存在这个操作")  # 不提供任意命令执行。
                self.redirect("/study?study=" + study_id)  # 操作后查看最新保存结果。
            except (ContractError, ValueError, UnicodeError) as error:  # 明确说明输入或版本问题。
                self.send(page("未保存，请核对", '<p>' + text(error) + '</p><p>可返回上一页核对，版本冲突时请先刷新。</p>'), 400)  # 不自动降低校验要求。
            except Exception:  # 未预料失败不能返回保存成功。
                self.send(page("操作未完成", '<p>保存发生异常，请先刷新核对状态，再联系维护者检查。不要把本次操作视为已完成。</p>'), 500)  # 避免重复提交造成误解。

    return HTTPServer(("127.0.0.1", port), Handler)  # 同一进程顺序处理写入，文件锁继续防护其他进程。
