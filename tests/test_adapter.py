"""评测适配的连接隔离、任务族结算、未知计量与精确停止。"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from harbor.models.agent.context import AgentContext

from sayacode_bench import network
from sayacode_bench.adapter import SayacodeAgent
from sayacode_bench.worker import (
    audit_metrics,
    capture_patch,
    export_checkpoints,
    git_baseline,
    process_identity,
    redact_secret,
    stop_worker,
    task_family_status,
    task_metadata,
    variant_profile,
)


def make_agent(tmp_path: Path, **extra: Any) -> SayacodeAgent:
    wheel = tmp_path / "sayacode-3.2.4-py3-none-any.whl"
    wheel.write_bytes(b"placeholder")
    profile = tmp_path / "private.json"
    profile.write_text(
        json.dumps(
            {
                "name": "test",
                "api_key": "never-in-command",
                "model_id": "model",
                "base_url": "http://private",
            }
        ),
        encoding="utf-8",
    )
    variant = tmp_path / "variant.json"
    variant.write_text(json.dumps({"id": "baseline", "team_enabled": True}), encoding="utf-8")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example==1 --hash=sha256:abc\n", encoding="utf-8")
    return SayacodeAgent(
        logs_dir=tmp_path / "logs",
        product_wheel=str(wheel),
        profile_path=str(profile),
        variant_path=str(variant),
        requirements_path=str(requirements),
        **extra,
    )


class Environment:
    default_user = "agent"

    def __init__(self, *, return_code: int = 0) -> None:
        self.commands: list[str] = []
        self.uploads: list[tuple[str, str]] = []
        self.return_code = return_code

    async def exec(self, command: str, **kwargs: Any) -> SimpleNamespace:
        self.commands.append(command)
        return SimpleNamespace(
            return_code=self.return_code if " > " in command else 0, stdout="", stderr=""
        )

    async def upload_file(self, source: Path, target: str) -> None:
        self.uploads.append((str(source), target))


@pytest.mark.parametrize("field", ["api_key", "base_url", "model_id", "context_length", "unknown"])
def test_variant_cannot_change_connection(field: str) -> None:
    with pytest.raises(ValueError):
        variant_profile({}, {"profile_overrides": {field: "replacement"}})


def test_variant_only_changes_declared_algorithm_fields() -> None:
    assert variant_profile(
        {"api_key": "private", "summary_trigger_ratio": 0.8},
        {"profile_overrides": {"summary_trigger_ratio": 0.6}},
    ) == {"api_key": "private", "summary_trigger_ratio": 0.6}


def test_secret_embedded_in_error_or_tool_text_is_redacted() -> None:
    payload = {
        "response": 'tool returned {"api_key":"sensitive-key"}',
        "tasks": [{"error": "Authorization sensitive-key failed"}],
    }
    result = redact_secret(payload, "sensitive-key")
    assert "sensitive-key" not in json.dumps(result)
    assert "***" in result["response"]


@pytest.mark.parametrize(
    "variant",
    [
        {"team_enabled": "false"},
        {"instruction_append": []},
        {"extra": True},
        {"profile_overrides": []},
    ],
)
def test_rejects_ambiguous_variant(variant: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        variant_profile({}, variant)


@pytest.mark.parametrize(
    ("final", "tasks", "expected"),
    [
        ({"type": "run.completed"}, [], "completed"),
        ({"type": "run.failed"}, [], "failed"),
        (
            {"type": "run.completed"},
            [{"status": "failed", "parent_wake": {"type": "agent.wake.completed"}}],
            "completed",
        ),
        (
            {"type": "run.completed"},
            [{"status": "idle", "parent_wake": {"type": "agent.wake.failed"}}],
            "failed",
        ),
        ({"type": "run.completed"}, [{"status": "paused"}], "paused"),
        ({"type": "run.stopped"}, [], "stopped"),
    ],
)
def test_task_family_outcomes(
    final: dict[str, Any], tasks: list[dict[str, Any]], expected: str
) -> None:
    assert task_family_status(final, tasks) == expected


def test_audit_includes_children_deduplicates_and_keeps_unknown(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    rows = [
        {"event": "model.started", "run_id": "main", "thread_id": "main"},
        {
            "event": "model.completed",
            "run_id": "main",
            "thread_id": "main",
            "details": {"usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}},
        },
        {"event": "model.started", "run_id": "child", "thread_id": "child"},
        {
            "event": "model.failed",
            "run_id": "child",
            "thread_id": "child",
            "details": {"status_code": 429, "error_type": "RateLimitError"},
        },
    ]
    path.write_bytes(
        ("\n".join(json.dumps(item) for item in [*rows, rows[1]]) + "\n").encode() + b"\x98broken\n"
    )
    metrics = audit_metrics(path)
    assert metrics["usage"]["model_calls"] == 2
    assert metrics["usage"]["input_tokens"] == 5
    assert metrics["usage"]["missing_usage_calls"] == 1
    assert metrics["usage"]["cost_usd"] is None
    assert metrics["terminal_http_statuses"] == [429]
    assert metrics["usage"]["damaged_audit_lines"] == 1


def test_recovered_error_is_not_terminal_and_text_does_not_define_status(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    rows = [
        {
            "event": "model.failed",
            "run_id": "a",
            "thread_id": "child",
            "details": {"status_code": 429},
        },
        {"event": "model.completed", "run_id": "b", "thread_id": "child", "details": {}},
        {
            "event": "model.failed",
            "run_id": "c",
            "thread_id": "main",
            "details": {"error": "429 rate limit api_key=private"},
        },
    ]
    path.write_text("\n".join(json.dumps(item) for item in rows), encoding="utf-8")
    metrics = audit_metrics(path)
    assert metrics["terminal_http_statuses"] == []
    assert "private" not in json.dumps(metrics)


async def test_run_uploads_private_files_and_always_stops_before_return(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    environment = Environment()
    await agent.run("Quote ' and newline\noriginal official task", environment, AgentContext())
    commands = "\n".join(environment.commands)
    assert "never-in-command" not in commands
    assert "original official task" not in commands
    assert "chmod 600" in commands
    assert "chown agent" in commands
    assert "--stop /logs/agent/sayacode/worker.pid.json" in environment.commands[-2]
    assert "--capture-final /logs/agent/model.patch" in environment.commands[-1]
    assert "--workspace" not in commands  # 保留任务镜像定义的工作目录。
    assert all("/installed-agent/" in target for _, target in environment.uploads)


async def test_nonzero_does_not_classify_tool_text_and_still_stops(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    environment = Environment(return_code=3)
    with pytest.raises(RuntimeError, match="exit=3"):
        await agent.run("task", environment, AgentContext())
    assert "--stop" in environment.commands[-2]
    assert "--capture-final" in environment.commands[-1]


def test_context_never_presents_partial_usage_as_complete(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    logs = agent.logs_dir / "sayacode"
    logs.mkdir(parents=True)
    (logs / "audit.jsonl").write_text(
        json.dumps({"event": "model.started", "run_id": "unknown", "thread_id": "child"}),
        encoding="utf-8",
    )
    context = AgentContext()
    agent.populate_context_post_run(context)
    assert context.n_input_tokens is None
    assert context.cost_usd is None
    assert context.metadata["sayacode"]["usage"]["missing_usage_calls"] == 1


def test_stale_pid_file_cannot_kill_reused_process(tmp_path: Path, monkeypatch: Any) -> None:
    path = tmp_path / "pid.json"
    path.write_text(json.dumps({"pid": 12345, "starttime": "old"}), encoding="utf-8")
    (tmp_path / "result.json").write_text('{"status":"completed"}', encoding="utf-8")
    monkeypatch.setattr("sayacode_bench.worker.process_identity", lambda pid: "different")
    monkeypatch.setattr("os.kill", lambda *args: pytest.fail("不应发送信号"))
    assert stop_worker(path) == 0
    assert process_identity(-100) is None


def test_missing_worker_without_result_is_not_confirmed_stopped(
    tmp_path: Path, monkeypatch: Any
) -> None:
    path = tmp_path / "pid.json"
    path.write_text(json.dumps({"pid": 12345, "starttime": "old"}), encoding="utf-8")
    monkeypatch.setattr("sayacode_bench.worker.process_identity", lambda pid: None)
    with pytest.raises(RuntimeError, match="停止状态未知"):
        stop_worker(path)


async def test_cancellation_waits_for_exact_worker_cleanup(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    started = asyncio.Event()
    cleaned = asyncio.Event()

    class CancellableEnvironment(Environment):
        async def exec(self, command: str, **kwargs: Any) -> SimpleNamespace:
            if " > " in command:
                started.set()
                await asyncio.Future()
            value = await super().exec(command, **kwargs)
            if "--stop" in command:
                cleaned.set()
            return value

    environment = CancellableEnvironment()
    task = asyncio.create_task(agent.run("task", environment, AgentContext()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()


async def test_install_preserves_task_python_and_never_uploads_private_profile(
    tmp_path: Path,
) -> None:
    agent = make_agent(tmp_path)
    environment = Environment()

    async def dependencies(*args: Any) -> None:
        return None

    agent.ensure_system_dependencies = dependencies
    await agent.install(environment)
    commands = "\n".join(environment.commands)
    assert "UV_PYTHON_INSTALL_DIR=/installed-agent/sayacode/python" in commands
    assert "uv/0.12.5/install.sh" in commands
    assert "--require-hashes" in commands
    assert "--no-deps" in commands
    assert "--system" not in commands
    assert all("profile" not in target for _, target in environment.uploads)


def git_command(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def test_patch_includes_new_binary_and_committed_changes_without_changing_index(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git_command(repo, "init", "-q")
    git_command(repo, "config", "user.name", "Evaluation")
    git_command(repo, "config", "user.email", "evaluation@example.invalid")
    git_command(repo, "config", "core.autocrlf", "false")
    (repo / "existing.txt").write_text("before\n", encoding="utf-8")
    git_command(repo, "add", ".")
    git_command(repo, "commit", "-qm", "initial")
    baseline = tmp_path / "base.json"
    original = git_baseline(repo, baseline)
    (repo / "existing.txt").write_text("committed edit\n", encoding="utf-8")
    git_command(repo, "add", ".")
    git_command(repo, "commit", "-qm", "agent commits")
    (repo / "existing.txt").write_text("staged edit\n", encoding="utf-8")
    git_command(repo, "add", ".")
    (repo / "added.bin").write_bytes(bytes(range(256)))
    before_index = (repo / ".git" / "index").read_bytes()
    patch = tmp_path / "model.patch"
    result = capture_patch(baseline, patch)
    assert result["patch_available"]
    assert result["base_commit"] == original["base_commit"]
    assert result["final_commit"] != result["base_commit"]
    assert b"GIT binary patch" in patch.read_bytes()
    assert b"+staged edit" in patch.read_bytes()
    assert (repo / ".git" / "index").read_bytes() == before_index
    target = tmp_path / "fresh"
    git_command(repo, "worktree", "add", "--detach", str(target), result["base_commit"])
    git_command(target, "apply", str(patch))
    assert (target / "added.bin").read_bytes() == bytes(range(256))
    assert (target / "existing.txt").read_text(encoding="utf-8") == "staged edit\n"


def test_non_git_terminal_task_does_not_fabricate_patch(tmp_path: Path) -> None:
    repo = tmp_path / "plain"
    repo.mkdir()
    baseline = tmp_path / "baseline.json"
    git_baseline(repo, baseline)
    patch = tmp_path / "model.patch"
    result = capture_patch(baseline, patch)
    assert result["patch_available"] is False
    assert not patch.exists()
    assert patch.with_suffix(".json").exists()


def test_checkpoint_export_does_not_overwrite_live_audit_or_export_credentials(
    tmp_path: Path,
) -> None:
    state, logs = tmp_path / "private", tmp_path / "logs"
    state.mkdir()
    logs.mkdir()
    (state / "audit.jsonl").write_text("stale-partial-audit", encoding="utf-8")
    (state / "store.sqlite3").write_text("private-key-in-task-snapshot", encoding="utf-8")
    (state / "config.json").write_text("private-key-in-config", encoding="utf-8")
    (state / "checkpoints.sqlite3").write_bytes(b"native-checkpoint")
    (logs / "audit.jsonl").write_text("complete-main-and-child-audit", encoding="utf-8")
    export_checkpoints(state, logs)
    assert (logs / "audit.jsonl").read_text(encoding="utf-8") == "complete-main-and-child-audit"
    assert (logs / "checkpoints.sqlite3").read_bytes() == b"native-checkpoint"
    assert not (logs / "store.sqlite3").exists()
    assert not (logs / "config.json").exists()


async def test_task_metadata_keeps_created_children_after_execution_cancel(tmp_path: Path) -> None:
    class Record:
        role = "builder"
        worktree_enabled = True
        delivery_state = "none"

        def to_dict(self) -> dict[str, Any]:
            return {"role": self.role, "status": "interrupted"}

    class Tasks:
        async def list(self, *, workspace: Path) -> list[Record]:
            assert workspace == tmp_path
            return [Record()]

    result = await task_metadata(SimpleNamespace(tasks=Tasks()), tmp_path)
    assert result["task_count"] == 1
    assert result["child_roles"] == ["builder"]
    assert result["task_records"][0]["status"] == "interrupted"


async def test_runtime_record_captures_effective_limits_and_never_config_env(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    environment = SimpleNamespace(
        _container_id="a" * 64,
        task_env_config=SimpleNamespace(
            cpus=1, memory_mb=4096, storage_mb=10240, docker_image="public/task:tag"
        ),
        trial_paths=SimpleNamespace(trial_dir=tmp_path / "trial"),
    )

    async def inspect(*args: str, **kwargs: Any) -> str:
        if args[0] == "image":
            assert args[-1] == "sha256:" + "b" * 64
            return json.dumps(
                [
                    {
                        "RepoDigests": ["public/task@sha256:" + "b" * 64],
                        "Architecture": "amd64",
                        "Os": "linux",
                    }
                ]
            )
        assert args[0] == "exec"
        return "cpu.max=100000 100000\nmemory.max=4294967296\nmemory.swap.max=4294967296"

    state = {
        "Image": "sha256:" + "b" * 64,
        "Config": {
            "Image": "public/task:tag",
            "WorkingDir": "/app",
            "Env": ["API_KEY=never-log-container-env"],
        },
        "HostConfig": {
            "NanoCpus": 1000000000,
            "Memory": 4294967296,
            "MemorySwap": 8589934592,
            "StorageOpt": None,
        },
    }

    monkeypatch.setattr(network, "docker", inspect)
    await network.IsolatedDockerEnvironment._save_runtime_record(environment, state)
    record = json.loads(
        (environment.trial_paths.trial_dir / "runtime.json").read_text(encoding="utf-8")
    )
    assert record["available"] is True
    assert record["docker_limits"]["Memory"] == 4294967296
    assert record["docker_limits"]["MemorySwap"] == 8589934592
    assert record["requested"]["storage_mb"] == 10240
    assert record["storage_hard_limit_supported"] is False
    assert record["repo_digests"][0].startswith("public/task@sha256:")
    assert "never-log-container-env" not in json.dumps(record)


async def test_failed_runtime_inspection_is_unknown_not_an_enforced_resource_claim(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    environment = SimpleNamespace(
        _container_id="a" * 64, trial_paths=SimpleNamespace(trial_dir=tmp_path / "trial")
    )

    async def unavailable(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("not allowed to echo provider detail")

    monkeypatch.setattr(network, "docker", unavailable)
    await network.IsolatedDockerEnvironment._save_runtime_record(environment, {"Image": "x"})
    record = json.loads(
        (environment.trial_paths.trial_dir / "runtime.json").read_text(encoding="utf-8")
    )
    assert record == {"schema_version": 1, "available": False, "error_type": "RuntimeError"}
