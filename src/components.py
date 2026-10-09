# A01仅整理本地数据库证据，人工复核后才供下游使用。
import csv  # 读取制表符分隔的原始表。
import hashlib  # 核对实际读取的数据快照。
import io  # 从已核验字节读取，防止读取期间文件被替换。
import math  # 排除无穷大等无效数值。
import re  # 识别药味分隔符与明确标识。
from collections import defaultdict  # 汇总去重关系及来源。
from contracts import require  # 沿用统一可读错误。
from storage import file_record, read_json, write_json, write_lock  # 沿用研究包归档和锁。
CONFIG = {"ob_min": 30.0, "dl_min": 0.18, "species": 9606, "identity": "TCMSP_MOLID", "mapping": "snapshot_UniProtAC_GeneNames", "version": "A01.1"}  # 仅写入大纲已确认的科学参数。
REQUIRED = {"Chinesename", "MOLID", "moleculename", "ob", "dl", "UniProtAC", "GeneNames", "Organism"}  # 缺列时不猜字段。
TABLE_LABELS = {"components": "筛选后成分", "herb_components": "药味与成分关系", "compound_targets": "去重成分—人类靶点关系", "targets": "人类靶点映射", "herb_summary": "各药味数量", "exclusions": "逐条排除与待核验记录"}  # 网页名称与内部表名分开。
FIELD_LABELS = {"compound_id": "成分编号", "name": "数据库成分名称", "herb": "药味", "herbs": "全部来源药味", "ob": "预测OB（%）", "dl": "预测DL", "gene": "数据库基因符号", "uniprot": "UniProt标识", "species": "物种编号", "mapping_status": "映射依据与状态", "raw_rows": "原始关系记录数", "components": "筛选后不同成分数", "human_genes": "不同人类基因数", "human_targets": "不同人类基因数", "reason": "排除或待核验原因", "source_lines": "原表行号", "source_line": "原表行号", "organism": "原物种", "status": "身份状态"}  # CSV仍保留稳定字段名。

def parse_herbs(value):  # 只拆分明确分隔的药味，不替换药材名称。
    herbs = list(dict.fromkeys(x for x in re.split(r"[\s,，、;；]+", value.strip()) if x))  # 相同药名不重复计数，原登记仍保留。
    require(bool(herbs), "请在登记中填写药味名称，以顿号或逗号分隔")  # 不从方剂名称猜处方。
    return herbs  # 配比和别名不会被自动去除或换算。

def select_rows(root, herbs):  # 在固定共享快照里查找本研究所需记录。
    meta = read_json(root / "references" / "tcmsp_snapshot.json")  # 保存来源版本及限制。
    path = root / "references" / "tcmsp_snapshot.tsv"  # 不依赖旧代码所在位置。
    raw = path.read_bytes()  # 一次读取，使核验与解析针对相同字节。
    require(hashlib.sha256(raw).hexdigest() == meta["sha256"] and len(raw) == meta["bytes"], "TCMSP快照校验失败，请停止使用并核查来源")  # 文件变化不能静默沿用。
    reader = csv.DictReader(io.TextIOWrapper(io.BytesIO(raw), encoding=meta["encoding"], errors="strict"), delimiter="\t")  # 不丢弃无法解码的字节。
    require(REQUIRED <= set(reader.fieldnames or []), "TCMSP快照缺少必要字段")  # 不猜测列的含义。
    selected = []  # 保存筛选前全部相关记录。
    for line, row in enumerate(reader, 2):  # 行号包括第一行表头。
        if row["Chinesename"].strip() in herbs:  # 仅按用户明确药名匹配。
            require(None not in row and all(row.get(key) is not None for key in REQUIRED), "原始表行结构不完整：" + str(line))  # 拒绝错列输入。
            selected.append(dict(row, source_line=line))  # 保留原字段原值和来源定位。
    missing = set(herbs) - {row["Chinesename"].strip() for row in selected}  # 区分药味未收录与筛选后为空。
    require(not missing, "快照未匹配药味：" + "、".join(sorted(missing)) + "。请核对药名；确需补充时先讨论来源，不自动替换药材。")  # 不让缺药味形成貌似全方的结果。
    return selected, meta  # 返回可随研究包保存的原始记录及总快照指纹。

def number(value):  # 判断预测指标是否可用。
    try:  # 空值或非数字不等于零。
        result = float(value)  # 保留原数值，不擅自换算单位。
        return result if math.isfinite(result) else None  # 非有限数不参加阈值比较。
    except (ValueError, TypeError):  # 缺失指标交由异常流程处理。
        return None  # 不能只用另一项指标替代。

