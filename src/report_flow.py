# A07双报告生成与可追溯结论草稿；两份Word只读取同一份结构化事实包。
from pathlib import Path  # 统一处理研究包内的报告路径。
from datetime import datetime  # 将归档时间转换为报告日期。
import json  # 保存可复算的报告索引。
from docx import Document  # 生成可编辑的Word报告。
from docx.enum.section import WD_SECTION  # 控制报告分节方式。
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT  # 统一表格布局。
from docx.enum.text import WD_ALIGN_PARAGRAPH  # 控制标题、正文和图注对齐。
from docx.oxml import OxmlElement  # 设置Word表格底色和重复表头。
from docx.oxml.ns import qn  # 设置中文字体及OOXML属性。
from docx.shared import Cm, Inches, Pt, RGBColor  # 设置页面、字号和配色。
from contracts import require, check_result  # 复用统一输入输出校验。
from storage import file_record, now, read_json, verified_file, write_json, write_lock  # 沿用项目归档规则。
from report_figures import generate_report_figures  # 由运行表直接生成本次报告图件。
from docking_contract import receptor_limitation_table  # 热图后直接呈现每个受体的结构限制与解释边界。

CONFIG = {  # 固定当前报告规则；历史运行继续按自身保存的配置校验。
    "schema_version": "A07.report.config.12",  # 第十二版绑定用户已审核的同源展示图并区分图面与原计划。
    "template_version": "A07.double_report.12",  # 结构保持原模板，补充复用留痕。
    "detailed_report": "专业详细版",  # 明确详细报告用途。
    "concise_report": "临床简略版",  # 明确简略报告用途。
    "concise_target_pages": 2,  # 记录大纲约定的简略版目标页数。
    "maximum_research_leads": 3,  # 不为凑数生成超过三条线索。
    "conclusion_review_required": True,  # 结论必须经过A07人工复核。
    "association_score_generated": False,  # 不生成未验证的关联总分或疗效概率。
    "heatmap_metadata_name": "A06结合能热图_红蓝渐变_v5_20260930.json",  # 兼容当前COPD流程测试的已审定热图索引。
    "comparison_storage": "revision_scoped",  # 差异说明只保存在本次报告修订目录，禁止共享文件被后续覆盖。
}  # 结束首版报告配置。

METHOD_REFERENCES = [  # 报告列出本次方法可核查的主要依据。
    {"编号": "R1", "文献": "Szklarczyk D, et al. The STRING database in 2023: protein-protein association networks and functional enrichment analyses for any sequenced genome of interest. Nucleic Acids Research. 2023;51(D1):D638-D646.", "链接": "https://doi.org/10.1093/nar/gkac1000"},  # STRING方法来源。
    {"编号": "R2", "文献": "Wu T, et al. clusterProfiler 4.0: A universal enrichment tool for interpreting omics data. The Innovation. 2021;2(3):100141.", "链接": "https://doi.org/10.1016/j.xinn.2021.100141"},  # 富集工具方法来源。
    {"编号": "R3", "文献": "Benjamini Y, Hochberg Y. Controlling the false discovery rate: a practical and powerful approach to multiple testing. Journal of the Royal Statistical Society Series B. 1995;57(1):289-300.", "链接": "https://doi.org/10.1111/j.2517-6161.1995.tb02031.x"},  # 多重检验校正来源。
    {"编号": "R4", "文献": "Trott O, Olson AJ. AutoDock Vina: improving the speed and accuracy of docking with a new scoring function, efficient optimization, and multithreading. Journal of Computational Chemistry. 2010;31(2):455-461.", "链接": "https://doi.org/10.1002/jcc.21334"},  # Vina原始方法来源。
    {"编号": "R5", "文献": "Eberhardt J, et al. AutoDock Vina 1.2.0: New docking methods, expanded force field, and Python bindings. Journal of Chemical Information and Modeling. 2021;61(8):3891-3898.", "链接": "https://doi.org/10.1021/acs.jcim.1c00203"},  # Vina新版方法来源。
]  # 结束主要方法文献。

def _result(workflow, manifest, run_id):  # 读取并完整核验一个固定上游结果。
    result = workflow.result(manifest, run_id)  # 结果文件及其附件均由统一框架校验。
    require(result is not None and result["outcome"] != "failed", "A07不能读取未完成或失败的上游结果")  # 报告不能把失败写成有效结果。
    return result  # 返回已核验的标准结果。

def _receptor_setup_rows(workflow, manifest, a06_run_id):  # 从当前A06绑定记录组装五个受体的结构与搜索盒参数。
    study_home = workflow.location(manifest["study_id"])  # 定位当前研究包，所有来源均在研究包内核验。
    current_result = workflow.result(manifest, a06_run_id)  # 优先读取A06标准结果中的通用受体参数表。
    if current_result and current_result.get("outcome") == "empty":  # 没有合格对接对象是允许报告的有效空结果。
        return [], list(current_result.get("files", []))  # 不要求虚构受体参数表。
    standard_rows = current_result.get("tables", {}).get("receptor_setup", []) if current_result else []  # 新版A06直接交付统一结构。
    if standard_rows:  # 通用结果不依赖某个病例的旧十组和扩展十五组拼接方式。
        required = {"靶点基因", "PDB ID", "蛋白链", "共晶参考配体", "搜索盒中心坐标", "搜索盒尺寸", "重对接RMSD（Å）", "质控状态"}  # 固定报告列。
        require(all(required <= set(row) for row in standard_rows), "A06通用受体参数表缺少必需字段")  # 缺字段时停止而不猜测。
        order = [key for key in (current_result.get("tables", {}).get("score_matrix", [{}])[0].keys()) if key not in ("compound_id", "compound_name")]  # 受体顺序来自本次矩阵。
        if current_result.get("tables", {}).get("generic_docking"):  # 动态版本保存明确PPI顺序。
            order = [row["target"] for row in current_result["tables"]["generic_docking"]["receptors"]]  # 不用JSON字段字母顺序。
        indexed = {row["靶点基因"]: row for row in standard_rows}  # 按标准基因符号建立索引。
        require(order and set(order) == set(indexed), "A06矩阵受体与受体参数表不一致")  # 报告不能混用其他受体。
        return [indexed[target] for target in order], list(current_result.get("files", []))  # 返回实际数量和A06已核验来源。
    current_run = read_json(verified_file(study_home, manifest["runs"][a06_run_id]["run_file"]))  # 读取当前五乘五A06运行及输入指纹。
    candidate_record = current_run["inputs"]["candidate_result"]  # 三个扩展受体来自当前A06明确绑定的候选结果。
    candidate = read_json(verified_file(study_home, candidate_record))  # 先核验候选结果指纹再读取结构参数。
    previous_record = current_run["inputs"]["previous_approved_a06_result"]  # AKT1和MAPK1来自当前A06绑定的已批准十组结果。
    previous_result = read_json(verified_file(study_home, previous_record))  # 核验旧A06结果，避免按目录时间猜版本。
    previous_run = read_json(verified_file(study_home, manifest["runs"][previous_result["run_id"]]["run_file"]))  # 读取旧A06固定的准备包和重对接输入。
    prep_record = previous_run["inputs"]["preparation_package"]  # 搜索盒、蛋白链和参考配体来自旧A06绑定准备包。
    redock_record = previous_run["inputs"]["redocking_result"]  # AKT1和MAPK1的RMSD来自旧A06绑定重对接结果。
    preparation_path = verified_file(workflow.root, prep_record)  # 项目级路径使用记录指纹核验后定位准备包。
    redocking_path = verified_file(workflow.root, redock_record)  # 项目级路径使用记录指纹核验后定位重对接结果。
    preparation = read_json(preparation_path)  # 读取经指纹固定的准备包。
    redocking = read_json(redocking_path)  # 读取经指纹固定的重对接诊断。
    preparation_record = file_record(study_home, preparation_path, "a06_preparation_package")  # 转为当前研究包内统一相对记录。
    redocking_record = file_record(study_home, redocking_path, "redocking_result")  # 转为当前研究包内统一相对记录。
    setup = {}  # 以标准靶点符号合并两批受体信息。
    old_rmsd = {row["symbol"]: row for row in redocking["results"]}  # 建立旧受体RMSD索引。
    for row in preparation["approved_boxes"]:  # 只读取旧A06实际批准的搜索盒。
        if row["symbol"] not in ("AKT1", "MAPK1"):  # 旧HSP90AA1结构未进入本次五乘五结果。
            continue  # 跳过已被4LWE替换的历史受体。
        ligand = row["reference_ligand"]  # 取得共晶参考配体的代码、链和序号。
        setup[row["symbol"]] = {  # 保存一行可直接进入报告的结构化参数。
            "靶点基因": row["symbol"], "PDB ID": row["pdb"], "蛋白链": row["chains"],
            "共晶参考配体": f"{ligand['code']} {ligand['auth_chain']}:{ligand['auth_sequence']}",
            "搜索盒中心坐标": "，".join(f"{axis}={float(value):.3f}" for axis, value in zip(("X", "Y", "Z"), row["center_angstrom"])),
            "搜索盒尺寸": "，".join(f"{axis}={float(value):.3f}" for axis, value in zip(("X", "Y", "Z"), row["size_angstrom"])),
            "重对接RMSD（Å）": f"{float(old_rmsd[row['symbol']]['rmsd_angstrom']):.3f}",
            "质控状态": "通过" if old_rmsd[row["symbol"]]["passed"] else "未通过",
        }  # 完成旧受体记录。
    for row in candidate["receptor_diagnostics"]:  # 读取扩展受体的实际结构、盒子和重对接诊断。
        ligand = row["reference"]  # 扩展包已保存共晶参考配体的完整位置。
        setup[row["target"]] = {  # 保存扩展受体的一行参数。
            "靶点基因": row["target"], "PDB ID": row["pdb"], "蛋白链": "/".join(row["chains"]),
            "共晶参考配体": ligand,
            "搜索盒中心坐标": "，".join(f"{axis}={float(value):.3f}" for axis, value in zip(("X", "Y", "Z"), row["box"]["center_angstrom"])),
            "搜索盒尺寸": "，".join(f"{axis}={float(value):.3f}" for axis, value in zip(("X", "Y", "Z"), row["box"]["size_angstrom"])),
            "重对接RMSD（Å）": f"{float(row['redocking_rmsd_A']):.3f}",
            "质控状态": "通过" if row["passed"] else "未通过",
        }  # 完成扩展受体记录。
    matrix = current_result.get("tables", {}).get("score_matrix", [])  # 兼容当前历史扩展结果时仍从矩阵读取实际顺序。
    order = [key for key in (matrix[0].keys() if matrix else []) if key not in ("compound_id", "compound_name")]  # 不把五个COPD受体写成通用规则。
    require(set(setup) == set(order), "A06绑定记录未能完整生成五个受体参数")  # 缺少任何一项都禁止报告。
    return [setup[target] for target in order], [candidate_record, previous_record, preparation_record, redocking_record]  # 同时返回数据与研究包内来源记录。

