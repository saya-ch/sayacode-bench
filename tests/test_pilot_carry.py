"""旧 pilot 的封闭证据夹具：检查身份、完整覆盖、原 null 和真实引用链。"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from sayacode_bench import pilot_carry as pc


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False) + "\n").encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@pytest.fixture
def evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """仅替换测试夹具的字节锚点；生产 API 没有接受另一套事件身份的参数。"""
    root = tmp_path / "old-bundle"
    derived = root / "inputs" / "restart-v2"
    derived.mkdir(parents=True)
    original_paths = {key: value[0] for key, value in pc._ORIGINAL_MEMBERS.items()}
    code = {
        "adapter": b"    async def install(self):\n        await self.ensure_system_dependencies()\n        await environment.upload_file()\n    async def _upload(self):\n        pass\n",
        "harbor_base": b"await self.install(environment)\n",
        "harbor_trial": b"await self._prepare()\nawait self._run()\n",
        "harbor_metadata": b"Metadata-Version: 2.1\nName: harbor\nVersion: 0.24.0\n",
    }
    record = ""
    for key, filename in (
        ("harbor_base", "harbor/agents/installed/base.py"),
        ("harbor_trial", "harbor/trial/trial.py"),
    ):
        value = base64.urlsafe_b64encode(hashlib.sha256(code[key]).digest()).rstrip(b"=").decode()
        record += f"{filename},sha256={value},{len(code[key])}\n"
    code["harbor_record"] = record.encode()
    monkeypatch.setattr(pc, "_CODE_SHA256", {key: digest(value) for key, value in code.items()})
    code_refs = {}
    for key, value in code.items():
        (derived / key).write_bytes(value)
        code_refs[key] = {"path": key, "sha256": digest(value)}
    rows = []
    for index, (input_tokens, output_tokens, read_tokens) in enumerate(
        ((331414, 6817, 304512), (395691, 6155, 371712), (345036, 5482, 323200))
    ):
        relative = f"evidence/usage-{index}.json"
        target = root / relative
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(encoded({"input_tokens": input_tokens}))
        rows.append(
            {
                "request_sha256": pc._REQUESTS[index],
                "status": "completed",
                "record_complete": True,
                "usage_complete": True,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_usage": {
                    "status": "complete",
                    "coverage_complete": True,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": read_tokens,
                },
                "usage": {"missing_usage_calls": 0, "damaged_audit_lines": 0},
                "usage_details": {
                    "path": pc.NATIVE_BUNDLE + "/" + relative,
                    "sha256": digest(target.read_bytes()),
                },
            }
        )
    rows.append(
        {
            "request_sha256": pc._REQUESTS[3],
            "status": "infrastructure_error",
            "verified": False,
            "worker_status": None,
            "original_reward": None,
            "input_tokens": None,
            "output_tokens": None,
            "usage_complete": False,
            "usage": {},
            "replay_status": "missing_patch",
            "cache_usage": {
                key: None
                for key in ("model_calls", "input_tokens", "output_tokens", "total_tokens")
            },
            "worker_result": {"sha256": None},
            "usage_details": {"sha256": None},
        }
    )
    lines = [encoded(row) for row in rows]
    monkeypatch.setattr(pc, "_ROW_SHA256", tuple(digest(line) for line in lines))
    monkeypatch.setattr(pc, "_PAID_SHA256", digest(b"".join(lines[:3])))
    trace = "\n".join(
        (
            "await self._prepare()",
            "await self._setup_agent()",
            "await self.install(environment)",
            'adapter.py", line 64, in install',
            "ensure_system_dependencies",
            "exec_as_root",
            "exit 100",
            "apt-get update && apt-get install -y ca-certificates",
            "404  Not Found",
            "ca-certificates_20250419%7edeb12u1%7edeb11u1_all.deb",
        )
    )
    original: dict[str, Any] = {
        "master": {"implementation": {"adapter.py": pc._CODE_SHA256["adapter"]}},
        "plan": {"master": {"sha256": pc._MASTER}, "schedule": [{}] * 48},
        "records3": b"".join(lines[:3]),
        "records4": b"".join(lines),
        "ledger3": {
            "phase_records": rows[:3],
            "paid_records": [],
            "unresolved_execution": False,
            "plan_sha256": pc._PLAN,
        },
        "ledger4": {
            "phase_records": rows,
            "paid_records": [],
            "unresolved_execution": True,
            "plan_sha256": pc._PLAN,
        },
        "receipt3": {"complete": True, "plan_sha256": pc._PLAN},
        "receipt4": {
            "complete": False,
            "continuation_allowed": False,
            "stop_reason": "trial_infrastructure_failure",
            "plan_sha256": pc._PLAN,
        },
        "failed_trial": {
            "id": pc._INCIDENT["failed_trial_id"],
            "agent_execution": None,
            "verifier": None,
            "agent_result": None,
            "verifier_result": None,
            "exception_info": {
                "exception_type": "NonZeroAgentExitCodeError",
                "exception_traceback": trace,
                "occurred_at": "2026-10-23T14:13:38.641319Z",
            },
            "environment_setup": {
                "started_at": "2026-10-23T14:13:33Z",
                "finished_at": "2026-10-23T14:13:35Z",
            },
            "agent_setup": {
                "started_at": "2026-10-23T14:13:35Z",
                "finished_at": "2026-10-23T14:13:38Z",
            },
        },
        "traceback": trace.encode(),
        "failed_job": {
            "stats": {
                "n_retries": 0,
                "evals": {"one": {"n_trials": 0, "n_errors": 1, "reward_stats": {}}},
            }
        },
        "harbor_lock": {
            "harbor": {"version": "0.24.0", "is_editable": False},
            "retry": {"max_retries": 0},
        },
        "network4": {"history": [{"mode": "public"}], "cleanup_errors": []},
        "dispatch4": {
            "actions_identity": {"run_id": 39966021053, "run_attempt": 1, "job_key": "shard_0004"},
            "credential_cleanup_confirmed": True,
        },
        "budget4": {
            "known_estimate_cny": 0.33304296,
            "historical_settled_cny": 0.62,
            "budget_consumed_cny": 0.95304296,
            "paid_model_calls": None,
            "missing_usage_calls": None,
            "total_bill_cny": None,
            "usage_complete": False,
            "incomplete_paid_records": 1,
            "stop_reason": "paid_usage_incomplete",
        },
    }
    for label, target in (
        ("receipt3", "previous_receipt"),
        ("ledger3", "ledger_before_sha256"),
        ("ledger4", "ledger_after"),
    ):
        value = digest(encoded(original[label]))
        original["receipt4"][target] = (
            value if target == "ledger_before_sha256" else {"sha256": value}
        )
    anchors = {}
    for label, value in original.items():
        raw = value if isinstance(value, bytes) else encoded(value)
        target = root / original_paths[label]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        anchors[label] = (original_paths[label], digest(raw))
    monkeypatch.setattr(pc, "_ORIGINAL_MEMBERS", anchors)
    decision = {
        "original_study": {"public_source_sha": pc._SOURCE, "master_sha256": pc._MASTER},
        "financial_continuity": {"future_unknown_usage_allowed": False},
    }
    (derived / "decision.json").write_bytes(encoded(decision))
    monkeypatch.setattr(pc, "_DECISION_SHA256", digest(encoded(decision)))
    (derived / "paid-records.jsonl").write_bytes(b"".join(lines[:3]))
    receipt = {
        "schema_version": 1,
        "kind": "d877_prefix4_pilot_carry_v1",
        "incident": copy.deepcopy(pc._INCIDENT),
        "boundaries": copy.deepcopy(pc._BOUNDARIES),
        "decision": {"path": "decision.json", "sha256": pc._DECISION_SHA256},
        "original_members": {
            key: {"path": pc.NATIVE_BUNDLE + "/" + relative, "sha256": sha}
            for key, (relative, sha) in anchors.items()
        },
        "code_evidence": code_refs,
        "paid_records": {"path": "paid-records.jsonl", "sha256": pc._PAID_SHA256},
    }
    return {
        "root": root,
        "derived": derived,
        "receipt": receipt,
        "original": original,
        "rows": rows,
    }


def validate(evidence: dict[str, Any]) -> list[dict[str, str]]:
    path = evidence["derived"] / "pilot-carry.json"
    raw = encoded(evidence["receipt"])
    path.write_bytes(raw)
    return pc.validate_pilot_carry(
        {"path": str(path), "sha256": digest(raw)}, bundle_root=evidence["root"]
    )


def test_exact_projection_reopens_original_usage(evidence: dict[str, Any]) -> None:
    before = (evidence["root"] / pc._ORIGINAL_MEMBERS["records4"][0]).read_bytes()
    assert validate(evidence) == [
        {
            "path": str((evidence["derived"] / "paid-records.jsonl").resolve()),
            "sha256": pc._PAID_SHA256,
        }
    ]
    assert (evidence["root"] / pc._ORIGINAL_MEMBERS["records4"][0]).read_bytes() == before
    assert json.loads(before.splitlines()[3])["input_tokens"] is None


@pytest.mark.parametrize(
    "label", ["records4", "ledger4", "failed_trial", "traceback", "master", "harbor_lock"]
)
def test_original_tamper_cannot_be_reauthorized_by_receipt(
    evidence: dict[str, Any], label: str
) -> None:
    original = evidence["root"] / pc._ORIGINAL_MEMBERS[label][0]
    original.write_bytes(original.read_bytes() + b" ")
    evidence["receipt"]["original_members"][label]["sha256"] = digest(original.read_bytes())
    with pytest.raises(ValueError, match="成员身份"):
        validate(evidence)


@pytest.mark.parametrize("label", ["records4", "ledger4", "traceback", "failed_trial", "dispatch4"])
def test_missing_evidence_is_not_accepted(evidence: dict[str, Any], label: str) -> None:
    del evidence["receipt"]["original_members"][label]
    with pytest.raises(ValueError, match="完整覆盖"):
        validate(evidence)


@pytest.mark.parametrize("mutation", ["two", "four", "duplicate", "reformatted"])
def test_prior_requires_exact_three_original_lines(evidence: dict[str, Any], mutation: str) -> None:
    rows = evidence["rows"]
    data = {
        "two": b"".join(map(encoded, rows[:2])),
        "four": b"".join(map(encoded, rows)),
        "duplicate": encoded(rows[0]) * 3,
        "reformatted": b"".join((json.dumps(row, indent=2) + "\n").encode() for row in rows[:3]),
    }[mutation]
    (evidence["derived"] / "paid-records.jsonl").write_bytes(data)
    evidence["receipt"]["paid_records"]["sha256"] = digest(data)
    with pytest.raises(ValueError, match="固定证据"):
        validate(evidence)


@pytest.mark.parametrize(
    "key,value",
    [
        ("future_missing_usage_allowed", True),
        ("measured_api_calls", 0),
        ("supplier_bill_verified", True),
        ("harbor_cloud_runtime_source_sha_verified", True),
    ],
)
def test_boundary_cannot_become_general_or_measured_zero(
    evidence: dict[str, Any], key: str, value: Any
) -> None:
    evidence["receipt"]["boundaries"][key] = value
    with pytest.raises(ValueError, match="证据边界"):
        validate(evidence)


@pytest.mark.parametrize(
    "key,value",
    [
        ("run_id", 39966021054),
        ("public_source_sha", "a" * 40),
        ("failed_sequence", 5),
        ("old_master_sha256", "a" * 64),
    ],
)
def test_not_a_future_setup_failure_whitelist(
    evidence: dict[str, Any], key: str, value: Any
) -> None:
    evidence["receipt"]["incident"][key] = value
    with pytest.raises(ValueError, match="事件身份"):
        validate(evidence)


@pytest.mark.parametrize("remove", [True, False])
def test_usage_must_exist_at_original_path(evidence: dict[str, Any], remove: bool) -> None:
    path = evidence["root"] / "evidence/usage-0.json"
    if remove:
        path.unlink()
    else:
        path.write_bytes(b"{}")
    with pytest.raises(ValueError):
        validate(evidence)


@pytest.mark.parametrize("key", ["agent_execution", "agent_result", "verifier", "verifier_result"])
def test_positive_phase_proof_rejects_execution_conflict(
    evidence: dict[str, Any], key: str
) -> None:
    originals = {
        k: v if isinstance(v, bytes) else encoded(v) for k, v in evidence["original"].items()
    }
    raw = json.loads(originals["failed_trial"])
    raw[key] = {"started_at": "2026-10-23T14:13:38Z"}
    originals["failed_trial"] = encoded(raw)
    with pytest.raises(ValueError, match="执行冲突"):
        pc._failed_trial(originals, evidence["rows"][3])


@pytest.mark.parametrize(
    "key", ["input_tokens", "output_tokens", "original_reward", "worker_status"]
)
def test_failed_original_null_cannot_be_zero(evidence: dict[str, Any], key: str) -> None:
    originals = {
        k: v if isinstance(v, bytes) else encoded(v) for k, v in evidence["original"].items()
    }
    row = copy.deepcopy(evidence["rows"][3])
    row[key] = 0
    with pytest.raises(ValueError, match="原 null"):
        pc._failed_trial(originals, row)


def test_worker_evidence_conflicts_with_not_started(evidence: dict[str, Any]) -> None:
    path = evidence["root"] / pc._TRIAL4 / "agent/sayacode/usage-details.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"{}")
    with pytest.raises(ValueError, match="未进入 worker"):
        validate(evidence)


@pytest.mark.parametrize(
    "path",
    [
        "../paid-records.jsonl",
        "/tmp/paid-records.jsonl",
        "C:/tmp/paid-records.jsonl",
        "..\\paid-records.jsonl",
    ],
)
def test_derived_path_cannot_escape(evidence: dict[str, Any], path: str) -> None:
    evidence["receipt"]["paid_records"]["path"] = path
    with pytest.raises(ValueError, match="相对路径"):
        validate(evidence)


def test_duplicate_json_fields_fail_closed(evidence: dict[str, Any]) -> None:
    path = evidence["derived"] / "bad.json"
    raw = b'{"kind":"one","kind":"two"}'
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="重复字段"):
        pc.validate_pilot_carry(
            {"path": str(path), "sha256": digest(raw)}, bundle_root=evidence["root"]
        )


def test_wrong_top_receipt_sha(evidence: dict[str, Any]) -> None:
    path = evidence["derived"] / "bad.json"
    path.write_bytes(encoded(evidence["receipt"]))
    with pytest.raises(ValueError, match="SHA256"):
        pc.validate_pilot_carry(
            {"path": str(path), "sha256": "0" * 64}, bundle_root=evidence["root"]
        )


def test_production_authority_is_one_fixed_incident() -> None:
    assert pc._INCIDENT["run_id"] == 39966021053
    assert (
        pc._INCIDENT["archive_sha256"]
        == "43297de79dd5d5016d1d7bb31420b11c42957b48eb155e7e53742e12776369c4"
    )
    assert (
        pc._ORIGINAL_MEMBERS["records4"][1]
        == "e5a774012aa101c76d9b642d51292077222d47bce25255f4f31c474405a4fc83"
    )
    assert pc._BOUNDARIES["future_missing_usage_allowed"] is False
    assert pc._BOUNDARIES["harbor_cloud_runtime_source_sha_verified"] is False
