"""安装旁证与无模型预检；TLS 失败只按原生退出码处理。"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import shlex
import shutil
import tarfile
import time
import tomllib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from harbor.environments.base import BaseEnvironment

from .artifacts import file_sha256, implementation_identity, read_json, write_json
from .resources import compare_runtimes, resource_status

UV_VERSION = "0.12.5"
UV_INSTALLER_URL = f"https://astral.sh/uv/{UV_VERSION}/install.sh"
# 版本身份默认值；正式跑批时由 locked_agents 依据 wheel 文件名动态覆盖
# （见 scripts/locked_agents.py:build_agent），避免 bump 产品版本后遗漏。
PRODUCT_VERSION = "3.2.4"
INSTALLATION_RECEIPT = "installation/receipt.json"
SHA = re.compile(r"[0-9a-f]{64}\Z")
HARBOR_FILES = (
    "harbor/agents/installed/base.py",
    "harbor/trial/trial.py",
    "harbor/models/job/config.py",
    "harbor/models/trial/config.py",
    "harbor/environments/base.py",
    "harbor/environments/docker/docker.py",
)


def file_reference(path: Path) -> dict[str, str]:
    path = path.resolve(strict=True)
    return {"path": str(path), "sha256": file_sha256(path)}


def harbor_installation_identity() -> dict[str, Any]:
    distribution = importlib.metadata.distribution("harbor")
    if distribution.version != "0.24.0":
        raise ValueError("安装预检必须使用冻结 Harbor 0.24.0")
    return {
        "version": distribution.version,
        "files": {
            name: file_sha256(Path(str(distribution.locate_file(name)))) for name in HARBOR_FILES
        },
    }


def source_identity() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    return {
        "implementation": implementation_identity(),
        "source_files": {
            name: file_sha256(root / name)
            for name in (
                "scripts/preflight_installations.py",
                "scripts/preflight_installation_storage.py",
                ".github/workflows/preflight-installations.yml",
            )
        },
    }


async def _record_exec(
    environment: BaseEnvironment,
    command: str,
    directory: Path,
    name: str,
    *,
    user: str | None,
    timeout: int = 120,
) -> dict[str, Any]:
    """保存 Harbor 返回的完整文本；异常时不编造未返回的 stdout。"""
    started = time.monotonic()
    record: dict[str, Any] = {
        "command": command,
        "requested_user": user,
        "return_code": None,
        "error_type": None,
    }
    write_json(directory / f"{name}.attempt.json", record, exclusive=True)
    try:
        result = await environment.exec(command=command, user=user, timeout_sec=timeout)
        record["return_code"] = result.return_code
        for field in ("stdout", "stderr"):
            value = getattr(result, field)
            record[field] = value
            if value is not None:
                path = directory / f"{name}.{field}.txt"
                with path.open("x", encoding="utf-8", newline="") as stream:
                    stream.write(value)
                record[field + "_file"] = file_reference(path)
        return record
    except BaseException as exc:
        record["error_type"] = type(exc).__name__
        raise
    finally:
        record["elapsed_seconds"] = time.monotonic() - started
        write_json(directory / f"{name}.result.json", record, exclusive=True)


async def prepare_uv_installer(
    environment: BaseEnvironment,
    installer: PurePosixPath,
    evidence: Path,
    ensure_dependencies: Callable[[BaseEnvironment, tuple[str, ...]], Awaitable[None]],
) -> dict[str, Any]:
    """真实下载同时验证现有信任链；仅 60/77 允许一次官方 CA 安装修复。

    同一 trial 重跑时安装证据目录可能已存在：清空后重建，避免 ``exclusive``
    写入撞到旧文件而把可恢复的重跑变成 ``FileExistsError``。"""
    if evidence.exists():
        shutil.rmtree(evidence)
    evidence.mkdir(parents=True, exist_ok=False)
    state: dict[str, Any] = {
        "schema_version": 1,
        "url": UV_INSTALLER_URL,
        "tls_verification_required": True,
        "passed": False,
        "ca_repair_attempted": False,
        "phase": "ensure_curl",
        "attempts": [],
    }
    try:
        await ensure_dependencies(environment, ("curl",))
        state["phase"] = "prepare_directory"
        directory = await _record_exec(
            environment,
            f"mkdir -p {shlex.quote(str(installer.parent))}",
            evidence,
            "directory",
            user="root",
        )
        if directory["return_code"] != 0:
            raise RuntimeError("uv 安装目录创建失败")
        for attempt in (1, 2):
            state["phase"] = "download"
            # -q 必须排首位，防止镜像 curlrc 关闭校验；重定向也只允许 HTTPS。
            command = (
                "curl -q --fail --location --silent --show-error "
                "--proto '=https' --proto-redir '=https' --connect-timeout 30 --max-time 120 "
                f"{shlex.quote(UV_INSTALLER_URL)} -o {shlex.quote(str(installer))}"
            )
            observed = await _record_exec(
                environment, command, evidence, f"download-{attempt}", user="root", timeout=130
            )
            state["attempts"].append(observed)
            code = observed["return_code"]
            if code == 0:
                break
            if attempt == 1 and code in {60, 77}:
                state["phase"] = "ensure_ca"
                state["ca_repair_attempted"] = True
                write_json(evidence / "bootstrap.json", state)
                await ensure_dependencies(environment, ("ca_certificates",))
            else:
                raise RuntimeError(f"uv TLS 下载失败，curl exit={code}")
        state["phase"] = "verify_download"
        identity = await _record_exec(
            environment,
            f"test -s {shlex.quote(str(installer))} && sha256sum {shlex.quote(str(installer))}",
            evidence,
            "installer-identity",
            user="root",
        )
        digest = str(identity.get("stdout") or "").split()
        if identity["return_code"] != 0 or not digest or SHA.fullmatch(digest[0]) is None:
            raise RuntimeError("uv 安装脚本为空或 SHA256 未确认")
        state.update(passed=True, phase="complete", installer_sha256=digest[0])
        return state
    except BaseException as exc:
        state["error_type"] = type(exc).__name__
        raise
    finally:
        write_json(evidence / "bootstrap.json", state)


async def verify_installed_runtime(
    environment: BaseEnvironment,
    root: PurePosixPath,
    evidence: Path,
    bootstrap: Mapping[str, Any],
    *,
    wheel: Path,
    requirements: Path,
) -> dict[str, Any]:
    """使用实际 Agent 用户做硬检查；不依赖 Harbor 的 best-effort version。"""
    state: dict[str, Any] = {
        "schema_version": 1,
        "passed": False,
        "model_execution_performed": False,
        "bootstrap": dict(bootstrap),
        "wheel_sha256": file_sha256(wheel),
        "requirements_sha256": file_sha256(requirements),
        "harbor": harbor_installation_identity(),
        "checks": [],
    }
    python = shlex.quote(str(root / "venv/bin/python"))
    imports = (
        "from sayacode.application import SayacodeApp; "
        "from sayacode.agent import AgentRuntime; "
        "from langgraph.runtime import RunControl; "
        "from langchain_core.tracers.context import register_configure_hook; "
        "print('SAYACODE_IMPORT_OK')"
    )
    commands = (
        ("identity", "id -u", None),
        (
            "version",
            f"{shlex.quote(str(root / 'venv/bin/sayacode'))} --version",
            f"SAYACODE {PRODUCT_VERSION}",
        ),
        ("imports", f"{python} -c {shlex.quote(imports)}", "SAYACODE_IMPORT_OK"),
        ("worker-help", f"{python} {shlex.quote(str(root / 'worker.py'))} --help", "--profile"),
    )
    try:
        if (
            bootstrap.get("passed") is not True
            or bootstrap.get("tls_verification_required") is not True
        ):
            raise ValueError("安装后的检查必须绑定成功的 TLS 下载")
        for name, command, expected in commands:
            result = await _record_exec(environment, command, evidence, name, user=None, timeout=90)
            state["checks"].append({"name": name, **result})
            stdout = str(result.get("stdout") or "").strip()
            if result["return_code"] != 0:
                raise RuntimeError(f"安装后 {name} 检查失败")
            if name == "identity":
                if not stdout.isdigit():
                    raise RuntimeError("实际 Agent UID 未确认")
                state["agent_effective_uid"] = int(stdout)
                state["configured_agent_user"] = environment.default_user
            elif name == "worker-help":
                if not all(flag in stdout for flag in ("--profile", "--variant", "--instruction")):
                    raise RuntimeError("worker --help 输出不完整")
            elif stdout != expected:
                raise RuntimeError(f"安装后 {name} 身份不匹配")
        state["passed"] = True
        return state
    except BaseException as exc:
        state["error_type"] = type(exc).__name__
        raise
    finally:
        write_json(evidence / "receipt.json", state, exclusive=True)


def _reference(value: Any, root: Path | None = None) -> Path:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        raise ValueError("原件引用缺少路径")
    path = Path(value["path"])
    if (
        not path.is_absolute()
        or not isinstance(value.get("sha256"), str)
        or SHA.fullmatch(value["sha256"]) is None
    ):
        raise ValueError("原件引用身份无效")
    path = path.resolve(strict=True)
    if root is not None and not path.is_relative_to(root.resolve(strict=True)):
        raise ValueError("预检原件越出冻结 bundle 或 case 目录")
    if not path.is_file() or file_sha256(path) != value["sha256"]:
        raise ValueError("预检原件 SHA256 不符")
    return path


def _tar_json(archive: tarfile.TarFile, name: str) -> dict[str, Any]:
    member = archive.getmember(name)
    if not member.isfile():
        raise ValueError("资格原件必须为普通文件")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError("资格原件缺失")
    value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("资格元数据结构无效")
    return value


def qualified_installation_tasks(
    qualifications: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """只开原 selection/sanity/runtime；不打开题面、参考补丁或模型正文。"""
    expected = {"swe-bench-pro-v2": (8, 24), "terminal-bench-2.1": (2, 12)}
    indexed = {item.get("benchmark"): item for item in qualifications}
    if len(qualifications) != 2 or set(indexed) != set(expected):
        raise ValueError("预检必须保留原 32 SWE 与 14 Terminal")
    result: list[dict[str, Any]] = []
    for benchmark, counts in expected.items():
        path = _reference(indexed[benchmark]["archive"])
        with tarfile.open(path, "r:gz") as archive:
            selection = _tar_json(archive, "qualification/selection.json")
            sanity = _tar_json(archive, "qualification/sanity.json")
            cloud = _tar_json(archive, "inputs/cloud-plan.json")
            if (
                sanity.get("complete") is not True
                or sanity.get("passed") is not True
                or tuple(len(selection.get(part, [])) for part in ("dev", "holdout")) != counts
            ):
                raise ValueError("原资格范围未完整通过")
            qualified = {row["task_id"]: row for row in sanity["tasks"]}
            tasks = [*selection["dev"], *selection["holdout"]]
            if len(qualified) != sum(counts) or len({t["task_id"] for t in tasks}) != sum(counts):
                raise ValueError("原资格任务身份重复或缺失")
            for task in tasks:
                if task["benchmark"] != benchmark:
                    raise ValueError("资格 benchmark 不一致")
                oracle = qualified[task["task_id"]]["oracle"]
                identity = oracle["runtime_identity"]
                reference = oracle["runtime"]
                relative = PurePosixPath(reference["path"]).relative_to(
                    PurePosixPath(cloud["bundle_root"])
                )
                if ".." in relative.parts:
                    raise ValueError("资格 runtime 引用越界")
                member = archive.getmember(str(relative))
                stream = archive.extractfile(member) if member.isfile() else None
                if stream is None:
                    raise ValueError("原生资格 runtime 缺失")
                raw = stream.read()
                if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
                    raise ValueError("原生资格 runtime SHA256 不符")
                native = json.loads(raw)
                if resource_status(identity, task["environment"]) is not True or not all(
                    value is True
                    for value in compare_runtimes(identity, native, task["environment"]).values()
                ):
                    raise ValueError("原资格镜像或资源不符")
                original = task["environment"]["docker_image"]
                repository = (
                    original.split("@", 1)[0] if "@" in original else original.rsplit(":", 1)[0]
                )
                digests = [
                    v for v in identity["repo_digests"] if v.startswith(repository + "@sha256:")
                ]
                if len(digests) != 1:
                    raise ValueError("资格镜像没有唯一固定 RepoDigest")
                result.append(
                    {
                        "benchmark": benchmark,
                        "task_id": task["task_id"],
                        "task": task,
                        "runtime_identity": identity,
                        "immutable_image": digests[0],
                        "host_cohort": cloud["host_cohort"],
                    }
                )
    return result


def installation_inputs(path: Path, source_sha: str | None = None) -> dict[str, Any]:
    """共享输入只作只读绑定，不修改旧研究路径。"""
    inputs = read_json(path)
    root = Path(inputs["bundle_root"]).resolve(strict=True)
    if not path.resolve(strict=True).is_relative_to(root) or inputs.get("schema_version") != 1:
        raise ValueError("预检 inputs 不在冻结 bundle")
    if re.fullmatch(r"[0-9a-f]{40}", str(inputs.get("source_sha"))) is None:
        raise ValueError("预检源码必须为完整 SHA")
    if source_sha is not None and inputs["source_sha"] != source_sha:
        raise ValueError("预检源码与输入不一致")
    for name in ("product_wheel", "requirements", "profile"):
        _reference(inputs[name], root)
    original = read_json(Path(__file__).resolve().parents[2] / "reproduction/identity.json")
    if (
        inputs["product_wheel"]["sha256"] != original["production_wheel_sha256"]
        or inputs["requirements"]["sha256"] != original["requirements_sha256"]
    ):
        raise ValueError("预检必须使用原生产 wheel 和锁定依赖字节")
    profile = read_json(_reference(inputs["profile"], root))
    if "api_key" in profile:
        raise ValueError("安装预检只允许无密钥 profile")
    if set(inputs.get("variants", {})) != {"baseline", "diagnostic", "focused"}:
        raise ValueError("预检必须绑定原三配置")
    for reference in inputs["variants"].values():
        variant = read_json(_reference(reference, root))
        if variant.get("profile_overrides") != {}:
            raise ValueError("预检配置不能变更连接参数")
    for qualification in inputs["qualifications"]:
        _reference(qualification["archive"], root)
    return inputs


def _installation_receipt(
    value: Mapping[str, Any], root: Path, artifacts: Mapping[str, Any]
) -> None:
    if (
        value.get("passed") is not True
        or value.get("model_execution_performed") is not False
        or value.get("wheel_sha256") != artifacts["product_wheel"]
        or value.get("requirements_sha256") != artifacts["requirements"]
        or value.get("harbor") != harbor_installation_identity()
    ):
        raise ValueError("安装硬门禁或发行物身份不符")
    bootstrap = value["bootstrap"]
    codes = [row["return_code"] for row in bootstrap["attempts"]]
    if (
        bootstrap.get("passed") is not True
        or bootstrap.get("tls_verification_required") is not True
        or bootstrap.get("url") != UV_INSTALLER_URL
        or codes not in ([0], [60, 0], [77, 0])
        or bootstrap.get("ca_repair_attempted") is not (len(codes) == 2)
    ):
        raise ValueError("TLS 下载或 CA 修复链未确认")
    checks = value["checks"]
    if [row.get("name") for row in checks] != ["identity", "version", "imports", "worker-help"]:
        raise ValueError("安装后硬检查不完整")
    for row in [*bootstrap["attempts"], *checks]:
        for field in ("stdout", "stderr"):
            if row.get(field) is not None:
                original = _reference(row[field + "_file"], root).read_text(encoding="utf-8")
                if original != row[field]:
                    raise ValueError("安装原输出与收据不一致")
    if any(row["return_code"] != 0 or row["requested_user"] is not None for row in checks):
        raise ValueError("硬检查没有使用实际 Agent 用户或命令失败")
    if (
        str(checks[0]["stdout"]).strip() != str(value["agent_effective_uid"])
        or str(checks[1]["stdout"]).strip() != f"SAYACODE {PRODUCT_VERSION}"
        or str(checks[2]["stdout"]).strip() != "SAYACODE_IMPORT_OK"
        or not all(
            flag in checks[3]["stdout"] for flag in ("--profile", "--variant", "--instruction")
        )
    ):
        raise ValueError("安装后版本、导入或 worker 入口不符")


def validate_installation_case_native(
    case: Mapping[str, Any],
    case_root: Path,
    wanted: Mapping[str, Any],
    artifact_identity: Mapping[str, Any],
) -> None:
    """生成收据前和合并后共用同一原生硬门禁。"""
    native = case["native"]
    trial = read_json(_reference(native["trial_result"], case_root))
    job = read_json(_reference(native["job_result"], case_root))
    runtime = read_json(_reference(native["runtime"], case_root))
    installed = read_json(_reference(native["installation"], case_root))
    task_path = _reference(native["task_config"], case_root)
    synthetic = tomllib.loads(task_path.read_text(encoding="utf-8"))
    if (
        trial["config"].get("install_only") is not True
        or trial["config"]["agent"]["import_path"] != "sayacode_bench.adapter:SayacodeAgent"
        or trial.get("exception_info") is not None
        or (trial.get("agent_setup") or {}).get("started_at") is None
        or (trial.get("agent_setup") or {}).get("finished_at") is None
        or trial.get("finished_at") is None
        or trial["config"]["agent"].get("model_name") is not None
        or any(
            trial.get(k) is not None
            for k in ("agent_execution", "verifier", "agent_result", "verifier_result")
        )
        or job.get("n_total_trials") != 1
        or job.get("finished_at") is None
        or job["stats"].get("n_completed_trials") != 1
        or job["stats"].get("n_errored_trials") != 0
        or job["stats"].get("n_running_trials") != 0
        or job["stats"].get("n_pending_trials") != 0
        or job["stats"].get("n_retries") != 0
    ):
        raise ValueError("原生 install_only 阶段未确认")
    # 资格以 tag 请求、预检以已核 digest 请求；只统一期待视图中的地址。
    # 实际请求必须固定 digest，原件不改写，实际 Image ID 与资源仍逐项比较。
    qualified_runtime = wanted["runtime_identity"]
    expected_runtime = {
        **qualified_runtime,
        "requested": {**qualified_runtime["requested"], "docker_image": wanted["immutable_image"]},
    }
    if (
        synthetic["environment"]["docker_image"] != wanted["immutable_image"]
        or runtime.get("requested", {}).get("docker_image") != wanted["immutable_image"]
        or synthetic.get("agent", {}).get("user") != wanted["task"]["agent"].get("user")
        or installed.get("configured_agent_user") != wanted["task"]["agent"].get("user")
        or resource_status(runtime, wanted["task"]["environment"]) is not True
        or not all(
            v is True
            for v in compare_runtimes(
                runtime, expected_runtime, wanted["task"]["environment"]
            ).values()
        )
    ):
        raise ValueError("预检 Agent 用户、原镜像或官方资源不符")
    _installation_receipt(installed, case_root, artifact_identity)
    host = case["host"]
    preparation = read_json(_reference(host["runner_preparation"], case_root))
    probe = read_json(_reference(host["network_probe"], case_root))
    repository = Path(__file__).resolve().parents[2]
    if (
        preparation.get("passed") is not True
        or preparation.get("repository") != "saya-ch/sayacode-bench-runs"
        or preparation.get("runner_image") != wanted["host_cohort"]
        or preparation.get("script_sha256")
        != file_sha256(repository / "scripts/prepare_cloud_runner.py")
        or probe.get("passed") is not True
        or probe.get("cleanup_confirmed") is not True
        or probe.get("cleanup_errors") != []
        or probe.get("source_sha256", {}).get("network.py")
        != file_sha256(repository / "src/sayacode_bench/network.py")
        or probe.get("source_sha256", {}).get("test_network.py")
        != file_sha256(repository / "tests/test_network.py")
    ):
        raise ValueError("预检宿主 cohort、准备或网络探针原件不符")


def validate_installation_preflight(
    reference: Mapping[str, Any],
    *,
    tasks: Sequence[Mapping[str, Any]] | None = None,
    artifacts: Mapping[str, Any] | None = None,
    implementation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """每次重开完整46原件；阶段任务只能是原集合的精确子集。"""
    receipt_path = _reference(reference)
    receipt = read_json(receipt_path)
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "installation_preflight"
        or receipt.get("complete") is not True
        or receipt.get("passed") is not True
    ):
        raise ValueError("完整46安装预检尚未通过")
    inputs_path = _reference(receipt["inputs"])
    inputs = installation_inputs(inputs_path, receipt["source_sha"])
    root = Path(inputs["bundle_root"])
    _reference(reference, root)
    identities = source_identity()
    if receipt["source_identity"] != identities or (
        implementation is not None and dict(implementation) != identities["implementation"]
    ):
        raise ValueError("预检源码已变化")
    if receipt.get("harbor") != harbor_installation_identity():
        raise ValueError("预检 Harbor 发行版或关键源码变化")
    expected = qualified_installation_tasks(inputs["qualifications"])
    artifact_identity = {
        "product_wheel": inputs["product_wheel"]["sha256"],
        "requirements": inputs["requirements"]["sha256"],
        "variants": {k: v["sha256"] for k, v in inputs["variants"].items()},
    }
    if artifacts is not None:
        if any(artifacts.get(k) != artifact_identity[k] for k in ("product_wheel", "requirements")):
            raise ValueError("模型阶段发行物不是预检原件")
        if any(
            artifact_identity["variants"].get(k) != v
            for k, v in artifacts.get("variants", {}).items()
        ):
            raise ValueError("模型阶段配置不是预检原件")
    if len(receipt["cases"]) != 46:
        raise ValueError("预检不能缩减原46分母")
    for index, (case_ref, wanted) in enumerate(zip(receipt["cases"], expected, strict=True), 1):
        case_path = _reference(case_ref, root)
        case = read_json(case_path)
        if (
            case.get("kind") != "installation_preflight_case"
            or case.get("passed") is not True
            or case.get("complete") is not True
            or case.get("case_index") != index
            or case.get("inputs") != receipt["inputs"]
            or case.get("source_sha") != inputs["source_sha"]
            or case.get("task") != wanted["task"]
        ):
            raise ValueError("预检 case 缺失、顺序、任务或输入不符")
        validate_installation_case_native(case, case_path.parent, wanted, artifact_identity)
    known = {(row["benchmark"], row["task_id"]): row["task"] for row in expected}
    if tasks is not None and any(
        known.get((t.get("benchmark"), t.get("task_id"))) != dict(t) for t in tasks
    ):
        raise ValueError("阶段任务不属于完整预检的固定原集合")
    return {
        **receipt,
        "coverage": {"swe-bench-pro-v2": 32, "terminal-bench-2.1": 14},
        "artifacts": artifact_identity,
        "profile": read_json(_reference(inputs["profile"], root)),
    }
