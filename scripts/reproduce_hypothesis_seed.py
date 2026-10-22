"""固定 qutebrowser 镜像与 Hypothesis seed，独立三次参考解诊断，不调用模型。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.execution import run_official_trial
from sayacode_bench.network import docker
from sayacode_bench.sources import SOURCES, fetch_source
from scripts import diagnose_fixtures as fixtures
from scripts.regrade_calibration_patches import native_result_observations

SEED = "242126932532074149523975327703198283377"
HASH_SEED = "0"
_IMAGE_ADDOPTS = (
    '{{range .Config.Env}}{{if eq (index (split . "=") 0) "PYTEST_ADDOPTS"}}'
    "{{json .}}{{println}}{{end}}{{end}}"
)


def fixed_plan() -> dict[str, Any]:
    """题目、镜像、次数与两种 seed 均不能由命令行更换。"""
    fixture = fixtures.fixed_plan()["fixtures"][0]
    return {
        "schema_version": 1,
        "phase": "fixed_hypothesis_seed_fixture_diagnostic",
        "benchmark": "swe-bench-pro-v2",
        "revision": fixtures.REVISION,
        "harbor_version": "0.24.0",
        "fixture": fixture,
        "hypothesis_seed": SEED,
        "python_hash_seed": HASH_SEED,
        "external_diagnostic_window_seconds": 1500,
        "external_force_cancel_grace_seconds": 60,
        "external_window_scope": "25 minute supervisor window for this diagnostic, not a claim of exhausting every official task timeout; incomplete stays incomplete",
        "pytest_addopts_policy": "append fixed seed to PYTEST_ADDOPTS read from pinned image",
        "schedule": [
            {
                "fixture": fixture["name"],
                "task_id": fixture["task_id"],
                "agent": "oracle",
                "repeat": repeat,
                "job_name": f"hypothesis-seed-oracle-{repeat}",
            }
            for repeat in (1, 2, 3)
        ],
        "model_requests": 0,
        "formal_comparison_eligible": False,
        "formal_validation_eligible": False,
        "affects_original_scores": False,
        "interpretation": "固定三次全新环境；验证器 env 追加 seed 并固定 Python hash seed，属于独立诊断偏离，不替换原始资格或模型评分。",
    }


def _value_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def verifier_environment(fixture: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    """Docker 模板仅返回指定键，不将整个镜像 Config.Env 读出或归档。"""
    output = await docker(
        "image", "inspect", "--format", _IMAGE_ADDOPTS, fixture["immutable_image"]
    )
    values = [json.loads(line) for line in output.splitlines() if line.strip()]
    if len(values) > 1 or any(
        not isinstance(value, str) or not value.startswith("PYTEST_ADDOPTS=") for value in values
    ):
        raise ValueError("固定镜像的 PYTEST_ADDOPTS 不唯一或无法确认")
    original = values[0].partition("=")[2] if values else ""
    combined = original + (" " if original else "") + f"--hypothesis-seed={SEED}"
    environment = {"PYTEST_ADDOPTS": combined, "PYTHONHASHSEED": HASH_SEED}
    return environment, {
        "image_pytest_addopts_present": bool(values),
        "image_pytest_addopts_sha256": _value_hash(original),
        "image_pytest_addopts_bytes": len(original.encode()),
        "verifier_env_sha256": _value_hash(environment),
        "hypothesis_seed": SEED,
        "python_hash_seed": HASH_SEED,
    }


def native_config_observations(
    raw: dict[str, Any], raw_root: Path, expected_env: dict[str, str], task_id: str
) -> dict[str, Any]:
    """同时校验 Harbor 保存的 Job 与 Trial 配置，只公开固定参数证明和哈希。"""
    job = Path(raw.get("job_dir", "")).resolve()
    if not job.is_relative_to(raw_root.resolve()):
        raise ValueError("原生配置路径越过本次输出目录")
    paths = list(job.glob("instance_*/config.json"))
    if len(paths) != 1:
        raise ValueError("缺少唯一原生 Trial 配置")
    job_path, trial_path = job / "config.json", paths[0]
    job_config, trial_config = read_json(job_path), read_json(trial_path)
    expected_verifier = {"env": expected_env}
    # 使用原生配置模型补全被 exclude_defaults 省略的默认字段。
    from harbor.models.job.config import JobConfig
    from harbor.models.trial.config import TrialConfig, VerifierConfig

    job_value = JobConfig.model_validate(job_config)
    trial_value = TrialConfig.model_validate(trial_config)
    if (
        job_value.verifier != VerifierConfig.model_validate(expected_verifier)
        or trial_value.verifier != VerifierConfig.model_validate(expected_verifier)
        or len(job_value.tasks) != 1
        or job_value.tasks[0].path is None
        or job_value.tasks[0].path.name != task_id
        or trial_value.task.path is None
        or trial_value.task.path.name != task_id
        or len(job_value.agents) != 1
        or job_value.agents[0].name != "oracle"
        or job_value.agents[0].import_path is not None
        or trial_value.agent.name != "oracle"
        or trial_value.agent.import_path is not None
        or job_value.n_attempts != 1
        or job_value.n_concurrent_trials != 1
        or job_value.retry.max_retries != 0
        or any(
            value.timeout_multiplier != 1
            or any(
                getattr(value, name) is not None
                for name in (
                    "agent_timeout_multiplier",
                    "verifier_timeout_multiplier",
                    "agent_setup_timeout_multiplier",
                    "environment_build_timeout_multiplier",
                )
            )
            or any(
                getattr(value.environment, name) is not None
                for name in (
                    "override_cpus",
                    "override_memory_mb",
                    "override_storage_mb",
                    "override_gpus",
                    "override_tpu",
                )
            )
            for value in (job_value, trial_value)
        )
    ):
        raise ValueError("原生配置与固定 oracle、验证器 env 或原始预算不一致")
    return {
        "available": True,
        "matches_expected": True,
        "native_job_config_sha256": file_sha256(job_path),
        "native_trial_config_sha256": file_sha256(trial_path),
        "verifier_env_sha256": _value_hash(trial_value.verifier.env),
        "hypothesis_seed": SEED,
        "python_hash_seed": HASH_SEED,
        "agent": "oracle",
        "task_id_matches": True,
        "task_overrides": False,
    }


def summary(
    plan: dict[str, Any], records: list[dict[str, Any]], *, interrupted: bool
) -> dict[str, Any]:
    complete = len(records) == 3 and all(
        row.get("attempted") is True
        and row.get("image_matches_expected") is True
        and row.get("native_status") == "completed"
        and row.get("verified") is True
        and type(row.get("original_reward")) in (int, float)
        and row["original_reward"] in (0, 1)
        and row.get("native_trial", {}).get("available") is True
        and row.get("native_config", {}).get("matches_expected") is True
        for row in records
    )
    return {
        "phase": plan["phase"],
        "planned_jobs": 3,
        "recorded_jobs": len(records),
        "all_jobs_attempted": len(records) == 3
        and all(row.get("attempted") is True for row in records),
        "diagnostic_evidence_complete": complete and not interrupted,
        "oracle_all_passed": complete and all(row["original_reward"] == 1 for row in records),
        "oracle_rewards": [row.get("original_reward") for row in records],
        "statuses": [row.get("status") for row in records],
        "hypothesis_seed": SEED,
        "python_hash_seed": HASH_SEED,
        "interrupted": interrupted,
        "external_diagnostic_window_seconds": plan["external_diagnostic_window_seconds"],
        "model_requests": 0,
        "formal_comparison_eligible": False,
        "formal_validation_eligible": False,
        "affects_original_scores": False,
        "interpretation": plan["interpretation"],
    }


async def reproduce(cache: Path, output: Path) -> dict[str, Any]:
    """三次固定全跑，0 分也照常保留；准备失败和中断不能冒充完整证据。"""
    output, cache = output.resolve(), cache.resolve()
    repository = Path(__file__).parents[1].resolve()
    if any(
        output.is_relative_to(root) or root.is_relative_to(output) for root in (cache, repository)
    ):
        raise ValueError("输出必须与源码缓存和仓库隔离，原始工件只保留在仓库外")
    if output.exists():
        raise FileExistsError("固定 seed 诊断必须使用新目录")
    if version("harbor") != "0.24.0" or SOURCES["swe-bench-pro-v2"].revision != fixtures.REVISION:
        raise ValueError("仅支持冻结的 Harbor 与公开源版本")
    public, raw_root = output / "public", output / "raw" / "jobs"
    public.mkdir(parents=True)
    plan = fixed_plan()
    write_json(public / "plan.json", plan, exclusive=True)
    write_json(
        public / "host.json",
        {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "host_python": sys.version,
            "harbor_version": version("harbor"),
            "script_sha256": file_sha256(Path(__file__)),
            "fixture_helpers_sha256": file_sha256(Path(fixtures.__file__)),
            "native_result_helpers_sha256": file_sha256(
                Path(native_result_observations.__code__.co_filename)
            ),
            "uv_lock_sha256": file_sha256(repository / "uv.lock"),
        },
    )
    records: list[dict[str, Any]] = []
    interrupted = False
    try:
        ready: dict[str, Any] = {}
        snapshot = None
        verifier_env: dict[str, str] = {}
        try:
            snapshot = fetch_source(SOURCES["swe-bench-pro-v2"], cache)
            ready = {
                **fixtures.fixture_metadata(snapshot, plan["fixture"]),
                **await fixtures.pin_image(plan["fixture"]),
            }
            verifier_env, env_proof = await verifier_environment(plan["fixture"])
            write_json(output / "raw" / "verifier-env.json", verifier_env, exclusive=True)
            write_json(public / "verifier-env-proof.json", env_proof, exclusive=True)
        except Exception as exc:
            ready["error_type"] = type(exc).__name__
        write_json(public / "image-preparation.json", ready)
        for item in plan["schedule"]:
            observation: dict[str, Any] = {**item, "attempted": False}
            try:
                if snapshot is None or "error_type" in ready:
                    observation.update(
                        status="preparation_failed", error_type=ready.get("error_type")
                    )
                else:
                    observation["attempted"] = True
                    raw = await run_official_trial(
                        snapshot.tasks_path / item["task_id"],
                        raw_root,
                        item["job_name"],
                        {"name": "oracle"},
                        {
                            "import_path": "sayacode_bench.network:IsolatedDockerEnvironment",
                            "kwargs": {"messages_upstream": "http://127.0.0.1:9/v1/messages"},
                        },
                        configuration="oracle",
                        repeat=item["repeat"],
                        canonical_model="not_used",
                        endpoint="not_used",
                        verifier_config={"env": verifier_env},
                    )
                    observation.update({key: raw.get(key) for key in fixtures._OUTCOME_FIELDS})
                    observation["native_status"] = raw.get("status")
                    observation.update(
                        fixtures.collect_trial(raw, public, item["job_name"], ready, raw_root)
                    )
                    observation["native_trial"] = native_result_observations(
                        raw, raw_root, item["task_id"]
                    )
                    observation["native_config"] = native_config_observations(
                        raw, raw_root, verifier_env, item["task_id"]
                    )
                    write_json(
                        public / "trials" / item["job_name"] / "native-observations.json",
                        {
                            "result": observation["native_trial"],
                            "config": observation["native_config"],
                        },
                    )
            except Exception as exc:
                observation.update(status="diagnostic_error", error_type=type(exc).__name__)
            records.append(observation)
            write_json(public / "records.json", records)
            write_json(public / "summary.json", summary(plan, records, interrupted=False))
            print(
                f"[{len(records)}/3] oracle #{item['repeat']}: {observation.get('status')}",
                flush=True,
            )
    except BaseException:
        interrupted = True
        raise
    finally:
        result = summary(plan, records, interrupted=interrupted)
        write_json(public / "summary.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(reproduce(args.cache, args.output))
    except KeyboardInterrupt:
        return 130
    return 0 if result["diagnostic_evidence_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
