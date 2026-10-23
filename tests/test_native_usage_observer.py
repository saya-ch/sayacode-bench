"""原生缓存用量旁证；默认不依赖 LangChain，也不调用供应商 API。"""

from __future__ import annotations

import asyncio
import builtins
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from sayacode_bench import worker


@pytest.fixture
def evidence(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    audit = tmp_path / "audit.jsonl"
    usage = {"input_tokens": 100, "output_tokens": 7, "total_tokens": 107}
    rows = [
        {"event": event, "run_id": "run-1", "thread_id": "thread-1", "details": {"usage": usage}}
        for event in ("model.started", "model.completed")
    ]
    audit.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    payload = {
        "schema_version": 1,
        "collector": "langchain_callback_usage_v1",
        "audit_sha256": hashlib.sha256(audit.read_bytes()).hexdigest(),
        "calls": [
            {
                "run_id": "run-1",
                "thread_id": "thread-1",
                "event": "completed",
                "usage": {**usage, "input_token_details": {"cache_read": 80, "cache_creation": 0}},
            }
        ],
    }
    return payload, audit


def test_complete_numeric_evidence_and_missing_thread_use_audit_identity(evidence: Any) -> None:
    payload, audit = evidence
    payload["calls"][0]["thread_id"] = None
    result = worker.validate_native_usage_details(payload, audit)
    assert result["status"] == "complete" and result["coverage_complete"] is True
    assert result["model_calls"] == result["matched_calls"] == 1
    assert result["input_tokens"] == 100 and result["total_tokens"] == 107
    assert result["cache_read_input_tokens"] == 80
    assert result["cache_creation_input_tokens"] == 0
    assert "calls" not in result


@pytest.mark.parametrize(
    "change,reason",
    [
        ("schema", "sidecar_schema_invalid"),
        ("hash", "audit_identity_mismatch"),
        ("duplicate", "observer_conflict"),
        ("thread", "thread_identity_mismatch"),
        ("sum", "usage_total_mismatch"),
        ("audit", "audit_usage_mismatch"),
        ("negative", "usage_field_invalid"),
        ("boolean", "usage_field_invalid"),
        ("cache_boolean", "cache_field_invalid"),
        ("too_many", "cache_exceeds_input"),
    ],
)
def test_invalid_identity_or_numbers_never_get_a_discount(
    evidence: Any, change: str, reason: str
) -> None:
    payload, audit = evidence
    call = payload["calls"][0]
    if change == "schema":
        payload["schema_version"] = 2
    elif change == "hash":
        payload["audit_sha256"] = "a" * 64
    elif change == "duplicate":
        payload["calls"].append(dict(call))
    elif change == "thread":
        call["thread_id"] = "wrong"
    elif change == "sum":
        call["usage"]["total_tokens"] = 108
    elif change == "audit":
        call["usage"].update(input_tokens=101, total_tokens=108)
    elif change == "negative":
        call["usage"]["input_tokens"] = -1
    elif change == "boolean":
        call["usage"]["input_tokens"] = True
    elif change == "cache_boolean":
        call["usage"]["input_token_details"]["cache_read"] = True
    else:
        call["usage"]["input_token_details"]["cache_read"] = 101
    result = worker.validate_native_usage_details(payload, audit)
    assert result["status"] == "invalid" and result["reason"] == reason
    assert result["coverage_complete"] is False


@pytest.mark.parametrize(
    "change", ["absent", "calls", "details", "cache_read", "creation", "error"]
)
def test_missing_coverage_or_details_stays_unavailable(evidence: Any, change: str) -> None:
    payload, audit = evidence
    if change == "absent":
        payload = {}
    elif change == "calls":
        payload["calls"] = []
    elif change == "details":
        payload["calls"][0]["usage"].pop("input_token_details")
    elif change == "error":
        payload["calls"][0].update(event="failed", usage=None)
    else:
        payload["calls"][0]["usage"]["input_token_details"].pop(
            change if change == "cache_read" else "cache_creation"
        )
    result = worker.validate_native_usage_details(payload, audit)
    assert result["status"] == "unavailable" and result["coverage_complete"] is False
    assert result["cache_read_input_tokens"] is None


def test_generic_zero_does_not_hide_ttl_cache_creation(evidence: Any) -> None:
    payload, audit = evidence
    details = payload["calls"][0]["usage"]["input_token_details"]
    details.update(cache_read=60, ephemeral_5m_input_tokens=20, ephemeral_1h_input_tokens=10)
    result = worker.validate_native_usage_details(payload, audit)
    assert result["status"] == "complete" and result["cache_creation_input_tokens"] == 30
    details["cache_creation"] = 30
    assert worker.validate_native_usage_details(payload, audit)["cache_creation_input_tokens"] == 30
    details["cache_creation"] = 31
    assert worker.validate_native_usage_details(payload, audit)["status"] == "invalid"
    details.pop("cache_read")
    details["cache_creation"] = 0
    result = worker.validate_native_usage_details(payload, audit)
    assert result["status"] == "unavailable" and result["cache_creation_input_tokens"] == 30


def test_missing_dependency_is_observation_unavailable_not_a_runner_fallback(
    evidence: Any, monkeypatch: Any
) -> None:
    _, audit = evidence
    original = builtins.__import__

    def import_without_langchain(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("langchain_core"):
            raise ImportError("synthetic dependency absence")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_langchain)
    with worker.observe_native_usage() as snapshot:
        result = snapshot(audit)
    assert result["status"] == "unavailable" and result["collector_unavailable"] is True
    assert worker._USAGE_CONTEXT.get() is None


def test_missing_sidecar_does_not_impose_new_checks_on_legacy_audit(tmp_path: Path) -> None:
    result = worker.validate_native_usage_details({}, tmp_path / "does-not-exist")
    assert result["reason"] == "sidecar_missing" and result["status"] == "unavailable"
    assert result["input_tokens"] is None and result["cache_creation_input_tokens"] is None


def test_official_context_token_resets_when_scope_raises() -> None:
    pytest.importorskip("langchain_core")
    with pytest.raises(RuntimeError):
        with worker.observe_native_usage():
            assert worker._USAGE_CONTEXT.get() is not None
            raise RuntimeError("synthetic scope failure")
    assert worker._USAGE_CONTEXT.get() is None


async def test_official_context_hook_coexists_with_explicit_callbacks_and_async_child(
    tmp_path: Path,
) -> None:
    pytest.importorskip("langchain")
    from langchain.agents import create_agent
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    audit = tmp_path / "audit.jsonl"
    rows = []

    class Audit(BaseCallbackHandler):
        def on_chat_model_start(
            self,
            serialized: Any,
            messages: Any,
            *,
            run_id: Any,
            metadata: Any = None,
            **kwargs: Any,
        ) -> None:
            rows.append(
                {
                    "event": "model.started",
                    "run_id": str(run_id),
                    "thread_id": metadata["thread_id"],
                    "details": {},
                }
            )

        def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
            thread = next(row["thread_id"] for row in rows if row["run_id"] == str(run_id))
            rows.append(
                {"event": "model.failed", "run_id": str(run_id), "thread_id": thread, "details": {}}
            )

        def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
            thread = next(row["thread_id"] for row in rows if row["run_id"] == str(run_id))
            usage = response.generations[0][0].message.usage_metadata
            rows.append(
                {
                    "event": "model.completed",
                    "run_id": str(run_id),
                    "thread_id": thread,
                    "details": {"usage": {key: usage[key] for key in worker._USAGE_TOTALS}},
                }
            )

    usage = {
        "input_tokens": 100,
        "output_tokens": 7,
        "total_tokens": 107,
        "input_token_details": {"cache_read": 80, "cache_creation": 0},
    }
    graph = create_agent(
        FakeMessagesListChatModel(responses=[AIMessage(content="synthetic", usage_metadata=usage)]),
        tools=[],
    )
    callback = Audit()

    async def invoke(thread: str) -> None:
        await graph.ainvoke(
            {"messages": [{"role": "user", "content": "synthetic"}]},
            config={"callbacks": [callback], "metadata": {"thread_id": thread}},
        )

    with worker.observe_native_usage() as snapshot:
        await invoke("parent")
        await asyncio.create_task(invoke("child"))
        audit.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        result = snapshot(audit)
        assert result["status"] == "complete" and result["matched_calls"] == 2
        assert result["cache_read_input_tokens"] == 160
        assert {call["thread_id"] for call in result["calls"]} == {"parent", "child"}

        class FailedModel(FakeMessagesListChatModel):
            def _generate(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("synthetic private error body")

        failed = create_agent(FailedModel(responses=[]), tools=[])
        with pytest.raises(RuntimeError):
            await failed.ainvoke(
                {"messages": [{"role": "user", "content": "synthetic"}]},
                config={"callbacks": [callback], "metadata": {"thread_id": "failed"}},
            )
        audit.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        error_result = snapshot(audit)
        assert error_result["status"] == "unavailable" and error_result["model_calls"] == 3
        assert "synthetic private error body" not in json.dumps(error_result)
    assert worker._USAGE_CONTEXT.get() is None
    await invoke("outside")
    assert len(result["calls"]) == 2 and len(rows) == 8
