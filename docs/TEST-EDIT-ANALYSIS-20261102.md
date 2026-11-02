# 「改测试通过」的真相：测试代码被重置，只有快照可改（2026-11-02）

> 触发：分析 v2 通过 trial 的 patch 时，发现 Codex/mini-swe 有 41%/51% 的 pass 「修改了既有测试文件」，而 SAYACODE 为 0。需要判定这是否影响判分。
> 结论：**verifier 会重置测试代码（无效），但不重置 `__snapshots__/*.snap`（有效）**。真正「靠改测试通过」的只有 mini-swe 4 个、Codex 3 个、SAYACODE 0 个（占 pass 5–7%），不是 41%/51%。

## 一、verifier 的 reset 范围（以 `tests/test.sh` 为准）

- `tests/test.sh` 在判分前执行 `Resetting test-space to base state (full test-code surface)`：
  - `CODE_DIRS = {tests, test, __tests__, spec, specs}` → 命中则 `git checkout HEAD -- <path>`（重置）；
  - `DATA_DIRS = {testdata, test_data, fixtures, fixture, mocks, mock, __snapshots__}` → **命中则排除，不重置**（`test.sh:38,43`）。
- 因此：
  - 修改 `tests/*.py`、`*_test.go`、`*.test.tsx` 等 **测试代码 → 被重置，对 reward 无效**。
  - 修改 `__snapshots__/*.snap` **快照 → 不被重置，对 reward 有效**。

## 二、规模（v2 终版，pass trial）

| agent | pass | 改 `.snap`（有效） | 改测试代码（被 reset，无效） |
|---|---|---|---|
| SAYACODE | 63 | **0** | 0 |
| mini-swe | 56 | **4** | 19 |
| Codex | 55 | **3** | 25 |

- SAYACODE 为 0：其 bench adapter worker（`worker.py:497 restore_existing_test_files`）在提交 patch 前就 `git checkout` 还原了既有测试文件，且最终 patch 不含测试。
- 对手（mini-swe/Codex）没有这层保护，patch 里会带测试改动；但 **verifier 会重置测试代码**，所以 41%/51% 里绝大部分对分数无影响。
- 有效的只有 `.snap`：mini-swe `element-web-9bf77963ee` r1/r2、`b7fea97bb6` r1；Codex `b7fea97bb6` r2 等。

## 三、严格口径（扣除「靠改 .snap 通过」）

| agent | planned pass | 扣除改 snap 后 | planned%（严格） |
|---|---|---|---|
| SAYACODE | 63/80 | 63 | **78.8%** |
| mini-swe | 56/80 | 52 | **65.0%** |
| Codex | 55/80 | 52 | **65.0%** |

- 方向不变（SAYACODE 仍最高），差距从 **10.0pp** 扩到 **13.8pp**。
- 但修订幅度有限（mini-swe/Codex 各 −3.8pp），**不能把对手说成「一半靠改测试」**。

## 四、需要纠正的旧说法

- 此前分析（`C:\sb\tmp\explore\analysis2\semantic-diff.md`）称「top 1–3 是修改既有测试后 reward=1，是改测试通过的直接证据」——**部分正确**：其中只有含 `.snap` 的 job 有效；纯改 `test_pip.py`/`*_test.go` 的会被 reset，**不构成作弊**。
- 正确表述：**「修改测试代码无效（被 verifier 重置）；修改快照有效，规模 3–4 个 trial」**。

## 五、对评测设计的含义

1. **不要用「patch 含测试文件」当作弊指标**——verifier 重置后大部分无效；应看「是否改 `.snap`」或「是否在 reset 白名单外改测试」。
2. **SAYACODE 的 worker 还原机制是多余的严格**：即使不还原，verifier 也会重置测试代码；但还原能保证 patch 干净、避免快照类误判（SAYACODE 因此拿不到靠改快照的分）。
3. **若要公平，两个选择**：
   - **宽松**：所有 agent 都允许改快照（当前事实上如此，但 SAYACODE 被自己的保护挡住）→ 应在报告里注明 SAYACODE 未利用该空间。
   - **严格**：对所有 agent 都还原/重置 `.snap`（需改 verifier 或 adapter）→ 当前未做。
4. 建议在 `PROTOCOL-V2` 的缺失/口径里加一条：**「改快照通过」单列**，不进 pass@1 主表，或作为敏感性分析。
