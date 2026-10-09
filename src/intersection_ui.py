# A03网页仅调用已归档结果与统一执行入口。
from contracts import ContractError  # 显示上游尚缺资料的具体原因。
from intersection_flow import payload_from, venn_svg, study_labels  # 不在网页另算科学指标。

def controls(workflow, view, item, token):  # 同一研究卡片显示交集与候选两个关口。
    from web import text, hidden, table  # 复用安全转义与表单工具。
    manifest = view["manifest"]  # 真实状态来自统一内核。
    if manifest.get("trashed", False):  # 回收站保持只读。
        return ""  # 不呈现写入操作。
    sid, current = manifest["study_id"], manifest["current"]  # 表单绑定明确版本。
    base = hidden("token", token) + hidden("study", sid)  # 不接受跨研究选择。
    if item["module_id"] == "A03":  # 交集可独立运行和复核。
        body = '<div style="max-width:650px">' + venn_svg(item["result"]["summary"], *study_labels(workflow, manifest, item["result"]["run_id"])) + '</div>' if item["result"] and "仅方剂靶点数" in item["result"]["summary"] else ""  # 数值与归档一致，旧运行只更新网页标签，不覆盖原图。
        if not item["available"]:  # 上游未通过时不生成可点击运行按钮。
            return body + '<p class="notice">下一步：等待A01、A02的标准化结果复核通过。现在不需要填写主候选，也不能使用尚未核验的疾病名单运行交集。</p>'  # 在运行位置明确解释等待条件。
        try:  # 正式运行前检查已确认标准身份接口是否具备。
            payload_from(*(workflow.result(manifest, current[key]) for key in ("A01", "A02")))  # 不从原始名称表替代。
        except ContractError as error:  # 硬条件不足不能靠点击复核绕过。
            return body + '<p class="notice"><strong>必须处理：上游交接资料不完整</strong><br>' + text(error) + '</p>'  # 不制造伪交集。
        return body + '<form method="post" action="/intersection">' + base + "".join(hidden("expected_" + key.lower(), current.get(key, "")) for key in ("A01", "A02", "A03")) + '<label>A03运行原因<input name="reason" required maxlength="4000"></label><button>运行A03交集与排序</button></form>'  # 运行不自动批准。
    if not item["available"]:  # 交集未批准时不能选择。
        return '<p class="muted">交集复核通过后，在此确认主候选；此关口只影响对接准备，不阻断PPI与富集。</p>'  # 解释分支边界。
    parent = workflow.result(manifest, current["A03"])  # 候选选自当前已批准交集。
    summary = parent["summary"]  # 不按展示顺序自行取前五。
    prompt = "存在截断处并列：请结合身份及研究依据选择，边界可选名额为" + str(summary["边界可选名额"]) + "。" if summary["截断处需要并列选择"] else "请核对建议候选身份；允许少于五个，不凑数。"  # 只突出实际存在的关键问题。
    heading = "已复核主候选（仅影响对接）；需要调整时另存新版本" if item["state"] == "approved" else "必须处理（仅影响对接）：主候选确认"  # 已批准时不重复催审。
    body = '<div class="notice"><strong>' + heading + '</strong><p>' + prompt + '完整主排序及边界建议见A03结果表。替换、少选或暂不选择，请在理由中说明；补充清单不需要现在逐项决定。</p></div>'  # 用户不审核所有正常网络边。
    saved = item.get("result") if item.get("state") != "stale" else None  # 不将失效上游的候选自动带入新版本。
    selected_ids = [row["compound_id"] for row in saved["tables"]["selected"]] if saved else []  # 回填本版本实际保存的选择。
    values = "\n".join(selected_ids)  # 每行一个编号，与现有表单一致。
    body += '<details><summary>查看可选成分及两种排序</summary>' + table([{"成分编号": row["compound_id"], "成分名称": row["name"], "来源药味": row["herbs"], "交集靶点数": row["intersection_count"], "Degree": row["mixed_degree"], "已选择": row["compound_id"] in selected_ids} for row in parent["tables"]["ranking"] if row["in_network"]]) + '</details>'  # 在选择位置提供身份参考，无需回文件抄编号。
    form = '<form method="post" action="/intersection-select">' + base + hidden("expected_a03", current["A03"]) + hidden("expected_select", current.get("A03_SELECT", ""))  # 防止旧页面覆盖选择。
    form += '<label>主候选成分编号（通常最多5个；经人工决定可纳入截断并列和未覆盖药味最高位，每行一个）<textarea name="selected" maxlength="2000">' + text(values) + '</textarea></label><label>候选核对人<input name="reviewer" required maxlength="200"></label><label>候选选择、并列或替换理由<textarea name="reason" required maxlength="4000"></textarea></label><label><input type="checkbox" style="width:auto" name="confirmed" value="yes" required>已核对所选成分身份；未选、扩展或替换的原因已说明</label><button>保存主候选版本</button><p class="muted">超过5个时，程序只接受截断并列及未覆盖药味最高位成分；保存后仍须总体复核。</p></form>'  # 不自动签署通过。
    return body + '<details><summary>填写或修改主候选</summary>' + form + '</details>'  # 已选择后不重复强迫填写。

