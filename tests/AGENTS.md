# tests/ — 测试

| 位置 | 内容 | 数据 | 运行方式 |
|---|---|---|---|
| `tests/modulea/` | 新架构外壳：接口、状态映射、安全检查、复核、回收站 | 临时目录中的虚构研究（`devtools.demo_data` 内置数据） | `PYTHONPATH=src python3 -m unittest discover -s tests/modulea`，任何平台 |
| `tests/test_*.py` | 科学内核各模块 | 多数为虚构数据；部分读取真实研究（只读） | 需要科学依赖（networkx、python-docx、rdkit、meeko 等），在 Windows 参考环境运行 |
| `tests/*.mjs` | 原网页的 Playwright 检查 | 虚构研究 | 需要外部 Playwright（`MODULEA_NODE_MODULES`） |

## 规则

1. 常规测试一律使用临时目录和虚构研究；**不得写入 `studies/`**。
2. 读取真实研究的测试必须只读，并在数据缺失时跳过（`skipIf`）并说明原因（现有少数测试尚未加跳过，属于待办）。
3. 修复缺陷先写能复现缺陷的测试。
4. 改动科学内核时，说明在哪个平台、用哪个解释器运行了哪些测试；不能运行的测试如实写明原因，不写“全部通过”。
5. 测试截图等中间产物不提交到仓库。
