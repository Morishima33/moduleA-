# 身份规则升级的只读对照；不发布研究、不签署复核。
import argparse  # 提供可重复调用入口。
import hashlib  # 绑定本次使用的代码字节。
import json  # 保存完整映射和对照。
from pathlib import Path  # 固定项目和治理目录。
from contracts import require, fingerprint  # 使用既有校验规则。
from storage import now  # 统一UTC时间。
from workflow import Workflow  # 读取有来源校验的研究包。
from hgnc import HgncMap  # 显式使用旧映射规则复算。
from normalization import preview, compute, impact_preview  # 与网页相同的新版预览。
from intersection import calculate  # 与A03相同的集合和排序算法。

def calculate_preview(results):  # 仅使用身份已明确的记录作影响预检。
    a, d = results["A01"][1], results["A02"][1]  # 两侧同一预览。
    return calculate(a["components"], a["herb_components"], a["normalized_compound_targets"], d["normalized_targets"], [x["herb"] for x in a["herb_summary"]], "HGNC")  # 不是人工批准的A03运行。

def audit(root, sid, prefix):  # 输出位置必须符合既定治理目录。
    require(prefix.parent.resolve() == (root / "governance").resolve(), "身份验收文件必须位于项目governance目录")  # 不散落到桌面或旧项目。
    paths = [prefix.with_suffix(suffix) for suffix in (".json", ".md")]  # 两种表现来自同一事实。
    require(not any(path.exists() for path in paths), "验收文件已存在，请明确使用新的版本名称")  # 不覆盖已生成审计。
    flow = Workflow(root)  # 仅调用只读预览。
    before = fingerprint(flow.load(sid))  # 固定原研究索引。
    manifest, bases, mapper, meta, scopes, results, stamp = preview(flow, sid)  # 同网页数据路径。
    old_mapper = HgncMap((root / "references/hgnc_complete_set_20260913.tsv").read_bytes(), rule="HGNC.resolve.2")  # 对照是此前本项目规则，不冒称旧Kimi计算。
    previous = {key:compute(base, old_mapper, key, scopes if key == "A02" else {}, False) for key,base in bases.items()}  # 同原始输入及同疾病范围。
    old_calc, new_calc = calculate_preview(previous), calculate_preview(results)  # 比较集合和成分名次。
    added = sorted({x["target_id"] for x in new_calc["sets"] if x["in_intersection"]} - {x["target_id"] for x in old_calc["sets"] if x["in_intersection"]})  # 新增交集有具体身份。
    stats = {key:{"before_genes":previous[key][0]["标准化基因数"], "after_genes":value[0]["标准化基因数"], "before_issue_groups":previous[key][0]["身份问题组数"], "after_issue_groups":value[0]["身份问题组数"], "remaining_categories":value[0]["身份分类"]} for key,value in results.items()}  # 分清基因数和问题组。
    unchanged = before == fingerprint(flow.load(sid))  # 确保未代改研究索引。
    require(unchanged, "只读核查期间研究索引已改变，请重新核查")  # 版本变更不报告旧统计为当前。
    payload = {"created_at":now(), "study_id":sid, "analysis_purpose":"workflow_test_readonly_audit", "source_runs":{key:base["run_id"] for key,base in bases.items()}, "source_result_files":{key:manifest["runs"][base["run_id"]]["result_file"] for key,base in bases.items()}, "preview_stamp":stamp, "mapping_source":meta, "rule_before":old_mapper.rule, "rule_after":mapper.rule, "code_sha256":{name:hashlib.sha256((root / "src" / name).read_bytes()).hexdigest() for name in ("hgnc.py", "identity_sources.py", "identity_queries.py", "normalization.py", "intersection.py", "identity_audit.py")}, "statistics":stats, "before_counts":old_calc["counts"], "after_counts":new_calc["counts"], "before_ranking":old_calc["ranking"], "after_ranking":new_calc["ranking"], "added_intersection":[mapper.records[x] for x in added], "impact":impact_preview(results, mapper), "mapping_details":{key:value[1]["identity_mapping"] for key,value in results.items()}, "remaining_issues":{key:value[1]["identity_issues"] for key,value in results.items()}, "study_index_unchanged":unchanged, "scope_is_unconfirmed_preview":True}  # 原始资料与归一依据全留存。
    with paths[0].open("x", encoding="utf-8") as stream:  # 不覆盖历史审计。
        json.dump(payload, stream, ensure_ascii=False, indent=2)  # 可机器复算的完整依据。
    rows = ["# A01/A02身份核对升级与只读验收", "", "本文件记录已获用户批准的身份规则升级。不是正式研究结果；未发布标准化运行，未代签范围、身份例外或总体复核。", "", "## 版本和来源", "", f"研究：{sid}", f"A01来源：{bases['A01']['run_id']}", f"A02来源：{bases['A02']['run_id']}", f"规则：{old_mapper.rule} → {mapper.rule}；新发布配置 normalized.test.2。", "HGNC、NCBI当前人类表、NCBI人类历史表与Ensembl/UniProt查询原文固定归档；查询快照当前固定identity_queries_20260913_v3.json，v1/v2保留为查询扩展历史。", "", "## 同批资料的规则对照", "", "| 模块 | 原标准基因数 | 新标准基因数 | 原问题组数 | 新未进入主集合组数 |", "|---|---:|---:|---:|---:|"]  # 面向专业复核的事实摘要。
    rows += [f"| {key} | {v['before_genes']} | {v['after_genes']} | {v['before_issue_groups']} | {v['after_issue_groups']} |" for key,v in stats.items()]  # 数字只来自实际计算。
    rows += ["", "新分类：", "", *[f"- {key}：{json.dumps(value['remaining_categories'], ensure_ascii=False)}" for key,value in stats.items()], "", f"已明确身份的交集预检：{old_calc['counts']['intersection']} → {new_calc['counts']['intersection']}。", "新增交集：" + "、".join(mapper.records[x]["symbol"] for x in added), "该对照保持输入和本病范围草案相同，比较的是本项目旧/新身份规则，不是重新获取的正式MeSH研究，也不是与旧Kimi的筛选政策混算。", "", "## 排序对照", "", "| 成分 | 原交集靶点数 | 新交集靶点数 | 原主排序 | 新主排序 |", "|---|---:|---:|---:|---:|"]  # 不把数量差当作疗效提升。
    old_ranks = {x["compound_id"]:x for x in old_calc["ranking"]}  # 对同一成分作前后比较。
    rows += [f"| {x['name']} | {old_ranks[x['compound_id']]['intersection_count']} | {x['intersection_count']} | {old_ranks[x['compound_id']]['main_rank']} | {x['main_rank']} |" for x in new_calc["ranking"][:8]]  # 展示主候选边界附近。
    rows += ["", "## 未解决项目与处理边界", "", "CALM1/P62158：官方记录为拆分至三个蛋白条目，候选涉及CALM1/2/3；不自动替换或扩展成三个基因边。网页置顶显示可能影响交集。", "SNORD33/ENSG00000252022：已查到当前人类Ensembl基因记录，但查询未给出可接入现行HGNC的明确跨库链接，不能仅凭同名强行确认。", "身份已查实但没有明确HGNC链接者单独保留；biological-region按生物区域保留，不冒充单基因。其他未查实名称已与本包HGNC及NCBI现行/历史表核对，不代表已逐个在GeneCards等原网站人工查证，也不代表生物学无效。缺少原库编号、家族性名称等需要补充原始资料。", "本轮没有新增模糊匹配、强制大写、评分阈值、亚型或多编号任取规则。只有实际已查询成功的官方证据参与确认；请求失败独立记录并可在新版本重试。", "", "## 网页和复用", "", "重启start.cmd，进入研究→A02→进入结果汇总与交接准备。分类汇总和可能影响交集的问题优先显示，完整明细折叠。明确接受本次范围及未进入集合的记录后才生成两侧待复核新版本；A01和A02分别通过后才可运行A03。", "归档时A01/A02共用同一HGNC及补充证据包，A03拒绝证据不一致的两侧输入。历史normalized.test.1继续按HGNC.resolve.2复算。", "可重复调用src/identity_audit.py：提供研究编号及governance中的新输出前缀；不修改研究。未来原始上传尽量保留基因符号、明确命名空间的编号、物种及来源。身份采集器支持批量和增量证据保存；陌生编号未查询时明确提示，不能说已全面查询。", "", "## 方法依据", "", "- HGNC官方多符号核对：https://www.genenames.org/help/multi-symbol-checker/", "- HGNChelper标准名优先与旧名纠正：https://cran.r-project.org/web/packages/HGNChelper/HGNChelper.pdf", "- NCBI Gene官方帮助：https://www.ncbi.nlm.nih.gov/books/NBK3840/", "- Ensembl历史批量接口：https://rest.ensembl.org/documentation/info/archive_id_post", "- Ensembl当前批量身份接口：https://rest.ensembl.org/documentation/info/lookup_post", "- UniProt历史蛋白记录：https://www.uniprot.org/uniprotkb/P62158/history", "", "完整映射、来源指纹、各问题原字段和全部排序见同名JSON。具体测试结论见governance/审阅与变更记录.md本次增补。"]  # 限制与调用路径明确。
    with paths[1].open("x", encoding="utf-8") as stream:  # 文字版本同样不可覆盖。
        stream.write("\n".join(rows) + "\n")  # 保持可读段落。
    return {"statistics":stats, "before_counts":old_calc["counts"], "after_counts":new_calc["counts"], "added_intersection":payload["added_intersection"], "files":[str(x) for x in paths]}  # 控制台不倾倒全量数据。

if __name__ == "__main__":  # 单一明确命令入口。
    parser = argparse.ArgumentParser(description="身份核对只读验收，不签署研究")  # 面向维护者。
    parser.add_argument("--study", required=True)  # 不猜当前研究。
    parser.add_argument("--output-prefix", required=True)  # 输出版本由调用者明确提供。
    arguments = parser.parse_args()  # 不隐式覆盖现有文件。
    print(json.dumps(audit(Path(__file__).resolve().parents[1], arguments.study, Path(arguments.output_prefix)), ensure_ascii=False, indent=2))  # 输出真实核查摘要。
