# AUDIT-RECOMPUTE：impact-350 vs v2v-main 独立复核

> 方式：只读原始文件，用本文件 §6 的脚本从 `FINAL-SUMMARY.json`、`sayacode/jobs/*`、`tasks/*/solution/gold_patch.diff` 重算；不参考任何既有结论或数字。
> 数据根：`C:\sb\hard\ab-ctx\impact-350`、`C:\sb\hard\ab-ctx\v2v-main`；题集 `C:\sb\hard\ab-ctx\sample-20.json`（20 题）。

## 1. 复核结果表（含口径）

### 1.1 通过率（`effective_reward`；分母=40 trial）

| 组 | reward=1.0 | reward=0.0 | reward=None | planned（None 算失败） | observed（排除 None） |
|---|---:|---:|---:|---:|---:|
| impact-350 | **24** | 16 | **0** | **24/40 = 60.0%** | 24/40 = 60.0% |
| v2v-main | **23** | 17 | **0** | **23/40 = 57.5%** | 23/40 = 57.5% |

- 本数据两组 None 均为 0，因此 **planned 与 observed 数值相同**；口径差异在本数据上为 0。
- 若未来出现 None：planned 计入分母算失败，observed 从分母排除（脚本已按此实现）。

### 1.2 配对分析（key = `(task_id, repeat)`）

| 项 | 值 |
|---|---:|
| 配对 key（两组交集） | **40**（20 题 × 2 repeat，无缺失 key） |
| 双方都通过 | **20** |
| 只 impact-350 通过 | **4** |
| 只 v2v-main 通过 | **3** |
| 双方都失败 | **13** |
| **McNemar 精确 p（two-sided）** | **1.0**（b=4, c=3, n=7, k=3：2·(1+7+21+35)/128 = 1.0） |

- 校验：both_pass + only_impact = 20+4 = 24 = impact-350 通过数；both_pass + only_control = 20+3 = 23 = v2v-main 通过数。一致。
- 另一口径（None 算失败）结果**相同**（本数据 None=0）：both 20 / only_impact 4 / only_control 3 / both_fail 13，p=1.0。

### 1.3 空 patch（`patch` 字节字段）

| 组 | patch == 0 | patch is None | 合计 |
|---|---:|---:|---:|
| impact-350 | **4** | 0 | 4 |
| v2v-main | **5** | 0 | 5 |

- 两组 0 字节 patch 的 trial 其 `effective_reward` 均为 0.0（实测 4/4、5/5）。
- impact 的 0 字节 trial：openlibrary-03095f r2、flipt-756f r1、element-web-772df302 r2、navidrome-0130c r1。
- v2v 的 0 字节 trial：ansible-7e1a3 r2、qutebrowser-3d01c r2、qutebrowser-3e21c r2、flipt-756f r1、navidrome-6b3b4 r1。

### 1.4 文件覆盖率（`|model.patch ∩ gold| / |gold|`）

gold 来源：`C:\sb\tmp\hard\cache\swe-bench-pro-v2-…\v2\tasks\<task_id>\solution\gold_patch.diff`（**20/20 存在**）。
模型文件集合：每个 trial 的 `agent/model.patch` 的 `+++ b/` 路径集合。gold 文件集合同理。

| 组 | 口径 | 平均覆盖率 | 样本 |
|---|---|---:|---|
| impact-350 | 全部题（40 trial 平均） | **0.6274** | 40 |
| impact-350 | gold≥3 文件（15 题） | **0.5698** | 15 题 / 30 trial |
| v2v-main | 全部题（40 trial 平均） | **0.5481** | 40 |
| v2v-main | gold≥3 文件（15 题） | **0.4974** | 15 题 / 30 trial |

- 「题级平均」与「trial 平均」数学上相等（每题恰 2 repeat，见 §3）；两组 20 题中 gold≥3 文件的都是 **15 题**。
- 每题两 repeat 的覆盖率**不完全相同**：impact 5 题不同、v2v 11 题不同（所以不能用「一题一值」替代 trial 级分布）。

### 1.5 数据完整性（40 trial/组）

| 组 | 缺 `agent/model.patch` | 缺 `audit.jsonl` | `result.json.stats.n_errored_trials > 0` |
|---|---:|---:|---:|
| impact-350 | **0** | **0** | **0** |
| v2v-main | **0** | **1** | **3** |