def _energy_text(values):  # 将一组实际结合能压缩为可读范围。
    numbers = [float(value) for value in values if isinstance(value, (int, float))]  # 缺失项不补零。
    return "未运行" if not numbers else f"{min(numbers):.3f}至{max(numbers):.3f} kcal/mol"  # 保留三位小数并如实表示范围。

def _compound_display(name):  # 将数据库英文名转换为本项目已确认的报告名称。
    names = {"beta-sitosterol": "β-谷甾醇", "quercetin": "槲皮素"}  # 只转换已核对的常用名称。
    return names.get(name, name)  # 未定义名称保持原始记录不自行翻译。

def _research_leads(a04, a05, a06):  # 从已复核事实生成最多三条待核验线索。
    metrics = {row["symbol"]: row for row in a04["tables"].get("metrics", [])}  # 以标准基因符号定位网络指标。
    matrix = a06["tables"].get("score_matrix", [])  # 读取已批准的结合能矩阵。
    receptors = [key for key in (matrix[0].keys() if matrix else []) if key not in ("compound_id", "compound_name")]  # 从矩阵字段取得五个受体。
    primary_targets = a06["tables"].get("generic_docking", {}).get("primary_targets")  # 扩展受体不参与主要研究线索。
    receptors = [target for target in receptors if primary_targets is None or target in primary_targets]  # 历史结果保留原解释范围。
    scored = [(float(row[target]), row.get("compound_name"), target) for row in matrix for target in receptors if isinstance(row.get(target), (int, float))]  # 汇总全部真实评分。
    strongest = min(scored) if scored else (None, "未完成", "未完成")  # 评分越负表示同一设置下预测越有利。
    strongest = (strongest[0], _compound_display(strongest[1]), strongest[2])  # 报告使用已确认的中文成分名。
    leads = []  # 有真实评分时才生成结构线索，空结果不凑数。
    if strongest[0] is not None:  # 至少一组有效对接才能提出优先核验组合。
        primary_target = strongest[2]  # 评分最负组合的受体作为结构核验起点。
        primary_metric = metrics.get(primary_target, {})  # 同时读取该受体的PPI位置。
        same_target = sorted((item for item in scored if item[2] == primary_target), key=lambda item: (item[0], str(item[1])))  # 在同一受体内稳定排序。
        comparison = same_target[1] if len(same_target) > 1 else None  # 第二个成分只作同靶点对照。
        next_step = f"优先核验{strongest[1]}—{primary_target}"  # 使用本次真实组合，不引用固定成分或靶点。
        if comparison:  # 同一受体至少有两个完成组合时形成同靶点比较。
            next_step += f"，并以{_compound_display(comparison[1])}—{primary_target}作为同靶点成分对照"  # 控制受体差异后比较成分。
        next_step += "；如继续研究，可开展分子动力学并补充成分暴露、结合和功能实验。"  # 明确计算后续仍不能替代实验。
        leads.append({"线索": f"{primary_target}优先核验线索", "支持事实": f"{primary_target}的PPI Degree为{primary_metric.get('degree', '未进入网络')}；{strongest[1]}—{primary_target}在本次相同Vina设置下评分最负（{strongest[0]:.3f} kcal/mol）。", "下一步核验": next_step})  # 保存完全由本次运行事实驱动的第一条线索。
        other_targets = [target for target in receptors if target != primary_target and target in metrics]  # 只从本次已对接受体中找跨靶点参考。
        if other_targets:  # 不足两个受体时不生成虚假的跨靶点比较。
            ranked_targets = sorted(other_targets, key=lambda target: (-int(metrics[target].get("degree", 0)), target))  # 按原PPI Degree稳定提名参考受体。
            reference_target = ranked_targets[0]  # 只提名一个，避免凑多个线索。
            leads.append({"线索": f"跨靶点结构对照线索（{reference_target}）", "支持事实": f"{reference_target}已进入本次对接矩阵且PPI Degree为{metrics[reference_target].get('degree', '未进入网络')}，可作为与{primary_target}不同受体背景的结构参考。", "下一步核验": f"从{reference_target}的已完成组合中选择姿势完整且评分靠前的一组，与{primary_target}优先组合在相同条件下比较稳定性；该比较用于观察结构结果是否依赖单一受体，不用于直接判断哪个靶点更有效。"})  # 只解释比较设计，不自行赋予疾病机制。
    bp = a05["tables"].get("bp_display", [])  # 读取同源BP展示结果。
    kegg = a05["tables"].get("kegg_display", [])  # 读取同源KEGG展示结果。
    if bp or kegg:  # 有富集事实时生成第三条线索。
        bp_text = "；".join(f"{row.get('ID')} {row.get('Description')}" for row in bp[:2]) or "本次无BP展示条目"  # 保留官方条目编号和名称。
        kegg_text = "；".join(f"{row.get('ID')} {row.get('Description')}" for row in kegg[:2]) or "本次无KEGG展示条目"  # 保留官方通路编号和名称。
        leads.append({  # 形成富集方向线索。
            "线索": "功能与通路线索",  # 不自行命名新的机制结论。
            "支持事实": f"按BH校正后的展示结果中，BP前列包括{bp_text}；KEGG前列包括{kegg_text}。",  # 只陈述已计算事实。
            "下一步核验": "结合疾病专门文献和关键命中基因复核生物学相关性；富集结果不等同通路被激活或受到治疗调控。",  # 明确解释边界。
        })  # 完成富集线索。
    return leads[:CONFIG["maximum_research_leads"]]  # 严格执行最多三条。

