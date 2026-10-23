"""容器内装配真实 SAYACODE；评测只控制输入与保存证据，不重写 Agent 循环。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

PROFILE_OVERRIDES = frozenset(
    {
        "summary_trigger_ratio",
        "summary_trigger_tokens",
        "summary_keep_messages",
        "context_edit_trigger",
        "model_retries",
        "tool_retries",
        "file_search",
        "tool_selector_max_tools",
        "native_tool_search_tools",
    }
)

_USAGE_COLLECTOR = "langchain_callback_usage_v1"
_USAGE_TOTALS = ("input_tokens", "output_tokens", "total_tokens")
_CACHE_KEYS = (
    "cache_read",
    "cache_creation",
    "ephemeral_5m_input_tokens",
    "ephemeral_1h_input_tokens",
)
_USAGE_CONTEXT: ContextVar[Any] = ContextVar("sayacode_bench_native_usage", default=None)
_USAGE_HOOK_REGISTERED = False
NATIVE_USAGE_REASONS = frozenset(
    (
        "sidecar_missing audit_unavailable coverage_or_details_missing audit_invalid audit_conflict "
        "sidecar_schema_invalid audit_identity_mismatch sidecar_calls_invalid observer_conflict "
        "thread_identity_mismatch usage_field_invalid usage_total_mismatch audit_usage_mismatch "
        "cache_field_invalid cache_creation_conflict cache_exceeds_input usage_evidence_invalid "
        "worker_usage_mismatch"
    ).split()
)


def validate_native_usage_details(payload: dict[str, Any], audit_path: Path) -> dict[str, Any]:
    """只核原生数字与逐次 callback 身份；此函数不导入 LangChain。"""
    result: dict[str, Any] = dict.fromkeys(
        (
            "audit_sha256",
            "model_calls",
            *_USAGE_TOTALS,
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    )
    result.update(
        collector=_USAGE_COLLECTOR,
        status="unavailable",
        reason="sidecar_missing",
        matched_calls=0,
        coverage_complete=False,
    )
    if not payload:
        return result
    try:
        data = audit_path.read_bytes()
        result["audit_sha256"] = hashlib.sha256(data).hexdigest()
        audit: dict[str, dict[str, Any]] = {}
        for line in data.splitlines():
            if not line.strip():
                continue
            row = json.loads(line.decode("utf-8-sig"))
            if not isinstance(row, dict):
                raise ValueError("audit_invalid")
            if row.get("event") not in {"model.started", "model.completed", "model.failed"}:
                continue
            run_id = row.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                raise ValueError("audit_invalid")
            item = audit.setdefault(run_id, {"thread_id": row.get("thread_id"), "usage": None})
            if item["thread_id"] != row.get("thread_id"):
                raise ValueError("audit_conflict")
            if row["event"] == "model.completed":
                usage = (row.get("details") or {}).get("usage")
                if item["usage"] is not None and item["usage"] != usage:
                    raise ValueError("audit_conflict")
                item["usage"] = usage
        result["model_calls"] = len(audit)
        if payload.get("schema_version") != 1 or payload.get("collector") != _USAGE_COLLECTOR:
            raise ValueError("sidecar_schema_invalid")
        if payload.get("audit_sha256") != result["audit_sha256"]:
            raise ValueError("audit_identity_mismatch")
        calls = payload.get("calls")
        if not isinstance(calls, list):
            raise ValueError("sidecar_calls_invalid")
        seen: set[str] = set()
        totals = dict.fromkeys(_USAGE_TOTALS, 0)
        cached = created = 0
        unavailable = not audit or bool(payload.get("collector_unavailable"))
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("run_id"), str):
                raise ValueError("sidecar_calls_invalid")
            run_id = call["run_id"]
            if run_id in seen or call.get("conflict"):
                raise ValueError("observer_conflict")
            seen.add(run_id)
            source = audit.get(run_id)
            if source is None:
                unavailable = True
                continue
            if call.get("thread_id") not in {None, source["thread_id"]}:
                raise ValueError("thread_identity_mismatch")
            usage = call.get("usage")
            if call.get("event") != "completed" or not isinstance(usage, dict):
                unavailable = True
                continue
            if usage.get("invalid"):
                raise ValueError("usage_field_invalid")
            if any(key not in usage or usage[key] is None for key in _USAGE_TOTALS):
                unavailable = True
                continue
            if any(type(usage[key]) is not int or usage[key] < 0 for key in _USAGE_TOTALS):
                raise ValueError("usage_field_invalid")
            if usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
                raise ValueError("usage_total_mismatch")
            original = source["usage"]
            if not isinstance(original, dict) or any(
                key not in original or original[key] is None for key in _USAGE_TOTALS
            ):
                unavailable = True
                continue
            if any(
                type(original[key]) is not int or original[key] != usage[key]
                for key in _USAGE_TOTALS
            ):
                raise ValueError("audit_usage_mismatch")
            result["matched_calls"] += 1
            for key in _USAGE_TOTALS:
                totals[key] += usage[key]
            details = usage.get("input_token_details")
            if not isinstance(details, dict):
                unavailable = True
                continue
            if any(
                value is not None and (type(value) is not int or value < 0)
                for value in details.values()
            ):
                raise ValueError("cache_field_invalid")
            generic = details.get("cache_creation")
            ttl = sum(details.get(key) or 0 for key in _CACHE_KEYS[2:])
            if generic and ttl and generic != ttl:
                raise ValueError("cache_creation_conflict")
            writes = ttl or generic
            if writes is not None:
                created += writes
            read = details.get("cache_read")
            if read is None or writes is None:
                unavailable = True
                continue
            if read + writes > usage["input_tokens"]:
                raise ValueError("cache_exceeds_input")
            cached += read
        if created:
            result["cache_creation_input_tokens"] = created
        if seen != set(audit) or result["matched_calls"] != len(audit):
            unavailable = True
        if audit and result["matched_calls"] == len(audit):
            result.update({key: totals[key] for key in _USAGE_TOTALS})
        if unavailable:
            result["reason"] = "coverage_or_details_missing"
        else:
            result.update(
                status="complete",
                reason=None,
                coverage_complete=True,
                cache_read_input_tokens=cached,
                cache_creation_input_tokens=created,
            )
    except (OSError, UnicodeError, json.JSONDecodeError):
        result.update(reason="audit_unavailable")
    except (ValueError, TypeError, AttributeError) as exc:
        result.update(
            status="invalid",
            reason=str(exc) if str(exc) in NATIVE_USAGE_REASONS else "usage_evidence_invalid",
        )
    return result


@contextmanager
def observe_native_usage() -> Iterator[Any]:
    """通过官方可继承 context hook 旁观全部模型，不修改产品 callback。"""
    global _USAGE_HOOK_REGISTERED
    calls: dict[str, dict[str, Any]] = {}
    lock = threading.Lock()
    unavailable = False
    token = None
    try:
        from langchain_core.callbacks import BaseCallbackHandler
        from langchain_core.tracers.context import register_configure_hook

        class Observer(BaseCallbackHandler):  # type: ignore[misc]
            def on_chat_model_start(
                self,
                serialized: Any,
                messages: Any,
                *,
                run_id: Any,
                metadata: Any = None,
                **kwargs: Any,
            ) -> None:
                with lock:
                    calls[str(run_id)] = {
                        "run_id": str(run_id),
                        "thread_id": (metadata or {}).get("thread_id"),
                        "event": "started",
                        "usage": None,
                    }

            def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
                try:
                    raw = response.generations[0][0].message.usage_metadata
                    usage = (
                        {key: raw[key] for key in _USAGE_TOTALS if key in raw}
                        if isinstance(raw, dict)
                        else None
                    )
                    if usage is not None:
                        details = raw.get("input_token_details")
                        if isinstance(details, dict):
                            usage["input_token_details"] = {
                                key: details[key] for key in _CACHE_KEYS if key in details
                            }
                        numbers = [usage.get(key) for key in _USAGE_TOTALS] + list(
                            usage.get("input_token_details", {}).values()
                        )
                        if any(
                            value is not None and (type(value) is not int or value < 0)
                            for value in numbers
                        ):
                            usage = {"invalid": True}
                except (AttributeError, IndexError, TypeError):
                    usage = None
                with lock:
                    item = calls.setdefault(str(run_id), {"run_id": str(run_id), "thread_id": None})
                    if item.get("event") == "completed" and item.get("usage") != usage:
                        item["conflict"] = True
                    item.update(event="completed", usage=usage)

            def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
                with lock:
                    calls.setdefault(
                        str(run_id), {"run_id": str(run_id), "thread_id": None}
                    ).update(event="failed", usage=None)

        if not _USAGE_HOOK_REGISTERED:
            register_configure_hook(_USAGE_CONTEXT, inheritable=True)
            _USAGE_HOOK_REGISTERED = True
        token = _USAGE_CONTEXT.set(Observer())
    except ImportError:
        unavailable = True

    def snapshot(audit_path: Path) -> dict[str, Any]:
        with lock:
            payload = {
                "schema_version": 1,
                "collector": _USAGE_COLLECTOR,
                "collector_unavailable": unavailable,
                "audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest()
                if audit_path.is_file()
                else None,
                "calls": list(calls.values()),
            }
        return {**payload, **validate_native_usage_details(payload, audit_path)}

    try:
        yield snapshot
    finally:
        if token is not None:
            _USAGE_CONTEXT.reset(token)


def write_json(path: Path, data: Any) -> None:
    """以同目录替换保存结果，强制停止时不暴露半个 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("配置必须为 JSON 对象")
    return value


