"""固定两题、每题三参考解一空解的无模型跨宿主诊断；不改本地资格结论。"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import re
import shutil
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path
from typing import Any

from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.execution import run_official_trial
from sayacode_bench.network import docker
from sayacode_bench.sources import SOURCES, SourceSnapshot, fetch_source

REVISION = "66f92766bba642462d4bbe5479e83f91f9211862"
REPOSITORY = "ghcr.io/scaleapi/swe-bench_pro-v2"
FIXTURES = (
    {
        "name": "calibration-qutebrowser",
        "task_id": "instance_qutebrowser__qutebrowser-3d01c201b8aa54dd71d4f801b1dd12feb4c0a08a-v5fc38aaf22415ab0b70567368332beee7955b367",
        "digest": "sha256:cc0e0f503659eac82afb4f304e853c5a94ddd2aba834e62d3fd757fa6fba13e3",
    },
    {
        "name": "development-openlibrary",
        "task_id": "instance_internetarchive__openlibrary-ba3abfb6af6e722185d3715929ab0f3e5a134eed-v76304ecdb3a5954fcf13feb710e8c40fcf24b73c",
        "digest": "sha256:94e6d17b2ccb9a6012860bd61e85fb9182b073f1673e46a01d0565989fe09add",
    },
)
_VERIFIER_FILES = (
    "test-stdout.txt",
    "test-stderr.txt",
    "run-script-stdout.txt",
    "run-script-stderr.txt",
)
_OUTCOME_FIELDS = (
    "status",
    "original_reward",
    "verified",
    "harbor_exception_type",
    "duration_seconds",
    "task_checksum",
    "request_sha256",
)


def fixed_plan() -> dict[str, Any]:
    """不接收题目参数，不读取其他开发任务或最终验收题面。"""
    return {
        "schema_version": 1,
        "phase": "cross_host_fixture_diagnostic",
        "benchmark": "swe-bench-pro-v2",
        "revision": REVISION,
        "harbor_version": "0.24.0",
        "model_agent_used": False,
        "model_requests": 0,
        "fixtures": [
            {
                **item,
                "immutable_image": f"{REPOSITORY}@{item['digest']}",
                "original_image_reference": f"{REPOSITORY}:{item['task_id']}",
            }
            for item in FIXTURES
        ],
        "schedule": [
            {
                "fixture": item["name"],
                "task_id": item["task_id"],
                "agent": agent,
                "repeat": repeat,
                "job_name": f"cross-host-{index}-{agent}-{repeat}",
            }
            for index, item in enumerate(FIXTURES, 1)
            for agent, repeat in (("oracle", 1), ("oracle", 2), ("oracle", 3), ("nop", 1))
        ],
        "interpretation": "固定八次，不按成绩挑选；跨宿主诊断不替换本地评分或资格决定。",
        "formal_comparison_eligible": False,
        "affects_local_scores": False,
    }


async def pin_image(fixture: dict[str, Any]) -> dict[str, Any]:
    """拉取不可变 digest，再给原 task.toml 引用赋同一 tag，不改任务文件。"""
    immutable = fixture["immutable_image"]
    await docker("pull", immutable, timeout=600)
    await docker("tag", immutable, fixture["original_image_reference"])
    image = json.loads(await docker("image", "inspect", fixture["original_image_reference"]))[0]
    if immutable not in image.get("RepoDigests", []):
        raise ValueError("实际镜像未保留预定仓库 digest")
    return {
        "expected_image_id": image["Id"],
        "expected_repo_digest": immutable,
        "architecture": image.get("Architecture"),
        "os": image.get("Os"),
    }


def fixture_metadata(snapshot: SourceSnapshot, fixture: dict[str, Any]) -> dict[str, Any]:
    """只解析指定两题的公开资源配置，不加载参考补丁或其他题目。"""
    if snapshot.spec.revision != REVISION:
        raise ValueError("公开源提交与固定诊断不一致")
    task = snapshot.tasks_path / fixture["task_id"]
    configuration = tomllib.loads((task / "task.toml").read_text(encoding="utf-8"))
    resources = configuration.get("environment", {})
    if (
        resources.get("docker_image") != fixture["original_image_reference"]
        or resources.get("cpus") != 1
        or resources.get("memory_mb") != 4096
    ):
        raise ValueError("任务资源或镜像引用与已知诊断基线不一致")
    return {
        "task_config_sha256": file_sha256(task / "task.toml"),
        "official_resources": {
            key: resources.get(key) for key in ("cpus", "memory_mb", "storage_mb", "docker_image")
        },
    }


def verifier_observations(directory: Path) -> dict[str, Any]:
    """只导出数量、异常类型与工件哈希；原始断言正文不进入云 artifact。"""
    observations = {}
    for name in _VERIFIER_FILES:
        source = directory / name
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8", errors="replace")
        errors: dict[str, int] = {}
        for kind in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)):", text):
            errors[kind] = errors.get(kind, 0) + 1
        counts = {}
        for count, status in re.findall(
            r"\b(\d+)\s+(passed|failed|errors?|skipped|deselected|xfailed|xpassed)\b", text
        ):
            counts[status] = int(count)
        required = re.findall(r"Required tests:\s*(\d+)", text)
        passed = re.findall(r"Passed tests:\s*(\d+)", text)
        observations[name] = {
            "bytes": source.stat().st_size,
            "sha256": file_sha256(source),
            "exception_types": errors,
            "pytest_counts": counts,
            "required_tests": int(required[-1]) if required else None,
            "passed_required_tests": int(passed[-1]) if passed else None,
            "segmentation_fault": "segmentation fault" in text.lower(),
            "pytest_internal_error": "INTERNALERROR>" in text,
            "fatal_python_error": "fatal python error" in text.lower(),
        }
    return observations


def collect_trial(
    raw: dict[str, Any],
    public: Path,
    job_name: str,
    pinned: dict[str, Any],
    raw_root: Path,
) -> dict[str, Any]:
    """从唯一原生 trial 收集最小诊断证据，绝不复制 agent/solution 日志。"""
    result = {key: raw.get(key) for key in _OUTCOME_FIELDS}
    job_dir = Path(raw.get("job_dir", "")).resolve()
    if not job_dir.is_relative_to(raw_root.resolve()):
        raise ValueError("原始 job 路径越过本次独占输出目录")
    trials = list(job_dir.glob("instance_*/result.json"))
    if len(trials) != 1:
        return {**result, "image_matches_expected": None, "trial_evidence": "not_unique_or_missing"}
    trial = trials[0].parent
    target = public / "trials" / job_name
    target.mkdir(parents=True, exist_ok=True)
    runtime_path = trial / "runtime.json"
    runtime = read_json(runtime_path) if runtime_path.is_file() else {}
    matched = (
        (
            runtime.get("available") is True
            and runtime.get("image_id") == pinned["expected_image_id"]
            and pinned["expected_repo_digest"] in runtime.get("repo_digests", [])
        )
        if runtime
        else None
    )
    if runtime:
        # runtime 是本仓库环境生成的公开资源白名单，不含容器 Config.Env。
        shutil.copyfile(runtime_path, target / "runtime.json")
        result["runtime_sha256"] = file_sha256(runtime_path)
    write_json(target / "verifier-observations.json", verifier_observations(trial / "verifier"))
    result.update(
        image_matches_expected=matched,
        verifier_observations=f"trials/{job_name}/verifier-observations.json",
    )
    return result


def summary(
    plan: dict[str, Any], records: list[dict[str, Any]], *, interrupted: bool
) -> dict[str, Any]:
    results = {}
    for fixture in plan["fixtures"]:
        rows = [row for row in records if row["fixture"] == fixture["name"]]
        results[fixture["name"]] = {
            "task_id": fixture["task_id"],
            "expected_digest": fixture["digest"],
            "oracle_rewards": [
                row.get("original_reward") for row in rows if row["agent"] == "oracle"
            ],
            "nop_rewards": [row.get("original_reward") for row in rows if row["agent"] == "nop"],
            "statuses": [row.get("status") for row in rows],
        }
    return {
        "phase": plan["phase"],
        "planned_jobs": 8,
        "recorded_jobs": len(records),
        "all_jobs_attempted": len(records) == 8
        and all(row.get("attempted") is True for row in records),
        "all_expected_images_confirmed": len(records) == 8
        and all(row.get("image_matches_expected") is True for row in records),
        "interrupted": interrupted,
        "fixtures": results,
        "model_requests": 0,
        "formal_comparison_eligible": False,
        "affects_local_scores": False,
        "interpretation": plan["interpretation"],
    }


async def diagnose(cache: Path, output: Path) -> dict[str, Any]:
    """固定运行全部八次；成绩或单次执行错误均不会触发挑选重试。"""
    output, cache = output.resolve(), cache.resolve()
    if output.is_relative_to(cache) or cache.is_relative_to(output):
        raise ValueError("输出与源缓存必须隔离")
    if output.exists():
        raise FileExistsError("诊断必须使用新目录，不能覆盖或续选旧成绩")
    if version("harbor") != "0.24.0" or SOURCES["swe-bench-pro-v2"].revision != REVISION:
        raise ValueError("仅支持已锁定的 Harbor 和公开源版本")
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
            "uv_lock_sha256": file_sha256(Path(__file__).parents[1] / "uv.lock"),
        },
    )
    records: list[dict[str, Any]] = []
    interrupted = False
    preparation: dict[str, dict[str, Any]] = {}
    snapshot = None
    try:
        try:
            snapshot = fetch_source(SOURCES["swe-bench-pro-v2"], cache)
        except Exception as exc:
            preparation = {
                item["name"]: {"error_type": type(exc).__name__} for item in plan["fixtures"]
            }
        environment = {
            "import_path": "sayacode_bench.network:IsolatedDockerEnvironment",
            "kwargs": {"messages_upstream": "http://127.0.0.1:9/v1/messages"},
        }
        for fixture in plan["fixtures"]:
            if snapshot is not None:
                try:
                    metadata = fixture_metadata(snapshot, fixture)
                    pinned = await pin_image(fixture)
                    preparation[fixture["name"]] = {**metadata, **pinned}
                except Exception as exc:
                    preparation[fixture["name"]] = {"error_type": type(exc).__name__}
            write_json(public / "image-preparation.json", preparation)
            for item in [row for row in plan["schedule"] if row["fixture"] == fixture["name"]]:
                observation: dict[str, Any] = {**item, "attempted": False}
                try:
                    ready = preparation[fixture["name"]]
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
                            {"name": item["agent"]},
                            environment,
                            configuration=item["agent"],
                            repeat=item["repeat"],
                            canonical_model="not_used",
                            endpoint="not_used",
                        )
                        # 执行事实先保存；资源或日志采集失败不能抹去已得到的原生评分。
                        observation.update({key: raw.get(key) for key in _OUTCOME_FIELDS})
                        observation["native_status"] = raw.get("status")
                        observation.update(
                            collect_trial(raw, public, item["job_name"], ready, raw_root)
                        )
                except Exception as exc:
                    observation.update(status="diagnostic_error", error_type=type(exc).__name__)
                records.append(observation)
                write_json(public / "records.json", records)
                write_json(public / "summary.json", summary(plan, records, interrupted=False))
                print(
                    f"[{len(records)}/8] {fixture['name']} {item['agent']} #{item['repeat']}: {observation.get('status')}",
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
        result = asyncio.run(diagnose(args.cache, args.output))
    except KeyboardInterrupt:
        return 130
    return 0 if result["all_jobs_attempted"] and result["all_expected_images_confirmed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
