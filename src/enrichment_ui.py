# 富集界面只突出汇总，完整结果可分页和下载。
from contracts import require  # 查询不能跨模块伪用。
GROUPS=("BP","CC","MF","KEGG")  # 固定展示顺序。
FIELDS={"ID":"条目ID","Description":"功能或通路","GeneRatio":"命中数/有效输入数","BgRatio":"条目基因数/背景数","pvalue":"原始P值","p.adjust":"BH校正P值","qvalue":"qvalue原值","geneID":"命中Entrez编号","gene_symbols":"命中基因","Count":"命中数","group":"类别","background_count":"背景基因数","effective_count":"有效输入数","missing_count":"本类未注释数","tested_count":"实际检验条目数","significant_count":"显著条目数","display_count":"展示数","entrez_id":"Entrez编号","symbol":"基因","reason":"说明","Size":"条目大小"}  # 不混称p.adjust与qvalue。
TABLES={"group_summary":"四类结果汇总","identity_mapping":"基因编号对应","identity_issues":"必须处理：身份问题"}  # 主表名称。
for group in GROUPS:  # 全量表均有中文入口。
    for key,label in {"all":"全部实际检验","significant":"显著结果","display":"图中展示条目","skipped":"未检验原因","background":"完整背景","effective":"有效输入","missing":"本类无注释输入"}.items():  # 不隐藏分母来源。
        TABLES[group.lower()+"_"+key]=group+" · "+label  # 与保存字段对应。

def controls(view,item,token):  # 原模块卡片内运行，不另建入口。
    from web import hidden  # 复用转义。
    from enrichment_plot import chart  # 同源图表。
    body=''  # 图形按类折叠。
    if item.get("result"):  # 不展示虚构图。
        for g in GROUPS:  # 四类分别两图。
            body+='<details><summary>'+g+'：柱状图和气泡图</summary>'+''.join(chart(item["result"]["tables"][g.lower()+"_display"],g,k) for k in ("bar","bubble"))+'</details>'  # 可查看但不挤占复核区。
    manifest=view["manifest"]  # 使用实际研究索引。
    if manifest.get("trashed") or not item["available"]:  # 复用上游及只读限制。
        return body+'<p>需先通过A03交集；无需等待PPI。</p>'  # 不额外增设关口。
    fields=hidden("token",token)+hidden("study",manifest["study_id"])+hidden("expected_a03",manifest["current"].get("A03",""))+hidden("expected_a05",manifest["current"].get("A05",""))  # 防止旧页面重跑覆盖。
    return body+'<form method="post" action="/enrichment">'+fields+'<label>A05运行原因<input name="reason" required maxlength="4000"></label><button>运行GO与KEGG富集并生成图表</button></form><p>采用已冻结的人类注释、BH校正及10—500条目大小。首次获取可能需数分钟，请勿重复点击。</p>'  # 直接操作说明。

def detail_page(workflow,sid,query):  # 完整表分页，避免首页加载数万条。
    from web import page,table,text  # 共用中文页面与转义。
    manifest=workflow.load(sid)  # 只读当前研究。
    rid=query.get("run",[""])[0]  # 查询固定版本。
    require(rid in manifest["runs"] and workflow.run(manifest,rid)["module_id"]=="A05","不是本研究A05运行")  # 不跨模块读取。
    result=workflow.result(manifest,rid)  # 所有文件完整性检查。
    name=query.get("table",[""])[0]  # 固定结果表。
    require(name in TABLES and name in result["tables"],"富集表不存在")  # 不读任意文件。
    rows=result["tables"][name]  # 真实完整结果。
    index=max(0,int(query.get("page",["0"])[0]))  # 每页50条。
    subset=[{FIELDS.get(k,k):v for k,v in r.items()} for r in rows[index*50:(index+1)*50]]  # 仅页面分页，统计不变。
    base='/enrichment-table?study='+sid+'&amp;run='+rid+'&amp;table='+name+'&amp;page='  # 固定内部参数。
    nav=('<a href="'+base+str(index-1)+'">上一页</a> ' if index else '')+('<a href="'+base+str(index+1)+'">下一页</a>' if (index+1)*50<len(rows) else '')  # 不省略后续记录。
    return page(TABLES[name],'<p><a href="/study?study='+sid+'">返回研究</a> · 共'+str(len(rows))+'条 · 第'+str(index+1)+'页</p>'+nav+table(subset)+nav)  # 下载仍在原运行结果区。