def redact_secret(value: Any, secret: str | None) -> Any:
    """已知连接密钥即使出现在异常或工具字符串正文中，也不进入公开事件。"""
    if isinstance(value, str):
        return value.replace(secret, "***") if secret else value
    if isinstance(value, dict):
        return {str(key): redact_secret(item, secret) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_secret(item, secret) for item in value]
    return value


def export_checkpoints(state: Path, logs: Path) -> None:
    """应用正常关闭后导出图检查点；强制停止不补采数据库，也不复制 Store 或审计。"""
    source = state / "checkpoints.sqlite3"
    if source.is_file() and not source.is_symlink():
        target = logs / source.name
        shutil.copyfile(source, target)
        target.chmod(0o600)


def export_tool_outputs(state: Path, logs: Path) -> dict[str, Any]:
    """保存各线程共用的完整工具输出，只复制普通文件，清单记录实际复制的字节。"""
    source = state / "outputs"
    target = logs / "outputs"
    if logs.resolve().is_relative_to(source.resolve()) or source.resolve().is_relative_to(
        logs.resolve()
    ):
        raise ValueError("完整工具输出源与私有日志目录必须隔离")
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "source_directory": "outputs",
        "status": "absent",
        "files": [],
        "skipped": [],
        "errors": [],
    }

    def linked(path: Path) -> bool:
        return path.is_symlink() or path.is_junction()

    def walk_error(error: OSError) -> None:
        path = Path(error.filename) if isinstance(error.filename, str) else source
        manifest["errors"].append(
            {
                "path": path.relative_to(state).as_posix(),
                "error_type": type(error).__name__,
            }
        )

    if source.exists() or linked(source):
        if linked(source) or not source.is_dir():
            manifest["skipped"].append({"path": "outputs", "reason": "not_regular_directory"})
        else:
            if linked(target):
                raise ValueError("私有工具输出的目标目录不能是链接")
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            manifest["status"] = "complete"
            for directory, directories, names in os.walk(
                source, followlinks=False, onerror=walk_error
            ):
                parent = Path(directory)
                for name in sorted(directories):
                    path = parent / name
                    if linked(path):
                        manifest["skipped"].append(
                            {
                                "path": path.relative_to(state).as_posix(),
                                "reason": "linked_directory",
                            }
                        )
                directories[:] = sorted(name for name in directories if not linked(parent / name))
                for name in sorted(names):
                    path = parent / name
                    relative = path.relative_to(state).as_posix()
                    try:
                        if linked(path) or not stat.S_ISREG(path.lstat().st_mode):
                            manifest["skipped"].append(
                                {"path": relative, "reason": "not_regular_file"}
                            )
                            continue
                        destination = logs / relative
                        for parent_directory in destination.parents:
                            if parent_directory == logs:
                                break
                            if linked(parent_directory):
                                raise ValueError("私有工具输出的目标目录不能是链接")
                        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        if linked(destination):
                            raise ValueError("私有工具输出的目标不能是链接")
                        # 原子替换避免中断留下看似完整的文件；摘要与复制共享同一流。
                        descriptor, temporary = tempfile.mkstemp(
                            prefix=".output-", dir=destination.parent
                        )
                        temporary_path = Path(temporary)
                        digest, copied = hashlib.sha256(), 0
                        try:
                            with os.fdopen(descriptor, "wb") as writer:
                                with path.open("rb") as reader:
                                    while block := reader.read(1024 * 1024):
                                        writer.write(block)
                                        digest.update(block)
                                        copied += len(block)
                            temporary_path.chmod(0o600)
                            temporary_path.replace(destination)
                        finally:
                            temporary_path.unlink(missing_ok=True)
                        manifest["files"].append(
                            {"path": relative, "bytes": copied, "sha256": digest.hexdigest()}
                        )
                    except (OSError, ValueError) as exc:
                        manifest["errors"].append(
                            {"path": relative, "error_type": type(exc).__name__}
                        )
    if manifest["skipped"] or manifest["errors"]:
        manifest["status"] = "partial"
    manifest["file_count"] = len(manifest["files"])
    manifest["total_bytes"] = sum(item["bytes"] for item in manifest["files"])
    write_json(logs / "outputs-manifest.json", manifest)
    (logs / "outputs-manifest.json").chmod(0o600)
    return manifest


