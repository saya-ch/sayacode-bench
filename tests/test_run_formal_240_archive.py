"""``run_formal_240.archive_incomplete_jobs`` 的回归测试。

存在理由：归档判据曾用 ``job_dir.glob("instance_*/verifier/reward.txt")``，
只认 SWE-bench 的目录命名。接入 SWE-EVO（trial 目录 ``sweevo-...__random``）后
**每个已完成 job 都匹配不上，会被当成「无结果」移进 ``abandoned/``，等于丢数据**
（实测 pilot1 的 10/10 个已完成 job 全部误判）。

2026-11-07 复盘把它列为 P0 存活缺陷 S1
（``docs/review/2026-11-07/R3-infrastructure.md``）。本文件用 SWE-EVO 命名锁住行为。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_formal_240

#: 非 SWE-bench 命名 —— 本测试的全部意义就在这里
SWE_EVO_TRIAL = "sweevo-iterative-dvc-2-21-1-2-21-2__Xk9mQp"


def _job(root: Path, job_name: str, trial_name: str, *, reward=None, terminal=None, patch=None):
    job_dir = root / "jobs" / job_name
    trial = job_dir / trial_name
    (trial / "agent").mkdir(parents=True)
    (trial / "verifier").mkdir(parents=True)
    (trial / "result.json").write_text('{"task_name": "x"}', encoding="utf-8")
    if reward is not None:
        (trial / "verifier" / "reward.txt").write_text(str(reward), encoding="utf-8")
    if terminal is not None:
        (trial / "verifier" / "terminal.json").write_text(json.dumps(terminal), encoding="utf-8")
    if patch is not None:
        (trial / "agent" / "model.patch").write_text(patch, encoding="utf-8")
    return job_dir


def test_completed_swe_evo_job_is_not_archived(tmp_path: Path) -> None:
    """有 reward 的 job 绝不能被归档 —— 这是 S1 的原始症状。"""
    _job(tmp_path, "job-done", SWE_EVO_TRIAL, reward=1.0, patch="--- a\n+++ b\n")
    moved = run_formal_240.archive_incomplete_jobs(tmp_path, "test")
    assert moved == 0
    assert (tmp_path / "jobs" / "job-done").is_dir()
    assert not list(tmp_path.glob("abandoned-*"))


def test_terminal_only_job_is_not_archived(tmp_path: Path) -> None:
    """只有 terminal.json（空 patch 显式终态）也算完成，不能归档。"""
    _job(tmp_path, "job-terminal", SWE_EVO_TRIAL, terminal={"status": "skipped_empty_patch"})
    assert run_formal_240.archive_incomplete_jobs(tmp_path, "test") == 0
    assert (tmp_path / "jobs" / "job-terminal").is_dir()


def test_patch_only_job_is_not_archived(tmp_path: Path) -> None:
    """阶段 1 产物（只有 patch，还没验证）也不能归档。"""
    _job(tmp_path, "job-patch", SWE_EVO_TRIAL, patch="--- a\n+++ b\n")
    assert run_formal_240.archive_incomplete_jobs(tmp_path, "test") == 0
    assert (tmp_path / "jobs" / "job-patch").is_dir()


def test_incomplete_job_is_archived(tmp_path: Path) -> None:
    """完全没有产物的残留 job 才归档（Docker 崩溃场景）。"""
    job_dir = tmp_path / "jobs" / "job-stale"
    (job_dir / SWE_EVO_TRIAL / "agent").mkdir(parents=True)
    moved = run_formal_240.archive_incomplete_jobs(tmp_path, "test")
    assert moved == 1
    assert not job_dir.exists()
    abandoned = list(tmp_path.glob("abandoned-*"))
    assert len(abandoned) == 1
    assert (abandoned[0] / "job-stale").is_dir()


def test_mixed_jobs_only_stale_archived(tmp_path: Path) -> None:
    """混合场景：只归档不完整的，完整的原样保留。"""
    _job(tmp_path, "job-done", SWE_EVO_TRIAL, reward=1.0)
    (tmp_path / "jobs" / "job-stale" / SWE_EVO_TRIAL).mkdir(parents=True)
    assert run_formal_240.archive_incomplete_jobs(tmp_path, "test") == 1
    assert (tmp_path / "jobs" / "job-done").is_dir()
    assert not (tmp_path / "jobs" / "job-stale").exists()


def test_no_jobs_dir_returns_zero(tmp_path: Path) -> None:
    assert run_formal_240.archive_incomplete_jobs(tmp_path, "test") == 0


def test_empty_jobs_dir_returns_zero(tmp_path: Path) -> None:
    (tmp_path / "jobs").mkdir()
    assert run_formal_240.archive_incomplete_jobs(tmp_path, "test") == 0


@pytest.mark.parametrize("trial_name", [SWE_EVO_TRIAL, "instance_psf__requests-2931__abc"])
def test_old_and_new_naming_both_recognised(tmp_path: Path, trial_name: str) -> None:
    """两种题库命名都必须识别为已完成 —— 回归保护。"""
    _job(tmp_path, "job", trial_name, reward=0.0)
    assert run_formal_240.archive_incomplete_jobs(tmp_path, "test") == 0
    assert (tmp_path / "jobs" / "job").is_dir()
