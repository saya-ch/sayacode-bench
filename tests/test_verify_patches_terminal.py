"""空 patch 终态与断点续跑判据：不再永久 pending。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import verify_patches


def make_inner(root: Path, job: str, *, patch: bytes | None, reward: float | None = None) -> Path:
    inner = root / "jobs" / job / "instance_task__x1"
    (inner).mkdir(parents=True)
    (inner / "result.json").write_text(
        json.dumps({"task_name": "swebench-pro/instance_task__x1"}), encoding="utf-8"
    )
    if patch is not None:
        (inner / "agent").mkdir()
        (inner / "agent" / "model.patch").write_bytes(patch)
    if reward is not None:
        (inner / "verifier").mkdir(exist_ok=True)
        (inner / "verifier" / "reward.txt").write_text(str(reward), encoding="utf-8")
    return inner


def test_empty_patch_becomes_terminal_and_second_run_is_not_pending(tmp_path: Path) -> None:
    inner = make_inner(tmp_path, "job-empty", patch=b"")
    pending = verify_patches.collect_pending(tmp_path / "jobs")
    assert len(pending) == 1
    assert pending[0][2] == 0

    terminal = verify_patches.record_empty_patch(inner, 0)
    payload = json.loads(terminal.read_text(encoding="utf-8"))
    assert payload["status"] == "skipped_empty_patch"
    assert payload["reward"] == 0.0

    # 第二次运行：空 patch 的 job 不再进入 pending
    assert verify_patches.collect_pending(tmp_path / "jobs") == []


def test_reward_and_pending_detection(tmp_path: Path) -> None:
    make_inner(tmp_path, "job-with-reward", patch=b"abc", reward=1.0)
    make_inner(tmp_path, "job-needs-verify", patch=b"abc")
    make_inner(tmp_path, "job-no-patch", patch=None)
    pending = verify_patches.collect_pending(tmp_path / "jobs")
    assert [entry[0] for entry in pending] == ["job-needs-verify"]
