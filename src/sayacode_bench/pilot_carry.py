"""只验证 d877 的四条旧先导；不提供未来安装失败或未知用量的通用豁免。

原 tar 在派生时完整核验；运行时重开固定成员及逐条引用，校验原字节身份。
Harbor 控制流程来自相同发行物的 RECORD 重建，不冒称旧云 VM 源码实测。
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import ntpath
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

from .artifacts import file_sha256

NATIVE_BUNDLE = "/tmp/sayacode-studies/deepseek-v41-20261023"
_SOURCE = "d8778bd41ed8adc9d7d09486fe5d59cdd4fd4469"
_MASTER = "a90fb1e87df978df95d131abc20f666f86ccc0559bd4dd142984d3756324d876"
_PLAN = "5ecc397db94c3da17e5ab904c0486d817d10e6812e82573463c6110a0a9bb30c"
_DECISION_SHA256 = "0cc332265855d8a7deaca9b031c14aca741f1c8481f2b6a76aa714f771bafdea"
_PAID_SHA256 = "a8d8803e801b6493ac5bd395852b79f7f8b7a2f00e4690a7525cc6a965187c01"
_S3 = "shards/dev-0003-36ba31e6ffa0"
_S4 = "shards/dev-0004-7c9124a3a899"
_JOB4 = _S4 + "/run/jobs/dev-0004-diagnostic-2"
_TRIAL4 = _JOB4 + "/instance_element-hq__element-web__tLZGeW5"
_INCIDENT = {
    "public_source_sha": _SOURCE,
    "old_master_sha256": _MASTER,
    "old_plan_sha256": _PLAN,
    "run_id": 39966021053,
    "private_source_sha": "1159e1df2130165569b491ca9cfbafc4e3ad8862",
    "archive_sha256": "43297de79dd5d5016d1d7bb31420b11c42957b48eb155e7e53742e12776369c4",
    "archive_bytes": 93346371,
    "original_bundle_root": NATIVE_BUNDLE,
    "original_records": 4,
    "carried_records": 3,
    "failed_sequence": 4,
    "failed_trial_id": "4e22363c-763a-415a-bc51-67526e1ff2b3",
}
_BOUNDARIES = {
    "archive_rehashed_at_derivation": True,
    "runtime_check": "fixed_original_members_and_live_record_references_sha256",
    "model_execution": "not_started_verified_for_this_frozen_adapter_path",
    "usage_applicability": "not_applicable_not_executed",
    "original_null_usage_preserved": True,
    "measured_api_calls": None,
    "supplier_bill_verified": False,
    "future_missing_usage_allowed": False,
    "old_scores_reused": False,
    "harbor_code_provenance": "local_distribution_RECORD_reconstruction",
    "harbor_cloud_runtime_source_sha_verified": False,
}
_ROW_SHA256 = (
    "180ec9587bd4c35850c04db3227f857f94a709ccdf773939c990e3ce4bbffc0a",
    "feaac913d7849514f00de625952c69043de079ee1b52659d56ad955126165132",
    "1643aaef14b7a29e911d0e8c777fd9b8b39b78d209bcd9b314385aa43af245a9",
    "75a1511507b5d092577e0d83a94f7bf6555c56ac6d39e7e2dc00a76ae534f775",
)
_REQUESTS = (
    "42ef0d748091453383b95cf3927b5fdeec5874e76304462857e8d8629f16a7e7",
    "76cc259704b4285b8c2d09808949fd3e342a2aaa4aedf22af59853634b9a0297",
    "ce2bbaa924bee48e1c70e53f3c0e4b8b78ab2636a37d013cd895c81858cf96b3",
    "cd16a317c00e8122fc87202ea0a682ec6129ab9d0147caf0d0ed2af56b8080d4",
)
# 此表由已完整核验的唯一原 tar 派生；不能由收据提供另一组期望身份。
_ORIGINAL_MEMBERS = {
    "master": ("inputs/primary-dev.json", _MASTER),
    "plan": ("primary-dev-plan.json", _PLAN),
    "records3": (_S3 + "/run/records.jsonl", _PAID_SHA256),
    "records4": (
        _S4 + "/run/records.jsonl",
        "e5a774012aa101c76d9b642d51292077222d47bce25255f4f31c474405a4fc83",
    ),
    "ledger3": (
        _S3 + "/ledger.json",
        "cf46c76ee5e38056c81db2f40a21414dd10e7a3b31f08809bb8192d469237c97",
    ),
    "ledger4": (
        _S4 + "/ledger.json",
        "5498ed3eeeb9ff4193c1e0db4b788fdfb425bd52cf3f28cca9a8253b3a1ab32f",
    ),
    "receipt3": (
        _S3 + "/shard-receipt.json",
        "2a6f1e55fb70066dd78f8a4b56c19f650dfa1dcd11332ab80fc054288aed34f8",
    ),
    "receipt4": (
        _S4 + "/shard-receipt.json",
        "f107f89cf59bd38e8e7ddca34cb840316ac858119f3a0f45915c7be4d5ddda3e",
    ),
    "budget4": (
        _S4 + "/run/budget.json",
        "2fbc2a69aebb3a57ca248b0d5117a00065d43cec9891a16afe81d4c6a134de41",
    ),
    "failed_trial": (
        _TRIAL4 + "/result.json",
        "3ba7a6af20f4944348728df873eae0ba0de9e5ac9f72aa38017d8ffd82fcc92e",
    ),
    "failed_job": (
        _JOB4 + "/result.json",
        "4a170fbe82ee1eb8b84627d51bd9e61883ca540981a1ba3f9b781619cf37e531",
    ),
    "harbor_lock": (
        _JOB4 + "/lock.json",
        "d98d420520dd35a2062c73d590c21b2edcbff8863af76b7bc2da720606573c05",
    ),
    "traceback": (
        _TRIAL4 + "/exception.txt",
        "0f48f6e380ff5e100c79cd31f7662dba506b0425409d0da95d49864dee93ce62",
    ),
    "network4": (
        _TRIAL4 + "/network-isolation.json",
        "0d2c620bd959c223ab5044362593705761fa50d3bfeca88cd2561471e7924679",
    ),
    "dispatch4": (
        "orchestration/dev-0004-7c9124a3a899/dispatch.json",
        "dd110c5ba6a7d4d4344c5e386685933213aab37b8e66a564224982c1d4744b25",
    ),
}
_CODE_SHA256 = {
    "adapter": "8251a3cfae0f48c1345bde5d06064aa3df920dc256f1bd4aab22230c1d06b293",
    "harbor_base": "31a7721e0cfa5522f85056439495b9741e2232869537f9ec21fb9ac95b611647",
    "harbor_trial": "3bb2c0b9dd7553022ba98da96ef5188abc27e2c8475ac949d541f47c5d86ecc6",
    "harbor_record": "9de07f7993260a76bc75e8005f91da7657707e566da6fde6f5db5bce504e98db",
    "harbor_metadata": "7b295ee5accbd7a28e08c63b0b9817dbe1b696f22e1fd920e9d5548938e16af9",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("旧 pilot carry：" + message)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        _require(key not in result, "JSON 存在重复字段")
        result[key] = value
    return result


def _object(content: bytes) -> dict[str, Any]:
    value = json.loads(content, object_pairs_hook=_pairs)
    if not isinstance(value, dict):
        raise ValueError("旧 pilot carry：证据必须为 JSON 对象")
    return value


def _reference(value: Any) -> tuple[str, str]:
    _require(isinstance(value, Mapping) and set(value) == {"path", "sha256"}, "文件引用格式无效")
    path, expected = value["path"], value["sha256"]
    _require(isinstance(path, str) and bool(path), "文件路径缺失")
    _require(
        isinstance(expected, str)
        and len(expected) == 64
        and all(c in "0123456789abcdef" for c in expected),
        "文件 SHA256 无效",
    )
    return path, expected


def _read(path: Path, expected: str, *, inside: Path | None = None) -> bytes:
    resolved = path.resolve(strict=True)
    _require(resolved.is_file(), "证据不是普通文件")
    if inside is not None:
        _require(resolved.is_relative_to(inside.resolve(strict=True)), "证据路径越界")
    # 所有解析对象均为小元数据或码源；不解析原模型输出或题面。
    _require(resolved.stat().st_size <= 4 * 1024 * 1024, "元数据大小异常")
    data = resolved.read_bytes()
    _require(hashlib.sha256(data).hexdigest() == expected, "原件 SHA256 不符")
    return data


def _relative(value: Any, base: Path, expected: str | None = None) -> tuple[bytes, Path]:
    path, digest = _reference(value)
    relative = PurePosixPath(path)
    _require(
        not relative.is_absolute()
        and not ntpath.splitdrive(path)[0]
        and "\\" not in path
        and ".." not in relative.parts,
        "派生证据须使用收据目录内的相对路径",
    )
    if expected is not None:
        _require(digest == expected, "不能替换固定证据的期望 SHA")
    target = base.joinpath(*relative.parts)
    return _read(target, digest, inside=base), target.resolve(strict=True)


def _original_path(path: str, root: Path) -> Path:
    relative = PurePosixPath(path).relative_to(PurePosixPath(NATIVE_BUNDLE))
    _require(".." not in relative.parts and "\\" not in path, "原件引用越出固定旧 bundle")
    target = root.joinpath(*relative.parts).resolve(strict=True)
    _require(target.is_relative_to(root.resolve(strict=True)), "原件引用通过链接越界")
    return target


def _live_references(value: Any, root: Path) -> None:
    """只对非空哈希读取原路径字节；原 null 从不改为零或伪称已核验。"""
    if isinstance(value, Mapping):
        if isinstance(value.get("path"), str) and value.get("sha256") is not None:
            path, expected = _reference(value)
            target = _original_path(path, root)
            _require(file_sha256(target) == expected, "source/usage/runtime 等原路径引用 SHA 不符")
        for child in value.values():
            _live_references(child, root)
    elif isinstance(value, list):
        for child in value:
            _live_references(child, root)


def _nulls(value: Mapping[str, Any], keys: tuple[str, ...]) -> None:
    _require(all(key in value and value[key] is None for key in keys), "原 null 缺失或出现执行冲突")


def _code_proof(code: dict[str, bytes]) -> None:
    metadata = code["harbor_metadata"].decode("utf-8")
    _require(
        "\nName: harbor\n" in "\n" + metadata and "\nVersion: 0.24.0\n" in metadata,
        "Harbor 发行物版本不符",
    )
    rows = list(csv.reader(io.StringIO(code["harbor_record"].decode("utf-8"))))
    for label, filename in (
        ("harbor_base", "harbor/agents/installed/base.py"),
        ("harbor_trial", "harbor/trial/trial.py"),
    ):
        matching = [row for row in rows if row and row[0] == filename]
        encoded = (
            base64.urlsafe_b64encode(hashlib.sha256(code[label]).digest()).rstrip(b"=").decode()
        )
        _require(
            len(matching) == 1
            and len(matching[0]) == 3
            and matching[0][1] == "sha256=" + encoded
            and matching[0][2] == str(len(code[label])),
            "Harbor 码源与本地发行物 RECORD 不一致",
        )
    adapter = code["adapter"].decode("utf-8")
    install = adapter.split("    async def install(", 1)[1].split("    async def _upload(", 1)[0]
    _require(
        install.index("await self.ensure_system_dependencies")
        < install.index("await environment.upload_file"),
        "固定 adapter 的安装控制流程不符",
    )
    trial = code["harbor_trial"].decode("utf-8")
    _require(
        trial.index("await self._prepare()") < trial.index("await self._run()"),
        "Harbor prepare/run 顺序不符",
    )
    _require(
        b"await self.install(environment)" in code["harbor_base"], "Harbor setup/install 证据缺失"
    )


def _failed_trial(originals: dict[str, bytes], row: dict[str, Any]) -> None:
    raw = _object(originals["failed_trial"])
    _require(raw.get("id") == _INCIDENT["failed_trial_id"], "不是本次失败的唯一 trial")
    _nulls(raw, ("agent_execution", "verifier", "agent_result", "verifier_result"))
    _nulls(row, ("worker_status", "original_reward", "input_tokens", "output_tokens"))
    _require(
        row.get("status") == "infrastructure_error"
        and row.get("verified") is False
        and row.get("usage_complete") is False
        and row.get("usage") == {}
        and row.get("replay_status") == "missing_patch",
        "失败记录的未知用量或不可评分状态被改写",
    )
    _nulls(row["cache_usage"], ("model_calls", "input_tokens", "output_tokens", "total_tokens"))
    _nulls(row["worker_result"], ("sha256",))
    _nulls(row["usage_details"], ("sha256",))
    exc = raw["exception_info"]
    trace = exc["exception_traceback"]
    _require(exc.get("exception_type") == "NonZeroAgentExitCodeError", "原生错误类型不符")
    _require(
        originals["traceback"].decode("utf-8").strip() == trace.strip()
        and all(
            fragment in trace
            for fragment in (
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
        ),
        "缺少安装阶段的正面 traceback 证据",
    )
    times = [
        raw[phase][edge]
        for phase in ("environment_setup", "agent_setup")
        for edge in ("started_at", "finished_at")
    ]
    times.append(exc["occurred_at"])
    parsed = [datetime.fromisoformat(item) for item in times]
    _require(
        all(item.utcoffset() is not None for item in parsed) and parsed == sorted(parsed),
        "原生阶段时间冲突",
    )
    lock = _object(originals["harbor_lock"])
    _require(
        lock.get("harbor") == {"version": "0.24.0", "is_editable": False}
        and lock["retry"]["max_retries"] == 0,
        "原生 Harbor 版本或重试记录不符",
    )
    job = _object(originals["failed_job"])
    stats = job["stats"]
    evaluations = list(stats["evals"].values())
    _require(
        stats["n_retries"] == 0
        and len(evaluations) == 1
        and evaluations[0]["n_trials"] == 0
        and evaluations[0]["n_errors"] == 1
        and evaluations[0]["reward_stats"] == {},
        "失败 job 出现评分或重试冲突",
    )


def validate_pilot_carry(
    reference: Mapping[str, Any], *, bundle_root: Path | None = None
) -> list[dict[str, str]]:
    """freeze/load 共用的只读检查，返回唯一、稳定的前三行 prior 引用。

    正式运行默认原 Linux bundle；bundle_root 仅供本机原件映射核验，既不改原
    JSON 路径，也不改变任何固定身份。调用方须把返回引用纳入预算 prior_records，
    不得用这些先导成绩作为新阶段成绩；未来未知用量仍使用原停止规则。
    """
    try:
        return _validate(reference, bundle_root=bundle_root)
    except (OSError, KeyError, TypeError, IndexError, UnicodeError) as error:
        raise ValueError("旧 pilot carry：原件缺失或证据结构无效") from error


def _validate(reference: Mapping[str, Any], *, bundle_root: Path | None) -> list[dict[str, str]]:
    filename, digest = _reference(reference)
    path = Path(filename).resolve(strict=True)
    receipt = _object(_read(path, digest))
    _require(
        set(receipt)
        == {
            "schema_version",
            "kind",
            "incident",
            "boundaries",
            "decision",
            "original_members",
            "code_evidence",
            "paid_records",
        },
        "收据字段不符",
    )
    _require(
        type(receipt["schema_version"]) is int
        and receipt["schema_version"] == 1
        and receipt["kind"] == "d877_prefix4_pilot_carry_v1",
        "不是本次专用收据",
    )

    # JSON 字节化比较也拒绝把 False/None 伪装为 0 或遗漏字段。
    def equal(a: Any, b: Any) -> bool:
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    _require(
        equal(receipt["incident"], _INCIDENT) and equal(receipt["boundaries"], _BOUNDARIES),
        "事件身份或证据边界被改变",
    )
    decision_raw, _ = _relative(receipt["decision"], path.parent, _DECISION_SHA256)
    decision = _object(decision_raw)
    _require(
        decision["original_study"]["public_source_sha"] == _SOURCE
        and decision["original_study"]["master_sha256"] == _MASTER
        and decision["financial_continuity"]["future_unknown_usage_allowed"] is False,
        "恢复决定不适用于本事件",
    )
    root = (bundle_root if bundle_root is not None else Path(NATIVE_BUNDLE)).resolve(strict=True)
    _require(
        set(receipt["original_members"]) == set(_ORIGINAL_MEMBERS) and bool(_ORIGINAL_MEMBERS),
        "原四条及阶段证据未完整覆盖",
    )
    originals: dict[str, bytes] = {}
    for label, (relative, expected) in _ORIGINAL_MEMBERS.items():
        fixed = {"path": NATIVE_BUNDLE + "/" + relative, "sha256": expected}
        _require(receipt["original_members"][label] == fixed, "原件成员身份被替换")
        originals[label] = _read(_original_path(fixed["path"], root), expected, inside=root)
    _require(set(receipt["code_evidence"]) == set(_CODE_SHA256), "码源证明不完整")
    code = {
        key: _relative(receipt["code_evidence"][key], path.parent, expected)[0]
        for key, expected in _CODE_SHA256.items()
    }
    _code_proof(code)
    lines = originals["records4"].splitlines(keepends=True)
    _require(
        len(lines) == 4
        and tuple(hashlib.sha256(line).hexdigest() for line in lines) == _ROW_SHA256,
        "原四行身份、完整覆盖或原字节被改变",
    )
    rows = [_object(line) for line in lines]
    _require(tuple(row.get("request_sha256") for row in rows) == _REQUESTS, "旧请求身份不符或重复")
    _require(originals["records3"] == b"".join(lines[:3]), "前三行不是原记录的精确前缀")
    paid, paid_path = _relative(receipt["paid_records"], path.parent, _PAID_SHA256)
    _require(paid == b"".join(lines[:3]), "prior_records 必须为前三行逐字节投影")
    ledger3, ledger4 = _object(originals["ledger3"]), _object(originals["ledger4"])
    _require(
        ledger3["phase_records"] == rows[:3]
        and ledger4["phase_records"] == rows
        and ledger3["paid_records"] == ledger4["paid_records"] == []
        and ledger3["unresolved_execution"] is False
        and ledger4["unresolved_execution"] is True,
        "原账本覆盖或未知执行状态不符",
    )
    rec3, rec4 = _object(originals["receipt3"]), _object(originals["receipt4"])
    _require(
        rec3["complete"] is True
        and rec4["complete"] is False
        and rec4["continuation_allowed"] is False
        and rec4["stop_reason"] == "trial_infrastructure_failure",
        "原失败 receipt 被改写",
    )
    _require(
        rec4["previous_receipt"]["sha256"] == hashlib.sha256(originals["receipt3"]).hexdigest()
        and rec4["ledger_before_sha256"] == hashlib.sha256(originals["ledger3"]).hexdigest()
        and rec4["ledger_after"]["sha256"] == hashlib.sha256(originals["ledger4"]).hexdigest(),
        "receipt/ledger 链不符",
    )
    master, plan = _object(originals["master"]), _object(originals["plan"])
    _require(
        master["implementation"]["adapter.py"] == _CODE_SHA256["adapter"]
        and plan["master"]["sha256"] == _MASTER
        and len(plan["schedule"]) == 48
        and all(item["plan_sha256"] == _PLAN for item in (rec3, rec4, ledger3, ledger4)),
        "旧 source/master/plan 不符",
    )
    dispatch = _object(originals["dispatch4"])
    _require(
        dispatch["actions_identity"]
        == {"run_id": 39966021053, "run_attempt": 1, "job_key": "shard_0004"}
        and dispatch["credential_cleanup_confirmed"] is True,
        "原运行身份或收尾证据不符",
    )
    _failed_trial(originals, rows[3])
    network = _object(originals["network4"])
    _require(
        [item["mode"] for item in network["history"]] == ["public"]
        and network["cleanup_errors"] == [],
        "出现模型网络阶段或清理冲突",
    )
    # 实际重开旧绝对路径中的证据；不能只有一份自述 sidecar。
    _live_references(rows, root)
    _live_references(rec3, root)
    _live_references(rec4, root)
    for filename in ("result.json", "usage-details.json", "audit.jsonl", "worker.log"):
        _require(
            not (root / _TRIAL4 / "agent" / "sayacode" / filename).exists(),
            "发现与未进入 worker 相冲突的原件",
        )
    known = Decimal(0)
    for row in rows[:3]:
        cache, usage = row["cache_usage"], row["usage"]
        _require(
            row["status"] == "completed"
            and row["record_complete"] is True
            and row["usage_complete"] is True
            and cache["status"] == "complete"
            and cache["coverage_complete"] is True
            and cache["cache_creation_input_tokens"] == 0
            and usage["missing_usage_calls"] == usage["damaged_audit_lines"] == 0,
            "已知三条存在不完整计量",
        )
        known += (
            Decimal(row["input_tokens"] - cache["cache_read_input_tokens"]) * 2
            + Decimal(cache["cache_read_input_tokens"]) * Decimal("0.04")
            + Decimal(row["output_tokens"]) * 8
        ) / 1_000_000
    budget = _object(originals["budget4"])
    _require(
        known == Decimal("0.33304296")
        and Decimal(str(budget["known_estimate_cny"])) == known
        and Decimal(str(budget["historical_settled_cny"])) == Decimal("0.62")
        and Decimal(str(budget["budget_consumed_cny"])) == Decimal("0.95304296"),
        "已知预算结转不符",
    )
    _nulls(budget, ("paid_model_calls", "missing_usage_calls", "total_bill_cny"))
    _require(
        budget["usage_complete"] is False
        and budget["incomplete_paid_records"] == 1
        and budget["stop_reason"] == "paid_usage_incomplete",
        "旧未知用量停止记录被改写",
    )
    return [{"path": str(paid_path), "sha256": hashlib.sha256(paid).hexdigest()}]
