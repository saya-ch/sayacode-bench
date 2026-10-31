# scripts/archive 索引

本目录保存**一次性历史脚本**。它们不再进入现行流程，保留仅为追溯。

| 脚本 | 为何归档 | 现在能否使用 |
|---|---|---|
| `summarize_formal.py` | v1（formal-240）跑批的一次性汇总脚本，输出三 agent 记分卡；已被 `scripts/final_summary.py` 取代。v1 结论已作废，该脚本产出的数字也不可引用。 | 仅作历史参考；现行汇总用 `scripts/final_summary.py` |

## 为什么其他历史脚本没有一起移进来

`scripts/` 根目录仍保留大量历史脚本（`calibrate_cloud.py`、`qualify_cloud.py`、`generate_sharded_workflow.py`、`prepare_primary_study.py` 等）。原因是它们被 `src/sayacode_bench/`、`tests/` 或 `.github/workflows/` **以模块导入或 SHA256 身份绑定**：

- `from scripts import qualify_cloud` 这类导入在移动后会直接 `ModuleNotFoundError`，导致相关测试失败；
- `src/installation.py`、`src/artifacts.py` 会校验这些脚本的哈希作为实现身份，移动即身份不符；
- 8 个 workflow 直接按 `scripts/<name>.py` 路径调用。

因此它们保留原位，在 [scripts/README.md](../README.md) 中标注为「历史工具（被绑定）」。若将来要真正归档，必须同步修改 `src/`、`tests/` 与 workflow 中的引用——那属于代码改动，不在本次文档清理范围内。
