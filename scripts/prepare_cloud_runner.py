"""在全新 GitHub Linux VM 移除不用的宿主工具链，为官方容器保留磁盘。"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from sayacode_bench.artifacts import write_json

# 仅限托管镜像中与本研究无关的宿主工具链，不触碰 Docker 或任务容器。
PREINSTALLED_TOOLCHAINS = (Path("/usr/local/lib/android"), Path("/usr/share/dotnet"))


def require_hosted_runner() -> None:
    if (
        platform.system() != "Linux"
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
        or os.environ.get("RUNNER_OS") != "Linux"
        or os.environ.get("GITHUB_REPOSITORY") != "saya-ch/sayacode-bench-runs"
    ):
        raise ValueError("仅允许指定私有仓库的全新 GitHub Linux 托管 VM")


def prepare(output: Path) -> dict[str, Any]:
    """不调用模型、不修改镜像；保存宿主准备前后真实空闲空间。"""
    require_hosted_runner()
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    output = output.resolve()
    if not output.is_relative_to(temporary) or output == temporary:
        raise ValueError("宿主准备记录必须位于本 job 临时目录")
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "role": "ephemeral_host_preparation_not_task_environment_change",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runner_image": {
            key: os.environ.get(key) for key in ("ImageOS", "ImageVersion", "RUNNER_ARCH")
        },
        "free_before_bytes": shutil.disk_usage("/").free,
        "targets": [],
        "passed": False,
    }
    write_json(output, evidence)
    try:
        for target in PREINSTALLED_TOOLCHAINS:
            if target.resolve() != target or target.is_symlink() or target.is_mount():
                raise ValueError("预装工具链路径不是预定的普通目录")
            row = {"path": str(target), "existed": target.exists(), "removed": False}
            evidence["targets"].append(row)
            write_json(output, evidence)
            if row["existed"]:
                if not target.is_dir():
                    raise ValueError("预装工具链不是目录")
                subprocess.run(
                    ["sudo", "rm", "-rf", "--", str(target)],
                    check=True,
                    timeout=600,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if target.exists():
                    raise ValueError("预装工具链移除未确认")
                row["removed"] = True
            evidence["free_after_bytes"] = shutil.disk_usage("/").free
            write_json(output, evidence)
        evidence["passed"] = True
        return evidence
    finally:
        evidence["free_after_bytes"] = shutil.disk_usage("/").free
        write_json(output, evidence)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare(args.output)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # 不打印底层命令正文、环境或任意本机路径。
        print(type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
