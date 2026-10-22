"""私有 GitHub 执行仓库的两题校准入口；执行与重判仍由现有 Harbor 链路承担。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from sayacode_bench.artifacts import (
    fatal_stop_reason,
    file_sha256,
    implementation_identity,
    read_json,
    write_json,
)
from sayacode_bench.budget import budget_reason, estimate_paid_usage
from sayacode_bench.connections import CANONICAL_MODEL
from sayacode_bench.execution import run_official_trial
from sayacode_bench.gates import TASK_IDENTITIES, validate_preflight
from sayacode_bench.network import docker
from sayacode_bench.sources import SOURCES, fetch_source, tree_digest
from sayacode_bench.study import freeze_paid_budget, run_phase

if __package__:
    from .diagnose_wheel import compare_wheels
else:
    from diagnose_wheel import compare_wheels

EXECUTION_REPOSITORY = "saya-ch/sayacode-bench-runs"
REVISION = "66f92766bba642462d4bbe5479e83f91f9211862"
IMAGE_REPOSITORY = "ghcr.io/scaleapi/swe-bench_pro-v2"
FIXTURES = {
    "qutebrowser": (
        "instance_qutebrowser__qutebrowser-3d01c201b8aa54dd71d4f801b1dd12feb4c0a08a-"
        "v5fc38aaf22415ab0b70567368332beee7955b367",
        "sha256:cc0e0f503659eac82afb4f304e853c5a94ddd2aba834e62d3fd757fa6fba13e3",
    ),
    "ansible": (
        "instance_ansible__ansible-de5858f48dc9e1ce9117034e0d7e76806f420ca8-"
        "v1055803c3a812189a1133297f7f5468579283f86",
        "sha256:31ebe11c8cb1c5e3f74b15e0345fce7f9adc7eb406209131828f8b49bf4b7f61",
    ),
}
MIN_DISK_BYTES = 12 * 1024**3
GLOBAL_LIMIT_CNY = 100
CLOUD_LIMIT_CNY = 15
STOP_FRACTION = 0.8
KNOWN_PAID_PROBES = {"remote-chat-20261022T0412Z", "remote-messages-20261022T0416Z"}
PROFILE = {
    "name": "cloud-calibration",
    "protocol": "anthropic_messages",
    "base_url": "https://api.siliconflow.cn",
    "model_id": "deepseek-ai/DeepSeek-V4.1-Flash",
    "context_length": 65536,
    "max_output_tokens": 8192,
    "summary_trigger_ratio": 0.8,
    "summary_keep_messages": 12,
    "context_edit_trigger": None,
    "model_retries": 1,
    "tool_retries": 2,
    "file_search": True,
    "tool_selector_max_tools": None,
}


class ArtifactGateError(ValueError):
    """只携带可公开的工件门禁原因枚举，不附带命令或 HTTP 正文。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def require_private(metadata: dict[str, Any]) -> None:
    """调用方必须先用 GitHub API 获取实时仓库信息；公开或不明身份均拒绝。"""
    if (
        metadata.get("full_name") != EXECUTION_REPOSITORY
        or metadata.get("private") is not True
        or metadata.get("visibility") != "private"
    ):
        raise ValueError("仅允许指定的私有执行仓库")


def source_identity(root: Path, source_sha: str, workflow: Path) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise ValueError("公开源码必须为完整小写提交 SHA，不能使用分支或标签")
    actual = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    if actual != source_sha:
        raise ValueError("公开 checkout 与指定提交不一致")
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--exit-code",
            "HEAD",
            "--",
            "src",
            "scripts",
            "studies",
            "reproduction",
            "pyproject.toml",
            "uv.lock",
        ],
        check=True,
        capture_output=True,
    )
    recorded = subprocess.run(
        ["git", "-C", str(root), "show", "HEAD:scripts/calibrate_cloud.py"],
        check=True,
        capture_output=True,
    ).stdout
    if hashlib.sha256(recorded).hexdigest() != file_sha256(Path(__file__)):
        raise ValueError("校准入口不属于固定公开提交")
    return {
        "public_repository": "saya-ch/sayacode-bench",
        "public_source_sha": source_sha,
        "script_sha256": file_sha256(Path(__file__)),
        "wheel_diagnostic_sha256": file_sha256(Path(__file__).with_name("diagnose_wheel.py")),
        "workflow_sha256": file_sha256(workflow),
        "implementation": implementation_identity(),
    }