def assemble_payload(workflow, manifest, parent_runs, heatmap_metadata_record=None):  # 生成两份报告共同使用的唯一事实包。
    results = {module: _result(workflow, manifest, parent_runs[module]) for module in ("A00", "A01", "A02", "A03", "A04", "A05", "A06")}  # 固定七个必需模块。
    selection_run = manifest["current"].get("A03_SELECT")  # 主候选来自独立人工选择关口。
    require(selection_run and workflow.approved(manifest, selection_run), "A03主候选尚未复核通过")  # 报告不能绕过候选审核。
    selection = _result(workflow, manifest, selection_run)  # 读取已批准候选版本。
    heatmap_png = None  # 有效空A06不生成假热图。
    heatmap_metadata = {}  # 无图时不生成虚假图面数量。
    if heatmap_metadata_record:  # 只有A06实际产生热图时才核验图件。
        metadata_path = verified_file(workflow.location(manifest["study_id"]), heatmap_metadata_record)  # 固定已验证元数据实际目录。
        heatmap_metadata = read_json(metadata_path)  # 核验用户认可的热图索引。
        schema = heatmap_metadata.get("schema_version")  # 同时兼容历史固定热图和新版动态热图。
        require(schema in {"A06.heatmap.1", "A06.dynamic_heatmap.1"}, "热图元数据版本不受支持")  # 不扫描未知图件。
        if schema == "A06.heatmap.1":  # 历史图使用直接运行编号。
            require(heatmap_metadata.get("run_id") == parent_runs["A06"], "热图没有绑定当前A06运行")  # 防止旧图进入新报告。
        else:  # 动态图必须通过来源指纹绑定，不仅比较矩阵大小。
            candidate_hashes = [record["sha256"] for record in results["A06"].get("sources", []) if record.get("role") == "generic_docking_candidate"]  # 读取A06绑定候选来源。
            require(len(candidate_hashes) == 1 and heatmap_metadata.get("source_result", {}).get("sha256") == candidate_hashes[0], "动态热图未绑定当前A06事实指纹")  # 相同数量的其他运行不能借图。
            require(heatmap_metadata.get("dimensions", {}).get("planned_pairs") == len(results["A06"].get("tables", {}).get("generic_docking", {}).get("planned_pairs", [])), "动态热图组合数与当前A06不一致")  # 防止跨运行借图。
        heatmap_png = next((record for record in heatmap_metadata.get("files", []) if record.get("role") == "heatmap_png"), None)  # 只选元数据明确标识的PNG。
        require(heatmap_png is not None, "A06热图PNG索引缺失")  # 不扫描文件名猜测图片。
        image_root = metadata_path.parent if schema == "A06.dynamic_heatmap.1" else workflow.root  # 动态图使用元数据目录相对记录。
        heatmap_png_path = verified_file(image_root, heatmap_png)  # 校验实际图片字节与目录边界。
        heatmap_png = file_record(workflow.location(manifest["study_id"]), heatmap_png_path, "heatmap_png")  # 转为当前研究包内的统一相对记录。
    intake = results["A00"]["summary"]  # 研究对象来自已批准A00。
    selected = selection["tables"].get("selected", [])  # 主候选名单来自A03_SELECT。
    round1 = results["A04"]["tables"].get("round1", [])  # 第一轮PPI主候选来自已批准A04。
    round2 = results["A04"]["tables"].get("round2", [])  # 第二轮名单仅作为参考表。
    group_summary = results["A05"]["tables"].get("group_summary", [])  # 富集数量来自同一A05结果。
    matrix = results["A06"]["tables"].get("score_matrix", [])  # 对接矩阵来自已批准A06。
    receptor_setup, receptor_setup_sources = _receptor_setup_rows(workflow, manifest, parent_runs["A06"])  # 从A06绑定输入生成受体参数表。
    generic_docking = results["A06"].get("tables", {}).get("generic_docking")  # 第二版A06提供结构限制表的唯一事实源。
    receptor_limitations = receptor_limitation_table(generic_docking) if isinstance(generic_docking, dict) else []  # 历史结果保持空表兼容。
    purpose = results["A06"]["summary"].get("分析用途") or results["A03"]["summary"].get("analysis_purpose", "research")  # 沿全链传播分析用途。
    disease_sources = results["A02"]["tables"].get("source_summary", [])  # 报告使用本次实际来源，不写死五库成功。
    source_exceptions = results["A02"]["tables"].get("source_exceptions", [])  # 缺库流程测试例外随链传播。
    source_status_text = "；".join(row["database"] + "：" + row["availability"] + "（" + str(row["records"]) + "条）" for row in disease_sources)  # 记录数与状态并列。
    source_exception_text = "" if not source_exceptions else "GeneCards因注册或获取障碍未提供；Open Targets贡献" + str(source_exceptions[0]["otp_unique_genes"]) + "/" + str(source_exceptions[0]["all_unique_genes"]) + "个标准化疾病基因（" + str(source_exceptions[0]["otp_contribution_percent"]) + "%），仅是本次流程测试的主要来源，不代表与GeneCards等价。"  # 禁止“五库共同支持”表述。
    key_counts = [  # 用一张小表固定两份报告中的关键数量。
        {"指标": "方剂标准化靶点数", "数值": results["A01"]["summary"].get("标准化基因数")},  # A01事实。
        {"指标": "疾病标准化靶点数", "数值": results["A02"]["summary"].get("标准化基因数")},  # A02事实。
        {"指标": "交集靶点数", "数值": results["A03"]["summary"].get("交集靶点数")},  # A03事实。
        {"指标": "主候选成分数", "数值": len(selected)},  # A03_SELECT事实。
        {"指标": "PPI参与节点数", "数值": results["A04"]["summary"].get("参与节点数")},  # A04事实。
        {"指标": "PPI合格边数", "数值": results["A04"]["summary"].get("合格边数")},  # A04事实。
        {"指标": "PPI第一轮主候选数", "数值": results["A04"]["summary"].get("第一轮主候选数")},  # A04事实。
        {"指标": "正式对接成功组合数", "数值": results["A06"]["summary"].get("成功组合数")},  # A06事实。
    ]  # 结束关键数量表。
    enrichment_counts = {row["group"]: row["significant_count"] for row in group_summary}  # 按实际四类汇总显著条目。
    docking_reuse = generic_docking.get('reuse_provenance', {}) if generic_docking else {}  # 读取显式复用事实，不根据相同评分推测。
    reuse_text = (f"本版{len(generic_docking['completed_pairs'])}组有效对接评分及固定Top-1姿势经受体、配体、搜索盒和Vina参数一致性核验后复用；未重新进行研究成分对接。本版参考配体重对接已独立运行和复算，主要受体按新版PPI顺序确定，原失败项和结构限制保留。") if docking_reuse else ''  # 准确区分重对接与研究成分计算。
    if docking_reuse and 'reused_pair_count' in docking_reuse:  # 通用模板可以部分复用、部分新计算，不宣称全部复用。
        reuse_text = f"本版有效组合中{docking_reuse['reused_pair_count']}组经输入、搜索盒、软件及参数一致性核验后复用固定Top-1；{docking_reuse['newly_calculated_pair_count']}组为本次新计算。参考配体重对接使用本研究准备阶段实测值。复用组合保留原计算时间，失败项不以零填补。"  # 两份报告共用真实混合事实。
    source_boundary = docking_reuse.get('source_boundary') or ("本次疾病侧资料仅用于流程测试；正式研究须核验检索策略、导出完整性和来源版本。" if purpose == 'workflow_test' else "数据库覆盖、更新频率和检索策略会影响候选集合。")  # 研究专属来源限制从绑定事实包读取。
    limitations = [  # 两份报告共用同一组关键限制。
        "本次案例的analysis_purpose为workflow_test，属于流程测试，不作为正式研究结论。" if purpose == "workflow_test" else "本报告属于网络药理学与分子对接初筛，不能单独证明疗效、因果关系或临床获益。",  # 用途限制。
        source_exception_text or source_boundary,  # 来源限制按本次实际资料生成。
        "交集和网络中心性反映当前资料与网络结构，不等同靶点的重要性已被实验确认。",  # 网络解释限制。
        "富集结果表示候选基因集合的统计过度代表，不等同通路被激活、抑制或受到治疗调控。",  # 富集解释限制。
        "分子对接评分用于结构层面的优先核验；不同蛋白间的分值不直接代表体内药效强弱。",  # 对接解释限制。
        f"本次计划包含{len(matrix)}个候选成分与{len([key for key in (matrix[0].keys() if matrix else []) if key not in ('compound_id', 'compound_name')])}个受体；主要结论只使用当前研究内通过参考配体重对接质控的5个主要受体，预测口袋或存在结构限制的受体仅作为扩展线索。受体构象、搜索盒、配体电离状态和Vina打分函数仍会影响数值。",  # 区分主要与探索结果。
    ]  # 结束共同限制。
    receptor_names = [key for key in (matrix[0].keys() if matrix else []) if key not in ("compound_id", "compound_name")]  # 取得矩阵受体字段。
    scored = [(float(row[target]), row.get("compound_name"), target) for row in matrix for target in receptor_names if isinstance(row.get(target), (int, float))]  # 汇总25格评分。
    primary_targets = generic_docking.get("primary_targets") if generic_docking else None  # 当前主要结论限制为严格五受体。
    main_scored = [item for item in scored if primary_targets is None or item[2] in primary_targets]  # 全矩阵仍用于数量与扩展结果展示。
    strongest = min(main_scored) if main_scored else (None, "未完成", "未完成")  # 找到评分最负组合。
    strongest = (strongest[0], _compound_display(strongest[1]), strongest[2])  # 报告使用已确认的中文成分名。
    ppi_names = [row.get("symbol") for row in round1[:8] if row.get("symbol")]  # PPI描述只列本次第一轮前列节点。
    go_names = [row.get("Description") for group in ("BP", "CC", "MF") for row in results["A05"]["tables"].get(group.lower() + "_display", [])[:1] if row.get("Description")]  # 各GO分类最多取一个实际前列条目。
    kegg_names = [row.get("Description") for row in results["A05"]["tables"].get("kegg_display", [])[:2] if row.get("Description")]  # 读取本次KEGG前两项。
    structure_text = "本次没有形成可比较的有效对接评分。" if strongest[0] is None else f"本次实际完成{len(scored)}组有效评分；在主要受体范围内，{strongest[1]}—{strongest[2]}评分最负（{strongest[0]:.3f} kcal/mol）。该值只表示本次统一Vina设置下预测更有利，分子大小和疏水性可能影响评分，不能称为最有效成分。"  # 有效空结果也能形成诚实结论。
    lead_text = "建议先补充合格的结构结果，再讨论分子动力学或实验优先级。" if strongest[0] is None else f"建议优先核验{strongest[1]}—{strongest[2]}；如需比较，可先选择同一受体的另一候选成分控制受体差异，再选择一个通过质控的其他受体作为跨靶点结构参考。分子动力学用于比较复合物随时间的稳定性，不能替代结合、细胞或临床证据。"  # 后续动作由实际完成状态决定。
    conclusion_sections = [  # 四层结论全部从本次运行事实构建，疾病解释留给人工复核。
        {"层次": "PPI方向", "结论": ("第一轮前列网络节点包括" + "、".join(ppi_names) + "。这些节点在当前PPI网络中处于相对中心位置，可用于确定优先查证对象；其疾病生物学角色仍需结合专门文献核实，不能视为已被方剂直接调控。") if ppi_names else "本次未形成PPI第一轮候选；这是有效空结果，不据此补造核心靶点。"},  # 网络层结论。
        {"层次": "富集方向", "结论": ("GO前列条目包括" + "；".join(go_names) + "；KEGG前列条目包括" + "；".join(kegg_names) + "。这些条目表示当前基因集的统计过度代表，具体疾病意义须经文献复核；疾病名称型通路不直接外推疗效。") if (go_names or kegg_names) else "本次没有达到既定显著性标准的GO或KEGG条目，不据此补造功能机制。"},  # 富集层结论。
        {"层次": "结构方向", "结论": structure_text},  # 结构层结论。
        {"层次": "后续研究", "结论": lead_text},  # 后续研究层结论。
    ]  # 结束四层结论。
    conclusion = " ".join(row["结论"] for row in conclusion_sections) + " 因此不能据此认定治疗有效、确定已证实机制或给出疗效概率。"  # 汇总为网页共同结论并保留科学边界。
    payload = {  # 汇总唯一报告事实包。
        "schema_version": "A07.report.payload.4",  # 第四版事实包不再包含固定COPD结论。
        "study_id": manifest["study_id"],  # 保存稳定研究编号。
        "analysis_purpose": purpose,  # 传播流程测试或正式研究用途。
        "disease_source_status": source_status_text,  # 保存实际来源状态供报告方法段引用。
        "source_exception_text": source_exception_text or (source_boundary if docking_reuse else ''),  # 不继续报告已经撤销的缺库例外。
        "docking_reuse_text": reuse_text,  # 两份报告同时明确复用而非重新计算。
        "research": intake,  # 保存已批准研究对象。
        "parent_runs": dict(parent_runs),  # 固定七个上游运行。
        "selection_run": selection_run,  # 固定主候选选择版本。
        "heatmap_metadata": heatmap_metadata_record,  # 固定图形元数据记录。
        "heatmap_png": heatmap_png,  # 固定实际PNG及指纹。
        "heatmap_display": heatmap_metadata.get("display_dimensions", heatmap_metadata.get("dimensions", {})),  # 图面数量与原计划分别报告。
        "heatmap_display_note": heatmap_display_note(heatmap_metadata),  # 保留失败组合及删减行列说明。
        "conclusion_draft": conclusion,  # 保存待A07专业复核的共同结论。
        "conclusion_sections": conclusion_sections,  # 保存四层可读结论。
        "key_counts": key_counts,  # 保存共同关键数量。
        "selected_compounds": selected,  # 保存共同主候选成分。
        "ppi_round1_top": round1[:10],  # 详细版展示前十项，完整表仍在A04。
        "ppi_round1": round1,  # 图件保留全部52个第一轮节点。
        "ppi_round2": round2,  # 第二轮19节点仅进入参考表。
        "a03_summary": results["A03"]["summary"],  # 图件使用A03交集统计。
        "a03_tables": results["A03"]["tables"],  # 图件使用A03网络运行表。
        "a04_tables": results["A04"]["tables"],  # 图件使用A04完整PPI运行表。
        "a05_tables": results["A05"]["tables"],  # 图件使用A05富集运行表。
        "enrichment_group_summary": group_summary,  # 保存四类完整汇总。
        "enrichment_highlights": {group: results["A05"]["tables"].get(group.lower() + "_display", [])[:12] for group in ("BP", "CC", "MF", "KEGG")},  # 图件每类最多保留十二项。
        "docking_matrix": matrix,  # 保存共同结合能矩阵。
        "receptor_setup": receptor_setup,  # 保存五个受体的结构、搜索盒和重对接质控参数。
        "receptor_limitations": receptor_limitations,
        "primary_targets": primary_targets,  # 所有主要结论使用同一严格受体范围。  # 紧跟热图呈现结构限制，不使用ABC代码。
        "receptor_setup_sources": receptor_setup_sources,  # 保存受体参数表的四项绑定来源记录。
        "research_leads": _research_leads(results["A04"], results["A05"], results["A06"]),  # 生成最多三条待复核线索。
        "limitations": limitations,  # 保存共同限制。
        "enrichment_counts": enrichment_counts,  # 供两份报告一致引用。
        "method_references": METHOD_REFERENCES,  # 保存主要方法文献。
    }  # 完成事实包。
    return payload  # 两份Word只能从该对象取数。

