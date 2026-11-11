"""验证 large-sample-v1-pro-v2-100.json 切片。

检查项：
  1. size == 100，task_id 无重复
  2. 100 ∩ 已用40 == 40（恰好包含现有 40 题，逐条比对 native_id）
  3. 新增 60 题全部在干净池内（逐条断言，且与已用 40 题零交集）
  4. 每个 native_id 在磁盘题目录真实存在，且 task.toml 可解析
  5. stratum 分布表（40 题 vs 100 题）
  6. schema 与现有 40 题文件一致
全部通过才 exit 0。

用法：
  python scripts/verify_slice_100.py
"""
from __future__ import annotations

import json
import sys
import tomllib
from collections import Counter
from pathlib import Path

BASE = Path(r"C:\develop\sayacode-bench\studies")
SLICE_100 = BASE / "large-sample-v1-pro-v2-100.json"
SLICE_40 = BASE / "large-sample-v1-pro-v2.json"
CANDIDATES = Path(r"C:\sb\hard\ab-ctx\holdout-candidates.json")
TASKS_DIR = Path(
    r"C:\sb\tmp\hard\cache\swe-bench-pro-v2-66f92766bba642462d4bbe5479e83f91f9211862\v2\tasks"
)

EXPECTED_SIZE = 100
EXPECTED_NEW = 60
EXPECTED_HEAD = 40


def derive_repo(native_id: str) -> str:
    s = native_id
    if s.startswith("instance_"):
        s = s[len("instance_"):]
    if "__" in s:
        s = s.split("__", 1)[1]
    return s.split("-", 1)[0]


class Checker:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.checks = 0

    def ok(self, cond: bool, label: str, detail: str = "") -> bool:
        self.checks += 1
        if cond:
            print(f"  [PASS] {label}" + (f"  {detail}" if detail else ""))
        else:
            print(f"  [FAIL] {label}" + (f"  {detail}" if detail else ""))
            self.failures.append(label + (f" :: {detail}" if detail else ""))
        return cond

    def report(self) -> int:
        print("\n" + "=" * 70)
        print(f"检查项 {self.checks} 个，失败 {len(self.failures)} 个")
        if self.failures:
            print("\n失败明细：")
            for f in self.failures:
                print(f"  - {f}")
            print("\n结论：FAIL")
            return 1
        print("\n结论：全部通过 (exit 0)")
        return 0


