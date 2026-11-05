"""collect_pending 的回归测试：重跑阶段2 不能把已验证的 trial 再次排队。

背景（AGENTS 坑 18 / LESSONS §2.4）：verify 产物在 ``verify/jobs/``，
旧实现只看 stage1 的 ``jobs/``，watchdog 续跑时会重复创建 verify job，
撞 run_official_trial 的「已有记录未收尾」ValueError。
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import verify_patches as module


def _stage1(jobs: Path, name: str, *, reward: str | None = None, terminal: bool = False,
            patch: bool = True) -> Path:
    job = jobs / name
    inner = job / "instance_demo__x1"
    (inner / "agent").mkdir(parents=True)
    if patch:
        (inner / "agent" / "model.patch").write_bytes(b"x" * 128)
    (inner / "result.json").write_text(
        json.dumps({"task_name": f"swebench-pro/{name}"}), encoding="utf-8"
    )
    if reward is not None or terminal:
        (inner / "verifier").mkdir(parents=True, exist_ok=True)
        if reward is not None:
            (inner / "verifier" / "reward.txt").write_text(reward, encoding="utf-8")
        if terminal:
            (inner / "verifier" / "terminal.json").write_text(
                json.dumps({"status": "skipped_empty_patch"}), encoding="utf-8"
            )
    return job


def _verify(jobs: Path, name: str, *, reward: str | None = "1",
            terminal: bool = False) -> Path:
    vjob = jobs.parent / "verify" / "jobs" / f"verify-{name}"
    inner = vjob / "instance_demo__y1"
    (inner / "verifier").mkdir(parents=True)
    if reward is not None:
        (inner / "verifier" / "reward.txt").write_text(reward, encoding="utf-8")
    if terminal:
        (inner / "verifier" / "terminal.json").write_text(
            json.dumps({"status": "skipped_empty_patch"}), encoding="utf-8"
        )
    return vjob


def test_pending_without_any_outcome(tmp_path: Path) -> None:
    jobs = tmp_path / "sayacode" / "jobs"
    _stage1(jobs, "job-a")

    found = module.collect_pending(jobs)

    assert [row[0] for row in found] == ["job-a"]


def test_verify_reward_skips_job(tmp_path: Path) -> None:
    jobs = tmp_path / "sayacode" / "jobs"
    _stage1(jobs, "job-a")
    _verify(jobs, "job-a", reward="1")

    assert module.collect_pending(jobs) == []


def test_verify_terminal_skips_job(tmp_path: Path) -> None:
    jobs = tmp_path / "sayacode" / "jobs"
    _stage1(jobs, "job-a")
    _verify(jobs, "job-a", reward=None, terminal=True)

    assert module.collect_pending(jobs) == []


def test_stage1_own_outcome_still_skips(tmp_path: Path) -> None:
    jobs = tmp_path / "sayacode" / "jobs"
    _stage1(jobs, "job-reward", reward="0")
    _stage1(jobs, "job-terminal", terminal=True)
    _stage1(jobs, "job-nopatch", patch=False)

    assert module.collect_pending(jobs) == []


def test_mixed_batch_only_pending_remains(tmp_path: Path) -> None:
    jobs = tmp_path / "sayacode" / "jobs"
    _stage1(jobs, "job-done")
    _stage1(jobs, "job-todo")
    _verify(jobs, "job-done")

    found = module.collect_pending(jobs)

    assert [row[0] for row in found] == ["job-todo"]


def test_unfinished_verify_job_stays_pending(tmp_path: Path) -> None:
    """verify 目录存在但没有终态 -> 仍算待验证（残留由续跑流程处理）。"""
    jobs = tmp_path / "sayacode" / "jobs"
    _stage1(jobs, "job-a")
    vjob = jobs.parent / "verify" / "jobs" / "verify-job-a"
    (vjob / "instance_demo__y1").mkdir(parents=True)

    assert [row[0] for row in module.collect_pending(jobs)] == ["job-a"]
