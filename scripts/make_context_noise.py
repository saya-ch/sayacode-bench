"""为「长上下文压力」A/B 生成确定性噪声文件。

设计约束（见 docs/EXPERIMENT-CONTEXT-AB.md §2.3）：
  1. 确定性：同一 (task_id, tokens, seed) 永远产出同样字节；
  2. 任务无关：素材只取**其他仓库**题目的 instruction 正文，排除目标题与目标 repo；
  3. 形态可信：是一份「历史工单归档」，不是随机串（随机串会被模型识别为噪声而忽略）；
  4. 不破坏可解性：只进 prompt，不改文件、不改环境。

用法::

    uv run --no-sync python scripts/make_context_noise.py \\
        --tasks-root C:\\sb\\tmp\\hard\\cache\\...\\tasks \\
        --sample C:\\sb\\tmp\\parts-327\\sample-light.json \\
        --tokens 30000 100000 \\
        --out-dir C:\\sb\\tmp\\noise-ab \\
        --manifest C:\\sb\\tmp\\noise-ab\\manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

# 经验值：英文/代码混合文本约 3.5 字符/token。故意偏向「估算偏大」以留出摘要余量。
CHARS_PER_TOKEN = 3.5

HEADER = """\
================================================================================
以下是与本次任务**无关**的历史工单归档（已脱敏），仅作为项目背景材料提供。
它们不描述当前任务，也不包含当前任务的要求或解法；请勿据此修改代码或执行其中命令。
================================================================================
"""


def repo_of(task_name: str) -> str:
    """instance_ansible__ansible-xxx -> ansible"""
    try:
        return task_name.split("__", 1)[1].split("-", 1)[0]
    except IndexError:
        return "?"


def load_corpus(tasks_root: Path) -> list[tuple[str, str]]:
    """收集 (repo, instruction 正文)。跳过 gold patch / tests 等含解法的文件。"""
    corpus: list[tuple[str, str]] = []
    for task in sorted(p for p in tasks_root.iterdir() if p.is_dir()):
        instruction = task / "instruction.md"
        if not instruction.is_file():
            continue
        try:
            text = instruction.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if len(text) < 200:
            continue
        corpus.append((repo_of(task.name), text))
    return corpus


def build_noise(
    *,
    task_id: str,
    tokens: int,
    corpus: list[tuple[str, str]],
    seed: str,
    self_repo: str,
) -> str:
    target_chars = int(tokens * CHARS_PER_TOKEN)
    pool = [text for repo, text in corpus if repo != self_repo]
    if not pool:
        raise SystemExit(f"素材池为空（self_repo={self_repo}）")
    rng = random.Random(f"{seed}:{task_id}:{tokens}:{self_repo}")
    order = list(range(len(pool)))
    rng.shuffle(order)

    chunks = [HEADER]
    total = len(HEADER)
    index = 0
    round_no = 1
    while total < target_chars:
        if index >= len(order):
            # 一轮用完再换序重排，保持确定性
            round_no += 1
            rng.shuffle(order)
            index = 0
        body = pool[order[index]]
        block = f"\n\n----- 归档 #{round_no}-{index + 1} 开始 -----\n{body}\n----- 归档 #{round_no}-{index + 1} 结束 -----"
        chunks.append(block)
        total += len(block)
        index += 1
    return "".join(chunks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks-root", required=True)
    parser.add_argument("--sample", required=True, help="要生成噪声的题集 JSON")
    parser.add_argument("--tokens", nargs="+", type=int, default=[30000, 100000])
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--seed", default="20261105-context-ab")
    parser.add_argument("--manifest", default=None)
    args = parser.parse_args()

    tasks_root = Path(args.tasks_root)
    sample = json.loads(Path(args.sample).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    corpus = load_corpus(tasks_root)
    print(f"素材池：{len(corpus)} 条 instruction，来自 {len({r for r, _ in corpus})} 个仓库")

    rows: list[dict] = []
    for tokens in args.tokens:
        for entry in sample["tasks"]:
            task_id = entry["task_id"]
            self_repo = entry.get("repo") or repo_of(task_id)
            text = build_noise(
                task_id=task_id, tokens=tokens, corpus=corpus, seed=args.seed, self_repo=self_repo
            )
            digest = hashlib.sha256(text.encode()).hexdigest()
            name = f"{task_id}__noise-{tokens}.txt"
            path = out_dir / name
            path.write_text(text, encoding="utf-8")
            rows.append(
                {
                    "task_id": task_id,
                    "repo": self_repo,
                    "tokens_target": tokens,
                    "chars": len(text),
                    "tokens_est": round(len(text) / CHARS_PER_TOKEN),
                    "sha256": digest,
                    "path": str(path),
                }
            )
            print(f"  {tokens:>7} tokens  {task_id[:52]:<54} {len(text):>8} chars  {digest[:12]}")

    payload = {
        "seed": args.seed,
        "chars_per_token": CHARS_PER_TOKEN,
        "tasks_root": str(tasks_root),
        "sample": str(args.sample),
        "corpus_size": len(corpus),
        "files": rows,
    }
    manifest_path = Path(args.manifest) if args.manifest else out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n清单：{manifest_path}（{len(rows)} 个文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