def build_baseline(
    root: Path, artifacts: Path, requirements: Path, wheel_input: Path | None = None
) -> dict[str, Any]:
    """显式选择原件；平台重建只作诊断，不能自动替换冻结运行包。"""
    identity = read_json(root / "reproduction" / "identity.json")
    archive = root / "reproduction" / "product-baseline-source.zip"
    if file_sha256(archive) != identity["source_archive_sha256"]:
        raise ArtifactGateError("source_archive_hash_mismatch")
    if not requirements.is_file():
        raise ArtifactGateError("missing_original_requirements")
    if file_sha256(requirements) != identity["requirements_sha256"]:
        raise ArtifactGateError("requirements_hash_mismatch")
    filename = "sayacode-3.2.4-py3-none-any.whl"
    selected = None
    if wheel_input is not None:
        if not wheel_input.is_file():
            raise ArtifactGateError("missing_original_wheel")
        if file_sha256(wheel_input) != identity["production_wheel_sha256"]:
            raise ArtifactGateError("original_wheel_hash_mismatch")
        # 私有输入名可为 product-baseline.whl；仅保字节复制为 pip 接受的规范文件名。
        selected = artifacts / "original" / filename
        selected.parent.mkdir(parents=True, exist_ok=True)
        if selected.exists() and file_sha256(selected) != identity["production_wheel_sha256"]:
            raise ArtifactGateError("original_wheel_cache_hash_mismatch")
        if not selected.exists():
            shutil.copyfile(wheel_input, selected)
    rebuilt = artifacts / "wheel" / filename
    if not rebuilt.exists():
        source = artifacts / "baseline-source"
        source.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(archive) as contents:
            for item in contents.infolist():
                path = PurePosixPath(item.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in item.filename
                    or ":" in item.filename
                    or stat.S_ISLNK(item.external_attr >> 16)
                ):
                    raise ArtifactGateError("source_archive_path_rejected")
            contents.extractall(source)
        rebuilt.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["uv", "build", "--wheel", "--out-dir", str(rebuilt.parent), str(source)],
                check=True,
                capture_output=True,
                timeout=600,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise ArtifactGateError("wheel_rebuild_failed") from exc
    if selected is not None:
        try:
            diagnostic = compare_wheels(selected, rebuilt)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise ArtifactGateError("wheel_archive_unreadable") from exc
    else:
        diagnostic = {
            "allowed": file_sha256(rebuilt) == identity["production_wheel_sha256"],
            "mode": "exact_rebuild_without_original_input",
            "original_sha256": identity["production_wheel_sha256"],
            "rebuilt_sha256": file_sha256(rebuilt),
        }
    write_json(artifacts / "rebuild-diagnostic.json", diagnostic)
    if not diagnostic["allowed"]:
        raise ArtifactGateError("wheel_rebuild_difference_rejected")
    if selected is None:
        selected = rebuilt
    return {
        "wheel": str(selected.resolve()),
        "wheel_selection": "explicit_original" if wheel_input is not None else "exact_rebuild",
        "original_wheel_input": str(wheel_input.resolve()) if wheel_input is not None else None,
        "rebuild_diagnostic": diagnostic,
        "requirements": str(requirements.resolve()),
        "identity": identity,
    }


