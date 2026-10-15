# 项目上传工具

- `github_upload.ps1`：PowerShell 7.2+，模块完成并通过相应检查后，只提交明确文件并上传 `development`。
- `github_upload_policy.json`：固定仓库、开发分支及文件大小限制；不保存认证信息。
- 行为测试：`tests/test_github_upload.py`；使用 Python 标准库、Git 和 PowerShell，在临时本地仓库运行。

详细格式和使用步骤见 [GitHub自动上传说明](../docs/GitHub自动上传说明_v1.0.md)。报告和日志保存在仓库外，不提交测试结果截图或过程文件。

- `open_snapshot_preview.py`：使用指定的独立 `--data-root` 和 `--runtime-dir` 打开核查页面，启动时检查归档与 A01 版本；服务进程隐藏启动，浏览器可见。同一端口已运行时复用，不停止其他服务、不触发研究复核或科学重跑。研究快照与运行日志不提交。

- `check_report_template.py`：Python 3.11+标准库，只读核对第24版模板及直接排版依赖SHA256；失败输出具体路径，不访问或修改研究资料。清单位于`templates/A07.double_report.24.lock.json`。
