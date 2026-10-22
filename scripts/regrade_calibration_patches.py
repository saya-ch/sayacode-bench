"""固定六次真实补丁重判和四次 Ansible 控制；不调用模型或改原始评分。"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import json
import platform
import re
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Any

from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.execution import run_official_trial
from sayacode_bench.sources import SOURCES, SourceSnapshot, fetch_source
from scripts.diagnose_fixtures import REVISION, collect_trial, fixture_metadata, pin_image

REPOSITORY = "ghcr.io/scaleapi/swe-bench_pro-v2"
TOOLING_SHA256 = "5c8b344de37164e9723f1724c2573013957fb644c3913a64c12c1718c737d876"
PLUGIN = "sayacode_bench.artifact_replay:ArtifactReplayAgent"
PRIOR_CONTROL_DIRECTORY = "reports/cross-host-fixture-diagnostic-20261022"
PRIOR_CONTROL_FILES = {
    "summary.json": "d78527ef2c5ea6bfa76e099875e3cd5846cf7bab6ee319731eacf9cfb8e1ce69",
    "records.json": "38bcdc11bc232471277b5f9aa6fe0277de969a9ab1084927c467758c1932d8ae",
    "image-preparation.json": "986ddf4c76e8c707aafaf9c841626654ca11b39e6b65389e52e49fe185dc791c",
    "provenance.json": "f3a7cdb18639208220ce5e3e91761e3ac6fcd63718aa36cde64afb6b6feffcb1",
}
FIXTURES = (
    {
        "name": "qutebrowser",
        "task_id": "instance_qutebrowser__qutebrowser-3d01c201b8aa54dd71d4f801b1dd12feb4c0a08a-v5fc38aaf22415ab0b70567368332beee7955b367",
        "digest": "sha256:cc0e0f503659eac82afb4f304e853c5a94ddd2aba834e62d3fd757fa6fba13e3",
        "patch_sha256": "d905b09f498fa5ff4edbecc185d88f16200db2967acae28d5c2e5b185efc6592",
    },
    {
        "name": "ansible",
        "task_id": "instance_ansible__ansible-de5858f48dc9e1ce9117034e0d7e76806f420ca8-v1055803c3a812189a1133297f7f5468579283f86",
        "digest": "sha256:31ebe11c8cb1c5e3f74b15e0345fce7f9adc7eb406209131828f8b49bf4b7f61",
        "patch_sha256": "6f63f697720842b83c3013403f5a98df424e236173344c76b98c7d647a2fa6e6",
    },
)
_SOURCE_FIELDS = (
    "schema_version",
    "phase",
    "source_kind",
    "benchmark",
    "revision",
    "task_id",
    "canonical_model",
    "endpoint",
    "patch_sha256",
    "patch_bytes",
    "base_commit",
    "original_source_status",
    "original_reward",
    "local_pristine_reward",
    "original_raw_trial_result_sha256",
    "original_worker_result_sha256",
    "original_records_sha256",
    "immutable_image_digest",
    "license_sha256",
)


def fixed_plan() -> dict[str, Any]:
    """两道已公开校准题固定十次；补齐 Ansible 在同一 VM 的参考与空解控制。"""
    return {
        "schema_version": 1,
        "phase": "cross_host_calibration_patch_diagnostic",
        "benchmark": "swe-bench-pro-v2",
        "revision": REVISION,
        "harbor_version": "0.24.0",
        "model_agent_used": False,
        "model_requests": 0,
        "replay_agent": PLUGIN,
        "upstream_tooling_sha256": TOOLING_SHA256,
        "replay_adaptation": "portable artifact locator subclass; only _find_patch is overridden; upstream setup/run/apply/verifier unchanged",
        "prior_qutebrowser_controls": {
            "workflow_url": "https://github.com/saya-ch/sayacode-bench/actions/runs/39736698121",
            "report_directory": PRIOR_CONTROL_DIRECTORY,
            "files_sha256": PRIOR_CONTROL_FILES,
            "oracle_rewards": [1, 1, 1],
            "nop_rewards": [0],
            "same_vm_as_current_patch_trials": False,
        },
        "fixtures": [
            {
                **fixture,
                "immutable_image": f"{REPOSITORY}@{fixture['digest']}",
                "original_image_reference": f"{REPOSITORY}:{fixture['task_id']}",
            }
            for fixture in FIXTURES
        ],
        "schedule": [
            {
                "fixture": fixture["name"],
                "task_id": fixture["task_id"],
                "agent": agent,
                "repeat": repeat,
                "job_name": f"calibration-{index}-{agent}-{repeat}",
            }
            for index, fixture in enumerate(FIXTURES, 1)
            for agent, repeat in (
                (("oracle", 1), ("oracle", 2), ("oracle", 3), ("nop", 1))
                if fixture["name"] == "ansible"
                else ()
            )
            + tuple(("portable-patch-replay", repeat) for repeat in range(1, 4))
        ],
        "formal_comparison_eligible": False,
        "affects_local_scores": False,
        "interpretation": "固定六次独立 pristine 重判及 Ansible 三参考一空解；qutebrowser 引用既有云端控制，不按成绩挑选；原本地评分保留，不构成正式模型比较。",
    }


def prior_qutebrowser_controls() -> dict[str, Any]:
    """绑定已发布的真实云端控制，不把另一次 VM 的控制说成本次重跑。"""
    root = Path(__file__).parents[1] / PRIOR_CONTROL_DIRECTORY
    for name, expected in PRIOR_CONTROL_FILES.items():
        if file_sha256(root / name) != expected:
            raise ValueError("既有 qutebrowser 云端控制工件缺失或身份变化")
    records = json.loads((root / "records.json").read_text(encoding="utf-8"))
    runtimes = {}
    for row in records:
        if row["fixture"] != "calibration-qutebrowser":
            continue
        runtime = root / "trials" / row["job_name"] / "runtime.json"
        if file_sha256(runtime) != row["runtime_sha256"]:
            raise ValueError("既有 qutebrowser 控制的原生资源工件身份变化")
        runtimes[row["job_name"]] = row["runtime_sha256"]
    reference: dict[str, Any] = fixed_plan()["prior_qutebrowser_controls"]
    return {**reference, "runtime_files_sha256": runtimes}


@contextmanager
def replay_tooling(snapshot: SourceSnapshot) -> Iterator[dict[str, str]]:
    """先验证固定源码，再正常导入薄插件；不在公开源缓存留下 pyc。"""
    source = snapshot.path / "v2" / "tooling" / "patch_replay.py"
    if snapshot.spec.revision != REVISION or file_sha256(source) != TOOLING_SHA256:
        raise ValueError("官方重判工具源码与冻结 Git blob 不一致")
    names = ("patch_replay", "sayacode_bench.artifact_replay")
    previous = {name: sys.modules.get(name) for name in names}
    bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("patch_replay", source)
        if spec is None or spec.loader is None:
            raise ImportError("不能导入固定上游重判模块")
        module = importlib.util.module_from_spec(spec)
        sys.modules["patch_replay"] = module
        spec.loader.exec_module(module)
        sys.modules.pop(names[1], None)
        plugin = importlib.import_module(names[1])
        plugin_path = plugin.__file__
        if plugin_path is None:
            raise ImportError("薄插件必须来自可校验的源码文件")
        sys.dont_write_bytecode = bytecode
        yield {
            "upstream_tooling_sha256": file_sha256(source),
            "artifact_locator_sha256": file_sha256(Path(plugin_path)),
        }
    finally:
        sys.dont_write_bytecode = bytecode
        for name, prior in previous.items():
            if prior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


def prepare_source(evidence: Path, fixture: dict[str, Any], raw: Path) -> dict[str, Any]:
    """复制真实补丁及来源说明，不伪造原 job 的 result.json 或 normalized.json。"""
    root = evidence.resolve(strict=True)
    directory = root / fixture["name"]
    source, patch, license_path = (
        directory / "source.json",
        directory / "model.patch",
        directory / "LICENSE",
    )
    for path in (directory, source, patch, license_path):
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError("公开补丁输入不允许链接或目录越界")
    metadata = read_json(source)
    if (
        metadata.get("schema_version") != 1
        or metadata.get("source_kind") != "actual_captured_model_patch"
        or metadata.get("phase") != "calibration_patch_evidence"
        or metadata.get("benchmark") != "swe-bench-pro-v2"
        or metadata.get("task_id") != fixture["task_id"]
        or metadata.get("revision") != REVISION
        or metadata.get("immutable_image_digest") != fixture["digest"]
        or metadata.get("patch_sha256") != fixture["patch_sha256"]
        or file_sha256(patch) != fixture["patch_sha256"]
        or type(metadata.get("patch_bytes")) is not int
        or metadata["patch_bytes"] != patch.stat().st_size
        or metadata.get("license_sha256") != file_sha256(license_path)
    ):
        raise ValueError("真实校准工件的固定身份或字节不一致")
    for key in (
        "original_raw_trial_result_sha256",
        "original_worker_result_sha256",
        "original_records_sha256",
    ):
        if not isinstance(metadata.get(key), str) or not re.fullmatch(
            r"[0-9a-f]{64}", metadata[key]
        ):
            raise ValueError("原始评分证据缺少有效 SHA256")
    for key in ("original_reward", "local_pristine_reward"):
        if type(metadata.get(key)) not in (int, float) or metadata[key] not in (0, 1):
            raise ValueError("原始评分必须明确记录为 0 或 1")
    safe = {key: metadata[key] for key in _SOURCE_FIELDS if key in metadata}
    # 任何未知嵌套内容都不复制进公开说明；固定输入只接受标量事实。
    if any(not isinstance(value, (str, int, float)) for value in safe.values()):
        raise ValueError("来源白名单仅接受标量事实")
    destination = raw / fixture["name"] / "instance_source"
    destination.mkdir(parents=True)
    write_json(destination / "source.json", safe)
    (destination / "agent").mkdir()
    shutil.copyfile(patch, destination / "agent" / "model.patch")
    if file_sha256(destination / "agent" / "model.patch") != fixture["patch_sha256"]:
        raise ValueError("复制后的真实补丁身份变化")
    return {**safe, "source_json_sha256": file_sha256(source)}


def replay_observations(raw: dict[str, Any], raw_root: Path, task_id: str) -> dict[str, Any]:
    """只公开官方 replay.json 的身份和返回码，不导出补丁、应用正文或文件路径。"""
    job = Path(raw.get("job_dir", "")).resolve()
    if not job.is_relative_to(raw_root.resolve()):
        raise ValueError("原生 replay 路径越过本次输出目录")
    artifacts = list(job.glob("instance_*/agent/replay.json"))
    if len(artifacts) != 1:
        return {"available": False, "reason": "not_unique_or_missing"}
    path = artifacts[0]
    value = read_json(path)
    if value.get("task") != task_id:
        raise ValueError("原生 replay 工件的任务身份不一致")
    code = value.get("apply_rc")
    return {
        "available": True,
        "native_replay_sha256": file_sha256(path),
        "patch_applied_attempted": value.get("patch") is not None,
        "apply_rc": code if type(code) is int else None,
        "empty_or_missing_patch": value.get("patch") is None,
    }


def native_result_observations(raw: dict[str, Any], raw_root: Path, task_id: str) -> dict[str, Any]:
    """把本次原生评分文件与公开结果绑定，只摘录身份、奖励和异常类型。"""
    job = Path(raw.get("job_dir", "")).resolve()
    if not job.is_relative_to(raw_root.resolve()):
        raise ValueError("原生结果路径越过本次输出目录")
    results = list(job.glob("instance_*/result.json"))
    if len(results) != 1:
        return {"available": False, "reason": "not_unique_or_missing"}
    path = results[0]
    value = read_json(path)
    name = value.get("task_name")
    if not isinstance(name, str) or name.split("/")[-1] != task_id:
        raise ValueError("本次原生评分文件与指定任务不一致")
    verifier = value.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    reward = rewards.get("reward") if isinstance(rewards, dict) else None
    reward = reward if type(reward) in (int, float) and reward in (0, 1) else None
    if reward != raw.get("original_reward"):
        raise ValueError("原生评分与归一化 reward 不一致")
    exception = value.get("exception_info")
    kind = exception.get("exception_type") if isinstance(exception, dict) else None
    return {
        "available": True,
        "native_trial_result_sha256": file_sha256(path),
        "task_id_matches": True,
        "reward": reward,
        "exception_type": kind
        if isinstance(kind, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,100}", kind)
        else None,
    }


def summary(
    plan: dict[str, Any], records: list[dict[str, Any]], *, interrupted: bool
) -> dict[str, Any]:
    planned = len(plan["schedule"])
    patches = [row for row in records if row["agent"] == "portable-patch-replay"]
    controls = [row for row in records if row["agent"] in {"oracle", "nop"}]
    return {
        "phase": plan["phase"],
        "planned_jobs": planned,
        "recorded_jobs": len(records),
        "all_jobs_attempted": len(records) == planned
        and all(row.get("attempted") is True for row in records),
        "all_expected_images_confirmed": len(records) == planned
        and all(row.get("image_matches_expected") is True for row in records),
        "all_native_trials_scored": len(records) == planned
        and all(
            row.get("verified") is True
            and row.get("native_status") == "completed"
            and type(row.get("original_reward")) in (int, float)
            and row["original_reward"] in (0, 1)
            and isinstance(row.get("native_trial"), dict)
            and row["native_trial"].get("available") is True
            for row in records
        ),
        "all_replay_evidence_available": len(patches) == 6
        and all(
            isinstance(row.get("replay"), dict)
            and row["replay"].get("available") is True
            and row["replay"].get("patch_applied_attempted") is True
            and type(row["replay"].get("apply_rc")) is int
            for row in patches
        ),
        "all_patches_applied": len(patches) == 6
        and all(
            isinstance(row.get("replay"), dict) and row["replay"].get("apply_rc") == 0
            for row in patches
        ),
        "ansible_controls_passed": len(controls) == 4
        and all(
            row.get("verified") is True
            and row.get("image_matches_expected") is True
            and isinstance(row.get("native_trial"), dict)
            and row["native_trial"].get("available") is True
            and row.get("original_reward") == (1 if row["agent"] == "oracle" else 0)
            for row in controls
        ),
        "prior_qutebrowser_controls": plan["prior_qutebrowser_controls"],
        "interrupted": interrupted,
        "fixtures": {
            fixture["name"]: {
                "task_id": fixture["task_id"],
                "patch_sha256": fixture["patch_sha256"],
                "expected_digest": fixture["digest"],
                "cloud_pristine_rewards": [
                    row.get("original_reward")
                    for row in patches
                    if row["fixture"] == fixture["name"]
                ],
                "oracle_rewards": [
                    row.get("original_reward")
                    for row in controls
                    if row["fixture"] == fixture["name"] and row["agent"] == "oracle"
                ],
                "nop_rewards": [
                    row.get("original_reward")
                    for row in controls
                    if row["fixture"] == fixture["name"] and row["agent"] == "nop"
                ],
                "statuses": [
                    row.get("status") for row in records if row["fixture"] == fixture["name"]
                ],
            }
            for fixture in plan["fixtures"]
        },
        "model_requests": 0,
        "formal_comparison_eligible": False,
        "affects_local_scores": False,
        "interpretation": plan["interpretation"],
    }


async def regrade(cache: Path, output: Path, evidence: Path) -> dict[str, Any]:
    """固定十次全跑；准备失败和执行错误仍保留原计划，不按分数重试。"""
    output, cache, evidence = output.resolve(), cache.resolve(), evidence.resolve()
    for other in (cache, evidence):
        if output.is_relative_to(other) or other.is_relative_to(output):
            raise ValueError("输出必须与源码缓存和原始补丁隔离")
    if output.exists():
        raise FileExistsError("重判诊断必须使用全新目录")
    if version("harbor") != "0.24.0" or SOURCES["swe-bench-pro-v2"].revision != REVISION:
        raise ValueError("仅支持冻结 Harbor 与公开源版本")
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
    preparation: dict[str, Any] = {}
    interrupted = False
    try:
        write_json(public / "prior-qutebrowser-controls.json", prior_qutebrowser_controls())
        snapshot = fetch_source(SOURCES["swe-bench-pro-v2"], cache)
        with replay_tooling(snapshot) as identity:
            write_json(public / "replay-implementation.json", identity)
            environment = {
                "import_path": "sayacode_bench.network:IsolatedDockerEnvironment",
                "kwargs": {"messages_upstream": "http://127.0.0.1:9/v1/messages"},
            }
            for fixture in plan["fixtures"]:
                try:
                    preparation[fixture["name"]] = {
                        **fixture_metadata(snapshot, fixture),
                        **await pin_image(fixture),
                    }
                except Exception as exc:
                    preparation[fixture["name"]] = {"error_type": type(exc).__name__}
                try:
                    source = prepare_source(evidence, fixture, output / "raw" / "portable-sources")
                    write_json(public / "sources" / f"{fixture['name']}.json", source)
                except Exception as exc:
                    preparation[fixture["name"]]["patch_source_error_type"] = type(exc).__name__
                write_json(public / "image-preparation.json", preparation)
                for item in [row for row in plan["schedule"] if row["fixture"] == fixture["name"]]:
                    observation: dict[str, Any] = {
                        **item,
                        "attempted": False,
                    }
                    if item["agent"] == "portable-patch-replay":
                        observation["patch_sha256"] = fixture["patch_sha256"]
                    try:
                        ready = preparation[fixture["name"]]
                        preparation_error = ready.get("error_type") or (
                            ready.get("patch_source_error_type")
                            if item["agent"] == "portable-patch-replay"
                            else None
                        )
                        if preparation_error:
                            observation.update(
                                status="preparation_failed", error_type=preparation_error
                            )
                        else:
                            observation["attempted"] = True
                            agent = (
                                {
                                    "import_path": PLUGIN,
                                    "model_name": "replay",
                                    "kwargs": {
                                        "source_job": str(
                                            output / "raw" / "portable-sources" / fixture["name"]
                                        )
                                    },
                                }
                                if item["agent"] == "portable-patch-replay"
                                else {"name": item["agent"]}
                            )
                            raw = await run_official_trial(
                                snapshot.tasks_path / item["task_id"],
                                raw_root,
                                item["job_name"],
                                agent,
                                environment,
                                configuration=f"calibration_{item['agent']}_diagnostic",
                                repeat=item["repeat"],
                                canonical_model="not_used",
                                endpoint="not_used",
                            )
                            # 先保留真实判分；后续证据收集错误不能抹去运行事实。
                            observation.update(
                                {
                                    key: raw.get(key)
                                    for key in (
                                        "status",
                                        "original_reward",
                                        "verified",
                                        "harbor_exception_type",
                                        "duration_seconds",
                                        "task_checksum",
                                        "request_sha256",
                                    )
                                }
                            )
                            observation["native_status"] = raw.get("status")
                            observation.update(
                                collect_trial(raw, public, item["job_name"], ready, raw_root)
                            )
                            native = native_result_observations(raw, raw_root, item["task_id"])
                            write_json(
                                public
                                / "trials"
                                / item["job_name"]
                                / "native-result-observations.json",
                                native,
                            )
                            observation["native_trial"] = native
                            if item["agent"] == "portable-patch-replay":
                                replay = replay_observations(raw, raw_root, item["task_id"])
                                write_json(
                                    public
                                    / "trials"
                                    / item["job_name"]
                                    / "replay-observations.json",
                                    replay,
                                )
                                observation["replay"] = replay
                    except Exception as exc:
                        observation.update(status="diagnostic_error", error_type=type(exc).__name__)
                    records.append(observation)
                    write_json(public / "records.json", records)
                    write_json(public / "summary.json", summary(plan, records, interrupted=False))
                    print(
                        f"[{len(records)}/10] {fixture['name']} {item['agent']} #{item['repeat']}: {observation.get('status')}",
                        flush=True,
                    )
    except Exception as exc:
        # 公共源或固定 tooling 无法准备时，不隐去十个未执行项。
        if not records:
            records.extend(
                {
                    **item,
                    "attempted": False,
                    "status": "preparation_failed",
                    "error_type": type(exc).__name__,
                }
                for item in plan["schedule"]
            )
            write_json(public / "records.json", records)
        else:
            interrupted = True
            raise
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
    parser.add_argument(
        "--evidence", type=Path, default=Path(__file__).parents[1] / "evidence" / "calibration"
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(regrade(args.cache, args.output, args.evidence))
    except KeyboardInterrupt:
        return 130
    return (
        0
        if all(
            result[field]
            for field in (
                "all_jobs_attempted",
                "all_expected_images_confirmed",
                "all_native_trials_scored",
                "all_replay_evidence_available",
                "ansible_controls_passed",
            )
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
