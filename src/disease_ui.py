# 本文件只显示A02候选和复核表单，不自行决定科学纳入或修改数据。
from urllib.parse import urlencode  # 生成安全的本机分页链接。
from disease import DATABASES, FORMATS, SCOPES, TABLE_LABELS, FIELD_LABELS  # 默认来源继续服务历史研究。
from normalization import TABLE_NAMES as NORMALIZATION_TABLES, FIELD_NAMES as NORMALIZATION_FIELDS  # 新标准化表的显示名称。
from contracts import require  # 校验请求的表与条目。
COPD_NAMES = {"copd", "慢性阻塞性肺疾病", "慢阻肺", "chronic obstructive pulmonary disease", "pulmonary disease, chronic obstructive"}  # 仅用于限制明确的COPD历史资料入口。

def manual_uploads(base, disease, result):  # 三库按用户决定提供固定手动入口。
    from web import text, hidden  # 复用安全字段和中文展示。
    profile = result["summary"].get("source_profile", "A02.source_profile.default.1") if result else "A02.source_profile.default.1"  # 只对当前结果启用研究级例外。
    special = profile in ("A02.source_profile.1", "A02.source_profile.2", "A02.source_profile.3")  # 新五库方案隐藏可自动生成的字段。
    if profile == "A02.source_profile.3":  # 新版流程测试保留三库详细文件补充入口。
        specs = {"GeneCards": (("genecards_csv", "detailed_txt"), "支持GeneCards官方搜索结果CSV；原始评分完整保留。"), "OMIM": (("omim_xlsx", "omim"), "支持OMIM Gene Map .xlsx或TSV。"), "TTD": (("detailed_txt",), "人工详细文件将成为当前来源，自动结果仍保留在历史版本。"), "PharmGKB": (("detailed_txt",), "人工详细文件将成为当前来源，自动结果仍保留在历史版本。") }  # 同库不与自动结果做并集。
    elif special:  # 历史新五库研究保持原入口。
        specs = {"GeneCards": (("genecards_csv", "tsv", "names"), "支持官方搜索结果CSV；保留原始关联评分，不新增阈值。"), "OMIM": (("omim_xlsx", "omim", "tsv"), "支持OMIM Gene Map .xlsx、TSV或通用TSV；Excel自动查找唯一合法表头。"), "PharmGKB": (("tsv", "names"), "官方API无精确实体时记录真实零结果；这里保留官方导出文件备用入口。") }  # 格式兼容不改变历史科学方案。
    else:  # 默认历史五库入口保持不变。
        specs = {"GeneCards": (("tsv", "names"), "推荐带相关性评分的通用TSV；只有逐行名单也可收集，缺评分不会补0。"), "OMIM": (("omim", "tsv"), "支持OMIM Gene Map TSV或通用TSV；保留基因、表型及表型编号。"), "DisGeNET": (("tsv", "names"), "推荐带原始评分与疾病编号的通用TSV；逐行名单仅保存可取得的信息。") }  # 默认方案不受影响。
    states = {row["database"]: row for row in result["tables"]["source_summary"]} if result else {}  # 当前资料来自真实结果。
    template = '/disease-detailed-template' if profile == "A02.source_profile.3" else '/disease-template'  # 新版使用严格详细字段模板。
    body = '<h3>手动提供数据库资料</h3><p>在对应数据库下载后，使用下面的专属入口上传。每次上传只更新这一库，其他库和历史版本保留。<a href="' + template + '">下载字段模板</a>。OMIM支持.xlsx；其他未知Excel或PDF不自动猜列。</p>'  # 给出实际可用方式。
    for db, (formats, hint) in specs.items():  # 固定数据库，不要求反复选择来源库。
        state = states.get(db, {})  # 未上传不能显示为零靶点。
        status = (state.get("availability", "尚未上传") + '；' + str(state.get("records", 0)) + '条；获取日期：' + str(state.get("retrieved_at", "")) + '；版本：' + str(state.get("version", ""))) if state else "尚未上传"  # 明确缺失、零结果与已有资料。
        body += '<details><summary>' + db + '：上传或替换资料</summary><p>' + text(status) + '</p><p>' + hint + '</p><form method="post" enctype="multipart/form-data" action="/disease-upload">' + base + hidden("database", db)  # 复用原上传校验和版本门控。
        body += '<label>文件格式<select aria-label="' + db + '文件格式" name="format">' + ''.join('<option value="' + fmt + '">' + text(FORMATS[fmt]) + '</option>' for fmt in formats) + '</select></label><label>文件编码<select aria-label="' + db + '文件编码" name="encoding"><option value="utf-8-sig">UTF-8</option><option value="gbk">GBK</option></select></label><label>' + db + '资料文件<input type="file" name="upload" required></label>'  # 支持格式在上传前讲清。
        fields = (("query", "实际检索词或疾病名称", disease), ("retrieved_at", "资料下载日期", ""), ("version", "数据库版本（未知填未知）", "")) if special else (("query", "实际检索词或疾病名称", disease), ("retrieved_at", "资料下载日期", ""), ("version", "数据库版本（未知填未知）", ""), ("source_url", "来源网址或出处说明", ""), ("reason", "本次上传或替换原因", ""))  # 本次研究的来源和原因由后台自动记录。
        for key, title, value in fields:  # 真实日期和版本不由程序编造。
            body += '<label>' + db + ' ' + title + '<input name="' + key + '" value="' + text(value) + '" required maxlength="2000"></label>'  # 保留必要追溯说明。
        if db == 'GeneCards':  # 检索语法和导出范围只据实记录。
            body += '<label>检索词是否加引号<select name="query_quoted"><option value="unknown">不确定</option><option value="no">未加引号</option><option value="yes">加引号</option></select></label><label>导出是否包含本次全部搜索结果<select name="export_completeness"><option value="unknown">不确定</option><option value="complete">已核对为全部搜索结果</option><option value="partial">仅部分搜索结果</option></select></label><p>完整导出仅指本次搜索结果，不代表整个数据库；未知不自动改为完整。</p>'  # 不要求用户猜测未知信息。
        body += '<label><input type="checkbox" style="width:auto" name="confirmed" value="yes" required>确认这份' + db + '资料用于当前研究候选核查</label><button>上传并整理' + db + '</button></form></details>'  # 不自动批准疾病集合。
    return body  # 所有入口属于同一A02卡片。