def record_tool_output_coverage(state: Path, logs: Path, *, stage: str) -> dict[str, Any]:
    """采集失败单独留证；文件复制完整不代表生成它的工具已成功执行。"""
    try:
        exported = export_tool_outputs(state, logs)
        coverage = {key: exported[key] for key in ("status", "file_count", "total_bytes")}
    except Exception as exc:
        coverage = {"status": "failed", "error_type": type(exc).__name__}
    coverage["stage"] = stage
    try:
        write_json(logs / "outputs-coverage.json", coverage)
        (logs / "outputs-coverage.json").chmod(0o600)
    except OSError as exc:
        # 日志盘也不可写时，仍不能把工件采集错误冒充进程未停止。
        coverage = {"status": "failed", "stage": stage, "error_type": type(exc).__name__}
    return coverage


def git_baseline(workspace: Path, output: Path) -> dict[str, Any]:
    """在 Agent 启动前记录任务实际仓库及提交，非 Git 题保持原样。"""

    def query(*arguments: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(workspace), *arguments],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError:
            return None
        return result.stdout.decode("utf-8", "strict").strip() if result.returncode == 0 else None

    repo = query("rev-parse", "--show-toplevel")
    commit = query("rev-parse", "--verify", "HEAD") if repo else None
    result: dict[str, Any] = {
        "available": bool(repo and commit),
        "repo": repo,
        "base_commit": commit,
    }
    write_json(output, result)
    return result


