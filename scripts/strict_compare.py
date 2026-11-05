"""严格口径三/四组对比：planned / observed / strict（扣改 .snap 的通过）。

用途：v2 主表只报 planned；但 known-passing 里存在「靠改 `__snapshots__/*.snap`
通过」的 trial，而 verifier 不重置快照目录（`tests/test.sh` 的 DATA_DIRS 包含它），
这类 pass 属于评测器漏洞而非能力，必须单独扣掉后再比较。

strict 口径与 planned 的差异只有一项判定：某个 pass trial 的 patch 是否修改了
`*.snap` 文件；其余（缺失、超时、真实失败）一律沿用 planned 计数。

用法::

    uv run --no-sync python scripts/strict_compare.py --root C:\\sb\\hard\\v2-325
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

SNAP_RE = re.compile(r"(__snapshots__/.*\.snap$|\.snap$)", re.IGNORECASE)


def _patch_files(path: Path) -> list[str] | None:
    """返回 patch 里新增/修改的文件列表；找不到 patch 时返回 None。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith("+++ "):
            name = line[4:].strip()
            if name.startswith("b/"):
                name = name[2:]
            if name != "/dev/null":
                out.append(name)
    return out


def _find_patch(job: Path) -> Path | None:
    direct = list(job.rglob("model.patch"))
    if direct:
        return direct[0]
    # verify 阶段把 patch 放在 replay.json 里指向 native 的 model.patch
    for replay in job.rglob("replay.json"):
        try:
            payload = json.loads(replay.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        candidate = payload.get("patch")
        if candidate and os.path.isfile(candidate):
            return Path(candidate)
    return None


def _read_terminal(job: Path) -> str | None:
    """读显式终态（`verifier/terminal.json` 的 status），与 formal.py 同源。

    空 patch 跳过（`skipped_empty_patch`）这类终态在协议里按「观测到 0 分」计入，
    不算 missing；只看 reward.txt 会把它们误判成缺失（v2/v3 期间实际发生过）。
    """
    for terminal in job.rglob("terminal.json"):
        try:
            payload = json.loads(terminal.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        status = payload.get("status") if isinstance(payload, dict) else None
        if status:
            return str(status)
    return None


def _collect(agent_dir: Path) -> tuple[dict[str, dict], int]:
    """收集一个 agent 的 trial：native 优先，native 无 reward 时由 verify 接管。"""
    trials: dict[str, dict] = {}
    for kind, base in (("native", agent_dir / "jobs"), ("verify", agent_dir / "verify" / "jobs")):
        if not base.is_dir():
            continue
        for job in sorted(base.iterdir()):
            if not job.is_dir():
                continue
            key = job.name[7:] if kind == "verify" and job.name.startswith("verify-") else job.name
            reward_files = list(job.rglob("reward.txt"))
            reward = None
            if reward_files:
                try:
                    reward = reward_files[0].read_text(encoding="utf-8").strip()
                except OSError:
                    reward = None
            terminal = _read_terminal(job)
            if kind == "native":
                trials[key] = {"job": job, "reward": reward, "terminal": terminal, "kind": kind}
                continue
            existing = trials.get(key)
            if existing is None:
                trials[key] = {"job": job, "reward": reward, "terminal": terminal, "kind": kind}
            elif existing["reward"] is None and reward is not None:
                # native 无 reward 时由 verify 接管（与 formal.py 的合并口径一致）；
                # patch 仍取 native job（verify 的 replay.json 指向它）。
                existing["reward"] = reward
                existing["terminal"] = terminal
                existing["kind"] = "verify"
            elif existing["terminal"] is None and terminal is not None:
                existing["terminal"] = terminal
    planned = len(trials)
    return trials, planned


def analyse(agent_dir: Path, planned_total: int) -> dict:
    trials, planned = _collect(agent_dir)
    observed = 0
    passes = 0
    strict = 0
    snap_passes: list[str] = []
    missing_passes = 0
    terminal_only: list[str] = []
    for key, info in sorted(trials.items()):
        reward = info["reward"]
        # 与 formal.py 的 Trial.observed 对齐：有 reward，或有显式终态（按 0 分计入观测）。
        if reward is None and info.get("terminal") is None:
            continue
        observed += 1
        if reward is None:
            terminal_only.append(key)
            continue
        if reward not in ("1", "1.0"):
            continue
        passes += 1
        patch = _find_patch(info["job"])
        if patch is None:
            missing_passes += 1
            strict += 1  # 找不到 patch 时保守计入通过（无可判定证据）
            continue
        files = _patch_files(patch) or []
        if any(SNAP_RE.search(name) for name in files):
            snap_passes.append(key)
        else:
            strict += 1
    return {
        "planned": planned_total,
        "observed": observed,
        "passes": passes,
        "strict_passes": strict,
        "snap_passes": len(snap_passes),
        "missing": planned_total - observed,
        "terminal_only_trials": terminal_only,
        "snap_trial_keys": snap_passes,
        "pass_rate_planned": passes / planned_total if planned_total else 0.0,
        "pass_rate_observed": passes / observed if observed else 0.0,
        "strict_rate_planned": strict / planned_total if planned_total else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="结果根目录（含各 agent 子目录）")
    parser.add_argument("--agents", nargs="*", default=None)
    parser.add_argument("--planned", type=int, default=80, help="冻结题集 × 重复数的计划分母")
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()

    root = Path(args.root)
    agents = args.agents or sorted(p.name for p in root.iterdir() if p.is_dir())
    report: dict[str, dict] = {}
    for name in agents:
        agent_dir = root / name
        if not (agent_dir / "jobs").is_dir():
            continue
        report[name] = analyse(agent_dir, args.planned)

    print(f"{'agent':14}{'planned':>9}{'observed':>10}{'pass':>7}{'snap':>6}{'strict':>8}"
          f"{'planned%':>11}{'observed%':>11}{'strict%':>10}{'missing':>9}")
    for name, row in report.items():
        print(
            f"{name:14}{row['planned']:>9}{row['observed']:>10}{row['passes']:>7}"
            f"{row['snap_passes']:>6}{row['strict_passes']:>8}"
            f"{row['pass_rate_planned']*100:>10.1f}%{row['pass_rate_observed']*100:>10.1f}%"
            f"{row['strict_rate_planned']*100:>9.1f}%{row['missing']:>9}"
        )
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n明细已写 {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