def batch_scope_form(groups, base):  # 全量条目在同一个表单完成，不需要翻页提交。
    from web import text  # 所有来源文字进行安全转义。
    body = '<section><h2>集中审查全部疾病条目</h2><p>共' + str(len(groups)) + '个条目，下面包含全部来源，不受上方搜索和分页影响。先选统一处理，再调整例外，最后一次确认。可用浏览器Ctrl+F查找疾病名称。首版仅纳入本病直接条目；亚型和范围外条目不纳入，待核验不自动处理。全部确认不等于全部纳入。</p><form method="post" action="/disease-scope-batch">' + base  # 提交固定全量版本。
    body += '<label>未单独调整条目的统一处理<select aria-label="未单独调整条目的统一处理" name="batch_default"><option value="keep">保留每条已有决定（首次为待核验）</option>' + ''.join('<option value="' + key + '">' + label + '</option>' for key, label in SCOPES.items()) + '</select></label>'  # 默认不改变科学意见。
    body += '<div style="overflow:auto;max-height:65vh"><table><thead><tr><th>来源</th><th>疾病或表型</th><th>疾病编号</th><th>记录数</th><th>原决定</th><th>本次决定</th></tr></thead><tbody>'  # 长表集中滚动而非逐页保存。
    for row in groups:  # 包括全部942或其他数量的实际分组。
        body += '<tr>' + ''.join('<td>' + text(value) + '</td>' for value in (row['database'], row['disease_term'], row['disease_id'], row.get('records', ''), SCOPES[row['scope']])) + '<td><select aria-label="条目' + row['scope_id'] + '本次决定" name="entry_' + row['scope_id'] + '"><option value="inherit">采用上方统一处理</option>' + ''.join('<option value="' + key + '">' + label + '</option>' for key, label in SCOPES.items()) + '</select></td></tr>'  # 例外优先于统一选择。
    body += '</tbody></table></div><label>本批复核人<input name="reviewer" required maxlength="200"></label><label>本批范围复核依据<textarea name="note" required maxlength="4000"></textarea></label><p>依据会随每条决定留存；特殊条目的理由可在此注明名称或编号。待核验仍保持待核验，不会自动放行下游。</p><label><input style="width:auto" type="checkbox" name="confirmed" value="yes" required>确认提交整张表的统一处理及例外决定</label><button>一次保存全部范围决定</button></form></section>'  # 人工明确提交，不代签。
    return body  # 一个批次生成一个可追溯版本。


