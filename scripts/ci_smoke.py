"""小样本冒烟门禁：从冻结题集抽 2 题，校验配置/镜像/题集；默认 dry-run，不跑付费模型。

dry-run 只做**结构门禁**：题集可解析、抽题确定、job 名唯一、输出目录可写。本地若提供了
tasks_root / profile / wheel / requirements / variant，再额外校验运行时就绪；这些项缺失时
记为 ``skipped``，只有显式 ``--require-runtime`` 才判失败（CI 无付费凭据时不应误报）。

``--execute`` 才真正调用一次 sayacode（每道抽中的题 1 次），并校验：patch 非空、有 reward
产出、无 exception。默认永远不跑模型。

用法::

    uv run --no-sync python scripts/ci_smoke.py --dry-run
    uv run --no-sync python scripts/ci_smoke.py --execute --out C:\\sb\\hard\\smoke
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from auto_resume import DockerStatus, probe_docker  # noqa: E402
from locked_agents import CANONICAL_MODEL, FormalPaths, build_agent, env_cfg  # noqa: E402

from sayacode_bench.execution import run_official_trial  # noqa: E402

DEFAULT_SAMPLE = ROOT / "studies" / "sample-40-final.json"
DEFAULT_SEED = 20261022
PASS, FAIL, SKIPPED = "pass", "fail", "skipped"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def load_sample_tasks(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("tasks")
    if not isinstance(items, list) or len(items) < 2:
        raise ValueError("题集必须包含至少 2 道题")
    tasks: list[dict[str, str]] = []
    for item in items:
        task_id = item.get("task_id")
        repository = item.get("repo", item.get("repository"))
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("题集 task_id 必须是非空字符串")
        tasks.append({"task_id": task_id, "repo": str(repository or "")})
    if len({task["task_id"] for task in tasks}) != len(tasks):
        raise ValueError("题集存在重复 task_id")
    return tasks


def select_smoke_tasks(
    tasks: list[dict[str, str]], *, count: int = 2, seed: int = DEFAULT_SEED
) -> list[dict[str, str]]:
    """固定 seed 抽样；同一输入始终得到同一组冒烟题。"""
    if count < 1:
        raise ValueError("count 必须至少为 1")
    if count > len(tasks):
        raise ValueError("count 不能大于题集大小")
    return random.Random(seed).sample(tasks, count)


def smoke_job_name(task_id: str, repeat: int = 1) -> str:
    short = task_id[len("instance_") :] if task_id.startswith("instance_") else task_id
    return f"smoke-sayacode-{short[:30]}-r{repeat}"


def structure_checks(
    sample: Path, tasks: list[dict[str, str]], out: Path, selected: list[dict[str, str]]
) -> list[Check]:
    checks: list[Check] = []
    checks.append(Check("sample_parsed", PASS if tasks else FAIL, f"{sample} -> {len(tasks)} 题"))
    unique = len({task["task_id"] for task in selected}) == len(selected)
    checks.append(
        Check(
            "smoke_tasks",
            PASS if unique else FAIL,
            "抽中：" + "、".join(f"{task['repo']}/{task['task_id'][:40]}" for task in selected),
        )
    )
    job_names = [smoke_job_name(task["task_id"]) for task in selected]
    checks.append(
        Check(
            "job_names_unique",
            PASS if len(set(job_names)) == len(job_names) else FAIL,
            "、".join(job_names),
        )
    )
    try:
        out.mkdir(parents=True, exist_ok=True)
        probe = out / ".smoke-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(Check("output_writable", PASS, str(out)))
    except OSError as exc:
        checks.append(Check("output_writable", FAIL, f"{type(exc).__name__}: {exc}"))
    return checks


def runtime_checks(
    paths: FormalPaths,
    tasks: list[dict[str, str]],
    selected: list[dict[str, str]],
    docker_status: DockerStatus | None = None,
) -> list[Check]:
    """本地有真实输入时才检查运行时就绪；缺失记 skipped，不误判。"""
    checks: list[Check] = []
    missing_task_dirs = [
        task["task_id"] for task in selected if not (paths.tasks_root / task["task_id"]).is_dir()
    ]
    if not paths.tasks_root.is_dir():
        checks.append(Check("tasks_root", SKIPPED, f"未提供 {paths.tasks_root}"))
    elif missing_task_dirs:
        checks.append(Check("tasks_root", FAIL, "抽查题目录缺失：" + "、".join(missing_task_dirs)))
    else:
        checks.append(Check("tasks_root", PASS, str(paths.tasks_root)))

    required = {
        "profile": paths.profile,
        "wheel": paths.wheel,
        "requirements": paths.requirements,
        "variant": paths.variant,
    }
    absent = [name for name, path in required.items() if not path.is_file()]
    if absent:
        checks.append(Check("sayacode_inputs", SKIPPED, "未提供：" + "、".join(absent)))
    else:
        try:
            import tempfile

            with tempfile.TemporaryDirectory() as scratch:
                config = build_agent("sayacode", paths, profile_dir=Path(scratch))
            detail = f"import_path={config.import_path} model_name={config.model_name}"
            checks.append(Check("sayacode_inputs", PASS, detail))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("sayacode_inputs", FAIL, f"{type(exc).__name__}: {str(exc)[:160]}"))

    docker = docker_status or probe_docker()
    if docker.online:
        checks.append(Check("docker", PASS, f"ServerVersion={docker.server_version}"))
    else:
        checks.append(Check("docker", SKIPPED, f"不可用：{docker.error}"))
    return checks


def validate_trial(record: dict[str, Any], job_dir: Path) -> list[Check]:
    """execute 模式下的三条硬校验：无 exception、有 reward、patch 非空。"""
    checks: list[Check] = []
    status = str(record.get("status") or "")
    checks.append(
        Check(
            "no_exception",
            PASS if status and not status.startswith("exception") else FAIL,
            f"status={status}",
        )
    )
    reward = record.get("original_reward")
    checks.append(Check("reward_present", PASS if reward is not None else FAIL, f"reward={reward}"))
    patches = list(job_dir.glob("instance_*/agent/model.patch"))
    size = patches[0].stat().st_size if patches else 0
    checks.append(Check("patch_nonempty", PASS if size > 0 else FAIL, f"model.patch {size} 字节"))
    return checks


def run_execute(
    paths: FormalPaths, selected: list[dict[str, str]], out: Path
) -> tuple[list[Check], list[dict[str, Any]]]:
    agent = build_agent("sayacode", paths, profile_dir=out)
    environment = env_cfg(paths)
    checks: list[Check] = []
    rows: list[dict[str, Any]] = []
    for task in selected:
        task_id = task["task_id"]
        name = smoke_job_name(task_id)
        try:
            record = run_official_trial_sync(
                paths.tasks_root / task_id, out / "jobs", name, agent, environment
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                Check(f"run:{task_id[:24]}", FAIL, f"{type(exc).__name__}: {str(exc)[:160]}")
            )
            rows.append(
                {"task_id": task_id, "job": name, "status": f"exception:{type(exc).__name__}"}
            )
            continue
        rows.append(
            {
                "task_id": task_id,
                "job": name,
                **{key: record.get(key) for key in ("status", "original_reward")},
            }
        )
        for check in validate_trial(record, out / "jobs" / name):
            checks.append(Check(f"{check.name}:{task_id[:24]}", check.status, check.detail))
    return checks, rows


def run_official_trial_sync(
    task_dir: Path, jobs_dir: Path, job_name: str, agent: Any, environment: Any
) -> dict[str, Any]:
    import asyncio

    async def _call() -> dict[str, Any]:
        return await run_official_trial(
            task_dir,
            jobs_dir,
            job_name,
            agent,
            environment,
            configuration="smoke",
            repeat=1,
            canonical_model=CANONICAL_MODEL,
            endpoint="magpie",
        )

    result: dict[str, Any] = asyncio.run(_call())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(os.environ.get("SAYACODE_BENCH_SMOKE_OUT", "results/smoke")),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只校验配置/镜像/题集（默认）")
    mode.add_argument(
        "--execute", action="store_true", help="真正跑 2 题 sayacode 一次（会产生模型费用）"
    )
    parser.add_argument("--require-runtime", action="store_true", help="把缺失的运行时项判为失败")
    parser.add_argument("--no-docker", action="store_true", help="跳过 Docker 检查")
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        tasks = load_sample_tasks(args.sample)
        selected = select_smoke_tasks(tasks, count=args.count, seed=args.seed)
    except (OSError, ValueError) as exc:
        print(f"[fail] 题集不可用：{exc}", file=sys.stderr)
        return 2

    paths = FormalPaths.from_env()
    docker_status = DockerStatus(online=False, error="已跳过") if args.no_docker else None
    checks = structure_checks(args.sample, tasks, args.out, selected)
    rows: list[dict[str, Any]] = []
    execute = bool(args.execute)

    if execute:
        checks.extend(runtime_checks(paths, tasks, selected, docker_status))
        # 真正跑模型前，运行时项必须全部就绪；skipped 等同于未就绪。
        blocking = [check for check in checks if check.status != PASS]
        if blocking:
            print("[fail] 运行时未就绪，拒绝执行模型调用", file=sys.stderr)
            for check in blocking:
                print(f"  - {check.name}: {check.detail}", file=sys.stderr)
            checks.append(Check("runtime_ready", FAIL, "运行时未就绪，未执行模型调用"))
        else:
            trial_checks, rows = run_execute(paths, selected, args.out)
            checks.extend(trial_checks)
    else:
        checks.extend(runtime_checks(paths, tasks, selected, docker_status))

    failures = [check for check in checks if check.status == FAIL]
    skipped = [check for check in checks if check.status == SKIPPED]
    if args.require_runtime and skipped:
        failures.extend(
            Check(check.name, FAIL, f"要求运行时就绪但被跳过：{check.detail}") for check in skipped
        )
    status = "ok" if not failures else "fail"

    print(f"[smoke] 模式={'execute' if execute else 'dry-run'} 题数={len(selected)}")
    for check in checks:
        mark = {PASS: "PASS", FAIL: "FAIL", SKIPPED: "SKIP"}[check.status]
        print(f"  [{mark}] {check.name}: {check.detail}")
    if rows:
        print("[smoke] 逐题结果：")
        for row in rows:
            print(
                f"  - {row['task_id'][:56]} status={row.get('status')} reward={row.get('original_reward')}"
            )
    print(f"[smoke] 结论：{status}（fail={len(failures)}，skipped={len(skipped)}）")

    payload = {
        "schema_version": 1,
        "mode": "execute" if execute else "dry-run",
        "status": status,
        "sample": str(args.sample),
        "seed": args.seed,
        "selected": [task["task_id"] for task in selected],
        "checks": [check.as_dict() for check in checks],
        "rows": rows,
        "model_requests": len(selected) if execute else 0,
        "note": "dry-run 不调用模型；execute 才产生模型请求，费用由调用方承担",
    }
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[json] 已写 {args.json_out}")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
