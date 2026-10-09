# 人工复核后的安全自动接续；只运行已有明确规则的模块，遇到人工判断立即暂停。
from components import run_components  # A00通过后可以按固定本地来源生成A01。
from a02_auto_prepare import prepare as prepare_a02  # A00通过后自动准备OTP与TTD公开来源。
from enrichment_flow import run_enrichment  # A03通过后可以按固定配置生成A05。
from intersection_flow import run_intersection  # A01和A02通过后可以生成A03。
from ppi_flow import run_ppi  # A03通过后可以从STRING生成A04。
from report_dispatch import run_reports  # A00至A06均通过后可以生成A07双报告。
from docking_automation import current_plan, start_job  # 通用后台执行和交付入口。
from docking_generic_prep import prepare_screen  # A04与候选通过后自动整理通用受体筛查关口。


def _approved(workflow, manifest, module):  # 判断一个模块是否存在当前有效且通过的版本。
    run_id = manifest.get("current", {}).get(module)  # 读取当前指针。
    return bool(run_id and workflow.approved(manifest, run_id))  # 复用完整文件和复核校验。


def _needs_run(workflow, manifest, module):  # 判断模块缺失或因上游变化已经失效。
    run_id = manifest.get("current", {}).get(module)  # 取得可能存在的旧版本。
    return not run_id or not workflow.active(manifest, run_id)  # 历史存在不等于仍可使用。


def _modern_profile(manifest):  # 判断是否采用A00预上传和五库自动准备流程。
    return manifest.get("workflow_profile") in ("A00.preupload.1", "A00.preupload.2")  # 历史新版与缺GeneCards测试版都应自动接续。


