"""只对已知校准题固定重判三轮，不调用模型，也不改写原评分。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.execution import replay_official_trial, run_official_trial
from sayacode_bench.sources import SOURCES, fetch_source


async def verify(cache: Path, source_job: Path, output: Path) -> dict[str, Any]:
    """每轮各一次固定补丁与官方参考解，异常不触发挑分或额外轮次。"""
    source_job = source_job.resolve(strict=True)
    experiment_manifest = source_job.parent.parent / "manifest.json"
    manifest = read_json(experiment_manifest)
    if manifest.get("phase") != "calibration" or manifest.get("benchmark") != "swe-bench-pro-v2":
        raise ValueError("仅允许既有 SWE 校准题，不接受开发或最终验收任务")
    source = read_json(source_job / "normalized.json")
    task_id = source["task_id"]
    if task_id not in {task["task_id"] for task in manifest["tasks"]}:
        raise ValueError("源任务不属于校准清单")
    patches = list(source_job.glob("instance_*/agent/model.patch"))
    if len(patches) != 1 or not patches[0].is_file():
        raise ValueError("需要唯一已捕获校准补丁")
    patch = patches[0]
    patch_hash = file_sha256(patch)
    snapshot = fetch_source(SOURCES["swe-bench-pro-v2"], cache)
    task_path = snapshot.tasks_path / task_id
    environment = read_json(source_job / "config.json").get("environment")
    output = output.resolve()
    if output.exists():
        raise FileExistsError("稳定性复核使用新目录，不覆盖或续选旧成绩")
    output.mkdir(parents=True)
    write_json(
        output / "plan.json",
        {
            "phase": "calibration_verifier_stability",
            "model_calls": 0,
            "rounds": 3,
            "source_job": str(source_job),
            "calibration_manifest_sha256": file_sha256(experiment_manifest),
            "task_id": task_id,
            "task_checksum": source.get("task_checksum"),
            "patch_sha256": patch_hash,
            "source_config_sha256": file_sha256(source_job / "config.json"),
            "source_revision": snapshot.spec.revision,
            "interpretation": "固定三轮，不因失败提前选分；原始官方评分保持不变",
        },
        exclusive=True,
    )
    records: list[dict[str, Any]] = []
    for index in range(1, 4):
        for kind in ("patch", "oracle"):
            print(f"[{len(records) + 1}/6] {kind} calibration round {index}", flush=True)
            try:
                if not patch.is_file() or file_sha256(patch) != patch_hash:
                    raise ValueError("校准补丁在固定重判期间变化")
                if kind == "patch":
                    record = await replay_official_trial(
                        task_path,
                        output / "jobs",
                        f"patch-{index}",
                        source_job,
                        snapshot.path / "v2" / "tooling",
                        environment,
                    )
                    reward = record.get("replay_reward")
                else:
                    record = await run_official_trial(
                        task_path,
                        output / "jobs",
                        f"oracle-{index}",
                        {"name": "oracle"},
                        environment,
                        configuration="oracle_diagnostic",
                        repeat=index,
                        canonical_model=source["canonical_model"],
                        endpoint=source["endpoint"],
                    )
                    reward = record.get("original_reward")
                record = {
                    **record,
                    "calibration_kind": kind,
                    "calibration_round": index,
                    "diagnostic_reward": reward,
                }
            except Exception as exc:
                record = {
                    "calibration_kind": kind,
                    "calibration_round": index,
                    "status": "diagnostic_error",
                    "success": None,
                    "verified": False,
                    "diagnostic_reward": None,
                    "error_type": type(exc).__name__,
                }
            records.append(record)
            write_json(output / f"{kind}-{index}.json", record, exclusive=True)
            write_json(output / "records.json", records)
    groups = {}
    for kind in ("patch", "oracle"):
        rows = [row for row in records if row["calibration_kind"] == kind]
        known = [
            row["diagnostic_reward"]
            for row in rows
            if row.get("verified") is True and row.get("diagnostic_reward") in (0, 1)
        ]
        groups[kind] = {
            "attempts": len(rows),
            "verified_grades": len(known),
            "rewards": [row.get("diagnostic_reward") for row in rows],
            "observed_score_variation": len(set(known)) > 1 if known else None,
            "all_verified_pass": len(known) == 3 and all(value == 1 for value in known),
            "unconfirmed": len(rows) - len(known),
        }
    aggregate = {
        "schema_version": 1,
        "task_id": task_id,
        "patch_sha256": patch_hash,
        "planned": 6,
        "recorded": len(records),
        "model_calls": 0,
        "groups": groups,
        "original_scores_unchanged": True,
        "caution": "三轮未观察到翻转不证明绝对稳定；诊断结果不替换原始官方首判。",
    }
    write_json(output / "aggregate.json", aggregate, exclusive=True)
    return aggregate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--source-job", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = asyncio.run(verify(args.cache, args.source_job, args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(group["unconfirmed"] == 0 for group in result["groups"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
