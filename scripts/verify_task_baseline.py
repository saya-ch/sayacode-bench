"""SWE-EVO task 基线验证：不打 agent patch，确认题目有效并按基线修正 p2p。

判定：
  fake        f2p 在基线全部通过 → 题目无效，剔除
  usable      f2p 有失败；p2p 按基线过滤后可用
  broken      镜像不可用 / patch 完全应用不上

对 usable 的题，把「基线就失败的 p2p」从 config.json 剔除（标准 SWE-bench 做法），
否则任何 agent 都不可能通过。

镜像滚动：拉取 → 验证 → 删除。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

TASKS_ROOT = Path(r"C:\sb\newset\swe-evo\tasks")
OUT = Path(r"C:\sb\analysis\swe-evo-baseline.json")
PY = "/opt/miniconda3/envs/testbed/bin/python"


def image_of(task_dir: Path) -> str | None:
    f = task_dir / "environment" / "Dockerfile"
    if not f.is_file():
        return None
    m = re.search(r"^FROM\s+(\S+)", f.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def has_image(image: str) -> bool:
    r = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=60)
    return r.returncode == 0


def pull(image: str) -> bool:
    print(f"  pulling {image} ...", flush=True)
    r = subprocess.run(["docker", "pull", image], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  PULL FAILED: {(r.stderr or '')[-160:]}", flush=True)
    return r.returncode == 0


def run_baseline(task_dir: Path, image: str, timeout: int) -> dict:
    tests = (task_dir / "tests").resolve()
    script = (
        "cd /testbed || exit 2; "
        "git apply --reject --whitespace=nowarn /tests/test_patch.patch >/dev/null 2>&1 || true; "
        "bash /tests/run_script.sh > /tmp/log 2>&1; "
        f"{PY} /tests/parser.py /tmp/log --json 2>&1 | tail -1"
    )
    cmd = ["docker", "run", "--rm", "-v", f"{tests.as_posix()}:/tests", image, "bash", "-c", script]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = r.stdout or ""
        m = re.search(r"__JSON__(\{.*\})", out)
        if not m:
            return {"ok": False, "reason": "no_json", "raw": out[-300:] + (r.stderr or "")[-200:]}
        return {"ok": True, "payload": json.loads(m.group(1))}
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "timeout"}


def sat(node: str, statuses: dict[str, str]) -> bool:
    if statuses.get(node) == "PASSED":
        return True
    for k, v in statuses.items():
        if v == "PASSED" and (k.startswith(node) or node.startswith(k)):
            return True
    return False


def classify_baseline(
    f2p: list[str], p2p: list[str], statuses: dict[str, str]
) -> dict[str, object]:
    """新题库准入判定（纯函数，便于离线测试三档结论）。

    返回 ``verdict`` / ``reason`` / ``keep_p2p`` / ``f2p_pass`` / ``p2p_pass``。
    - fake：基线跑下来 FAIL_TO_PASS 全部通过（题目本身已修好，不能用来评测）
    - usable：基线 F2P 有失败（题目有效），同时把基线就失败的 P2P 剔除
    - unknown：没有声明 F2P，无法判定
    """
    f2p_pass = sum(1 for t in f2p if sat(t, statuses))
    p2p_pass = sum(1 for t in p2p if sat(t, statuses))
    common = {"f2p_pass": f2p_pass, "p2p_pass": p2p_pass, "keep_p2p": []}
    if f2p and f2p_pass == len(f2p):
        return {**common, "verdict": "fake", "reason": "f2p_all_pass_at_baseline"}
    if f2p_pass < len(f2p):
        keep = [t for t in p2p if sat(t, statuses)]
        return {**common, "verdict": "usable", "reason": "f2p_fails_at_baseline", "keep_p2p": keep}
    return {**common, "verdict": "unknown", "reason": "no_f2p"}


def apply_baseline_filter(task: Path, keep_p2p: list[str]) -> int:
    """把基线就失败的 P2P 从 ``tests/config.json`` 剔除，返回剔除条数。"""
    cfg_path = task / "tests" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    original = len(cfg.get("pass_to_pass", []))
    dropped = original - len(keep_p2p)
    cfg["pass_to_pass"] = keep_p2p
    cfg["baseline_filtered_p2p"] = dropped
    cfg_path.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return dropped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--keep-images", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--skip-epoch", action="store_true", default=True)
    args = ap.parse_args()

    tasks = sorted(p for p in TASKS_ROOT.iterdir() if p.is_dir())
    if args.only:
        tasks = [t for t in tasks if any(s in t.name for s in args.only)]
    tasks = tasks[: args.limit]

    results = []
    for i, task in enumerate(tasks, 1):
        image = image_of(task)
        print(f"\n[{i}/{len(tasks)}] {task.name}", flush=True)
        if not image:
            results.append({"task": task.name, "verdict": "broken", "reason": "no_image"})
            continue
        if args.skip_epoch and "epoch-research" in image:
            results.append(
                {"task": task.name, "verdict": "broken", "reason": "epoch_image_version_mismatch"}
            )
            print("  skip: epoch-research image", flush=True)
            continue
        if not has_image(image) and not pull(image):
            results.append({"task": task.name, "verdict": "broken", "reason": "pull_failed"})
            continue

        res = run_baseline(task, image, args.timeout)
        if not res["ok"]:
            results.append({"task": task.name, "verdict": "broken", "reason": res["reason"]})
            print(f"  -> broken ({res['reason']})", flush=True)
        else:
            payload = res["payload"]
            f2p, p2p = payload["f2p"], payload["p2p"]
            baseline = classify_baseline(f2p, p2p, payload["statuses"])
            verdict, reason = baseline["verdict"], baseline["reason"]
            f2p_pass, p2p_pass = baseline["f2p_pass"], baseline["p2p_pass"]
            if verdict == "fake":
                print(f"  -> FAKE (f2p {f2p_pass}/{len(f2p)} passed at baseline)", flush=True)
            elif verdict == "usable":
                dropped = apply_baseline_filter(task, baseline["keep_p2p"])
                print(
                    f"  -> USABLE (f2p {f2p_pass}/{len(f2p)}, p2p {p2p_pass}/{len(p2p)}; "
                    f"dropped {dropped} failing p2p)",
                    flush=True,
                )
            else:
                print("  -> unknown (no f2p)", flush=True)

            results.append(
                {
                    "task": task.name,
                    "verdict": verdict,
                    "reason": reason,
                    "f2p": [f2p_pass, len(f2p)],
                    "p2p": [p2p_pass, len(p2p)],
                    "image": image,
                }
            )

        if not args.keep_images:
            subprocess.run(["docker", "rmi", image], capture_output=True)
            print("  image removed", flush=True)

        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    c = Counter(r["verdict"] for r in results)
    print("\n=== 汇总 ===")
    for k, v in c.most_common():
        print(f"  {k}: {v}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
