# A00阶段只暂存并校验疾病来源文件；A00通过前不生成A02科学结果。
import hashlib  # 为原始上传生成内容指纹。
from pathlib import Path  # 将文件限定在当前研究包。
from contracts import fingerprint, require  # 使用统一契约和身份指纹。
from disease import metadata, parse_source  # 复用A02格式校验，不复制解析规则。
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock  # 使用现有归档体系。

PROFILE = "A00.preupload.2"  # 新版登记显式保存研究用途和四库同层上传规则。
COMPATIBLE_PROFILES = ("A00.preupload.1", PROFILE)  # 历史预上传研究继续读取原契约。
SOURCE_PROFILE = "A02.source_profile.3"  # 新流程测试支持缺GeneCards的可审计例外。
UPLOAD_DATABASES = ("GeneCards", "OMIM", "TTD", "PharmGKB")  # OTP始终自动获取，不提供预上传入口。
OFFICIAL_URLS = {"GeneCards": "https://www.genecards.org/", "OMIM": "https://www.omim.org/", "TTD": "https://ttd.idrblab.cn/", "PharmGKB": "https://api.clinpgx.org/v1"}  # 后台固定官方出处。

def identity(summary):  # 只绑定会改变研究对象或疾病检索范围的A00字段。
    mesh = summary.get("mesh_verification", {})  # 新流程必须已有NLM核对证据。
    value = {key: summary.get(key) for key in ("formula", "herbs", "disease", "disease_scope", "species", "analysis_purpose")}  # 用途变化会使旧暂存资料失效。
    value.update(mesh_term=mesh.get("preferred_term"), mesh_id=mesh.get("mesh_id"), mesh_year=mesh.get("mesh_year"))  # 绑定官方疾病身份。
    return fingerprint(value)  # 不在文件名中暴露研究内容。

def current(workflow, manifest):  # 读取当前A00对应的暂存清单。
    record = manifest.get("current_source_staging")  # 历史研究没有该字段。
    if not record:  # 尚未上传属于正常状态。
        return None  # 页面显示未提供。
    value = read_json(verified_file(workflow.location(manifest["study_id"]), record))  # 指纹不一致立即停止。
    return value  # 是否仍绑定当前A00由调用者明确判断。

def stage(workflow, study_id, expected_a00, source):  # 上传或替换一个A00暂存来源。
    require(source.get("database") in UPLOAD_DATABASES, "A00暂存区不支持这个数据库")  # DisGeNET和OTP不进入入口。
    with write_lock(workflow.root):  # 文件、清单和研究索引一次发布。
        manifest = workflow.load(study_id)  # 页面提交后重新读取当前状态。
        require(not manifest.get("trashed") and manifest.get("workflow_profile") in COMPATIBLE_PROFILES, "当前研究不使用A00资料预上传流程")  # 历史研究保持原样。
        require(manifest["current"].get("A00") == expected_a00 and workflow.active(manifest, expected_a00), "A00版本已改变，请刷新后重新上传")  # 不绑定过期登记。
        require(not workflow.approved(manifest, expected_a00), "A00已经通过；后续补充或替换资料请在A02卡片操作")  # 防止通过后暂存新文件却未进入已有A02。
        a00 = workflow.result(manifest, expected_a00)["summary"]  # 读取官方核对后的当前登记。
        item = dict(source, source_url=OFFICIAL_URLS[source["database"]], source_status="staged")  # 两个隐藏字段由后台生成。
        item = dict(metadata(item), data=source["data"])  # 收紧元信息并保留原始字节。
        parse_source(item, item["data"])  # 立即检查格式和必要字段，但不形成A02。
        previous = current(workflow, manifest)  # 同一A00可逐库补充或替换。
        datasets = {}  # 仅复用仍绑定当前A00身份的暂存来源。
        if previous and previous.get("a00_run_id") == expected_a00 and previous.get("identity_hash") == identity(a00):
            for old in previous.get("datasets", []):  # 原文件不复制、不覆盖。
                datasets[old["database"]] = old  # 当前清单只引用所选版本。
        token = new_id("stage")  # 本次上传获得独立目录和清单身份。
        suffix = ".csv" if item["format"] == "genecards_csv" else (".xlsx" if item["format"] == "omim_xlsx" else (".tsv" if item["format"] in ("omim", "tsv", "detailed_txt") else (".txt" if item["format"] == "names" else ".json")))  # 扩展名反映实际格式。
        path = workflow.location(study_id) / "raw" / "A00_staging" / token / (item["database"].lower() + suffix)  # 不采用用户文件名作为路径。
        path.parent.mkdir(parents=True, exist_ok=False)  # 每次上传独立留存。
        with path.open("xb") as stream:  # 原文件只写一次。
            stream.write(item["data"])  # 不修改用户字节。
        stored = {key: value for key, value in item.items() if key != "data"}  # 清单不重复塞入文件内容。
        stored.update(sha256=hashlib.sha256(item["data"]).hexdigest(), bytes=len(item["data"]), source_record=file_record(workflow.location(study_id), path, "staged_source"), staged_at=now(), staging_reason="替换当前暂存来源" if item["database"] in datasets else "本研究首次暂存")  # 自动记录首次或替换。
        datasets[item["database"]] = stored  # 新上传成为该库当前暂存版本。
        manifest_value = {"version": PROFILE, "staging_id": token, "study_id": study_id, "a00_run_id": expected_a00, "identity_hash": identity(a00), "datasets": [datasets[key] for key in UPLOAD_DATABASES if key in datasets], "created_at": now()}  # 顺序固定便于核对。
        manifest_path = workflow.location(study_id) / "raw" / "A00_staging" / token / "source_staging.json"  # 每个版本有独立清单。
        write_json(manifest_path, manifest_value)  # 旧清单不覆盖。
        record = file_record(workflow.location(study_id), manifest_path, "source_staging_manifest")  # 总索引只引用完整清单。
        manifest.setdefault("source_staging_versions", []).append(record)  # 全部历史可追溯。
        manifest["current_source_staging"] = record  # 当前指针最后更新。
        workflow.save(manifest)  # 原子发布研究索引。
        return manifest_value  # 网页显示当前状态。

def sources_for_a02(workflow, manifest):  # A00通过后取得仍有效的预上传来源。
    value = current(workflow, manifest)  # 当前清单可能不存在或属于旧A00。
    if not value:  # 缺文件不阻止A00或A01。
        return []  # A02稍后显示尚未提供。
    a00_id = manifest["current"]["A00"]  # 只允许当前登记。
    a00 = workflow.result(manifest, a00_id)["summary"]  # 重新计算科学身份指纹。
    if value.get("a00_run_id") != a00_id or value.get("identity_hash") != identity(a00):
        return []  # 旧暂存资料保留但绝不自动复用。
    result = []  # 将归档字节交给统一A02入口。
    for item in value.get("datasets", []):
        result.append({key: val for key, val in item.items() if key not in ("source_record", "sha256", "bytes", "staged_at", "staging_reason")} | {"data": verified_file(workflow.location(manifest["study_id"]), item["source_record"]).read_bytes()})  # 不改变来源元信息。
    return result  # A02会再次解析并独立归档来源引用。