def analyze(rows, herbs):  # 同一计算函数供本地查询和后续导入接口复用。
    identities = defaultdict(set)  # 检查同一编号的身份与预测值是否矛盾。
    mappings = defaultdict(set)  # 检查同一蛋白标识是否出现多基因冲突。
    for row in rows:  # 冲突检查覆盖筛选前的相关记录。
        cid = row["MOLID"].strip()  # 数据库编号是本阶段身份键。
        identities[cid].add((row["moleculename"].strip(), number(row["ob"]), number(row["dl"])))  # 不凭名称合并其他编号。
        if row["Organism"].strip() == "Homo sapiens (Human)" and row["UniProtAC"].strip():  # 非人类记录不混入人类映射检查。
            mappings[row["UniProtAC"].strip()].add(row["GeneNames"].strip())  # 保留所有候选基因符号。
    compounds, memberships, edges, targets, excluded = {}, defaultdict(list), defaultdict(list), defaultdict(list), []  # 分开保存成分、药味和靶点关系。
    qualified = 0  # 记录通过预测阈值的原始行数。
    for row in rows:  # 每条输入均明确处理。
        cid, herb, line = row["MOLID"].strip(), row["Chinesename"].strip(), row["source_line"]  # 保留原表定位。
        ob, dl = number(row["ob"]), number(row["dl"])  # 缺失不会按零纳入统计。
        reason = ""  # 空原因才允许继续处理。
        if not re.fullmatch(r"MOL\d+", cid) or len(identities[cid]) != 1:  # 身份不清时不强行去重。
            reason = "成分编号缺失或同编号身份/预测值冲突，待核验"  # 具体原行仍在研究包中。
        elif ob is None or dl is None:  # 大纲未授权缺指标替代规则。
            reason = "OB/DL缺失或无效，待补充与复核"  # 不自动放行。
        elif ob < CONFIG["ob_min"] or dl < CONFIG["dl_min"]:  # 两条件同时满足才通过。
            reason = "未同时达到OB≥30%且DL≥0.18"  # 明确排除依据。
        else:  # 成分通过已批准的预测筛选。
            qualified += 1  # 这是原始行数，不是成分个数。
            compounds[cid] = {"compound_id": cid, "name": row["moleculename"].strip(), "ob": ob, "dl": dl, "status": "按TCMSP编号整理；结构身份尚待候选阶段核验"}  # 不宣称已经验证结构。
            memberships[(herb, cid)].append(line)  # 保留共享成分的全部药味来源。
            acc, gene = row["UniProtAC"].strip(), row["GeneNames"].strip()  # 原值保存在raw快照。
            if not row["Organism"].strip():  # 缺物种不能当作已知非人类。
                reason = "物种缺失，待核验"  # 不纳入主靶点集合。
            elif row["Organism"].strip() != "Homo sapiens (Human)":  # 仅主分析人类范围已批准。
                reason = "非人类靶点，不纳入主分析"  # 原非人类行不删除。
            elif not acc or not gene:  # 缺字段与无生物学靶点不是同一含义。
                reason = "靶点标识或基因符号缺失，待核验"  # 保留缺失原因。
            elif len(mappings[acc]) != 1 or not re.fullmatch(r"[A-Z0-9]+(?:-\d+)?", acc) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", gene):  # 不拆分歧义映射并取第一项。
                reason = "靶点映射冲突、多值或标识格式待核验"  # 交由专业人员处理。
            else:  # 可明确读取的快照人类映射进入待复核主表。
                edges[(cid, acc, gene)].append(line)  # 同成分同蛋白同基因只保留一条主关系。
                targets[(acc, gene)].append(line)  # 不同蛋白到同一基因仍保留映射关系。
        if reason:  # 正常排除和待核验均有明细。
            excluded.append({"source_line": line, "herb": herb, "compound_id": cid, "organism": row["Organism"], "reason": reason})  # 原记录无需在异常表中重复全部字段。
    line_text = lambda values: ";".join(map(str, sorted(set(values))))  # 来源行号用稳定顺序编码，便于CSV保存。
    for cid, item in compounds.items():  # 补充成分去重后的来源和人类关系数。
        item["herbs"] = "、".join(herb for herb in herbs if (herb, cid) in memberships)  # 所有来源药味都保留。
        item["human_targets"] = len({gene for comp, acc, gene in edges if comp == cid})  # 按不同基因计数，避免多蛋白重复。
    tables = {"components": [compounds[k] for k in sorted(compounds)], "herb_components": [{"herb": herb, "compound_id": cid, "source_lines": line_text(lines)} for (herb, cid), lines in sorted(memberships.items())], "compound_targets": [{"compound_id": cid, "uniprot": acc, "gene": gene, "species": 9606, "source_lines": line_text(lines)} for (cid, acc, gene), lines in sorted(edges.items())], "targets": [{"uniprot": acc, "gene": gene, "species": 9606, "mapping_status": "源表人类映射，待专业复核；未在线更新", "source_lines": line_text(lines)} for (acc, gene), lines in sorted(targets.items())], "exclusions": excluded}  # 表名和字段固定，网页中文另行映射。
    tables["herb_summary"] = [{"herb": herb, "raw_rows": sum(row["Chinesename"].strip() == herb for row in rows), "components": sum(h == herb for h, cid in memberships), "human_genes": len({gene for cid, acc, gene in edges if (herb, cid) in memberships})} for herb in herbs]  # 药味共享成分数不可直接相加当全方数。
    summary = {"原始关系记录数": len(rows), "通过OB/DL的关系记录数": qualified, "筛选后不同成分数": len(compounds), "人类关系证据行数": sum(map(len, edges.values())), "去重成分—人类靶点关系数": len(edges), "不同人类基因数": len({gene for acc, gene in targets}), "排除或待核验记录数": len(excluded)}  # 不把关系记录数写作成分数。
    anomalies = ["本地软件提取快照的数据库发布版本未知；不是已核实的官方最新版。", "OB/DL为预测筛选，不代表样品检出、含量或体内暴露；同名不同编号未强行合并。", "人类映射来自原表，未在线核实当前UniProt/HGNC；须专业复核后用于下游。"]  # 明确证据边界。
    if any("待" in row["reason"] for row in excluded):  # 数据缺失不隐藏在普通阈值排除中。
        anomalies.append("存在身份、指标或映射待核验记录；补充处理规则需确认，不得据此声称资料完整。")  # 供网页提醒与后续审核。
    return summary, tables, anomalies  # 三者由同一批原始记录生成。

