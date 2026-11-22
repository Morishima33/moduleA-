# 项目上传工具

- `github_upload.ps1`：PowerShell 7.2+，模块完成并通过相应检查后，只提交明确文件并上传 `development`。
- `github_upload_policy.json`：固定仓库、开发分支及文件大小限制；不保存认证信息。
- 行为测试：`tests/test_github_upload.py`；使用 Python 标准库、Git 和 PowerShell，在临时本地仓库运行。

详细格式和使用步骤见 [GitHub自动上传说明](../docs/GitHub自动上传说明_v1.0.md)。报告和日志保存在仓库外，不提交测试结果截图或过程文件。

- `open_snapshot_preview.py`：使用指定的独立 `--data-root` 和 `--runtime-dir` 打开核查页面，启动时检查归档与 A01 版本；服务进程隐藏启动，浏览器可见。同一端口已运行时复用，不停止其他服务、不触发研究复核或科学重跑。研究快照与运行日志不提交。

- `check_report_template.py`：Python 3.11+标准库，只读核对第24版模板及直接排版依赖SHA256；失败输出具体路径，不访问或修改研究资料。清单位于`templates/A07.double_report.24.lock.json`。

- `replay_archived_network.py`：使用 Module A 的科学 Python 运行，显式指定已归档的研究、A03/A04/A05 和本机 Rscript。通过原校验器复算 A03 交集、A04 STRING 网络和 A05 GO/KEGG；R 仅在临时目录中用固定注释分析。输出每阶段归档、表格指纹和耗时。A04/A05 必须属于指定 A03；A05 支持方案富集协议 1 和 2。

  `python tools/replay_archived_network.py --data-root <归档根目录> --study-id <研究编号> --a03 <运行编号> --a04 <运行编号> --a05 <运行编号> --rscript <程序路径>`

- `check_database_evidence.py` 将补充证据输出为只读 JSON。三个入口分别核对补救批次已选实验结构的 PDBe 链和残基区间与 wwPDB 报告、对比同一 A03 下两份 A04 或 A05 归档，以及用完整 InChIKey 和人源单蛋白 UniProt 核查 ChEMBL 活性。A05 对照显著条目的命中基因、命中数和校正后 P 值。两个在线入口记录原响应的指纹。

  - `python tools/check_database_evidence.py structures --data-root <归档根目录> --study-id <研究编号> --run <A06补救运行> --target <HGNC编号>`
  - `python tools/check_database_evidence.py compare --data-root <归档根目录> --study-id <研究编号> --run <原运行> --against <对照运行>`
  - `python tools/check_database_evidence.py chembl --inchikey <已核验结构键> --uniprot <已核验蛋白编号>`