def capture_patch(baseline_path: Path, patch_path: Path) -> dict[str, Any]:
    """按官方重放边界保存最终工作树差异，含新文件和二进制，不合入子交付。"""
    baseline = read_object(baseline_path)
    if not baseline.get("available"):
        result = {**baseline, "patch_available": False}
        write_json(patch_path.with_suffix(".json"), result)
        return result
    repo = Path(baseline["repo"])
    environment = {**os.environ, "GIT_PAGER": "cat", "GIT_TERMINAL_PROMPT": "0"}

    def execute(
        *arguments: str, stdout: Any = subprocess.PIPE
    ) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            env=environment,
            stdout=stdout,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Git 补丁采集失败")
        return result

    # 使用临时索引执行 intent-to-add，避免改变 Agent 交付的真实暂存区。
    with tempfile.TemporaryDirectory(prefix="sayacode-final-index-") as temporary:
        index = Path(temporary) / "index"
        raw_path = execute("rev-parse", "--git-path", "index").stdout.decode().strip()
        source = Path(raw_path)
        source = source if source.is_absolute() else repo / source
        if source.is_file():
            shutil.copyfile(source, index)
        environment["GIT_INDEX_FILE"] = str(index)
        if not index.exists():
            execute("read-tree", str(baseline["base_commit"]))
        execute("add", "--intent-to-add", "--all")
        with patch_path.open("wb") as stream:
            execute(
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--binary",
                str(baseline["base_commit"]),
                "--",
                stdout=stream,
            )
        stat = execute(
            "diff", "--no-ext-diff", "--no-textconv", "--stat", str(baseline["base_commit"]), "--"
        ).stdout.decode("utf-8", "replace")
    result = {
        **baseline,
        "patch_available": True,
        "patch_bytes": patch_path.stat().st_size,
        "patch_sha256": hashlib.sha256(patch_path.read_bytes()).hexdigest(),
        "diffstat": stat,
        "final_commit": execute("rev-parse", "HEAD").stdout.decode().strip(),
    }
    write_json(patch_path.with_suffix(".json"), result)
    return result


