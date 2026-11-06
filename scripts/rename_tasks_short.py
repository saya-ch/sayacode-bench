"""把 SWE-EVO task 目录改成短且合法的 slug，避免 Harbor 生成非法 Docker 镜像名。

问题：目录名 `sweevo-iterative__dvc_1.11.12_1.11.13` 被 Harbor slug 化后可能以 `-` 结尾，
与 `__<random>__env-main` 拼成 `-__`，Docker 报 invalid reference format。

slug 规则：仅保留 [a-z0-9]，其余折叠为单个 `-`，首尾去 `-`，加前缀 `sweevo-`。
同时更新任务目录名、task.toml 的 name、以及 sample 里的 task_id。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TASKS = Path(r"C:\sb\newset\swe-evo\tasks")
SAMPLE = Path(r"C:\sb\newset\swe-evo\sample-pilot.json")


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"sweevo-{s}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mapping: dict[str, str] = {}
    for d in sorted(p for p in TASKS.iterdir() if p.is_dir()):
        new = slug(d.name.replace("sweevo-", "", 1))
        if new == d.name:
            continue
        mapping[d.name] = new
        print(f"{d.name}\n  -> {new}")
        if args.dry_run:
            continue
        target = TASKS / new
        if target.exists():
            print(f"  SKIP: target exists {target}")
            continue
        d.rename(target)
        # 同步 task.toml 的 name
        toml = target / "task.toml"
        if toml.is_file():
            text = toml.read_text(encoding="utf-8")
            text = re.sub(r'^name = ".*"$', f'name = "swe-evo/{new}"', text, flags=re.M)
            toml.write_text(text, encoding="utf-8", newline="\n")

    if args.dry_run or not mapping:
        print(f"\n{len(mapping)} 个待改（dry-run）")
        return

    # 更新 sample
    if SAMPLE.is_file():
        s = json.loads(SAMPLE.read_text(encoding="utf-8"))
        for t in s["tasks"]:
            if t["task_id"] in mapping:
                t["task_id"] = mapping[t["task_id"]]
        SAMPLE.write_text(
            json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"\nsample 已更新: {SAMPLE}")

    print(f"\n改名 {len(mapping)} 个")


if __name__ == "__main__":
    main()
