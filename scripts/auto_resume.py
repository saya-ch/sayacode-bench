"""断点自愈：检查 Docker、分类未收尾 job、把残留移到 ``abandoned-auto-<ts>/`` 并给出续跑命令。

判定依据是每个 job 根目录的 ``normalized.json``：

- ``record_complete=True`` → **已完成**，不动；
- ``record_complete=False`` → **未收尾**，移到 abandoned，允许续跑重新创建同名 job；
- 缺少 ``normalized.json``（或无法解析 / 缺字段）→ **无结果**，同样视为残留并移走。

默认 ``--dry-run`` 只报告；只有 ``--apply`` 才实际移动。Docker 在线状态与残留容器／网络只做报告，
``--prune`` 才清理疑似评测残留（``saya-isolated-*`` 网络与 ``harbor`` / ``swe-bench`` 容器）。

用法::

    uv run --no-sync python scripts/auto_resume.py --root C:\\sb\\hard\\v2-325
    uv run --no-sync python scripts/auto_resume.py --root C:\\sb\\hard\\v2-325 --apply
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path(r"C:\sb\hard\v2-325")
AGENTS = ("sayacode", "mini-swe", "codex")
KINDS = ("jobs", "verify/jobs")
EVAL_NETWORK_PREFIX = "saya-isolated-"
EVAL_CONTAINER_MARKERS = ("harbor", "swe-bench", "instance_", "testbed")

COMPLETED = "completed"
INCOMPLETE = "incomplete"
NO_RESULT = "no_result"


@dataclass(frozen=True)
class JobState:
    agent: str
    kind: str
    job_dir: Path
    classification: str
    status: str | None = None
    failure_category: str | None = None
    normalization_issues: tuple[str, ...] = ()
    record_complete: bool | None = None
    task_id: str | None = None
    repeat: int | None = None

    @property
    def residual(self) -> bool:
        return self.classification != COMPLETED

    def as_dict(self, root: Path) -> dict[str, Any]:
        try:
            relative = str(self.job_dir.relative_to(root))
        except ValueError:
            relative = str(self.job_dir)
        return {
            "agent": self.agent,
            "kind": self.kind,
            "job": self.job_dir.name,
            "path": relative,
            "classification": self.classification,
            "status": self.status,
            "failure_category": self.failure_category,
            "normalization_issues": list(self.normalization_issues),
            "record_complete": self.record_complete,
            "task_id": self.task_id,
            "repeat": self.repeat,
        }


@dataclass
class DockerStatus:
    online: bool
    server_version: str | None = None
    eval_containers: tuple[dict[str, str], ...] = ()
    eval_networks: tuple[str, ...] = ()
    error: str | None = None


@dataclass
class MovePlan:
    source: Path
    target: Path


def classify_job(job_dir: Path) -> JobState:
    """只按 normalized.json 判定；缺失或坏文件一律归为 no_result。"""
    normalized = job_dir / "normalized.json"
    if not normalized.is_file():
        return JobState(agent="", kind="", job_dir=job_dir, classification=NO_RESULT)
    try:
        payload = json.loads(normalized.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return JobState(agent="", kind="", job_dir=job_dir, classification=NO_RESULT)
    if not isinstance(payload, dict):
        return JobState(agent="", kind="", job_dir=job_dir, classification=NO_RESULT)
    record_complete = payload.get("record_complete")
    if record_complete is True:
        classification = COMPLETED
    elif record_complete is False:
        classification = INCOMPLETE
    else:
        classification = NO_RESULT
    issues = payload.get("normalization_issues")
    return JobState(
        agent="",
        kind="",
        job_dir=job_dir,
        classification=classification,
        status=payload.get("status"),
        failure_category=payload.get("failure_category"),
        normalization_issues=tuple(str(value) for value in issues)
        if isinstance(issues, list)
        else (),
        record_complete=record_complete if isinstance(record_complete, bool) else None,
        task_id=payload.get("task_id") if isinstance(payload.get("task_id"), str) else None,
        repeat=payload.get("repeat") if isinstance(payload.get("repeat"), int) else None,
    )


def scan_root(root: Path, *, agents: Sequence[str] | None = None) -> list[JobState]:
    """扫描 ``<root>/<agent>/{jobs,verify/jobs}/*``；保留 agent/kind 归属。"""
    states: list[JobState] = []
    if not root.is_dir():
        return states
    wanted = set(agents) if agents else None
    for agent_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if wanted is not None and agent_dir.name not in wanted:
            continue
        for kind in KINDS:
            base = agent_dir / Path(kind)
            if not base.is_dir():
                continue
            for job_dir in sorted(path for path in base.iterdir() if path.is_dir()):
                state = classify_job(job_dir)
                states.append(
                    JobState(
                        agent=agent_dir.name,
                        kind=kind,
                        job_dir=job_dir,
                        classification=state.classification,
                        status=state.status,
                        failure_category=state.failure_category,
                        normalization_issues=state.normalization_issues,
                        record_complete=state.record_complete,
                        task_id=state.task_id,
                        repeat=state.repeat,
                    )
                )
    return states


def _docker(args: Sequence[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _is_eval_container(name: str, image: str) -> bool:
    haystack = f"{name} {image}".lower()
    return any(marker in haystack for marker in EVAL_CONTAINER_MARKERS)


def probe_docker(runner: Any = None) -> DockerStatus:
    """检查 daemon 与疑似评测残留；runner 可注入以便离线测试。"""
    run = runner or _docker
    try:
        info = run(["info", "--format", "{{.ServerVersion}}"])
    except Exception as exc:  # noqa: BLE001
        return DockerStatus(online=False, error=f"{type(exc).__name__}: {str(exc)[:120]}")
    if info.returncode != 0:
        detail = ((info.stderr or "") + (info.stdout or "")).strip()
        return DockerStatus(online=False, error=detail[:200] or "docker info 失败")
    version = (info.stdout or "").strip() or None
    containers: list[dict[str, str]] = []
    try:
        listing = run(["ps", "-a", "--format", "{{.Names}}|{{.Status}}|{{.Image}}"])
        for line in (listing.stdout or "").splitlines():
            parts = line.split("|")
            if len(parts) < 3:
                continue
            name, status, image = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if _is_eval_container(name, image):
                containers.append({"name": name, "status": status, "image": image})
        networks = run(["network", "ls", "--format", "{{.Name}}"])
        eval_networks = tuple(
            name.strip()
            for name in (networks.stdout or "").splitlines()
            if name.strip().startswith(EVAL_NETWORK_PREFIX)
        )
    except Exception as exc:  # noqa: BLE001
        return DockerStatus(
            online=True, server_version=version, error=f"{type(exc).__name__}: {str(exc)[:120]}"
        )
    return DockerStatus(
        online=True,
        server_version=version,
        eval_containers=tuple(containers),
        eval_networks=eval_networks,
    )


def prune_docker(status: DockerStatus, runner: Any = None) -> list[str]:
    """只清理疑似评测残留；返回已执行动作。"""
    run = runner or _docker
    actions: list[str] = []
    for container in status.eval_containers:
        name = container.get("name")
        if not name:
            continue
        run(["rm", "-f", name])
        actions.append(f"rm container {name}")
    for network in status.eval_networks:
        run(["network", "rm", network])
        actions.append(f"rm network {network}")
    return actions


def plan_moves(states: Iterable[JobState], root: Path, stamp: str) -> list[MovePlan]:
    """只规划未完成 / 无结果 job 的移动；已完成不进入计划。"""
    plans: list[MovePlan] = []
    for state in states:
        if not state.residual:
            continue
        target = (
            root / f"abandoned-auto-{stamp}" / state.agent / Path(state.kind) / state.job_dir.name
        )
        plans.append(MovePlan(source=state.job_dir, target=target))
    return plans


def apply_moves(plans: Sequence[MovePlan]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for plan in plans:
        plan.target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(plan.source), str(plan.target))
        results.append({"from": str(plan.source), "to": str(plan.target)})
    return results


def resume_commands(root: Path, agents: Iterable[str]) -> list[str]:
    names = sorted(set(agents))
    agent_flag = f" --agents {' '.join(names)}" if names else ""
    return [
        f"uv run --no-sync python scripts/run_formal_240.py --out {root} --skip-existing{agent_flag}",
        f"uv run --no-sync python scripts/verify_patches.py --out {root} --tasks-root <v2/tasks>{agent_flag}",
    ]


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _report(states: Sequence[JobState], root: Path) -> dict[str, Any]:
    counts = Counter(state.classification for state in states)
    residual = [state for state in states if state.residual]
    return {
        "root": str(root),
        "total_jobs": len(states),
        "counts": {name: counts.get(name, 0) for name in (COMPLETED, INCOMPLETE, NO_RESULT)},
        "residual": [state.as_dict(root) for state in residual],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("SAYACODE_BENCH_FORMAL_ROOT", DEFAULT_ROOT)),
        help="结果根目录（含 <agent>/jobs 与 <agent>/verify/jobs）",
    )
    parser.add_argument("--agents", nargs="+", default=None, help="只处理指定 agent")
    parser.add_argument("--dry-run", action="store_true", default=None, help="只报告（默认）")
    parser.add_argument("--apply", action="store_true", help="实际移动未收尾 / 无结果 job")
    parser.add_argument(
        "--prune", action="store_true", help="清理疑似评测残留容器与网络（仅 --apply 时生效）"
    )
    parser.add_argument("--no-docker", action="store_true", help="跳过 Docker 检查")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.apply and args.dry_run:
        parser.error("--apply 与 --dry-run 互斥")
    apply = bool(args.apply)
    if not args.root.is_dir():
        print(f"[错误] 结果根目录不存在：{args.root}", file=sys.stderr)
        return 2

    docker = DockerStatus(online=False, error="已跳过")
    if not args.no_docker:
        docker = probe_docker()
    if docker.online:
        print(f"[docker] 在线，ServerVersion={docker.server_version}")
        print(
            f"[docker] 疑似评测残留容器 {len(docker.eval_containers)} 个，网络 {len(docker.eval_networks)} 个"
        )
        for container in docker.eval_containers:
            print(f"  - 容器 {container['name']}  {container['status']}  {container['image']}")
        for network in docker.eval_networks:
            print(f"  - 网络 {network}")
    else:
        print(f"[docker] 不可用：{docker.error}")

    states = scan_root(args.root, agents=args.agents)
    report = _report(states, args.root)
    counts = report["counts"]
    print(
        f"\n[scan] 共 {report['total_jobs']} 个 job："
        f"已完成 {counts[COMPLETED]}，未收尾 {counts[INCOMPLETE]}，无结果 {counts[NO_RESULT]}"
    )
    for item in report["residual"]:
        extra = ""
        if item["failure_category"]:
            extra += f"  failure_category={item['failure_category']}"
        if item["normalization_issues"]:
            extra += f"  issues={','.join(item['normalization_issues'])}"
        print(f"  - [{item['classification']}] {item['path']}{extra}")

    stamp = _stamp()
    plans = plan_moves(states, args.root, stamp)
    moved: list[dict[str, str]] = []
    pruned: list[str] = []
    if apply:
        if plans:
            moved = apply_moves(plans)
            print(
                f"\n[apply] 已移动 {len(moved)} 个 job 到 {args.root / f'abandoned-auto-{stamp}'}"
            )
        else:
            print("\n[apply] 没有需要移动的 job")
        if args.prune and docker.online:
            pruned = prune_docker(docker)
            print(f"[apply] Docker 清理动作 {len(pruned)} 条")
            for action in pruned:
                print(f"  - {action}")
    else:
        print(
            f"\n[dry-run] 将移动 {len(plans)} 个 job 到 {args.root / f'abandoned-auto-{stamp}'}（加 --apply 执行）"
        )

    residual_agents = sorted({state.agent for state in states if state.residual})
    commands = resume_commands(args.root, residual_agents)
    print("\n[resume] 续跑命令：")
    for command in commands:
        print(f"  {command}")

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "apply" if apply else "dry-run",
        "docker": {
            "online": docker.online,
            "server_version": docker.server_version,
            "error": docker.error,
            "eval_containers": list(docker.eval_containers),
            "eval_networks": list(docker.eval_networks),
        },
        "scan": report,
        "moves": moved,
        "planned_moves": [{"from": str(plan.source), "to": str(plan.target)} for plan in plans],
        "pruned": pruned,
        "resume_commands": commands,
    }
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[json] 已写 {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
