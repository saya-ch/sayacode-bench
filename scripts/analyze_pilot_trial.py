"""分析 pilot 里已完成的 trial：patch 覆盖了 gold 的多少、行为量多少。

用于在官方验证之前先判断「agent 是不是只改了个皮毛」。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TASKS = Path(r"C:\sb\newset\swe-evo\tasks")


def files_of(patch_text: str) -> set[str]:
    out = set()
    for line in patch_text.splitlines():
        if line.startswith("+++ "):
            name = line[4:].strip()
            if name.startswith("b/"):
                name = name[2:]
            if name and name != "/dev/null":
                out.add(name)
    return out


def stat(patch_text: str) -> tuple[int, int, int]:
    files = len(re.findall(r"^diff --git ", patch_text, re.M))
    added = len(re.findall(r"^\+[^+]", patch_text, re.M))
    removed = len(re.findall(r"^-[^-]", patch_text, re.M))
    return files, added, removed


def audit_stats(path: Path) -> dict:
    tools: dict[str, int] = {}
    n_model = n_tool = 0
    errors = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"model.started"' in line:
            n_model += 1
        if '"tool.completed"' in line:
            n_tool += 1
            try:
                d = json.loads(line).get("details") or {}
            except ValueError:
                continue
            tools[str(d.get("tool_name"))] = tools.get(str(d.get("tool_name")), 0) + 1
            if d.get("error_type"):
                errors += 1
    return {"model_calls": n_model, "tool_calls": n_tool, "tool_errors": errors, "tools": tools}


def main() -> None:
    job = Path(sys.argv[1])
    stem = job.name.replace("sayacode-", "").rsplit("-r", 1)[0].rstrip("-")
    candidates = [
        d for d in TASKS.iterdir() if d.is_dir() and (stem in d.name or d.name.startswith(stem))
    ]
    if not candidates:
        # 退化匹配：用 job 名的前 28 字符
        candidates = [d for d in TASKS.iterdir() if d.is_dir() and d.name.startswith(stem[:28])]
    task_dir = candidates[0] if candidates else None

    patch = next(job.rglob("model.patch"), None)
    print(f"trial: {job.name}")
    print(f"task dir: {task_dir.name if task_dir else '?'}")
    if not patch:
        print("no model.patch")
        return
    text = patch.read_text(encoding="utf-8", errors="replace")
    n_files, added, removed = stat(text)
    mine = files_of(text)
    print(f"\nagent patch: {patch.stat().st_size} 字节, {n_files} 文件, +{added}/-{removed}")

    if task_dir:
        gold = task_dir / "solution" / "gold_patch.diff"
        if gold.is_file():
            gtext = gold.read_text(encoding="utf-8", errors="replace")
            g_files, g_added, g_removed = stat(gtext)
            gset = files_of(gtext)
            print(f"gold patch : {gold.stat().st_size} 字节, {g_files} 文件, +{g_added}/-{g_removed}")
            covered = mine & gset
            print(
                f"\n覆盖: {len(covered)}/{len(gset)} 个 gold 文件 "
                f"({len(covered) / len(gset) * 100:.0f}%)；agent 多改 {len(mine - gset)} 个"
            )
            missing = sorted(gset - mine)[:8]
            if missing:
                print("gold 里没被碰的文件（前 8 个）:")
                for m in missing:
                    print("  -", m)

    audit = next(job.rglob("audit.jsonl"), None)
    if audit:
        s = audit_stats(audit)
        print(f"\n行为: 模型调用 {s['model_calls']}, 工具调用 {s['tool_calls']}, 工具错误 {s['tool_errors']}")
        top = sorted(s["tools"].items(), key=lambda kv: -kv[1])[:8]
        print("  工具分布:", ", ".join(f"{k}={v}" for k, v in top))


if __name__ == "__main__":
    main()
