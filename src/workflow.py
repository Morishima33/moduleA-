# 本文件管理模块交接、版本、复核和失效规则，不包含药理计算。
from pathlib import Path  # 定位项目和研究包。
import csv  # 导出可复核的明细表。
import io  # 在内存中形成完整表格再保存。
import platform  # 记录本次 Python 与系统环境。
from contracts import MODULES, SCHEMA_VERSION, ContractError, check_intake, check_module, check_result, fingerprint, require, safe_id  # 使用统一契约。
from storage import file_record, new_id, now, read_json, verified_file, within, write_json, write_lock  # 使用统一留存规则。

class Workflow:  # 对网页和未来各分析模块提供同一入口。
    def __init__(self, root, validators=None):  # root 是项目根目录，不是某次运行目录。
        self.root = Path(root).resolve()  # 全部研究资料相对这个根目录组织。
        self.validators = validators or {}  # 只有接入专用校验的模块才可以处理正式研究。
        self.environment = {"python": platform.python_version(), "system": platform.platform()}  # 记录可复核的环境说明。
        sources = sorted((Path(__file__).parent).glob("*.py"))  # 包含当前实现的全部 Python 文件。
        self.code_version = fingerprint({p.name: fingerprint(p.read_text(encoding="utf-8")) for p in sources})  # 用代码内容定位本次实现。

    def location(self, study_id):  # 定位且核验研究编号。
        safe_id(study_id, "study")  # 不允许任意目录作为研究编号。
        return within(self.root / "studies", study_id)  # 所有研究归入 studies。

    def load(self, study_id):  # 读取研究总索引，不凭目录存在推断完成。
        manifest = read_json(self.location(study_id) / "manifest.json")  # 索引是唯一当前版本指针。
        require(manifest.get("schema_version") == SCHEMA_VERSION and manifest.get("study_id") == study_id, "研究索引版本或身份不匹配")  # 不静默升级不兼容资料。
        return manifest  # 返回带版本的索引。

    def save(self, manifest):  # 更新当前版本指针，历史文件不覆盖。
        manifest["updated_at"] = now()  # 记录索引最后一次变化。
        write_json(self.location(manifest["study_id"]) / "manifest.json", manifest, replace=True)  # 原子发布新索引。

    def studies(self, trashed=False):  # 列出用户已有研究，支持关闭后重新打开。
        folder = self.root / "studies"  # 不扫描旧项目或桌面。
        if not folder.exists():  # 尚未创建研究属于正常情况。
            return []  # 返回空清单。
        manifests = [self.load(p.name) for p in sorted(folder.iterdir()) if p.is_dir() and p.name.startswith("study_")]  # 损坏索引会明确报错。
        return [item for item in manifests if item.get("trashed", False) == trashed]  # 旧研究缺少标记时按正常研究读取。

    def create(self, intake, kind="research"):  # 建立独立研究包和待复核登记。
        check_intake(intake)  # 必填信息和人类范围必须完整。
        require(kind in ("research", "contract_test"), "未知研究类型")  # 测试资料有明确身份。
        with write_lock(self.root):  # 创建包与首条运行在同一写入锁内完成。
            study_id = new_id("study")  # 每次研究获得新的唯一编号。
            modern = kind == "research" and isinstance(intake.get("mesh_verification"), dict) and intake["mesh_verification"].get("status") == "verified"  # 有正式疾病身份的新研究启用新版预上传流程。
            manifest = {"schema_version": SCHEMA_VERSION, "study_id": study_id, "kind": kind, "workflow_profile": "A00.preupload.2" if modern else "legacy", "created_at": now(), "current": {}, "runs": {}, "reviews": []}  # 研究用途由A00字段决定，不由MeSH存在性推断。
            for name in ("intake", "raw", "normalized", "runs", "reviews", "reports"):  # 按大纲创建研究内部目录。
                (self.location(study_id) / name).mkdir(parents=True, exist_ok=False)  # 不合并到同名既有研究。
            run = self._begin(manifest, "A00", intake, {}, "首次登记")  # 固定本次用户输入。
            write_json(self.location(study_id) / "intake" / (run["run_id"] + ".json"), intake)  # 保存原始登记快照。
            self._finish(manifest, run["run_id"], intake, {}, [], "success")  # 完成登记处理但不替代人工复核。
            self.save(manifest)  # 登记准备好后才发布研究索引。
            return study_id  # 网页据此打开新研究。

    def run(self, manifest, run_id):  # 读取明确指定的运行，不猜“最新文件”。
        cache = getattr(self, "_view_cache", None)  # 研究页面一次请求内允许复用已核验运行。
        if cache is not None and run_id in cache["runs"]:  # 同一页面重复读取不再次计算文件指纹。
            return cache["runs"][run_id]  # 缓存仅在本次view调用期间存在。
        safe_id(run_id, "run")  # 校验编号类型。
        require(run_id in manifest["runs"], "运行不属于当前研究")  # 拒绝跨研究接入。
        record = manifest["runs"][run_id]  # 取得该运行的文件指纹。
        path = verified_file(self.location(manifest["study_id"]), record["run_file"])  # 校验输入配置快照。
        run = read_json(path)  # 读取不可覆盖的开始记录。
        require(run["study_id"] == manifest["study_id"] and run["run_id"] == run_id, "运行身份不一致")  # 二次确认归属。
        if cache is not None:  # 仅记录本次页面已核验的数据。
            cache["runs"][run_id] = run  # 不跨请求或写操作复用。
        return run  # 返回该次固定输入。

    def result(self, manifest, run_id):  # 获取结果并核验全部关联文件。
        cache = getattr(self, "_view_cache", None)  # 同一页面可能多次检查同一结果及附件。
        if cache is not None and run_id in cache["results"]:  # 已完成全链核验时直接复用内存对象。
            return cache["results"][run_id]  # 不降低首次读取的指纹检查。
        record = manifest["runs"][run_id]  # 不访问其他研究的索引。
        if not record.get("result_file"):  # 尚未形成完整结果。
            return None  # 不能解释成成功空集合。
        root = self.location(manifest["study_id"])  # 限定读取范围。
        result = read_json(verified_file(root, record["result_file"]))  # 验证结果摘要。
        run = self.run(manifest, run_id)  # 核验与结果关联的输入快照。
        require(result["artifact_id"] == run["artifact_id"] and result["run_id"] == run_id and result["study_id"] == manifest["study_id"], "产物身份不一致")  # 防止结果错配。
        for item in result["files"]:  # 所有表、日志和异常文件均参与校验。
            verified_file(root, item)  # 缺失或改变都必须暂停使用。
        if cache is not None:  # 仅缓存已经完整验证的标准结果。
            cache["results"][run_id] = result  # 下一次网页请求仍会重新核验磁盘。
        return result  # 返回已验证的标准结果。

    def latest_review(self, manifest, artifact_id):  # 当前决定来自明确的历史记录顺序。
        cache = getattr(self, "_view_cache", None)  # 同一产物在状态和依赖检查中会重复查询复核。
        if cache is not None and artifact_id in cache["reviews"]:  # 已查得的结果包括明确的无复核状态。
            return cache["reviews"][artifact_id]  # 避免重复读取全部复核文件。
        for item in reversed(manifest["reviews"]):  # 按保存顺序查最近决定，不比较文件时间。
            review = read_json(verified_file(self.location(manifest["study_id"]), item))  # 复核记录也必须完整。
            if review["artifact_id"] == artifact_id:  # 仅取属于该产物的决定。
                if cache is not None:  # 当前页面保存查找结果。
                    cache["reviews"][artifact_id] = review  # 不跨请求使用旧复核状态。
                return review  # 旧决定仍保留在 reviews 中。
        if cache is not None:  # 没有复核同样是可缓存的本次事实。
            cache["reviews"][artifact_id] = None  # 防止每个依赖再次遍历历史。
        return None  # 尚无人工决定。

    def active(self, manifest, run_id):  # 为一次页面请求缓存版本有效性判断。
        cache = getattr(self, "_view_cache", None)  # 缓存作用域由view创建和清理。
        if cache is not None and run_id in cache["active"]:  # 已完成相同版本判断时直接复用。
            return cache["active"][run_id]  # 不在不同请求之间保留状态。
        value = self._active(manifest, run_id)  # 首次仍执行完整依赖和复核检查。
        if cache is not None:  # 只保存本次视图所需结果。
            cache["active"][run_id] = value  # 上游状态不会在同一个同步请求中改变。
        return value  # 返回真实有效性。

    def _active(self, manifest, run_id):  # 执行未缓存的版本有效性检查。
        run = self.run(manifest, run_id)  # 读取不可变运行快照。
        if manifest["current"].get(run["module_id"]) != run_id:  # 同模块已有新运行时旧运行自动失效。
            return False  # 历史产物仍保留但不供下游使用。
        for module, parent_id in run["parent_runs"].items():  # 逐一检查实际依赖。
            if manifest["current"].get(module) != parent_id or not self.approved(manifest, parent_id):  # 父产物改变或批准撤回。
                return False  # 仅沿依赖关系失效。
            parent = self.run(manifest, parent_id)  # 取得被依赖产物的准确身份。
            review = self.latest_review(manifest, parent["artifact_id"])  # 读取目前生效的上游决定。
            if not review or review["review_id"] != run["parent_review_ids"].get(module):  # 批准撤回后重批不能恢复旧下游批准。
                return False  # 必须重新建立并复核下游版本。
        return True  # 本次运行仍对应当前已批准输入。

    def approved(self, manifest, run_id):  # 为一次页面请求缓存可用性判断。
        cache = getattr(self, "_view_cache", None)  # 缓存不跨越复核或文件修改操作。
        if cache is not None and run_id in cache["approved"]:  # 同一上游常被多个下游重复查询。
            return cache["approved"][run_id]  # 直接返回已完整验证的本次结果。
        value = self._approved(manifest, run_id)  # 首次执行全部文件、依赖和复核检查。
        if cache is not None:  # 保存到当前view作用域。
            cache["approved"][run_id] = value  # 下一次网页请求会重新检查。
        return value  # 返回是否允许下游使用。

    def _approved(self, manifest, run_id):  # 执行未缓存的批准状态检查。
        if manifest.get("trashed", False):  # 暂停回收站研究供下游使用，不删除原批准。
            return False  # 恢复后重新按原文件和版本核验。
        if not self.active(manifest, run_id):  # 先检查版本及上游有效性。
            return False  # 旧批准不能跨版本继续使用。
        result = self.result(manifest, run_id)  # 检查结果和明细文件。
        if not result or result["outcome"] == "failed":  # 未完成或失败不能批准。
            return False  # 失败不作为缓存命中。
        if result["summary"].get("handoff_blocked", False):  # 候选收集阶段不能用普通通过绕过尚未核定的科学规则。
            return False  # A02候选不能解锁A03。
        review = self.latest_review(manifest, result["artifact_id"])  # 找到该产物的最近人工决定。
        return bool(review and review["decision"] == "approved")  # 只有明确通过才开放下游。

    def _begin(self, manifest, module, inputs, config, reason):  # 写入新运行，调用者负责锁和提交索引。
        require(not manifest.get("trashed", False), "研究在回收站中，请先恢复")  # 禁止向回收站研究启动新任务。
        check_module(module)  # 校验模块编号。
        require(isinstance(inputs, dict) and isinstance(config, dict), "输入和配置必须是对象")  # 统一模块接口。
        require(isinstance(reason, str) and reason.strip(), "必须记录创建或修订原因")  # 禁止无理由替换上游。
        require(module == "A00" or module in self.validators or manifest["kind"] == "contract_test", "该科学模块尚未接入，不生成占位研究结果")  # 框架不能伪装成科研模块。
        parents = {}  # 固定本次真正使用的上游运行。
        artifacts = []  # 保存可追溯的上游产物身份。
        parent_reviews = {}  # 同时固定本次依赖的上游批准记录，撤回后不自动复活旧下游。
        for dependency in MODULES[module][1]:  # 遍历大纲规定的依赖。
            parent_id = manifest["current"].get(dependency)  # 当前指针只用于选定具体版本。
            require(parent_id and self.approved(manifest, parent_id), "上游尚未复核通过：" + dependency)  # 未满足时只阻止当前步骤。
            parents[dependency] = parent_id  # 运行开始后不自动切换。
            parent_reviews[dependency] = self.latest_review(manifest, self.run(manifest, parent_id)["artifact_id"])["review_id"]  # 保存当时生效的批准身份。
            artifacts.append(self.run(manifest, parent_id)["artifact_id"])  # 保存准确产物关系。
        run_id = new_id("run")  # 每次运行均有独立编号。
        run = {"schema_version": SCHEMA_VERSION, "study_id": manifest["study_id"], "run_id": run_id, "module_id": module, "artifact_id": new_id("artifact"), "parent_runs": parents, "parent_review_ids": parent_reviews, "parent_artifact_ids": artifacts, "inputs": inputs, "config": config, "input_hash": fingerprint({"inputs": inputs, "parents": artifacts}), "config_hash": fingerprint(config), "code_version": self.code_version, "environment_version": fingerprint(self.environment), "environment": self.environment, "created_at": now(), "reason": reason}  # 固定所有交接依据。
        folder = self.location(manifest["study_id"]) / "runs" / module / run_id  # 不使用跨研究 current 目录。
        write_json(folder / "run.json", run)  # 原始运行快照只写一次。
        manifest["runs"][run_id] = {"run_file": file_record(self.location(manifest["study_id"]), folder / "run.json", "run"), "result_file": None}  # 结果未完成时保持空指针。
        manifest["current"][module] = run_id  # 新运行成为该模块当前版本，下游按依赖即时判定失效。
        return run  # 给实际计算函数提供固定上下文。

    def begin(self, study_id, module, inputs, config, reason):  # 未来分析模块的统一启动接口。
        with write_lock(self.root):  # 确保依赖检查与选定上游不会交错。
            manifest = self.load(study_id)  # 每次操作重读磁盘状态。
            run = self._begin(manifest, module, inputs, config, reason)  # 不让模块自行寻找文件。
            self.save(manifest)  # 记录运行中状态。
            return run  # 计算应使用这个对象里的固定版本。

    def _finish(self, manifest, run_id, summary, tables, anomalies, outcome, sources=None, figures=None, attachments=None):  # 发布完整结果，调用者负责写入锁。
        require(not manifest.get("trashed", False), "研究在回收站中，请先恢复")  # 回收站不接受新的运行结果。
        check_result(summary, tables, anomalies, outcome)  # 验证标准结果形状。
        run = self.run(manifest, run_id)  # 确认运行属于本研究。
        require(not manifest["runs"][run_id]["result_file"], "该运行已经结束，修订必须建立新运行")  # 不覆盖历史结果。
        require(self.active(manifest, run_id), "上游已改变，本次结果不得发布；请重新运行")  # 防止慢计算回写过期结果。
        if outcome != "failed" and run["module_id"] in self.validators:  # 正式科学模块必须另做领域校验。
            self.validators[run["module_id"]](run, summary, tables, anomalies, outcome)  # 由模块专用校验把关身份、字段与数量。
        root = self.location(manifest["study_id"])  # 本研究包根目录。
        folder = root / "runs" / run["module_id"] / run_id  # 所有输出归入同次运行。
        sources, figures, attachments = sources or [], figures or [], attachments or []  # 实际来源、图形和大型文件均通过索引关联。
        if run["module_id"] == "A00":  # 登记也要能回查原始输入快照。
            sources = [file_record(root, root / "intake" / (run_id + ".json"), "intake")]  # 将原始登记纳入校验链。
        files = list(sources) + list(figures) + list(attachments)  # 大型文件不塞入摘要，仅保存路径和指纹。
        for record in files:  # 提交前检查所有外部生成的关联文件。
            verified_file(root, record)  # 必须已经落在当前研究包并通过完整性校验。
        for name, rows in tables.items():  # 将普通明细保存为CSV，嵌套事实包保存为JSON。
            if isinstance(rows, dict):  # A06动态契约包含嵌套对象，不能错误压平成CSV。
                path = folder / (name + ".json")  # 使用同名JSON保存完整结构。
                write_json(path, rows)  # 统一不可覆盖写入。
                files.append(file_record(root, path, "structured_table"))  # 将指纹纳入结果。
                continue  # 其他普通表仍按CSV处理。
            columns = sorted({key for row in rows for key in row})  # 字段顺序稳定，不按文件修改时间变化。
            buffer = io.StringIO(newline="")  # 避免 Windows 多余空行。
            writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")  # 固定 CSV 格式。
            writer.writeheader()  # 输出表头。
            writer.writerows(rows)  # 输出全部明细，不只保存展示条数。
            path = folder / (name + ".csv")  # 内部表名已通过路径校验。
            with path.open("x", encoding="utf-8-sig", newline="") as stream:  # 中文表格便于本机查看，不覆盖已存在文件。
                stream.write(buffer.getvalue())  # 一次写入该表完整内容。
            files.append(file_record(root, path, "table"))  # 将表的指纹纳入结果。
        for name, value, role in (("anomalies.json", anomalies, "anomalies"), ("execution.json", {"started_at": run["created_at"], "finished_at": now(), "outcome": outcome}, "execution")):  # 错误与执行情况分别留存。
            write_json(folder / name, value)  # 独立文件只写一次。
            files.append(file_record(root, folder / name, role))  # 文件均可从标准结果回查。
        result = {key: run[key] for key in ("schema_version", "study_id", "run_id", "module_id", "artifact_id", "parent_artifact_ids", "input_hash", "config_hash", "code_version", "environment_version")}  # 保留必要共用元信息。
        result.update({"outcome": outcome, "summary": summary, "tables": tables, "anomalies": anomalies, "files": files, "figures": figures, "sources": sources, "created_at": now(), "kind": manifest["kind"]})  # 来源与图形必须是实际归档文件，不能伪造占位图。
        write_json(folder / "result.json", result)  # 最后形成标准摘要。
        manifest["runs"][run_id]["result_file"] = file_record(root, folder / "result.json", "result")  # 完整结果才挂到索引。
        return result  # 仍须人工复核，不自动认定批准。

    def finish(self, study_id, run_id, summary, tables=None, anomalies=None, outcome="success", sources=None, figures=None, attachments=None):  # 分析模块统一提交结果的入口。
        with write_lock(self.root):  # 防止并发提交同次运行。
            manifest = self.load(study_id)  # 重读当前批准状态。
            result = self._finish(manifest, run_id, summary, tables or {}, anomalies or [], outcome, sources, figures, attachments)  # 验证来源、明细及关联文件并归档。
            self.save(manifest)  # 发布待复核结果。
            return result  # 供网页读取。

    def revise_intake(self, study_id, intake, reason, expected_run):  # 修改登记时创建新版本而不覆盖原件。
        check_intake(intake)  # 修改后的数据仍须完整。
        with write_lock(self.root):  # 避免用户在旧页面上覆盖别人刚保存的登记。
            manifest = self.load(study_id)  # 读取实际版本。
            require(manifest["current"]["A00"] == expected_run, "登记已更新，请刷新后重试")  # 旧页面提交不生效。
            run = self._begin(manifest, "A00", intake, {}, reason)  # 记录修订理由和新运行。
            write_json(self.location(study_id) / "intake" / (run["run_id"] + ".json"), intake)  # 保存新原始登记。
            self._finish(manifest, run["run_id"], intake, {}, [], "success")  # 新登记重新等待复核。
            self.save(manifest)  # 下游有效性随新版本自动变化。
            return run["run_id"]  # 供界面定位。

    def review(self, study_id, run_id, decision, reviewer, note, expected_review=None):  # 复核动作只改变审核记录，不改结果。
        require(decision in ("approved", "rejected", "pending"), "未知复核决定")  # 对应通过、退回、暂存。
        require(isinstance(reviewer, str) and reviewer.strip() and isinstance(note, str) and note.strip(), "请填写复核人和意见")  # 每次决定必须可追溯。
        with write_lock(self.root):  # 校验及保存同一版本。
            manifest = self.load(study_id)  # 防止页面缓存状态被误用。
            require(not manifest.get("trashed", False), "研究在回收站中，请先恢复")  # 即使旧页面仍开着也禁止修改复核。
            require(self.active(manifest, run_id), "该版本已失效，不能继续复核")  # 历史结果不能重新解锁下游。
            result = self.result(manifest, run_id)  # 检查结果文件及明细指纹。
            require(result and result["outcome"] != "failed", "未完成或失败的运行不能复核通过")  # 有效空结果可正常复核。
            require(decision != "approved" or not result["summary"].get("handoff_blocked", False), "本产物仍为候选整理阶段，正式筛选规则未核定；可暂存意见，不能批准下游使用")  # 服务端独立阻止伪造表单绕过。
            if decision == "approved" and self.run(manifest, run_id)["module_id"] == "A07": # 完整报告批准需匹配当前通路选择。
                from report_dispatch import require_alignment # 仅A07关口调用，避免模块初始化循环。
                require_alignment(self, manifest, self.run(manifest, run_id)) # 在同一写锁内拒绝已改变的图与解释。
            previous = self.latest_review(manifest, result["artifact_id"])  # 找到页面应针对的上次决定。
            require((previous["review_id"] if previous else None) == expected_review, "复核状态已更新，请刷新后再提交")  # 阻止旧页面覆盖较新决定。
            review = {"schema_version": SCHEMA_VERSION, "study_id": study_id, "run_id": run_id, "artifact_id": result["artifact_id"], "config_hash": result["config_hash"], "result_hash": manifest["runs"][run_id]["result_file"]["sha256"], "review_id": new_id("review"), "decision": decision, "reviewer": reviewer.strip(), "note": note.strip(), "previous_review_id": expected_review, "created_at": now()}  # 绑定真实审核对象与配置。
            path = self.location(study_id) / "reviews" / (review["review_id"] + ".json")  # 每次决定独立留存。
            write_json(path, review)  # 不修改旧复核意见。
            manifest["reviews"].append(file_record(self.location(study_id), path, "review"))  # 明确保存先后顺序。
            self.save(manifest)  # 复核变更后下游状态实时重新计算。
            return review  # 网页可显示保存成功的记录。

    def review_a01_a02(self, study_id, entries, reviewer):  # 一次保存两个模块的独立复核决定。
        require(isinstance(reviewer, str) and reviewer.strip(), "请填写复核人")  # 复核人由两项共用。
        require(isinstance(entries, dict) and set(entries) == {"A01", "A02"}, "须同时提交A01和A02当前状态")  # 不接受缺项或其他模块。
        with write_lock(self.root):  # 两项先全部校验，再共同发布。
            manifest = self.load(study_id)  # 防止旧页面覆盖新运行。
            require(not manifest.get("trashed", False), "研究在回收站中，请先恢复")  # 回收站保持只读。
            require(manifest.get("workflow_profile") in ("A00.preupload.1", "A00.preupload.2"), "当前研究不使用A01/A02一次复核流程")  # 两版预上传研究使用一次复核流程。
            prepared, paths = [], []  # 只有发生变化的模块创建新复核记录。
            for module in ("A01", "A02"):  # 固定顺序使历史可读。
                entry = entries[module]  # 页面传回该模块的当前版本和决定。
                run_id = entry.get("run_id", "")  # 每项绑定明确运行。
                require(manifest["current"].get(module) == run_id and self.active(manifest, run_id), module + "版本已改变，请刷新后重新提交")  # 两项任一过期则全批拒绝。
                result = self.result(manifest, run_id)  # 核验结果和全部关联文件。
                require(result and result["outcome"] != "failed", module + "尚未形成可复核结果")  # 失败运行不能伪装成复核对象。
                previous = self.latest_review(manifest, result["artifact_id"])  # 取得页面应针对的最近决定。
                expected = entry.get("expected_review") or None  # HTML空值等同尚无复核。
                require((previous["review_id"] if previous else None) == expected, module + "复核状态已更新，请刷新后重新提交")  # 两项均做版本冲突检查。
                if entry.get("action") == "preserve":  # 已通过模块不重复生成相同记录。
                    require(previous is not None, module + "没有可保留的复核决定")  # 未审核模块不能跳过。
                    continue  # 保留原复核身份及历史。
                decision, note = entry.get("decision", ""), entry.get("note", "")  # 两项意见保持独立。
                require(decision in ("approved", "rejected", "pending") and isinstance(note, str) and note.strip(), module + "须选择决定并填写意见")  # 每项都有完整依据。
                require(decision != "approved" or not result["summary"].get("handoff_blocked", False), module + "仍有资料、范围或身份问题，不能批准下游使用")  # 服务端不依赖网页隐藏选项。
                review = {"schema_version": SCHEMA_VERSION, "study_id": study_id, "run_id": run_id, "artifact_id": result["artifact_id"], "config_hash": result["config_hash"], "result_hash": manifest["runs"][run_id]["result_file"]["sha256"], "review_id": new_id("review"), "decision": decision, "reviewer": reviewer.strip(), "note": note.strip(), "previous_review_id": expected, "batch": "A01_A02", "created_at": now()}  # 两条记录仍可分别追溯。
                prepared.append(review)  # 全部校验完成后才写盘。
            require(bool(prepared), "A01和A02决定均未变化，无需重复保存")  # 防止空批次制造操作假象。
            try:  # 任一文件或索引写入失败时不留下半批次引用。
                for review in prepared:  # 两条独立文件保留各自身份。
                    path = self.location(study_id) / "reviews" / (review["review_id"] + ".json")  # 路径由安全编号组成。
                    write_json(path, review)  # 不覆盖历史复核。
                    paths.append(path)  # 失败时只清理本批新文件。
                manifest["reviews"].extend(file_record(self.location(study_id), path, "review") for path in paths)  # 两条都写完才加入索引。
                self.save(manifest)  # 原子发布新的复核历史。
            except Exception:  # 索引未发布时清理本批孤立文件。
                for path in paths:  # 路径均在本研究reviews目录且由本次生成。
                    path.unlink(missing_ok=True)  # 不碰任何旧复核记录。
                raise  # 保留真实错误给网页。
            return prepared  # 调用方据此判断是否继续A03。

    def view(self, study_id):  # 网页与命令行共用的研究状态视图。
        previous_cache = getattr(self, "_view_cache", None)  # 保留可能存在的外层只读作用域。
        self._view_cache = {"runs": {}, "results": {}, "reviews": {}, "active": {}, "approved": {}}  # 本次请求内相同文件只完整核验一次。
        try:  # 异常时也必须清除缓存，避免后续请求使用旧状态。
            return self._view_snapshot(study_id)  # 生成完整状态视图。
        finally:  # 无论页面成功还是失败均恢复原作用域。
            self._view_cache = previous_cache  # 下一次独立请求重新读取磁盘和指纹。

    def _view_snapshot(self, study_id):  # 在本次只读缓存作用域内生成研究状态。
        manifest = self.load(study_id)  # 状态始终来自磁盘。
        modules = []  # 按固定模块顺序组织展示。
        for module, (title, dependencies) in MODULES.items():  # 对全部步骤逐一计算状态。
            run_id = manifest["current"].get(module)  # 查找明确的当前版本。
            state, result, review, run = "waiting", None, None, None  # 没有运行时不能显示成功。
            available = all(manifest["current"].get(p) and self.approved(manifest, manifest["current"][p]) for p in dependencies)  # 判断上游是否齐备。
            if run_id:  # 已启动的模块展示实际运行记录。
                run = self.run(manifest, run_id)  # 核验并读取固定输入。
                result = self.result(manifest, run_id)  # 完整结果缺失则显示运行中。
                state = "stale" if not self.active(manifest, run_id) else "running"  # 上游变化优先显示失效。
                if state != "stale" and result:  # 有完整且有效的结果才能审核。
                    review = self.latest_review(manifest, result["artifact_id"])  # 显示最近决定。
                    state = "failed" if result["outcome"] == "failed" else (review["decision"] if review else "awaiting_review")  # 不把成功等同批准。
            elif available:  # 输入齐备但尚无运行。
                state = "ready" if module == "A00" or module in self.validators or manifest["kind"] == "contract_test" else "not_connected"  # 明确标记尚未接入科学模块。
            modules.append({"module_id": module, "title": title, "state": state, "run": run, "result": result, "review": review, "available": available})  # 所有展示共用同一状态来源。
        return {"manifest": manifest, "modules": modules}  # 前端不自行推算科研完成情况。

    def reusable(self, study_id, module, inputs, config):  # 判断当前结果是否可复用，不自动跨研究寻找缓存。
        check_module(module)  # 只查询登记过的模块。
        manifest = self.load(study_id)  # 读取当前版本与批准记录。
        run_id = manifest["current"].get(module)  # 当前指针绑定具体运行。
        if not run_id or not self.approved(manifest, run_id):  # 未批准、失败或失效结果不能复用。
            return None  # 调用者需要重新运行或补齐审核。
        run = self.run(manifest, run_id)  # 已批准检查包含输出文件校验。
        expected = fingerprint({"inputs": inputs, "parents": run["parent_artifact_ids"]})  # 同时检查本次输入和上游版本。
        same = run["input_hash"] == expected and run["config_hash"] == fingerprint(config) and run["code_version"] == self.code_version and run["environment_version"] == fingerprint(self.environment)  # 不因文件存在就复用。
        return self.result(manifest, run_id) if same else None  # 原样复用已审核标准结果。

    def set_trashed(self, study_id, trashed, operator, reason, expected_action=None):  # 仅改变研究是否显示在回收站，不删除目录。
        require(isinstance(trashed, bool), "回收站操作必须明确为移入或恢复")  # 不接受含糊的状态。
        require(isinstance(operator, str) and operator.strip() and isinstance(reason, str) and reason.strip(), "请填写管理人和操作原因")  # 每次管理动作必须留痕。
        with write_lock(self.root):  # 管理操作与其他写入不能交错。
            manifest = self.load(study_id)  # 读取最新研究状态。
            events = manifest.get("management_events", [])  # 兼容没有回收站字段的已有研究。
            previous = read_json(verified_file(self.location(study_id), events[-1])) if events else None  # 核验最近管理记录。
            require((previous["action_id"] if previous else None) == expected_action, "管理状态已改变，请刷新后重试")  # 旧页面不能覆盖新的移入或恢复决定。
            require(manifest.get("trashed", False) != trashed, "研究已经处于该状态")  # 重复点击不生成重复记录。
            if trashed:  # 未完成的任务不能被静默搁置。
                require(all(manifest["runs"][run_id]["result_file"] for run_id in manifest["current"].values()), "存在尚未完整提交的运行，请先处理后再移入回收站")  # 不在运行期间隐藏任务。
            action = {"action_id": new_id("action"), "study_id": study_id, "operator": operator.strip(), "reason": reason.strip(), "action": "trash" if trashed else "restore", "created_at": now(), "previous_action_id": expected_action}  # 管理记录与科学复核记录明确区分。
            path = self.location(study_id) / "reviews" / (action["action_id"] + ".json")  # 人工管理记录归入既定留痕目录，以action前缀区分。
            write_json(path, action)  # 不覆盖此前任何管理记录。
            manifest.setdefault("management_events", []).append(file_record(self.location(study_id), path, "management"))  # 使用独立索引，不混入模块复核历史。
            manifest["trashed"] = trashed  # 原研究包仍留在原位置，仅改变可见性和写入资格。
            self.save(manifest)  # 原子发布管理状态。
            return action  # 网页显示本次操作已保存。
