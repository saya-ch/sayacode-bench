"""从冻结计划生成原生 Actions 串行 DAG；云端辅助命令只调用现有研究 CLI。

本文件不会授权正式试验。完整 bundle 包含原始私有证据，逐片快照会增长；
三天保留不意味着免费额度充足，也不允许脚本自动删除云端 artifact。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from sayacode_bench.artifacts import file_sha256, implementation_identity, read_json, write_json
from sayacode_bench.execution import paired_order

EXECUTION_REPOSITORY = "saya-ch/sayacode-bench-runs"
PUBLIC_REPOSITORY = "saya-ch/sayacode-bench"
CHECKOUT = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
TEMPLATE = Path(__file__).resolve().parents[1] / ".github/workflows/run-study-shard.yml"
SHA = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
LABEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}\Z")
STORAGE_NOTE = (
    "完整原始 bundle 每片累积并保留三天；500 MB 免费 artifact 存储不是充分条件。"
    "需人工核实分钟、存储及计费授权；下载核验前不得删除云端证据，本脚本不删除 artifact。"
)
HOST_FIELDS = ("ImageOS", "ImageVersion", "RUNNER_ARCH")
HOST_EXCLUSIONS = ("physical_cpu_identity", "kernel_identity", "provider_model_immutability")


def _host_cohort(value: Any) -> dict[str, str]:
    """只约束宿主镜像声明，不把三字段相同扩大为硬件或模型相同。"""
    if (
        not isinstance(value, dict)
        or set(value) != set(HOST_FIELDS)
        or any(not isinstance(item, str) or not item.strip() for item in value.values())
        or value.get("RUNNER_ARCH") != "X64"
    ):
        raise ValueError("runner 政策必须固定三字段宿主镜像 cohort")
    return {key: value[key] for key in HOST_FIELDS}


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _archive_digest(path: Path) -> str:
    """完整 raw bundle 可能很大，校验不把整个 tar 载入内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or "\n" in value:
        raise ValueError("需要 bundle 内的相对 POSIX 路径")
    return path


def _local(root: Path, relative: str) -> Path:
    result = root.joinpath(*_relative(relative).parts)
    if not result.resolve().is_relative_to(root.resolve()) or result.is_symlink():
        raise ValueError("工件路径越过 bundle")
    return result


def _mapped(reference: dict[str, str], original: PurePosixPath, local: Path) -> Path:
    path = PurePosixPath(reference["path"])
    if not path.is_relative_to(original):
        raise ValueError("冻结工件不在固定 Linux bundle")
    target = _local(local, str(path.relative_to(original)))
    if not SHA.fullmatch(reference["sha256"]) or file_sha256(target) != reference["sha256"]:
        raise ValueError("冻结工件字节身份不同")
    return target


