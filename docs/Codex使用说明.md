# Codex 使用说明

本文件告诉你如何让 Codex（或其他编程代理）在本项目里按规范开发。

## 1 Codex 怎么知道项目规范

**不需要每次在对话里重复规则。** Codex 启动时会自动读取仓库里的 `AGENTS.md`，把它当作项目规范：

| 文件 | 作用范围 |
|---|---|
| `AGENTS.md`（根目录） | 全仓库：项目约束、科学决定摘要、架构硬规则、代码规范、开发流程、停止条件 |
| `src/AGENTS.md` | 科学内核（扁平模块）：冻结规则、待拆解清单 |
| `src/modulea/AGENTS.md` | 新架构外壳：分层、依赖方向、扩展方式 |
| `src/modulea/api/AGENTS.md` | 前后端接口契约 |
| `src/modulea/presenters/AGENTS.md`、`src/modulea/tasks/AGENTS.md` | 展示适配、后台任务 |
| `web/AGENTS.md` | 前端 |
| `tests/AGENTS.md` | 测试 |

规则是“由近到远”：Codex 改某个文件时，该文件所在目录的 `AGENTS.md` 优先，上级目录的规则同样有效。根目录 `AGENTS.md` 第 1 节规定了与已批准大纲的优先级关系，Codex 不能用这些文件推翻大纲。

**注意读取上限。** Codex 默认最多读取约 32 KB 的项目规范，目前最长的一条链路（根目录 → src → src/modulea → src/modulea/api）约 31 KB。如果以后文件变长，Codex 提示规范被截断，在本机 `~/.codex/config.toml` 中加一行：

```toml
project_doc_max_bytes = 65536
```

## 2 怎么开始一项任务

1. 在项目根目录打开 Codex（`codex`），或在 Codex 应用中选择本仓库。
2. 从 `main` 新建分支，一项任务一个分支、一个 PR。
3. 用下面的模板下任务（把【】换成具体内容）：

```text
任务：【一句话描述，例如“接入 A03_SELECT 候选选择的新接口”】
依据：【对应文档位置，例如 src/AGENTS.md 第 3 节第 2 条 / README 第 5 节路线第 1 项】
要求：
- 先读根目录 AGENTS.md 以及要改动目录的 AGENTS.md，按其中的规则执行。
- 遇到大纲和 AGENTS.md 都没有答案的科学或流程问题，停下来问我，不要自己决定。
- 不改 studies/ 下任何文件，不改已批准大纲 Word，不改已批准规则版本的行为。
- 完成后运行 PYTHONPATH=src python3 -m unittest discover -s tests/modulea；
  改到科学内核时，再运行对应的 tests/test_*.py，并写明运行环境。
- 提交 PR，说明改了什么、依据哪条规则、测试结果；不要自行合并。
```

4. 审核 PR：看 PR 说明里有没有写明依据和测试结果，`studies/` 和 `docs/*.docx` 是否没有改动。合并由你操作。

## 3 推荐的任务顺序

每一项单独开一个 PR，前一项合并后再开下一项。

| 顺序 | 任务 | 依据 | 完成标志 |
|---|---|---|---|
| 1 | 修复 `ppi_flow.py` 未传授权时回退到 COPD 授权的缺陷 | `src/AGENTS.md` 第 3 节第 2 条 | 不传授权且存在身份缺口时阻断并给出中文原因；COPD 与过敏性鼻炎原有测试结果不变 |
| 2 | 统一 A07 校验（`docking_automation.py` 改走 `report_dispatch`） | 同上第 4 条 | 自动化路径和网页路径对同一 A07 运行得到相同校验结论 |
| 3 | 复算护栏工具：核验全部已批准运行的归档指纹，并比对冻结实现从归档输入复算的结果 | 根目录 AGENTS.md 第 3 节第 7 条 | 对 4 项研究运行一次全部通过，输出中文报告；工具只读 |
| 4 | 模块操作接入新接口：运行、上传、A02 范围批量决定、A03_SELECT 选择、A06 结构方案确认、通路审核 | `src/modulea/api/AGENTS.md` 第 7 节 | 每个操作有 `POST .../actions/{action}`、契约文档和前端入口；新版工作台不再需要原网页 |
| 5 | 历史授权从代码移到研究包内的决定文件 | `src/AGENTS.md` 第 3 节第 1 条 | 通用代码中找不到研究编号；复算结果不变 |
| 6 | 解除通用代码对病例脚本的依赖，合并重复实现 | 同上第 3、5 条 | 每类一个实现，按版本号分派；旧版本行为逐位不变（由第 3 项护栏证明） |
| 7 | 对接复用键改为算法版本号；平台路径配置化；依赖锁定 | 同上第 6、7、8 条 | 换电脑只需填写 `config/local.toml`；旧复用条目仍能命中 |

第 3 项（复算护栏）要在第 5、6 项之前完成，否则无法证明改动没有影响历史结果。

## 4 必须停下来问你的情况

根目录 `AGENTS.md` 第 8 节第 4 条列出的停止条件，Codex 遇到时应停下报告，而不是自行处理。最常见的几种：

- 需要一个大纲和已确认决定都没有规定的科学参数（例如新的阈值、新的数据库、新的受体选择规则）。
- 需要移动、重命名或删除既有文件。
- 已批准运行的归档文件指纹发生变化。
- `studies/` 出现不是你自己操作产生的改动。

如果 Codex 没有停下而是自作主张，PR 审核时直接退回，并在对话里提醒它重读根目录 `AGENTS.md` 第 2 节。

## 5 常用命令

```bash
# 新版工作台
PYTHONPATH=src python3 -m modulea serve
# 环境检查
PYTHONPATH=src python3 -m modulea doctor
# 外壳测试
PYTHONPATH=src python3 -m unittest discover -s tests/modulea -v
# 演示数据（只读源研究）
PYTHONPATH=src python3 -m modulea.devtools.demo_data /tmp/moduleA-demo --source . --study <研究编号>
# 前端开发与构建
cd web && npm install && npm run dev
cd web && npm run build
```