def _font(run, size=None, bold=False, color=None):  # 统一设置中英文字体。
    run.font.name = "Arial"  # 设置西文字体。
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")  # 设置中文字体。
    run.font.size = Pt(size) if size else run.font.size  # 仅在指定时修改字号。
    run.bold = bold  # 设置是否加粗。
    if color:  # 有颜色时设置字体颜色。
        run.font.color.rgb = RGBColor(*color)  # 使用明确RGB颜色。
    return run  # 返回已格式化文本片段。

def _shade(cell, fill):  # 设置表格单元格底色。
    properties = cell._tc.get_or_add_tcPr()  # 获取单元格属性。
    shading = OxmlElement("w:shd")  # 创建底色节点。
    shading.set(qn("w:fill"), fill)  # 写入十六进制颜色。
    properties.append(shading)  # 将底色附加到单元格。

def _repeat_header(row):  # 让跨页表格重复显示表头。
    properties = row._tr.get_or_add_trPr()  # 获取行属性。
    repeat = OxmlElement("w:tblHeader")  # 创建重复表头节点。
    repeat.set(qn("w:val"), "true")  # 启用重复表头。
    properties.append(repeat)  # 将设置附加到当前行。

def _keep_row_together(row):  # 禁止一个数据行被拆到两页。
    properties = row._tr.get_or_add_trPr()  # 获取行属性。
    keep = OxmlElement("w:cantSplit")  # 创建禁止拆分节点。
    keep.set(qn("w:val"), "true")  # 启用禁止拆分。
    properties.append(keep)  # 将设置附加到当前行。

def _set_cell_text(cell, value, bold=False, color=None, size=9):  # 用统一样式写入表格单元格。
    cell.text = ""  # 清除默认空段落内容。
    paragraph = cell.paragraphs[0]  # 使用单元格已有段落。
    paragraph.paragraph_format.space_after = Pt(0)  # 减少表格行间空白。
    run = paragraph.add_run("—" if value is None or value == "" else str(value))  # 缺失显示破折号而非零。
    _font(run, size=size, bold=bold, color=color)  # 应用中英文字体和强调。
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER  # 垂直居中便于阅读。

def _table(document, rows, columns, widths=None, font_size=9):  # 生成统一风格的数据表。
    table = document.add_table(rows=1, cols=len(columns))  # 先建立表头。
    table.alignment = WD_TABLE_ALIGNMENT.CENTER  # 表格整体居中。
    table.style = "Table Grid"  # 使用稳定的网格样式。
    _repeat_header(table.rows[0])  # 多页时重复表头。
    for index, column in enumerate(columns):  # 写入每个表头。
        _set_cell_text(table.rows[0].cells[index], column, bold=True, color=(255, 255, 255), size=font_size)  # 表头使用白字。
        _shade(table.rows[0].cells[index], "2F6077")  # 表头使用深蓝绿色。
        for paragraph in table.rows[0].cells[index].paragraphs:  # 表头必须与首条数据同行分页。
            paragraph.paragraph_format.keep_with_next = True  # 防止页末只剩表头。
        if widths:  # 提供宽度时设置首选宽度。
            table.rows[0].cells[index].width = Cm(widths[index])  # 使用厘米便于A4页面控制。
    for row in rows:  # 逐行写入真实结果。
        cells = table.add_row().cells  # 新增一行数据。
        _keep_row_together(table.rows[-1])  # 关键事实不得在页间拆成两段。
        for index, column in enumerate(columns):  # 按固定列顺序写入。
            _set_cell_text(cells[index], row.get(column), size=font_size)  # 缺值不补零。
            if widths:  # 保持与表头一致的列宽。
                cells[index].width = Cm(widths[index])  # 设置当前单元格宽度。
    document.add_paragraph().paragraph_format.space_after = Pt(0)  # 在表后保留轻微间距。
    return table  # 返回表格供必要时继续设置。

def _set_cell_borders(cell, **edges):  # 为学术三线表设置指定边线。
    properties = cell._tc.get_or_add_tcPr()  # 获取单元格属性。
    borders = properties.first_child_found_in("w:tcBorders")  # 查找已有边框节点。
    if borders is None:  # 没有边框时创建新节点。
        borders = OxmlElement("w:tcBorders")  # 创建单元格边框容器。
        properties.append(borders)  # 将边框容器加入单元格属性。
    for edge, attrs in edges.items():  # 逐条设置上边线、下边线或无边线。
        tag = "w:" + edge  # 形成OOXML边线标签。
        element = borders.find(qn(tag))  # 查找当前方向的边线。
        if element is None:  # 尚未设置时创建边线元素。
            element = OxmlElement(tag)  # 创建指定方向边线。
            borders.append(element)  # 加入边框容器。
        for key, value in attrs.items():  # 写入线型、粗细和颜色。
            element.set(qn("w:" + key), str(value))  # 使用Word命名空间属性。

def _receptor_setup_table(document, rows):  # 生成截图风格的受体及对接空间参数三线表。
    columns = ["靶点基因", "PDB ID", "蛋白链", "共晶参考配体", "搜索盒中心坐标", "搜索盒尺寸", "重对接RMSD（Å）", "质控状态"]  # 固定列顺序。
    widths = [1.6, 1.3, 1.1, 2.1, 3.6, 3.6, 2.0, 1.4]  # 控制八列在A4正文宽度内清晰排布。
    caption = document.add_paragraph()  # 创建表题段落。
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 表题居中。
    _font(caption.add_run("表  受体蛋白结构与分子对接搜索空间参数"), size=9.5, bold=True, color=(32, 51, 66))  # 使用简洁学术表题。
    table = document.add_table(rows=1, cols=len(columns))  # 创建表头。
    table.alignment = WD_TABLE_ALIGNMENT.CENTER  # 表格整体居中。
    table.autofit = False  # 固定列宽防止坐标列异常挤压。
    _repeat_header(table.rows[0])  # 跨页时重复表头。
    for index, column in enumerate(columns):  # 写入八列表头。
        _set_cell_text(table.rows[0].cells[index], column, bold=True, size=7.0)  # 使用黑字学术表头。
        table.rows[0].cells[index].width = Cm(widths[index])  # 固定当前列宽。
        _set_cell_borders(table.rows[0].cells[index], top={"val": "single", "sz": "12", "color": "59666D"}, bottom={"val": "single", "sz": "8", "color": "7A858B"}, left={"val": "nil"}, right={"val": "nil"})  # 表头使用上下两条横线。
    for row in rows:  # 写入五个受体。
        cells = table.add_row().cells  # 新增受体行。
        _keep_row_together(table.rows[-1])  # 每个受体保持在同一页。
        for index, column in enumerate(columns):  # 按固定列写入参数。
            _set_cell_text(cells[index], row[column], size=6.8)  # 紧凑显示三位小数坐标。
            cells[index].width = Cm(widths[index])  # 保持列宽一致。
            _set_cell_borders(cells[index], top={"val": "nil"}, bottom={"val": "nil"}, left={"val": "nil"}, right={"val": "nil"})  # 数据区不显示竖线和内部横线。
    for cell in table.rows[-1].cells:  # 仅最后一行增加底线。
        _set_cell_borders(cell, bottom={"val": "single", "sz": "12", "color": "59666D"})  # 完成三线表底线。
    note = document.add_paragraph()  # 添加质控解释。
    _font(note.add_run("注：有共晶参考配体的受体按其位置建立搜索盒；探索受体可使用已批准的P2Rank预测口袋，失败项记为未形成。参考配体Top-1对称性校正重原子RMSD≤2 Å为本项目重对接质控标准。坐标和尺寸单位为Å。"), size=8.0, color=(73, 102, 117))  # 说明方法与单位。
    return table  # 返回表格供测试或后续样式调整。

def _configure(document, title):  # 设置两份报告共用的页面和样式。
    section = document.sections[0]  # 使用首节设置A4页面。
    section.top_margin = Cm(1.7)  # 设置上边距。
    section.bottom_margin = Cm(1.7)  # 设置下边距。
    section.left_margin = Cm(1.8)  # 设置左边距。
    section.right_margin = Cm(1.8)  # 设置右边距。
    styles = document.styles  # 取得文档样式集合。
    for name, size, color in (("Normal", 10.5, (32, 51, 66)), ("Title", 22, (29, 78, 101)), ("Heading 1", 15, (29, 78, 101)), ("Heading 2", 12.5, (46, 96, 119))):  # 统一正文和标题层级。
        style = styles[name]  # 获取内置样式。
        style.font.name = "Arial"  # 设置西文字体。
        style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")  # 设置中文字体。
        style.font.size = Pt(size)  # 设置字号。
        style.font.color.rgb = RGBColor(*color)  # 设置字体颜色。
    title_properties = styles["Title"]._element.get_or_add_pPr()  # 获取标题段落属性。
    title_border = title_properties.find(qn("w:pBdr"))  # 查找内置标题样式可能携带的下边线。
    if title_border is not None:  # 存在边线时移除。
        title_properties.remove(title_border)  # 标题仅使用留白和字号区分。
    styles["Normal"].paragraph_format.space_after = Pt(5)  # 正文段后留白。
    styles["Normal"].paragraph_format.line_spacing = 1.25  # 正文使用适度行距。
    document.core_properties.title = title  # 写入Word标题元数据。
    document.core_properties.subject = "Module A网络药理学与分子对接报告"  # 写入主题元数据。
    document.core_properties.author = "Module A工作台"  # 避免写入个人账户姓名。

def _add_title(document, title, subtitle, payload, revision):  # 添加报告首页标题和研究身份。
    paragraph = document.add_paragraph(style="Title")  # 使用标题样式。
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 标题居中。
    _font(paragraph.add_run(title), size=22, bold=True, color=(29, 78, 101))  # 写入主标题。
    paragraph = document.add_paragraph()  # 新增副标题段落。
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 副标题居中。
    _font(paragraph.add_run(subtitle), size=12, bold=True, color=(73, 102, 117))  # 写入报告类型。
    research = payload["research"]  # 读取共同研究对象。
    meta = [  # 形成简洁身份表。
        {"项目": "方剂", "内容": research.get("formula")},  # 方剂来自A00。
        {"项目": "疾病", "内容": research.get("disease")},  # 疾病来自A00。
        {"项目": "研究编号", "内容": payload["study_id"]},  # 使用稳定研究编号。
        {"项目": "报告修订", "内容": revision},  # 使用本次A07修订编号。
        {"项目": "分析用途", "内容": "流程测试，非正式研究结论" if payload["analysis_purpose"] == "workflow_test" else "网络药理学与分子对接初筛"},  # 清楚标记用途。
    ]  # 结束身份表。
    _table(document, meta, ["项目", "内容"], [3.4, 13.4], font_size=9.5)  # 用两列表呈现身份。