def inspect_plan(
    plan_path: Path, bundle: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """本机可映射读取 Linux bundle，原始 JSON 路径从不重写。"""
    plan = read_json(plan_path)
    original = PurePosixPath(plan["bundle_root"])
    if (
        plan.get("schema_version") != 1
        or original.parent != PurePosixPath("/tmp/sayacode-studies")
        or not LABEL.fullmatch(original.name)
    ):
        raise ValueError("需要固定 Linux study bundle")
    master = read_json(_mapped(plan["master"], original, bundle))
    runner = read_json(_mapped(plan["runner_policy"], original, bundle))
    _host_cohort(runner.get("host_cohort"))
    authorization = read_json(_mapped(plan["authorization"], original, bundle))
    if (
        master.get("frozen") is not True
        or master.get("phase") not in {"dev", "holdout", "validation", "calibration"}
        or authorization.get("authorized") is not True
        or authorization.get("phase") != master["phase"]
        or authorization.get("master_manifest_sha256") != plan["master"]["sha256"]
        or runner.get("platform") != "linux"
        or runner.get("architecture") != "amd64"
        or runner.get("job_timeout_seconds") != 21600
        or not COMMIT.fullmatch(str(runner.get("public_source_sha", "")))
        or runner.get("executor_workflow_sha256") != file_sha256(TEMPLATE)
        or plan.get("implementation") != implementation_identity()
        or plan.get("artifacts") != master.get("artifacts")
    ):
        raise ValueError("计划、授权、源码、模板或 runner 政策未绑定")
    if any("api_key" in profile for profile in master.get("connection_profiles", {}).values()):
        raise ValueError("master 不得包含私有密钥")
    expected = paired_order(master)
    schedule = plan["schedule"]
    if not schedule or len(schedule) != len(expected) or _hash(schedule) != plan["schedule_sha256"]:
        raise ValueError("全 master schedule 身份不一致")
    for actual, row in zip(schedule, expected, strict=True):
        task = next(task for task in master["tasks"] if task["task_id"] == row["task_id"])
        reserve = math.ceil(
            2
            * (
                task["environment"]["build_timeout_sec"]
                + task["agent"]["timeout_sec"]
                + task["verifier"]["timeout_sec"]
            )
            + 1200
            + 900
        )
        key = _hash([plan["master"]["sha256"], row["task_id"], row["configuration"], row["repeat"]])
        endpoint = master["connections"][(row["repeat"] - 1) % len(master["connections"])]
        if (
            any(actual.get(field) != value for field, value in row.items())
            or actual.get("trial_key") != key
            or actual.get("block_id")
            != _hash([plan["master"]["sha256"], row["task_id"], row["repeat"]])
            or actual.get("shard_id") != f"{master['phase']}-{row['sequence']:04d}-{key[:12]}"
            or actual.get("endpoint") != endpoint
            or actual.get("reserve_seconds") != reserve
            or not 0 < reserve <= 21600
        ):
            raise ValueError("顺序、连接、试验键或官方时限不一致")
    return plan, master, runner


def _artifact_bindings(bundle: Path, digests: dict[str, Any]) -> dict[str, Any]:
    """按冻结 SHA 唯一定位输入，不通过文件名猜测或修改候选。"""
    files: dict[str, list[str]] = {}
    for path in sorted((bundle / "inputs").rglob("*")):
        if path.is_file() and not path.is_symlink():
            files.setdefault(file_sha256(path), []).append(path.relative_to(bundle).as_posix())

    def locate(digest: str) -> str:
        matches = files.get(digest, [])
        if len(matches) != 1:
            raise ValueError("生产工件 SHA 必须在 inputs 中唯一存在")
        return matches[0]

    return {
        "wheel": locate(digests["product_wheel"]),
        "requirements": locate(digests["requirements"]),
        "variants": {label: locate(digest) for label, digest in digests["variants"].items()},
    }


def generate(
    plan_path: Path,
    bundle: Path,
    output: Path,
    *,
    seed_sha256: str,
    seed_file: str = "",
    seed_artifact: str = "",
    seed_run_id: str = "",
) -> dict[str, Any]:
    """只生成可审阅文件，不访问 GitHub、Docker、凭据或模型。"""
    if output.exists() or output.with_suffix(".receipt.json").exists():
        raise FileExistsError("生成工作流不可覆盖")
    if not SHA.fullmatch(seed_sha256):
        raise ValueError("seed tar 必须有完整 SHA256")
    if seed_file:
        _relative(seed_file)
        if seed_artifact or seed_run_id:
            raise ValueError("seed file 与私有 artifact 二选一")
    elif not LABEL.fullmatch(seed_artifact) or not seed_run_id.isdigit() or int(seed_run_id) <= 0:
        raise ValueError("需要私有执行仓库的 seed artifact 和原 run ID")
    plan, master, runner = inspect_plan(plan_path, bundle)
    contract = {
        "schema_version": 1,
        "public_source_sha": runner["public_source_sha"],
        "plan_sha256": file_sha256(plan_path),
        "plan_relative_path": plan_path.resolve().relative_to(bundle.resolve()).as_posix(),
        "bundle_root": plan["bundle_root"],
        "private_home": f"/tmp/sayacode-private/{PurePosixPath(plan['bundle_root']).name}",
        "executor_workflow_sha256": file_sha256(TEMPLATE),
        "generator_sha256": file_sha256(Path(__file__)),
        "host_cohort": runner["host_cohort"],
        "bindings": _artifact_bindings(bundle, plan["artifacts"]),
    }
    text = json.dumps(contract, ensure_ascii=False, separators=(",", ":"))
    jobs: dict[str, Any] = {
        "review": {
            "runs-on": "ubuntu-24.04",
            "timeout-minutes": 5,
            "steps": [
                {
                    "name": "只审阅；正式执行须另获授权及额度确认",
                    "env": {"GH_TOKEN": "${{ github.token }}"},
                    "shell": "bash",
                    "run": PRIVATE_GUARD,
                }
            ],
        }
    }
    for index, entry in enumerate(plan["schedule"], 1):
        previous = f"shard_{index - 1:04d}" if index > 1 else "review"
        condition = (
            "always() && !cancelled() && inputs.execute_models && "
            "inputs.confirm_formal_scope && inputs.confirm_actions_budget && "
            f"needs.{previous}.result == 'success'"
        )
        if index > 1:
            condition += f" && needs.{previous}.outputs.continuation_allowed == 'true'"
        arguments = {
            "contract_json": text,
            "shard_id": entry["shard_id"],
            "mode": "shard",
            "input_archive_sha256": seed_sha256
            if index == 1
            else f"${{{{ needs.{previous}.outputs.archive_sha256 }}}}",
            "input_artifact": seed_artifact
            if index == 1
            else f"${{{{ needs.{previous}.outputs.artifact_name }}}}",
            "input_run_id": seed_run_id if index == 1 else "${{ github.run_id }}",
            "seed_file": seed_file if index == 1 else "",
            "previous_receipt_sha256": ""
            if index == 1
            else f"${{{{ needs.{previous}.outputs.receipt_sha256 }}}}",
            "previous_ledger_sha256": ""
            if index == 1
            else f"${{{{ needs.{previous}.outputs.ledger_sha256 }}}}",
        }
        jobs[f"shard_{index:04d}"] = {
            "needs": [previous],
            "if": "${{ " + condition + " }}",
            "uses": "./.github/workflows/run-study-shard.yml",
            "with": arguments,
            "secrets": {"connection_keys_json": "${{ secrets.STUDY_CONNECTION_KEYS_JSON }}"},
        }
    last = f"shard_{len(plan['schedule']):04d}"
    jobs["merge"] = {
        "needs": [last],
        "if": "${{ always() && !cancelled() && needs." + last + ".result == 'success' }}",
        "uses": "./.github/workflows/run-study-shard.yml",
        "with": {
            "contract_json": text,
            "mode": "merge",
            "shard_id": "",
            "input_artifact": f"${{{{ needs.{last}.outputs.artifact_name }}}}",
            "input_run_id": "${{ github.run_id }}",
            "input_archive_sha256": f"${{{{ needs.{last}.outputs.archive_sha256 }}}}",
            "previous_receipt_sha256": f"${{{{ needs.{last}.outputs.receipt_sha256 }}}}",
            "previous_ledger_sha256": f"${{{{ needs.{last}.outputs.ledger_sha256 }}}}",
        },
    }
    workflow = {
        "name": f"冻结研究 {master['phase']} {contract['plan_sha256'][:12]}",
        "on": {
            "workflow_dispatch": {
                "inputs": {
                    key: {"description": description, "type": "boolean", "default": False}
                    for key, description in (
                        ("execute_models", "实际执行冻结阶段；默认只审阅"),
                        ("confirm_formal_scope", "已另行获得这份完整阶段和路由的执行授权"),
                        ("confirm_actions_budget", "已核实 Actions 分钟、增长存储和计费范围"),
                    )
                }
            }
        },
        "permissions": {"contents": "read", "actions": "read"},
        "concurrency": {"group": "sayacode-study-global", "cancel-in-progress": False},
        "jobs": jobs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # JSON 是 YAML 的子集，避免引入另一个 YAML 生成器或非标准表达式转义。
    output.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema_version": 1,
        "plan_sha256": contract["plan_sha256"],
        "schedule_sha256": plan["schedule_sha256"],
        "public_source_sha": runner["public_source_sha"],
        "executor_workflow_sha256": contract["executor_workflow_sha256"],
        "generator_sha256": contract["generator_sha256"],
        "workflow_sha256": file_sha256(output),
        "seed_sha256": seed_sha256,
        "shard_count": len(plan["schedule"]),
        "planned_reserve_seconds": sum(row["reserve_seconds"] for row in plan["schedule"]),
        "artifact_retention_days": 3,
        "storage_note": STORAGE_NOTE,
        "execution_authorized_by_generation": False,
        "host_cohort_enforced": True,
        "host_cohort_fields": list(HOST_FIELDS),
        "host_cohort_exclusions": list(HOST_EXCLUSIONS),
    }
    write_json(output.with_suffix(".receipt.json"), receipt, exclusive=True)
    return receipt


PRIVATE_GUARD = """set -eu
test "$GITHUB_REPOSITORY" = saya-ch/sayacode-bench-runs
test "$GITHUB_RUN_ATTEMPT" = 1
gh api "repos/$GITHUB_REPOSITORY" > "$RUNNER_TEMP/repository.json"
python - <<'PY'
import json, os
from pathlib import Path
d = json.loads((Path(os.environ['RUNNER_TEMP'])/'repository.json').read_text(encoding='utf-8'))
assert d.get('full_name') == 'saya-ch/sayacode-bench-runs'
assert d.get('private') is True and d.get('visibility') == 'private'
PY
"""


def restore_archive(archive: Path, target: Path, expected_sha256: str) -> None:
    """只恢复完整私有 tar；拒绝路径逃逸、外部链接和现存目录。"""
    if not SHA.fullmatch(expected_sha256) or _archive_digest(archive) != expected_sha256:
        raise ValueError("bundle tar SHA256 不同")
    if target.exists() or target.is_symlink():
        raise FileExistsError("fresh runner 不能覆盖原 bundle")
    with tarfile.open(archive, "r:*") as stream:
        members = stream.getmembers()
        names = set()
        total = 0
        for member in members:
            name = _relative(member.name)
            if str(name) in names or not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError("重复路径或不支持的 tar 成员")
            names.add(str(name))
            if member.issym():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or ".." in link.parts or "\\" in member.linkname:
                    raise ValueError("拒绝外部或不明确的符号链接")
            total += member.size
        target.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(target.parent).free < total + 12 * 1024**3:
            raise ValueError("恢复完整证据后不足官方镜像所需磁盘余量")
        target.mkdir(exist_ok=False)
        stream.extractall(target, members=members, filter="data")


def load_contract(
    text: str, bundle: Path | None = None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = json.loads(text)
    root = bundle or Path(contract["bundle_root"])
    path = _local(root, contract["plan_relative_path"])
    if file_sha256(path) != contract["plan_sha256"]:
        raise ValueError("计划 SHA 与生成 DAG 不同")
    plan, master, runner = inspect_plan(path, root)
    if (
        contract["bundle_root"] != plan["bundle_root"]
        or contract["public_source_sha"] != runner["public_source_sha"]
        or contract["executor_workflow_sha256"] != file_sha256(TEMPLATE)
        or contract["generator_sha256"] != file_sha256(Path(__file__))
        or contract.get("host_cohort") != runner["host_cohort"]
        or contract["bindings"] != _artifact_bindings(root, plan["artifacts"])
    ):
        raise ValueError("生成器、工件或模板已漂移")
    return contract, plan, master


def verify_previous(
    plan: dict[str, Any], entry: dict[str, Any] | None, receipt_sha: str, ledger_sha: str
) -> Path | None:
    sequence = entry["sequence"] - 1 if entry else len(plan["schedule"])
    if not sequence:
        if receipt_sha or ledger_sha:
            raise ValueError("首片不能夹带前序账本")
        return None
    previous = plan["schedule"][sequence - 1]
    path: Path = Path(plan["bundle_root"]) / "shards" / previous["shard_id"] / "shard-receipt.json"
    value = read_json(path)
    ledger = Path(value["ledger_after"]["path"])
    if (
        not SHA.fullmatch(receipt_sha)
        or file_sha256(path) != receipt_sha
        or not SHA.fullmatch(ledger_sha)
        or value["ledger_after"]["sha256"] != ledger_sha
        or file_sha256(ledger) != ledger_sha
        or (entry is not None and value.get("continuation_allowed") is not True)
    ):
        raise ValueError("下载的前序 receipt 或累计账本未通过")
    return path


async def prepare_image(master: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """复用已存在的固定 digest 拉取函数；不改官方 task 文件。"""
    from scripts.diagnose_fixtures import pin_image

    task = next(task for task in master["tasks"] if task["task_id"] == entry["task_id"])
    runtime = master["qualified_runtime_identities"][entry["task_id"]]
    original = task["environment"]["docker_image"]
    repository = original.rsplit(":", 1)[0]
    matches = [
        value
        for value in runtime.get("repo_digests", [])
        if value.startswith(repository + "@sha256:")
    ]
    if len(matches) != 1:
        raise ValueError("冻结资格缺少唯一原镜像 RepoDigest，不能猜测 tag")
    result = await pin_image({"immutable_image": matches[0], "original_image_reference": original})
    if (
        result["expected_image_id"] != runtime["image_id"]
        or result["os"] != "linux"
        or result["architecture"] != "amd64"
    ):
        raise ValueError("拉取的官方镜像与资格身份不同")
    return result


def _cli(arguments: list[str], log: Path, *, deadline: float | None = None) -> int:
    environment = dict(os.environ)
    environment.pop("SAYACODE_STUDY_CONNECTION_KEYS_JSON", None)
    with log.open("wb") as stream:
        result = subprocess.run(
            [sys.executable, "-m", "sayacode_bench.cli", *arguments],
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=max(1, deadline - time.time()) if deadline is not None else None,
            check=False,
        )
    return result.returncode


def _private_directory(contract: dict[str, Any], bundle: Path) -> Path:
    private = Path(contract["private_home"])
    if private != Path("/tmp/sayacode-private") / bundle.name or private.is_relative_to(bundle):
        raise ValueError("私有 profile 路径不符合固定布局")
    return private


def execute(
    contract_text: str,
    shard_id: str,
    *,
    probe: Path,
    runner_preparation: Path,
    deadline: float,
    receipt_sha: str = "",
    ledger_sha: str = "",
) -> dict[str, Any]:
    """只建立本片私有连接并调用生产 CLI，不实现 Agent 或评分循环。"""
    contract, plan, master = load_contract(contract_text)
    bundle = Path(plan["bundle_root"])
    entry = next(row for row in plan["schedule"] if row["shard_id"] == shard_id)
    directory = bundle / "orchestration" / shard_id
    directory.mkdir(parents=True, exist_ok=False)
    status: dict[str, Any] = {
        "model_dispatch_attempted": False,
        "receipt_complete": False,
        "continuation_allowed": False,
        "error_type": None,
        "host_cohort_confirmed": False,
        "host_cohort_fields": list(HOST_FIELDS),
        "host_cohort_exclusions": list(HOST_EXCLUSIONS),
    }
    private = _private_directory(contract, bundle)
    created = False
    profiles: list[Path] = []
    try:
        prepared = read_json(runner_preparation)
        write_json(directory / "runner-preparation.json", prepared, exclusive=True)
        status["runner_preparation_sha256"] = file_sha256(runner_preparation)
        status["expected_host_cohort"] = _host_cohort(contract.get("host_cohort"))
        status["observed_host_cohort"] = prepared.get("runner_image")
        if (
            prepared.get("passed") is not True
            or prepared.get("script_sha256")
            != file_sha256(Path(__file__).with_name("prepare_cloud_runner.py"))
            or prepared.get("runner_image") != status["expected_host_cohort"]
        ):
            raise ValueError("当前宿主镜像 cohort 或准备脚本与冻结政策不同")
        status["host_cohort_confirmed"] = True
        before = verify_previous(plan, entry, receipt_sha, ledger_sha)
        observed = read_json(probe)
        if (
            observed.get("passed") is not True
            or observed.get("cleanup_confirmed") is not True
            or observed.get("source_sha256", {}).get("network.py")
            != implementation_identity()["network.py"]
            or not math.isfinite(deadline)
            or time.time() + entry["reserve_seconds"] > deadline
        ):
            raise ValueError("本 runner 网络、清理或官方时间余量不足")
        write_json(directory / "network-probe.json", observed, exclusive=True)
        write_json(
            directory / "image-preparation.json",
            asyncio.run(prepare_image(master, entry)),
            exclusive=True,
        )
        if (
            time.time() + entry["reserve_seconds"] > deadline
            or shutil.disk_usage(bundle).free < 12 * 1024**3
        ):
            raise ValueError("镜像准备后时间或磁盘不足，不启动模型")
        # 连接参数来自完整 master，只有 key 来自本次显式 Secret；不打印正文。
        keys = json.loads(os.environ.get("SAYACODE_STUDY_CONNECTION_KEYS_JSON", "{}"))
        if set(keys) != set(master["connections"]) or any(
            not isinstance(value, str) or not value for value in keys.values()
        ):
            raise ValueError("显式连接密钥与冻结连接集合不同")
        private.mkdir(parents=True, exist_ok=False)
        private.chmod(0o700)
        created = True
        arguments = [
            "run-shard",
            "--plan",
            str(_local(bundle, contract["plan_relative_path"])),
            "--shard-id",
            shard_id,
            "--cache",
            str(bundle / "cache"),
            "--output",
            str(bundle / "shards" / shard_id),
            "--private-home",
            str(private),
            "--deadline-epoch",
            str(deadline),
        ]
        if before:
            arguments += ["--previous-receipt", str(before)]
        for label in master["connections"]:
            if not LABEL.fullmatch(label):
                raise ValueError("非法连接别名")
            path = private / f"{label}.json"
            profiles.append(path)
            write_json(
                path,
                {**master["connection_profiles"][label], "api_key": keys[label]},
                exclusive=True,
            )
            path.chmod(0o600)
            arguments += ["--connection", f"{label}={path}"]
        bindings = contract["bindings"]
        arguments += [
            "--wheel",
            str(_local(bundle, bindings["wheel"])),
            "--requirements",
            str(_local(bundle, bindings["requirements"])),
        ]
        for label, value in bindings["variants"].items():
            arguments += ["--variant", f"{label}={_local(bundle, value)}"]
        status["model_dispatch_attempted"] = True
        status["native_cli_returncode"] = _cli(
            arguments, directory / "entry.log", deadline=deadline + 300
        )
        path = bundle / "shards" / shard_id / "shard-receipt.json"
        receipt = read_json(path)
        status.update(
            {
                "receipt_sha256": file_sha256(path),
                "ledger_sha256": receipt["ledger_after"]["sha256"],
                "receipt_complete": receipt.get("complete") is True,
                "continuation_allowed": receipt.get("continuation_allowed") is True
                and status["native_cli_returncode"] == 0,
            }
        )
        status["merge_cli_returncode"] = merge(
            contract_text, output=bundle / "merged" / f"prefix-{entry['sequence']:04d}"
        )
        # 未完整前缀返回 1 是原 CLI 的既定语义；异常参数/身份返回 2 必须止损。
        if status["merge_cli_returncode"] not in {0, 1}:
            raise ValueError("严格归并失败，不允许后续派发")
    except Exception as exc:
        status["error_type"] = type(exc).__name__
        status["continuation_allowed"] = False
    finally:
        if created:
            try:
                for path in profiles:
                    path.unlink(missing_ok=True)
                for label in master["connections"]:
                    (private / "runs" / "run" / f"{label}-gateway.json").unlink(missing_ok=True)
                for path in (private / "runs" / "run", private / "runs", private):
                    if path.is_dir():
                        path.rmdir()
                status["credential_cleanup_confirmed"] = True
            except OSError as exc:
                status["credential_cleanup_confirmed"] = False
                status["continuation_allowed"] = False
                status["error_type"] = type(exc).__name__
        write_json(directory / "dispatch.json", status, exclusive=True)
    return status


def merge(contract_text: str, *, output: Path | None = None) -> int:
    contract, plan, _ = load_contract(contract_text)
    bundle = Path(plan["bundle_root"])
    receipts = [
        bundle / "shards" / row["shard_id"] / "shard-receipt.json" for row in plan["schedule"]
    ]
    receipts = [path for path in receipts if path.is_file()]
    if not receipts:
        return 1
    destination = output or bundle / "merged" / "final"
    arguments = [
        "merge-shards",
        "--plan",
        str(_local(bundle, contract["plan_relative_path"])),
        "--output",
        str(destination),
    ]
    for path in receipts:
        arguments += ["--receipt", str(path)]
    return _cli(arguments, bundle / "orchestration" / f"merge-{destination.name}.log")


def archive_bundle(contract_text: str, output: Path, *, shard_id: str) -> dict[str, Any]:
    """不裁剪原生证据、不自动删除旧工件；归档失败会阻止后序。"""
    contract = json.loads(contract_text)
    bundle = Path(contract["bundle_root"])
    if output.resolve().is_relative_to(bundle.resolve()):
        raise ValueError("归档文件必须位于完整 bundle 外部")
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz", dereference=False) as stream:
        for path in sorted(bundle.iterdir()):
            stream.add(path, arcname=path.name, recursive=True)
    status_path = bundle / "orchestration" / shard_id / "dispatch.json"
    status = read_json(status_path) if shard_id and status_path.is_file() else {}
    result = {
        "schema_version": 1,
        "plan_sha256": contract["plan_sha256"],
        "archive_sha256": _archive_digest(archive),
        "archive_bytes": archive.stat().st_size,
        "receipt_sha256": status.get("receipt_sha256", ""),
        "ledger_sha256": status.get("ledger_sha256", ""),
        "receipt_complete": status.get("receipt_complete") is True,
        "host_cohort_confirmed": status.get("host_cohort_confirmed") is True,
        "host_cohort_fields": list(HOST_FIELDS),
        "host_cohort_exclusions": list(HOST_EXCLUSIONS),
        "continuation_allowed": status.get("continuation_allowed") is True,
        "artifact_retention_days": 3,
        "storage_note": STORAGE_NOTE,
        "contains_private_raw_evidence": True,
        "cloud_artifact_deletion_performed": False,
    }
    write_json(output / "bundle-manifest.json", result, exclusive=True)
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as stream:
            for key in (
                "archive_sha256",
                "receipt_sha256",
                "ledger_sha256",
                "continuation_allowed",
            ):
                value = result[key]
                stream.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate_parser = commands.add_parser("generate")
    for name in ("plan", "bundle-directory", "output"):
        generate_parser.add_argument("--" + name, type=Path, required=True)
    generate_parser.add_argument("--seed-sha256", required=True)
    generate_parser.add_argument("--seed-file", default="")
    generate_parser.add_argument("--seed-artifact", default="")
    generate_parser.add_argument("--seed-run-id", default="")
    for name in ("restore", "execute", "archive", "merge"):
        sub = commands.add_parser(name)
        sub.add_argument("--contract", default=None)
        if name == "restore":
            sub.add_argument("--archive", type=Path, required=True)
            sub.add_argument("--sha256", required=True)
        if name in {"execute", "archive"}:
            sub.add_argument("--shard-id", required=True)
        if name == "execute":
            sub.add_argument("--probe", type=Path, required=True)
            sub.add_argument("--runner-preparation", type=Path, required=True)
            sub.add_argument("--deadline-epoch", type=float, required=True)
            sub.add_argument("--previous-receipt-sha256", default="")
            sub.add_argument("--previous-ledger-sha256", default="")
        if name == "archive":
            sub.add_argument("--output", type=Path, required=True)
        if name == "merge":
            sub.add_argument("--previous-receipt-sha256", required=True)
            sub.add_argument("--previous-ledger-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.command == "generate":
            generate(
                args.plan,
                args.bundle_directory,
                args.output,
                seed_sha256=args.seed_sha256,
                seed_file=args.seed_file,
                seed_artifact=args.seed_artifact,
                seed_run_id=args.seed_run_id,
            )
            return 0
        text = args.contract or os.environ["SAYACODE_STUDY_CONTRACT"]
        if args.command == "restore":
            contract = json.loads(text)
            root = PurePosixPath(contract["bundle_root"])
            if root.parent != PurePosixPath("/tmp/sayacode-studies") or not LABEL.fullmatch(
                root.name
            ):
                raise ValueError("恢复目标不是固定 Linux study bundle")
            current = (
                subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True)
                .stdout.decode()
                .strip()
            )
            if current != contract["public_source_sha"]:
                raise ValueError("public source SHA 不同")
            restore_archive(args.archive, Path(contract["bundle_root"]), args.sha256)
            load_contract(text)
        elif args.command == "execute":
            value = execute(
                text,
                args.shard_id,
                probe=args.probe,
                runner_preparation=args.runner_preparation,
                deadline=args.deadline_epoch,
                receipt_sha=args.previous_receipt_sha256,
                ledger_sha=args.previous_ledger_sha256,
            )
            return (
                0
                if value["error_type"] is None
                and value.get("native_cli_returncode") == 0
                and value.get("receipt_complete") is True
                else 1
            )
        elif args.command == "archive":
            archive_bundle(text, args.output, shard_id=args.shard_id)
        elif args.command == "merge":
            _, plan, _ = load_contract(text)
            verify_previous(plan, None, args.previous_receipt_sha256, args.previous_ledger_sha256)
            return merge(text)
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        tarfile.TarError,
    ) as exc:
        # 不把底层异常正文、绝对路径或凭据写入 Actions 控制台。
        print(type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