def main() -> int:
    c = Checker()

    print("=" * 70)
    print("验证 large-sample-v1-pro-v2-100.json")
    print("=" * 70)

    for p in (SLICE_100, SLICE_40, CANDIDATES, TASKS_DIR):
        if not p.exists():
            print(f"[FATAL] 路径不存在: {p}")
            return 2

    data = json.loads(SLICE_100.read_text(encoding="utf-8"))
    existing = json.loads(SLICE_40.read_text(encoding="utf-8"))
    cand = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    clean_set = set(cand["tasks"])
    tasks = data["tasks"]

    # ---------- 1) 基本结构 ----------
    print("\n[1] 基本结构")
    c.ok(data.get("size") == EXPECTED_SIZE, "size == 100", f"实际 {data.get('size')}")
    c.ok(len(tasks) == EXPECTED_SIZE, "tasks 长度 == 100", f"实际 {len(tasks)}")
    c.ok(data.get("schema_version") == existing.get("schema_version"),
         "schema_version 与 40 题文件一致",
         f"{data.get('schema_version')} vs {existing.get('schema_version')}")
    c.ok(data.get("source") == existing.get("source"), "source 一致", str(data.get("source")))
    c.ok(bool(data.get("seed")), "seed 已写明", str(data.get("seed")))
    c.ok(data.get("repeats") == 1, "repeats == 1", str(data.get("repeats")))
    c.ok(data.get("name") == "large-sample-v1-pro-v2-100", "name 正确", str(data.get("name")))

    # schema 键集合对齐（字段名完全一致）
    expected_keys = set(existing["tasks"][0].keys())
    bad_keys = [t["native_id"] for t in tasks if set(t.keys()) != expected_keys]
    c.ok(not bad_keys, "每条 task 的字段集合与 40 题文件一致",
         f"不一致 {len(bad_keys)} 条" if bad_keys else f"字段: {sorted(expected_keys)}")

    # ---------- 2) 无重复 ----------
    print("\n[2] 唯一性")
    nids = [t["native_id"] for t in tasks]
    tids = [t["task_id"] for t in tasks]
    c.ok(len(set(nids)) == EXPECTED_SIZE, "native_id 无重复", f"唯一 {len(set(nids))}")
    c.ok(len(set(tids)) == EXPECTED_SIZE, "task_id 无重复", f"唯一 {len(set(tids))}")
    c.ok(len(tids) == len(set(tids)), "task_id 数量一致")

    # task_id 格式
    bad_fmt = [t["task_id"] for t in tasks if t["task_id"] != f"pro-v2/{t['native_id']}"]
    c.ok(not bad_fmt, "task_id == 'pro-v2/'+native_id", f"异常 {len(bad_fmt)} 条")

    # ---------- 3) 前 40 题原样 == 现有 40 题 ----------
    print("\n[3] 前 40 题与现有切片对齐")
    ex_tasks = existing["tasks"]
    ex_nids = [t["native_id"] for t in ex_tasks]
    head = tasks[:EXPECTED_HEAD]
    head_nids = [t["native_id"] for t in head]
    c.ok(head_nids == ex_nids, "前 40 题的 native_id 序列与现有文件完全一致",
         f"一致 {sum(1 for a, b in zip(head_nids, ex_nids) if a == b)}/{len(ex_nids)}")

    # 逐字段原样比对。``memory_mb`` 是有意的例外：旧 40 题写的是占位符 0
    # （``compose_large_sample.py`` 的历史行为），而 ``task.toml`` 里的真实值是
    # 4096。该字段只作描述用途——``run_formal_240`` 只读 ``task_id``，容器内存由
    # Harbor 从 ``task.toml`` 解析——所以归一化不会改变任何已跑 trial 的语义。
    field_diff = []
    for i, (new_t, old_t) in enumerate(zip(head, ex_tasks)):
        for k in old_t.keys():
            if k == "memory_mb":
                continue
            if new_t.get(k) != old_t.get(k):
                field_diff.append((i, k, old_t.get(k), new_t.get(k)))
    c.ok(
        not field_diff,
        "前 40 题逐字段原样保留（memory_mb 除外）",
        f"差异 {len(field_diff)} 处" if field_diff else "",
    )
    if field_diff:
        for d in field_diff[:10]:
            print(f"     idx={d[0]} field={d[1]} old={d[2]!r} new={d[3]!r}")

    # memory_mb 必须写真实值，不能留历史占位符 0
    bad_mem = [t["native_id"] for t in tasks if t.get("memory_mb") != 4096]
    c.ok(
        not bad_mem,
        "全部 100 题 memory_mb == 4096（真实值，非占位 0）",
        f"异常 {len(bad_mem)} 条",
    )

    # ---------- 4) 100 ∩ 已用40 == 40 ----------
    print("\n[4] 与已用 40 题的集合关系")
    nid_set = set(nids)
    ex_set = set(ex_nids)
    inter = nid_set & ex_set
    c.ok(len(inter) == EXPECTED_HEAD, "100 ∩ 已用40 == 40",
         f"实际交集 {len(inter)}")
    extra_in_100 = inter - ex_set
    c.ok(not extra_in_100, "100 中没有已用40之外的『已用』题")

    # ---------- 5) 新增 60 题：全部在干净池，且与已用 40 零交集 ----------
    print("\n[5] 新增 60 题校验（逐条断言）")
    new_tasks = tasks[EXPECTED_HEAD:]
    c.ok(len(new_tasks) == EXPECTED_NEW, "新增题数 == 60", f"实际 {len(new_tasks)}")

    # 5a 逐条断言在干净池内
    not_in_clean = [t["native_id"] for t in new_tasks if t["native_id"] not in clean_set]
    c.ok(not not_in_clean, "新增 60 题逐条都在干净池内",
         f"不在干净池 {len(not_in_clean)} 条" if not_in_clean else "60/60 均在")
    for n in not_in_clean[:20]:
        print(f"     NOT_IN_CLEAN: {n}")

    # 5b 逐条断言与已用 40 题零交集
    overlap = [t["native_id"] for t in new_tasks if t["native_id"] in ex_set]
    c.ok(not overlap, "新增 60 题逐条都不在已用 40 题中",
         f"重叠 {len(overlap)} 条" if overlap else "60/60 均无重叠")
    for n in overlap[:20]:
        print(f"     OVERLAP: {n}")

    # 5c 新增题彼此不重复
    new_nids = [t["native_id"] for t in new_tasks]
    c.ok(len(set(new_nids)) == len(new_nids), "新增 60 题内部无重复")

    # 5d 干净池核算数字（记录实际值）
    usable = clean_set - ex_set
    print(f"     [信息] 干净池 {len(clean_ids := list(cand['tasks']))} 个；"
          f"与已用40 交集 {len(clean_set & ex_set)}；可用候选 {len(usable)}")

    # ---------- 6) 磁盘存在性 + task.toml 可解析 ----------
    print("\n[6] 磁盘题目录与 task.toml")
    missing_dir = []
    bad_toml = []
    repo_mismatch = []
    for t in tasks:
        nid = t["native_id"]
        d = TASKS_DIR / nid
        if not d.is_dir():
            missing_dir.append(nid)
            continue
        tpl = d / "task.toml"
        if not tpl.is_file():
            bad_toml.append((nid, "task.toml 缺失"))
            continue
        try:
            with tpl.open("rb") as f:
                meta = tomllib.load(f)
        except Exception as e:  # noqa: BLE001
            bad_toml.append((nid, f"解析失败: {e}"))
            continue
        # repo 字段与推导一致性
        if derive_repo(nid) != t["repo"]:
            repo_mismatch.append((nid, t["repo"], derive_repo(nid)))

    c.ok(not missing_dir, "100 个 native_id 磁盘目录全部存在",
         f"缺失 {len(missing_dir)}" if missing_dir else "100/100 存在")
    for n in missing_dir[:10]:
        print(f"     MISSING_DIR: {n}")

    c.ok(not bad_toml, "100 个 task.toml 全部可解析",
         f"失败 {len(bad_toml)}" if bad_toml else "100/100 可解析")
    for n, why in bad_toml[:10]:
        print(f"     BAD_TOML: {n} :: {why}")

    c.ok(not repo_mismatch, "repo 字段与推导规则一致",
         f"不一致 {len(repo_mismatch)}" if repo_mismatch else "100/100 一致")

    # ---------- 7) stratum 分布表 ----------
    print("\n[7] stratum 分布（40 题 vs 100 题）")
    ex_repo = Counter(t["repo"] for t in ex_tasks)
    all_repo = Counter(t["repo"] for t in tasks)
    new_repo = Counter(t["repo"] for t in new_tasks)
    repos = sorted(all_repo.keys(), key=lambda r: (-all_repo[r], r))

    print(f"    {'stratum':<14}{'40题':>6}{'新增':>6}{'100题':>7}{'100题占比':>11}")
    print("    " + "-" * 44)
    total = 0
    for r in repos:
        print(f"    {r:<14}{ex_repo.get(r,0):>6}{new_repo.get(r,0):>6}{all_repo[r]:>7}"
              f"{all_repo[r]/len(tasks)*100:>10.1f}%")
        total += all_repo[r]
    print("    " + "-" * 44)
    print(f"    {'合计':<14}{sum(ex_repo.values()):>6}{sum(new_repo.values()):>6}{total:>7}")

    # stratum 分布与配额推导一致（信息性，不做硬失败，只校验加总）
    c.ok(sum(all_repo.values()) == EXPECTED_SIZE, "stratum 计数加总 == 100")

    # stratum == repo 的一致性（现有切片口径）
    stratum_mismatch = [t["native_id"] for t in tasks if t["stratum"] != t["repo"]]
    c.ok(not stratum_mismatch, "stratum 与 repo 一致（沿用现有口径）",
         f"不一致 {len(stratum_mismatch)}" if stratum_mismatch else "")

    return c.report()


if __name__ == "__main__":
    sys.exit(main())