def variant_profile(profile: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    """实验只允许公开算法参数变化；连接和模型身份由控制器单独固定。"""
    unknown = set(variant) - {"id", "team_enabled", "profile_overrides", "instruction_append"}
    if unknown:
        raise ValueError(f"未知实验参数: {sorted(unknown)}")
    if not isinstance(variant.get("team_enabled", True), bool):
        raise ValueError("team_enabled 必须为布尔值")
    if not isinstance(variant.get("instruction_append", ""), str):
        raise ValueError("instruction_append 必须为字符串")
    overrides = variant.get("profile_overrides", {})
    if not isinstance(overrides, dict) or set(overrides) - PROFILE_OVERRIDES:
        raise ValueError("实验不得覆盖连接、模型身份或未知 Profile 字段")
    return {**profile, **overrides}


def audit_metrics(path: Path) -> dict[str, Any]:
    """汇总全部线程并保留未知计量；服务状态仅读取原生 callback 字段。"""
    observed: set[str] = set()
    reported: dict[str, dict[str, int]] = {}
    latest: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    damaged = 0
    if path.is_file():
        with path.open("rb") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line.decode("utf-8-sig"))
                except (ValueError, UnicodeError):
                    damaged += 1
                    continue
                if not isinstance(row, dict):
                    damaged += 1
                    continue
                kind = row.get("event")
                if kind not in {"model.started", "model.completed", "model.failed"}:
                    continue
                identifier = row.get("run_id")
                if not isinstance(identifier, str) or not identifier:
                    damaged += 1
                    continue
                observed.add(identifier)
                details = row.get("details")
                details = details if isinstance(details, dict) else {}
                if kind in {"model.completed", "model.failed"}:
                    latest[str(row.get("thread_id"))] = row
                if kind == "model.failed":
                    code = details.get("status_code")
                    failures.append(
                        {
                            "thread_id": row.get("thread_id"),
                            "run_id": identifier,
                            "status_code": code
                            if type(code) is int and 100 <= code <= 599
                            else None,
                            "error_type": details.get("error_type"),
                            "error_chain": details.get("error_chain"),
                        }
                    )
                usage = details.get("usage")
                if kind != "model.completed" or not isinstance(usage, dict):
                    continue
                numeric = {
                    key: value
                    for key in ("input_tokens", "output_tokens", "total_tokens")
                    if type(value := usage.get(key)) is int and value >= 0
                }
                if len(numeric) >= len(reported.get(identifier, {})):
                    reported[identifier] = numeric
    complete = sum(len(item) == 3 for item in reported.values())
    terminal_codes = sorted(
        {
            details["status_code"]
            for row in latest.values()
            if row.get("event") == "model.failed"
            and isinstance(details := row.get("details"), dict)
            and type(details.get("status_code")) is int
            and 100 <= details["status_code"] <= 599
        }
    )
    return {
        "usage": {
            **{
                key: sum(item.get(key, 0) for item in reported.values())
                for key in ("input_tokens", "output_tokens", "total_tokens")
            },
            "model_calls": len(observed),
            "reported_calls": complete,
            "missing_usage_calls": len(observed) - complete,
            "damaged_audit_lines": damaged,
            "cost_usd": None,
        },
        "model_failures": failures,
        "terminal_http_statuses": terminal_codes,
    }