def archive_rebuild_diagnostic(artifacts: Path, output: Path) -> None:
    """归档前缀仅用于已核实的私有仓库；保留真实重建 wheel，不修正其字节。"""
    diagnostic = artifacts / "rebuild-diagnostic.json"
    files = [diagnostic, *sorted((artifacts / "wheel").glob("*.whl"))]
    for source in files:
        if source.is_file():
            target = output / "rebuild" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def task_row(root: Path, fixture: str, cache: Path) -> tuple[dict[str, Any], Path]:
    template = read_json(root / "studies" / "calibration.json")
    expected = {task_id for task_id, _ in FIXTURES.values()}
    if (
        template.get("phase") != "calibration"
        or template.get("revision") != REVISION
        or {row["task_id"] for row in template["tasks"]} != expected
    ):
        raise ValueError("只能使用既有两道校准题，不接受开发或最终任务替代")
    row = next(row for row in template["tasks"] if row["task_id"] == FIXTURES[fixture][0])
    snapshot = fetch_source(SOURCES["swe-bench-pro-v2"], cache)
    path = snapshot.tasks_path / row["task_id"]
    actual = (
        file_sha256(path / "instruction.md"),
        file_sha256(path / "task.toml"),
        tree_digest(path),
    )
    if snapshot.spec.revision != REVISION or actual != tuple(row[key] for key in TASK_IDENTITIES):
        raise ValueError("官方校准任务身份发生变化")
    return row, path


async def resources() -> dict[str, list[str]]:
    """观察本 job 前后资源，不删除预存对象，也不执行 prune。"""
    return {
        "containers": sorted((await docker("container", "ls", "--all", "--quiet")).split()),
        "networks": sorted((await docker("network", "ls", "--quiet")).split()),
        "volumes": sorted((await docker("volume", "ls", "--quiet")).split()),
    }


async def cleanup_evidence(before: dict[str, list[str]], output: Path) -> bool:
    after = await resources()
    remaining = {key: sorted(set(after[key]) - set(before[key])) for key in before}
    passed = not any(remaining.values())
    write_json(
        output / "cleanup.json", {"cleanup_confirmed": passed, "new_resources_remaining": remaining}
    )
    return passed


async def controls(root: Path, fixture: str, cache: Path, probe: Path, output: Path) -> bool:
    observed_probe = read_json(probe)
    if (
        observed_probe.get("passed") is not True
        or observed_probe.get("cleanup_confirmed") is not True
        or observed_probe.get("source_sha256", {}).get("network.py")
        != implementation_identity()["network.py"]
    ):
        raise ValueError("当前网络实现的真实探针尚未通过")
    row, task = task_row(root, fixture, cache)
    output.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(output.anchor).free < MIN_DISK_BYTES:
        raise ValueError("insufficient_disk_headroom")
    before = await resources()
    image = f"{IMAGE_REPOSITORY}@{FIXTURES[fixture][1]}"
    await docker("pull", image, timeout=600)
    await docker("tag", image, row["environment"]["docker_image"])
    inspected = json.loads(await docker("image", "inspect", image))[0]
    if image not in inspected.get("RepoDigests", []):
        raise ValueError("不可变镜像 digest 未确认")
    records = []
    reason = None
    try:
        for agent, repeat in (("oracle", 1), ("oracle", 2), ("oracle", 3), ("nop", 1)):
            if shutil.disk_usage(output.anchor).free < MIN_DISK_BYTES:
                reason = "insufficient_disk_headroom"
                break
            try:
                record = await run_official_trial(
                    task,
                    output / "jobs",
                    f"{agent}-{repeat}",
                    {"name": agent},
                    {
                        "import_path": "sayacode_bench.network:IsolatedDockerEnvironment",
                        "kwargs": {"messages_upstream": "http://127.0.0.1:9/v1/messages"},
                    },
                    configuration=agent,
                    repeat=repeat,
                    endpoint="control",
                )
            except Exception as exc:
                record = {
                    "status": "infrastructure_error",
                    "record_complete": False,
                    "verified": False,
                    "error_type": type(exc).__name__,
                }
            records.append(record)
            write_json(output / "records.json", records)
    finally:
        cleaned = await cleanup_evidence(before, output)
    gate = {
        "benchmark": "swe-bench-pro-v2",
        "revision": REVISION,
        "complete": len(records) == 4,
        "passed": len(records) == 4 and cleaned,
        "reason": reason,
        "tasks": [
            {
                **row,
                "passed": True,
                "oracle_repeats": 3,
                "oracle_trials": records[:3],
                "oracle": records[0] if records else None,
                "nop": records[3] if len(records) == 4 else None,
            }
        ],
    }
    try:
        validate_preflight(
            gate, read_json(probe), benchmark="swe-bench-pro-v2", revision=REVISION, tasks=[row]
        )
        runtime = records[0]["runtime_identity"]
        if runtime["image_id"] != inspected["Id"]:
            raise ValueError("参考解实际镜像与不可变镜像不同")
    except (ValueError, KeyError, TypeError):
        gate["passed"] = gate["tasks"][0]["passed"] = False
    write_json(output / "sanity.json", gate)
    return gate["passed"] is True


