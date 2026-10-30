"""跑前配置摘要：把关键 profile 参数与派生阈值打印出来，供人工确认。

复刻产品 src/sayacode/agent/graph.py::summary_trigger_for 的算法，确保与实际行为一致。
用法: python scripts/profile_summary.py <profile.json> [<profile2.json> ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def derive(profile: dict) -> dict:
    ctx = int(profile["context_length"])
    maxout = int(profile["max_output_tokens"])
    configured_input = max(1, ctx - maxout)
    margin = min(max(2_048, int(ctx * 0.05)), max(1, int(configured_input * 0.10)))
    reserved = max(1, configured_input - margin)
    cands = [reserved]
    ratio = profile.get("summary_trigger_ratio")
    if ratio is not None:
        cands.append(max(1, int(ctx * ratio)))
    explicit = profile.get("summary_trigger_tokens")
    if explicit is not None:
        cands.append(explicit)
    return {
        "context_length": ctx,
        "max_output_tokens": maxout,
        "usable_input": configured_input,
        "margin": margin,
        "summary_trigger": min(cands) if (ratio is not None or explicit is not None) else None,
        "trigger_ratio_of_context": (min(cands) / ctx) if (ratio is not None or explicit is not None) else None,
    }


def summary_text(path: str | Path) -> str:
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    d = derive(profile)
    trig = d["summary_trigger"]
    lines = [
        f"=== 跑前配置：{profile.get('name', Path(path).stem)} ===",
        f"  文件            {path}",
        f"  模型 model_id   {profile.get('model_id')}",
        f"  协议 protocol   {profile.get('protocol')}",
        f"  上下文          {d['context_length']:,} tokens（可用输入 {d['usable_input']:,}）",
        f"  最大输出        {d['max_output_tokens']:,} tokens",
        f"  摘要触发点      {trig:,} tokens（占上下文 {d['trigger_ratio_of_context']:.1%}）" if trig else "  摘要触发点      关闭",
        f"  摘要保留消息    {profile.get('summary_keep_messages')}",
        f"  上下文编辑      {profile.get('context_edit_trigger')!r}",
        f"  重试 model/tool {profile.get('model_retries')}/{profile.get('tool_retries')}",
    ]
    return "\n".join(lines)


def main() -> None:
    for p in sys.argv[1:]:
        print(summary_text(p))
        print()


if __name__ == "__main__":
    main()
