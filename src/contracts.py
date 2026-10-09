# 本文件定义所有模块共用的名称、依赖和数据校验，避免各写一套规则。
import hashlib  # 生成内容指纹，用于识别文件是否改变。
import json  # 统一数据的保存和交换格式。
import re  # 检查编号，阻止编号被当作任意文件路径。

SCHEMA_VERSION = "1.0"  # 固定本版交接格式的版本。
MODULES = {  # 模块顺序用于网页显示，依赖关系单独规定。
    "A00": ("研究登记", ()),  # 登记没有上游模块。
    "A01": ("成分与方剂靶点", ("A00",)),  # 方剂资料依赖已复核登记。
    "A02": ("疾病靶点", ("A00",)),  # 疾病资料也依赖已复核登记。
    "A03": ("交集与成分候选", ("A01", "A02")),  # 交集需要两侧资料同时通过。
    "A03_SELECT": ("A03主候选确认（仅对接分支）", ("A03",)),  # 内部选择关口不阻断PPI和富集。
    "A04": ("PPI 分析", ("A03",)),  # PPI 从已复核交集开始。
    "A05": ("GO 与 KEGG 富集", ("A03",)),  # 富集与 PPI 独立推进。
    "A06_PREP": ("对接对象与配置复核", ("A03", "A03_SELECT", "A04")),  # 先确认成分、蛋白、结构及配置。
    "A06": ("分子对接结果", ("A06_PREP",)),  # 对象准备通过后才允许真正对接。
    "A07": ("双报告与结论复核", ("A00", "A01", "A02", "A03", "A04", "A05", "A06")),  # 汇总各必需分支。
}  # A06_PREP 是 A06 内部审核关口，不是新增科学分析。

class ContractError(ValueError):  # 用可读错误统一报告输入、版本和复核问题。
    pass  # 沿用标准异常的消息功能。

def require(condition, message):  # 只有条件符合时才能进入下一步。
    if not condition:  # 检查调用者提交的数据或状态。
        raise ContractError(message)  # 将具体问题交给网页或测试显示。

def encoded(value):  # 用固定方式序列化，保证内容一致时指纹一致。
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")).encode("utf-8")  # 禁止 NaN 等非标准数值。

def fingerprint(value):  # 给结构化数据生成 SHA256 指纹。
    return hashlib.sha256(encoded(value)).hexdigest()  # 返回适合保存和比较的文字。

def safe_id(value, prefix):  # 限定研究、运行、产物和复核编号格式。
    require(isinstance(value, str) and re.fullmatch(prefix + r"_[0-9a-f]{32}", value), "编号格式不合法")  # 不允许路径符号或任意名称。
    return value  # 返回已检查的编号。

def check_module(module):  # 防止模块名称拼写错误或伪造模块。
    require(module in MODULES, "未知模块")  # 只接受明确登记的模块。
    return module  # 返回已核对的名称。

def check_intake(data):  # 校验研究登记的基本完整性，不自行补充科学信息。
    require(isinstance(data, dict), "研究登记必须是对象")  # 输入必须具有命名字段。
    for name in ("formula", "herbs", "disease", "disease_scope", "operator"):  # 这些字段由用户填写并复核。
        require(isinstance(data.get(name), str) and 0 < len(data[name].strip()) <= 2000, "请完整填写方剂、药味、疾病、范围和登记人")  # 空白或过长文字不能通过。
    require(data.get("species") == 9606, "本版研究物种必须为人类 9606")  # 严格采用大纲的人类范围。
    purpose = data.get("analysis_purpose")  # 历史登记允许没有用途字段，新登记必须由网页明确保存。
    require(purpose is None or purpose in ("formal_research", "workflow_test"), "研究用途只能是正式研究或流程测试")  # 不凭MeSH身份推断用途。
    mesh_fields = (data.get("mesh_term"), data.get("mesh_id"), data.get("mesh_verification"))  # 历史登记可以没有MeSH，新登记一旦提供就必须完整。
    require(not any(mesh_fields) or all(mesh_fields), "MeSH标准词、编号和官方核对证据必须同时保存")  # 防止半套身份进入版本链。
    if all(mesh_fields):  # 新网页建立的研究执行正式身份校验。
        from mesh_identity import validate_mesh_identity  # 延迟导入避免基础契约形成循环依赖。
        validate_mesh_identity(data)  # 词、编号、年度和证据必须一致。

def check_result(summary, tables, anomalies, outcome):  # 约束结果外壳，不替代各科学模块的数据校验。
    require(isinstance(summary, dict) and isinstance(tables, dict), "结果摘要和明细表格式错误")  # 摘要和表索引必须具备明确字段。
    require(isinstance(anomalies, list) and all(isinstance(item, str) for item in anomalies), "异常清单必须是文字列表")  # 异常不混入数值结果。
    require(outcome in ("success", "empty", "failed") or (outcome == "partial" and isinstance(tables.get("generic_docking"), dict)), "部分完成仅适用于已验证的通用对接结果")  # 明确区分失败与空集合。
    for name, rows in tables.items():  # 每张表分别检查。
        require(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name), "表名须使用简明英文标识")  # 内部表名不参与任意路径拼接。
        if name == "generic_docking" and isinstance(rows, dict):  # 对接事实包使用专门契约，不放宽普通表。
            from docking_contract import validate_generic_result  # 延迟导入避免循环依赖。
            validate_generic_result(rows)  # 核对矩阵、姿势和失败原因。
            require(rows["outcome"] == outcome, "对接事实包与外壳状态不一致")  # 状态必须同源。
            continue  # 普通表仍遵守平面单元格规则。
        require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), "明细表须由记录对象组成")  # 各行必须可以按字段解释。
        require(all(all(isinstance(key, str) for key in row) for row in rows), "表字段名必须是文字")  # 保证统一字段索引。
        require(all(all(value is None or isinstance(value, (str, int, float, bool)) for value in row.values()) for row in rows), "表单元格须为简单值，结构文件单独关联")  # 不把大型对象塞入单元格。
    encoded({"summary": summary, "tables": tables, "anomalies": anomalies})  # 进一步验证数据可严格保存为 JSON。
