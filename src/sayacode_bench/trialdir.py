"""trial 目录与产物定位：不依赖 task 的命名前缀。

Harbor 在**每个 job 目录下**创建一层 trial 子目录，目录名形如：

- SWE-bench：``instance_<org>__<repo>-<sha>__<random>``
- SWE-EVO：  ``sweevo-<slug>__<random>``
- 其它自建题库：任意 slug

它们**唯一的共同点**是：子目录里含 Harbor 产物（``result.json`` / ``agent/`` /
``verifier/``）。早期代码用 ``glob("instance_*")`` 或
``name.startswith("instance_")`` 来定位，这在接入非 SWE-bench 题库时会**静默**
返回空，表现为：

- 阶段 2 报「待验证 0 个」；
- 汇总时全部落到 ``no_job`` / ``empty_patch``；
- 归档判据把已完成 job 当成「无结果」移进 ``abandoned/``（**丢数据**）；
- 体检器输出空表。

2026-11-07 复盘（``docs/review/2026-11-07/R3-infrastructure.md`` S1/S3/S5）
确认这类假设仍有 15 处存活，且之前的修复（``46f57f0``）**未附任何回归测试**。
本模块把该判定收敛到一处，使「换题库」只需换数据、不必改代码。
"""

from __future__ import annotations

from pathlib import Path

#: 判定「这个子目录是 trial 目录」的依据；任一命中即可。
#: 不用目录名前缀，只用内容 —— 内容才是跨题库稳定的信号。
TRIAL_MARKERS: tuple[str, ...] = ("result.json", "agent", "verifier", "config.json")

#: 常见产物的相对位置（相对 trial 目录）
REWARD_PARTS: tuple[str, ...] = ("verifier", "reward.txt")
TERMINAL_PARTS: tuple[str, ...] = ("verifier", "terminal.json")
PATCH_PARTS: tuple[str, ...] = ("agent", "model.patch")
RESULT_PARTS: tuple[str, ...] = ("result.json",)


def _children(directory: Path) -> list[Path]:
    """列出直接子目录；目录不存在或无权限时返回空列表（不抛）。"""
    try:
        return [child for child in sorted(directory.iterdir()) if child.is_dir()]
    except OSError:
        return []


def is_trial_dir(path: Path) -> bool:
    """``path`` 是否像一个 Harbor trial 目录（按内容判定）。"""
    if not path.is_dir():
        return False
    return any((path / marker).exists() for marker in TRIAL_MARKERS)


def iter_trial_dirs(job_dir: Path) -> list[Path]:
    """返回 ``job_dir`` 下所有 trial 目录，按名字排序；没有则返回空列表。"""
    return [child for child in _children(job_dir) if is_trial_dir(child)]


def find_trial_dir(job_dir: Path) -> Path | None:
    """返回 ``job_dir`` 下的 trial 目录。

    优先级：
    1. 含 ``result.json`` 的子目录（Harbor 完成后一定有）；
    2. 含其它 marker 的子目录；
    3. ``job_dir`` 自身像 trial 目录（退化布局：产物直接放在 job 下）；
    4. ``instance_`` 前缀的子目录（仅为向后兼容旧布局，**不是判定依据**）；
    5. 第一个子目录（最宽松兜底）。

    找不到返回 ``None``。
    """
    children = _children(job_dir)
    with_result = [c for c in children if (c / "result.json").is_file()]
    if with_result:
        return with_result[0]
    marked = [c for c in children if is_trial_dir(c)]
    if marked:
        return marked[0]
    if is_trial_dir(job_dir):
        return job_dir
    prefixed = [c for c in children if c.name.startswith("instance_")]
    if prefixed:
        return prefixed[0]
    if children:
        return children[0]
    return None


def find_trial_file(job_dir: Path, *relparts: str) -> Path | None:
    """在 ``job_dir`` 下定位某个产物文件（不依赖前缀）。

    依次尝试：每个 trial 子目录下的相对路径 → ``job_dir`` 自身的相对路径。
    找不到返回 ``None``。
    """
    relative = Path(*relparts)
    for trial in iter_trial_dirs(job_dir):
        candidate = trial / relative
        if candidate.exists():
            return candidate
    direct = job_dir / relative
    return direct if direct.exists() else None


def has_trial_file(job_dir: Path, *relparts: str) -> bool:
    """``find_trial_file`` 的布尔版，便于在条件表达式里用。"""
    return find_trial_file(job_dir, *relparts) is not None


def find_trial_files(job_dir: Path, *relparts: str) -> list[Path]:
    """返回所有命中的产物文件（用于需要遍历多 trial 的场景）。"""
    relative = Path(*relparts)
    hits = [trial / relative for trial in iter_trial_dirs(job_dir) if (trial / relative).exists()]
    if not hits:
        direct = job_dir / relative
        if direct.exists():
            hits = [direct]
    return hits