- v2v-main 缺 audit 的 trial：`sayacode-qutebrowser__qutebrowser-3d01c201b-r2`（同时 n_errored_trials=1）。
- v2v-main 其它 errored：`qutebrowser-3e21c8214-r2`、`flipt-io__flipt-9d25c18b79-r1`（各有 audit，但 result.json 报 1 个 errored）。

## 2. 匹配与完整性

### 2.1 job 名 ↔ task_id 匹配（重点怀疑点，已实测）

- job 名格式：`sayacode-<repo>__<name>-<commit前缀>-r<repeat>`；task_id 格式：`instance_<repo>__<name>-<commit(40 hex)>[-v<version>]`。
- 匹配规则：**用 task_id 的 40 位 commit 做前缀匹配**（`commit.startswith(prefix)`），并用 `<repo>__<name>` 与 `repeat` 双校验。
- 实测：**两组各 40/40 trial 全部匹配**，无 parse 失败、无歧义；20 题 × 2 repeat = 40 个唯一 `(task_id, repeat)`。
- 前缀长度实测分布：**[5, 9, 10, 11, 13, 17, 18, 19]**；**每组有 20 个 trial 的前缀长度 < 12**（其中 12 个 < 10）。
  - 因此**用「固定 12 位 commit」硬匹配会漏掉一半 trial**（20/40）；这是必须用前缀匹配的实证原因。
- 注意 `<repo>` 含 `-`（`flipt-io`、`element-hq`、`future-architect`），不能用 `rsplit("-", 1)` 拆 job 名——实测该写法会拆错 14/40（首版脚本即犯此错，修正后才 40/40）。

### 2.2 r1/r2 混淆（重点怀疑点，已实测）

- 用 `(task_id, repeat)` 作 key：两组各 **40** 个唯一 key（不是 20）。
- 若用 `task_id` 单键合并 r1/r2：只剩 **20** 个 key；即便取「最后一次 repeat」口径，impact 通过 12、v2v 通过 10；「任一 repeat 通过」口径 impact 14、v2v 15——**都与 40-trial 的 24/23 不同**。样本量和通过数都会错，不能这样合并。

### 2.3 gold 来源（与任务描述不完全一致，如实说明）

- 任务说「gold 从上面那个 jsonl 取」，但 `C:\sb\hard\ab-ctx` 下**没有名为 gold 的 `.jsonl`**（搜索 `*gold*.jsonl` 无结果）；`sample-20.json` 只有 `task_id`/`repo`，不含 gold patch 内容。
- 因此本复核采用 `tasks/<task_id>/solution/gold_patch.diff`（SWE-bench Pro V2 官方 solution，20/20 存在）。
- `ab-ctx\failure-diffs\` 下有 14 个 `*.gold.patch`，抽样对比发现其文件集合与 tasks 目录 gold **不一致**（例：flipt-756f 的 failure-diffs gold 有 8 个文件，tasks 目录 gold 有 6 个）——无法确认两者同源，故**未采用** failure-diffs 的 gold。

## 3. 不同口径差异有多大

| 口径选择 | 数字 | 差异 |
|---|---|---|
| planned vs observed（None=0） | 60.0% vs 60.0%；57.5% vs 57.5% | **0**（本数据无 None） |
| McNemar 完整配对 vs None 算失败 | p=1.0 vs p=1.0（b=4/c=3） | **0** |
| 覆盖率「全部题」vs「gold≥3 文件」 | impact 0.6274 vs 0.5698；v2v 0.5481 vs 0.4974 | 差 **5.8pp / 5.1pp**（gold≥3 略低） |
| 题级平均 vs trial 平均 | 相等（0.6274；0.5481） | **0**（每题恰 2 repeat） |
| 用 `task_id` 单键 vs `(task_id, repeat)` | 20 vs 40 key；通过数 12/10（last）或 14/15（any）vs 24/23 | **样本量减半、通过数全错** |
| 固定 12 位 commit vs 前缀匹配 | 漏 20/40 trial（前缀 <12 的题） | **一半样本丢失** |

## 4. 我无法确认的

1. **「gold 从上面那个 jsonl 取」具体指哪个文件**：`ab-ctx` 下没有 gold jsonl；若另有所指（例如某次导出的补丁清单），我没有找到，也未纳入。
2. **`failure-diffs` 的 14 个 `.gold.patch` 与 tasks 目录 gold 是否同源**：抽样文件集合不一致（flipt-756f 8 vs 6），无法确认；未采用。
3. **0 字节 patch 的语义**：4/5 个 0 字节 trial 的 reward 都是 0，但「0 字节」可能是模型没输出、也可能是 patch 被截断；未查 `audit.jsonl`/`job.log` 确认根因。
4. **v2v-main 3 个 `n_errored_trials=1` 的根因**：只统计了计数，未读 `job.log`/`exception`；其中 `qutebrowser-3d01c r2` 同时缺 `audit.jsonl`。
5. **覆盖率是文件集合级**：不看行级差异、不看内容正确性；「文件被改到」不等于「改对」。
6. **`effective_reward` 由谁写入**：本复核直接读 `FINAL-SUMMARY.json` 的 `effective_reward`，未回溯它是由 `reward` 与 `terminal` 如何合成的（`reward`/`terminal` 字段也在 trial 中，但本次只按 `effective_reward` 口径）。

## 5. 复核用脚本（可直接运行）

> 脚本路径：`C:\sb\tmp\audit-recompute\recompute.py`（只读）。以下为完整源码。

```python
"""独立复核 impact-350 vs v2v-main（只读原始文件）。"""
import json, os, re, math
from collections import Counter, defaultdict

