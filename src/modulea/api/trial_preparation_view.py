"""准备关联的只读接口投影，文件下载只使用研究内的归档索引。"""

from copy import deepcopy


def present_context(study_id, context):
    """给实际来源及准备文件附同源下载键，不重新计算准备状态。"""
    info = deepcopy(context)
    files = info.pop("files")
    urls = {
        (
            r["path"],
            r["sha256"],
        ): f"/api/v1/studies/{study_id}/files/{info['link_id']}.{i}"
        for i, r in enumerate(files)
    }

    def attach(value):
        if isinstance(value, dict):
            if {"path", "sha256", "bytes"} <= value.keys():
                value["url"] = urls.get((value["path"], value["sha256"]))
            else:
                for child in value.values():
                    attach(child)
        elif isinstance(value, list):
            for child in value:
                attach(child)

    attach(info)
    info["source_url"] = (
        f"/api/v1/studies/{study_id}/files/{info['link_id']}.{len(files) - 2}"
    )
    return info
