"""对 pilot 已完成的 trial 做静态预测：patch 与 gold 的贴合度。

假设：patch 覆盖 gold 文件越少、改动量偏离 gold 越远，越可能失败。
等官方验证结果出来后，可以对照本表检验预测准不准。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

RUN = Path(r"C:\sb\newset\runs\pilot1\sayacode\jobs")
TASKS = Path(r"C:\sb\newset\swe-evo\tasks")


def files_of(text: str) -> set[str]:
    out = set()
    for line in text.splitlines():
        if line.startswith("+++ "):
            n = line[4:].strip()
            if n.startswith("b/"):
                n = n[2:]
            if n and n != "/dev/null":
                out.add(n)
    return out


def stat(text: str) -> tuple[int, int, int]:
    return (
        len(re.findall(r"^diff --git ", text, re.M)),
        len(re.findall(r"^\+[^+]", text, re.M)),
        len(re.findall(r"^-[^-]", text, re.M)),
    )


def task_dir_for(job_name: str) -> Path | None:
    stem = job_name.replace("sayacode-", "").rsplit("-r", 1)[0].rstrip("-")
    for d in TASKS.iterdir():
        if d.is_dir() and (d.name.startswith(stem) or stem.startswith(d.name[:28])):
            return d
    return None


def audit_stats(path: Path) -> tuple[int, int, int, int]:
    n_model = n_tool = n_edit = n_explore = 0
    EDIT = {"search_replace", "write_file", "delete_file"}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"model.started"' in line:
            n_model += 1
        elif '"tool.completed"' in line:
            n_tool += 1
            try:
                d = json.loads(line).get("details") or {}
            except ValueError:
                continue
            if str(d.get("tool_name")) in EDIT:
                n_edit += 1
            else:
                n_explore += 1
    return n_model, n_tool, n_edit, n_explore


CODE_SUFFIXES = (
    ".py", ".pyx", ".pxd", ".go", ".rs", ".ts", ".tsx", ".js", ".jsx", ".java", ".kt",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".rb", ".php", ".scala",
)


def code_files(files: set[str]) -> set[str]:
    """只保留源码文件。

    SWE-EVO 的「版本演进」题把整个发布改动都算进 gold patch：dask 那题
    102KB / 50 个文件里绝大多数是 .github/workflows/*.yml、dependabot.yml、
    .pre-commit-config.yaml 这类 CI 配置。用「对全部 gold 文件的覆盖率」
    会严重低估 agent，所以覆盖率只按源码文件算。
    """
    return {f for f in files if f.endswith(CODE_SUFFIXES)}


def main() -> None:
    rows = []
    for job in sorted(RUN.iterdir()):
        if not job.is_dir():
            continue
        patch = next(job.rglob("model.patch"), None)
        if not patch:
            continue
        text = patch.read_text(encoding="utf-8", errors="replace")
        files, added, removed = stat(text)
        mine = files_of(text)
        td = task_dir_for(job.name)
        gold_files = gold_added = gold_removed = 0
        gold_code_count = 0
        coverage = None
        if td:
            g = td / "solution" / "gold_patch.diff"
            if g.is_file():
                gt = g.read_text(encoding="utf-8", errors="replace")
                gold_files, gold_added, gold_removed = stat(gt)
                gset = code_files(files_of(gt))
                gold_code_count = len(gset)
                mine_code = code_files(mine)
                coverage = len(mine_code & gset) / len(gset) if gset else None
        audit = next(job.rglob("audit.jsonl"), None)
        nm = nt = ne = nx = 0
        if audit:
            nm, nt, ne, nx = audit_stats(audit)

        # 静态预测：coverage<0.6 或 改动量偏离 gold 3 倍以上 → 预测失败
        verdict = "?"
        if coverage is not None:
            ratio = (added + removed) / max(gold_added + gold_removed, 1)
            if coverage < 0.6 or ratio > 3 or ratio < 0.3:
                verdict = "FAIL(预测)"
            else:
                verdict = "PASS(预测)"

        rows.append(
            {
                "trial": job.name,
                "task": td.name if td else "?",
                "files": files,
                "delta": f"+{added}/-{removed}",
                "gold": f"{gold_files}f({gold_code_count}code) +{gold_added}/-{gold_removed}",
                "coverage": coverage,
                "explore_edit": f"{nx}/{ne}" if ne else f"{nx}/0",
                "model_calls": nm,
                "predict": verdict,
            }
        )

    print(f"{'trial':52}{'files':>6}{'delta':>12}{'gold':>14}{'cov':>7}{'explore/edit':>14}{'calls':>7}  predict")
    print("-" * 130)
    for r in rows:
        cov = f"{r['coverage'] * 100:.0f}%" if r["coverage"] is not None else "-"
        print(
            f"{r['trial'][:50]:52}{r['files']:>6}{r['delta']:>12}{r['gold']:>14}{cov:>7}"
            f"{r['explore_edit']:>14}{r['model_calls']:>7}  {r['predict']}"
        )

    out = Path(r"C:\sb\newset\pilot-predict.json")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {out}（官方验证出来后对照）")


if __name__ == "__main__":
    main()
