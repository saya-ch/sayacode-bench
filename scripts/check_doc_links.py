"""校验仓库内 markdown 链接：目标文件存在、锚点可解析、大小写与 git index 一致。

为什么需要它
------------
归档文档时最典型的破坏是把链接搬死——``docs/X.md`` 改成 ``docs/archive/X.md`` 时
漏掉一处就是 404。肉眼不可靠（本仓库有 400+ 条链接），需要机器把关。

第一版校验器（写在临时目录里）有六个盲区，这个版本逐一补上：

1. **锚点从未检查**。``[D29](#d29-...)`` 指向的标题被改写后，链接静默变成死引用。
2. **引用式链接**（``[x][ref]`` + ``[ref]: url``）和 ``<path.md>`` autolink 完全
   不认，只找 ``](...)``。
3. **围栏只认三反引号**，``~~~`` 和四个以上反引号的代码块会被当成正文去解析，
   里面的示例链接被误报。
4. **行内代码只认单反引号**，`` ``a`b`` `` 这种双反引号 span 里的内容会被误判。
5. **目标含括号或空格就被截断**，``[x](a_(b).md)`` 只取到 ``a_(b`` 。
6. **用 ``Path.exists()`` 判定**，Windows 大小写不敏感，写错大小写照样通过，
   clone 到 Linux/GitHub 才 404。

用法::

    python scripts/check_doc_links.py            # 校验整个仓库
    python scripts/check_doc_links.py --strict   # 锚点问题也算失败
"""

from __future__ import annotations

import argparse
import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {".venv", ".git", "node_modules", ".pytest_cache", ".ruff_cache", "dist"}

# ``` 或 ~~~ 围栏，允许 3 个以上同类字符、允许缩进
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1[ \t]*$", re.S | re.M)
# 双反引号优先于单反引号（``a`b`` 里的 a`b 不是代码边界）
INLINE_CODE_RE = re.compile(r"(``.+?``|`[^`\n]*`)", re.S)
# [text](target) 与 ![alt](target)；target 允许 <...> 包裹
INLINE_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)\s*(?:\"[^\"]*\")?\s*\)")
# [text][ref] 与 [text][] 与 [ref]
REF_LINK_RE = re.compile(r"!?\[([^\]]*)\]\[([^\]]*)\]")
REF_DEF_RE = re.compile(r"^[ \t]{0,3}\[([^\]]+)\]:\s*(\S+)", re.M)
AUTOLINK_RE = re.compile(r"<([^>\s]+\.md)>")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)


def slugify(heading: str) -> str:
    """GitHub 风格锚点：小写、去标点、**每个空格各换成一个连字符**。

    注意不能把连续空格折叠：``## 4. 三分法：站得住 / 描述性`` 里的 ``/`` 被删掉后
    留下两个相邻空格，GitHub 生成的是 ``4-三分法站得住--描述性``（双连字符）。
    折叠成单连字符会让这类锚点永远匹配不上。
    """
    text = heading.strip()
    text = re.sub(r"`([^`]*)`", r"\1", text)  # 去掉行内代码的反引号，保留内容
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # 保留链接文字
    text = text.lower()
    kept = []
    for ch in text:
        if ch.isalnum() or ch in "-_ ":
            kept.append(ch)
        elif unicodedata.category(ch).startswith("Z"):
            kept.append(" ")
    text = "".join(kept).strip()
    return text.replace(" ", "-")


def strip_fences(text: str) -> str:
    """只去掉围栏代码块，**保留行内代码**。

    标题里经常带行内代码（``#### D12｜`timeout` 分类…``）。如果连行内代码一起删掉，
    标题文本会缺词，算出来的 slug 必然对不上。
    """
    return FENCE_RE.sub("", text)


def strip_code(text: str) -> str:
    """去掉围栏代码块和行内代码——用于**抽取链接**，避免把示例链接当真链接。"""
    return INLINE_CODE_RE.sub("", strip_fences(text))


