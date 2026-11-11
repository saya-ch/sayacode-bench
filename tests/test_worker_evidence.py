"""worker 崩溃留证：ROOTCAUSE #17/#19 的回归测试。

现象：worker exit=2，`result.json` 只有 `{"status":"infrastructure_error",
"error_type":"ValueError"}`，`worker.log` 0 字节，`state_dir/worker-error.txt` 不存在，
两条 trial 因此无法定根因（判 unknown）。

本组测试锁住三条通道：
1. 启动第一步写 `worker-start.txt`（SIGKILL 也能看出进程起来过）；
2. 主流程异常把 traceback 同时写到 stderr 与 `state/worker-error.txt`；
3. 顶层 `BaseException` 兜底同样留证。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from sayacode_bench import worker


def _prepare(tmp_path: Path, *, profile_text: str = "[]") -> dict[str, Path]:
    """构造最小 worker 输入；profile 用 JSON 数组，保证 `_run` 在早期就抛 ValueError。"""
    profile = tmp_path / "profile.json"
    profile.write_text(profile_text, encoding="utf-8")
    variant = tmp_path / "variant.json"
    variant.write_text(json.dumps({"id": "baseline", "team_enabled": True}), encoding="utf-8")
    instruction = tmp_path / "instruction.txt"
    instruction.write_text("do the task", encoding="utf-8")
    return {
        "profile": profile,
        "variant": variant,
        "instruction": instruction,
        "state": tmp_path / "state",
        "logs": tmp_path / "logs",
    }


def _argv(paths: dict[str, Path]) -> list[str]:
    return [
        "worker.py",
        "--profile", str(paths["profile"]),
        "--variant", str(paths["variant"]),
        "--instruction", str(paths["instruction"]),
        "--state", str(paths["state"]),
        "--logs", str(paths["logs"]),
    ]


def test_worker_start_file_records_pid_argv_and_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """启动第一步必须落 worker-start.txt：SIGKILL 之后仍能看出进程起来过。"""
    logs = tmp_path / "logs"
    monkeypatch.setattr(sys, "argv", ["worker.py", "--state", str(tmp_path / "state")])
    worker._record_worker_start(logs)

    start = logs / "worker-start.txt"
    assert start.is_file()
    payload = json.loads(start.read_text(encoding="utf-8"))
    assert payload["pid"] > 0
    assert payload["argv"] == ["worker.py", "--state", str(tmp_path / "state")]
    assert payload["python"] == sys.version
    assert "env" in payload and "HOME" in payload["env"]


def test_main_exception_writes_traceback_to_stderr_and_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """主流程异常：stderr 有 traceback（worker.log 由此非空），state 里也有一份。"""
    paths = _prepare(tmp_path)
    monkeypatch.setattr(sys, "argv", _argv(paths))

    assert worker.main() == 2

    captured = capsys.readouterr()
    assert "Traceback (most recent call last)" in captured.err
    assert "stage=main" in captured.err

    error_file = paths["state"] / "worker-error.txt"
    assert error_file.is_file()
    body = error_file.read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in body
    assert "stage=main" in body

    # 原有契约不变：result.json 仍只暴露类型名，不泄露正文。
    result = json.loads((paths["logs"] / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "infrastructure_error"
    assert isinstance(result["error_type"], str)
    assert set(result) == {"status", "error_type"}


def test_crash_evidence_does_not_raise_when_state_unwritable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """留证本身不能把进程再搞崩：state 不可写时只放弃写文件，stderr 仍然有。"""
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["worker.py", "--state", str(blocker), "--logs", str(tmp_path)])

    worker._emit_crash("main", ValueError("boom"))

    assert "ValueError" in capsys.readouterr().err
    # state 路径不可用（父级是文件），不应抛出，也不应破坏原文件
    assert blocker.is_file()


def test_top_level_guard_emits_crash_on_base_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """顶层兜底：main 之外的 BaseException 也要留证，然后照常抛出。"""
    state = tmp_path / "state"
    monkeypatch.setattr(sys, "argv", ["worker.py", "--state", str(state)])

    with pytest.raises(KeyboardInterrupt):
        try:
            raise KeyboardInterrupt("cancelled")
        except SystemExit:
            raise
        except BaseException as exc:  # 与 __main__ 分支同一逻辑
            worker._emit_crash("top-level", exc)
            raise

    captured = capsys.readouterr()
    assert "stage=top-level" in captured.err
    assert "KeyboardInterrupt" in captured.err
    assert (state / "worker-error.txt").is_file()
