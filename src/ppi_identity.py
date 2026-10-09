# STRING身份补查仅在明确批准的研究与上游版本内生效。
import csv  # 读取官方HGNC快照。
import io  # 不生成临时表。
import json  # 解析原始响应。
import hashlib  # 固定证据指纹。
from pathlib import Path  # 定位研究级授权，不把新病例写死在代码。
from storage import read_json, verified_file  # 核验授权绑定的真实上游。
from contracts import require  # 异常明确阻断。
SNAPSHOT = "9e07bb49393c12aca8bc931a4349010404c24994a8a58745c14676b8c2b74492"  # 已归档HGNC原件。
SCOPE = {"study_id":"study_28a9580bd87543c98892e3c7ce4d1426", "a03_run":"run_9962119da1624fd0860320f6aa111920", "decision":"用户明确同意并要求写入规则；2026-09-13；AGENTS.md：A04 STRING映射缺口处理", "check_ids":["HGNC:125","HGNC:12680","HGNC:5525"], "omit_ids":["HGNC:12680","HGNC:5525"]}  # COPD授权不外推。
RHINITIS_SCOPE = {"study_id":"study_26fce8e06ccc44a1a4fa7cefc8f789ba", "a03_run":"run_aeadcc9b674a49b6b53441ed42657de6", "decision":"用户明确同意按稳定编号核对；ACP3证据一致后接入，VEGFA仍无唯一正确匹配时仅退出本次PPI；2026-10-04", "check_ids":["HGNC:125","HGNC:12680"], "omit_ids":["HGNC:12680"]}  # 仅绑定当前过敏性鼻炎测试。
SCOPES = {(item["study_id"],item["a03_run"]):item for item in (SCOPE,RHINITIS_SCOPE)}  # 每项授权都绑定研究和上游版本。
BASE = "https://version-12-0.string-db.org/api/json/"  # 固定STRING版本。

def authorization(sid, a03, root=None):  # 读取与研究及A03同时匹配的人工决定。
    legacy = SCOPES.get((sid, a03))  # 保留已发布历史决定的原格式。
    if legacy is not None or root is None:  # 历史复算不依赖新增文件。
        return legacy  # 未提供项目位置时不隐式猜目录。
    require(Path(sid).name == sid and Path(a03).name == a03 and sid not in ('.', '..') and a03 not in ('.', '..'), "授权身份不能含路径")  # 防止越界读取。
    home = Path(root) / 'studies' / sid  # 每项新决定留在所属研究。
    path = home / 'governance' / ('A04_identity_authorization_' + a03 + '.json')  # 文件名绑定准确A03，不按日期猜版本。
    if not path.exists():  # 无明确本轮决定时不沿用旧例外。
        return None  # 正常身份检查继续保持阻断。
    record = read_json(path)  # 读取用户明确授权的版本化记录。
    scope = record.get('scope', {})  # 保留授权本身与诊断资料的区别。
    require(record.get('schema_version') == 'A04.identity.authorization.1' and record.get('status') == 'user_approved' and scope.get('study_id') == sid and scope.get('a03_run') == a03 and bool(scope.get('decision')), "PPI身份授权记录不完整或不属于本版")  # 不能只凭文件存在放行。
    parent = read_json(verified_file(home, record['a03_result']))  # 上游文件指纹必须一致。
    require(parent['run_id'] == a03 and parent['module_id'] == 'A03', "身份授权绑定的交集版本错误")  # 不允许另一个结果借用决定。
    ids = {row['target_id'] for row in parent['tables']['intersection_targets']}  # 验证实际交集覆盖。
    require(set(scope.get('check_ids', [])) <= ids and set(scope.get('omit_ids', [])) <= set(scope.get('check_ids', [])), "身份授权范围与交集不一致")  # 不扩展到交集之外。
    return scope  # 接口用于各个完整或缺库研究，不改变科学核查规则。

def context(root, sid, a03):  # 其他研究不自动套用例外。
    if authorization(sid,a03,root) is None:  # 绑定用户确认的输入版本。
        return None  # 保留原有严格核对。
    raw = (root / "references/hgnc_complete_set_20260913.tsv").read_bytes()  # 使用已固定官方证据。
    require(hashlib.sha256(raw).hexdigest() == SNAPSHOT, "HGNC补查快照指纹不一致")  # 不随更新改变历史规则。
    return raw  # 发布时引用归档副本。

