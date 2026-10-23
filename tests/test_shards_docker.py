"""显式 opt-in 的真实分片集成；本地 stub 替代模型服务，不评价模型效果。"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import tomllib
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest
from test_network import _host_mock_selection

from sayacode_bench import shards, study
from sayacode_bench.artifacts import file_sha256, implementation_identity, read_json, write_json
from sayacode_bench.budget import estimate_paid_usage
from sayacode_bench.execution import run_official_trial
from sayacode_bench.network import docker
from sayacode_bench.sources import SOURCES, SourceSnapshot, SourceSpec, fetch_source, tree_digest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).with_name("fixtures") / "shards-smoke"
SYNTHETIC_REVISION = "synthetic-shards-smoke-v1"


def _tool_result(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get("type") == "tool_result" or any(
            _tool_result(item) for item in value.values()
        )
    return isinstance(value, list) and any(_tool_result(item) for item in value)


def _reply(payload: dict[str, Any], index: int) -> dict[str, Any]:
    """从真实请求 schema 选择文件工具；此函数不写任何任务文件。"""
    if _tool_result(payload.get("messages", [])):
        content, stop = [{"type": "text", "text": "合成文件任务完成。"}], "end_turn"
    else:
        tool = next(
            (
                item
                for item in payload.get("tools", [])
                if item.get("name", "").endswith("write_file")
                and {"path", "content"}.issubset(item.get("input_schema", {}).get("properties", {}))
            ),
            None,
        )
        if tool is None:
            raise ValueError("write_file_schema_not_present")
        content = [
            {
                "type": "tool_use",
                "id": f"toolu_synthetic_{index}",
                "name": tool["name"],
                "input": {"path": "/app/answer.txt", "content": "42\n"},
            }
        ]
        stop = "tool_use"
    # Anthropic 原生 input_tokens 不含缓存；两轮归一化输入均保持 32。
    cache_read = 2 if stop == "end_turn" else 0
    return {
        "id": f"msg_synthetic_{index}",
        "type": "message",
        "role": "assistant",
        "model": payload.get("model", "synthetic-shard-smoke"),
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 32 - cache_read,
            "output_tokens": 16,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": cache_read,
        },
    }


def _sse(message: dict[str, Any]) -> bytes:
    events: list[dict[str, Any]] = [
        {
            "type": "message_start",
            "message": {
                **message,
                "content": [],
                "stop_reason": None,
                "usage": {**message["usage"], "output_tokens": 0},
            },
        }
    ]
    block = message["content"][0]
    start = {**block, "input": {}} if block["type"] == "tool_use" else {**block, "text": ""}
    delta = (
        {"type": "input_json_delta", "partial_json": json.dumps(block["input"], ensure_ascii=False)}
        if block["type"] == "tool_use"
        else {"type": "text_delta", "text": block["text"]}
    )
    events.extend(
        [
            {"type": "content_block_start", "index": 0, "content_block": start},
            {"type": "content_block_delta", "index": 0, "delta": delta},
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
                # 固定 Anthropic 适配器只在最终 delta 采集完整用量。
                "usage": dict(message["usage"]),
            },
            {"type": "message_stop"},
        ]
    )
    return "".join(
        f"event: {item['type']}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
        for item in events
    ).encode("utf-8")


@contextmanager
def _stub(output: Path) -> Iterator[tuple[ThreadingHTTPServer, list[dict[str, Any]]]]:
    records: list[dict[str, Any]] = []
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            if self.path != "/v1/messages":
                self.send_error(404)
                return
            payload: dict[str, Any] = {}
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2 * 1024**2:
                    raise ValueError("invalid_request_size")
                payload = json.loads(self.rfile.read(length))
                with lock:
                    if len(records) >= 16:
                        raise ValueError("unexpected_fixture_request_loop")
                    message = _reply(payload, len(records) + 1)
                    records.append(
                        {
                            "sequence": len(records) + 1,
                            "stream": bool(payload.get("stream")),
                            "tool_names": [item.get("name") for item in payload.get("tools", [])],
                            "tool_result_seen": _tool_result(payload.get("messages", [])),
                            "reply_stop_reason": message["stop_reason"],
                            "synthetic_usage": message["usage"],
                        }
                    )
                streaming = payload.get("stream") is True
                body = (
                    _sse(message)
                    if streaming
                    else json.dumps(message, ensure_ascii=False).encode("utf-8")
                )
                self.send_response(200)
                self.send_header(
                    "Content-Type", "text/event-stream" if streaming else "application/json"
                )
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()
            except Exception as exc:
                known_reasons = {
                    "write_file_schema_not_present",
                    "invalid_request_size",
                    "unexpected_fixture_request_loop",
                }
                reason = (
                    str(exc) if isinstance(exc, ValueError) and str(exc) in known_reasons else None
                )
                with lock:
                    records.append(
                        {
                            "error_type": type(exc).__name__,
                            "reason": reason,
                            "tool_names": [item.get("name") for item in payload.get("tools", [])],
                        }
                    )
                self.send_error(400, "synthetic fixture error")

    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, records
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        write_json(
            output / "stub/request-metadata.json",
            {
                "supplier_endpoint_configured": False,
                "usage_is_synthetic": True,
                "requests": records,
            },
        )


async def _inventory() -> dict[str, list[str]]:
    return {
        "containers": (await docker("container", "ls", "--all", "--quiet")).split(),
        "networks": (await docker("network", "ls", "--quiet")).split(),
        "volumes": (await docker("volume", "ls", "--quiet")).split(),
    }


def _inputs() -> tuple[Path, Path, Path]:
    names = (
        "SAYACODE_BENCH_SMOKE_WHEEL",
        "SAYACODE_BENCH_SMOKE_REQUIREMENTS",
        "SAYACODE_BENCH_SMOKE_OUTPUT",
    )
    if any(not os.environ.get(name) for name in names):
        pytest.fail("真实分片 smoke 必须显式提供原始 wheel、requirements 与独占 output 路径")
    wheel, requirements, output = (Path(os.environ[name]).resolve() for name in names)
    identity = read_json(ROOT / "reproduction/identity.json")
    assert file_sha256(wheel) == identity["production_wheel_sha256"]
    assert file_sha256(requirements) == identity["requirements_sha256"]
    if output.exists():
        pytest.fail("真实分片 smoke 不覆盖或自动续跑已有目录")
    return wheel, requirements, output


@pytest.mark.skipif(
    os.environ.get("SAYACODE_BENCH_SHARD_SMOKE") != "1",
    reason="真实分片 Docker smoke 默认关闭；需显式开关和原始工件路径",
)
async def test_real_production_graph_shards_with_local_anthropic_stub(monkeypatch: Any) -> None:
    assert sys.platform == "linux", "本 smoke 当前要求同宿主 Linux Docker"
    original_wheel, original_requirements, output = _inputs()
    output.mkdir(parents=True, exist_ok=False)
    write_json(
        output / "scope.json",
        {
            "scope": "synthetic infrastructure smoke, not SWE/DeepSeek evaluation",
            "model_service": "local canned Anthropic HTTP/SSE",
            "actual_model_capability_evaluated": False,
            "oracle_role": "one real runtime observation, not formal three-plus-one qualification",
        },
    )
    official = fetch_source(SOURCES["swe-bench-pro-v2"], output / "official-source")
    synthetic = output / "synthetic"
    task = synthetic / "tasks/instance_shards_smoke"
    shutil.copytree(FIXTURE, task)
    tooling = synthetic / "v2/tooling"
    shutil.copytree(
        official.path / "v2/tooling", tooling, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    write_json(
        output / "tooling.json",
        {
            "official_revision": official.spec.revision,
            "patch_replay_sha256": file_sha256(tooling / "patch_replay.py"),
            "original_patch_replay_sha256": file_sha256(
                official.path / "v2/tooling/patch_replay.py"
            ),
        },
    )
    mapping = SourceSnapshot(
        SourceSpec(
            "synthetic-shards-smoke", "local-test-fixture", SYNTHETIC_REVISION, "tasks", "MIT"
        ),
        synthetic,
        tree_digest(task),
        0,
    )
    monkeypatch.setattr(study, "fetch_source", lambda *args: mapping)
    inputs = output / "inputs"
    inputs.mkdir()
    wheel = inputs / "sayacode-3.2.4-py3-none-any.whl"
    requirements = inputs / "requirements.txt"
    shutil.copyfile(original_wheel, wheel)
    shutil.copyfile(original_requirements, requirements)
    identity = read_json(ROOT / "reproduction/identity.json")
    assert file_sha256(wheel) == identity["production_wheel_sha256"]
    assert file_sha256(requirements) == identity["requirements_sha256"]
    tag = "sayacode-shards-smoke:" + uuid.uuid4().hex
    before = await _inventory()
    owned_image_created = False
    try:
        await docker("build", "--tag", tag, str(task / "environment"), timeout=600)
        owned_image_created = True
        inspection = json.loads(await docker("image", "inspect", tag))[0]
        write_json(
            output / "derived-image.json",
            {key: inspection.get(key) for key in ("Id", "Architecture", "Os")},
        )
        definition = task / "task.toml"
        definition.write_text(
            definition.read_text(encoding="utf-8").replace("SHARDS_SMOKE_RUNTIME_IMAGE", tag),
            encoding="utf-8",
        )
        config = tomllib.loads(definition.read_text(encoding="utf-8"))
        host = await _host_mock_selection()
        write_json(output / "host-route.json", host)
        with _stub(output) as (server, http_records):
            upstream = f"http://{host['host_address']}:{server.server_port}"
            environment = {
                "import_path": "sayacode_bench.network:IsolatedDockerEnvironment",
                "kwargs": {"messages_upstream": upstream + "/v1/messages"},
            }
            oracle = await run_official_trial(
                task,
                output / "oracle",
                "runtime-oracle",
                {"name": "oracle"},
                environment,
                configuration="oracle",
                endpoint="stub",
            )
            write_json(output / "oracle-runtime.json", oracle)
            assert (
                oracle["status"] == "completed"
                and oracle["verified"] is True
                and oracle["original_reward"] == 1
            )
            assert not http_records, "参考解不得调用模型 stub"
            variant = inputs / "baseline.json"
            write_json(
                variant,
                {
                    "id": "synthetic-smoke",
                    "team_enabled": False,
                    "profile_overrides": {},
                    "instruction_append": "",
                },
            )
            private = output.parent / (output.name + "-private-" + uuid.uuid4().hex)
            private.mkdir(mode=0o700)
            profile = private / "stub.json"
            public_profile = {
                "name": "synthetic-local-stub",
                "protocol": "anthropic_messages",
                "base_url": upstream,
                "model_id": "synthetic-shard-smoke",
                "context_length": 65536,
                "max_output_tokens": 8192,
                "summary_trigger_ratio": None,
                "context_edit_trigger": None,
                "model_retries": 0,
                "tool_retries": 0,
                "file_search": False,
                "tool_selector_max_tools": None,
            }
            write_json(
                profile, {**public_profile, "api_key": "synthetic-local-only-not-a-supplier-key"}
            )
            profile.chmod(0o600)
            row = {
                "task_id": task.name,
                "repository": "synthetic/shards-smoke",
                "leakage_group": "synthetic-v1",
                "instruction_sha256": file_sha256(task / "instruction.md"),
                "config_sha256": file_sha256(definition),
                "task_tree_sha256": tree_digest(task),
                "environment": config["environment"],
                "agent": config["agent"],
                "verifier": config["verifier"],
            }
            price = inputs / "synthetic-price-basis.json"
            shutil.copyfile(
                ROOT / "studies/prices/siliconflow-deepseek-v4.1-flash-20261022.json", price
            )
            master = {
                "phase": "calibration",
                "frozen": True,
                "canonical_model": "DeepSeek-V4.1-Flash",
                "benchmark": "swe-bench-pro-v2",
                "revision": SYNTHETIC_REVISION,
                "scope": "synthetic harness smoke; benchmark key selects pristine adapter only; not a SWE score",
                "seed": "synthetic-real-shards-v1",
                "tasks": [row],
                "configurations": ["baseline"],
                "baseline": "baseline",
                "candidate": None,
                "repeats": 2,
                "connections": ["stub"],
                "connection_profiles": {"stub": public_profile},
                "reported_token_limit": 100000,
                "preflight_passed": False,
                "runtime_evidence_required": True,
                "qualified_runtime_identities": {task.name: oracle["runtime_identity"]},
                "implementation": implementation_identity(),
                "artifacts": {
                    "product_wheel": file_sha256(wheel),
                    "requirements": file_sha256(requirements),
                    "variants": {"baseline": file_sha256(variant)},
                },
                "paid_budget": study.freeze_paid_budget(
                    limit_cny=1, price_snapshot=price, paid_endpoints=["stub"]
                ),
            }
            manifest = inputs / "master.json"
            write_json(manifest, master)
            policy, authorization = inputs / "runner.json", inputs / "authorization.json"
            write_json(
                policy, {"platform": "linux", "architecture": "amd64", "scope": "local-stub-only"}
            )
            write_json(
                authorization,
                {
                    "authorized": True,
                    "phase": "calibration",
                    "master_manifest_sha256": file_sha256(manifest),
                    "scope": "synthetic zero-paid-API integration",
                },
            )
            plan_path = output / "plan.json"
            plan = shards.freeze_execution_plan(
                manifest, policy, authorization, plan_path, bundle_root=output
            )
            previous, receipts = None, []
            for entry in plan["schedule"]:
                location = output / "shards" / entry["shard_id"]
                receipt = await shards.run_shard(
                    plan_path,
                    entry["shard_id"],
                    previous,
                    output=location,
                    cache=output / "cache",
                    wheel=wheel,
                    requirements=requirements,
                    variants={"baseline": variant},
                    connections={"stub": profile},
                    private_home=private,
                )
                previous = location / "shard-receipt.json"
                receipts.append(previous)
                assert receipt["status"] == "completed" and receipt["complete"] is True, receipt
            merged = shards.merge_shards(plan_path, receipts, output / "merged")
            rows = shards._rows(output / "merged/records.jsonl")
            assert merged["complete"] is True and len(rows) == 2
            assert {item["repeat"] for item in rows} == {1, 2}
            assert all(
                item["verified"] is True and item["success"] is True and item["replay_reward"] == 1
                for item in rows
            )
            assert all(
                item["usage_complete"] is True and Path(item["patch"]["path"]).stat().st_size > 0
                for item in rows
            )
            for item in rows:
                cache_usage = item["cache_usage"]
                assert cache_usage["status"] == "complete"
                assert cache_usage["coverage_complete"] is True
                assert cache_usage["matched_calls"] == cache_usage["model_calls"] == 2
                assert cache_usage["input_tokens"] == item["input_tokens"] == 64
                assert cache_usage["output_tokens"] == item["output_tokens"] == 32
                assert cache_usage["cache_read_input_tokens"] == 2
                assert cache_usage["cache_creation_input_tokens"] == 0
                details = item["usage_details"]
                assert details["sha256"] == file_sha256(Path(details["path"]))
                sidecar = read_json(Path(details["path"]))
                assert sidecar["collector"] == "langchain_callback_usage_v1"
                assert sidecar["status"] == "complete" and len(sidecar["calls"]) == 2
                assert sidecar["audit_sha256"] == cache_usage["audit_sha256"]
            assert sum(item["usage"]["model_calls"] for item in rows) == len(http_records)
            assert (
                len([item for item in http_records if item.get("reply_stop_reason") == "tool_use"])
                == 2
            )
            assert not merged["summary"]["formal_comparison_eligible"]
            assert not merged["summary"]["final_result_eligible"]
            estimate = estimate_paid_usage(rows, paid_endpoints=("stub",))
            assert merged["summary"]["paid_budget"]["cache_discount_applied"] is False
            assert estimate["cache_discount_applied"] is False
            assert (
                merged["summary"]["paid_budget"]["known_estimate_cny"]
                == estimate["known_estimate_cny"]
            )
            write_json(
                output / "smoke-result.json",
                {
                    "passed": True,
                    "scope": master["scope"],
                    "source_trials": 2,
                    "pristine_trials": 2,
                    "synthetic_usage_only": True,
                    "supplier_endpoint_configured": False,
                    "native_usage_observer_verified": True,
                    "estimated_token_arithmetic": estimate,
                },
            )
    finally:
        after = await _inventory()
        remaining = {kind: sorted(set(after[kind]) - set(before[kind])) for kind in before}
        if owned_image_created:
            await docker("image", "rm", tag, check=False)
        image_left = await docker("image", "ls", "--quiet", "--filter", f"reference={tag}")
        write_json(
            output / "cleanup.json",
            {
                "cleanup_confirmed": not any(remaining.values()) and not image_left,
                "new_resources_remaining": remaining,
                "owned_image_remaining": bool(image_left),
            },
        )
        assert not any(remaining.values()) and not image_left


def test_canned_reply_uses_request_schema_and_waits_for_real_tool_result() -> None:
    request = {
        "model": "synthetic",
        "tools": [
            {
                "name": "write_file",
                "input_schema": {
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}}
                },
            }
        ],
        "messages": [{"role": "user", "content": "write the synthetic answer"}],
    }
    first = _reply(request, 1)
    assert first["stop_reason"] == "tool_use"
    assert first["content"][0]["input"] == {"path": "/app/answer.txt", "content": "42\n"}
    assert first["usage"]["input_tokens"] == 32
    assert first["usage"]["cache_read_input_tokens"] == 0
    assert first["usage"]["cache_creation_input_tokens"] == 0
    request["messages"].append(
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}
    )
    second = _reply(request, 2)
    assert second["stop_reason"] == "end_turn"
    assert second["usage"]["input_tokens"] == 30
    assert second["usage"]["cache_read_input_tokens"] == 2
    assert second["usage"]["cache_creation_input_tokens"] == 0
    assert second["usage"]["input_tokens"] + second["usage"]["cache_read_input_tokens"] == 32


def test_canned_sse_has_native_anthropic_usage_and_tool_json_events() -> None:
    message = {
        "id": "msg_synthetic",
        "type": "message",
        "role": "assistant",
        "model": "synthetic",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_synthetic",
                "name": "write_file",
                "input": {"path": "/app/answer.txt", "content": "42\n"},
            }
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 30,
            "output_tokens": 16,
            "cache_read_input_tokens": 2,
            "cache_creation_input_tokens": 0,
        },
    }
    encoded = _sse(message).decode("utf-8")
    events = [
        json.loads(line.removeprefix("data: "))
        for line in encoded.splitlines()
        if line.startswith("data: ")
    ]
    assert events[0]["message"]["usage"] == {
        "input_tokens": 30,
        "output_tokens": 0,
        "cache_read_input_tokens": 2,
        "cache_creation_input_tokens": 0,
    }
    assert events[-2]["usage"]["output_tokens"] == 16
    assert events[-2]["usage"] == message["usage"]
    assert events[-1]["type"] == "message_stop"
    assert json.loads(events[2]["delta"]["partial_json"]) == message["content"][0]["input"]


def test_canned_final_usage_survives_official_anthropic_stream_parser() -> None:
    """走锁定 SDK 的真实事件转换；不创建 HTTP 连接或改写生产 callback。"""
    pytest.importorskip("langchain_anthropic")
    from anthropic.types import RawMessageStreamEvent
    from langchain_anthropic import ChatAnthropic
    from pydantic import TypeAdapter

    message = {
        "id": "msg_synthetic",
        "type": "message",
        "role": "assistant",
        "model": "synthetic",
        "content": [{"type": "text", "text": "synthetic"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 30,
            "output_tokens": 16,
            "cache_read_input_tokens": 2,
            "cache_creation_input_tokens": 0,
        },
    }
    events = [
        json.loads(line.removeprefix("data: "))
        for line in _sse(message).decode("utf-8").splitlines()
        if line.startswith("data: ")
    ]
    model = ChatAnthropic(
        model="synthetic", api_key="synthetic-local-only", base_url="http://127.0.0.1:9"
    )
    parser = TypeAdapter(RawMessageStreamEvent)

    def converted_usage() -> Any:
        combined = block = None
        for raw in events:
            chunk, block = model._make_message_chunk_from_anthropic_event(
                parser.validate_python(raw),
                stream_usage=True,
                coerce_content_to_string=False,
                block_start_event=block,
            )
            if chunk is not None:
                combined = chunk if combined is None else combined + chunk
        assert combined is not None
        return combined.usage_metadata

    usage = converted_usage()
    assert usage["input_tokens"] == 32 and usage["output_tokens"] == 16
    assert usage["input_token_details"] == {"cache_read": 2, "cache_creation": 0}
    # 保留失败回归：只有 start 带输入计量不能让当前适配器获得缓存旁证。
    events[-2]["usage"] = {"output_tokens": 16}
    missing = converted_usage()
    assert missing["input_tokens"] == 0
    assert not missing.get("input_token_details")
