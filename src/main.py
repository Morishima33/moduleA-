# 本文件是项目统一启动入口，不依赖旧项目目录。
from pathlib import Path  # 从脚本位置定位当前项目。
import argparse  # 提供可选端口和浏览器开关。
import webbrowser  # 在用户正常启动时打开工作台。
from web import create_server  # 调用共用网页服务。

def main():  # 命令行与启动脚本调用同一个函数。
    parser = argparse.ArgumentParser(description="Module A 研究工作台")  # 说明当前能力。
    parser.add_argument("--port", type=int, default=8765)  # 默认使用本机固定端口。
    parser.add_argument("--no-browser", action="store_true")  # 检查或后台启动时可不打开浏览器。
    parser.add_argument("--check", action="store_true")  # 只检查环境与本机端口，检查后退出。
    args = parser.parse_args()  # 读取用户指定的启动选项。
    project = Path(__file__).resolve().parents[1]  # 根目录随项目移动，不写死用户名和盘符。
    server = create_server(project, args.port)  # 仅绑定本机回环地址。
    address = "http://127.0.0.1:" + str(server.server_port)  # 读取实际使用端口。
    print("Module A 研究工作台：" + address, flush=True)  # 清楚告诉用户如何访问。
    print("已接入A00—A07；当前玉屏风散—COPD案例为流程测试，正式研究仍须按MeSH重新检索疾病资料。关闭前请保存复核。", flush=True)  # 同步当前能力并保留正式研究边界。
    if args.check:  # 启动验收不留下后台服务。
        server.server_close()  # 确认端口可用后释放。
        print("启动检查通过。", flush=True)  # 提供可复核的启动检查结果。
        return  # 不进入长期服务循环。
    if not args.no_browser:  # 正常运行时主动打开工作台。
        webbrowser.open(address)  # 用户能直接进入网页。
    try:  # 服务运行直到用户停止。
        server.serve_forever()  # 响应页面和表单。
    except KeyboardInterrupt:  # 用户按 Ctrl+C 时正常退出。
        print("工作台已停止，已保存的研究资料仍在 studies 目录。", flush=True)  # 保存与网页生命周期分离。
    finally:  # 释放本机端口。
        server.server_close()  # 下次启动可以恢复已保存研究。

if __name__ == "__main__":  # 仅直接启动本文件时运行服务。
    main()  # 执行统一入口。
