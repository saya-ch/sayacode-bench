"""完整工具输出进入私有原始日志；不导出产品配置、Store 或链接目标。"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from sayacode_bench import worker
from sayacode_bench.worker import export_tool_outputs


def test_complete_main_child_and_binary_outputs_are_copied_with_streamed_hashes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    state, logs = tmp_path / "state", tmp_path / "logs"
    outputs = state / "outputs"
    (outputs / "子任务").mkdir(parents=True)
    data = {
        "main.stdout.txt": ("主线程完整输出\n" * 200_000).encode("utf-8"),
        "子任务/child.stderr.txt": "子任务完整错误输出\n".encode("utf-8"),
        "read-result.txt": b"complete file tool result",
        "binary.bin": bytes(range(256)),
        "empty.stderr.txt": b"",
    }
    for name, content in data.items():
        (outputs / name).write_bytes(content)
    for name in ("store.sqlite3", "config.json", "audit.jsonl", "checkpoints.sqlite3"):
        (state / name).write_text("DO-NOT-EXPORT-PRIVATE-STATE", encoding="utf-8")

    def no_read_bytes(path: Path) -> Any:
        pytest.fail(f"导出不能整文件读入内存：{path.name}")

    with monkeypatch.context() as context:
        context.setattr(Path, "read_bytes", no_read_bytes)
        manifest = export_tool_outputs(state, logs)
    assert manifest["status"] == "complete"
    assert manifest["file_count"] == len(data)
    assert manifest["total_bytes"] == sum(len(content) for content in data.values())
    assert manifest["skipped"] == manifest["errors"] == []
    assert json.loads((logs / "outputs-manifest.json").read_text(encoding="utf-8")) == manifest
    assert set(path.name for path in logs.iterdir()) == {"outputs", "outputs-manifest.json"}
    entries = {entry["path"]: entry for entry in manifest["files"]}
    for name, content in data.items():
        copied = logs / "outputs" / name
        assert copied.read_bytes() == content
        assert entries[f"outputs/{name}"] == {
            "path": f"outputs/{name}",
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        if os.name != "nt":
            assert stat.S_IMODE(copied.stat().st_mode) == 0o600
    if os.name != "nt":
        assert stat.S_IMODE((logs / "outputs-manifest.json").stat().st_mode) == 0o600
    assert not list(logs.rglob(".output-*"))


def test_no_output_directory_is_explicitly_recorded_without_fabricated_files(
    tmp_path: Path,
) -> None:
    state, logs = tmp_path / "state", tmp_path / "logs"
    state.mkdir()
    (state / "config.json").write_text("private", encoding="utf-8")
    result = export_tool_outputs(state, logs)
    assert result["status"] == "absent"
    assert result["file_count"] == result["total_bytes"] == 0
    assert not (logs / "outputs").exists()
    assert not (logs / "config.json").exists()


def symlink(source: Path, target: Path, *, directory: bool = False) -> None:
    try:
        if directory and os.name == "nt":
            # 普通 Windows 用户可创建目录 junction；无需用管理员权限掩盖测试。
            subprocess.run(
                ["cmd", "/d", "/c", "mklink", "/J", str(source), str(target)],
                capture_output=True,
                check=True,
                timeout=10,
            )
        else:
            source.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"当前系统无法创建符号链接：{type(exc).__name__}")


def test_source_file_and_directory_links_are_not_followed(tmp_path: Path) -> None:
    state, logs, outside = tmp_path / "state", tmp_path / "logs", tmp_path / "outside"
    outputs = state / "outputs"
    outputs.mkdir(parents=True)
    outside.mkdir()
    (outside / "private.txt").write_text("DO-NOT-COPY-OUTSIDE", encoding="utf-8")
    (outputs / "regular.txt").write_text("allowed", encoding="utf-8")
    symlink(outputs / "linked.txt", outside / "private.txt")
    symlink(outputs / "linked-directory", outside, directory=True)
    result = export_tool_outputs(state, logs)
    assert result["status"] == "partial" and result["file_count"] == 1
    assert {item["path"] for item in result["skipped"]} == {
        "outputs/linked.txt",
        "outputs/linked-directory",
    }
    assert not (logs / "outputs" / "linked.txt").exists()
    assert not (logs / "outputs" / "linked-directory").exists()


def test_source_output_root_link_is_not_traversed(tmp_path: Path) -> None:
    state, logs, outside = tmp_path / "state", tmp_path / "logs", tmp_path / "outside"
    state.mkdir()
    outside.mkdir()
    (outside / "private.txt").write_text("private", encoding="utf-8")
    symlink(state / "outputs", outside, directory=True)
    result = export_tool_outputs(state, logs)
    assert result["status"] == "partial" and result["file_count"] == 0
    assert result["skipped"] == [{"path": "outputs", "reason": "not_regular_directory"}]


def test_destination_root_link_cannot_write_outside_private_trial_logs(tmp_path: Path) -> None:
    state, logs, outside = tmp_path / "state", tmp_path / "logs", tmp_path / "outside"
    (state / "outputs").mkdir(parents=True)
    (state / "outputs" / "tool.txt").write_text("output", encoding="utf-8")
    logs.mkdir()
    outside.mkdir()
    symlink(logs / "outputs", outside, directory=True)
    with pytest.raises(ValueError, match="目标目录不能是链接"):
        export_tool_outputs(state, logs)
    assert not list(outside.iterdir())


def test_nested_destination_link_cannot_create_external_directories(tmp_path: Path) -> None:
    state, logs, outside = tmp_path / "state", tmp_path / "logs", tmp_path / "outside"
    (state / "outputs" / "child" / "nested").mkdir(parents=True)
    (state / "outputs" / "child" / "nested" / "tool.txt").write_text("output", encoding="utf-8")
    (logs / "outputs").mkdir(parents=True)
    outside.mkdir()
    symlink(logs / "outputs" / "child", outside, directory=True)
    result = export_tool_outputs(state, logs)
    assert result["status"] == "partial" and result["file_count"] == 0
    assert result["errors"][0]["error_type"] == "ValueError"
    assert not list(outside.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="Windows 没有 POSIX 命名管道文件接口")
def test_non_regular_output_file_is_skipped_without_blocking(tmp_path: Path) -> None:
    state, logs = tmp_path / "state", tmp_path / "logs"
    (state / "outputs").mkdir(parents=True)
    os.mkfifo(state / "outputs" / "pipe")
    result = export_tool_outputs(state, logs)
    assert result["status"] == "partial" and result["file_count"] == 0
    assert result["skipped"] == [{"path": "outputs/pipe", "reason": "not_regular_file"}]


def test_one_unreadable_output_preserves_other_files_and_records_partial_manifest(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    state, logs = tmp_path / "state", tmp_path / "logs"
    (state / "outputs").mkdir(parents=True)
    bad = state / "outputs" / "bad.txt"
    bad.write_text("unreadable", encoding="utf-8")
    (state / "outputs" / "good.txt").write_text("complete", encoding="utf-8")
    original = Path.open

    def open_file(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == bad:
            raise PermissionError("DO-NOT-REPEAT-PRIVATE-ERROR-BODY")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    result = export_tool_outputs(state, logs)
    assert result["status"] == "partial" and result["file_count"] == 1
    assert result["errors"] == [{"path": "outputs/bad.txt", "error_type": "PermissionError"}]
    assert (logs / "outputs" / "good.txt").read_text(encoding="utf-8") == "complete"
    assert not list(logs.rglob(".output-*"))


def test_repeat_export_replaces_same_output_atomically_and_preserves_live_audit(
    tmp_path: Path,
) -> None:
    state, logs = tmp_path / "state", tmp_path / "logs"
    (state / "outputs").mkdir(parents=True)
    path = state / "outputs" / "tool.txt"
    path.write_text("first", encoding="utf-8")
    first = export_tool_outputs(state, logs)
    (logs / "audit.jsonl").write_text("complete-live-audit", encoding="utf-8")
    path.write_text("updated output", encoding="utf-8")
    second = export_tool_outputs(state, logs)
    assert first["files"][0]["sha256"] != second["files"][0]["sha256"]
    assert second["status"] == "complete" and second["file_count"] == 1
    assert (logs / "outputs" / "tool.txt").read_text(encoding="utf-8") == "updated output"
    assert (logs / "audit.jsonl").read_text(encoding="utf-8") == "complete-live-audit"


def test_overlapping_output_destination_is_rejected_before_copying(tmp_path: Path) -> None:
    state = tmp_path / "state"
    (state / "outputs").mkdir(parents=True)
    with pytest.raises(ValueError, match="必须隔离"):
        export_tool_outputs(state, state / "outputs" / "logs")
    assert not (state / "outputs" / "logs").exists()


def test_unreadable_directory_cannot_claim_complete_coverage(
    tmp_path: Path, monkeypatch: Any
) -> None:
    state, logs = tmp_path / "state", tmp_path / "logs"
    source = state / "outputs"
    source.mkdir(parents=True)

    def walk(path: Path, *, followlinks: bool, onerror: Any) -> Any:
        assert path == source and followlinks is False
        onerror(PermissionError(13, "private error body", str(source / "child")))
        yield str(source), [], []

    monkeypatch.setattr(os, "walk", walk)
    result = export_tool_outputs(state, logs)
    assert result["status"] == "partial" and result["file_count"] == 0
    assert result["errors"] == [{"path": "outputs/child", "error_type": "PermissionError"}]


def export_arguments(monkeypatch: Any, state: Path, logs: Path) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker",
            "--export-outputs",
            "--state-home",
            str(state),
            "--logs",
            str(logs),
        ],
    )


def test_output_export_command_preserves_original_result_and_unclean_checkpoint(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    state, logs = tmp_path / "state", tmp_path / "logs"
    (state / "outputs").mkdir(parents=True)
    (state / "outputs" / "child.stdout.txt").write_text(
        "complete available bytes", encoding="utf-8"
    )
    (state / "checkpoints.sqlite3").write_bytes(b"unclean-after-forced-stop")
    logs.mkdir()
    original = {"status": "stopped", "unconfirmed_effects": True, "original_reward": 0}
    (logs / "result.json").write_text(json.dumps(original), encoding="utf-8")
    export_arguments(monkeypatch, state, logs)
    monkeypatch.setattr(
        worker, "stop_worker", lambda *args: pytest.fail("导出命令不应重复停止进程")
    )
    assert worker.main() == 0
    coverage = json.loads((logs / "outputs-coverage.json").read_text(encoding="utf-8"))
    assert coverage["stage"] == "export_command" and coverage["status"] == "complete"
    assert (logs / "outputs" / "child.stdout.txt").read_text(
        encoding="utf-8"
    ) == "complete available bytes"
    assert not (logs / "checkpoints.sqlite3").exists()
    assert json.loads((logs / "result.json").read_text(encoding="utf-8")) == original


@pytest.mark.parametrize("confirmation", ["raises", "nonzero"])
def test_unconfirmed_stop_does_not_export_live_outputs(
    tmp_path: Path,
    monkeypatch: Any,
    confirmation: str,
) -> None:
    logs = tmp_path / "logs"
    monkeypatch.setattr(sys, "argv", ["worker", "--stop", str(logs / "worker.pid.json")])

    def stop(pid: Path) -> int:
        if confirmation == "raises":
            raise RuntimeError("process stop not confirmed")
        return 1

    monkeypatch.setattr(worker, "stop_worker", stop)
    monkeypatch.setattr(
        worker,
        "record_tool_output_coverage",
        lambda *args, **kwargs: pytest.fail("不能采集仍在运行的输出"),
    )
    if confirmation == "raises":
        with pytest.raises(RuntimeError, match="not confirmed"):
            worker.main()
    else:
        assert worker.main() == 1
    assert not logs.exists()


def test_failed_output_export_is_separate_from_original_run_result(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    state, logs = tmp_path / "state", tmp_path / "logs"
    logs.mkdir()
    original = {"status": "completed", "original_reward": 0}
    (logs / "result.json").write_text(json.dumps(original), encoding="utf-8")
    export_arguments(monkeypatch, state, logs)

    def failed(*args: Any) -> Any:
        raise PermissionError("DO-NOT-LEAK-PRIVATE-ERROR-BODY")

    monkeypatch.setattr(worker, "export_tool_outputs", failed)
    assert worker.main() == 1
    coverage = json.loads((logs / "outputs-coverage.json").read_text(encoding="utf-8"))
    assert coverage == {
        "status": "failed",
        "error_type": "PermissionError",
        "stage": "export_command",
    }
    assert json.loads((logs / "result.json").read_text(encoding="utf-8")) == original
    assert "DO-NOT-LEAK" not in capsys.readouterr().out


def test_output_export_requires_explicit_state_home_and_logs(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "argv", ["worker", "--export-outputs"])
    monkeypatch.setattr(worker, "stop_worker", lambda *args: pytest.fail("参数错误时不能发送信号"))
    with pytest.raises(SystemExit) as caught:
        worker.main()
    assert caught.value.code == 2


def test_stop_confirmation_has_no_output_export_dependency(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "argv", ["worker", "--stop", str(tmp_path / "pid.json")])
    monkeypatch.setattr(worker, "stop_worker", lambda *args: 0)
    monkeypatch.setattr(
        worker,
        "record_tool_output_coverage",
        lambda *args, **kwargs: pytest.fail("stop仅确认进程停止"),
    )
    assert worker.main() == 0
