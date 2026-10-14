"""后台生成A05排名首位通路图；工具位置取运行配置。"""

import json
import os
from pathlib import Path
from contracts import require
from ..core.kernel import full_workflow


def run_ranked_maps(settings, task, manager):
    from science_modules.a05.ranked_pathway_maps import generate_ranked_maps

    payload = json.loads(task["payload"])
    config = settings.runtime_dir / "pathway_runtime.json"
    executable = os.environ.get("MODULEA_RSCRIPT")
    if not executable and config.is_file():
        executable = json.loads(config.read_text(encoding="utf-8"))["rscript_executable"]
    require(executable, "未配置通路图Rscript，请核对运行配置")

    def progress(done, total, text):
        manager.update(task["task_id"], progress={"step_zh": text, "done": done, "total": total})

    result = generate_ranked_maps(
        full_workflow(settings.data_root),
        task["study_id"],
        payload["expected_a05"],
        Path(executable),
        progress,
    )
    return f"已保存{len(result['items'])}张排名首位命中通路图，可在A05页面下载。"