BASE = r"C:\sb\hard\ab-ctx"
TASKS = r"C:\sb\tmp\hard\cache\swe-bench-pro-v2-66f92766bba642462d4bbe5479e83f91f9211862\v2\tasks"
GROUPS = {"impact-350": os.path.join(BASE, "impact-350"), "v2v-main": os.path.join(BASE, "v2v-main")}

def parse_job(job):
    m = re.match(r"^sayacode-(.+)-([0-9a-f]{5,40})-r([12])$", job)
    return (m.group(1), m.group(2), int(m.group(3))) if m else None

def parse_tid(tid):
    m = re.match(r"^instance_(.+)-([0-9a-f]{40})(?:-v[0-9a-z]+)?$", tid)
    return (m.group(1), m.group(2)) if m else None

def patch_files(path):
    files = set()
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("+++ b/"):
            p = line[6:].strip()
            if p != "/dev/null":
                files.add(p)
    return files

def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = 2 * sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, p)

def trial_dir(job_dir):
    cands = [d for d in os.listdir(job_dir)
             if os.path.isdir(os.path.join(job_dir, d)) and d.startswith("instance_")]
    return os.path.join(job_dir, cands[0]) if cands else None

def find_audit(trial):
    for root, dirs, files in os.walk(trial):
        if "audit.jsonl" in files:
            return os.path.join(root, "audit.jsonl")
    return None

def load_group(path):
    d = json.load(open(os.path.join(path, "FINAL-SUMMARY.json"), encoding="utf-8"))
    return d["agents"]["sayacode"]["trials"]