def validate_components(run, summary, tables, anomalies, outcome):  # 接入统一提交前的专用检查。
    require(run["config"] == CONFIG, "A01配置与已批准规则不一致")  # 不接受静默改阈值。
    require(set(tables) == set(TABLE_LABELS), "A01结果表缺失或多出未知表")  # 防止占位结果通过。
    ids = {row["compound_id"] for row in tables["components"]}  # 明确当前成分集合。
    require(len(ids) == len(tables["components"]) == summary["筛选后不同成分数"], "A01成分数量不一致")  # 去重与摘要一致。
    require(all(row["ob"] >= 30 and row["dl"] >= .18 for row in tables["components"]), "A01成分阈值不一致")  # 复核筛选输出。
    edges = tables["compound_targets"]  # 关系表是后续交集的输入。
    require(all(row["species"] == 9606 and row["compound_id"] in ids for row in edges), "A01存在非人类或未知成分关系")  # 防止成员错配。
    require(len({(row["compound_id"], row["uniprot"], row["gene"]) for row in edges}) == len(edges) == summary["去重成分—人类靶点关系数"], "A01关系重复或数量不一致")  # 不重复计数。
    require({(row["uniprot"], row["gene"]) for row in edges} == {(row["uniprot"], row["gene"]) for row in tables["targets"]}, "A01映射与关系不一致")  # 靶点集合不能额外增加。
    require(len({row["gene"] for row in edges}) == summary["不同人类基因数"], "A01基因数不一致")  # 基因数与蛋白映射行数区分。
    require(outcome == ("success" if ids else "empty"), "A01空结果状态不一致")  # 不凑成分或隐藏空集。

def run_components(workflow, study_id, expected_a00, expected_a01, reason):  # 网页与未来独立调用共用的执行入口。
    require(bool(reason.strip()), "请填写运行或重跑原因")  # 每次新版本均保留理由。
    with write_lock(workflow.root):  # 固定读取、上游批准和发布，防止旧页面覆盖新版本。
        manifest = workflow.load(study_id)  # 读取当前研究。
        require(not manifest.get("trashed", False), "研究在回收站中，请先恢复")  # 回收站只读。
        require(manifest["current"].get("A00") == expected_a00 and manifest["current"].get("A01", "") == expected_a01, "页面版本已改变，请刷新后再运行A01")  # 重复点击不能创建重复运行。
        require(workflow.approved(manifest, expected_a00), "请先复核通过A00研究登记")  # 未批准登记不用于科学处理。
        intake = workflow.result(manifest, expected_a00)["summary"]  # 使用明确批准的输入快照。
        herbs = parse_herbs(intake["herbs"])  # 不从其他研究取药味。
        rows, meta = select_rows(workflow.root, herbs)  # 读取经过指纹核验的本地资料。
        summary, tables, anomalies = analyze(rows, herbs)  # 预检失败时尚未创建新的运行。
        outcome = "success" if tables["components"] else "empty"  # 有效空集合照常留档。
        validate_components({"config": CONFIG}, summary, tables, anomalies, outcome)  # 写文件前验证科学输出。
        inputs = {"herbs": herbs, "source_id": meta["source_id"], "source_sha256": meta["sha256"]}  # 记录重现所需输入身份。
        run = workflow._begin(manifest, "A01", inputs, dict(CONFIG), reason)  # 沿用现有运行与依赖体系。
        root = workflow.location(study_id)  # 资料只写入当前研究包。
        folder = root / "raw" / run["run_id"]  # 每次运行保存独立来源快照。
        write_json(folder / "tcmsp_selected.json", rows)  # 保存筛选前全部命中行及原值。
        write_json(folder / "tcmsp_source.json", meta)  # 原数据库版本未知也如实保留。
        sources = [file_record(root, folder / name, "source") for name in ("tcmsp_selected.json", "tcmsp_source.json")]  # 来源文件参与结果完整性校验。
        result = workflow._finish(manifest, run["run_id"], summary, tables, anomalies, outcome, sources=sources)  # 归档表格与标准结果。
        workflow.save(manifest)  # 完整结果发布为待复核，不自动批准。
        return result  # 网页重新加载同一已保存事实。