def controls(workflow, view, token):  # 在统一研究页面提供资料获取入口。
    from web import text, hidden  # 运行时复用公共网页工具，避免初始化循环。
    manifest = view["manifest"]  # 来源操作绑定本研究当前版本。
    item = next(item for item in view["modules"] if item["module_id"] == "A02")  # 使用内核实际状态。
    if manifest.get("trashed", False) or not item["available"]:  # 不给只读或未通过登记的研究写入入口。
        return ""  # 等待上游或恢复研究。
    sid = manifest["study_id"]  # 稳定研究编号。
    base = hidden("token", token) + hidden("study", sid) + hidden("expected_a00", manifest["current"]["A00"]) + hidden("expected_a02", manifest["current"].get("A02", ""))  # 服务端再次校验版本。
    body = '<p class="notice">A02当前只整理候选。已确认暂不新增数值评分阈值，原始评分全部保留；可以记录复核意见，但不能批准给A03使用。首版不纳入亚型。相应条目仍保留溯源，后期通过新版本扩展。同库新资料会替换当前来源，旧版本保留。</p>'  # 科学阶段明确区分。
    if item["result"] and item["result"]["summary"].get("namespace") == "HGNC":  # 已生成标准化结果时不继续声称只能候选。
        body = '<p class="notice">标准化结果已生成。请在本卡片的决定中选择通过，允许下游使用，并保存复核决定；A01同样通过后，可运行A03。原始来源及例外均已留存。</p>'  # 同时适用于测试和正式版本。
    intake = view["modules"][0]["result"]["summary"]  # 当前A00保存研究对象及官方疾病身份。
    disease = intake["disease"]  # 中文名称用于页面显示。
    mesh = intake.get("mesh_verification") if isinstance(intake.get("mesh_verification"), dict) and intake["mesh_verification"].get("status") == "verified" else None  # 历史研究可以没有新字段。
    query_term = mesh["preferred_term"] if mesh else disease  # 三库表单优先预填用户确认的MeSH标准词。
    active_databases = item["result"]["summary"].get("databases", list(DATABASES)) if item["result"] else list(DATABASES)  # 页面只显示本运行实际方案。
    special = item["result"] and item["result"]["summary"].get("source_profile") in ("A02.source_profile.1", "A02.source_profile.2", "A02.source_profile.3")  # 三个新五库方案使用相同页面。
    if mesh:  # 任意新疾病显示实际归档的官方身份。
        body += '<p class="notice"><strong>正式研究疾病身份：' + text(mesh["preferred_term"]) + '（MeSH：' + text(mesh["mesh_id"]) + '）</strong><br>本次使用MeSH ' + text(mesh["mesh_year"]) + '并已保存NLM核对证据。下面各库仍须填写实际采用的检索词或原生编号；预填MeSH词可以修改为该库真实查询写法。</p>'  # 不声称所有数据库直接支持MeSH编号。
    elif disease.strip().casefold() in COPD_NAMES:  # 历史COPD测试继续显示已知标准概念。
        body += '<p class="notice"><strong>正式研究检索标准：Pulmonary Disease, Chronic Obstructive（MeSH：D029424）</strong><br>请以此标准词重新检索并下载正式资料。<a href="https://www.ncbi.nlm.nih.gov/mesh/68029424" target="_blank" rel="noopener noreferrer">核对NLM标准词</a>。当前Kimi三库旧资料仅用于流程测试，不能描述为MeSH检索结果。OTP编号和TTD原生名称属于各库查询方式，实际检索词必须如实填写；跨库对应关系仍须核对。</p>'  # 区分疾病标准与实际查询记录。
    else:  # 未核对的疾病不自动猜测MeSH编号。
        body += '<p class="notice">本研究是新功能接入前建立的历史登记，尚无归档的MeSH核对证据。若要作为正式研究使用，请先修订A00并填写MeSH标准词及编号。</p>'  # 不把旧登记冒充正式身份。
    if special:  # 首屏突出本次采用的五库及真实状态。
        states = {row["database"]: row["availability"] for row in item["result"]["tables"]["source_summary"]}  # 状态来自已归档结果。
        body += '<p class="notice"><strong>本研究五库：' + '、'.join(active_databases) + '</strong><br>' + '；'.join(db + '：' + states.get(db, '尚未提供资料') for db in active_databases) + '。PharmGKB为零时表示无精确本病实体，不是接口失败。</p>'  # 用户无需展开明细判断缺库。
    body += '<details><summary>资料获取与更新</summary>'  # 默认折叠次要资料操作。
    body += manual_uploads(base, query_term, item["result"])  # 三个手动来源预填已核对标准词。
    body += '<h3>资料获取与更新</h3><p>正式MeSH研究会自动准备可公开获取的来源；原始响应及文件随运行保存。联网操作请等待，不要重复点击。</p>'  # 说明自动范围和留存。
    if not mesh and disease.strip().casefold() in COPD_NAMES:  # 只有原测试研究显示历史资料入口，正式研究不得误用。
        body += '<details><summary>本次COPD测试：导入Kimi三库资料</summary><p>仅导入GeneCards、OMIM、DisGeNET；保持当前OTP和TTD来源不变。缺评分和派生来源保留说明，不是新检索结果。</p><form method="post" action="/disease-import">' + base + '<label>历史资料导入原因<input name="reason" required maxlength="4000"></label><label><input style="width:auto" type="checkbox" name="confirmed" value="yes" required>确认将Kimi三库COPD资料用于本次测试候选核查</label><button>导入Kimi三库候选</button></form></details>'  # 用户明确选择历史资料。
    body += '<details><summary>其他格式与其他库上传（高级入口）</summary><p>支持名单、OMIM表、旧JSON或通用TSV。请先选择实际格式；同库旧范围决定不会自动套到新文件。<a href="/disease-template">下载通用TSV字段模板</a></p><form method="post" enctype="multipart/form-data" action="/disease-upload">' + base  # 上传复用同一研究和模块。
    body += '<label>来源数据库<select aria-label="来源数据库" name="database">' + "".join('<option>' + text(db) + '</option>' for db in active_databases) + '</select></label><label>文件格式<select aria-label="文件格式" name="format">' + "".join('<option value="' + key + '">' + text(label) + '</option>' for key, label in FORMATS.items()) + '</select></label>'  # 不显示本研究未启用的库。
    body += '<label>文件编码<select aria-label="文件编码" name="encoding"><option value="utf-8-sig">UTF-8</option><option value="gbk">GBK</option></select></label><label>资料文件<input type="file" name="upload" required></label>'  # 原始文件按选定编码解析。
    advanced_fields = (("query", "实际检索词或疾病名称"), ("retrieved_at", "资料获取日期"), ("version", "数据库版本（未知可填未知）")) if special else (("query", "实际检索词或疾病名称"), ("retrieved_at", "资料获取日期"), ("version", "数据库版本（未知可填未知）"), ("source_url", "来源网址或出处说明"), ("reason", "本次上传原因"))  # 研究级例外只隐藏已可自动留痕字段。
    for key, title in advanced_fields:  # 必要元信息由使用者填写。
        body += '<label>' + title + '<input name="' + key + '" required maxlength="2000"></label>'  # 不自动声称已知数据库版本。
    body += '<label><input style="width:auto" type="checkbox" name="confirmed" value="yes" required>确认这份资料用于当前研究候选核查</label><button>上传并整理候选</button></form></details>'  # 不意味着已经批准疾病关联。
    body += '<details><summary>在线获取OTP本病直接关联</summary><p>先在OTP核对疾病编号与名称。本入口明确关闭间接关联，不设分数阈值；返回后仍需复核疾病范围。失败不会发布部分名单。</p><form method="post" action="/disease-otp">' + base + '<label>OTP疾病编号<input name="disease_id" required value="' + ('MONDO_0005002' if disease.strip().casefold() in COPD_NAMES else '') + '" placeholder="例如 MONDO_0005002"></label><label>OTP查询原因<input name="reason" required maxlength="4000"></label><label><input style="width:auto" type="checkbox" name="confirmed" value="yes" required>确认用这个编号查询本研究候选资料</label><button>获取OTP直接关联候选</button></form></details>'  # 用户明确触发联网，不自动刷新旧结果。
    query = query_term if mesh else ("Chronic obstructive pulmonary disease" if disease.strip().casefold() in COPD_NAMES else "")  # 正式研究预填已核对MeSH词，用户仍记录TTD真实查询写法。
    body += '<details><summary>在线重新获取TTD官方资料</summary><p>下载完整靶点身份与疾病映射文件；按明确疾病名称检索候选，不按临床阶段筛除、不把缺评分补0。实际版本以下载文件头为准。</p><form method="post" action="/disease-ttd">' + base + '<label>TTD疾病英文名称<input name="query" required maxlength="2000" value="' + text(query) + '"></label><label>TTD本次运行原因<input name="reason" required maxlength="4000"></label><label><input type="checkbox" style="width:auto" name="confirmed" value="yes" required>确认从TTD官方重新获取本病候选</label><button>重新获取TTD并整理候选</button></form></details>'  # 不导入Kimi历史。
    if special:  # 本次研究提供官方精确实体重查入口和文件备用入口。
        body += '<details><summary>在线核对PharmGKB / ClinPGx精确疾病实体</summary><p>系统依次核对A00保存的MeSH首选词和Entry Term；只有唯一精确实体才读取直接Gene关系。不会用范围更宽的Rhinitis补齐。</p><form method="post" action="/disease-pharmgkb">' + base + '<label><input type="checkbox" style="width:auto" name="confirmed" value="yes" required>确认按已核对MeSH词查询ClinPGx</label><button>查询并保存PharmGKB状态</button></form></details>'  # 查询失败不会发布部分结果。
    return body + "</details>"  # 结束默认折叠的资料更新区域。