def continue_after_review(workflow, study_id):  # 自动推进到下一批必须人工复核的结果。
    created = []  # 保存本次实际新生成的模块。
    errors = []  # 单一并行分支失败不隐藏其他分支结果。
    manifest = workflow.load(study_id)  # 每个阶段从当前研究重新读取状态。
    if not _approved(workflow, manifest, "A00"):  # 研究登记未通过时没有科学模块资格。
        return {"created": created, "waiting": "请先通过A00研究登记", "errors": errors}  # 明确停点。
    modern = _modern_profile(manifest)  # 两版新研究均按A00预上传与五库自动方案接续。
    if modern and _needs_run(workflow, manifest, "A01"):  # 新流程先生成不依赖联网的方剂侧结果。
        try:  # 方剂资料问题不阻止疾病侧如实形成候选版本。
            result = run_components(workflow, study_id, manifest["current"]["A00"], manifest["current"].get("A01", ""), "A00通过后自动生成A01成分与方剂靶点")  # 使用固定TCMSP规则。
            created.append(result["module_id"])  # A01仍须人工复核。
        except Exception as error:  # 药味不匹配或本地快照异常应显示真实原因。
            errors.append("A01自动生成未完成：" + str(error))  # 不影响A02独立准备。
        manifest = workflow.load(study_id)  # A01可能已发布，重新读取当前状态。
    if modern and _needs_run(workflow, manifest, "A02"):  # 再解析暂存资料并独立获取三个自动来源。
        try:  # 每个自动数据库的失败会在A02内部形成明确状态。
            prepared = prepare_a02(workflow, study_id)  # 形成可查看但仍受门控的A02候选版本。
            created.append("A02:" + prepared["run_id"])  # 页面显示真实运行编号。
        except Exception as error:  # A02整体契约错误不撤销已形成的A01。
            errors.append("A02自动准备未完成：" + str(error))  # 留给用户补资料或重试。
        manifest = workflow.load(study_id)  # 后续判断采用最新两项状态。
    if modern and (created or errors):  # 本次新流程已完成至少一次实际尝试。
        ready = all(manifest["current"].get(module) and workflow.active(manifest, manifest["current"][module]) for module in ("A01", "A02"))  # 判断一次复核表单是否具备显示条件。
        waiting = "A01和A02已生成，请在原卡片查看并一次提交两项复核决定" if ready else "请查看A01/A02卡片中的失败或资料缺口；补齐后重试未完成项"  # 不声称失败模块已经生成。
        return {"created": created, "waiting": waiting, "errors": errors}  # 停在人工复核关口。
    if not modern and _needs_run(workflow, manifest, "A02"):  # 历史流程保持原先的公开来源准备顺序。
        try:  # 身份歧义或网络失败不能阻止本地方剂分支。
            prepared = prepare_a02(workflow, study_id)  # 不自动决定疾病范围或补造三个人工库。
            created.append("A02:" + prepared["run_id"])  # 页面可显示实际生成版本。
        except Exception as error:  # 错误保留给用户处理，不形成部分A02。
            errors.append("A02公开来源自动准备未完成：" + str(error))  # 明确需要人工核对或稍后重试。
        manifest = workflow.load(study_id)  # A02可能已生成，重新读取当前状态。
    if not modern and _needs_run(workflow, manifest, "A01"):  # 历史流程继续按原方式生成方剂侧结果。
        result = run_components(workflow, study_id, manifest["current"]["A00"], manifest["current"].get("A01", ""), "复核通过后自动接续：生成A01成分与方剂靶点")  # 使用生产入口并保留原因。
        created.append(result["module_id"])  # 新结果必须先由用户复核。
        message = "A01和A02已生成，请在原卡片查看；可以一次提交两项复核决定" if manifest.get("workflow_profile") == "A00.preupload.1" and manifest["current"].get("A02") else "A01已生成，请核对重点并复核；A02疾病资料已自动准备公开来源时，请补齐人工来源"  # 新旧流程分别提示。
        return {"created": created, "waiting": message, "errors": errors}  # 不越过新人工关口。
    if not _approved(workflow, manifest, "A01"):  # 已有A01但尚未通过。
        return {"created": created, "waiting": "请先复核A01；A02可以独立准备", "errors": errors}  # 不重复运行。
    if not _approved(workflow, manifest, "A02"):  # 疾病资料涉及来源和范围人工决定。
        return {"created": created, "waiting": "请完成并复核A02疾病资料；系统不会自动替你下载受限数据库或决定疾病范围", "errors": errors}  # 明确不能自动的原因。
    manifest = workflow.load(study_id)  # A01和A02齐备后重新读取指针。
    if _needs_run(workflow, manifest, "A03"):  # 交集计算不需要新增人工参数。
        expected = {key: manifest["current"].get(key, "") for key in ("A01", "A02", "A03")}  # 绑定当前两侧版本。
        result = run_intersection(workflow, study_id, expected, "复核通过后自动接续：生成A03交集与候选排序")  # 使用生产入口生成新版本。
        created.append(result["module_id"])  # A03结论仍需总体复核。
        return {"created": created, "waiting": "A03已生成，请核对交集、双排序和候选范围后复核", "errors": errors}  # 在人工候选判断前暂停。
    if not _approved(workflow, manifest, "A03"):  # 已有交集尚未批准。
        return {"created": created, "waiting": "请先复核A03交集结果", "errors": errors}  # 不自动选择成分。
    manifest = workflow.load(study_id)  # A03通过后两个分析分支可以独立推进。
    if _needs_run(workflow, manifest, "A04"):  # PPI尚无当前有效结果。
        try:  # STRING网络问题只记录本分支失败。
            result = run_ppi(workflow, study_id, manifest["current"]["A03"], manifest["current"].get("A04", ""), "复核通过后自动接续：生成A04 PPI", None)  # 联网和归档仍由生产入口执行。
            created.append(result["module_id"])  # 新A04等待用户复核。
        except Exception as error:  # 保留具体错误供页面提示，A05仍可继续。
            errors.append("A04未完成：" + str(error))  # 不把失败写成有效空结果。
    manifest = workflow.load(study_id)  # A04可能已形成新版本，重新读取避免旧状态。
    if _needs_run(workflow, manifest, "A05"):  # 富集与PPI互不依赖。
        try:  # R或来源问题只影响本分支。
            result = run_enrichment(workflow, study_id, manifest["current"]["A03"], manifest["current"].get("A05", ""), "复核通过后自动接续：生成A05 GO与KEGG富集")  # 使用固定来源和参数。
            created.append(result["module_id"])  # 新A05等待用户复核。
        except Exception as error:  # 页面显示实际失败原因。
            errors.append("A05未完成：" + str(error))  # 不阻止用户查看已完成的A04。
    if created or (errors and not _approved(workflow, workflow.load(study_id), 'A04')):  # 新结果需复核；富集单支失败不阻断已批准PPI后的对接。
        return {"created": created, "waiting": "请复核新生成的A04/A05；两个分支互不代替", "errors": errors}  # 不继续跨过新结果。
    manifest = workflow.load(study_id)  # 判断两个分支是否均已通过。
    if not _approved(workflow, manifest, "A04"):  # 任一分支仍待用户处理。
        return {"created": created, "waiting": "请完成并复核A04和A05；A03主候选也需单独确认", "errors": errors}  # 清楚列出并行关口。
    if not _approved(workflow, manifest, "A03_SELECT"):  # 分子对接对象不能由程序替用户选择。
        return {"created": created, "waiting": "请在A03主候选确认中选择对接成分；系统不会按排名自动代签", "errors": errors}  # 停在候选选择。
    if not _approved(workflow, manifest, "A06_PREP"):  # 新研究的结构、位点和配置必须复核。
        existing = manifest['current'].get('A06_PREP')  # 已生成准备只待用户复核，不重复采集。
        if existing and workflow.active(manifest, existing):  # 原准备结果继续使用原卡片。
            return {'created': created, 'waiting': '请复核A06对象与配置；通过并继续后自动对接或复用', 'errors': errors}  # 不代签。
        try:  # 固定规则可以自动形成只读筛查预览，但不能自动批准受体。
            screen = prepare_screen(workflow, study_id)  # 读取本次PPI顺序和七个已确认成分。
            if screen["created"]:  # 同一上游只登记一次新预览。
                created.append("A06受体筛查预览")  # 页面提示实际新增的人工关口。
        except Exception as error:  # 结构证据不足时保留前序结果并说明原因。
            errors.append("A06受体筛查未完成：" + str(error))  # 不把失败写成空受体集合。
        return {"created": created, "waiting": "请查看A06对接准备中的受体筛查表；成分已按本研究实际数量接入；在通用自动化入口确认结构方案后自动准备", "errors": errors}  # 不套用COPD受体或自动跳过高位候选。
    if not _approved(workflow, manifest, "A06"):  # 准备通过后通用后台按冻结输入运行。
        prep = workflow.run(manifest, manifest['current']['A06_PREP'])  # 识别新通用准备而不迁移历史。
        if _needs_run(workflow, manifest, 'A06') and prep['config'].get('schema_version') == 'A06.automation.preparation.1':  # 同一准备只启动一次。
            task = start_job(workflow, study_id, 'execute')  # 网页立即返回，计算在后台进行。
            return {'created': created, 'waiting': '对接或复用后台任务' + ('已完成，请查看A06结果并复核' if task['state'] == 'completed' else '已启动，请查看自动化进度'), 'errors': errors}  # 不自动批准评分。
        return {"created": created, "waiting": "请完成A06自动对接或任务包回传，并复核对接结果", "errors": errors}  # 不自动伪造评分。
    if not _approved(workflow, manifest, 'A05'):  # 富集不阻断分子对接，但双报告需要完整上游。
        return {'created': created, 'waiting': 'A06已通过，请完成A05复核后生成完整双报告', 'errors': errors}  # 不发布部分正式报告。
    if _needs_run(workflow, manifest, "A07"):  # 所有报告上游均已通过时可以自动汇总。
        selected = current_plan(workflow, study_id)  # 已确认通用方案包含任务编号与PyMOL位置。
        if selected is not None:  # 新模板先生成同源任务包，再出报告。
            task = start_job(workflow, study_id, 'deliver')  # 长导出也在后台运行。
            return {'created': created, 'waiting': '任务包与双报告后台任务' + ('已完成，请复核A07结论' if task['state'] == 'completed' else '已启动，请查看自动化进度'), 'errors': errors}  # 结论不代签。
        result = run_reports(workflow, study_id, manifest["current"].get("A07", ""), "复核通过后自动接续：生成A07双报告")  # 新建不可覆盖报告修订。
        created.append(result["module_id"])  # 结论仍需最后人工复核。
        return {"created": created, "waiting": "A07双报告已生成，请核对共同结论、研究线索和限制", "errors": errors}  # 停在结论关口。
    if not _approved(workflow, manifest, "A07"):  # 已生成但尚未确认。
        return {"created": created, "waiting": "请复核A07双报告结论", "errors": errors}  # 不自动代签结论。
    return {"created": created, "waiting": "A00至A07当前版本均已通过，本研究流程完成", "errors": errors}  # 给出明确终态。


def message(result):  # 将自动接续结果转换为网页短提示。
    parts = []  # 按实际执行内容组合提示。
    if result["created"]:  # 只列出真实新建模块。
        parts.append("已自动生成：" + "、".join(result["created"]))  # 用户知道发生了什么。
    parts.append(result["waiting"])  # 每次都说明下一步人工任务。
    if result["errors"]:  # 分支错误单独显示。
        parts.append("；".join(result["errors"]))  # 不隐藏失败原因。
    return "。".join(part for part in parts if part)  # 返回适合页面提示的完整句子。