def detail_page(workflow, study_id, query):  # 对大集合及来源表提供分页检索。
    from web import text, table, page  # 复用中文页面和转义。
    from urllib.parse import urlencode  # 安全组成分页链接。
    from contracts import require  # 拒绝未知表与运行。
    from intersection_flow import TABLE_LABELS, FIELD_LABELS  # 使用同一中文字段。
    manifest = workflow.load(study_id)  # 限定本研究。
    rid = query.get("run", [""])[0]  # 链接固定具体运行，避免看错版本。
    run = workflow.run(manifest, rid)  # 验证运行及指纹。
    require(run["module_id"] in ("A03", "A03_SELECT"), "不是A03结果")  # 不开放任意文件。
    result = workflow.result(manifest, rid)  # 验证关联资料。
    name = query.get("table", ["ranking"])[0]  # 指定已归档表。
    require(result and name in result["tables"], "结果表不存在")  # 不显示假的空集。
    search = query.get("q", [""])[0].strip()[:2000]  # 搜索仅影响显示。
    rows = [row for row in result["tables"][name] if not search or search.casefold() in " ".join(map(str, row.values())).casefold()]  # 不改变科学结果。
    count = max(1, (len(rows) + 49) // 50)  # 每页50条仅为界面配置。
    number = min(count, max(1, int(query.get("page", ["1"])[0])))  # 页码越界收敛。
    body = '<p><a href="/study?study=' + text(study_id) + '">返回研究</a></p><p class="notice">' + ("当前有效版本" if workflow.active(manifest, rid) else "历史或失效版本，仅供追溯") + '；查询不会改变纳入范围或排序。</p>'  # 旧页明确标识。
    body += '<form method="get" action="/intersection-table"><input type="hidden" name="study" value="' + text(study_id) + '"><input type="hidden" name="run" value="' + text(rid) + '"><input type="hidden" name="table" value="' + text(name) + '"><label>搜索成分、药味、基因或来源<input name="q" value="' + text(search) + '"></label><button>查询明细</button></form>'  # 不要求用户回文件查找。
    body += '<p>共' + str(len(rows)) + '条匹配，第' + str(number) + '/' + str(count) + '页。</p>' + table([{FIELD_LABELS.get(k, k): v for k, v in row.items()} for row in rows[(number - 1) * 50:number * 50]])  # 完整表仍保留下载。
    for target, label in ((number - 1, "上一页"), (number + 1, "下一页")):  # 保留搜索和运行身份。
        if 1 <= target <= count:  # 不创建越界链接。
            body += '<a href="/intersection-table?' + text(urlencode({"study": study_id, "run": rid, "table": name, "q": search, "page": target})) + '">' + label + '</a> '  # 只读查询地址。
    return page(TABLE_LABELS.get(name, name), body)  # 表名有明确中文含义。
