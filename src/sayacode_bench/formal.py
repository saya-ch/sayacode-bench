"""正式三 agent 对比的最终汇总：计划分母、缺失分类与三口径。

只读取已落盘的 job 目录、冻结题集与显式故障清单；不重新判分、不读取题面、不调用模型。

口径约定：

- ``planned``：冻结题集每题 × 计划重复数，缺失一律按未通过计入。这是唯一可用于对外
  宣称的分母，禁止把「有 reward 的 trial 数」当成计划分母。
- ``observed``：计划矩阵中真正拿到 reward（或显式终态标记）的 trial 子集。
- ``bounds``：worst = 观测通过数 / planned；best = (观测通过数 + 缺失数) / planned。
  两者只在缺失原因无法归因时用于说明敏感性，不能替代 planned 口径。

缺失类别（每条计划项最多归一类）：

- ``no_job``：磁盘上没有对应 job 目录。
- ``empty_patch``：job 存在，但 ``agent/model.patch`` 缺失或 0 字节。
- ``unverified``：有非空 patch，但没有 reward，也没有终态标记。
- ``model_fault``：``MODEL-FAULTS.json`` 显式归因为模型侧故障且无 reward。
- ``unattributed``：job 存在但无法映射到冻结题集（单列，不进入题级矩阵）。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import file_sha256

SCHEMA_VERSION = 2
MISSING_CLASSES = ("no_job", "empty_patch", "unverified", "model_fault", "unattributed")
TERMINAL_EMPTY_PATCH = "skipped_empty_patch"
_REQUIRED_RE = re.compile(r"Required tests:\s*(\d+)")
_REQUIRED_PASSED_RE = re.compile(r"Required tests that passed:\s*(\d+)")


@dataclass(frozen=True)
class TaskSpec:
    """冻结题集里的一道题。"""

    task_id: str
    repository: str

    @property
    def task(self) -> str:
        """去掉 ``instance_`` 前缀的可读短名。"""
        prefix = "instance_"
        return self.task_id[len(prefix):] if self.task_id.startswith(prefix) else self.task_id


@dataclass(frozen=True)
class Trial:
    """磁盘上的一个 trial（native 或 verify 阶段）。"""

    agent: str
    job: str
    kind: str
    task_id: str | None
    repository: str | None
    repeat: int
    reward: float | None
    terminal: str | None
    patch_bytes: int | None
    partial: float | None
    restored_tests: bool
    stripped_tests: bool
    faults: tuple[str, ...] = ()

    @property
    def effective_reward(self) -> float | None:
        """显式终态（空 patch 跳过）按 0 分计入观测。"""
        if self.reward is not None:
            return self.reward
        if self.terminal is not None:
            return 0.0
        return None

    @property
    def observed(self) -> bool:
        return self.effective_reward is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "task_id": self.task_id,
            "task": _short_task(self.task_id),
            "repo": self.repository,
            "repeat": self.repeat,
            "job": self.job,
            "kind": self.kind,
            "reward": self.reward,
            "terminal": self.terminal,
            "effective_reward": self.effective_reward,
            "patch": self.patch_bytes,
            "partial": self.partial,
            "restored_tests": self.restored_tests,
            "stripped_tests": self.stripped_tests,
            "faults": list(self.faults),
        }


@dataclass(frozen=True)
class PlanItem:
    task: TaskSpec
    repeat: int


@dataclass(frozen=True)
class MissingTrial:
    task_id: str
    task: str
    repository: str
    repeat: int
    missing_class: str
    detail: str
    job: str | None
    faults: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task": self.task,
            "repo": self.repository,
            "repeat": self.repeat,
            "class": self.missing_class,
            "detail": self.detail,
            "job": self.job,
            "faults": list(self.faults),
        }


def _short_task(task_id: str | None) -> str:
    if not task_id:
        return ""
    prefix = "instance_"
    return task_id[len(prefix):] if task_id.startswith(prefix) else task_id


def load_sample(path: Path) -> tuple[list[TaskSpec], dict[str, Any]]:
    """读取冻结题集；题集是计划分母的唯一来源。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("tasks")
    if not isinstance(items, list) or not items:
        raise ValueError("题集必须包含非空 tasks 列表")
    tasks: list[TaskSpec] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("题集 tasks 的每一项必须是对象")
        task_id = item.get("task_id")
        repository = item.get("repo", item.get("repository"))
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("题集 task_id 必须是非空字符串")
        if not isinstance(repository, str) or not repository:
            raise ValueError(f"题集缺少 repo：{task_id}")
        tasks.append(TaskSpec(task_id, repository))
    if len({task.task_id for task in tasks}) != len(tasks):
        raise ValueError("题集存在重复 task_id")
    meta = {
        "path": str(path),
        "sha256": file_sha256(path),
        "size": len(tasks),
        "repositories": len({task.repository for task in tasks}),
        "size_declared": raw.get("size"),
    }
    return tasks, meta


