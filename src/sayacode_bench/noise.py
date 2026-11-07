"""长上下文实验：把无关背景材料放到容器内文件，用短提示引导 agent 读取。

## 为什么是文件而不是 prompt

2026-11-07 实测：把 350KB（≈100k tokens）噪声直接拼进 instruction 时，
三个基线各自的传参通道**全部超限**：

| agent | 通道 | 失败 |
|---|---|---|
| mini-swe | argv ``--task=`` | Linux ``execve`` 单参数上限 → ``Argument list too long`` |
| Claude Code | 环境变量 | Windows 命令行 32KB → ``WinError 206`` |
| SAYACODE | ``--instruction <file>`` | ✅ 不受限 |

所以四组统一改成：**噪声写进容器内文件，instruction 只带一段固定短提示**。
这样传参通道的差异被彻底消除，组间可比性反而比原设计更好（原设计里
SAYACODE 走 prompt、基线走 argv/环境变量，通道本来就不同）。

## 代价（必须随结论声明）

测的东西从「prompt 里天然带着 100k 无关内容」变成「被告知去读一个 100k 的背景文件」。
前者更接近"上下文被动被占满"，后者更接近"主动检索"。两者都算长上下文压力，
但**不是同一件事**。

## 提示词设计约束

- 必须明确「与你要修的问题无关」——否则模型会把它当任务线索，变成另一回事；
- 必须明确「请完整读取」——否则模型可能只看开头几行，噪声就没进上下文；
- 必须提到「可能被截断，可分块读」——工具输出有上限，一次 `cat` 可能只拿到一部分；
- **长度固定**：提示词本身不含噪声，四组收到的提示完全一致。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

#: 背景材料在容器内的落点。所有 agent 统一。
BACKGROUND_PATH = "/tmp/BACKGROUND.md"

#: 指向噪声文件的环境变量。空或不存则整个机制不启用（clean 组）。
NOISE_ENV = "SAYACODE_BENCH_NOISE_FILE"

#: 固定提示。**不要**把噪声内容拼进来——四组必须收到逐字节一致的提示。
BACKGROUND_HINT = (
    "\n\n---\n\n"
    "【归档背景材料】\n"
    "本任务相关的历史归档材料已放入容器内 `{path}`（共 {chars:,} 字符）。\n"
    "它**与你当前要修复的问题无关**，不包含任何提示或答案，只是为了让上下文"
    "达到真实项目的规模。\n"
    "请在开始工作前先读取它：`cat {path}`（若一次输出被截断，请用 `sed -n` 分块读完）。\n"
    "之后照常完成任务即可，**不要**在最终答复里总结或复述这些材料。"
)


def noise_text() -> str | None:
    """读取噪声文件内容；未配置或为空则返回 ``None``。"""
    path = os.environ.get(NOISE_ENV)
    if not path:
        return None
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    return text if text.strip() else None


async def stage_background(instruction: str, environment: Any) -> str:
    """把噪声上传到容器内文件，并返回「原 instruction + 固定短提示」。

    ``environment`` 只需实现 ``upload_file(source_path, target_path)``。
    上传失败时不阻断任务——降级为原 instruction，并让调用方能在日志里看到。
    """
    text = noise_text()
    if text is None:
        return instruction

    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".md", delete=False, newline="\n"
    )
    local = Path(handle.name)
    try:
        handle.write(text)
        handle.close()
        await environment.upload_file(local, BACKGROUND_PATH)
    except Exception:  # noqa: BLE001 - 上传失败不应让整个 trial 崩掉
        return instruction
    finally:
        local.unlink(missing_ok=True)

    return instruction + BACKGROUND_HINT.format(path=BACKGROUND_PATH, chars=len(text))
