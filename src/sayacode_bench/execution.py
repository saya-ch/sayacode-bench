"""用官方 Harbor 执行单次试验、独立重判并保存可核查结果。"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import random
import re
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harbor.job import Job
from harbor.models.job.config import JobConfig, RetryConfig
from harbor.models.trial.config import AgentConfig, EnvironmentConfig, TaskConfig, VerifierConfig
from harbor.models.trial.result import TrialResult

CANONICAL_MODEL = "DeepSeek-V4.1-Flash"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}\Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _tree_hash(root: Path) -> str:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            entries.append((path.relative_to(root).as_posix(), "link", path.readlink().as_posix()))
        elif path.is_file():
            entries.append((path.relative_to(root).as_posix(), "file", _sha256(path)))
    return _json_hash(entries)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("结果必须是 JSON 对象")
    return value


def _write_object(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _file_identity(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": _sha256(path) if path.is_file() else None}


def _runtime_identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"available": False, "reason": "missing"}
    try:
        value = _read_object(path)
    except (OSError, UnicodeError, ValueError):
        return {"available": False, "reason": "unreadable"}
    if value.get("available") is not True:
        return {"available": False, "reason": "observation_failed"}
    return {
        "available": True,
        **{
            key: value.get(key)
            for key in (
                "image_id",
                "repo_digests",
                "architecture",
                "os",
                "requested",
                "docker_limits",
                "storage_hard_limit_supported",
            )
        },
    }


def _reward(trial: TrialResult) -> float | None:
    result = trial.verifier_result
    rewards = result.rewards if result else None
    if not isinstance(rewards, dict):
        return None
    value = rewards.get("reward")
    if type(value) not in {int, float} or value not in {0, 1}:
        return None
    return float(value)


def _duration(trial: TrialResult) -> float | None:
    if trial.started_at is None or trial.finished_at is None:
        return None
    return max(0.0, float((trial.finished_at - trial.started_at).total_seconds()))


def _terminal_failure_types(path: Path) -> list[str]:
    latest: dict[str, list[str]] = {}
    if path.is_file():
        with path.open("rb") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(row, dict) or row.get("event") not in {
                    "model.completed",
                    "model.failed",
                }:
                    continue
                thread = str(row.get("thread_id"))
                details = row.get("details")
                if row["event"] == "model.completed" or not isinstance(details, dict):
                    latest[thread] = []
                    continue
                chain = details.get("error_chain", [])
                chain = chain if isinstance(chain, list) else []
                latest[thread] = [
                    value
                    for value in [details.get("error_type"), *chain]
                    if isinstance(value, str)
                    and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,100}", value)
                ]
    return sorted({value for values in latest.values() for value in values})


def normalize_trial_result(
    trial: TrialResult,
    trial_dir: Path,
    *,
    configuration: str,
    repeat: int,
    endpoint: str,
    canonical_model: str = CANONICAL_MODEL,
    require_replay: bool = False,
) -> dict[str, Any]:
    """执行状态和官方 reward 分开；缺少评分不自动猜测为失败。"""
    worker_path = trial_dir / "agent" / "sayacode" / "result.json"
    worker: dict[str, Any] = {}
    issues = []
    if worker_path.is_file():
        try:
            worker = _read_object(worker_path)
        except (OSError, UnicodeError, ValueError):
            issues.append("worker_result_unreadable")
    agent_context = trial.agent_result
    metadata = agent_context.metadata if agent_context else None
    fallback = metadata.get("sayacode", {}) if isinstance(metadata, dict) else {}
    if not worker and isinstance(fallback, dict):
        worker = fallback
    exception = trial.exception_info
    exception_type = exception.exception_type if exception else None
    worker_status = worker.get("status")
    if exception_type == "AgentTimeoutError":
        status = "timeout"
    elif exception_type == "CancelledError":
        status = "cancelled"
    elif worker_status in {"completed", "failed", "paused", "infrastructure_error"}:
        status = str(worker_status)
    elif worker_status == "stopped":
        status = "cancelled"
    elif worker_status == "result_missing":
        status = "result_unknown"
    elif exception_type and not exception_type.startswith("Verifier"):
        status = "infrastructure_error"
    elif agent_context is not None and not issues:
        # oracle、空解、补丁重放等官方 Agent 没有 SAYACODE worker 文件。
        status = "completed"
    else:
        status = "result_unknown"

    reward = _reward(trial)
    verified = reward is not None and exception is None and not require_replay
    if status in {"failed", "timeout", "cancelled", "infrastructure_error"}:
        success: bool | None = False
    elif status == "completed" and verified:
        success = reward == 1
    else:
        success = None
    usage = worker.get("usage", {})
    usage = usage if isinstance(usage, dict) else {}
    model_calls = usage.get("model_calls")
    complete_usage = (
        type(model_calls) is int
        and model_calls > 0
        and usage.get("reported_calls") == model_calls
        and usage.get("missing_usage_calls") == 0
        and usage.get("damaged_audit_lines") == 0
    )
    usage_values = {
        name: value
        if type(value := usage.get(name)) is int and value >= 0 and model_calls
        else None
        for name in ("input_tokens", "output_tokens")
    }
    if not usage and agent_context is not None:
        usage_values = {
            "input_tokens": agent_context.n_input_tokens,
            "output_tokens": agent_context.n_output_tokens,
        }
        complete_usage = False
    terminal_types = _terminal_failure_types(trial_dir / "agent" / "sayacode" / "audit.jsonl")
    connection_types = {
        "APIConnectionError",
        "OpenAIConnectionError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "RemoteProtocolError",
        "ReadError",
        "NetworkError",
    }
    return {
        "schema_version": 1,
        "task_id": trial.task_name.split("/")[-1],
        "official_task_name": trial.task_name,
        "configuration": configuration,
        "repeat": repeat,
        "canonical_model": canonical_model,
        "endpoint": endpoint,
        "status": status,
        "worker_status": worker_status,
        "harbor_exception_type": exception_type,
        "success": success,
        "verified": verified,
        "original_reward": reward,
        "verification_kind": "pristine_replay_required" if require_replay else "official_verifier",
        "duration_seconds": _duration(trial),
        **usage_values,
        "usage_complete": complete_usage,
        "usage": usage,
        "task_count": worker.get("task_count"),
        "child_roles": worker.get("child_roles"),
        "terminal_http_statuses": worker.get("terminal_http_statuses", []),
        "terminal_error_types": terminal_types,
        "failure_category": "model_connection"
        if status == "failed" and connection_types.intersection(terminal_types)
        else None,
        "normalization_issues": issues,
        "trial_name": trial.trial_name,
        "task_checksum": trial.task_checksum,
        "raw_trial_result": _file_identity(trial_dir / "result.json"),
        "worker_result": _file_identity(worker_path),
        "runtime": _file_identity(trial_dir / "runtime.json"),
        "runtime_identity": _runtime_identity(trial_dir / "runtime.json"),
        "network_isolation": _file_identity(trial_dir / "network-isolation.json"),
        "record_complete": True,
    }


def _config(value: AgentConfig | Mapping[str, Any]) -> AgentConfig:
    if isinstance(value, AgentConfig):
        return value.model_copy(deep=True)
    return AgentConfig.model_validate(dict(value))


def _environment(value: EnvironmentConfig | Mapping[str, Any] | None) -> EnvironmentConfig:
    if isinstance(value, EnvironmentConfig):
        return value.model_copy(deep=True)
    return EnvironmentConfig.model_validate(
        dict(value) if value is not None else {"type": "docker"}
    )


def _verifier(value: VerifierConfig | Mapping[str, Any] | None) -> VerifierConfig:
    if isinstance(value, VerifierConfig):
        return value.model_copy(deep=True)
    return VerifierConfig.model_validate(dict(value) if value is not None else {})


def _request_identity(task_path: Path, config: JobConfig, metadata: Mapping[str, Any]) -> str:
    inputs: dict[str, Any] = {}
    for agent in config.agents:
        for key, value in agent.kwargs.items():
            if key.endswith("_path") or key == "product_wheel":
                path = Path(value) if isinstance(value, str) else None
                if path and path.is_file():
                    inputs[key] = _sha256(path)
            elif key == "source_job" and isinstance(value, str):
                source = Path(value)
                inputs[key] = {
                    str(path.relative_to(source)): _sha256(path)
                    for pattern in ("instance_*/result.json", "instance_*/agent/model.patch")
                    for path in sorted(source.glob(pattern))
                    if path.is_file()
                }
    uses_replay = any(
        agent.import_path == "patch_replay:PatchReplayAgent" for agent in config.agents
    )
    replay_module = sys.modules.get("patch_replay") if uses_replay else None
    tooling_file = Path(str(replay_module.__file__)) if replay_module is not None else None
    return _json_hash(
        {
            "task_tree": _tree_hash(task_path),
            "config": config.model_dump(mode="json"),
            "input_artifacts": inputs,
            "adapter_source": {
                name: _sha256(Path(__file__).with_name(name))
                for name in ("adapter.py", "worker.py")
            },
            "patch_replay_source": _sha256(tooling_file)
            if tooling_file and tooling_file.is_file()
            else None,
            "metadata": metadata,
        }
    )


async def run_official_trial(
    task_path: Path,
    output: Path,
    job_name: str,
    agent_config: AgentConfig | Mapping[str, Any],
    environment_config: EnvironmentConfig | Mapping[str, Any] | None = None,
    *,
    configuration: str = "baseline",
    repeat: int = 1,
    canonical_model: str = CANONICAL_MODEL,
    endpoint: str = "local",
    require_replay: bool = False,
    verifier_config: VerifierConfig | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """一个任务、一个配置、一次尝试；Harbor 负责环境、执行和验证。"""
    if not _NAME.fullmatch(job_name) or job_name in {".", ".."}:
        raise ValueError("job_name 必须是安全的单层名称")
    if type(repeat) is not int or repeat < 1:
        raise ValueError("repeat 必须从 1 开始")
    if not _NAME.fullmatch(endpoint):
        raise ValueError("endpoint 只记录连接别名，不接受 URL 或凭据")
    task_path = task_path.resolve(strict=True)
    if not task_path.is_dir() or not (task_path / "task.toml").is_file():
        raise ValueError("task_path 必须是官方 Harbor 任务目录")
    output = output.resolve()
    config = JobConfig(
        job_name=job_name,
        jobs_dir=output,
        tasks=[TaskConfig(path=task_path)],
        agents=[_config(agent_config)],
        environment=_environment(environment_config),
        verifier=_verifier(verifier_config),
        n_concurrent_trials=1,
        n_attempts=1,
        retry=RetryConfig(max_retries=0),
        quiet=True,
    )
    identity: dict[str, Any] = {
        "configuration": configuration,
        "repeat": repeat,
        "canonical_model": canonical_model,
        "endpoint": endpoint,
        "require_replay": require_replay,
    }
    request_hash = _request_identity(task_path, config, identity)
    job_dir = output / job_name
    record_path = job_dir / "normalized.json"
    if record_path.is_file():
        existing = _read_object(record_path)
        if (
            existing.get("record_complete") is True
            and existing.get("request_sha256") == request_hash
        ):
            return existing
        raise ValueError("已有记录未收尾或输入身份变化；不得自动重跑")
    if job_dir.exists():
        raise ValueError("已有未收尾 Harbor job；请显式保留现场并决定恢复策略")
    try:
        job = await Job.create(config)
        result = await job.run()
    except asyncio.CancelledError:
        _write_object(
            record_path,
            {
                "schema_version": 1,
                "task_id": task_path.name,
                **identity,
                "status": "cancelled",
                "success": None,
                "verified": False,
                "request_sha256": request_hash,
                "job_dir": str(job_dir),
                "record_complete": False,
            },
        )
        raise
    except Exception as exc:
        record = {
            "schema_version": 1,
            "task_id": task_path.name,
            **identity,
            "status": "infrastructure_error",
            "success": False,
            "verified": False,
            "harbor_exception_type": type(exc).__name__,
            "record_complete": True,
        }
    else:
        if len(result.trial_results) != 1:
            record = {
                "schema_version": 1,
                "task_id": task_path.name,
                **identity,
                "status": "result_unknown",
                "success": None,
                "verified": False,
                "trial_result_count": len(result.trial_results),
                "record_complete": False,
            }
        else:
            trial = result.trial_results[0]
            if not _NAME.fullmatch(trial.trial_name):
                raise ValueError("Harbor trial_name 超出本试验的单层目录约定")
            record = normalize_trial_result(
                trial,
                job_dir / trial.trial_name,
                **identity,
            )
    record.update(
        request_sha256=request_hash,
        job_dir=str(job_dir),
        raw_job_result=_file_identity(job_dir / "result.json"),
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )
    _write_object(record_path, record)
    return record


async def replay_official_trial(
    task_path: Path,
    output: Path,
    job_name: str,
    source_job: Path,
    official_tooling_path: Path,
    environment_config: EnvironmentConfig | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """复用上游 PatchReplayAgent，把唯一源补丁交给一个新的官方环境。"""
    source_job = source_job.resolve(strict=True)
    source = _read_object(source_job / "normalized.json")
    if source.get("record_complete") is not True:
        raise ValueError("源试验未收尾，不能对仍在变化的工件重判")
    raw_trials = list(source_job.glob("instance_*/result.json"))
    source_failed = source.get("status") in {
        "failed",
        "infrastructure_error",
        "cancelled",
        "timeout",
    }
    if not raw_trials:
        return {
            **source,
            "source_job": str(source_job),
            "verification_kind": "pristine_replay",
            "verified": False,
            "success": False if source_failed else None,
            "replay_status": "missing_source_trial",
            "apply_rc": None,
            "replay_reward": None,
            "replay_job_dir": None,
        }
    if len(raw_trials) > 1:
        raise ValueError("补丁重判要求源 job 恰好一个 instance trial，避免首补丁串用")
    raw_trial = _read_object(raw_trials[0])
    if raw_trial.get("task_name", "").split("/")[-1] != task_path.name:
        raise ValueError("源 job 与待重判任务不一致")
    patch = raw_trials[0].parent / "agent" / "model.patch"
    replay: dict[str, Any] = {
        **source,
        "source_job": str(source_job),
        "verification_kind": "pristine_replay",
        "verified": False,
        "success": False if source_failed else None,
        "patch": _file_identity(patch),
        "apply_rc": None,
        "replay_reward": None,
        "replay_job_dir": None,
    }
    if not patch.is_file():
        replay["replay_status"] = "missing_patch"
        return replay
    empty_patch = patch.stat().st_size == 0
    tooling = official_tooling_path.resolve(strict=True)
    module_file = tooling / "patch_replay.py"
    if not module_file.is_file():
        raise ValueError("official_tooling_path 必须含上游 patch_replay.py")
    previous = sys.modules.get("patch_replay")
    if previous is not None and Path(str(previous.__file__)).resolve() != module_file:
        raise ValueError("已有同名补丁模块来自其他路径，拒绝混用上游版本")
    sys.path.insert(0, str(tooling))
    try:
        previous_bytecode = sys.dont_write_bytecode
        try:
            # 上游快照是冻结输入；导入不能向其中生成 __pycache__。
            sys.dont_write_bytecode = True
            importlib.invalidate_caches()
            module = importlib.import_module("patch_replay")
        finally:
            sys.dont_write_bytecode = previous_bytecode
        if Path(str(module.__file__)).resolve() != module_file:
            raise ValueError("PatchReplayAgent 导入身份不一致")
        replay_record = await run_official_trial(
            task_path,
            output,
            job_name,
            AgentConfig(
                import_path="patch_replay:PatchReplayAgent",
                model_name="replay",
                kwargs={"source_job": str(source_job)},
            ),
            environment_config,
            configuration=str(source["configuration"]),
            repeat=int(source["repeat"]),
            canonical_model=str(source["canonical_model"]),
            endpoint=str(source["endpoint"]),
        )
    finally:
        sys.path.remove(str(tooling))
    replay.update(
        replay_job_dir=replay_record["job_dir"],
        replay_reward=replay_record.get("original_reward"),
        replay_raw_trial_result=replay_record.get("raw_trial_result"),
        replay_runtime=replay_record.get("runtime"),
        replay_runtime_identity=replay_record.get("runtime_identity"),
        replay_network_isolation=replay_record.get("network_isolation"),
        official_tooling_sha256=_sha256(module_file),
        original_duration_seconds=source.get("duration_seconds"),
        replay_duration_seconds=replay_record.get("duration_seconds"),
    )
    runtime_comparison: dict[str, bool | None] = {"same_image": None, "same_platform": None}
    runtime_values = []
    for identity in (source.get("runtime"), replay_record.get("runtime")):
        if not isinstance(identity, dict) or not isinstance(identity.get("path"), str):
            break
        runtime_path = Path(identity["path"])
        if not runtime_path.is_file() or _sha256(runtime_path) != identity.get("sha256"):
            break
        try:
            observed = _read_object(runtime_path)
        except (OSError, UnicodeError, ValueError):
            break
        if observed.get("available") is not True:
            break
        runtime_values.append(observed)
    if len(runtime_values) == 2:
        source_runtime, target_runtime = runtime_values
        if source_runtime.get("image_id") and target_runtime.get("image_id"):
            runtime_comparison["same_image"] = (
                source_runtime["image_id"] == target_runtime["image_id"]
            )
        if all(runtime.get(key) for runtime in runtime_values for key in ("architecture", "os")):
            runtime_comparison["same_platform"] = all(
                source_runtime[key] == target_runtime[key] for key in ("architecture", "os")
            )
    replay["runtime_comparison"] = runtime_comparison
    replay_json = (
        Path(replay_record["job_dir"])
        / str(replay_record.get("trial_name", ""))
        / "agent"
        / "replay.json"
    )
    empty_application_confirmed = False
    if replay_json.is_file():
        try:
            details = _read_object(replay_json)
        except (OSError, UnicodeError, ValueError):
            replay["replay_status"] = "replay_evidence_unreadable"
            return replay
        apply_rc = details.get("apply_rc")
        replay["apply_rc"] = apply_rc if type(apply_rc) is int else None
        if empty_patch and "patch" in details and details["patch"] is None:
            # 上游用 patch=null 记录有效的无修改交付，仍由 pristine verifier 判分。
            empty_application_confirmed = True
            replay["patch_application"] = "not_required_empty_patch"
        elif details.get("patch") != str(patch):
            replay["replay_status"] = "patch_identity_unconfirmed"
            return replay
    if _sha256(patch) != replay["patch"]["sha256"]:
        replay["replay_status"] = "source_patch_changed_during_replay"
        return replay
    if any(value is False for value in runtime_comparison.values()):
        replay["replay_status"] = "runtime_identity_mismatch"
        return replay
    if replay["apply_rc"] != 0 and not empty_application_confirmed:
        replay["replay_status"] = "patch_apply_failed_or_unconfirmed"
        if replay["apply_rc"] is not None:
            replay.update(status="patch_apply_failed", success=False)
    elif replay_record.get("verified") is True:
        replay.update(
            replay_status="completed_no_changes" if empty_patch else "completed",
            verified=True,
            success=source.get("status") == "completed" and replay["replay_reward"] == 1,
        )
    else:
        replay["replay_status"] = "verification_unconfirmed"
    return replay


def paired_order(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """固定随机块顺序；同一任务与重复编号的配置连续执行。"""
    tasks = manifest.get("tasks", [])
    labels = manifest.get("configurations", [])
    repeats = manifest.get("repeats")
    if not tasks or not labels or type(repeats) is not int or repeats < 1 or "seed" not in manifest:
        raise ValueError("排程需要任务、配置、正重复数和固定 seed")
    task_ids = [task["task_id"] for task in tasks]
    if len(set(task_ids)) != len(task_ids) or len(set(labels)) != len(labels):
        raise ValueError("排程任务或配置重复")
    generator = random.Random(str(manifest["seed"]))
    blocks = [(task_id, repeat) for task_id in task_ids for repeat in range(1, repeats + 1)]
    generator.shuffle(blocks)
    result: list[dict[str, Any]] = []
    for task_id, repeat in blocks:
        ordered_labels = list(labels)
        generator.shuffle(ordered_labels)
        result.extend(
            {"task_id": task_id, "configuration": label, "repeat": repeat}
            for label in ordered_labels
        )
    return [{**item, "sequence": index} for index, item in enumerate(result, 1)]


def remaining_order(
    manifest: Mapping[str, Any], records: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """完整成功和失败均跳过；未收尾记录需要人工明确恢复，不能自动重放。"""
    planned = paired_order(manifest)
    keys = {(row["task_id"], row["configuration"], row["repeat"]) for row in planned}
    completed = set()
    for row in records:
        key = (row.get("task_id"), row.get("configuration"), row.get("repeat"))
        if key not in keys or key in completed:
            raise ValueError("恢复记录不在计划内或重复")
        if row.get("record_complete") is not True:
            raise ValueError("已有未收尾试验，需要显式恢复决定")
        completed.add(key)
    return [
        row
        for row in planned
        if (row["task_id"], row["configuration"], row["repeat"]) not in completed
    ]