def _add_notice(document, text_value):  # 添加醒目的科学边界提示。
    table = document.add_table(rows=1, cols=1)  # 使用单格表保证提示不被拆散。
    table.alignment = WD_TABLE_ALIGNMENT.CENTER  # 提示框居中。
    _repeat_header(table.rows[0])  # 为辅助技术明确该单行是提示框首行。
    cell = table.cell(0, 0)  # 取得唯一单元格。
    _shade(cell, "EAF2F5")  # 使用浅蓝底色。
    _set_cell_text(cell, text_value, bold=True, color=(29, 78, 101), size=10)  # 写入边界文字。
    document.add_paragraph().paragraph_format.space_after = Pt(0)  # 保留提示框后间距。

def _add_heatmap(document, payload, root, width=6.3):  # 插入当前A06动态红蓝热图。
    if not payload.get("heatmap_png"):  # 有效空A06没有可绘制矩阵。
        document.add_paragraph("本次没有形成有效对接评分矩阵，因此不生成结合能热图。")  # 清楚呈现空结果而非缺图错误。
        return  # 不再尝试读取不存在的文件。
    path = verified_file(root, payload["heatmap_png"])  # 通过元数据指纹取得实际图片。
    paragraph = document.add_paragraph()  # 创建图片段落。
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 图片居中。
    paragraph.paragraph_format.keep_with_next = True  # 图片和紧随的图注不得跨页分离。
    picture = paragraph.add_run().add_picture(str(path), width=Inches(width))  # 按固定物理宽度插入PNG。
    compound_count = payload.get("heatmap_display", {}).get("compounds", len(payload.get("docking_matrix", [])))  # 使用实际图面列数。
    target_count = payload.get("heatmap_display", {}).get("receptors", len(payload.get("receptor_setup", [])))  # 使用实际图面行数。
    picture._inline.docPr.set("descr", f"{compound_count}个候选成分与{target_count}个受体的结合能热图")  # 为图片添加可读替代文字。
    caption = document.add_paragraph()  # 添加图注。
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 图注居中。
    caption.paragraph_format.keep_together = True  # 同一图注不拆到两页。
    _font(caption.add_run(f"图：{compound_count}个候选成分与{target_count}个受体的结合能热图（kcal/mol）。本次范围内评分越负红色越深，评分越不负蓝色越深；中间为浅红至浅蓝的平滑渐变，不表示阈值。"), size=8.5, color=(73, 102, 117))  # 不把颜色解释成疗效等级。

    if payload.get("heatmap_display_note"):  # 显示版删减必须紧随图解释。
        paragraph = document.add_paragraph()  # 两份报告均保留简短失败说明。
        _font(paragraph.add_run(payload["heatmap_display_note"]), size=8.0, color=(73, 102, 117))  # 不把未计算解释为无效。

def _receptor_limitation_report_table(document, rows):  # 在热图后集中呈现结构与解释边界。
    if not rows:  # 历史结果没有第二版结构化限制字段。
        return  # 不从旧自由文本推断。
    caption = document.add_paragraph()  # 建立表题。
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 表题居中。
    caption.paragraph_format.keep_with_next = True  # 表题与表头及首条数据保持同页。
    _font(caption.add_run("表  受体结构与结果解释说明"), size=9.5, bold=True, color=(32, 51, 66))  # 说明表不使用ABC等级。
    columns = ["PPI顺序", "靶点", "PDB ID", "搜索盒依据", "重对接情况", "结构或方法限制", "允许的解释范围"]  # 固定同层级字段。
    _table(document, rows, columns, [0.8, 1.45, 1.05, 2.4, 2.3, 6.5, 2.3], font_size=7.8)  # 十个受体可跨页但单行不拆分。

def _add_figure(document, payload, root, key, caption_text, width=6.35):  # 插入由当前运行表生成并记录指纹的图件。
    record = payload["report_figures"][key]["png"]  # 读取指定图件的PNG记录。
    path = verified_file(root, record)  # 在插图前再次核验文件及指纹。
    paragraph = document.add_paragraph()  # 创建图片段落。
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 图片居中。
    picture = paragraph.add_run().add_picture(str(path), width=Inches(width))  # 按页面宽度插入高分辨率PNG。
    picture._inline.docPr.set("descr", caption_text)  # 使用同源图注作为替代文字。
    caption = document.add_paragraph()  # 创建图注段落。
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 图注居中。
    _font(caption.add_run(caption_text), size=8.5, color=(73, 102, 117))  # 写入科学边界清楚的图注。

def _format_energy(value):  # 统一报告中的结合能显示。
    return "NA" if value is None else f"{float(value):.3f}"  # 缺失明确写未运行。

def build_detailed(payload, destination, root, revision):  # 生成专业详细版Word。
    document = Document()  # 创建新的可编辑Word文档。
    _configure(document, "Module A网络药理学与分子对接详细报告")  # 设置详细版样式。
    _add_title(document, "Module A网络药理学与分子对接报告", "专业详细版", payload, revision)  # 添加研究身份。
    _add_notice(document, ("本次为流程测试。" + (payload.get("source_exception_text") or "疾病侧资料不构成完整正式研究。") + "结果用于验证自动化流程，不得解释为临床疗效证明。") if payload["analysis_purpose"] == "workflow_test" else "本报告属于网络药理学与分子对接初筛，不得解释为临床疗效证明。")  # 突出实际用途和来源边界。
    document.add_heading("1 主要结论", level=1)  # 开始四层结论章节。
    for row in payload["conclusion_sections"]:  # 逐层写入可直接理解的研究指示。
        paragraph = document.add_paragraph()  # 建立当前结论段落。
        _font(paragraph.add_run(row["层次"] + "："), size=10.5, bold=True, color=(29, 78, 101))  # 突出结论层次。
        _font(paragraph.add_run(row["结论"]), size=10.5)  # 写入有边界的解释。
    document.add_paragraph("上述证据只能支持候选方向的优先级，不能据此认定治疗有效、确定已证实机制或给出疗效概率。")  # 明确总边界。
    document.add_heading("2 关键数量与完成情况", level=1)  # 开始关键数量章节。
    _table(document, payload["key_counts"], ["指标", "数值"], [10.5, 5.5], font_size=9.5)  # 显示共同数量表。
    enrichment_rows = [{"类别": row["group"], "有效输入数": row["effective_count"], "实际检验条目数": row["tested_count"], "BH显著条目数": row["significant_count"], "无注释输入数": row["missing_count"]} for row in payload["enrichment_group_summary"]]  # 形成富集汇总表。
    _table(document, enrichment_rows, ["类别", "有效输入数", "实际检验条目数", "BH显著条目数", "无注释输入数"], [2.2, 3.1, 3.8, 3.6, 3.3], font_size=8.5)  # 分母和缺口一起报告。
    document.add_heading("3 数据来源与方法", level=1)  # 开始方法章节。
    methods = [  # 按实际执行流程描述方法。
        "成分与方剂靶点：读取本地TCMSP提取快照，采用OB≥30%、DL≥0.18筛选，并通过HGNC规则整理人类靶点。",  # A01方法。
        "疾病靶点：按当前研究配置整合实际可用来源并保留原始评分。采集时来源状态（不代表当前模块复核状态）为：" + payload["disease_source_status"] + "。" + (payload.get("source_exception_text") or ""),  # A02方法不把缺库写成共同支持。
        "交集与候选：计算方剂靶点集T和疾病靶点集D的交集I；候选成分并列保留交集靶点数与网络Degree排序并经人工确认。",  # A03方法。
        "PPI：STRING 12.0、Homo sapiens、functional network、置信度≥0.9且不增加额外节点；全部合格连通分量参加第一轮。",  # A04方法。
        "富集：ORA；GO的BP、CC、MF分别BH校正，KEGG单独BH校正；基因集大小10–500，主要显著性标准为调整后P值<0.05。",  # A05方法。
        f"分子对接：本次计划对{len(payload['docking_matrix'])}个候选成分和{len(payload['receptor_setup'])}个受体进行计算。主要受体须在当前研究中完成参考配体Top-1对称性校正重原子RMSD≤2 Å质控；无可靠共晶位点的探索受体采用固定版本P2Rank首位口袋，不伪造RMSD。AutoDock Vina 1.2.7参数由A06运行记录固定。",  # A06方法区分严格质控与探索口袋。
    ]  # 结束方法段落。
    for method in methods:  # 逐段写入实际方法。
        document.add_paragraph(method)  # 方法不使用固定成功句式。
    if payload.get('docking_reuse_text'):  # 只有明确绑定复用记录时呈现。
        document.add_paragraph(payload['docking_reuse_text'])  # 不把历史运行日期写成新计算日期。
    document.add_heading("4 交集、成分与PPI网络", level=1)  # 开始网络结果章节。
    _add_figure(document, payload, root, "venn", "图1 方剂靶点与疾病靶点韦恩图。交集I为两侧标准化基因靶点的交集。")  # 插入韦恩图。
    full_count = len(payload["a04_tables"].get("metrics", []))  # 读取本次PPI实际参与节点数。
    round1_count = len(payload["ppi_round1"])  # 读取本次第一轮实际候选数。
    document.add_paragraph(f"药味—成分—交集靶点完整网络和{full_count}节点完整PPI网络保存在本报告修订的图源目录及运行表中；节点过密时正文不展示。")  # 保留追溯入口且不写死病例数量。
    _add_figure(document, payload, root, "ppi_round1", f"图2 第一轮{round1_count}节点主候选网络。全部节点保留，Degree前10位以红色突出并标注。")  # 仅插入清晰的第一轮核心图。
    network = [{"基因": row.get("symbol"), "HGNC": row.get("target_id"), "Degree": row.get("degree"), "Betweenness": f"{float(row.get('bc', 0)):.3f}", "Closeness": f"{float(row.get('cc', 0)):.4f}"} for row in payload["ppi_round1_top"]]  # 整理Degree前十表。
    _table(document, network, ["基因", "HGNC", "Degree", "Betweenness", "Closeness"], [2.7, 3.4, 2.2, 3.8, 3.8], font_size=8.2)  # 展示主候选前十。
    round2_rows = [{"基因": row.get("symbol"), "HGNC": row.get("target_id"), "Degree": row.get("degree"), "Betweenness": f"{float(row.get('bc', 0)):.3f}", "Closeness": f"{float(row.get('cc', 0)):.4f}"} for row in payload["ppi_round2"]]  # 整理第二轮19节点参考表。
    document.add_heading(f"第二轮{len(round2_rows)}节点参考名单", level=2)  # 明确第二轮不是主要结果并使用实际数量。
    _table(document, round2_rows, ["基因", "HGNC", "Degree", "Betweenness", "Closeness"], [2.7, 3.4, 2.2, 3.8, 3.8], font_size=8.2)  # 第二轮仅列表不绘图。
    document.add_heading("5 GO与KEGG富集结果", level=1)  # 开始富集章节。
    _add_figure(document, payload, root, "go_faceted", "图3 GO富集柱状图。BP为蓝色、CC为青绿色、MF为紫色；柱长及各组内部颜色深浅均表示Count，三类分别BH校正。")  # 插入GO分面图。
    _add_figure(document, payload, root, "kegg_bubble", "图4 KEGG富集气泡图。气泡大小表示Count，颜色表示调整后P值；疾病名称型通路不得直接外推疗效。")  # 插入KEGG气泡图。
    document.add_heading("6 分子对接结果", level=1)  # 开始对接章节。
    if payload["receptor_setup"]:  # 有合格受体时报告结构、口袋和重对接参数。
        _receptor_setup_table(document, payload["receptor_setup"])  # 表格行数使用本次实际受体数。
    else:  # 有效空A06仍需在正文明确呈现。
        document.add_paragraph("本次没有形成通过结构质控并进入对接的受体，因此无受体及搜索空间参数表。")  # 不生成只有表头的假表。
    _add_heatmap(document, payload, root, width=6.35)  # 插入五乘五红蓝热图。
    _receptor_limitation_report_table(document, payload.get("receptor_limitations", []))  # 热图后立即解释每个受体的限制。
    targets = [key for key in (payload["docking_matrix"][0].keys() if payload["docking_matrix"] else []) if key not in ("compound_id", "compound_name")]  # 受体列来自当前矩阵。
    if len(targets) > 6:  # 大矩阵改为与热图一致的受体行和成分列，防止超出A4页宽。
        compounds = payload['docking_matrix']  # 来源仍为同一结合能矩阵。
        targets = [row['靶点基因'] for row in payload['receptor_setup']]  # 保持PPI顺序。
        columns = ['受体'] + [row['compound_id'] for row in compounds]  # 短编号便于打印，与热图列名对应。
        docking_rows = [{'受体': target, **{row['compound_id']: _format_energy(row.get(target)) for row in compounds}} for target in targets]  # 只转置，不修改数据。
        widths = [2.4] + [(16.8 - 2.4) / max(1, len(compounds))] * len(compounds)  # 所有列总宽固定16.8厘米。
        _table(document, docking_rows, columns, widths, font_size=7.8)  # 打印时不裁切。
        document.add_paragraph('矩阵列名使用成分编号，与上方热图的名称一一对应；NA表示未形成有效Top-1评分，不代表结合能为零。')  # 明确失败含义。
    else:  # 历史小矩阵保持原方向。
        docking_rows = [{'成分': row.get('compound_name'), **{target: _format_energy(row.get(target)) for target in targets}} for row in payload['docking_matrix']]  # 读取原始评分。
        widths = [3.6] + [(16.8 - 3.6) / max(1, len(targets))] * len(targets)  # 小矩阵也不超过页宽。
        _table(document, docking_rows, ['成分'] + targets, widths, font_size=8.2)  # 保留历史表格展示。
    scores = [(float(row[target]), _compound_display(row.get("compound_name")), target) for row in payload["docking_matrix"] for target in targets if isinstance(row.get(target), (int, float))]  # 读取实际有限评分。
    main_scores = [item for item in scores if payload.get("primary_targets") is None or item[2] in payload["primary_targets"]]  # 扩展受体不替代主要结论。
    strongest = min(main_scores) if main_scores else None  # 有效空结果保持为空。
    docking_note = "单位：kcal/mol。本次没有形成有效对接评分。" if strongest is None else f"单位：kcal/mol。主要受体范围内评分最负的组合为{strongest[1]}—{strongest[2]}（{strongest[0]:.3f} kcal/mol）。该评分受分子大小和疏水性影响，不设置通用有效阈值，也不等同体内药效。"  # 动态报告最负组合。
    document.add_paragraph(docking_note)  # 突出实际最负组合并限制解释。
    document.add_heading("7 待进一步核验的研究线索", level=1)  # 开始研究线索章节。
    _table(document, payload["research_leads"], ["线索", "支持事实", "下一步核验"], [3.7, 7.5, 5.6], font_size=8.2)  # 最多三条且保留核验动作。
    document.add_heading("8 主要限制", level=1)  # 开始限制章节。
    for index, limitation in enumerate(payload["limitations"], 1):  # 按共同限制逐条写入。
        document.add_paragraph(f"{index}. {limitation}")  # 不隐藏数据来源和模型限制。
    document.add_heading("9 复核与追溯", level=1)  # 开始追溯章节。
    bindings = [{"模块": module, "运行编号": run_id} for module, run_id in payload["parent_runs"].items()] + [{"模块": "A03_SELECT", "运行编号": payload["selection_run"]}]  # 汇总固定版本。
    _table(document, bindings, ["模块", "运行编号"], [3.2, 13.6], font_size=8.5)  # 显示稳定运行编号。
    if payload.get("comparison_report_included"):  # 只有明确绑定差异说明的研究才显示附件提示。
        document.add_heading("附录 与既有研究结果的差异说明", level=1)  # 不把毕业论文比较强加给其他研究。
        document.add_paragraph("本报告修订附带独立差异说明，已与本修订一同保存并记录文件指纹。请以该附件中的比较对象、方法口径和解释边界为准。")  # 避免在通用模板中写死COPD受体。
    document.add_heading("10 主要方法参考文献", level=1)  # 开始参考文献章节。
    for row in payload["method_references"]:  # 逐条写入方法文献和链接。
        _font(document.add_paragraph().add_run(f"{row['编号']}. {row['文献']} {row['链接']}"), size=8.5)  # 使用普通可复制网址。
    destination.parent.mkdir(parents=True, exist_ok=True)  # 确保本次报告修订目录存在。
    document.save(destination)  # 保存专业详细版Word。

