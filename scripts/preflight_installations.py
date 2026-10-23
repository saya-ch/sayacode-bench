"""固定46镜像的原生 install_only 预检；单case执行，不调度模型任务。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from harbor.job import Job
from harbor.models.job.config import JobConfig, RetryConfig
from harbor.models.trial.config import AgentConfig, EnvironmentConfig, TaskConfig

from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.installation import (
    file_reference,
    harbor_installation_identity,
    installation_inputs,
    qualified_installation_tasks,
    source_identity,
    validate_installation_case_native,
    validate_installation_preflight,
)
from scripts.prepare_cloud_runner import require_hosted_runner

ROOT = Path(__file__).resolve().parents[1]


def verify_source(source_sha: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise ValueError("必须固定完整预检源码 SHA")
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=ROOT, check=True)
    if current != source_sha:
        raise ValueError("预检源码身份不符")


def _artifacts(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_wheel": inputs["product_wheel"]["sha256"],
        "requirements": inputs["requirements"]["sha256"],
        "variants": {k: v["sha256"] for k, v in inputs["variants"].items()},
    }


def _synthetic_task(directory: Path, wanted: dict[str, Any]) -> Path:
    """只写独占预检配置；官方题面、gold和任务文件不进入该目录。"""
    directory.mkdir(exist_ok=False)
    (directory / "environment").mkdir()
    (directory / "tests").mkdir()
    (directory / "instruction.md").write_text(
        "Installation-only infrastructure preflight. Do not execute a task.\n", encoding="utf-8"
    )
    (directory / "tests/test.sh").write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
    task = wanted["task"]
    agent: dict[str, Any] = {
        "timeout_sec": task["agent"]["timeout_sec"],
        "network_mode": "no-network",
    }
    if task["agent"].get("user") is not None:
        agent["user"] = task["agent"]["user"]
    environment = {
        key: task["environment"][key]
        for key in ("cpus", "memory_mb", "storage_mb", "build_timeout_sec")
    }
    environment.update(
        docker_image=wanted["immutable_image"], network_mode="public", workdir="/tmp"
    )
    content = ['version = "1.0"', ""]
    for name, values in (
        ("metadata", {"category": "installation-preflight-not-benchmark"}),
        ("agent", agent),
        ("verifier", {"timeout_sec": 1, "network_mode": "no-network"}),
        ("environment", environment),
    ):
        content.append(f"[{name}]")
        content.extend(
            f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in values.items()
        )
        content.append("")
    path = directory / "task.toml"
    path.write_text("\n".join(content), encoding="utf-8")
    return path


def _host_evidence(
    output: Path, preparation: Path, probe: Path, wanted: dict[str, Any]
) -> dict[str, Any]:
    observed, network = read_json(preparation), read_json(probe)
    if (
        observed.get("passed") is not True
        or observed.get("repository") != "saya-ch/sayacode-bench-runs"
        or observed.get("runner_image") != wanted["host_cohort"]
        or observed.get("script_sha256") != file_sha256(ROOT / "scripts/prepare_cloud_runner.py")
        or network.get("passed") is not True
        or network.get("cleanup_confirmed") is not True
        or network.get("cleanup_errors") != []
        or network.get("source_sha256", {}).get("network.py")
        != file_sha256(ROOT / "src/sayacode_bench/network.py")
        or network.get("source_sha256", {}).get("test_network.py")
        != file_sha256(ROOT / "tests/test_network.py")
    ):
        raise ValueError("宿主 cohort 或准备/网络探针未通过")
    host = output / "host"
    host.mkdir(exist_ok=False)
    for source, name in ((preparation, "runner-preparation.json"), (probe, "network-probe.json")):
        with (host / name).open("xb") as target:
            target.write(source.read_bytes())
    return {
        "runner_preparation": file_reference(host / "runner-preparation.json"),
        "network_probe": file_reference(host / "network-probe.json"),
    }


async def run_case(
    inputs_path: Path,
    source_sha: str,
    case_index: int,
    output: Path,
    runner_preparation: Path,
    probe: Path,
) -> dict[str, Any]:
    require_hosted_runner()
    verify_source(source_sha)
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise ValueError("原生预检不自动重跑已启动case")
    if any(
        name in os.environ
        for name in (
            "STUDY_CONNECTION_KEYS_JSON",
            "SAYACODE_STUDY_CONNECTION_KEYS_JSON",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "SILICONFLOW_API_KEY",
            "DEEPSEEK_API_KEY",
        )
    ):
        raise ValueError("安装预检不能获得模型凭据")
    inputs = installation_inputs(inputs_path, source_sha)
    cases = qualified_installation_tasks(inputs["qualifications"])
    if type(case_index) is not int or not 1 <= case_index <= 46:
        raise ValueError("case_index必须保留固定1..46范围")
    expected_output = (
        Path(inputs["bundle_root"]) / "installations/restart-v2" / f"case-{case_index:04d}"
    )
    if output.resolve() != expected_output.resolve():
        raise ValueError("预检case输出目录不是固定独占路径")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    wanted = cases[case_index - 1]
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "kind": "installation_preflight_case",
        "case_index": case_index,
        "inputs": file_reference(inputs_path),
        "source_sha": source_sha,
        "task": wanted["task"],
        "complete": False,
        "passed": False,
        "error_type": None,
        "native": {},
        "supplier_model_requests": 0,
    }
    write_json(output / "attempt.json", receipt, exclusive=True)
    try:
        receipt["host"] = _host_evidence(output, runner_preparation, probe, wanted)
        if shutil.disk_usage(output).free < 12 * 1024**3:
            raise ValueError("安装前磁盘余量不足12GiB")
        task_config = _synthetic_task(output / "synthetic-task", wanted)
        job_name = f"installation-{case_index:04d}"
        config = JobConfig(
            job_name=job_name,
            jobs_dir=output / "native",
            n_attempts=1,
            install_only=True,
            n_concurrent_trials=1,
            retry=RetryConfig(max_retries=0),
            quiet=True,
            tasks=[TaskConfig(path=task_config.parent)],
            agents=[
                AgentConfig(
                    import_path="sayacode_bench.adapter:SayacodeAgent",
                    kwargs={
                        "product_wheel": inputs["product_wheel"]["path"],
                        "requirements_path": inputs["requirements"]["path"],
                        "profile_path": inputs["profile"]["path"],
                        "variant_path": inputs["variants"]["baseline"]["path"],
                    },
                )
            ],
            environment=EnvironmentConfig(
                import_path="sayacode_bench.network:IsolatedDockerEnvironment",
                delete=True,
                kwargs={"messages_upstream": "http://127.0.0.1:9/v1/messages"},
            ),
        )
        write_json(output / "native-config.json", config.model_dump(mode="json"), exclusive=True)
        job = await Job.create(config)
        await job.run()
        job_directory = output / "native" / job_name
        trials = [
            p / "result.json"
            for p in job_directory.iterdir()
            if p.is_dir() and (p / "result.json").is_file()
        ]
        if len(trials) != 1:
            raise ValueError("原生预检没有唯一TrialResult")
        trial = trials[0].parent
        receipt["native"] = {
            "job_result": file_reference(job_directory / "result.json"),
            "trial_result": file_reference(trial / "result.json"),
            "task_config": file_reference(task_config),
        }
        for label, path in (
            ("runtime", trial / "runtime.json"),
            ("installation", trial / "agent/installation/receipt.json"),
        ):
            if path.is_file():
                receipt["native"][label] = file_reference(path)
        validate_installation_case_native(receipt, output, wanted, _artifacts(inputs))
        receipt.update(complete=True, passed=True)
    except Exception as exc:
        receipt["error_type"] = type(exc).__name__
        receipt["failure_message"] = str(exc)
    finally:
        write_json(output / "case-receipt.json", receipt, exclusive=True)
    return receipt


def merge_cases(
    inputs_path: Path, source_sha: str, case_receipts: list[Path], output: Path
) -> dict[str, Any]:
    require_hosted_runner()
    verify_source(source_sha)
    inputs = installation_inputs(inputs_path, source_sha)
    root = Path(inputs["bundle_root"]).resolve(strict=True)
    if output.resolve() != (root / "installations/restart-v2/preflight.json"):
        raise ValueError("完整预检收据必须位于固定bundle路径")
    output.parent.mkdir(parents=True, exist_ok=True)
    cases = [read_json(path) for path in case_receipts]
    indexed = {case["case_index"]: path for case, path in zip(cases, case_receipts, strict=True)}
    complete = len(cases) == 46 and set(indexed) == set(range(1, 47))
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "kind": "installation_preflight",
        "source_sha": source_sha,
        "inputs": file_reference(inputs_path),
        "source_identity": source_identity(),
        "harbor": harbor_installation_identity(),
        "complete": complete,
        "passed": complete,
        "cases": [file_reference(indexed[i]) for i in sorted(indexed)],
        "missing_indices": sorted(set(range(1, 47)) - set(indexed)),
        "supplier_model_requests": 0,
    }
    candidate = output.with_name(output.stem + ".candidate.json")
    write_json(candidate, receipt, exclusive=True)
    try:
        if not complete:
            raise ValueError("原46安装预检尚未完整")
        validate_installation_preflight(file_reference(candidate))
    except Exception as exc:
        receipt.update(
            complete=False, passed=False, error_type=type(exc).__name__, failure_message=str(exc)
        )
    write_json(output, receipt, exclusive=True)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "merge"):
        child = sub.add_parser(command)
        child.add_argument("--inputs", type=Path, required=True)
        child.add_argument("--source-sha", required=True)
        child.add_argument("--output", type=Path, required=True)
        if command == "run":
            child.add_argument("--case-index", type=int, required=True)
            child.add_argument("--runner-preparation", type=Path, required=True)
            child.add_argument("--probe", type=Path, required=True)
        else:
            child.add_argument("--case-receipts", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    if args.command == "run":
        result = asyncio.run(
            run_case(
                args.inputs,
                args.source_sha,
                args.case_index,
                args.output,
                args.runner_preparation,
                args.probe,
            )
        )
    else:
        result = merge_cases(args.inputs, args.source_sha, args.case_receipts, args.output)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "complete": result["complete"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
