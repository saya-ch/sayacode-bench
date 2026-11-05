"""strict_compare 三口径与 formal.py 缺失口径的一致性测试（合成目录，不是模型成绩）。

重点锁住一个真实发生过的回归：**只看 `reward.txt` 会把「显式终态（空 patch 跳过）」
误判为 missing**，从而让同一批数据在 `strict_compare.py` 与 `final_summary.py` 之间
给出不同的 observed / missing。v2/v3 期间因此出现过「Codex 缺失 0 vs 1」「mini-swe
缺失 1 vs 2」的互相矛盾。
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import strict_compare as module


def make_job(
    root: Path,
    name: str,
    *,
    reward: str | None = None,
    terminal: str | None = None,
    patch_files: tuple[str, ...] | None = None,
) -> Path:
    job = root / name
    inner = job / "trial"
    (inner / "verifier").mkdir(parents=True)
    (inner / "agent").mkdir(parents=True)
    if reward is not None:
        (inner / "verifier" / "reward.txt").write_text(reward, encoding="utf-8")
    if terminal is not None:
        (inner / "verifier" / "terminal.json").write_text(
            json.dumps({"status": terminal}), encoding="utf-8"
        )
    if patch_files is not None:
        lines = ["diff --git a/x b/x"]
        for name_ in patch_files:
            lines.append(f"+++ b/{name_}")
            lines.append("@@ -1 +1 @@")
            lines.append("-old")
            lines.append("+new")
        (inner / "agent" / "model.patch").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return job


def test_terminal_only_trial_counts_as_observed_not_missing(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    make_job(jobs, "t-pass", reward="1", patch_files=("src/app.py",))
    make_job(jobs, "t-empty", terminal="skipped_empty_patch")
    make_job(jobs, "t-none")

    row = module.analyse(tmp_path, planned_total=3)

    assert row["observed"] == 2, "有显式终态的 trial 必须计入 observed（按 0 分），不能算 missing"
    assert row["missing"] == 1
    assert row["passes"] == 1
    assert row["terminal_only_trials"] == ["t-empty"]
    assert row["pass_rate_observed"] == 0.5


def test_snap_patch_is_excluded_from_strict_only(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    make_job(jobs, "t-src", reward="1", patch_files=("src/app.py",))
    make_job(
        jobs,
        "t-snap",
        reward="1",
        patch_files=("src/view/__snapshots__/view-test.tsx.snap",),
    )

    row = module.analyse(tmp_path, planned_total=2)

    assert row["passes"] == 2
    assert row["snap_passes"] == 1
    assert row["snap_trial_keys"] == ["t-snap"]
    assert row["strict_passes"] == 1, "改 .snap 的通过不计入 strict"
    assert row["pass_rate_planned"] == 1.0
    assert row["strict_rate_planned"] == 0.5


def test_verify_phase_takes_over_when_native_has_no_reward(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    make_job(jobs, "t-x", patch_files=("src/app.py",))
    verify = tmp_path / "verify" / "jobs"
    make_job(verify, "verify-t-x", reward="1")

    row = module.analyse(tmp_path, planned_total=1)

    assert row["observed"] == 1
    assert row["passes"] == 1
    assert row["missing"] == 0
    assert row["strict_passes"] == 1


def test_missing_equals_planned_minus_observed(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    make_job(jobs, "t-ok", reward="1", patch_files=("src/a.py",))
    make_job(jobs, "t-fail", reward="0", patch_files=("src/a.py",))
    make_job(jobs, "t-gone")

    row = module.analyse(tmp_path, planned_total=5)

    assert row["observed"] == 2
    assert row["missing"] == 3
    assert row["passes"] == 1


def test_patch_name_parsing_handles_dev_null(tmp_path: Path) -> None:
    patch = tmp_path / "p.patch"
    patch.write_text(
        "\n".join(
            [
                "diff --git a/old.py b/old.py",
                "--- a/old.py",
                "+++ /dev/null",
                "+++ b/new/__snapshots__/a.snap",
            ]
        ),
        encoding="utf-8",
    )

    files = module._patch_files(patch)

    assert files == ["new/__snapshots__/a.snap"]
