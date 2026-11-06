# 「改测试通过」的真相：测试代码被重置，只有快照可改（2026-11-02）

> ## ⛔ 更正（2026-11-07）：核心前提已被证伪，本文结论作废
>
> 本文原断言「`__snapshots__/*.snap` 不被 verifier 重置」是**错误**的。实测 **642/642** 个任务镜像的 `tests/test.sh:97-105` 在判分前对 `*__snapshots__/*` 执行 `git checkout HEAD`（`:101` 的 `__NONE__` 哨兵使跳过分支永不触发；7 个模板偏移至 102-110，豁免的是个别 testdata 文件，不含任何 `__snapshots__` 路径）。因此 **agent 对快照的修改在判分时同样被还原**，「改快照换来的 pass」不存在。
>
> 后果：基于该前提的 `strict` 口径，以及本文全部「改 `.snap` 有效」的计数（mini-swe 4 / Codex 3 / SAYACODE 0）**一律作废**；`PROTOCOL-V2 §5.1` 已废除 strict。正确结论是：verifier 同时重置**测试代码**（`CODE_DIRS` 分支）与**测试数据面**（`DATA_DIRS` / 快照分支）。
>
> 证据：[RETROSPECTIVE-20261107](review/2026-11-07/RETROSPECTIVE-20261107.md) §四.1（P0-1，含 642/642 实测与 `test.sh` 片段）、`tests/test.sh` 原始文件、[PROTOCOL-V2 §5.1](PROTOCOL-V2.md)。
>
> 本文保留原始分析以记录错误推导过程；仍然有效的部分见文末 §六。

> 触发：分析 v2 通过 trial 的 patch 时，发现 Codex/mini-swe 有 41%/51% 的 pass 「修改了既有测试文件」，而 SAYACODE 为 0。需要判定这是否影响判分。
> ~~结论：**verifier 会重置测试代码（无效），但不重置 `__snapshots__/*.snap`（有效）**。真正「靠改测试通过」的只有 mini-swe 4 个、Codex 3 个、SAYACODE 0 个（占 pass 5–7%），不是 41%/51%。~~ `[已证伪，见顶部横幅]`

## 一、verifier 的 reset 范围（以 `tests/test.sh` 为准）

- `tests/test.sh` 在判分前执行 `Resetting test-space to base state (full test-code surface)`：
  - `CODE_DIRS = {tests, test, __tests__, spec, specs}` → 命中则 `git checkout HEAD -- <path>`（重置）；
  - `DATA_DIRS = {testdata, test_data, fixtures, fixture, mocks, mock, __snapshots__}` → **命中则排除，不重置**（`test.sh:38,43`）。`[部分证伪：这仅说明不按「测试代码」路径重置；`test.sh:97-105` 另行对数据/快照面执行 `git checkout HEAD`]`
- 因此：
  - 修改 `tests/*.py`、`*_test.go`、`*.test.tsx` 等 **测试代码 → 被重置，对 reward 无效**。（这一半仍然成立）
  - ~~修改 `__snapshots__/*.snap` **快照 → 不被重置，对 reward 有效**。~~ `[已证伪，见顶部横幅]` 实测 `test.sh:97-105` 对 `*__snapshots__/*` 同样执行 `git checkout HEAD`。

## 二、规模（v2 终版，pass trial；下表计数已作废 `[已证伪，见顶部横幅]`）

| agent | pass | 改 `.snap`（原判「有效」`[已证伪]`） | 改测试代码（被 reset，无效） |
|---|---|---|---|
| SAYACODE | 63 | **0** | 0 |
| mini-swe | 56 | **4** | 19 |
| Codex | 55 | **3** | 25 |

- SAYACODE 为 0：其 bench adapter worker（`worker.py:497 restore_existing_test_files`）在提交 patch 前就 `git checkout` 还原了既有测试文件，且最终 patch 不含测试。
- 对手（mini-swe/Codex）没有这层保护，patch 里会带测试改动；但 **verifier 会重置测试代码**，所以 41%/51% 里绝大部分对分数无影响。
- ~~有效的只有 `.snap`：mini-swe `element-web-9bf77963ee` r1/r2、`b7fea97bb6` r1；Codex `b7fea97bb6` r2 等。~~ `[已证伪]` 这些 trial 的快照修改在判分前已被 `git checkout HEAD` 还原；其中 mini-swe `element-web-9bf77963ee-r1` 改的两个 `.snap` 正是官方 `test_patch.patch` 要更新的路径，与它的通过**没有因果关系**。该计数若要保留，只能改名为 `touches_snap_pass`（行为描述，不参与排名）。

