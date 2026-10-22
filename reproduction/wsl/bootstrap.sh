#!/usr/bin/env bash
# 仅供新建的 sayacode-bench Ubuntu 24.04 WSL2 使用，由 root 审阅后执行。
# root 必须先实际核对 Windows/WSL 路由，确认下方两个候选网段没有冲突：
# SAYACODE_BENCH_ROUTES_CONFIRMED=1 bash bootstrap.sh
# 官方安装方式：https://docs.docker.com/engine/install/ubuntu/
# 本脚本只安装和配置，不启动 daemon、不运行容器或模型。
set -euo pipefail

if [[ ${EUID} -ne 0 || ${WSL_DISTRO_NAME:-} != sayacode-bench ]]; then
  printf '%s\n' '必须在独立 sayacode-bench WSL 发行版内以 root 执行。' >&2
  exit 2
fi
. /etc/os-release
if [[ ${ID:-} != ubuntu || ${VERSION_ID:-} != 24.04 || ${VERSION_CODENAME:-} != noble ]]; then
  printf '%s\n' '仅支持已确定的 Ubuntu 24.04 noble，停止安装。' >&2
  exit 2
fi
if [[ ${SAYACODE_BENCH_ROUTES_CONFIRMED:-} != 1 ]]; then
  printf '%s\n' '先核对实际路由：bip=172.30.240.1/24，pool=172.29.0.0/16、size=24；确认后显式设置 SAYACODE_BENCH_ROUTES_CONFIRMED=1。' >&2
  exit 2
fi

bootstrap_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v pgrep >/dev/null; then
  printf '%s\n' '缺少 pgrep，无法只读确认 daemon 状态；停止安装。' >&2
  exit 3
fi
for package in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx \
  podman-docker containerd runc docker-ce docker-ce-cli containerd.io; do
  if [[ "$(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true)" == installed ]]; then
    printf '已有相关包 %s；不卸载或替换，请 root 决定。\n' "$package" >&2
    exit 3
  fi
done
for path in /usr/sbin/policy-rc.d /etc/docker/daemon.json \
  /etc/apt/keyrings/docker.asc /etc/apt/sources.list.d/docker.sources \
  /etc/apt/sources.list.d/docker.list; do
  if [[ -e "$path" || -L "$path" ]]; then
    printf '保留已有文件 %s；请 root 检查后决定。\n' "$path" >&2
    exit 3
  fi
done
if pgrep -x dockerd >/dev/null || pgrep -x containerd >/dev/null || [[ -S /var/run/docker.sock ]]; then
  printf '%s\n' '检测到已有 daemon 或 Docker socket；不停止任何服务，退出。' >&2
  exit 3
fi

# 在任何 apt 安装之前阻止维护脚本启动服务；保留此文件供 root 后续处理。
# Debian 的 policy-rc.d 返回 101 表示拒绝服务动作，不需要修改系统服务状态。
cat > /usr/sbin/policy-rc.d <<'POLICY'
#!/bin/sh
# sayacode-bench：安装阶段由 root 保持服务未启动。
exit 101
POLICY
chmod 0755 /usr/sbin/policy-rc.d

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-remove --no-install-recommends ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL --connect-timeout 20 --max-time 120 \
  https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod 0644 /etc/apt/keyrings/docker.asc
architecture="$(dpkg --print-architecture)"
cat > /etc/apt/sources.list.d/docker.sources <<APT_SOURCE
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: ${architecture}
Signed-By: /etc/apt/keyrings/docker.asc
APT_SOURCE
chmod 0644 /etc/apt/sources.list.d/docker.sources
apt-get update

# 同时固定 Engine 和 CLI；没有该版本就停下，不改装其他版本。
apt-cache madison docker-ce docker-ce-cli > "$bootstrap_dir/docker-available-versions.txt"
mapfile -t candidates < <(apt-cache madison docker-ce | \
  awk '$3 ~ /(^|:)29[.]7[.]2-/ && $3 ~ /~ubuntu[.]24[.]04~noble$/ {print $3}' | sort -u)
if [[ ${#candidates[@]} -ne 1 ]]; then
  printf '%s\n' '官方 noble 仓库未给出唯一 Docker 29.7.2 包版本；已停止，由 root 决定，不回退其他版本。' >&2
  exit 4
fi
docker_package_version="${candidates[0]}"
if ! apt-cache madison docker-ce-cli | awk -v wanted="$docker_package_version" '$3 == wanted {found=1} END {exit !found}'; then
  printf '%s\n' 'CLI 缺少与 Engine 完全相同的包版本，停止安装。' >&2
  exit 4
fi

# 地址已由 root 确认才写入；Docker 状态使用该独立发行版的 /var/lib/docker。
install -m 0755 -d /etc/docker
cat > /etc/docker/daemon.json <<'DAEMON_CONFIG'
{
  "bip": "172.30.240.1/24",
  "default-address-pools": [{"base": "172.29.0.0/16", "size": 24}]
}
DAEMON_CONFIG
chmod 0644 /etc/docker/daemon.json
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-remove --no-install-recommends \
  "docker-ce=$docker_package_version" "docker-ce-cli=$docker_package_version" \
  containerd.io docker-buildx-plugin docker-compose-plugin

dpkg-query -W -f='${binary:Package}\t${Version}\n' \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
  > "$bootstrap_dir/package-versions.tsv"
cat "$bootstrap_dir/package-versions.tsv"
if pgrep -x dockerd >/dev/null || pgrep -x containerd >/dev/null || [[ -S /var/run/docker.sock ]]; then
  printf '%s\n' '发现 daemon 或 socket 意外出现；脚本未执行停止操作，请 root 检查。' >&2
  exit 5
fi
printf '%s\n' '指定包安装完成，未检测到 daemon/socket；policy-rc.d 仍保留，等待 root 后续决定启动。'
