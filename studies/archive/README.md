# studies/archive 索引

本目录保存**历史统计协议修订**。它们没有对应的正式效果试验，**不能作为现行依据，也不能从中挑选更有利的结果**。

| 文件 | 说明 |
|---|---|
| `sensitivity-protocol-v2.json` … `sensitivity-protocol-v5.json` | 早期协议修订（v2–v4 体量很小，v5 起加入费用/资源字段）。已全部被 v12 取代，仅作修订历史。 |
| `sensitivity-protocol-v6.json` | 引入统计与资源身份绑定；`sharded-execution-design.md`（已归档）曾引用。仅作历史。 |
| `sensitivity-protocol-v7.json` | 引入分片、编排、资格入口与完整实现身份。仅作历史。 |
| `sensitivity-protocol-v8.json` | 引入跨阶段目录隔离、物理批次恢复、Terminal 补充合同。仅作历史。 |
| `sensitivity-protocol-v9.json` | 修复目录指纹的跨平台排序（大小写敏感元组）。仅作历史。 |
| `sensitivity-protocol-v10.json` | 补齐离线报告门禁（独立分析 CLI 与标准报告共用费用证据检查）。仅作历史。 |
| `sensitivity-protocol-v11.json` | 新增显式收据核验与三阶段输入装配。仅作历史。 |

**现行统计协议是 `studies/sensitivity-protocol-v12.json`**（被 `src/sayacode_bench/study.py` 绑定）。任何分析都应使用 v12，不要用本目录的旧版本。

现行执行合同 `studies/execution-protocol-v13.json` 绑定 v12 的 SHA256；它留在 studies 根（被 `src/study.py` 引用），不在本目录。
