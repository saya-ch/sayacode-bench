"""历史 strict 口径核对：planned / observed / strict（扣掉 patch 改 ``*.snap`` 的通过）。

> ⚠️ **strict 口径已于 2026-11-07 废除**，见 ``docs/RESULTS-LEDGER.md`` §1。
> 废除理由：``strict`` 的前提「verifier 不重置 ``__snapshots__``」被证伪 —— 642/642 个
> ``tests/test.sh`` 在判分前对快照执行 ``git checkout HEAD``，agent 对快照的修改已被还原。
> **任何 strict 数字都不得引用**；本脚本仅保留为历史批次的核对工具（输出也不得进报告）。
>
> 方向性修复（2026-11-07）：旧实现在「pass 但找不到 patch」时把 trial 计入 strict，
> 与「扣掉不可判定项」的严格方向相反，会**高估** strict。现在找不到 patch 一律不计入
> strict，只记入 ``missing_patches``。reward 解析也从只认 ``"1"/"1.0"`` 改为 ``float()``
> 容错（``"1\n"``、``"1.00"`` 都能识别）。

strict 与 planned 的差异只有一项判定：某个 pass trial 的 patch 是否修改了 ``*.snap``
文件；其余（缺失、超时、真实失败）一律沿用 planned 计数。

用法::

    uv run --no-sync python scripts/strict_compare.py --root C:\\sb\\hard\\v2-325
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from sayacode_bench import trialdir

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
    patches = trialdir.find_trial_files(job, *trialdir.PATCH_PARTS)
    if patches:
        return patches[0]
    # verify 阶段把 patch 放在 replay.json 里指向 native 的 model.patch
    for replay in trialdir.find_trial_files(job, "replay.json"):
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
    for terminal in trialdir.find_trial_files(job, *trialdir.TERMINAL_PARTS):
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
            reward_file = trialdir.find_trial_file(job, *trialdir.REWARD_PARTS)
            reward = None
            if reward_file is not None:
                try:
                    reward = reward_file.read_text(encoding="utf-8").strip()
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
    missing_patches = 0
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
        # reward.txt 可能是 "1\n" / "1.0\n" / "1.00"：用 float 容错，不再只认字符串。
        try:
            value = float(str(reward).strip())
        except (TypeError, ValueError):
            continue
        if value != 1.0:
            continue
        passes += 1
        patch = _find_patch(info["job"])
        if patch is None:
            # 方向性修复：找不到 patch 时**不得**计入 strict（旧实现 strict += 1 会高估）。
            # 只记录为不可判定，供历史核对时人工查看。
            missing_patches += 1
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
        "missing_patches": missing_patches,
        "missing": planned_total - observed,
        "terminal_only_trials": terminal_only,
        "snap_trial_keys": snap_passes,
        "pass_rate_planned": passes / planned_total if planned_total else 0.0,
        "pass_rate_observed": passes / observed if observed else 0.0,
        "strict_rate_planned": strict / planned_total if planned_total else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "历史 strict 口径核对。strict 已于 2026-11-07 废除（见 docs/RESULTS-LEDGER.md §1）："
            "输出仅供历史核对，不得引用。planned/observed 仍按协议口径计算。"
        )
    )
    parser.add_argument("--root", required=True, help="结果根目录（含各 agent 子目录）")
    parser.add_argument("--agents", nargs="*", default=None)
    parser.add_argument("--planned", type=int, default=80, help="冻结题集 × 重复数的计划分母")
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    root = Path(args.root)
    agents = args.agents or sorted(p.name for p in root.iterdir() if p.is_dir())
    report: dict[str, dict] = {}
    for name in agents:
        agent_dir = root / name
        if not (agent_dir / "jobs").is_dir():
            continue
        report[name] = analyse(agent_dir, args.planned)

    print("⚠️ strict 口径已废除（2026-11-07）：下列 strict 列仅供历史核对，不得引用。")
    print(
        f"{'agent':14}{'planned':>9}{'observed':>10}{'pass':>7}{'snap':>6}{'strict':>8}"
        f"{'planned%':>11}{'observed%':>11}{'strict%':>10}{'missing':>9}"
    )
    for name, row in report.items():
        print(
            f"{name:14}{row['planned']:>9}{row['observed']:>10}{row['passes']:>7}"
            f"{row['snap_passes']:>6}{row['strict_passes']:>8}"
            f"{row['pass_rate_planned'] * 100:>10.1f}%{row['pass_rate_observed'] * 100:>10.1f}%"
            f"{row['strict_rate_planned'] * 100:>9.1f}%{row['missing']:>9}"
        )
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n明细已写 {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
