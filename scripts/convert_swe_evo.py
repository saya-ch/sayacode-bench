"""把 SWE-EVO 的行转换成 Harbor task 目录（schema 1.4）。

字段来源：`swe-evo-rows.json` 的每行
  image / problem_statement / test_patch / patch / FAIL_TO_PASS / PASS_TO_PASS / test_cmds

产物结构与 SWE-bench Pro V2 的 task 同构：
  task.toml, instruction.md, environment/Dockerfile,
  tests/{test.sh, run_script.sh, parser.py, config.json, test_patch.patch},
  solution/{gold_patch.diff, solve.sh}
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

INSTRUCTION_TMPL = """A code repository is available in the `{workdir}` directory. Your task is to implement the changes necessary to satisfy the following Pull Request (PR) description:

<pr_description>
{problem}
</pr_description>
"""

TASK_TOML = """schema_version = "1.4"
artifacts = []

[task]
name = "{name}"
version = "1.0.0"
description = ""
authors = []
keywords = []

[metadata]
author_name = "SWE-EVO"
author_email = "unknown"
difficulty = "{difficulty}"
category = "debugging"
tags = [ "debugging", "swe-evo",]

[verifier]
network_mode = "public"
timeout_sec = 2400.0
collect = []

[verifier.env]

[agent]
network_mode = "no-network"
timeout_sec = 3000.0

[environment]
network_mode = "public"
"""

TEST_SH = r"""#!/bin/bash
ulimit -n 65536 2>/dev/null || true
set -uo pipefail

mkdir -p /logs/verifier

cleanup_and_reward() {
    local exit_code=$?
    mkdir -p /logs/verifier
    if [ "${exit_code}" -eq 0 ]; then
        echo 1 > /logs/verifier/reward.txt
    else
        echo 0 > /logs/verifier/reward.txt
    fi
    exit "${exit_code}"
}
trap cleanup_and_reward EXIT

WORKDIR="__WORKDIR__"
cd "$WORKDIR" || { echo "ERROR: cannot cd $WORKDIR"; exit 1; }

rm -f .git/index.lock 2>/dev/null || true

# 1) 把被 test_patch 触及的测试文件恢复到基线，防止 agent 改测试
python3 - <<'PYRESET'
import subprocess, re, sys
patch = open('/tests/test_patch.patch', encoding='utf-8', errors='replace').read()
files = set()
for line in patch.splitlines():
    m = re.match(r'^diff --git a/(.+?) b/(.+)$', line)
    if m:
        files.add(m.group(2))
    elif line.startswith('--- '):
        p = line[4:].strip()
        if p.startswith('a/'):
            files.add(p[2:])