def detail_page(workflow, study_id, query, token):  # 大表分页和疾病条目复核入口。
    from web import text, hidden, table, page  # 复用公共转义、表格与页面样式。
    view = workflow.view(study_id)  # 数据来源统一，不从CSV猜当前运行。
    item = next(item for item in view["modules"] if item["module_id"] == "A02")  # 查找当前A02。
    require(item["result"] is not None, "A02尚无候选结果")  # 不伪造空页面。
    result, manifest = item["result"], view["manifest"]  # 固定本次读到的结果。
    name = query.get("table", ["candidate_records"])[0]  # 只允许已定义表名。
    require(name in result["tables"], "未知A02结果表")  # 路由不接收文件路径。
    search = query.get("q", [""])[0].strip()[:2000]  # 搜索不改变实际保存的候选或统计。
    database = query.get("database", [""])[0]  # 来源库筛选仅用于展示。
    active_databases = tuple(result["summary"].get("databases", DATABASES))  # 明细筛选服从当前运行方案。
    require(database in ("",) + active_databases, "未知来源数据库")  # 不产生误导的空库。
    rows = result["tables"][name]  # 整张表仍留在研究包。
    rows = [row for row in rows if (not database or row.get("database") == database) and (not search or search.casefold() in " ".join(map(str, row.values())).casefold())]  # 只过滤当前页面显示。
    number = max(1, int(query.get("page", ["1"])[0]))  # 页数不影响科学筛选。
    count = max(1, (len(rows) + 49) // 50)  # 固定每页50条是展示参数。
    number = min(number, count)  # 超出页码返回末页。
    body = '<p><a href="/study?study=' + study_id + '">返回研究与模块复核</a></p><p class="notice">候选资料，不是正式疾病主集合。搜索与翻页只改变显示；范围复核会另存新A02版本并保留原记录。</p>'  # 不混淆显示和重新运行。
    if name == "scope_groups" and not manifest.get("trashed", False) and item["state"] != "stale":  # 集中表使用全量原表，独立于搜索结果。
        base = hidden("token", token) + hidden("study", study_id) + hidden("expected_a00", manifest["current"]["A00"]) + hidden("expected_a02", item["run"]["run_id"])  # 防止旧页面覆盖新意见。
        body += batch_scope_form(result["tables"]["scope_groups"], base)  # 把主要入口放在分页明细前。
    body += '<details><summary>查询明细与单条补充复核</summary>'  # 次要分页与旧单条入口默认收起。
    body += '<form method="get" action="/disease">' + hidden("study", study_id) + hidden("table", name) + '<label>搜索名称、疾病或条目编号<input name="q" value="' + text(search) + '"></label><label>筛选来源<select aria-label="筛选来源" name="database"><option value="">全部</option>' + "".join('<option' + (' selected' if db == database else '') + '>' + db + '</option>' for db in active_databases) + '</select></label><button>查看</button></form>'  # 用户不用打开原始文件查找。
    selected = rows[(number - 1) * 50:number * 50]  # 未显示的行仍能翻页和下载。
    translated = [{NORMALIZATION_FIELDS.get(key, FIELD_LABELS.get(key, key)): SCOPES.get(value, value) if key == "scope" else value for key, value in row.items()} for row in selected]  # 范围决定显示中文。
    body += '<p>匹配' + str(len(rows)) + '条，第' + str(number) + '/' + str(count) + '页。</p>' + table(translated)  # 明确本页不是全量。
    for target, label in ((number - 1, "上一页"), (number + 1, "下一页")):  # 前后页保留筛选条件。
        if 1 <= target <= count:  # 不生成越界页。
            body += '<a href="/disease?' + text(urlencode({"study": study_id, "table": name, "q": search, "database": database, "page": target})) + '">' + label + '</a> '  # 链接只指向本机。
    if name == "scope_groups" and not manifest.get("trashed", False) and item["state"] != "stale":  # 只对有效当前条目提供复核。
        body += '<section><h2>记录一个疾病条目的范围意见</h2><p>选择当前页条目，决定适用于该条目对应的全部原始行。无法判断时保留待核验，不自动纳入亚型。</p><form method="post" action="/disease-scope">' + hidden("token", token) + hidden("study", study_id) + hidden("expected_a00", manifest["current"]["A00"]) + hidden("expected_a02", item["run"]["run_id"])  # 表单针对明确版本。
        body += '<label>当前页疾病条目<select aria-label="当前页疾病条目" name="scope_id">' + "".join('<option value="' + row["scope_id"] + '">' + text(row["database"] + " · " + row["disease_term"] + " · " + row["disease_id"]) + '</option>' for row in selected) + '</select></label>'  # 不要求用户手抄长编号。
        body += '<label>疾病范围决定<select aria-label="疾病范围决定" name="scope">' + "".join('<option value="' + key + '">' + label + '</option>' for key, label in SCOPES.items()) + '</select></label><label>范围复核人<input name="reviewer" required maxlength="200"></label><label>范围复核理由及依据<textarea name="note" required maxlength="4000"></textarea></label><button>保存范围意见并形成新版本</button></form></section>'  # 留下可追溯的人为判断。
    return page(NORMALIZATION_TABLES.get(name, TABLE_LABELS.get(name, name)), body + "</details>")  # 页面标题明确说明是候选或范围表。