def read_records(paths: list[Path]) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for path in paths
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def prior_ledger_reason(paths: list[Path], receipt_path: Path | None = None) -> str | None:
    """人工覆盖声明只确定预算范围，不冒充供应商账单或补齐未知 token。"""
    if not paths or any(not path.is_file() for path in paths):
        return "missing_prior_paid_records"
    if len(paths) != 1 or receipt_path is None or not receipt_path.is_file():
        return "missing_prior_ledger_receipt"
    receipt = read_json(receipt_path)
    if receipt.get("records_sha256") != file_sha256(paths[0]):
        return "prior_ledger_identity_changed"
    observations = receipt.get("historical_observations", [])
    if (
        receipt.get("coverage_confirmed") is not True
        or receipt.get("unresolved_in_scope_observations") != []
        or not isinstance(observations, list)
        or len(observations) != len(KNOWN_PAID_PROBES)
        or any(not isinstance(row, dict) for row in observations)
        or {row.get("id") for row in observations} != KNOWN_PAID_PROBES
    ):
        return "prior_ledger_coverage_unconfirmed"
    rows = read_records(paths)
    scope = receipt.get("budget_scope")
    if scope == "all_known_paid_activity":
        known_rows = {
            key: [row for row in rows if row.get("historical_observation_id") == key]
            for key in KNOWN_PAID_PROBES
        }
        if any(row.get("disposition") != "included" for row in observations) or any(
            len(matches) != 1 or matches[0].get("endpoint") != "remote"
            for matches in known_rows.values()
        ):
            return "known_paid_observations_missing"
    elif scope == "new_user_authorized_budget":
        if (
            not isinstance(receipt.get("authorization_reference"), str)
            or not receipt["authorization_reference"].strip()
            or not isinstance(receipt.get("budget_start"), str)
            or not receipt["budget_start"].strip()
            or any(row.get("disposition") != "prebudget_cost_unknown" for row in observations)
        ):
            return "new_budget_scope_not_authorized"
    else:
        return "prior_budget_scope_unconfirmed"
    return budget_reason(
        rows, limit_cny=GLOBAL_LIMIT_CNY, stop_fraction=STOP_FRACTION, paid_endpoints=("remote",)
    )


def model_time_reserve(row: dict[str, Any]) -> int:
    """保留两次官方环境、执行和验证预算及收尾时间，不改官方单题时限。"""
    return int(
        2
        * (
            row["environment"]["build_timeout_sec"]
            + row["agent"]["timeout_sec"]
            + row["verifier"]["timeout_sec"]
        )
        + 1200
        + 900
    )


def cloud_reason(rows: list[dict[str, Any]]) -> str | None:
    return budget_reason(
        rows, limit_cny=CLOUD_LIMIT_CNY, stop_fraction=STOP_FRACTION, paid_endpoints=("remote",)
    )


def not_started(output: Path, reason: str) -> dict[str, Any]:
    report = {
        "model_started": False,
        "execution_confirmed": False,
        "continue_allowed": False,
        "reason": reason,
    }
    write_json(output / "calibration.json", report)
    return report