def headings_of(path: Path) -> set[str]:
    try:
        body = strip_fences(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return set()
    return {slugify(m.group(2)) for m in HEADING_RE.finditer(body)}


def iter_markdown(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.md") if not any(part in SKIP_PARTS for part in p.parts)]


def git_index_paths(root: Path) -> set[str] | None:
    """仓库内被 git 跟踪的文件（相对路径，正斜杠，保留原始大小写）。

    Windows 上 ``Path.exists()`` 大小写不敏感，写错也能过；以 git index 为准才能
    发现 ``README.MD`` 这种在 GitHub 上 404 的写法。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def collect_links(body: str) -> list[str]:
    """取出所有待检查的目标（含纯锚点；外链排除）。"""
    targets: list[str] = []

    refs: dict[str, str] = {}
    for m in REF_DEF_RE.finditer(body):
        refs[m.group(1).strip().lower()] = m.group(2).strip()

    for m in INLINE_LINK_RE.finditer(body):
        targets.append(m.group(1).strip("<>").strip())
    for m in REF_LINK_RE.finditer(body):
        key = (m.group(2) or m.group(1)).strip().lower()
        if key in refs:
            targets.append(refs[key].strip("<>").strip())
    for m in AUTOLINK_RE.finditer(body):
        targets.append(m.group(1).strip())

    out = []
    for t in targets:
        if not t:
            continue
        if t.startswith(("http://", "https://", "mailto:", "ftp:", "data:")):
            continue
        # 纯锚点 ``#foo`` 指向同文件，不能跳过——文档内部跳转最常见的就是这种写法，
        # 标题一改就静默失效。
        out.append(t)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--strict", action="store_true", help="锚点问题也计为失败")
    args = ap.parse_args()

    root = args.root.resolve()
    tracked = git_index_paths(root)

    missing: list[tuple[Path, str]] = []
    wrong_case: list[tuple[Path, str, str]] = []
    bad_anchor: list[tuple[Path, str]] = []
    checked = 0
    files = iter_markdown(root)

    for md in files:
        try:
            raw = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        body = strip_code(raw)

        for target in collect_links(body):
            path_part, _, anchor = target.partition("#")
            path_part = unquote(path_part).strip()
            if not path_part and not anchor:
                continue
            if not path_part:
                # 同文件锚点
                checked += 1
                if slugify(anchor) not in headings_of(md):
                    bad_anchor.append((md.relative_to(root), target))
                continue
            checked += 1
            resolved = (md.parent / path_part).resolve()
            try:
                rel = resolved.relative_to(root)
            except ValueError:
                continue  # 仓库外，不判定

            if not resolved.exists():
                missing.append((md.relative_to(root), target))
                continue

            if tracked is not None:
                posix = rel.as_posix()
                if posix not in tracked:
                    # 大小写不同但文件存在 -> GitHub 上会 404
                    lowered = {p.lower(): p for p in tracked}
                    actual = lowered.get(posix.lower())
                    if actual:
                        wrong_case.append((md.relative_to(root), target, actual))

            if anchor and resolved.suffix == ".md":
                if slugify(anchor) not in headings_of(resolved):
                    bad_anchor.append((md.relative_to(root), target))

    print(f"扫描 {len(files)} 份 markdown，检查 {checked} 条仓库内链接")
    for label, items in (("文件不存在", missing), ("大小写与 git index 不一致", wrong_case)):
        if items:
            print(f"\n❌ {label}：{len(items)} 条")
            for row in items[:40]:
                print("   " + "  ->  ".join(str(x) for x in row))
    if bad_anchor:
        print(
            f"\n{'❌' if args.strict else '⚠️ '} 锚点无法解析：{len(bad_anchor)} 条"
            f"{'（--strict 下计为失败）' if not args.strict else ''}"
        )
        for row in bad_anchor[:40]:
            print("   " + "  ->  ".join(str(x) for x in row))

    hard_fail = bool(missing or wrong_case) or (args.strict and bad_anchor)
    if not hard_fail:
        print("\n✅ 无断链")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