def build_concise(payload, destination, root, revision):  # 生成约两页的临床简略版Word。
    document = Document()  # 创建新的可编辑Word文档。
    _configure(document, "Module A网络药理学与分子对接简略报告")  # 设置简略版样式。
    document.styles["Normal"].paragraph_format.space_after = Pt(3)  # 简报减小段后空白，避免追溯信息单独占页。
    document.styles["Normal"].paragraph_format.line_spacing = 1.1  # 字号不缩小，保持两页快速阅读。
    section = document.sections[0]  # 进一步压缩简略版页边距。
    section.top_margin = Cm(1.25)  # 设置较紧凑上边距。
    section.bottom_margin = Cm(1.25)  # 设置较紧凑下边距。
    section.left_margin = Cm(1.35)  # 设置较紧凑左边距。
    section.right_margin = Cm(1.35)  # 设置较紧凑右边距。
    paragraph = document.add_paragraph()  # 创建不带边线的简略版标题。
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 标题居中。
    _font(paragraph.add_run("网络药理学与分子对接结果简报"), size=20, bold=True, color=(29, 78, 101))  # 写入主标题。
    research = payload["research"]  # 读取共同研究对象。
    meta = document.add_paragraph()  # 使用一行紧凑身份信息代替五行表格。
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 身份信息居中。
    _font(meta.add_run(f"{research.get('formula')}  |  {research.get('disease')}  |  {payload['study_id']}  |  {revision}"), size=8.5, color=(73, 102, 117))  # 保留对象和追溯编号。
    _add_notice(document, "本次为流程测试和前期初筛。结果用于确定进一步核验方向，不代表已证实治疗有效。" if payload["analysis_purpose"] == "workflow_test" else "本报告用于前期初筛和下一步核验，不代表已证实治疗有效。")  # 页面首屏突出边界。
    document.add_heading("主要结论", level=1)  # 结论置于第一页前部。
    for row in payload["conclusion_sections"]:  # 简略版使用同一组四层结论。
        paragraph = document.add_paragraph()  # 建立紧凑结论段落。
        _font(paragraph.add_run(row["层次"] + "："), size=8.8, bold=True, color=(29, 78, 101))  # 突出阅读重点并控制两页篇幅。
        _font(paragraph.add_run(row["结论"]), size=8.8)  # 写入同源结论。
    document.add_paragraph("以上均为前期计算线索，不能据此认定治疗有效或机制已经证实。")  # 简略版保留直接的疗效边界。
    compact_counts = payload["key_counts"][:4] + [payload["key_counts"][4], payload["key_counts"][7]]  # 简略版保留六个关键数字。
    metric_rows = []  # 将六个数字压缩为两行三列。
    for start in (0, 3):  # 每行放置三个指标。
        metric_rows.append({f"关键数{i + 1}": f"{compact_counts[start + i]['指标']}\n{compact_counts[start + i]['数值']}" for i in range(3)})  # 每格同时显示名称和数值。
    _table(document, metric_rows, ["关键数1", "关键数2", "关键数3"], [5.6, 5.6, 5.6], font_size=8.5)  # 使用紧凑指标卡片。
    _add_heatmap(document, payload, root, width=4.85)  # 缩小到第二页仍能清楚阅读并容纳决策摘要的尺寸。
    paragraph = document.add_paragraph()  # 在简略版热图后突出最负评分组合。
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 说明与图注保持同一阅读区域。
    targets = [key for key in (payload["docking_matrix"][0].keys() if payload["docking_matrix"] else []) if key not in ("compound_id", "compound_name")]  # 从本次矩阵取得受体。
    scores = [(float(row[target]), _compound_display(row.get("compound_name")), target) for row in payload["docking_matrix"] for target in targets if isinstance(row.get(target), (int, float))]  # 汇总实际有限评分。
    main_scores = [item for item in scores if not payload.get('primary_targets') or item[2] in payload['primary_targets']]  # 简略版主要结论同样限定严格主要受体。
    score_note = "本次未形成有效对接评分。" if not main_scores else f"主要受体范围内，{min(main_scores)[1]}—{min(main_scores)[2]}评分最负（{min(main_scores)[0]:.3f} kcal/mol）；该值是优先核验线索，不等同于疗效。"  # 探索评分不能替代主要结论。
    if payload.get('docking_reuse_text'):  # 用一句话说明本版分值来源。
        score_note += ' 本版评分及固定姿势经一致性核验后复用，未重新计算研究成分对接。'  # 简略报告不省略计算来源。
    _font(paragraph.add_run(score_note), size=8.5, bold=True, color=(73, 102, 117))  # 防止把计算排序解释为疗效。
    document.add_heading("建议优先核验的研究线索", level=1)  # 热图后直接展示决策内容，避免空白分页。
    for index, lead in enumerate(payload["research_leads"], 1):  # 最多三条线索。
        paragraph = document.add_paragraph()  # 每条线索压缩为一个完整段落。
        _font(paragraph.add_run(f"{index}. {lead['线索']}："), size=8.5, bold=True, color=(29, 78, 101))  # 突出线索名称。
        _font(paragraph.add_run(lead["下一步核验"]), size=8.5)  # 主要事实已在第一页结论中，不重复整段支持文字。
    document.add_heading("需要同时看到的限制", level=1)  # 防止简报只呈现积极结果。
    for limitation in payload["limitations"][:3]:  # 简略版保留用途、来源和网络解释三条核心限制。
        paragraph = document.add_paragraph()  # 建立紧凑限制段落。
        _font(paragraph.add_run("• " + limitation), size=8.3)  # 使用短段落便于临床阅读。
    document.add_heading("追溯信息", level=1)  # 提供继续查证入口。
    paragraph = document.add_paragraph()  # 使用一段完成追溯说明。
    _font(paragraph.add_run(f"研究编号：{payload['study_id']}；报告修订：{revision}。详细版与本简报共用同一事实包；完整来源、参数、复核记录和方法文献见专业详细版。"), size=8.0)  # 指向详细资料且不重复方法名称。
    destination.parent.mkdir(parents=True, exist_ok=True)  # 确保本次报告修订目录存在。
    document.save(destination)  # 保存临床简略版Word。

