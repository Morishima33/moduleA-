# 使用临时合成研究启动A03真实浏览器验收。
from pathlib import Path  # 定位新项目。
import json  # 传入浏览器配置。
import os  # 读取已有测试工具位置。
import subprocess  # 启动Node浏览器脚本。
import sys  # 加载项目模块。
import tempfile  # 隔离测试研究。
import threading  # 运行短时本机服务。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 新项目源码。
from web import create_server  # 与实际工作台相同入口。
from test_intersection_flow import setup_study  # 仅准备contract_test合成上游。
project = Path(__file__).resolve().parents[1]  # 不固定个人工作区。
with tempfile.TemporaryDirectory(prefix="moduleA_a03_browser_") as temporary:  # 不写正式studies。
    flow, sid = setup_study(Path(temporary))  # 明确模拟已标准化的上游。
    server = create_server(Path(temporary), 0)  # 使用空闲测试端口。
    worker = threading.Thread(target=server.serve_forever, daemon=True)  # 浏览器请求由测试线程处理。
    worker.start()  # 启动临时服务。
    try:  # 验收失败也清理服务。
        settings = {"url": "http://127.0.0.1:" + str(server.server_port), "study": sid, "image": str(project / "tests/web_a03.png"), "selection": str(project / "tests/web_a03_select.png")}  # 截图留在已规定测试目录。
        result = subprocess.run([os.environ.get("MODULEA_NODE", "node"), str(project / "tests/test_web_a03.mjs")], input=json.dumps(settings), text=True, encoding="utf-8", capture_output=True, timeout=120)  # 测试工具不成为运行依赖。
        print(result.stdout)  # 返回实际验收信息。
        if result.returncode:  # 未通过不伪报完成。
            print(result.stderr, file=sys.stderr)  # 保留可诊断错误。
            raise SystemExit(result.returncode)  # 报告失败状态。
    finally:  # 仅关闭本测试资源。
        server.shutdown()  # 停止请求循环。
        server.server_close()  # 释放端口。
        worker.join(timeout=3)  # 回收工作线程。
