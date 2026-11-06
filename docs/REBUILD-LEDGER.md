# 从原始产物重建 RESULTS-LEDGER

> 目标：一条命令重建 [RESULTS-LEDGER](RESULTS-LEDGER.md) §2/§3 的主表数字。**只读**、不跑模型、不改数据。
> 本页是给「三个月后的自己」看的操作卡：命令、预期输出、常见错误。

## 前置

- 仓库 `C:\develop\sayacode-bench`，用 `uv run --no-sync`（脚本自带 `sys.path`，无需手动 PYTHONPATH）。
- 数据根：
  - v2-325（四组：SAYACODE 3.2.5 / mini-swe / Claude Code / OpenCode）→ `C:\sb\hard\v2-325`
  - v4-327（3.2.7，只有 sayacode）→ `C:\sb\hard\v4-327`
- v1 `C:\sb\hard\formal-240` **已删除**，只剩 `C:\sb\archive\formal-240-v1-20261031.zip`；v1 不参与 ledger 主表，不要拿它当默认根。

## 三条命令

### ① v2-325 四组（ledger §2.1）

```powershell
cd C:\develop\sayacode-bench
uv run --no-sync python scripts\final_summary.py --root C:\sb\hard\v2-325 --out C:\sb\bp-tmp\rebuild-v2.json
```

预期（planned / partial trial 级）：

| agent | planned | 缺失 | partial（n） |
|---|---:|---:|---:|
| sayacode | 78.8% (63/80) | 1 | 99.2%（73） |
| mini-swe | 85.0% (68/80) | 1 | 98.5%（77） |
| claude-code | 77.5% (62/80) | 1 | 97.8%（76） |
| opencode | 75.0% (60/80) | 0 | 94.4%（77） |

### ② v4-327（ledger §2.2）

```powershell
uv run --no-sync python scripts\final_summary.py --root C:\sb\hard\v4-327 --agents sayacode --out C:\sb\bp-tmp\rebuild-v4.json
```

预期：planned **76.2%（61/80）**、observed 77.2%、缺失 1（`vuls-4b680b99606` r1 `empty_patch`）、
task_macro 76.9%（39 题）、题级全通过 24/39、pass@2 36/39、partial 题级 97.8%。

### ③ 同题配对（ledger §3.2）

```powershell
uv run --no-sync python scripts\paired_compare.py --old C:\sb\hard\v2-325\FINAL-SUMMARY-V4.json --new C:\sb\hard\v4-327\FINAL-SUMMARY-327.json --out C:\sb\bp-tmp\paired-325-327.json
```

预期：配对 **78 trial（40 题）**；3.2.5 63/78 = 80.8% → 3.2.7 61/78 = 78.2%；
**Δ = −2.6pp**、McNemar exact **p = 0.8145**、题块 bootstrap 95% **[−12.5, +6.2] pp**；
翻转 18（3.2.5 独过 10 / 3.2.7 独过 8）。

## 常见错误

1. **默认根是 v2-325**：跑 v4-327 忘传 `--root`，会得到 v2 四组数据——数字对但批次错。
2. **别拿 v1 当根**：`formal-240` 已删，只有 zip；重建 ledger 不需要它。
3. **两批不可合并排名**（ledger §2.3）：v2-325 与 v4-327 制品/时间/served 都不同；跨批 McNemar 不得使用。
4. **partial 只能取 `verifier/output.json`**：`FINAL-SUMMARY` 的 `trials[].partial` 是 test-stdout 口径、覆盖不全（ledger §5.1）。`final_summary.py` 的 partial 段已按 output.json 重算。
5. **默认会覆盖** `<root>/FINAL-SUMMARY.json`：重建一律用 `--out` 到临时路径，避免改动数据根。
6. **数字对不上**：先核本页预期 → 再核数据根 mtime 与 `normalized.json` → 仍不一致就报 Lead，**不要自行改 ledger**。
7. 脚本只读磁盘，不跑 Docker/模型；`--agents` 默认四组，codex 组已作废，仅在历史复现时显式传。

## 校验方式

把三条命令的 JSON 写到 `C:\sb\bp-tmp\`，与 [RESULTS-LEDGER](RESULTS-LEDGER.md) §2/§3 逐项比对。
任何一项不一致都属于数据或口径问题，提交给 Lead 决定改代码还是改 ledger。
