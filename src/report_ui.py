# A07双报告网页入口；只突出结论、研究线索和两份Word下载。
TABLES = {  # 为A07结构化表提供中文标题。
    "key_counts": "两版报告共同关键数量",  # 显示报告共用数字。
    "research_leads": "待复核研究线索",  # 显示最多三条线索。
    "limitations": "两版报告共同限制",  # 显示必须同步的边界。
    "report_files": "报告文件与指纹",  # 显示两份Word和索引。
    "report_figures": "专业报告图件与指纹",  # 显示六张图的SVG和PNG记录。
    "version_bindings": "上游运行与复核绑定",  # 显示可追溯版本。
}  # 结束A07表名。

def _download_links(item, study_id):  # 生成两份Word的醒目下载入口。
    from web import text  # 函数内导入以避免网页主模块循环导入。
    result = item.get("result")  # 只读取真实A07结果。
    if not result:  # 未生成时没有下载内容。
        return ""  # 返回空字符串。
    links = []  # 收集Word下载链接。
    for index, record in enumerate(result.get("files", [])):  # 文件索引与通用下载路由一致。
        if record.get("role") in ("detailed_report", "concise_report", "docking_task_archive"):  # 只在重点区显示两份Word。
            label = "下载专业详细版Word" if record.get("role") == "detailed_report" else ("下载PyMOL任务包" if record.get("role") == "docking_task_archive" else "下载临床简略版Word")  # 使用普通用户可理解的名称。
            links.append('<a style="display:inline-block;margin:6px 12px 6px 0;padding:8px 14px;background:#225f77;color:white;border-radius:6px;text-decoration:none" href="/file?study=' + text(study_id) + '&amp;run=' + text(result["run_id"]) + '&amp;index=' + str(index) + '">' + label + '</a>')  # 只传受控索引。
    return '<p>' + "".join(links) + '</p>' if links else ""  # 两个按钮放在同一行。

def focus(item, study_id):  # 生成A07必须人工核对的重点区。
    from web import table, text  # 函数内复用统一转义和表格组件。
    result = item.get("result")  # 获取当前A07结果。
    if not result:  # 未生成报告时没有结论可审核。
        return ""  # 由运行入口说明下一步。
    summary = result["summary"]  # 共同结论来自标准摘要。
    leads = result["tables"].get("research_leads", [])  # 最多三条线索来自共同事实包。
    body = '<div class="notice"><strong>本轮你只需核对这三项</strong><ol><li>共同结论是否准确、不过度解释；两份报告使用同一组事实。</li><li>下列研究线索及下一步核验建议是否可以保留。</li><li>两份Word中的研究用途、实际疾病来源及对接结构限制是否表达清楚。</li></ol>'  # 将人工任务限制在三项。
    body += '<p><strong>共同结论草稿：</strong>' + text(summary.get("共同结论草稿")) + '</p>'  # 在网页直接显示结论，不要求先下载文件。
    body += table(leads, ["线索", "支持事实", "下一步核验"])  # 在网页一次显示全部线索。
    body += _download_links(item, study_id)  # 将两份Word放在复核重点旁边。
    body += '<p><strong>没有异议：</strong>填写复核人和意见，选择“通过，允许下游使用”并保存一次。通过后该修订成为已复核双报告；若需改结论，请选择退回并在意见中写明要修改的文字。</p></div>'  # 给出明确操作说明。
    return body  # 返回A07重点区域。

def controls(view, item, token):  # 在A07卡片中提供生成或修订入口。
    from web import hidden  # 函数内复用统一隐藏字段组件。
    manifest = view["manifest"]  # 取得已核验研究索引。
    study_id = manifest["study_id"]  # 固定当前研究。
    body = _download_links(item, study_id)  # 已生成时在其他操作区也保留下载入口。
    if manifest.get("trashed"):  # 回收站研究只读。
        return body + '<p>研究在回收站中，恢复后才能生成新的报告修订。</p>'  # 不提供写入表单。
    if not item.get("available"):  # A00至A06未全部批准时不能生成。
        return body + '<p>需先完成并通过A00至A06全部必需模块。</p>'  # 明确真实门控。
    fields = hidden("token", token) + hidden("study", study_id) + hidden("expected_a07", manifest["current"].get("A07", ""))  # 防止旧页面覆盖新修订。
    label = "重新生成新的报告修订" if item.get("result") else "生成双报告与结论草稿"  # 已有报告时说明会新建版本。
    body += '<form method="post" action="/reports">' + fields + '<label>A07生成或修订原因<input name="reason" required maxlength="4000"></label><button>' + label + '</button></form>'  # 每次报告修订保留原因。
    body += '<p>两份Word共用同一份已复核数据、共同结论和限制。重新生成会建立新的A07运行和报告修订，不覆盖旧报告。</p>'  # 说明版本行为。
    return body  # 返回A07操作区。
