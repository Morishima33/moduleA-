# 本文件在临时研究目录启动服务，调用真实浏览器验收网页。
from pathlib import Path  # 定位项目和测试脚本。
import json  # 传递浏览器测试配置。
import os  # 读取明确的工具环境设置。
import subprocess  # 调用已有 Node 与 Playwright。
import sys  # 引入本项目模块。
import tempfile  # 确保测试研究不进入正式目录。
import threading  # 为浏览器提供短时 HTTP 服务。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 仅引用新项目代码。
from web import create_server  # 使用与实际入口相同的网页实现。
from test_components import fixture  # 用虚构小型来源验证A01网页，避免写入真实研究。
project = Path(__file__).resolve().parents[1]  # 新根目录从文件位置推导。
def verified_mesh(term, descriptor_id):  # 浏览器验收不依赖外网可用性。
    return {"status": "verified", "mesh_id": descriptor_id, "preferred_term": term, "mesh_year": "2026", "checked_at": "2026-09-28T00:00:00+00:00", "provider": "U.S. National Library of Medicine", "api_version": "browser_test", "descriptor_resource": "http://id.nlm.nih.gov/mesh/2026/" + descriptor_id, "entry_terms": [term], "evidence": {"years_sha256": "a", "descriptor_sha256": "b", "details_sha256": "c"}}  # 保持与生产证据相同的字段契约。
with tempfile.TemporaryDirectory(prefix="moduleA_browser_") as temporary:  # 测试完成后自动清理虚构研究。
    fixture(Path(temporary))  # 在临时项目准备独立的A01来源。
    server = create_server(Path(temporary), 0, mesh_verifier=verified_mesh)  # 不占用实际工作台固定端口或外网。
    worker = threading.Thread(target=server.serve_forever, daemon=True)  # 在独立线程响应浏览器。
    worker.start()  # 开始接受本机请求。
    try:  # 测试失败时也关闭服务。
        settings = {"url": "http://127.0.0.1:" + str(server.server_port), "home": str(project / "tests" / "web_home.png"), "review": str(project / "tests" / "web_review.png"), "a01": str(project / "tests" / "web_a01.png"), "a02": str(project / "tests" / "web_a02.png")}  # 截图是测试产物，不放入研究结果。
        result = subprocess.run([os.environ.get("MODULEA_NODE", "node"), str(project / "tests" / "test_web.mjs")], input=json.dumps(settings), text=True, encoding="utf-8", capture_output=True, timeout=90)  # 工具路径由环境提供，不绑定个人目录。
        print(result.stdout)  # 输出真实验收结果。
        if result.returncode:  # 失败时返回具体测试错误。
            print(result.stderr, file=sys.stderr)  # 便于定位浏览器或页面问题。
            raise SystemExit(result.returncode)  # 不把失败写成通过。
    finally:  # 收尾只处理本测试建立的资源。
        server.shutdown()  # 停止测试 HTTP 循环。
        server.server_close()  # 释放临时端口。
        worker.join(timeout=3)  # 等待服务线程退出。
