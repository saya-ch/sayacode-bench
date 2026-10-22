"""冻结、未知用量和止损规则不能在报告时静默漂移。"""

from pathlib import Path

import pytest

from sayacode_bench.artifacts import (
    check_budget,
    fatal_stop_reason,
    read_json,
    record_stop,
    write_json,
)
from sayacode_bench.connections import messages_endpoint, read_connection


def test_frozen_manifest_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    write_json(path, {"frozen": True}, exclusive=True)
    with pytest.raises(FileExistsError):
        write_json(path, {"frozen": False}, exclusive=True)
    assert read_json(path) == {"frozen": True}


def test_stop_reason_survives_attempt_to_replace(tmp_path: Path) -> None:
    record_stop(tmp_path, "model_service_limit")
    with pytest.raises(FileExistsError):
        record_stop(tmp_path, "operator_interrupt")
    assert read_json(tmp_path / "abort.json")["reason"] == "model_service_limit"


def test_budget_counts_known_tokens_without_fabricating_missing_usage() -> None:
    records = [{"input_tokens": None, "output_tokens": 30}, {"input_tokens": 70}]
    assert check_budget(records, reported_token_limit=100) == "reported_token_threshold"
    assert check_budget(records, reported_token_limit=101) is None


def test_two_recent_connection_failures_stop_batch() -> None:
    records = [
        {"failure_category": "model_connection"},
        {},
        {"failure_category": "model_connection"},
    ]
    assert check_budget(records, reported_token_limit=100) == "unstable_model_connection"


def test_past_unstable_window_cannot_disappear_after_later_successes() -> None:
    records = [{"failure_category": "model_connection"}, *({} for _ in range(3))]
    assert fatal_stop_reason(records) is None
    records.append({"failure_category": "model_connection"})
    assert fatal_stop_reason(records) == "unstable_model_connection"
    records.extend({} for _ in range(6))
    assert fatal_stop_reason(records) == "unstable_model_connection"


def test_connection_failures_more_than_five_attempts_apart_do_not_stop() -> None:
    records = [
        {"failure_category": "model_connection"},
        *({} for _ in range(4)),
        {"failure_category": "model_connection"},
    ]
    assert fatal_stop_reason(records) is None


@pytest.mark.parametrize("status", [401, 402, 403, 429])
@pytest.mark.parametrize("field", ["terminal_http_status", "terminal_http_statuses"])
def test_terminal_service_failure_is_fatal_even_at_end(status: int, field: str) -> None:
    value = [status] if field.endswith("statuses") else status
    assert fatal_stop_reason([{}, {field: value}]) == "model_service_limit"


def test_ordinary_agent_failure_and_resource_threshold_are_not_fatal() -> None:
    records = [{"status": "failed", "success": False, "input_tokens": 100}]
    assert fatal_stop_reason(records) is None
    assert check_budget(records, reported_token_limit=100) == "reported_token_threshold"


def test_connection_export_excludes_secret(tmp_path: Path) -> None:
    path = tmp_path / "private.json"
    write_json(
        path,
        {
            "api_key": "not-a-real-key",
            "protocol": "anthropic_messages",
            "base_url": "https://model.invalid",
            "model_id": "model",
        },
    )
    value = read_connection("local", path).public_dict()
    assert value["canonical_model"] == "DeepSeek-V4.1-Flash"
    assert "api_key" not in value and "not-a-real-key" not in str(value)


@pytest.mark.parametrize(
    "base",
    [
        "https://model.invalid",
        "https://model.invalid/",
        "https://model.invalid/v1",
        "https://model.invalid/v1/",
    ],
)
def test_messages_endpoint_has_single_version_prefix(base: str) -> None:
    assert messages_endpoint(base) == "https://model.invalid/v1/messages"


def test_child_quota_stops_batch_without_relying_on_display_text() -> None:
    assert (
        check_budget([{"terminal_http_statuses": [429]}], reported_token_limit=100)
        == "model_service_limit"
    )
    assert check_budget([{"message": "tool output says 429"}], reported_token_limit=100) is None
