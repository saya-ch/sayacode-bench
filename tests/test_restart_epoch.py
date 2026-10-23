"""新轮次的离线合同测试；合成收据与替身不构成原生预检或模型成绩。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import test_historical_settlement
from test_budget import record
from test_observed_cache_budget import PROFILES

from sayacode_bench import cli, installation, pilot_carry, study
from sayacode_bench.artifacts import file_sha256, read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
PRICE = ROOT / "studies/prices/siliconflow-deepseek-v4.1-flash-observed-cache-20261023-v3.json"
historical = test_historical_settlement.historical


def reference(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": file_sha256(path)}


@pytest.fixture
def epoch(tmp_path: Path, monkeypatch: Any, historical: dict[str, Any]) -> dict[str, Any]:
    from scripts.analyze_sensitivity import protocol_identity

    paid = tmp_path / "pilot-paid.jsonl"
    paid.write_text(json.dumps(record(1)) + "\n", encoding="utf-8")
    carry, installed = tmp_path / "carry.json", tmp_path / "installed.json"
    write_json(installed, {"offline": "原生安装收据由独立模块测试"})
    monkeypatch.setattr(pilot_carry, "validate_pilot_carry", lambda ref: [reference(paid)])
    monkeypatch.setattr(
        installation, "validate_installation_preflight", lambda *args, **kwargs: {}, raising=False
    )
    arguments = dict(
        limit_cny=100,
        price_snapshot=PRICE,
        prior_records=[paid],
        historical_settlement=historical["path"],
        connection_profiles=PROFILES,
    )
    original = study.freeze_paid_budget(**arguments)
    artifacts = {
        "product_wheel": "a" * 64,
        "requirements": "b" * 64,
        "variants": {key: "c" * 64 for key in ("baseline", "diagnostic", "focused")},
    }
    old = tmp_path / "old-master.json"
    write_json(
        old, {"paid_budget": original, "connection_profiles": PROFILES, "artifacts": artifacts}
    )
    write_json(
        carry,
        {"offline": "费用适用性原件由独立模块测试", "original_members": {"master": reference(old)}},
    )
    policy = study.freeze_paid_budget(**arguments, pilot_carry=carry)
    analysis = tmp_path / "analysis-protocol.json"
    write_json(analysis, protocol_identity())
    return {
        "phase": "dev",
        "benchmark": "swe-bench-pro-v2",
        "tasks": [{"task_id": f"offline-{i}"} for i in range(8)],
        "configurations": ["baseline", "diagnostic", "focused"],
        "repeats": 2,
        "artifacts": artifacts,
        "connection_profiles": deepcopy(PROFILES),
        "implementation": {"offline": True},
        "execution_epoch": {
            "id": "restart-v2",
            "protocol": reference(ROOT / "studies/execution-protocol-v13.json"),
            "analysis_protocol": reference(analysis),
            "installation_preflight": reference(installed),
        },
        "paid_budget": policy,
    }


def test_load_rechecks_complete_installation_and_paid_originals(
    epoch: dict[str, Any], monkeypatch: Any
) -> None:
    calls = []

    def checked(ref: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((ref, kwargs))
        return {}

    monkeypatch.setattr(installation, "validate_installation_preflight", checked)
    policy, rows = study._paid_inputs(epoch)
    assert policy == epoch["paid_budget"] and len(rows) == 1
    assert calls == [
        (
            epoch["execution_epoch"]["installation_preflight"],
            {
                "tasks": epoch["tasks"],
                "artifacts": epoch["artifacts"],
                "implementation": epoch["implementation"],
            },
        )
    ]


@pytest.mark.parametrize("missing", ["protocol", "analysis_protocol", "installation_preflight"])
def test_incomplete_epoch_inputs_never_reach_paid_dispatch(
    epoch: dict[str, Any], missing: str
) -> None:
    epoch["execution_epoch"].pop(missing)
    with pytest.raises((OSError, ValueError)):
        study._paid_inputs(epoch)


def test_carry_cannot_disappear_from_cumulative_budget(epoch: dict[str, Any]) -> None:
    epoch["paid_budget"]["prior_records"] = []
    with pytest.raises(ValueError, match="没有完整延续"):
        study._paid_inputs(epoch)


@pytest.mark.parametrize("field,value", [("limit_cny", 200), ("stop_fraction", 1.0)])
def test_restart_cannot_reset_original_financial_scope(
    epoch: dict[str, Any], field: str, value: Any
) -> None:
    epoch["paid_budget"][field] = value
    with pytest.raises(ValueError, match="百元累计预算"):
        study._paid_inputs(epoch)


def test_restart_cannot_omit_original_historical_settlement(epoch: dict[str, Any]) -> None:
    epoch["paid_budget"].pop("historical_settlement")
    with pytest.raises(ValueError, match="历史核销"):
        study._paid_inputs(epoch)


def test_another_internally_valid_price_cannot_reprice_pilot(epoch: dict[str, Any]) -> None:
    old = epoch["paid_budget"]
    epoch["paid_budget"] = study.freeze_paid_budget(
        limit_cny=100,
        price_snapshot=ROOT / "studies/prices/siliconflow-deepseek-v4.1-flash-20261022.json",
        prior_records=[Path(ref["path"]) for ref in old["prior_records"]],
        historical_settlement=Path(old["historical_settlement"]["path"]),
        pilot_carry=Path(old["pilot_carry"]["path"]),
    )
    with pytest.raises(ValueError, match="原价格"):
        study._paid_inputs(epoch)


def test_restart_cannot_change_original_model_profile(epoch: dict[str, Any]) -> None:
    epoch["connection_profiles"]["remote"]["context_length"] = 1024
    with pytest.raises(ValueError, match="上下文配置"):
        study._paid_inputs(epoch)


@pytest.mark.parametrize("field", ["product_wheel", "requirements", "variants"])
def test_restart_cannot_change_original_package_or_variant(
    epoch: dict[str, Any], field: str
) -> None:
    if field == "variants":
        epoch["artifacts"][field]["focused"] = "f" * 64
    else:
        epoch["artifacts"][field] = "f" * 64
    with pytest.raises(ValueError, match="原生产包"):
        study._paid_inputs(epoch)


def test_old_complete_analysis_identity_cannot_be_relabelled_as_new(epoch: dict[str, Any]) -> None:
    path = Path(epoch["execution_epoch"]["analysis_protocol"]["path"])
    write_json(path, read_json(ROOT / "studies/sensitivity-protocol-v12.json"))
    epoch["execution_epoch"]["analysis_protocol"] = reference(path)
    with pytest.raises(ValueError, match="新轮次分析身份"):
        study._paid_inputs(epoch)


@pytest.mark.parametrize(
    "field,value", [("tasks", []), ("repeats", 1), ("configurations", ["baseline"])]
)
def test_restart_preserves_full_development_denominator(
    epoch: dict[str, Any], field: str, value: Any
) -> None:
    epoch[field] = value
    with pytest.raises(ValueError, match="完整开发"):
        study._paid_inputs(epoch)


def test_changed_preflight_stops_next_dispatch_even_with_cached_paid_rows(
    epoch: dict[str, Any], monkeypatch: Any
) -> None:
    policy, rows = study._paid_inputs(epoch)

    def changed(*args: Any, **kwargs: Any) -> None:
        raise ValueError("原生安装证据发生变化")

    monkeypatch.setattr(installation, "validate_installation_preflight", changed)
    assert (
        study._paid_stop_reason(policy, [], rows, manifest=epoch)
        == "execution_epoch_evidence_changed"
    )
    assert study.paid_budget_report(epoch, [], prior_records=rows)["evidence_valid"] is False


def test_future_missing_model_usage_remains_a_hard_stop(epoch: dict[str, Any]) -> None:
    policy, rows = study._paid_inputs(epoch)
    new = record(2, usage_complete=False, input_tokens=None, output_tokens=None)
    new["usage"].update(reported_calls=0, missing_usage_calls=10)
    assert study._paid_stop_reason(policy, [new], rows, manifest=epoch) == "paid_usage_incomplete"
    assert new["input_tokens"] is None and new["output_tokens"] is None


def test_protocol_is_a_separate_contract_and_v12_statistics_remain_exact(
    epoch: dict[str, Any], tmp_path: Path
) -> None:
    protocol = read_json(Path(epoch["execution_epoch"]["protocol"]["path"]))
    assert protocol["statistical_protocol"] == "sensitivity-protocol-v12.json"
    changed = tmp_path / "changed.json"
    copy = deepcopy(protocol)
    copy["primary_dev"]["trials"] = 2
    write_json(changed, copy)
    epoch["execution_epoch"]["protocol"] = reference(changed)
    with pytest.raises(ValueError, match="执行协议与固定源码"):
        study._paid_inputs(epoch)


def test_old_actual_analysis_identity_is_preserved_without_reusing_execution_identity() -> None:
    from scripts.analyze_sensitivity import protocol_identity

    old = read_json(ROOT / "studies/sensitivity-protocol-v12.json")
    current = protocol_identity()
    assert current != old
    assert current["validation_sha256"] != old["validation_sha256"]
    study.validate_statistical_continuity(old, current)


@pytest.mark.parametrize(
    "field",
    [
        "samples",
        "seed",
        "analysis_sha256",
        "script_sha256",
        "budget_sha256",
        "resource_rules_sha256",
    ],
)
def test_restart_rejects_changed_statistics_even_with_new_execution_identity(field: str) -> None:
    from scripts.analyze_sensitivity import protocol_identity

    old = read_json(ROOT / "studies/sensitivity-protocol-v12.json")
    current = protocol_identity()
    current[field] = "f" * 64 if field.endswith("sha256") else current[field] + 1
    with pytest.raises(ValueError, match="统计、候选或计价"):
        study.validate_statistical_continuity(old, current)


def test_cli_rejects_partial_restart_declaration_before_any_freeze(tmp_path: Path) -> None:
    import argparse

    with pytest.raises(ValueError, match="必须同时声明"):
        cli.freeze(argparse.Namespace(execution_protocol=tmp_path / "protocol.json"))
