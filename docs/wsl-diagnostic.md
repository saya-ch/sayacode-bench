# Ubuntu WSL2 独立 Engine 诊断计划

日期：2026-10-22。本文先记录执行前确定的用户授权与固定条件，末节记录实际执行结果。计划和实测分别保留，不从安装成功推断评分稳定。

## 授权与本轮范围

用户同意在当前电脑上使用独立 Ubuntu WSL2 环境继续诊断，不购买云主机；授权的付费模型 API 总预算为 **100 元人民币以内**。

本轮只运行官方参考解和空解，**计划模型请求为 0，模型 API 费用为 0**。镜像拉取、依赖安装及官方验证器所需联网不属于模型调用。100 元授权供后续明确冻结的模型研究使用，不是本轮需要用完的额度，也不授权跳过诊断直接开始正式模型批次。

只新增独立诊断输出，保留此前本机失败、失效批次和云端对照。不能覆盖旧评分，不能把环境修复后的新结果回填为旧试验成功。

## 已有对照及其边界

此前两个固定任务在本机出现异常，独立 Linux 的 [GitHub Actions 对照](https://github.com/saya-ch/sayacode-bench/actions/runs/39736698121) 已执行八次：

| 任务 | 既有独立 Linux oracle | 既有独立 Linux nop |
| --- | --- | --- |
| qutebrowser 校准题 | 1 / 1 / 1 | 0 |
| OpenLibrary 开发候选题 | 1 / 1 / 1 | 0 |

该对照确认了同一不可变镜像在另一执行宿主上的固定正负例表现；它不是当前电脑、当前 WSL 环境或整个候选池的稳定性证明。最小证据保存在 `reports/cross-host-fixture-diagnostic-20261022/`。

此外，[捕获补丁云端重判](https://github.com/saya-ch/sayacode-bench/actions/runs/39740758231) 已记录 qutebrowser 同补丁三次通过、Ansible 同补丁三次失败；Ansible 在该 VM 的三次 oracle 均通过，nop 失败。其作用是区分补丁结果和环境异常，不能替代本轮两个任务的 WSL 诊断。已有 [原生 Linux 网络探针](https://github.com/saya-ch/sayacode-bench/actions/runs/39740819102) 也只覆盖其实际运行宿主，新 WSL Engine 仍需自己的网络证据。

本机先前资格批次已经失效，**不得将其失败修复组直接沿用为新 WSL 宿主的排除名单**。

## 固定的两题与八次试验

复用 `scripts/diagnose_fixtures.py` 的固定计划，不添加题目参数，不按结果改题或补跑到成功。公开源固定为 SWE-bench Pro V2，提交 `66f92766bba642462d4bbe5479e83f91f9211862`，Harbor 固定为 `0.24.0`。

### qutebrowser

- 任务 ID：`instance_qutebrowser__qutebrowser-3d01c201b8aa54dd71d4f801b1dd12feb4c0a08a-v5fc38aaf22415ab0b70567368332beee7955b367`。
- 镜像：`ghcr.io/scaleapi/swe-bench_pro-v2@sha256:cc0e0f503659eac82afb4f304e853c5a94ddd2aba834e62d3fd757fa6fba13e3`。
- 固定顺序：oracle 第 1、2、3 次，nop 第 1 次。

### OpenLibrary

- 任务 ID：`instance_internetarchive__openlibrary-ba3abfb6af6e722185d3715929ab0f3e5a134eed-v76304ecdb3a5954fcf13feb710e8c40fcf24b73c`。
- 镜像：`ghcr.io/scaleapi/swe-bench_pro-v2@sha256:94e6d17b2ccb9a6012860bd61e85fb9182b073f1673e46a01d0565989fe09add`。
- 固定顺序：oracle 第 1、2、3 次，nop 第 1 次。

先完成 qutebrowser 四次，再完成 OpenLibrary 四次；每次由官方 Harbor 创建全新环境，单并发。保留每题官方资源、Agent／验证器时间和任务文件，以上两题均为官方 1 CPU、4096 MB 内存，不改隐藏测试或参考解。拉取固定 digest 后核对原任务镜像引用解析到同一镜像，不能用同名 tag 代替实际身份。

## 环境身份与执行前检查

“独立 Engine”指 Ubuntu 内单独运行的 Docker daemon、镜像存储和容器生命周期，不能只是从 Ubuntu 调用了 Docker Desktop 的共享 socket。执行前保存并检查实际 Docker context、daemon 身份、服务端版本、操作系统、架构和存储条件。

同时记录 Ubuntu 版本、WSL 版本与内核、Python、冻结依赖、评测源码身份和任务配置哈希。源码与诊断结果使用分离目录；公开源保持固定 Git 字节，Linux 执行数据优先放在发行版自身文件系统，记录实际路径类别，不静默混用 Windows 挂载盘与 Linux 文件系统的结果。

运行前确认足够的内存和磁盘余量，执行当前网络实现的真实 mock 探针，保留网络阶段切换与清理证据。网络探针不得调用付费模型；先前 Windows 或云端探针不能自动充当当前 WSL Engine 的通过证据。

## 先诊断，再资格，再模型研究

1. 安装并核实 Ubuntu 独立 Engine 的实际身份，保存环境证据；安装动作完成不等于诊断通过。
2. 使用全新输出目录执行上述固定八次试验，保留计划、原生评分、镜像／平台／资源、验证器异常和日志哈希。中断、未知、镜像不一致或未执行项如实保留，不记成普通功能失败。
3. 只有两题的固定 oracle 均为 1、nop 均为 0，且运行证据完整，才考虑在该宿主继续完整资格流程。任一次异常不能通过换题、改依赖、改测试或只展示成功重复来修饰；需要修环境时，保留旧批次并建立新的明确身份。
4. 两题通过只说明这次有限诊断通过。正式任务仍须从原始 seed、完整候选池和预声明范围出发，在当前宿主逐题执行固定三次 oracle 加一次 nop；按原规则记录资格排除和机械替补。
5. 资格完成后，在实际执行宿主冻结正式清单、代码与依赖，再执行开发、候选签收和独立最终验收。跨宿主路径和私有连接不能通过修改旧冻结文件来混合结果。

主研究的目标仍为 **8 道开发任务、24 道最终任务**。不能因本机速度、资格失败或运行成本而静默缩小 N。达到原定资格候选预算、资源不足或无法填满目标时，报告 `incomplete` 和实际原因；不得把较小分母写成完整研究。保留基线时执行独立单组 validation，不制造基线与自身的配对比较。

## 后续 API 预算的冻结要求

后续若开始使用付费连接，需在新的正式 manifest 中冻结 100 元预算、保守价格、停止派发比例以及全部已发生费用记录。按照现有协议，在已观测保守估算达到预算的 80% 时停止新付费派发；用量缺失、费用证据变化和服务配额错误也必须停止并留证，不将本地连接的未知成本写成免费。

这是任务派发止损，不能声称已经获得供应商强制的人民币硬上限。当前没有可用的公开账单 API 作为总账，回调可能不覆盖重试、在途请求和缺失用量；正式调用前必须保留这些边界并核实实际可控额度，不能以“最大输出”推算并承诺绝对账单。本轮八次诊断不使用模型，因此不消耗这项模型 API 预算。

## WSL 能说明什么

不同 Docker Engine 可以改变 daemon、用户空间、容器存储及文件系统路径等条件，但 **WSL2 发行版仍共享 WSL 内核，并使用同一台电脑的 CPU、内存、固件和 Windows 虚拟化基础设施**。独立 Ubuntu Engine 不等于另一台物理 Linux 机器，也不能复刻既有 GitHub Actions 宿主。

若新环境通过，可支持进一步缩小差异范围，不能仅凭通过就认定 Docker Desktop 是唯一原因；若仍失败，也不能据此排除硬件、内核或其他共享条件。该诊断不证明 Agent 能力提升，不产生正式成功率，也不更改既有云端或本机评分。

## 第一批实际结果：WSL 2.6.3、独立 Engine

已完成专用 Ubuntu 24.04.5 安装；安装文件与微软清单 SHA256 一致。实际 Engine 与 Desktop 不同，服务端为 Ubuntu、版本 29.7.2，使用 `/run/docker.sock` 和自身 ext4 存储。WSL 平台没有升级，内核仍是 `6.6.87.2-microsoft-standard-WSL2`。安装过程与包版本见 [重建说明](../reproduction/wsl/README.md)。

固定评测代码为 `72c3698589e961f704bbf7109b803254863739a5`。新 Linux 依赖安装检查为 509 项通过、1 项 Docker 探针跳过；真实 Docker 网络探针随后单独通过，四类专属资源的独立清理检查也通过。基础测试不作为评分稳定性的证明。

固定八次全部执行，原生结果正常收尾，实际镜像全部匹配：

| 任务 | oracle 第 1／2／3 次 | nop |
| --- | --- | --- |
| qutebrowser | 1 / 0 / 0 | 0 |
| OpenLibrary | 1 / 1 / 1 | 0 |

qutebrowser 第二次失败发生在 Hypothesis 的 `int_from_bytes` 调用，出现 `AttributeError`；第三次同样未通过。原始 stdout／stderr、结果和运行时工件均保存，公开最小事实见 `reports/wsl-fixture-diagnostic-20261022-v1/`。整个原始目录另行归档在仓库外，SHA256 为 `15b79c3f151b8a579587d72005e0bd7774967dbda60586e0a77a5a172d4a08aa`。

**本批是已完成的负面就绪诊断，不是未完成试验。** 它没有满足两题全部参考解通过的预定准入条件，因此没有进入正式模型研究；模型请求与付费 API 消耗均为 0。结束后没有遗留试验容器或专属网络，Engine 自身与镜像缓存仍供后续受控诊断使用。

原来云端与本机试验的 Hypothesis 随机种子没有固定一致，不能仅凭该批跨宿主通过率差异唯一归因机器。日志给出了第二次失败种子 `242126932532074149523975327703198283377`；因此单列了官方 Harbor `VerifierConfig.env` 固定种子对照，在保持任务、镜像、参考解与评分器不变的条件下继续排查。该对照属于诊断偏离，不覆盖八次原分，也不计入正式成绩。

## 固定失败种子的跨环境对照

上述对照已按代码提交 `4b477a55d424afbc9b07124ef8c77a596f52e5a1` 完成。本机与 [GitHub Linux 实际运行](https://github.com/saya-ch/sayacode-bench/actions/runs/39776020824) 均固定同一 qutebrowser 任务、不可变镜像、失败种子和 `PYTHONHASHSEED=0`，各执行三次全新环境 oracle。

`PYTEST_ADDOPTS` 从固定镜像中只读提取，保留原 flags 后追加 seed；原生 Harbor Job／Trial 的验证器配置都核对一致，没有修改任务文件、镜像、参考解或评分器。两边的原 flags 哈希与注入环境哈希完全相同，诊断证据均完整：

| 条件 | 固定 seed 的三次 oracle |
| --- | --- |
| 本机独立 Ubuntu、WSL 2.6.3 | 0 / 0 / 0 |
| GitHub Linux | 1 / 1 / 1 |

公开证据见 `reports/fixed-hypothesis-seed-20261022/`，原始本机目录另行归档在仓库外，SHA256 为 `b2c90b641609e16499917120d5ded69541840aedfc9b47b2a0db6567f7a7aaf6`。这减少了随机种子差异这一解释，但仍不能唯一定位内核、硬件或其他条件；也不能证明所有外部随机性、时序或环境条件完全相同。

该对照每边固定三次全跑，没有按成绩重试。它是显式改变验证器环境参数的独立诊断，不进入正式研究，也不替换此前默认参数的八次结果。模型请求及付费 API 消耗仍为 0。

## 平台更新的实际阻碍

后续只准备了一次升级到微软稳定版 WSL 3.0.3／内核 6.18.54.1 的新平台对照；Ubuntu、Engine、镜像、资源和评测代码保持原条件。若该新平台仍出现相同异常，就结束本轮本地平台配置试验，不继续更换版本到通过为止。

内置更新的 Store 与 GitHub 下载方式均返回 HTTP 403。已从微软官方 release 下载完整 x64 MSI，SHA256 与官方资产元数据一致，Authenticode 为 Valid，签名者为 Microsoft Corporation。但 Windows Installer 在替换旧版本时返回 Error 1730（总退出码 1603），明确要求管理员权限。更新没有完成，实际版本仍为 2.6.3；不能将计划中的新内核对照写成已执行。

已核验的安装文件为 `wsl.3.0.3.0.x64.msi`，SHA256 `ae977286974255bd26bf925f00f40f5692c6b2084155cbc0563c09aea091f211`。管理员安装完成后，需先核验实际 WSL／内核版本，再在新目录运行一次网络探针和相同固定八次诊断。旧结果保持不变。安装器详细日志含用户信息，仅在仓库外保存；公开层只记录签名、错误码与未完成事实。

来源：[微软稳定版发布页](https://github.com/microsoft/WSL/releases/tag/3.0.3)、[官方 WSL 更新命令](https://learn.microsoft.com/en-us/windows/wsl/basic-commands#update-wsl)。
