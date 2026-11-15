# Windows 与 macOS 运行和迁移

本版共用 Python 服务与任务管理器。浏览、项目管理和已归档结果下载不要求安装 Vina。新平台科学执行适配尚未接通；工具预检通过也不会宣布可提交科学计算。旧 Windows 科学入口保留原协议及工具绑定，不能将其用于 Mac。

## 启动、状态与正常停止

安装 Python 3.11 或以上；建议 3.12。发布源码已经包含前端构建，开发前端需要 Node 与 `web/package-lock.json` 中的依赖。将个人配置放在 `config/local.toml`，或通过 `MODULEA_CONFIG` 指定仓库外 TOML。示例见 `config/platform.example.toml`。数据根必须包含 `studies/`，运行目录必须在研究目录之外。

Windows 在终端执行：

```bat
set MODULEA_PYTHON=C:\Tools\Python312\python.exe
modulea.cmd preflight --json
modulea.cmd start
modulea.cmd status
modulea.cmd stop --confirmed
```

macOS 在终端执行（Apple Silicon 与 Intel 使用相同入口，依赖架构分别核对）：

```sh
export MODULEA_PYTHON=/absolute/path/to/python3
chmod u+x modulea.command
./modulea.command preflight --json
./modulea.command start
./modulea.command status
./modulea.command stop --confirmed
```

默认端口 8780，可用 `--port` 或 `MODULEA_PORT` 指定。启动默认打开浏览器，用 `--no-browser` 关闭；重复启动会核对实例、配置和构建，复用同实例。端口被其他程序占用会拒绝启动。正常停止通过原服务保护接口执行，活动任务或写入会阻断；此入口不会取消科学任务或强杀 PID。日志位置由启动结果给出。配置错误返回非零退出码。中文、空格路径应整体加引号。

`preflight --json` 一次列出系统、芯片、Python、前端、数据权限、端口、工具及字体。`browse_available` 只代表基础浏览条件；`toolchain_available` 只代表工具配置核对；当前 `science_available=false`。这三个字段不能互相替代，也不表示研究验收通过。

## 科学依赖与边界

| 依赖 | 版本与来源 | 平台情况 |
| --- | --- | --- |
| AutoDock Vina | [官方 1.2.7 发布](https://github.com/ccsb-scripps/AutoDock-Vina/releases/tag/v1.2.7) | 提供 Windows x64、macOS arm64 与 x86_64；必须选本机二进制 |
| P2Rank | [官方 2.5 发布](https://github.com/rdk/p2rank/releases/tag/2.5) | Java 工具；官方要求 Java 17–23，本工具配置为保留已有执行约束固定 Java 19 |
| Java | 本机原生 JDK 19 | Java 启动器与实际运行库均须记录；不能在 Mac 调用 Windows java.exe |
| RDKit、Meeko、Gemmi、NumPy、SciPy | 显式工具配置逐项固定版本 | 需在目标芯片的科学 Python 中实际导入，不用 Rosetta 成功推断原生通过 |
| PDBFixer、OpenMM | [PDBFixer 官方说明](https://github.com/openmm/pdbfixer)、[OpenMM 安装说明](https://docs.openmm.org/latest/userguide/application/01_getting_started.html) | 需要原生库及模板/力场，能导入不能代替准备质控 |
| 中文字体 | 本机合法可用字体 | 显式配置常规及粗体；旧归档图件不重写，新平台绘图适配仍待完成 |

工具配置预检格式为 `ModuleA.platform_tools.1`，明确目标协议 `A06.platform_execution.1`。该科学协议仍待实现，不能据配置文件推断已运行。配置必须包含系统、芯片、工具路径/版本/SHA、P2Rank jar/默认配置/模型清单及科学包版本；预检不会安装、下载或静默替换任何工具。依赖许可证以各官方发行版为准。本批不引入付费服务。

## 迁移研究

先结束原机写入，复制完整数据根的备份，保留历史目录、Word 批注、人工复核记录、原件、结果、登记检查点及代码快照。不要在原机活跃工程上执行迁移或安装。运行时 SQLite 与日志不是科研事实的替代品；不要让两个实例同时写同一数据根。

在源数据副本生成清单，在目标数据副本核对：

```sh
PYTHONPATH=src python3 -m modulea.migration inventory --data-root /data/source --study study_ID --inventory /backup/inventory.json
PYTHONPATH=src python3 -m modulea.migration verify --data-root /data/target --study study_ID --inventory /backup/inventory.json
```

Windows 可先 `set PYTHONPATH=src`，然后使用相同 Python 参数。替换为实际 study_ID，不能使用示例占位符直接运行。清单必须保存在数据根之外。核验递归读取已登记引用、长度和完整 SHA，并在返回前复核；未登记残件不作为成功。目标本机工具路径重新配置，历史归档路径和指纹保持。

`history_integrity_verified=true` 仅证明已登记字节与源清单一致，`resume_allowed=false` 明确保留原 Workflow 的输入、工具、源码、人工状态和执行绑定检查。恢复旧任务仍需明确提交且所有原绑定一致；跨平台变化必须新运行，不冒充原批无缝恢复。

## 自动检查

默认只调度带 `modulea-isolated` 标签的专用自托管 Windows X64、macOS ARM64、macOS X64 runner。不要给原计算机添加该标签。没有对应 runner 时检查保持排队，不能计作通过。仓库变量 `MODULEA_CI_RUNNER_MODE=hosted` 会启用托管 runner，须事先得到用户明确同意；本次用户选择保持默认自托管，不触发托管计费。

核心流水线验证 Python 核心、前端类型、读取契约及构建；跳过项原样列出。科学流水线单独手动触发，仅在 `modulea-science-isolated` runner 上运行。两者均不代表真实 COPD 计算完成或用户科研批准。
