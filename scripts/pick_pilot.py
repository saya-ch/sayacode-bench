"""选 6 道 SWE-EVO 试点题：覆盖 5 个 repo，避开 f2p 过多/测试补丁过大的重题。"""

from __future__ import annotations

import json
from pathlib import Path

ROWS = Path(r"C:\sb\tmp\benchmarks\swe-evo-rows.json")
OUT = Path(r"C:\sb\tmp\pilot6.json")

WANT = {"dask": 2, "pydantic": 1, "psf": 1, "scikit-learn": 1, "iterative": 1}
MAX_F2P = 64
MAX_TESTPATCH = 200_000


def main() -> None:
    rows = json.loads(ROWS.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    picked = []
    for r in sorted(rows, key=lambda x: len(x["test_patch"])):
        org = r["repo"].split("/")[0]
        if WANT.get(org, 0) <= seen.get(org, 0):
            continue
        if len(r["FAIL_TO_PASS"]) > MAX_F2P or len(r["test_patch"]) > MAX_TESTPATCH:
            continue
        seen[org] = seen.get(org, 0) + 1
        picked.append(r)
    for r in picked:
        print(
            f"{r['instance_id']:44} {r['repo']:22} "
            f"f2p={len(r['FAIL_TO_PASS']):<3} testpatch={len(r['test_patch']):<7}"
        )
        print(f"    {r['image']}")
    OUT.write_text(json.dumps([r["instance_id"] for r in picked], indent=2), encoding="utf-8")
    print(f"\n共 {len(picked)} 题 → {OUT}")


if __name__ == "__main__":
    main()
