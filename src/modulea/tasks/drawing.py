"""后台验证用户图片、制作同源PyMOL包和汇集选中包；不调用对接计算。"""

from hashlib import sha256
import io
import json
import os
from pathlib import Path
import warnings
from contracts import require
from ..core.kernel import full_workflow


def validate_image(data):
    """完整解码PNG/JPEG，拒绝假扩展名、截断及过大像素图。"""
    from PIL import Image, UnidentifiedImageError

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                require(image.format in ("PNG", "JPEG"), "仅支持真实PNG/JPEG图片")
                width, height = image.size
                require(0 < width * height <= 40_000_000, "图片像素数须不超过4000万")
                info = {"format": image.format, "width": width, "height": height}
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
        return info
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ValueError("图片无法完整解码，请重新导出PNG/JPEG后上传") from error


def run_figure(settings, task, manager):
    """校验私有暂存字节后经Workflow另存附件版本。"""
    payload = json.loads(task["payload"])
    queue = (settings.runtime_dir / "upload_queue").resolve()
    path = (queue / payload["blob_name"]).resolve()
    require(path.is_relative_to(queue), "图片暂存路径无效")
    data = path.read_bytes()
    require(sha256(data).hexdigest() == payload["blob_sha256"], "图片暂存校验失败")
    info = validate_image(data)
    suffix = Path(payload["name"]).suffix.lower()
    require(
        (info["format"] == "PNG" and suffix == ".png")
        or (info["format"] == "JPEG" and suffix in (".jpg", ".jpeg")),
        "文件名与真实图片格式不一致",
    )
    result = full_workflow(settings.data_root).save_docking_figure(
        task["study_id"], payload, data, info
    )
    manager.update(
        task["task_id"], progress={"step_zh": "图片已保存，可预览和下载", "done": 1, "total": 1}
    )
    return "图片已绑定当前A06并另存：" + result["artifact_id"]


def pymol_program(settings):
    """工具位置读取本机环境或运行配置，源码不固定个人路径。"""
    config = settings.runtime_dir / "drawing_runtime.json"
    value = os.environ.get("MODULEA_PYMOL_EXE")
    if not value and config.is_file():
        value = json.loads(config.read_text(encoding="utf-8"))["pymol_executable"]
    require(value and Path(value).is_file(), "未配置PyMOL程序，请核对出图运行配置")
    return value


def run_packages(settings, task, manager):
    """逐组合制作和发布，失败重试保留同版本已完成内容。"""
    from science_modules.a06.drawing_packages import prepare_packages, build_selected_bundle

    payload = json.loads(task["payload"])
    require(
        payload.get("request_version") == "A06.drawing.on_demand.2",
        "旧批量整理请求已停用，请在A06页面重新选择组合并点击生成",
    )

    def progress(done, total):
        manager.update(
            task["task_id"],
            progress={"step_zh": "整理同源PDB与PyMOL会话", "done": done, "total": total},
        )

    workflow = full_workflow(settings.data_root)
    rows = prepare_packages(
        workflow,
        task["study_id"],
        payload,
        pymol_program(settings),
        progress,
    )
    build_selected_bundle(workflow, task["study_id"], payload)
    return f"所选{len(rows)}组出图包及下载合集已保存，可在A06页面下载。"


def run_bundle(settings, task, manager):
    """所选成品直接汇集下载，不为其他组合执行准备。"""
    from science_modules.a06.drawing_packages import build_selected_bundle

    item = build_selected_bundle(
        full_workflow(settings.data_root), task["study_id"], json.loads(task["payload"])
    )
    manager.update(
        task["task_id"], progress={"step_zh": "所选组合下载包已整理", "done": 1, "total": 1}
    )
    return item["name_zh"] + "已保存，请在A06页面下载。"
