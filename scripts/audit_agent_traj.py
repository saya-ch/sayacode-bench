"""全量轨迹级 agent 适配健康审计。

动机：v2 里 Codex 组的 3 个 exception 让人以为「只有 3 个 trial 受影响」，
扫全量 `agent/*.txt` 才发现 **78/80 trial 有 unsupported call、80/80 有 websocket 405**，
即整组基线不可比。只看 exception.txt 会系统性低估适配缺陷。

本脚本对某个 agent 的所有 trial 统计适配健康信号（不依赖 exception.txt），
用于在出结论前验证「基线真的跑在正常状态」。

用法::

    uv run --no-sync python scripts/audit_agent_traj.py \\
        --root C:\\sb\\hard\\v2-325 --agent claude-code
"""

from __future__ import annotations

import argparse
import collections
import glob
import os
import re
from pathlib import Path

PATTERNS = {
    "unsupported_call": re.compile(r"unsupported call", re.I),
    "api_error": re.compile(r"API Error: (\d+)"),
    "websocket_405": re.compile(r"405 Method Not Allowed"),
    "unrecognized_model": re.compile(r"unrecognized_model"),
    # JSON 分隔符在紧凑（`"type":"x"`）与 pretty（`"type": "x"`）两种落盘格式下不同，
    # 必须容忍空白，否则只在一种格式的 trial 上命中（实测会让覆盖率掉到 50%）。
    "tool_use": re.compile(r'"type"\s*:\s*"tool_use"'),
    "tool_result": re.compile(r'"type"\s*:\s*"tool_result"'),
}


def _logs(job: Path) -> list[Path]:
    found: list[Path] = []
    for pattern in ("**/agent/*.txt", "**/agent/*.log", "**/*.txt"):
        found.extend(glob.glob(str(job / pattern), recursive=True))
    # 去重且只保留 agent 目录下的日志
    uniq = {p for p in found if os.sep + "agent" + os.sep in p}
    return sorted(uniq)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()

    base = Path(args.root) / args.agent / "jobs"
    if not base.is_dir():
        print(f"no jobs dir: {base}")
        return 1

    rows = []
    codes: collections.Counter = collections.Counter()
    for job in sorted(p for p in base.iterdir() if p.is_dir()):
        rewards = list(job.rglob("reward.txt"))
        reward = rewards[0].read_text(encoding="utf-8").strip() if rewards else None
        counts = {k: 0 for k in PATTERNS}
        size = 0
        for lg in _logs(job):
            try:
                text = Path(lg).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            size += len(text)
            for key, rx in PATTERNS.items():
                counts[key] += len(rx.findall(text))
            codes.update(PATTERNS["api_error"].findall(text))
        rows.append((job.name, reward, counts, size))

    n = len(rows)
    print(f"agent={args.agent} trials={n}")
    print("\n=== 适配健康信号（总量 / 命中 trial 数）===")
    for key in PATTERNS:
        total = sum(r[2][key] for r in rows)
        hit = sum(1 for r in rows if r[2][key] > 0)
        print(f"  {key:20} total={total:7}  trials={hit}/{n}")
    print(f"\n=== API 错误码分布 === {dict(codes) or '无'}")
    print("\n=== 按 reward 分组 ===")
    for rv in ("1", "0", None):
        sub = [r for r in rows if r[1] == rv]
        if not sub:
            continue
        print(
            f"  reward={rv}: n={len(sub)} api_error={sum(r[2]['api_error'] for r in sub)} "
            f"unsupported={sum(r[2]['unsupported_call'] for r in sub)} "
            f"tool_use={sum(r[2]['tool_use'] for r in sub)} "
            f"avg_log={sum(r[3] for r in sub)//max(1,len(sub))}B"
        )

    if args.json_out:
        import json

        Path(args.json_out).write_text(
            json.dumps(
                {
                    "agent": args.agent,
                    "trials": n,
                    "signals": {
                        k: {
                            "total": sum(r[2][k] for r in rows),
                            "trials": sum(1 for r in rows if r[2][k] > 0),
                        }
                        for k in PATTERNS
                    },
                    "api_error_codes": dict(codes),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n明细已写 {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