def queries(targets, raw, approved_scope=SCOPE):  # 从完整官方快照派生查询，不手填替代基因。
    require(raw is not None and hashlib.sha256(raw).hexdigest() == SNAPSHOT, "缺少已批准HGNC快照")  # 导入也须同一证据。
    records = {r["hgnc_id"]:r for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter="\t")}  # 按稳定身份读取。
    selected = {t["target_id"]:t for t in targets}  # 不改变上游集合。
    check_ids=tuple(approved_scope["check_ids"])  # 每项研究只核对实际发现的问题。
    require(all(g in selected for g in check_ids), "本次身份授权与交集不一致")  # 不迁移到其他输入。
    result = []  # 固定顺序便于复算。
    for gid in check_ids:  # 集中核对本研究已发现的问题。
        row = records[gid]  # 原快照行可回查。
        require(row["symbol"] == selected[gid]["symbol"], "交集名称与HGNC快照不一致")  # 不靠旧名字猜。
        names = [row["symbol"]] + [x for x in row["prev_symbol"].split("|") if x]  # 只使用官方现名和旧名。
        for field in ("uniprot_ids", "ensembl_gene_id"):  # 两类稳定编号独立请求。
            for value in filter(None, row[field].split("|")):  # 不任取多值第一项。
                result.append({"target_id":gid, "identifier":value, "field":field, "names":names})  # 保存查询来源。
    return result  # 空值不虚构编号。

def params(identifier):  # 与获取及校验共用同一请求定义。
    return {"identifiers":identifier, "species":9606, "echo_query":1, "caller_identity":"ModuleA"}  # 每个编号单独查询。

def resolve(targets, mapping, evidence, raw, approved_scope=SCOPE):  # 对原响应做可复算派生，不篡改原响应。
    require(evidence.get("authorization") == approved_scope and evidence.get("hgnc_sha256") == SNAPSHOT, "身份处理授权或证据不一致")  # 不接受来源包自拟例外。
    expected = queries(targets, raw, approved_scope)  # 重新从官方快照得到编号。
    probes = evidence.get("queries", [])  # 保存实际请求及响应。
    require(len(probes) == len(expected), "身份补查资料不完整")  # 缺请求不能当无匹配。
    grouped = {gid:[] for gid in approved_scope["check_ids"]}  # 分基因核对。
    for spec, probe in zip(expected, probes):  # 查询顺序与编号逐一绑定。
        source = probe["source"]  # 原始HTTP响应归档。
        require(probe["query"] == spec and source["url"] == BASE + "get_string_ids" and source["params"] == params(spec["identifier"]) and bool(source["retrieved_at"]), "补查请求与官方编号不一致")  # 不接受替换查询。
        rows = json.loads(source["response_text"])  # 空列表与失败对象不同。
        require(isinstance(rows, list) and all(int(r["queryIndex"]) == 0 and r.get("queryItem") == spec["identifier"] for r in rows), "补查响应不属于本次编号")  # 不借其他返回行通过。
        grouped[spec["target_id"]].append((spec, rows))  # 保留成功空结果。
    corrected = [dict(r) for r in mapping]  # 不修改原始来源对象。
    adjustments, excluded = [], []  # 已解决与本次不采用分开。
    for index, target in enumerate(targets):  # 保留原输入顺序。
        gid = target["target_id"]  # 稳定身份作为索引。
        if gid not in grouped:  # 无授权的其他问题仍由旧内核阻断。
            continue  # 不自动扩大例外。
        checks = grouped[gid]  # 两类稳定编号结果。
        valid = bool(checks) and all(len(rows) == 1 and int(rows[0]["ncbiTaxonId"]) == 9606 and rows[0]["stringId"].startswith("9606.") and rows[0]["preferredName"] in spec["names"] for spec, rows in checks)  # 必须全部唯一且名称有官方依据。
        ids = {rows[0]["stringId"] for spec, rows in checks if len(rows) == 1}  # 多编号不任取。
        original = [r for r in mapping if int(r["queryIndex"]) == index]  # 查明原始名称响应。
        if valid and len(ids) == 1:  # 全部官方编号一致才接入。
            sid = next(iter(ids))  # 唯一STRING蛋白。
            require(len(original) <= 1 and (not original or original[0]["stringId"] == sid), "名称与稳定编号相互冲突，须重新核对")  # 不覆盖编号反证。
            corrected = [r for r in corrected if int(r["queryIndex"]) != index]  # 仅替换派生映射。
            corrected.append({"queryIndex":index,"queryItem":target["symbol"],"ncbiTaxonId":9606,"preferredName":target["symbol"],"stringId":sid})  # 计算器用HGNC现名，原返回名另存。
            adjustments.append(dict(target, string_id=sid, returned="|".join(sorted({rows[0]["preferredName"] for spec, rows in checks})), identifiers="|".join(spec["identifier"] for spec, rows in checks), reason="官方现名/旧名与全部稳定编号一致"))  # 名称转换不隐去。
        elif gid in approved_scope["omit_ids"] and checks and all(not rows for spec, rows in checks):  # 仅成功空响应适用本次明确授权。
            require(not any(r["preferredName"] == target["symbol"] for r in original), "名称已匹配但稳定编号无结果，须核对而非自动排除")  # 新情况不套用旧缺口。
            excluded.append(dict(target, identifiers="|".join(spec["identifier"] for spec, rows in checks), returned="|".join(r["preferredName"] for r in original), reason="官方编号补查成功无匹配；用户同意仅本次PPI暂不采用，仍保留A03及富集输入", decision=approved_scope["decision"]))  # 不写零度数。
    return corrected, adjustments, excluded  # 未解决问题继续保持阻断。
