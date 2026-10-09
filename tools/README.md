# 项目上传工具

- `github_upload.ps1`：PowerShell 7.2+，模块完成并通过相应检查后，只提交明确文件并上传 `development`。
- `github_upload_policy.json`：固定仓库、开发分支及文件大小限制；不保存认证信息。
- 行为测试：`tests/test_github_upload.py`；使用 Python 标准库、Git 和 PowerShell，在临时本地仓库运行。

详细格式和使用步骤见 [GitHub自动上传说明](../docs/GitHub自动上传说明_v1.0.md)。报告和日志保存在仓库外，不提交测试结果截图或过程文件。
