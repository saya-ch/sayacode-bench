# 本机独立 WSL2 诊断环境

本目录保存 2026-10-22 实际执行的安装脚本和包版本。它是固定诊断环境的记录，不是通用工作站安装器，也不表示评分稳定性已经通过。

## 分发版与边界

- 独立名称：`sayacode-bench`，Ubuntu 24.04.5 LTS，WSL2。
- 动态虚拟磁盘上限 64 GiB；同时检查 Windows 物理磁盘余量。
- 根目录、Docker 数据和研究源／结果使用发行版自己的 ext4。
- Docker Engine 和 CLI 固定 29.7.2；实际依赖版本见本目录的 `package-versions.tsv`。
- 保留 Windows 全局 WSL 配置；首次安装及第一批诊断内核为 `6.6.87.2-microsoft-standard-WSL2`，后续升级单列在末节。
- Docker Desktop 在诊断期间停止，新 Engine 使用自己的 `/run/docker.sock`，没有共用 Desktop Engine。

同一台电脑上的另一个发行版仍共享 WSL 内核、Windows 虚拟化和物理硬件。新环境若通过诊断，只能说明这套配置下固定试验通过，不能唯一归因旧问题，也不能代替全部正式任务资格检查。

## 安装工件

微软分发清单指定的 Ubuntu 安装文件：

```text
ubuntu-24.04.5-wsl-amd64.wsl
388975696 bytes
SHA256 bb415d824822c4b878125729af451a5d18fb13d1cf5cbed9a7393ad64ac6039e
```

WSL 自带下载器首次返回 `Wsl/InstallDistro/0x80072f78`，没有注册发行版。随后通过 Ubuntu 镜像站取得文件，校验与微软清单完全相同后，以 `wsl --install --from-file ... --name sayacode-bench --location ... --version 2 --vhd-size 64GB --no-launch` 本地安装。安装文件和下载失败日志保存在仓库外。

来源：[微软分发清单](https://github.com/microsoft/WSL/blob/master/distributions/DistributionInfo.json)、[Ubuntu 官方文件](https://releases.ubuntu.com/24.04.5/ubuntu-24.04.5-wsl-amd64.wsl)、[实际镜像地址](https://mirrors.tuna.tsinghua.edu.cn/ubuntu-releases/24.04.5/ubuntu-24.04.5-wsl-amd64.wsl)。

## Docker 安装与生命周期

`bootstrap.sh` 使用 Docker 官方 apt 源，拒绝覆盖已有安装或配置。候选地址为 `172.30.240.1/24` 与 `172.29.0.0/16` 地址池；执行前已核对本机 Windows 和新发行版路由。其他机器必须先自行核对，不能直接将确认变量当作安全证明。

包安装期间的临时 `policy-rc.d` 阻止维护脚本启动服务；安装后已移出系统路径留档。新建的 Docker／socket／containerd 开机启动已关闭，诊断显式启动，避免以后启动发行版时意外与 Desktop 并行。

实际评测进程显式设置：

```bash
unset DOCKER_CONTEXT
export DOCKER_HOST=unix:///var/run/docker.sock
```

WSL 在空闲后可能结束发行版；诊断期间保留一个前台 WSL 会话，避免只有 systemd 服务时发行版退出。该会话只维持执行环境，不提供 Agent 服务。运行前仍需核对实际 Engine ID、操作系统、socket 和数据目录。

Python 宿主使用 uv 0.12.5、CPython 3.13.12 和仓库冻结锁文件。生产模型适配器自己的 Python 仍按产品基线规定安装，官方任务镜像的 Python 不被替换。

实际网络探针、两题固定八次诊断与后续结论见 [WSL 诊断记录](../../docs/archive/wsl-diagnostic.md)。本轮不调用模型；100 元为后续付费 API 预算，不用于购买主机，也不意味着必须花完。

## 后续 WSL 平台升级

用户随后使用已核验的微软安装包，以管理员身份升级至 WSL 3.0.3.0；实际启动内核为 `6.18.54.1-microsoft-standard-WSL2`。Ubuntu、Engine ID、Docker 包版本、存储和全局 WSL 配置保持原条件，新增的网络探针与固定八次诊断单独保存在 `reports/wsl3-fixture-diagnostic-20261022-v1/`。原安装脚本和初始版本记录没有改写成新平台。

新平台网络探针通过，但 qutebrowser 三次参考解均失败，未满足就绪门槛。本轮本地平台配置试验按预定规则结束，不推荐反复执行此安装脚本或更换版本到通过。既有安装器 Error 1730 是用户提权前的历史失败；它已不再是当前阻碍。