for f in sorted(files):
    subprocess.run(['git', 'checkout', 'HEAD', '--', f], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(f'restored {len(files)} test files')
PYRESET

# 2) 应用 test_patch（已过滤为仅测试文件；--reject 容忍个别 hunk 对不上）
if [ -s /tests/test_patch.patch ]; then
    if ! git apply --reject --whitespace=nowarn /tests/test_patch.patch 2>/tmp/apply.err; then
        applied=$(git diff --stat | wc -l)
        echo "WARN: partial test_patch apply (${applied} files changed); see /tmp/apply.err"
        cat /tmp/apply.err | head -10
        if [ "${applied}" -eq 0 ]; then
            echo "ERROR: test_patch applied nothing"
            exit 1
        fi
    fi
else
    echo "no test_patch, using in-repo tests"
fi

# 3) 跑测试
bash /tests/run_script.sh > /logs/verifier/test.log 2>&1
test_rc=$?

# 4) 判定
python3 /tests/parser.py /logs/verifier/test.log
exit $?
"""

RUN_SCRIPT = r"""#!/bin/bash
# 由 test_cmds + FAIL_TO_PASS/PASS_TO_PASS 推导出的测试文件清单
# sweb.eval 镜像的 pytest 在 conda testbed env 里
if [ -d /opt/miniconda3/envs/testbed/bin ]; then
    export PATH="/opt/miniconda3/envs/testbed/bin:$PATH"
fi
cd __WORKDIR__ || exit 1
__TEST_CMD__
"""

PARSER = r'''"""判定 SWE-EVO 结果：FAIL_TO_PASS 全通过且 PASS_TO_PASS 全通过。

注意：镜像内是 Python 3.8，不能用 PEP 585 的 dict[str, str] 注解。
"""

import json
import re
import sys
from pathlib import Path

CONFIG = Path("/tests/config.json")


def parse_statuses(log_path):
    """从 pytest -rA 的 short summary 里取 node -> PASSED/FAILED/ERROR。"""
    out = {}
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    line_re = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S+)")
    tail_re = re.compile(r"^(\S+)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")
    for line in text.splitlines():
        s = line.strip()
        m = line_re.match(s)
        if m:
            out[m.group(2)] = m.group(1)
            continue
        m = tail_re.match(s)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    log = sys.argv[1] if len(sys.argv) > 1 else "/logs/verifier/test.log"
    statuses = parse_statuses(log)

    def norm(node: str) -> str:
        return node.replace("[", "::")

    normed = {norm(k): v for k, v in statuses.items()}

    def satisfied(node: str) -> bool:
        node = node.strip()
        for cand in (node, norm(node)):
            if normed.get(cand) == "PASSED":
                return True
        # 参数化用例：允许前缀匹配
        for key, val in normed.items():
            if val == "PASSED" and (key.startswith(node) or node.startswith(key)):
                return True
        return False

    f2p = [x for x in cfg.get("fail_to_pass", []) if x]
    p2p = [x for x in cfg.get("pass_to_pass", []) if x]

    if "--json" in sys.argv:
        # 基线验证用：输出每个测试的原始状态，便于外部决定如何修正 f2p/p2p
        payload = {"statuses": statuses, "f2p": f2p, "p2p": p2p}
        print("__JSON__" + json.dumps(payload))
        return 0

    missing_f2p = [x for x in f2p if not satisfied(x)]
    broken_p2p = [x for x in p2p if not satisfied(x)]

    print(f"fail_to_pass: {len(f2p) - len(missing_f2p)}/{len(f2p)} satisfied")
    print(f"pass_to_pass: {len(p2p) - len(broken_p2p)}/{len(p2p)} satisfied")
    for x in missing_f2p[:10]:
        print(f"  MISSING F2P: {x}")
    for x in broken_p2p[:10]:
        print(f"  BROKEN P2P: {x}")

    ok = not missing_f2p and not broken_p2p and bool(f2p)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
'''


TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|test_utils)/"
    r"|(^|/)conftest\.py$"
    r"|(^|/)test_[^/]*\.py$"
    r"|_test\.(py|go|rs|ts|js)$"
    r"|\.(test|spec)\.(ts|tsx|js|jsx)$"
)


def filter_test_patch(text: str) -> str:
    """只保留测试相关文件的补丁块。

    SWE-EVO 的 test_patch 常混入 CI 配置（.github/workflows/*.yml）等，
    这些文件在镜像里上下文对不上，会让整个 git apply 失败。
    """
    if not text.strip():
        return ""
    blocks = re.split(r"(?=^diff --git )", text, flags=re.M)
    keep = []
    for b in blocks:
        m = re.match(r"diff --git a/(\S+) b/(\S+)", b)
        if not m:
            continue
        if TEST_PATH_RE.search(m.group(2)):
            keep.append(b)
    return "".join(keep)


def build(row: dict, out_root: Path, workdir: str) -> Path:
    iid = row["instance_id"]
    safe = iid.replace("/", "_")
    d = out_root / f"sweevo-{safe}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "environment").mkdir(exist_ok=True)
    (d / "tests").mkdir(exist_ok=True)
    (d / "solution").mkdir(exist_ok=True)

    f2p = row.get("FAIL_TO_PASS") or []
    p2p = row.get("PASS_TO_PASS") or []
    if isinstance(f2p, str):
        f2p = json.loads(f2p.replace("'", '"'))
    if isinstance(p2p, str):
        p2p = json.loads(p2p.replace("'", '"'))

    files = sorted({x.split("::")[0] for x in list(f2p) + list(p2p) if "::" in x})
    test_cmd = (row.get("test_cmds") or "pytest -rA --continue-on-collection-errors -n0").strip()

    (d / "task.toml").write_text(
        TASK_TOML.format(
            name=f"swe-evo/{iid}",
            difficulty="medium",
        ),
        encoding="utf-8",
    )
    (d / "instruction.md").write_text(
        INSTRUCTION_TMPL.format(workdir=workdir, problem=row["problem_statement"].strip()),
        encoding="utf-8",
    )
    (d / "environment" / "Dockerfile").write_text(f"FROM {row['image']}\n", encoding="utf-8")
    (d / "tests" / "test.sh").write_text(
        TEST_SH.replace("__WORKDIR__", workdir), encoding="utf-8", newline="\n"
    )
    (d / "tests" / "run_script.sh").write_text(
        RUN_SCRIPT.replace("__WORKDIR__", workdir).replace(
            "__TEST_CMD__", f"{test_cmd} " + " ".join(files)
        ),
        encoding="utf-8",
        newline="\n",
    )
    (d / "tests" / "parser.py").write_text(PARSER, encoding="utf-8")
    (d / "tests" / "config.json").write_text(
        json.dumps({"fail_to_pass": f2p, "pass_to_pass": p2p}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (d / "tests" / "test_patch.patch").write_text(
        filter_test_patch(row.get("test_patch") or ""), encoding="utf-8", newline="\n"
    )
    (d / "solution" / "gold_patch.diff").write_text(row.get("patch") or "", encoding="utf-8")
    (d / "solution" / "solve.sh").write_text(
        "#!/bin/bash\ncd __WORKDIR__ && git apply /solution/gold_patch.diff\n".replace(
            "__WORKDIR__", workdir
        ),
        encoding="utf-8",
        newline="\n",
    )
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=r"C:\sb\tmp\benchmarks\swe-evo-rows.json")
    ap.add_argument("--out", default=r"C:\sb\newset\swe-evo\tasks")
    ap.add_argument("--workdir", default="/testbed")
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    rows = json.loads(Path(args.rows).read_text(encoding="utf-8"))
    if args.ids:
        want = set(args.ids)
        rows = [r for r in rows if r["instance_id"] in want]
    if args.limit:
        rows = rows[: args.limit]

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    for row in rows:
        d = build(row, out_root, args.workdir)
        print("built", d.name)
    print(f"\n共 {len(rows)} 题 → {out_root}")


if __name__ == "__main__":
    main()