def build_comparison(payload, destination, revision):  # 生成独立的毕业论文结果差异说明。
    document = Document()  # 创建新的可编辑Word文档。
    _configure(document, "毕业论文结果与本次Module A结果差异说明")  # 使用统一中文字体和页面样式。
    paragraph = document.add_paragraph()  # 创建主标题段落。
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 主标题居中。
    _font(paragraph.add_run("毕业论文结果与本次Module A结果差异说明"), size=19, bold=True, color=(29, 78, 101))  # 写入清晰标题。
    document.add_paragraph(f"对应研究：玉屏风散—COPD；本次报告修订：{revision}。本说明用于解释两版结果为何不同，不用于否定任一版上游网络分析。")  # 说明文档用途。
    rows = [  # 按用户确认内容形成简短对照表。
        {"比较项": "受体选择", "毕业论文": "按PPI排名直接选取TP53、JUN、ESR1、MAPK1和TNF。", "本次Module A": "PPI提名后再检查蛋白身份、链、共晶位点、结构完整性、搜索盒和参考配体重对接，采用AKT1、MAPK1、HSP90AA1、TNF和ESR1。"},  # 解释核心差异。
        {"比较项": "结构限制", "毕业论文": "未形成同等粒度的逐受体结构质控链。", "本次Module A": "旧JUN和ESR1存在受体链身份问题，TP53使用短肽结构；这些问题只限制相应对接解释。"},  # 说明结构质控影响范围。
        {"比较项": "上游口径", "毕业论文": "采用当时的数据库、交集和PPI筛选口径。", "本次Module A": "数据库范围、HGNC标准化、交集数量和PPI筛选口径均按当前流程固定，因此数字不能直接替换。"},  # 解释数字差异。
        {"比较项": "方法优势", "毕业论文": "适合完成常见网络药理学结果链。", "本次Module A": "减少选错蛋白、选错链和对错口袋的风险，并绑定原始资料、参数、复核和文件指纹。"},  # 说明新增价值。
    ]  # 结束差异表。
    _table(document, rows, ["比较项", "毕业论文", "本次Module A"], [3.0, 6.3, 7.5], font_size=9)  # 用三列表呈现差异。
    _add_notice(document, "两版差异来自数据来源、标准化、网络筛选和结构质控口径的共同变化。结构问题不反向否定全部网络与富集结果；本次计算评分也不等同于实验准确性或临床疗效。")  # 给出最终解释边界。
    destination.parent.mkdir(parents=True, exist_ok=True)  # 确保方法学汇报目录存在。
    document.save(destination)  # 保存独立差异说明Word。

def validator(root):  # 建立A07领域校验器。
    def check(run, summary, tables, anomalies, outcome):  # 对标准A07结果进行独立约束检查。
        run_config = run.get("config", {})  # 历史报告必须按生成时保存的配置校验。
        require(str(run_config.get("schema_version", "")).startswith("A07.report.config."), "A07报告配置身份不正确")  # 接受可追溯历史版本但拒绝无身份配置。
        require(outcome == "success" and summary.get("handoff_blocked") is False, "A07报告状态不正确")  # 双报告必须完整生成后才能复核。
        require(summary.get("analysis_purpose") in ("workflow_test", "research"), "A07分析用途缺失")  # 用途必须沿链传播。
        require(summary.get("结论复核状态") == "待专业复核", "A07生成阶段不能自动批准结论")  # 生成报告不等于用户通过。
        require(len(tables.get("research_leads", [])) <= int(run_config.get("maximum_research_leads", 3)), "A07研究线索超过该版本上限")  # 按本次保存配置复算。
        require(len(tables.get("report_files", [])) == 3, "A07应包含两份Word和一份报告索引")  # 固定双报告交付结构。
        home = root / "studies" / run["study_id"]  # 定位当前研究包。
        for record in tables["report_files"]:  # 核验每个正式报告文件。
            verified_file(home, record)  # 文件必须位于研究包且指纹匹配。
        index_record = next(record for record in tables["report_files"] if record.get("role") == "report_index")  # 找到报告索引。
        index = read_json(verified_file(home, index_record))  # 读取并核验索引内容。
        require(index.get("schema_version") in ("A07.report.index.2", "A07.report.index.3") and index.get("run_id") == run["run_id"], "A07报告索引身份错误")  # 新旧索引均须绑定自身运行。
        require(index.get("parent_runs") == run["parent_runs"] and index.get("template_version") == run_config.get("template_version"), "A07报告索引版本绑定错误")  # 历史模板按自身记录核验。
        require(index.get("analysis_purpose") == summary.get("analysis_purpose"), "A07报告用途与索引不一致")  # 用途标签必须一致。
        require(len(index.get("figures", [])) == 12, "A07应包含六张图的SVG和PNG")  # 六张专业图件必须完整登记。
        for record in index["figures"]:  # 核验所有图源文件。
            verified_file(home, record)  # 图件必须位于当前报告修订目录且指纹匹配。
        comparison = index.get("comparison_report")  # 差异说明只对明确需要比较既有研究的修订存在。
        if comparison:  # 有差异说明时必须核验，不允许静默丢失。
            verified_file(home if index.get("schema_version") == "A07.report.index.3" else root, comparison)  # 新版附件位于修订目录，旧版沿用项目级路径。
        task_package = index.get('docking_task_package')  # 新版报告可绑定可下载PyMOL任务包。
        if task_package:  # 不要求历史报告补造该附件。
            package_index = read_json(verified_file(home, task_package['index']))  # 核验包的不可变索引。
            verified_file(home, task_package['archive'])  # 核验下载包。
            require(package_index['source_a06_run'] == run['parent_runs']['A06'] and package_index['study_id'] == run['study_id'], '报告任务包版本绑定错误')  # 防止跨研究或跨运行。
        conclusion = summary.get("共同结论草稿", "")  # 读取共同结论供边界检查。
        require("不能据此认定治疗有效" in conclusion and "疗效概率为" not in conclusion and "关联总分为" not in conclusion, "A07结论缺少边界或生成了未经验证的评分")  # 禁止自建量化结论。
    return check  # 返回给统一工作流注册。

def heatmap_display_note(metadata):  # 用通用元数据解释删减后的矩阵。
    original = metadata.get('dimensions', {})  # 原计划数量不随绘图删减。
    shown = metadata.get('display_dimensions')  # 历史图没有投影时不新增说明。
    if not shown:  # 保持旧报告规则兼容。
        return ''  # 无需解释未发生的删减。
    failures = len(metadata.get('omitted_pairs', []))  # 失败不能补造数值。
    omitted_targets = [item for item in metadata.get('receptor_order', []) if item not in metadata.get('displayed_receptor_order', [])]  # 全失败受体。
    omitted_compounds = [item for item in metadata.get('compound_order', []) if item not in metadata.get('displayed_compound_order', [])]  # 全失败成分。
    detail = ('未显示的全无评分受体：' + '、'.join(omitted_targets) + '。') if omitted_targets else ''  # 不隐藏删减身份。
    detail += ('未显示的全无评分成分：' + '、'.join(omitted_compounds) + '。') if omitted_compounds else ''  # 保留稳定成分编号。
    return f"原计划{original.get('receptors')}个受体×{original.get('compounds')}个成分，共{original.get('planned_pairs')}组；{len(metadata.get('displayed_pairs', []))}组形成有效评分，{failures}组未形成有效评分。删除全无评分行列后，图面为{shown['receptors']}×{shown['compounds']}；单对缺失以白底NA表示，不参与色标。" + detail + '未形成评分不等于无结合或无效；具体原因见受体说明及原始失败日志。'  # 不掩盖失败或外推疗效。


def report_heatmap_record(workflow, a06_result):  # 报告只能采用当前A06绑定且审核通过的展示图。
    if not a06_result or a06_result.get('outcome') == 'empty':  # 有效空结果没有热图。
        return None  # 不造图形来源。
    home = workflow.location(a06_result['study_id'])  # 当前研究目录。
    pointer = home / 'governance' / 'A06_figure_index.json'  # 显式展示索引。
    if pointer.is_file():  # 有用户修订图时先核实其归属。
        index = read_json(pointer)  # 不凭文件名选择最新版。
        if index.get('source_a06_run') == a06_result['run_id']:  # 旧A06的修订不能套到新结果。
            from docking_grouped_heatmap import current_display  # 共用网页的同源指纹验证。
            require(index.get('review_status') == 'approved', '当前热图修订尚未经过用户审核，不能写入报告')  # 助手核图不等于用户批准。
            current_display(workflow, a06_result)  # 核验图形元数据及PNG实际字节。
            return file_record(home, verified_file(home, index['metadata']), 'heatmap_metadata')  # 固定报告输入指纹。
    records = [record for record in a06_result.get('files', []) + a06_result.get('sources', []) if record.get('role') == 'heatmap_metadata']  # 历史A06原图记录。
    if records:  # 保持原A06显式元数据规则。
        require(len(records) == 1, 'A06绑定了多个热图元数据，不能猜测')  # 多版本须明确选择。
        path = verified_file(home, records[0])  # 核验原图指纹。
    else:  # 旧COPD保留已批准兼容位置。
        path = home / 'reports' / CONFIG['heatmap_metadata_name']  # 不扫描未知图文件。
        require(path.is_file(), 'A06未绑定热图元数据，且未找到兼容索引')  # 缺图不能静默忽略。
    return file_record(home, path, 'heatmap_metadata')  # 新报告始终绑定唯一图件。