def load_faults(path: Path | None) -> dict[tuple[str, str, str], tuple[str, ...]]:
    """读取 MODEL-FAULTS.json；缺失时返回空表，不猜测故障。"""
    if path is None or not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[tuple[str, str, str], tuple[str, ...]] = {}
    for entry in raw.get("faulty", []):
        if not isinstance(entry, Mapping):
            continue
        agent = str(entry.get("agent", ""))
        kind = str(entry.get("kind", "jobs"))
        job = str(entry.get("job", ""))
        faults = entry.get("faults", [])
        labels = tuple(str(value) for value in faults) if isinstance(faults, list) else ()
        result[(agent, kind, job)] = labels
    return result


def _read_reward(inner: Path) -> float | None:
    reward_file = inner / "verifier" / "reward.txt"
    if not reward_file.is_file():
        return None
    try:
        return float(reward_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _read_terminal(inner: Path) -> str | None:
    terminal_file = inner / "verifier" / "terminal.json"
    if not terminal_file.is_file():
        return None
    try:
        payload = json.loads(terminal_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    status = payload.get("status") if isinstance(payload, Mapping) else None
    return str(status) if status else None


def _read_partial(inner: Path) -> float | None:
    for stdout in inner.rglob("test-stdout.txt"):
        try:
            text = stdout.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        required = _REQUIRED_RE.search(text)
        passed = _REQUIRED_PASSED_RE.search(text)
        if required and passed and int(required.group(1)):
            return int(passed.group(1)) / int(required.group(1))
        break
    return None


def _read_patch_bytes(inner: Path) -> int | None:
    patch = inner / "agent" / "model.patch"
    return patch.stat().st_size if patch.is_file() else None


def _read_modification_flags(inner: Path) -> tuple[bool, bool]:
    """分别报告「恢复被改测试」与「删除新增测试」；不再混成一个 hacked。"""

    def present(name: str) -> bool:
        value = inner / "agent" / name
        if not value.is_file():
            return False
        try:
            payload = json.loads(value.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return True
        return bool(payload)

    return present("restored-test-files.json"), present("stripped-new-test-files.json")


def _read_inner_result(inner: Path) -> Mapping[str, Any]:
    result_file = inner / "result.json"
    if not result_file.is_file():
        return {}
    try:
        payload = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _task_from_result(inner: Path) -> str | None:
    payload = _read_inner_result(inner)
    name = payload.get("task_name")
    if isinstance(name, str) and name:
        return name.split("/")[-1]
    identifier = payload.get("task_id")
    if isinstance(identifier, Mapping):
        path = identifier.get("path")
        if isinstance(path, str) and path:
            return Path(path).name
    return None


def _repeat_of_job(job_name: str) -> int:
    match = re.search(r"-r(\d+)$", job_name)
    return int(match.group(1)) if match else 0


def _job_name_stem(job_name: str, agent: str) -> str:
    """job 名 = ``{agent}-{task_id 去掉 instance_ 的前 34 字符}-rN``。"""
    prefix = f"{agent}-"
    stem = job_name[len(prefix):] if job_name.startswith(prefix) else job_name
    return re.sub(r"-r\d+$", "", stem)


def _planned_job_name(agent: str, task_id: str, repeat: int) -> str:
    """复刻 run_formal_240 的 job 命名，用于把 MODEL-FAULTS 归因对回计划项。"""
    short = task_id[len("instance_"):] if task_id.startswith("instance_") else task_id
    return f"{agent}-{short[:34]}-r{repeat}"


def _match_task_by_job_name(stem: str, tasks: Sequence[TaskSpec]) -> str | None:
    candidates = [task.task_id for task in tasks if task.task_id.startswith("instance_")
                  and task.task_id[len("instance_"):].startswith(stem)]
    return candidates[0] if len(candidates) == 1 else None


def _resolve_task(
    inner: Path | None, job_name: str, agent: str, tasks: Sequence[TaskSpec]
) -> str | None:
    if inner is not None:
        task_id = _task_from_result(inner)
        if task_id:
            return task_id
    return _match_task_by_job_name(_job_name_stem(job_name, agent), tasks)


def _iter_jobs(base: Path) -> Iterable[Path]:
    if not base.is_dir():
        return []
    return sorted(path for path in base.iterdir() if path.is_dir())


def _inner_dir(job: Path) -> Path | None:
    return next(
        (child for child in sorted(job.iterdir()) if child.is_dir() and child.name.startswith("instance_")),
        None,
    )


def _collect_phase(
    base: Path,
    *,
    agent: str,
    tasks: Sequence[TaskSpec],
    faults: Mapping[tuple[str, str, str], tuple[str, ...]],
    kind: str,
) -> dict[str, Trial]:
    collected: dict[str, Trial] = {}
    for job in _iter_jobs(base):
        inner = _inner_dir(job)
        original = job.name[len("verify-"):] if kind == "verify" and job.name.startswith("verify-") else job.name
        task_id = _resolve_task(inner, original, agent, tasks)
        repository = next((task.repository for task in tasks if task.task_id == task_id), None)
        reward = _read_reward(inner) if inner is not None else None
        terminal = _read_terminal(inner) if inner is not None else None
        patch_bytes = _read_patch_bytes(inner) if inner is not None else None
        partial = _read_partial(inner) if inner is not None else None
        restored, stripped = _read_modification_flags(inner) if inner is not None else (False, False)
        job_key = original if kind == "verify" else job.name
        fault_key = (agent, "verify/jobs" if kind == "verify" else "jobs", job.name)
        collected[job_key] = Trial(
            agent=agent,
            job=job_key,
            kind=kind,
            task_id=task_id,
            repository=repository,
            repeat=_repeat_of_job(job.name),
            reward=reward,
            terminal=terminal,
            patch_bytes=patch_bytes,
            partial=partial,
            restored_tests=restored,
            stripped_tests=stripped,
            faults=faults.get(fault_key, ()),
        )
    return collected


def scan_agent(
    agent_dir: Path, agent: str, tasks: Sequence[TaskSpec],
    faults: Mapping[tuple[str, str, str], tuple[str, ...]] | None = None,
) -> list[Trial]:
    """扫描一个 agent 的 native 与 verify 阶段，verify 只在 native 缺 reward 时接管。"""
    faults = faults or {}
    native = _collect_phase(agent_dir / "jobs", agent=agent, tasks=tasks, faults=faults, kind="native")
    verified = _collect_phase(
        agent_dir / "verify" / "jobs", agent=agent, tasks=tasks, faults=faults, kind="verify"
    )
    merged: list[Trial] = []
    for job_name, trial in native.items():
        replay = verified.get(job_name)
        if trial.effective_reward is None and replay is not None and replay.observed:
            merged.append(
                Trial(
                    agent=agent,
                    job=job_name,
                    kind="verify",
                    task_id=trial.task_id or replay.task_id,
                    repository=trial.repository or replay.repository,
                    repeat=trial.repeat or replay.repeat,
                    reward=replay.reward,
                    terminal=replay.terminal,
                    patch_bytes=trial.patch_bytes,
                    partial=trial.partial if trial.partial is not None else replay.partial,
                    restored_tests=trial.restored_tests,
                    stripped_tests=trial.stripped_tests,
                    faults=trial.faults,
                )
            )
        else:
            merged.append(trial)
    for job_name, trial in verified.items():
        if job_name not in native and trial.observed:
            merged.append(trial)
    return merged


def build_plan(tasks: Sequence[TaskSpec], repeats: int) -> list[PlanItem]:
    if repeats < 1:
        raise ValueError("repeats 必须至少为 1")
    return [PlanItem(task=task, repeat=repeat) for task in tasks for repeat in range(1, repeats + 1)]


def classify_missing(trial: Trial | None) -> str | None:
    if trial is not None and trial.observed:
        return None
    if trial is None:
        return "no_job"
    if trial.faults:
        return "model_fault"
    if trial.patch_bytes is None or trial.patch_bytes == 0:
        return "empty_patch"
    return "unverified"


def summarize_agent(
    agent: str,
    trials: Sequence[Trial],
    plan: Sequence[PlanItem],
    *,
    faults: Mapping[tuple[str, str, str], tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """按计划矩阵对齐 trial，输出三口径、缺失清单与逐 trial 明细。"""
    faults = faults or {}
    by_key: dict[tuple[str, int], Trial] = {}
    unattributed: list[Trial] = []
    duplicates: list[dict[str, Any]] = []
    for trial in trials:
        if trial.task_id is None or trial.repeat < 1:
            unattributed.append(trial)
            continue
        key = (trial.task_id, trial.repeat)
        if key in by_key:
            duplicates.append({"task_id": trial.task_id, "repeat": trial.repeat, "job": trial.job})
            if by_key[key].effective_reward is None and trial.effective_reward is not None:
                by_key[key] = trial
            continue
        by_key[key] = trial

    matched: list[tuple[PlanItem, Trial | None]] = []
    for item in plan:
        matched.append((item, by_key.get((item.task.task_id, item.repeat))))

    rows: list[dict[str, Any]] = []
    missing: list[MissingTrial] = []
    counts: Counter[str] = Counter()
    for item, matched_trial in matched:
        missing_class = classify_missing(matched_trial)
        if missing_class is not None:
            counts[missing_class] += 1
            missing_faults: tuple[str, ...] = ()
            if matched_trial is not None:
                missing_faults = matched_trial.faults
            else:
                planned_job = _planned_job_name(agent, item.task.task_id, item.repeat)
                missing_faults = faults.get((agent, "jobs", planned_job), ())
            detail = _missing_detail(missing_class, matched_trial)
            if missing_class == "no_job" and missing_faults:
                detail += "；MODEL-FAULTS 曾归因：" + "、".join(missing_faults)
            entry = MissingTrial(
                task_id=item.task.task_id,
                task=item.task.task,
                repository=item.task.repository,
                repeat=item.repeat,
                missing_class=missing_class,
                detail=detail,
                job=matched_trial.job if matched_trial is not None else None,
                faults=missing_faults,
            )
            missing.append(entry)
            rows.append(
                {
                    **entry.as_dict(),
                    "kind": None,
                    "reward": None,
                    "terminal": None,
                    "effective_reward": None,
                    "patch": None,
                    "partial": None,
                    "restored_tests": False,
                    "stripped_tests": False,
                    "faults": list(missing_faults),
                }
            )
            continue
        assert matched_trial is not None
        rows.append(matched_trial.as_dict())

    planned = len(plan)
    observed_trials = [trial for _, trial in matched if trial is not None and trial.observed]
    observed = len(observed_trials)
    passes = sum(1 for trial in observed_trials if trial.effective_reward == 1.0)
    missing_count = len(missing)
    # 未被计划矩阵吸收的 job：只报告，不进入任何分母。
    for trial in unattributed:
        rows.append({**trial.as_dict(), "missing_class": "unattributed"})

    return {
        "agent": agent,
        "planned": planned,
        "observed": observed,
        "passes": passes,
        "missing": missing_count,
        "missing_counts": dict(sorted(counts.items())),
        "missing_trials": [entry.as_dict() for entry in missing],
        "unattributed": [trial.as_dict() for trial in unattributed],
        "duplicate_trials": duplicates,
        "rates": {
            "planned_pass_rate": passes / planned if planned else None,
            "observed_pass_rate": passes / observed if observed else None,
            "worst_bound": passes / planned if planned else None,
            "best_bound": (passes + missing_count) / planned if planned else None,
        },
        "trials": rows,
    }


def _missing_detail(missing_class: str, trial: Trial | None) -> str:
    if trial is None:
        return "磁盘上没有对应 job 目录"
    if missing_class == "model_fault":
        return "MODEL-FAULTS.json 归因：" + "、".join(trial.faults)
    if missing_class == "empty_patch":
        size = "缺失" if trial.patch_bytes is None else f"{trial.patch_bytes} 字节"
        return f"model.patch {size}"
    if missing_class == "unverified":
        return f"有 patch（{trial.patch_bytes} 字节）但没有验证 reward"
    return ""


def account_faults(
    agent_results: Mapping[str, Any],
    faults: Mapping[tuple[str, str, str], tuple[str, ...]],
) -> list[dict[str, Any]]:
    """把 MODEL-FAULTS 的每条归因对回实际落点，便于解释缺口。"""
    entries: list[dict[str, Any]] = []
    for (agent, kind, job), labels in sorted(faults.items()):
        data = agent_results.get(agent, {})
        rows = data.get("trials", []) if isinstance(data, Mapping) else []
        outcome = "unresolved"
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            missing_class = row.get("class") or row.get("missing_class")
            if row.get("job") == job:
                if missing_class:
                    outcome = "missing:" + str(missing_class)
                elif row.get("effective_reward") is not None:
                    outcome = f"observed_reward={row['effective_reward']}"
                break
            repeat = row.get("repeat")
            task_id = row.get("task_id")
            if (
                row.get("job") is None
                and missing_class
                and isinstance(task_id, str)
                and isinstance(repeat, int)
                and _planned_job_name(agent, task_id, repeat) == job
            ):
                outcome = "missing:" + str(missing_class)
                break
        entries.append(
            {"agent": agent, "kind": kind, "job": job, "faults": list(labels), "outcome": outcome}
        )
    return entries


def summarize(
    root: Path,
    *,
    sample: Path,
    repeats: int = 2,
    agents: Sequence[str] = ("sayacode", "mini-swe", "codex"),
    faults_path: Path | None = None,
) -> dict[str, Any]:
    """对结果根目录产出完整汇总；缺失 job 不再出现在明细中。"""
    tasks, sample_meta = load_sample(sample)
    faults = load_faults(faults_path if faults_path is not None else root / "MODEL-FAULTS.json")
    plan = build_plan(tasks, repeats)
    agent_results: dict[str, Any] = {}
    for agent in agents:
        agent_dir = root / agent
        if not agent_dir.is_dir():
            agent_results[agent] = summarize_agent(agent, [], plan, faults=faults)
            continue
        trials = scan_agent(agent_dir, agent, tasks, faults)
        agent_results[agent] = summarize_agent(agent, trials, plan, faults=faults)
    missing_total = sum(entry["missing"] for entry in agent_results.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "sample": sample_meta,
        "repeats": repeats,
        "agents": agent_results,
        "fault_accounting": account_faults(agent_results, faults),
        "totals": {
            "planned": len(plan) * len(agents),
            "observed": sum(entry["observed"] for entry in agent_results.values()),
            "passes": sum(entry["passes"] for entry in agent_results.values()),
            "missing": missing_total,
        },
    }


def missing_gap_report(summary: Mapping[str, Any]) -> dict[str, Any]:
    """把 19 条缺口按 agent × 类别展开，供报告直接引用。"""
    gaps: dict[str, Any] = {"total": 0, "by_agent": {}, "by_class": {}}
    by_class: Counter[str] = Counter()
    for agent, data in summary["agents"].items():
        gaps["by_agent"][agent] = {
            "planned": data["planned"],
            "observed": data["observed"],
            "missing": data["missing"],
            "classes": data["missing_counts"],
        }
        gaps["total"] += data["missing"]
        by_class.update(data["missing_counts"])
    gaps["by_class"] = dict(sorted(by_class.items()))
    return gaps


def write_summary(path: Path, summary: Mapping[str, Any]) -> None:
    from .artifacts import write_json

    write_json(path, summary)


__all__ = [
    "MISSING_CLASSES",
    "SCHEMA_VERSION",
    "TERMINAL_EMPTY_PATCH",
    "MissingTrial",
    "PlanItem",
    "TaskSpec",
    "Trial",
    "account_faults",
    "build_plan",
    "classify_missing",
    "load_faults",
    "load_sample",
    "missing_gap_report",
    "scan_agent",
    "summarize",
    "summarize_agent",
    "write_summary",
]