def main():
    out = {}
    trials = {g: load_group(p) for g, p in GROUPS.items()}
    for g, tr in trials.items():
        rr = [t.get("effective_reward") for t in tr]
        n_pass = sum(1 for r in rr if r == 1.0)
        n_fail = sum(1 for r in rr if r == 0.0)
        n_none = sum(1 for r in rr if r is None)
        patches = [t.get("patch") for t in tr]
        out[g] = {
            "trials": len(tr),
            "reward_dist": {"1.0": n_pass, "0.0": n_fail, "None": n_none},
            "planned": {"num": n_pass, "den": len(tr), "rate": n_pass / len(tr)},
            "observed": {"num": n_pass, "den": n_pass + n_fail,
                         "rate": n_pass / (n_pass + n_fail) if n_pass + n_fail else None},
            "empty_patch": {"zero": sum(1 for p in patches if p == 0),
                            "none": sum(1 for p in patches if p is None)},
        }
    A = { (t["task_id"], t["repeat"]): t for t in trials["impact-350"] }
    B = { (t["task_id"], t["repeat"]): t for t in trials["v2v-main"] }
    keys = sorted(set(A) & set(B))
    both = only_a = only_b = both_fail = 0
    pairs_a = 0
    for k in keys:
        a = A[k].get("effective_reward"); b = B[k].get("effective_reward")
        if a is None or b is None:
            continue
        pairs_a += 1
        if a == 1.0 and b == 1.0: both += 1
        elif a == 1.0 and b == 0.0: only_a += 1
        elif a == 0.0 and b == 1.0: only_b += 1
        else: both_fail += 1
    out["pairing"] = {"keys": len(keys), "complete_pairs": pairs_a,
                      "both_pass": both, "only_impact": only_a, "only_control": only_b,
                      "both_fail": both_fail, "mcnemar_p_complete": mcnemar_exact(only_a, only_b)}
    both2 = only_a2 = only_b2 = both_fail2 = 0
    for k in keys:
        a = 1.0 if A[k].get("effective_reward") == 1.0 else 0.0
        b = 1.0 if B[k].get("effective_reward") == 1.0 else 0.0
        if a == 1.0 and b == 1.0: both2 += 1
        elif a == 1.0: only_a2 += 1
        elif b == 1.0: only_b2 += 1
        else: both_fail2 += 1
    out["pairing_none_as_fail"] = {"both_pass": both2, "only_impact": only_a2, "only_control": only_b2,
                                   "both_fail": both_fail2, "mcnemar_p": mcnemar_exact(only_a2, only_b2), "n": len(keys)}
    cov = {}
    for g, tr in trials.items():
        per_trial = []
        per_task = defaultdict(list)
        for t in tr:
            job = os.path.join(GROUPS[g], "sayacode", "jobs", t["job"])
            td = trial_dir(job) if os.path.isdir(job) else None
            mp = os.path.join(td, "agent", "model.patch") if td else None
            gp = os.path.join(TASKS, t["task_id"], "solution", "gold_patch.diff")
            mf = patch_files(mp) if mp and os.path.isfile(mp) else None
            gf = patch_files(gp) if os.path.isfile(gp) else None
            if mf is None or gf is None or not gf:
                per_trial.append(None); continue
            r = len(mf & gf) / len(gf)
            per_trial.append(r); per_task[t["task_id"]].append((r, len(gf)))
        valid = [x for x in per_trial if x is not None]
        task_union = []; ge3 = []
        for tid, vals in per_task.items():
            rs = [v[0] for v in vals]; nf = vals[0][1]
            task_union.append(sum(rs) / len(rs))
            if nf >= 3: ge3.append(sum(rs) / len(rs))
        cov[g] = {"n_trials_with_patch": len(valid), "n_trials_missing": len(per_trial) - len(valid),
                  "trial_mean": sum(valid) / len(valid) if valid else None,
                  "task_mean": sum(task_union) / len(task_union) if task_union else None,
                  "task_mean_gold_ge3": sum(ge3) / len(ge3) if ge3 else None,
                  "n_tasks_gold_ge3": len(ge3)}
    out["coverage"] = cov
    integ = {}
    for g, tr in trials.items():
        miss_patch = miss_audit = errored = 0
        for t in tr:
            job = os.path.join(GROUPS[g], "sayacode", "jobs", t["job"])
            td = trial_dir(job) if os.path.isdir(job) else None
            if td is None or not os.path.isfile(os.path.join(td, "agent", "model.patch")):
                miss_patch += 1
            if td is None or find_audit(td) is None:
                miss_audit += 1
            rj = os.path.join(job, "result.json")
            if os.path.isfile(rj):
                d = json.load(open(rj, encoding="utf-8"))
                if (d.get("stats") or {}).get("n_errored_trials", 0) > 0:
                    errored += 1
            else:
                errored += 1
        integ[g] = {"missing_model_patch": miss_patch, "missing_audit_jsonl": miss_audit,
                    "result_errored": errored, "trials": len(tr)}
    out["integrity"] = integ
    print(json.dumps(out, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
```

运行方式：

```powershell
python C:\sb\tmp\audit-recompute\recompute.py
```

## 6. 一句话

impact-350 planned **24/40 = 60.0%**、v2v-main **23/40 = 57.5%**（两组 None 均为 0，planned=observed）；40 对配对 both 20 / only-impact 4 / only-control 3 / both-fail 13，**McNemar p = 1.0**；文件覆盖率 impact **0.6274**（gold≥3 题 **0.5698**）、v2v **0.5481**（**0.4974**）；0 字节 patch 4 / 5 个；完整性仅 v2v 有 1 个缺 audit、3 个 `n_errored_trials>0`。匹配必须用「commit 前缀」而非固定 12 位（每组 20/40 的 job 前缀 <12 位），配对必须用 `(task_id, repeat)` 双键（单用 task_id 会把 40 变 20）。