def run_reports(workflow, study_id, expected_a07, reason, reuse_current_concise=False, task_package=None):  # 生成新的A07双报告修订。
    manifest = workflow.load(study_id)  # 读取当前研究状态。
    require(manifest["current"].get("A07", "") == expected_a07, "A07版本已改变，请刷新后重试")  # 防止旧页面覆盖新报告。
    study_home = workflow.location(study_id)  # 后续所有报告附件使用研究包相对路径。
    a06_id = manifest["current"].get("A06")  # 取得当前已批准A06。
    a06_result = workflow.result(manifest, a06_id) if a06_id else None  # 读取当前A06标准结果。
    task_records = []  # 任务包可选，历史报告继续读取原接口。
    if task_package:  # 当前研究可明确绑定同源PyMOL任务包。
        package_index_path = verified_file(study_home, task_package['index'])  # 必须由显式指纹记录指定。
        package_index = read_json(package_index_path)  # 读取已完成包的唯一索引。
        require(package_index['study_id'] == study_id and package_index['source_a06_run'] == a06_id, '任务包不是当前A06来源')  # 拒绝同维度其他运行。
        for item in package_index['files']:  # 原始资料、PDB和PSE都必须完整。
            verified_file(package_index_path.parent, item)  # 不只核对压缩包存在。
        require(package_index['completed_pair_count'] == a06_result['summary']['成功组合数'] and package_index['planned_pair_count'] == a06_result['summary']['计划组合数'], '任务包数量与A06不一致')  # 全计划与有效输出同源。
        verified_file(study_home, task_package['archive'])  # 压缩交付本身也必须通过指纹。
        task_records = [task_package['index'], task_package['archive']]  # 下载记录不挤占固定两份Word。
    heatmap_record = report_heatmap_record(workflow, a06_result)  # 优先使用用户已审核的同源展示修订。
    with write_lock(workflow.root):  # 在一次锁内固定上游、生成文件并发布结果。
        manifest = workflow.load(study_id)  # 锁内重新读取最新状态。
        require(manifest["current"].get("A07", "") == expected_a07, "A07版本已改变，请刷新后重试")  # 再次校验并发版本。
        require(report_heatmap_record(workflow, a06_result) == heatmap_record, "热图展示版本已改变，请刷新后重试")  # 锁内拒绝并发换图。
        inputs = {"heatmap_metadata": heatmap_record} if heatmap_record else {}  # 有效空A06没有图形输入。
        if task_package:  # 将任务包绑定到当前报告运行输入。
            inputs["task_package_index"] = task_package["index"]  # 运行记录回指唯一任务版本。
            inputs["task_package_archive"] = task_package["archive"]  # 下载包独立回指。
        run = workflow._begin(manifest, "A07", inputs, dict(CONFIG), reason)  # 自动固定A00至A06当前批准版本和复核编号。
        payload = assemble_payload(workflow, manifest, run["parent_runs"], heatmap_record)  # 生成唯一事实包。
        revision = "report_rev_" + run["run_id"].removeprefix("run_")  # 从稳定运行编号派生唯一报告修订号。
        report_dir = workflow.location(study_id) / "reports" / revision  # 每次报告修订使用独立目录。
        figure_paths = generate_report_figures(report_dir / "figures", payload)  # 从绑定运行表生成六张同源SVG和PNG。
        figure_keys = {"venn": "01_方剂疾病靶点韦恩图", "herb_compound_target": "02_药味成分交集靶点网络图", "ppi_full": "03_PPI完整网络图", "ppi_round1": "04_PPI第一轮主候选网络图", "go_faceted": "05_GO富集三分类柱状图", "kegg_bubble": "06_KEGG富集气泡图"}  # 建立报告语义键与稳定文件名映射。
        payload["report_figures"] = {key: {kind: file_record(workflow.location(study_id), figure_paths[name][kind], f"{key}_{kind}") for kind in ("svg", "png")} for key, name in figure_keys.items()}  # 记录每张图的两种格式和指纹。
        previous_comparison = None  # 默认不把毕业论文差异说明强加给其他研究。
        if expected_a07:  # 修订已有报告时检查其是否明确绑定过差异说明。
            previous_result = workflow.result(manifest, expected_a07)  # 核验当前A07结果。
            previous_index_record = next((record for record in previous_result.get("tables", {}).get("report_files", []) if record.get("role") == "report_index"), None)  # 定位旧索引。
            if previous_index_record:  # 旧索引存在才读取可选附件。
                previous_index = read_json(verified_file(study_home, previous_index_record))  # 核验旧索引自身。
                old_comparison = previous_index.get("comparison_report")  # 读取旧差异说明记录。
                if old_comparison:  # 只有指纹仍匹配的附件才能复制到新修订。
                    previous_comparison = verified_file(study_home if previous_index.get("schema_version") == "A07.report.index.3" else workflow.root, old_comparison)  # 兼容新旧相对根目录。
        payload["comparison_report_included"] = previous_comparison is not None  # 供专业报告决定是否显示附件提示。
        detailed_path = report_dir / "ModuleA_专业详细报告.docx"  # 使用稳定且可读的详细版名称。
        concise_path = report_dir / "ModuleA_临床简略报告.docx"  # 使用稳定且可读的简略版名称。
        comparison_path = report_dir / "ModuleA_既有研究结果差异说明.docx" if previous_comparison else None  # 可选附件进入本次唯一修订目录。
        build_detailed(payload, detailed_path, workflow.location(study_id), revision)  # 从共同事实包生成详细版。
        if reuse_current_concise and expected_a07:  # 本次仅修订专业版时保持临床简略报告字节不变。
            previous_a07 = workflow.result(manifest, expected_a07)  # 读取当前A07报告记录。
            require(workflow.run(manifest, expected_a07).get("parent_runs") == run.get("parent_runs"), "上游已变化，不能复用旧简略报告")  # 只允许纯报告版式修订复用。
            previous_concise = next(record for record in previous_a07["tables"]["report_files"] if record["role"] == "concise_report")  # 找到旧简略版。
            concise_path.write_bytes(verified_file(workflow.location(study_id), previous_concise).read_bytes())  # 原样复制到新修订目录。
        else:  # 常规A07运行继续生成同源简略报告。
            build_concise(payload, concise_path, workflow.location(study_id), revision)  # 从同一事实包生成简略版。
        if comparison_path:  # 当前研究已有明确差异说明时将其冻结到本次修订。
            comparison_path.write_bytes(previous_comparison.read_bytes())  # 字节级复制，保留已审核内容并禁止共享路径覆盖。
        detailed_record = file_record(workflow.location(study_id), detailed_path, "detailed_report")  # 记录详细版指纹。
        concise_record = file_record(workflow.location(study_id), concise_path, "concise_report")  # 记录简略版指纹。
        index_path = report_dir / "report_index.json"  # 索引与两份报告放在同一修订目录。
        report_index = {  # 建立可机读的报告发布索引。
            "schema_version": "A07.report.index.3",  # 第三版把可选差异说明保存在修订目录内。
            "study_id": study_id,  # 绑定当前研究。
            "run_id": run["run_id"],  # 绑定当前A07运行。
            "report_revision": revision,  # 保存可读修订编号。
            "template_version": CONFIG["template_version"],  # 固定模板版本。
            "analysis_purpose": payload["analysis_purpose"],  # 传播分析用途。
            "parent_runs": run["parent_runs"],  # 固定七个上游运行。
            "parent_review_ids": run["parent_review_ids"],  # 固定当时生效的七个复核决定。
            "selection_run": payload["selection_run"],  # 固定主候选选择版本。
            "heatmap_metadata": heatmap_record,  # 固定图形元数据；有效空结果为None。
            "reports": [detailed_record, concise_record],  # 保存两份Word及指纹。
            "figures": [record for pair in payload["report_figures"].values() for record in pair.values()],  # 保存六张图的SVG和PNG指纹。
            "comparison_report": file_record(study_home, comparison_path, "comparison_report") if comparison_path else None,  # 可选差异说明使用研究包内不可变路径。
            "docking_task_package": task_package,  # 与当前A06相同的固定姿势交付包。
            "conclusion_review_required": True,  # 明确生成后仍须人工复核。
            "created_at": now(),  # 保存报告生成时间。
        }  # 完成报告索引。
        write_json(index_path, report_index)  # 写入不可覆盖的新索引。
        index_record = file_record(workflow.location(study_id), index_path, "report_index")  # 记录索引自身指纹。
        report_files = [detailed_record, concise_record, index_record]  # A07固定三项正式文件。
        summary = {  # 形成网页和后续复核使用的摘要。
            "analysis_purpose": payload["analysis_purpose"],  # 传播流程测试标记。
            "报告修订": revision,  # 显示明确修订编号。
            "详细报告": detailed_path.name,  # 显示可读文件名。
            "简略报告": concise_path.name,  # 显示可读文件名。
            "差异说明": comparison_path.name if comparison_path else "本研究未绑定独立差异说明",  # 不为其他研究生成毕业论文比较。
            "共同结论草稿": payload["conclusion_draft"],  # 网页直接突出待核验结论。
            "研究线索数": len(payload["research_leads"]),  # 告知用户只需审核几条线索。
            "结论复核状态": "待专业复核",  # 不自动代签A07。
            "handoff_blocked": False,  # 文件完整后允许用户提交A07决定。
        }  # 结束A07摘要。
        tables = {  # 保存网页可复核和可追溯的结构化结果。
            "key_counts": payload["key_counts"],  # 两版报告共同数量。
            "research_leads": payload["research_leads"],  # 最多三条线索。
            "limitations": [{"限制": value} for value in payload["limitations"]],  # 共同限制列表。
            "report_files": report_files,  # 两份Word和索引。
            "report_figures": report_index["figures"],  # 网页和验收可核查全部图源。
            "version_bindings": [{"模块": module, "运行编号": run_id, "复核编号": run["parent_review_ids"].get(module)} for module, run_id in run["parent_runs"].items()],  # 七个上游版本与复核绑定。
        }  # 结束A07结构化表。
        anomalies = list(payload["limitations"])  # 异常与限制区沿用共同边界，不另造成功句式。
        check_result(summary, tables, anomalies, "success")  # 发布前检查统一结果结构。
        optional_sources = [record for record in (heatmap_record, payload["heatmap_png"]) if record]  # 有效空A06没有热图来源。
        sources = [manifest["runs"][run_id]["result_file"] for run_id in run["parent_runs"].values()] + optional_sources + payload["receptor_setup_sources"]  # 将七个上游结果及实际存在的结构来源纳入索引。
        attachments = task_records + report_files + report_index["figures"] + ([report_index["comparison_report"]] if report_index["comparison_report"] else [])  # 报告、索引、图源及可选差异说明均纳入指纹。
        result = workflow._finish(manifest, run["run_id"], summary, tables, anomalies, "success", sources=sources, attachments=attachments)  # 发布待复核A07标准结果。
        workflow.save(manifest)  # 原子更新研究索引。
    return result  # 返回网页可显示的A07结果。