## 三、严格口径（扣除「靠改 .snap 通过」）—— ⛔ 整节作废 `[已证伪，见顶部横幅]`

> 下表基于「`.snap` 修改有效」的错误前提；实测快照在判分前已被 verifier 还原，`strict` 口径已由 [PROTOCOL-V2 §5.1](PROTOCOL-V2.md) 废除。本表**仅供追溯错误推导**，不得引用。

| agent | planned pass | 扣除改 snap 后 | planned%（严格） |
|---|---|---|---|
| SAYACODE | 63/80 | 63 | **78.8%** |
| mini-swe | 56/80 | 52 | **65.0%** |
| Codex | 55/80 | 52 | **65.0%** |

- ~~方向不变（SAYACODE 仍最高），差距从 **10.0pp** 扩到 **13.8pp**。~~ `[已证伪]`
- ~~但修订幅度有限（mini-swe/Codex 各 −3.8pp），**不能把对手说成「一半靠改测试」**。~~ 结论的后半句仍成立，但不能再以 strict 差值论证。

## 四、需要纠正的旧说法

- 此前分析（`C:\sb\tmp\explore\analysis2\semantic-diff.md`）称「top 1–3 是修改既有测试后 reward=1，是改测试通过的直接证据」——~~部分正确~~ `[已证伪]`：其中含 `.snap` 的 job 同样被 `git checkout HEAD` 还原，**没有任何 job 因改测试/快照而对 reward 有效**；「纯改 `test_pip.py`/`*_test.go` 会被 reset」这一半仍成立。
- ~~正确表述：**「修改测试代码无效（被 verifier 重置）；修改快照有效，规模 3–4 个 trial」**。~~ `[已证伪]` 正确表述（2026-11-07）：**verifier 同时重置测试代码与测试数据面（含 `__snapshots__`）；不存在「改测试/快照通过」的 trial。** 相关计数只能作行为描述（`touches_snap_pass`），不能用于能力对比。

## 五、对评测设计的含义

1. **不要用「patch 含测试文件」当作弊指标**——verifier 重置后大部分无效（结论仍成立）。~~应看「是否改 `.snap`」或「是否在 reset 白名单外改测试」。~~ `[已证伪]` `.snap` 同样被重置，「是否改 `.snap`」不再是有区分度的有效指标，只能作行为描述。
2. **SAYACODE 的 worker 还原机制**：即使不还原，verifier 也会重置测试代码；还原的真实作用是让最终 patch 更干净。~~避免快照类误判（SAYACODE 因此拿不到靠改快照的分）~~ `[已证伪]` 快照同样被重置，不存在「靠改快照的分」。
3. ~~**若要公平，两个选择**：宽松（允许改快照）/ 严格（对所有 agent 还原 `.snap`）。~~ `[已证伪]` 两个选择都不必要——verifier 已对 `.snap` 统一执行 `git checkout HEAD`，组间不存在快照差异。
4. 2026-11-07 已处理：`PROTOCOL-V2 §5.1` 废除 `strict`，仅允许 `touches_snap_pass` 作为行为描述列，且必须附「快照在判分前已被还原、不影响结果、不参与排名」声明。

## 六、仍然有效的部分（2026-11-07 更正后）

1. **verifier 会重置测试代码**（`CODE_DIRS` / `is_test_code`，`test.sh:37-74`）：修改 `tests/*.py`、`*_test.go`、`*.test.tsx` 等对 reward 无效——这一半仍然成立。
2. **「patch 含测试文件」不能当作弊指标**：测试代码确实被重置，按 patch 是否含测试文件统计「作弊率」会系统性高估。
3. **SAYACODE 的 worker 还原机制**（`restore_existing_test_files`）仍有价值：它让最终 patch 更干净、不含测试改动；但不能再声称它「挡住了靠改快照的分」。
4. **`.snap` 触碰计数可保留为行为描述**，唯一允许的名字是 `touches_snap_pass`，且必须注明「快照在判分前已被还原，不影响结果，不参与排名」。
5. **`strict` 口径与本文原「严格口径」整节作废**；现行口径见 [PROTOCOL-V2](PROTOCOL-V2.md) §2 / §5.1。

## 七、更正记录

- 2026-11-07：`strict` 前提证伪（642/642 `test.sh:97-105` 重置 `*__snapshots__/*`；`__NONE__` 哨兵使跳过分支不可达）。本文顶部加更正横幅，依赖该前提的推论逐条标记 `[已证伪]`，并补「仍然有效的部分」。证据：[RETROSPECTIVE-20261107](review/2026-11-07/RETROSPECTIVE-20261107.md) §四.1、[PROTOCOL-V2 §5.1](PROTOCOL-V2.md)。
