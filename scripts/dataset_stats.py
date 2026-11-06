"""题库统计（DATASET-CARD 的唯一可复现来源）。

用法：
  python scripts/dataset_stats.py
  python scripts/dataset_stats.py --json C:\\sb\\tmp\\explore\\m5\\stats.json

所有指标均为「参数化多口径」，不挑单一数字：
  - 饱和 S1a/S1b：5 组 / 4 组（不含 3.2.7）下「所有组题级 partial == 1.0」；
    S2：题级均值 >= 0.995（health.md 的 SATURATED）；S3：所有组 >= 0.99。
  - 区分度：题级「组均值」pstdev（阈值 0.02/0.03/0.05）；trial 级 pstdev（含两 repeat，阈值 0.02）。
  - broken：同一测试在 >=2 个不同 agent 中各自稳定失败 >=2 次（health.md 判据）；
    env_impossible：题级 0/1 通过率 == 0（DEEP-ANALYSIS 的「环境性不可过」口径）。
  - 难度：gold_patch.diff 与 model.patch 的 files / lines(additions+deletions)，
    可切换「含/不含测试与 CI 文件」；agent 侧分「全部 agent」与「仅 SAYACODE」。
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

DEFAULT_DATASET = r"C:\sb\analysis\dataset.json"
DEFAULT_ROOTS = [r"C:\sb\hard\v2-325", r"C:\sb\hard\v4-327"]
DEFAULT_TASKS = r"C:\sb\tmp\hard\cache\swe-bench-pro-v2-66f92766bba642462d4bbe5479e83f91f9211862\v2\tasks"
DEFAULT_SAMPLE = r"C:\develop\sayacode-bench\studies\sample-40-final.json"
DEFAULT_GOLDCHECK = r"C:\sb\hard\gold-check\gold-summary.json"
DEFAULT_SWEEVO = r"C:\sb\newset\swe-evo\tasks"

TEST_RE = re.compile(r"(^|/)(test|tests|__tests__|__snapshots__|spec|specs|testing|testdata|fixtures|ci|\.github)(/|$)|(-test\.|_test\.|\.test\.|\.spec\.|\.snap$)", re.I)
ALL_KEYS = [("sayacode", "3.2.5"), ("sayacode", "3.2.7"), ("mini-swe", "baseline"),
            ("claude-code", "baseline"), ("opencode", "baseline")]
KEYS_4 = [k for k in ALL_KEYS if k != ("sayacode", "3.2.7")]


def is_test_or_ci(p: str) -> bool:
    return bool(TEST_RE.search(p))


def inner_any(jp: Path):
    try:
        for x in jp.iterdir():
            if x.is_dir() and (x / "result.json").is_file():
                return x
    except OSError:
        pass
    return None


def diff_stats(path: Path, include_tests=True):
    if not path.is_file():
        return None
    files = set()
    adds = dels = 0
    cur = None
    inh = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:].strip()
            if include_tests or not is_test_or_ci(cur):
                files.add(cur)
        elif line.startswith("@@"):
            inh = True
        elif inh and cur and (include_tests or not is_test_or_ci(cur)):
            if line.startswith("+") and not line.startswith("+++"):
                adds += 1
            elif line.startswith("-") and not line.startswith("---"):
                dels += 1
        elif line.startswith("diff --git"):
            inh = False
    return {"files": len(files), "adds": adds, "dels": dels, "lines": adds + dels}


def med(vals):
    if not vals:
        return {"n": 0, "median": None, "mean": None, "max": None}
    return {"n": len(vals), "median": statistics.median(vals),
            "mean": round(statistics.mean(vals), 1), "max": max(vals)}


def collect_failures(roots):
    out = defaultdict(lambda: defaultdict(list))
    counts = defaultdict(list)
    seen = set()
    for root in roots:
        rp = Path(root)
        if not rp.is_dir():
            continue
        for agent_dir in rp.iterdir():
            if not agent_dir.is_dir():
                continue
            agent = agent_dir.name
            if agent not in ("sayacode", "mini-swe", "claude-code", "opencode"):
                continue
            for base in (agent_dir / "jobs", agent_dir / "verify" / "jobs"):
                if not base.is_dir():
                    continue
                for job in sorted(base.iterdir()):
                    m = re.search(r"-r([12])$", job.name)
                    if not m:
                        continue
                    stem = job.name[: m.start()]
                    if stem.startswith("verify-"):
                        stem = stem[len("verify-"):]
                    for a in ("sayacode", "mini-swe", "claude-code", "opencode"):
                        if stem.startswith(a + "-"):
                            stem = stem[len(a) + 1:]
                            break
                    key = (agent, stem[:34], int(m.group(1)))
                    if key in seen:
                        continue
                    inner = inner_any(job)
                    if inner is None:
                        continue
                    f = inner / "verifier" / "output.json"
                    if not f.is_file():
                        continue
                    try:
                        tests = json.loads(f.read_text(encoding="utf-8")).get("tests") or []
                    except (OSError, ValueError):
                        continue
                    seen.add(key)
                    nf = sum(1 for t in tests if str(t.get("status", "")).upper() != "PASSED")
                    if nf < len(tests):
                        counts[stem[:34]].append(nf)
                    out[stem[:34]][agent].append({str(t.get("name")) for t in tests
                                                  if str(t.get("status", "")).upper() != "PASSED"})
    return out, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=DEFAULT_DATASET)
    ap.add_argument("--roots", nargs="*", default=DEFAULT_ROOTS)
    ap.add_argument("--tasks", default=DEFAULT_TASKS)
    ap.add_argument("--sample", default=DEFAULT_SAMPLE)
    ap.add_argument("--goldcheck", default=DEFAULT_GOLDCHECK)
    ap.add_argument("--sweevo", default=DEFAULT_SWEEVO)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    rows = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    sample = json.loads(Path(args.sample).read_text(encoding="utf-8"))
    sample_ids = [t["task_id"] for t in sample["tasks"]]
    per = defaultdict(list)
    for r in rows:
        if r.get("partial") is not None:
            per[r["task"]].append(r)

    def groups(task, keys):
        by = defaultdict(list)
        for r in per[task]:
            if (r["agent"], r["tag"]) in keys:
                by[(r["agent"], r["tag"])].append(r["partial"])
        return by

    def sat(keys, pred):
        n = 0
        for t in per:
            by = groups(t, keys)
            if len(by) < 3:
                continue
            gm = [statistics.mean(v) for v in by.values()]
            if pred(gm):
                n += 1
        return n

    saturation = {
        "S1a_5grp_all_eq_1.0": sat(ALL_KEYS, lambda gm: all(x >= 0.9995 for x in gm)),
        "S1b_4grp_no327_all_eq_1.0": sat(KEYS_4, lambda gm: all(x >= 0.9995 for x in gm)),
        "S2_5grp_task_mean_ge_0.995": sat(ALL_KEYS, lambda gm: sum(gm) / len(gm) >= 0.995),
        "S3_5grp_all_ge_0.99": sat(ALL_KEYS, lambda gm: all(x >= 0.99 for x in gm)),
        "S3b_4grp_all_ge_0.99": sat(KEYS_4, lambda gm: all(x >= 0.99 for x in gm)),
    }

    def disc(keys, mode):
        n = 0
        for t in per:
            by = groups(t, keys)
            if len(by) < 3:
                continue
            if mode == "trial":
                vals = [x for v in by.values() for x in v]
                sd = statistics.pstdev(vals) if len(vals) >= 2 else 0.0
            else:
                gm = [statistics.mean(v) for v in by.values()]
                sd = statistics.pstdev(gm) if len(gm) >= 2 else 0.0
            if sd >= 0.02:
                n += 1
        return n

    discrimination = {
        "task_mean_sd_ge_0.02_5grp": disc(ALL_KEYS, "group"),
        "trial_sd_ge_0.02_5grp": disc(ALL_KEYS, "trial"),
        "task_mean_sd_ge_0.03_5grp": sum(
            1 for t in per if len(groups(t, ALL_KEYS)) >= 3 and
            statistics.pstdev([statistics.mean(v) for v in groups(t, ALL_KEYS).values()]) >= 0.03),
        "trial_sd_ge_0.05_5grp": sum(
            1 for t in per if len(groups(t, ALL_KEYS)) >= 3 and
            statistics.pstdev([x for v in groups(t, ALL_KEYS).values() for x in v]) >= 0.05),
    }

    fails, fail_counts = collect_failures(args.roots)
    broken, chronic = [], {}
    for t in per:
        ag = fails.get(t) or next((v for k, v in fails.items() if k[:30] == t[:30]), {})
        hit = defaultdict(set)
        for agent, sets in ag.items():
            cnt = defaultdict(int)
            for s in sets:
                for test in s:
                    cnt[test] += 1
            for test, c in cnt.items():
                if c >= 2:
                    hit[test].add(agent)
        ch = [x for x, ags in hit.items() if len(ags) >= 2]
        if ch:
            broken.append(t)
            chronic[t] = ch[:2]
    # DEEP-ANALYSIS 的「环境性不可过」：每 trial 恒只挂 1 个测试（min==max==1）
    env_impossible = [t for t, v in fail_counts.items() if v and min(v) == 1 and max(v) == 1]

    # 难度
    gold, agent_all, agent_sayacode = [], [], []
    for tid in sample_ids:
        gp = Path(args.tasks) / tid / "solution" / "gold_patch.diff"
        d = diff_stats(gp, True)
        if d:
            gold.append(d)
    for root in args.roots:
        rp = Path(root)
        if not rp.is_dir():
            continue
        for ad in rp.iterdir():
            if not ad.is_dir():
                continue
            for base in (ad / "jobs", ad / "verify" / "jobs"):
                if not base.is_dir():
                    continue
                for job in base.iterdir():
                    inner = inner_any(job)
                    if inner is None:
                        continue
                    mp = inner / "agent" / "model.patch"
                    d = diff_stats(mp, True)
                    if not d:
                        continue
                    agent_all.append(d)
                    if ad.name == "sayacode":
                        agent_sayacode.append(d)

    # SWE-EVO
    sweevo = {"tasks": 0, "repos": {}, "gold_incl": {}, "gold_excl": {}}
    se = Path(args.sweevo)
    if se.is_dir():
        ts = sorted([d for d in se.iterdir() if d.is_dir()])
        sweevo["tasks"] = len(ts)
        repos = defaultdict(int)
        for t in ts:
            repos[t.name.split("-")[1] if "-" in t.name else t.name] += 1
        sweevo["repos"] = dict(repos)
        inc, exc = [], []
        for t in ts:
            gp = t / "solution" / "gold_patch.diff"
            d = diff_stats(gp, True)
            if d:
                inc.append(d)
            d2 = diff_stats(gp, False)
            if d2:
                exc.append(d2)
        sweevo["gold_incl"] = {"files": med([d["files"] for d in inc]), "lines": med([d["lines"] for d in inc])}
        sweevo["gold_excl"] = {"files": med([d["files"] for d in exc]), "lines": med([d["lines"] for d in exc])}

    out = {
        "dataset_rows": len(rows),
        "tasks_ge3_groups": len(per),
        "saturation": saturation,
        "discrimination": discrimination,
        "broken": {"count": len(broken), "tasks": broken,
                   "chronic_samples": {k: v for k, v in list(chronic.items())[:3]},
                   "env_impossible_count": len(env_impossible),
                   "env_impossible_tasks": env_impossible},
        "difficulty_sample40": {
            "gold_patch": {"files": med([d["files"] for d in gold]),
                           "lines_add_del": med([d["lines"] for d in gold]),
                           "lines_add_only": med([d["adds"] for d in gold])},
            "agent_all": {"files": med([d["files"] for d in agent_all]),
                          "lines_add_del": med([d["lines"] for d in agent_all]), "n": len(agent_all)},
            "agent_sayacode_only": {"files": med([d["files"] for d in agent_sayacode]),
                                    "lines_add_del": med([d["lines"] for d in agent_sayacode]),
                                    "n": len(agent_sayacode)},
        },
        "sweevo48": sweevo,
        "sample_size": len(sample_ids),
    }
    gc = Path(args.goldcheck)
    if gc.is_file():
        g = json.loads(gc.read_text(encoding="utf-8"))
        out["goldcheck"] = {"total": g.get("total"), "good": g.get("good"), "bad": g.get("bad"),
                            "other": len(g.get("other") or []), "bad_jobs": g.get("bad_jobs")}
    text = json.dumps(out, ensure_ascii=False, indent=1)
    print(text)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
