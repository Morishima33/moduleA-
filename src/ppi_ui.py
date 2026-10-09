# A04网页优先展示待核对事项，两轮明细折叠保存。
TABLES={"identity_adjustments":"官方证据核对后接入", "ppi_exclusions":"本次PPI暂不采用（保留A03及富集输入）", "mapping":"STRING身份映射", "identity_issues":"必须处理：STRING身份问题", "isolates":"已识别孤立节点（不参与中位数）", "edges":"全部合格关联边", "discarded_edges":"不合格边说明", "metrics":"全体参与节点的三项指标", "round1":"第一轮主候选", "round2":"第二轮参考子集", "thresholds":"两轮实际阈值"}  # 统一中文表名。
FIELDS={"identifiers":"补查官方编号", "decision":"用户授权依据", "target_id":"HGNC编号", "symbol":"基因", "string_id":"STRING编号", "reason":"原因", "returned":"实际返回名称", "source":"起点HGNC", "target":"终点HGNC", "score":"置信度", "source_row":"原始行", "degree":"Degree", "bc":"BC（未归一化）", "cc":"CC（WF修正）", "component":"连通分量", "round1":"第一轮入选", "round2":"第二轮入选", "round":"轮次", "population":"中位数总体节点数"}  # 指标口径明确。

def controls(view,item,token):  # 不另建科学状态。
    from web import hidden,table  # 复用转义和表格。
    from ppi import network_svg  # 图表同源。
    manifest=view["manifest"]  # 当前研究版本。
    if manifest.get("trashed"):  # 回收站只读。
        return ""  # 不展示写入入口。
    result=item.get("result")  # 无结果时不伪造。
    body=''  # 先呈现关键问题。
    if result:  # 显示已归档事实。
        omitted=result["summary"].get("本次PPI暂不采用数",0)  # 已批准缺口不混同未处理问题。
        if omitted:  # 正常结果也不能隐去覆盖限制。
            body+='<p class="notice">需要知悉：本次有'+str(omitted)+'项仅暂不参与PPI；仍保留在A03和富集输入。详见“本次PPI暂不采用”表。</p>'  # 不增加逐项签署。
        count=result["summary"]["身份待核验数"]  # 不能误作孤立节点。
        body+='<p class="notice">'+('必须处理：有'+str(count)+'个STRING身份问题，请先补充核对，当前不能交接。' if count else '重点复核第一轮主候选与两轮阈值；第二轮仅为参考，不需逐条审核所有连边。')+'</p>'  # 说明真实阻断。
        body+='<details><summary>查看PPI网络示意图</summary>'+network_svg(result["tables"])+'</details>'  # 不让复杂网络挤占首页。
    if not item["available"]:  # 建设可以完成，运行仍依赖用户复核。
        return body+'<p>请先在A03保存“通过，允许下游使用”，再运行PPI。</p>'  # 不要求先选对接成分。
    base=hidden("token",token)+hidden("study",manifest["study_id"])+hidden("expected_a03",manifest["current"].get("A03",""))+hidden("expected_a04",manifest["current"].get("A04",""))  # 版本绑定。
    body+='<p>人类；STRING 12.0功能网络；置信度≥0.9；不扩展邻居；全部有边分量参与。获取期间请勿重复点击。</p><form method="post" action="/ppi">'+base+'<label>A04运行原因<input name="reason" required maxlength="4000"></label><button>获取STRING并运行PPI两轮分析</button></form>'  # 主操作只有一个。
    body+='<details><summary>其他信息：离线来源包导入</summary><p>导入本工具格式A04.source.1或A04.source.2的完整STRING JSON包，包含映射、网络、查询参数和获取时间。必须对应本次交集；不能仅上传一张边表。资料包格式见项目templates/A04_STRING来源包说明.md。</p><form method="post" enctype="multipart/form-data" action="/ppi-upload">'+base+'<label>STRING来源包<input type="file" name="upload" accept=".json" required></label><label>导入依据及来源说明<input name="reason" required maxlength="4000"></label><button>导入来源包并运行PPI</button></form></details>'  # 离线与在线同一计算校验。
    return body  # 已完成结果仍须统一复核。