def runtime_matches(record: dict[str, Any], qualified: dict[str, Any]) -> bool:
    return all(
        isinstance(record.get(field), dict)
        and all(
            record[field].get(key) == qualified[key]
            for key in ("image_id", "architecture", "os", "requested", "docker_limits")
        )
        for field in ("runtime_identity", "replay_runtime_identity")
    )


async def calibrate(args: argparse.Namespace, frozen: dict[str, Any]) -> dict[str, Any]:
    root, output = args.root, args.output
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "input-identity.json", frozen)
    reason = prior_ledger_reason(args.prior_records, args.prior_ledger_receipt)
    if reason:
        return not_started(output, reason)
    row, _ = task_row(root, args.fixture, args.cache)
    gate = read_json(args.controls / "sanity.json")
    validate_preflight(
        gate, read_json(args.probe), benchmark="swe-bench-pro-v2", revision=REVISION, tasks=[row]
    )
    if read_json(args.controls / "cleanup.json").get("cleanup_confirmed") is not True:
        raise ValueError("参考解资源未独立确认清理")
    prior_cloud = read_records(args.cloud_prior_records)
    if args.fixture == "qutebrowser" and (prior_cloud or args.cloud_prior_report):
        raise ValueError("第一题不能携带其他云端校准尝试")
    if args.fixture == "ansible":
        if len(args.cloud_prior_records) != 1 or args.cloud_prior_report is None:
            raise ValueError("第二题必须继承第一题记录和签收")
        receipt = read_json(args.cloud_prior_report)
        if (
            len(prior_cloud) != 1
            or prior_cloud[0].get("task_id") != FIXTURES["qutebrowser"][0]
            or receipt.get("continue_allowed") is not True
            or receipt.get("records_sha256") != file_sha256(args.cloud_prior_records[0])
            or receipt.get("public_source_sha") != frozen["source"]["public_source_sha"]
        ):
            raise ValueError("第一题记录不完整、未获继续资格或内容身份不一致")
    reason = cloud_reason(prior_cloud)
    if reason:
        return not_started(output, reason)
    if time.time() + model_time_reserve(row) > args.deadline_epoch:
        return not_started(output, "insufficient_job_time")
    if shutil.disk_usage(output.anchor).free < MIN_DISK_BYTES:
        return not_started(output, "insufficient_disk_headroom")
    private = args.private_home.resolve()
    if private.is_relative_to(output.resolve()) or output.resolve().is_relative_to(private):
        raise ValueError("私有连接目录与结果目录必须隔离")
    budget = freeze_paid_budget(
        limit_cny=GLOBAL_LIMIT_CNY,
        stop_fraction=STOP_FRACTION,
        price_snapshot=root / "studies/prices/siliconflow-deepseek-v4.1-flash-20261022.json",
        prior_records=[*args.prior_records, *args.cloud_prior_records],
        paid_endpoints=["remote"],
    )
    global_prior = read_records([*args.prior_records, *args.cloud_prior_records])
    reason = budget_reason(
        global_prior,
        limit_cny=GLOBAL_LIMIT_CNY,
        stop_fraction=STOP_FRACTION,
        paid_endpoints=("remote",),
    )
    if reason:
        return not_started(output, reason)
    # 密钥仅在源码、工件、资格、用量、时间和路径检查全部完成后读取。
    secret = os.environ.get("SAYACODE_BENCH_MODEL_API_KEY")
    if not secret:
        return not_started(output, "missing_explicit_model_key")
    profile = private / "remote.json"
    variant = root / "studies/baseline.json"
    manifest = {
        "schema_version": 1,
        "phase": "calibration",
        "frozen": True,
        "canonical_model": CANONICAL_MODEL,
        "benchmark": "swe-bench-pro-v2",
        "revision": REVISION,
        "seed": f"cloud-two-calibration-v1-{args.fixture}",
        "tasks": [row],
        "configurations": ["baseline"],
        "baseline": "baseline",
        "candidate": None,
        "repeats": 1,
        "connections": ["remote"],
        "connection_profiles": {"remote": PROFILE},
        "reported_token_limit": 100_000_000,
        "runtime_evidence_required": True,
        "preflight_passed": True,
        "qualified_runtime_identities": {
            row["task_id"]: gate["tasks"][0]["oracle"]["runtime_identity"]
        },
        "preflight": {
            "sanity_sha256": file_sha256(args.controls / "sanity.json"),
            "network_probe_sha256": file_sha256(args.probe),
        },
        "artifacts": {
            "product_wheel": frozen["artifacts"]["identity"]["production_wheel_sha256"],
            "requirements": file_sha256(args.requirements),
            "variants": {"baseline": file_sha256(variant)},
        },
        "implementation": implementation_identity(),
        "cloud_source": frozen["source"],
        "cloud_host": frozen["host"],
        "prior_ledger_receipt_sha256": file_sha256(args.prior_ledger_receipt),
        "paid_budget": budget,
        "cloud_dispatch_limit_cny": CLOUD_LIMIT_CNY,
        "scope": "两道既有校准题各一次；不是正式研究，不按 reward 重跑或挑分",
    }
    manifest_path = output / "calibration.manifest.json"
    write_json(manifest_path, manifest, exclusive=True)
    # 私有目录由本次运行独占，避免失败收尾删除调用方已有的凭据。
    private.mkdir(parents=True, exist_ok=False)
    private.chmod(0o700)
    gateway_profile = private / "runs" / "run" / "remote-gateway.json"
    before = None
    error_type = None
    try:
        before = await resources()
        write_json(profile, {**PROFILE, "api_key": secret}, exclusive=True)
        profile.chmod(0o600)
        await asyncio.wait_for(
            run_phase(
                manifest_path,
                output / "run",
                args.cache,
                Path(frozen["artifacts"]["wheel"]),
                args.requirements,
                {"baseline": variant},
                {"remote": profile},
                private,
            ),
            timeout=max(1, args.deadline_epoch - time.time() - 900),
        )
    except Exception as exc:
        error_type = type(exc).__name__
    finally:
        try:
            cleaned = before is not None and await cleanup_evidence(before, output)
        except Exception as exc:
            cleaned = False
            write_json(
                output / "cleanup.json",
                {"cleanup_confirmed": False, "error_type": type(exc).__name__},
            )
        finally:
            profile.unlink(missing_ok=True)
            # run_phase 为受限网络生成的连接副本同样位于本次独占目录。
            gateway_profile.unlink(missing_ok=True)
    rows = (
        read_records([output / "run/records.jsonl"])
        if (output / "run/records.jsonl").is_file()
        else []
    )
    runtime = gate["tasks"][0]["oracle"]["runtime_identity"]
    valid = len(rows) == 1 and all(
        record.get("status") == "completed"
        and record.get("record_complete") is True
        and record.get("verified") is True
        and record.get("usage_complete") is True
        and record.get("replay_reward") in (0, 1)
        and record.get("runtime_comparison") == {"same_image": True, "same_platform": True}
        and runtime_matches(record, runtime)
        for record in rows
    )
    confirmed = bool(
        valid
        and cleaned
        and not error_type
        and not fatal_stop_reason(rows)
        and not cloud_reason([*prior_cloud, *rows])
        and not budget_reason(
            [*global_prior, *rows],
            limit_cny=GLOBAL_LIMIT_CNY,
            stop_fraction=STOP_FRACTION,
            paid_endpoints=("remote",),
        )
        and not (output / "run/abort.json").exists()
    )
    report = {
        "model_run_invoked": True,
        "execution_confirmed": bool(
            valid
            and cleaned
            and not error_type
            and not fatal_stop_reason(rows)
            and not (output / "run/abort.json").exists()
        ),
        "continue_allowed": confirmed,
        "task_id": row["task_id"],
        "error_type": error_type,
        "reward": rows[0].get("replay_reward") if len(rows) == 1 else None,
        "records_sha256": file_sha256(output / "run/records.jsonl") if rows else None,
        "public_source_sha": frozen["source"]["public_source_sha"],
        "cloud_paid_usage": estimate_paid_usage([*prior_cloud, *rows]),
        "provider_enforced_currency_cap": False,
        "boundary": "100 CNY全局、15 CNY云端子额均只在派发边界止损，在途请求不是硬封顶",
    }
    write_json(output / "calibration.json", report)
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("dry", "controls", "run"))
    for name in ("root", "requirements", "artifacts", "output", "metadata", "workflow"):
        result.add_argument(f"--{name}", type=Path, required=True)
    result.add_argument("--source-sha", required=True)
    result.add_argument("--wheel", type=Path, help="显式原始冻结 wheel；不自动回退为平台重建包")
    result.add_argument("--fixture", choices=tuple(FIXTURES))
    result.add_argument("--cache", type=Path)
    result.add_argument("--probe", type=Path)
    result.add_argument("--controls", type=Path)
    result.add_argument("--private-home", type=Path)
    result.add_argument("--deadline-epoch", type=float)
    result.add_argument("--prior-records", type=Path, action="append", default=[])
    result.add_argument("--prior-ledger-receipt", type=Path)
    result.add_argument("--cloud-prior-records", type=Path, action="append", default=[])
    result.add_argument("--cloud-prior-report", type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    stage = "repository_guard"
    try:
        require_private(read_json(args.metadata))
        stage = "source_identity"
        source = source_identity(args.root, args.source_sha, args.workflow)
        stage = "artifact_preflight"
        if args.command != "dry" and args.wheel is None:
            raise ArtifactGateError("explicit_original_wheel_required")
        artifacts = build_baseline(args.root, args.artifacts, args.requirements, args.wheel)
        frozen = {
            "source": source,
            "artifacts": artifacts,
            "host": {
                "system": platform.system(),
                "kernel": platform.release(),
                "machine": platform.machine(),
                "runner_image": os.environ.get("ImageOS"),
                "runner_image_version": os.environ.get("ImageVersion"),
            },
        }
        stage = args.command
        if args.command == "dry":
            args.output.mkdir(parents=True, exist_ok=False)
            ledger_reason = prior_ledger_reason(args.prior_records, args.prior_ledger_receipt)
            write_json(
                args.output / "preflight.json",
                {
                    **frozen,
                    "passed": True,
                    "model_calls": 0,
                    "fixed_fixtures": list(FIXTURES),
                    "global_limit_cny": GLOBAL_LIMIT_CNY,
                    "cloud_limit_cny": CLOUD_LIMIT_CNY,
                    "provider_enforced_currency_cap": False,
                    "model_dispatch_ready": ledger_reason is None,
                    "ledger_blocker": ledger_reason,
                },
            )
            passed = True
        else:
            if not args.fixture or args.cache is None or args.probe is None:
                raise ValueError("controls/run 需要固定题目、源缓存和真实探针")
            if args.command == "controls":
                passed = asyncio.run(
                    controls(args.root, args.fixture, args.cache, args.probe, args.output)
                )
            else:
                if any(
                    value is None
                    for value in (args.controls, args.private_home, args.deadline_epoch)
                ):
                    raise ValueError("run 需要资格证据、隔离私有目录和 job 截止时间")
                passed = asyncio.run(calibrate(args, frozen)).get("execution_confirmed", False)
        archive_rebuild_diagnostic(args.artifacts, args.output)
        print(json.dumps({"passed": passed, "command": args.command}))
        return 0 if passed else 1
    except Exception as exc:
        # 不把模型异常正文、HTTP 内容或私有 profile 写到控制台。
        args.output.mkdir(parents=True, exist_ok=True)
        reason = exc.reason if isinstance(exc, ArtifactGateError) else f"{stage}_failed"
        report = {
            "error_type": type(exc).__name__,
            "stage": stage,
            "reason": reason,
            "model_calls_unknown": args.command == "run" and stage == "run",
        }
        try:
            archive_rebuild_diagnostic(args.artifacts, args.output)
        except OSError as archive_error:
            report["diagnostic_archive_error_type"] = type(archive_error).__name__
        write_json(
            args.output / "entry-error.json",
            report,
        )
        print(json.dumps({"passed": False, **report}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