def task_family_status(final: dict[str, Any], tasks: list[dict[str, Any]]) -> str:
    """子失败可以被父纠正；未解决中断和父唤醒失败仍须如实呈现。"""
    mapping = {
        "run.completed": "completed",
        "run.paused": "paused",
        "run.stopped": "stopped",
        "agent.wake.completed": "completed",
        "agent.wake.paused": "paused",
        "agent.wake.stopped": "stopped",
    }
    states = [mapping.get(str(final.get("type")), "failed")]
    for task in tasks:
        wake = task.get("parent_wake")
        if isinstance(wake, dict):
            states.append(mapping.get(str(wake.get("type")), "failed"))
        if task.get("status") in {"paused", "interrupted", "pending", "running", "stopping"}:
            states.append("paused")
    for status in ("failed", "stopped", "paused"):
        if status in states:
            return status
    return "completed"


async def task_metadata(app: Any, workspace: Path) -> dict[str, Any]:
    """从唯一任务 Store 收集所有已创建子任务，取消路径也必须调用。"""
    records = await app.tasks.list(workspace=workspace)
    return {
        "task_count": len(records),
        "child_roles": [item.role for item in records],
        "unapplied_deliveries": sum(
            item.worktree_enabled and item.delivery_state != "applied" for item in records
        ),
        "task_records": [item.to_dict() for item in records],
    }


def process_identity(pid: int) -> str | None:
    """Linux starttime 防止过期 PID 文件误终止复用进程。"""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        fields = raw.rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except (OSError, IndexError):
        return None


def stop_worker(pid_path: Path, grace: float = 12.0) -> int:
    """只处理本试验 PID 及其已识别后代，先排空，再强制取消。"""
    if not pid_path.is_file():
        return 0
    identity = read_object(pid_path)
    pid = identity.get("pid")
    if (
        type(pid) is not int
        or pid < 2
        or not isinstance(identity.get("starttime"), str)
        or not identity["starttime"]
    ):
        raise ValueError("无效试验 PID")
    if process_identity(pid) != identity.get("starttime"):
        # 有完整结果意味着应用正常经过 finally 关闭；无结果时不能证明没有孤儿 Shell。
        if (pid_path.parent / "result.json").is_file():
            return 0
        raise RuntimeError("worker 已消失且缺少收尾结果，停止状态未知")
    children: dict[int, str] = {}
    # 每个 Shell 可以建立新进程组，必须同时识别后代，不能只 killpg 主线程。
    parent_map: dict[int, int] = {}
    for candidate in Path("/proc").iterdir():
        if not candidate.name.isdigit():
            continue
        try:
            fields = (candidate / "stat").read_text().rsplit(")", 1)[1].split()
            parent_map[int(candidate.name)] = int(fields[1])
        except (OSError, IndexError, ValueError):
            continue
    selected = {pid}
    while fresh := {child for child, parent in parent_map.items() if parent in selected} - selected:
        selected.update(fresh)
    for child in selected - {pid}:
        if value := process_identity(child):
            children[child] = value
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return 0
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and process_identity(pid) == identity.get("starttime"):
        time.sleep(0.1)
    for child, value in [*children.items(), (pid, str(identity["starttime"]))]:
        if process_identity(child) == value:
            try:
                os.kill(child, getattr(signal, "SIGKILL", 9))
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 3
    expected = {**children, pid: str(identity["starttime"])}
    while time.monotonic() < deadline:
        if all(process_identity(child) != value for child, value in expected.items()):
            return 0
        time.sleep(0.05)
    raise RuntimeError("进程族强制停止后仍未确认退出")


