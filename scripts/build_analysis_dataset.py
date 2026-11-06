"""把四组 trial 的 verifier 明细、用量、patch、时长汇成一个分析用数据集。

数据源：
  v2-325/{agent}/jobs/*/<trial>/verifier/{output.json,reward.txt}
  v2-325/{agent}/verify/jobs/*/<trial>/verifier/{output.json,reward.txt}
  v4-327/sayacode/{jobs,verify/jobs}/...

trial 目录按内容识别（含 result.json / agent / verifier），不依赖 ``instance_`` 前缀。

输出：C:\\sb\\analysis\\dataset.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sayacode_bench import trialdir

V2 = Path(r"C:\sb\hard\v2-325")
V4 = Path(r"C:\sb\hard\v4-327")
OUT = Path(r"C:\sb\analysis\dataset.json")

AGENTS_V2 = ["sayacode", "mini-swe", "claude-code", "opencode"]


def job_meta(job: Path) -> tuple[str, int] | None:
    """从 job 目录名解析 (task_id, repeat)。"""
    name = job.name
    m = re.search(r"-r([12])$", name)
    if not m:
        return None
    repeat = int(m.group(1))
    stem = name[: m.start()]
    for prefix in ("verify-",):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
    # 去掉 agent 前缀
    for a in ("sayacode", "mini-swe", "claude-code", "opencode"):
        if stem.startswith(a + "-"):
            stem = stem[len(a) + 1 :]
            break
    return stem, repeat


def read_verifier(inner: Path) -> tuple[int, int, int, int, int] | None:
    """返回 (required, passed, f2p_total, f2p_passed, p2p_total)。"""
    out_json = inner / "verifier" / "output.json"
    if not out_json.is_file():
        return None
    try:
        data = json.loads(out_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tests = data.get("tests") or []
    if not isinstance(tests, list):
        return None
    required = len(tests)
    passed = sum(1 for t in tests if str(t.get("status", "")).upper() == "PASSED")

    cfg_path = None
    for cand in inner.rglob("config.json"):
        if cand.parent.name == "tests":
            cfg_path = cand
            break
    f2p_total = f2p_passed = p2p_total = 0
    if cfg_path:
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            f2p = cfg.get("fail_to_pass") or []
            p2p = cfg.get("pass_to_pass") or []
            if isinstance(f2p, str):
                f2p = json.loads(f2p.replace("'", '"'))
            if isinstance(p2p, str):
                p2p = json.loads(p2p.replace("'", '"'))
            f2p_total, p2p_total = len(f2p), len(p2p)
        except (OSError, ValueError):
            pass
    return required, passed, f2p_total, f2p_passed, p2p_total


def read_usage(inner: Path, agent: str) -> dict:
    for cand in inner.rglob(f"{agent}/result.json"):
        try:
            d = json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        u = d.get("usage") or {}
        if u:
            return {
                "input_tokens": u.get("input_tokens"),
                "output_tokens": u.get("output_tokens"),
                "model_calls": u.get("model_calls"),
                "model_failures": d.get("model_failures"),
            }
    return {}


def read_duration(inner: Path) -> dict:
    f = inner / "result.json"
    if not f.is_file():
        return {}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    from datetime import datetime

    def parse(x):
        if not x:
            return None
        try:
            return datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        except ValueError:
            return None

    a, b = parse(d.get("started_at")), parse(d.get("finished_at"))
    total = (b - a).total_seconds() / 60 if a and b else None
    ex = d.get("agent_execution") or {}
    x, y = parse(ex.get("started_at")), parse(ex.get("finished_at"))
    exe = (y - x).total_seconds() / 60 if x and y else None
    return {"minutes": total, "exec_minutes": exe}


def patch_info(inner: Path) -> dict:
    p = None
    for cand in inner.rglob("model.patch"):
        p = cand
        break
    if not p or not p.is_file():
        return {"patch_bytes": None, "patch_files": None, "touches_snap": None}
    text = p.read_text(encoding="utf-8", errors="replace")
    size = len(text)
    files = [
        ln[4:].strip()[2:]
        for ln in text.splitlines()
        if ln.startswith("+++ ") and "/dev/null" not in ln
    ]
    return {
        "patch_bytes": size,
        "patch_files": len(files),
        "touches_snap": any(".snap" in f for f in files),
    }


def collect(root: Path, agent: str, tag: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for base in (root / agent / "jobs", root / agent / "verify" / "jobs"):
        if not base.is_dir():
            continue
        for job in sorted(base.iterdir()):
            if not job.is_dir():
                continue
            meta = job_meta(job)
            if meta is None:
                continue
            task, repeat = meta
            key = (task, repeat)
            if key in seen:
                continue
            inner = trialdir.find_trial_dir(job)
            if inner is None:
                continue
            verd = read_verifier(inner)
            if verd is None:
                continue
            seen.add(key)
            required, passed = verd[0], verd[1]
            row = {
                "agent": agent,
                "tag": tag,
                "task": task,
                "repeat": repeat,
                "required": required,
                "passed": passed,
                "partial": passed / required if required else None,
                "f2p_total": verd[2],
                "p2p_total": verd[4],
            }
            row.update(read_usage(inner, agent))
            row.update(read_duration(inner))
            row.update(patch_info(inner))
            rows.append(row)
    return rows


def main() -> None:
    rows: list[dict] = []
    for a in AGENTS_V2:
        rows += collect(V2, a, "3.2.5" if a == "sayacode" else "baseline")
    rows += collect(V4, "sayacode", "3.2.7")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    from collections import Counter

    c = Counter((r["agent"], r["tag"]) for r in rows)
    print(f"共 {len(rows)} 条 trial → {OUT}")
    for k, v in sorted(c.items()):
        print(f"  {k[0]:12} {k[1]:9} {v}")
    no_partial = sum(1 for r in rows if r["partial"] is None)
    print("缺部分得分:", no_partial)


if __name__ == "__main__":
    main()