async def run(args: argparse.Namespace) -> int:
    with observe_native_usage() as snapshot:
        return await _run(args, snapshot)


async def _run(args: argparse.Namespace, usage_snapshot: Any) -> int:
    """调用生产应用并等待完整任务族；SIGTERM 只控制生命周期。"""
    from langgraph.runtime import RunControl
    from sayacode.agent import AgentRuntime
    from sayacode.application import SayacodeApp
    from sayacode.audit import AuditLog
    from sayacode.cli.events import _redact
    from sayacode.config import Config, ConfigRepository, Profile
    from sayacode.paths import AppPaths

    profile_data = read_object(args.profile)
    variant = read_object(args.variant)
    profile = Profile.from_dict(variant_profile(profile_data, variant))
    workspace = (args.workspace or Path.cwd()).resolve()
    state = args.state.resolve()
    logs = args.logs.resolve()
    if workspace != Path(workspace.anchor) and (
        state.is_relative_to(workspace) or logs.is_relative_to(workspace)
    ):
        raise ValueError("评测状态与日志不得存放任务仓库内")
    state.mkdir(parents=True, exist_ok=False, mode=0o700)
    logs.mkdir(parents=True, exist_ok=True)
    original_home = os.environ.get("HOME")
    os.environ["SAYACODE_HOME"] = str(state / "app")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    paths = AppPaths.resolve(state / "app")
    repository = ConfigRepository(paths.home)
    config = Config(
        default_profile=profile.name,
        default_trust="full",
        profiles={profile.name: profile},
        preferences={"language": "en", "shutdown_grace_seconds": "5"},
    )
    await repository.save(config)
    runtime = await AgentRuntime.open(paths.home)
    app = SayacodeApp(
        paths=paths,
        repository=repository,
        config=config,
        runtime=runtime,
        workspace=workspace,
        session_id="bench-main",
        trust_level="full",
        trust_explicit=True,
        profile_name=profile.name,
        headless=True,
        team_enabled=variant.get("team_enabled", True),
    )
    # 审计逐行直接进入已挂载日志，强制终止也保留此前已确认计量。
    app.audit = AuditLog(logs / "audit.jsonl")
    control = RunControl()
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)
    write_json(
        logs / "worker.pid.json", {"pid": os.getpid(), "starttime": process_identity(os.getpid())}
    )
    instruction = args.instruction.read_text(encoding="utf-8")
    appended = variant.get("instruction_append", "")
    if appended:
        instruction += "\n\n" + appended
    start = time.perf_counter()
    result: dict[str, Any] = {"status": "failed", "task_count": None, "child_roles": None}

    async def execute() -> None:
        await app.initialize()
        final: dict[str, Any] = {}
        with (logs / "events.jsonl").open("w", encoding="utf-8") as stream:

            def emit(event: dict[str, Any]) -> None:
                public = redact_secret(_redact(event), profile.api_key)
                stream.write(json.dumps(public, ensure_ascii=False, default=str) + "\n")
                stream.flush()

            watcher = app.watch_notifications(emit)
            try:
                async for event in app.stream(
                    instruction,
                    input_format="headless",
                    control=control,
                    include_notifications=False,
                ):
                    emit(event)
                    if event.get("type") in {
                        "run.completed",
                        "run.failed",
                        "run.paused",
                        "run.stopped",
                    }:
                        final = event
                tasks = await app.wait_for_tasks()
                # 任务族已结束；补齐 watcher 尚未读取的末尾事件再关闭文件。
                for event in app.drain_notifications():
                    emit(event)
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
        result.update(
            status=task_family_status(final, tasks),
            final=_redact(final),
            tasks=_redact(tasks),
        )

    execution = asyncio.create_task(execute())
    stop_waiter = asyncio.create_task(stopping.wait())
    try:
        done, _ = await asyncio.wait([execution, stop_waiter], return_when=asyncio.FIRST_COMPLETED)
        if stop_waiter in done and not execution.done():
            records = await app.tasks.list(workspace=workspace)
            app.stop_threads(
                {app.session_id, *(item.thread_id for item in records)}, "benchmark stop"
            )
            control.request_drain("benchmark stop")
            shutdown = asyncio.create_task(app.tasks.shutdown(timeout=5))
            try:
                await asyncio.wait_for(asyncio.shield(execution), timeout=7)
            except TimeoutError:
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
                result.update(status="stopped", unconfirmed_effects=True)
            await shutdown
            result["stop_requested"] = True
        else:
            await execution
    except Exception as exc:
        result.update(status="failed", error_type=type(exc).__name__)
    finally:
        stop_waiter.cancel()
        await asyncio.gather(stop_waiter, return_exceptions=True)
        try:
            metadata = await task_metadata(app, workspace)
            rows = metadata.pop("task_records")
            result.update(metadata)
            write_json(logs / "tasks.json", redact_secret(_redact(rows), profile.api_key))
        except Exception as exc:
            # 不能把无法读取的历史或取消前创建的任务伪装成零个子 Agent。
            result["task_metadata_error"] = type(exc).__name__
        try:
            await app.aclose()
        except Exception as exc:
            result.update(status="failed", cleanup_error=type(exc).__name__)
        else:
            try:
                export_checkpoints(paths.home, logs)
            except Exception as exc:
                result["checkpoint_export_error"] = type(exc).__name__
    result.update(audit_metrics(logs / "audit.jsonl"))
    try:
        write_json(logs / "usage-details.json", usage_snapshot(logs / "audit.jsonl"))
    except (OSError, ValueError, TypeError) as exc:
        result["usage_details_error"] = type(exc).__name__
    result.update(
        duration_seconds=round(time.perf_counter() - start, 3),
        variant_id=variant.get("id"),
        model_id=profile.model_id,
        original_home=original_home,
        instruction_sha256=hashlib.sha256(instruction.encode()).hexdigest(),
    )
    write_json(logs / "result.json", redact_secret(_redact(result), profile.api_key))
    return {"completed": 0, "paused": 3, "stopped": 130}.get(str(result["status"]), 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", type=Path)
    parser.add_argument("--export-outputs", action="store_true")
    parser.add_argument("--capture-base", type=Path)
    parser.add_argument("--capture-final", type=Path)
    parser.add_argument("--base-file", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--variant", type=Path)
    parser.add_argument("--instruction", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--state-home", type=Path, help="完整输出采集使用的产品状态根目录")
    parser.add_argument("--logs", type=Path)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    if args.stop:
        return stop_worker(args.stop)
    if args.export_outputs:
        if args.state_home is None or args.logs is None:
            parser.error("完整输出采集需要 state-home 和 logs")
        coverage = record_tool_output_coverage(args.state_home, args.logs, stage="export_command")
        print(json.dumps({"tool_outputs_export": coverage}))
        return 0 if coverage["status"] in {"complete", "absent"} else 1
    if args.capture_base:
        git_baseline(args.workspace or Path.cwd(), args.capture_base)
        return 0
    if args.capture_final:
        if not args.base_file:
            parser.error("capture-final 需要 base-file")
        capture_patch(args.base_file, args.capture_final)
        return 0
    if any(
        getattr(args, name) is None
        for name in ("profile", "variant", "instruction", "state", "logs")
    ):
        parser.error("运行需要 profile、variant、instruction、state 和 logs")
    os.umask(0o077)
    # 在导入模型依赖之前发布 PID；安装与冷启动阶段的取消也能精确路由。
    args.logs.mkdir(parents=True, exist_ok=True)
    write_json(
        args.logs / "worker.pid.json",
        {"pid": os.getpid(), "starttime": process_identity(os.getpid())},
    )
    try:
        return asyncio.run(run(args))
    except Exception as exc:
        # 不向命令日志回显配置和接口错误正文。
        if args.logs:
            write_json(
                args.logs / "result.json",
                {"status": "infrastructure_error", "error_type": type(exc).__name__},
            )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
