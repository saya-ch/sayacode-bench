# 执行宿主交叉验证

日期：2026-10-22。本节只讨论环境资格，不生成或修正 Agent 效果分数。

## 观察

本机 Docker 环境中，多个固定镜像的官方参考解出现不一致结果；OpenLibrary 有 pytest `SIGSEGV`，qutebrowser 有 AST／pytest 内部类型错误。不同次运行的实际镜像、架构与资源已经核对，异常并非全是正常功能断言失败。

因此没有将“运行过一次 gold 就通过”作为足够的正式准入，也没有通过只保留碰巧通过的任务来发布成绩。

## 固定云端对照

[实际 GitHub Actions 运行](https://github.com/saya-ch/sayacode-bench/actions/runs/39736698121) 使用固定源码、Harbor 0.24.0、相同不可变镜像 digest，两个已知任务各运行三次参考解和一次空解。没有模型密钥或模型调用；八次均完成，实际镜像全部确认。

| 任务 | 本机参考解复核 | 独立 Linux 参考解 | 独立 Linux 空解 |
| --- | --- | --- | --- |
| 校准 qutebrowser | 0 / 0 / 0 | 1 / 1 / 1 | 0 |
| 开发候选 OpenLibrary | 1 / 0 / 1 | 1 / 1 / 1 | 0 |

完整最小证据见 `reports/cross-host-fixture-diagnostic-20261022/`，包括固定计划、宿主与实际资源、镜像解析、逐次结构化结果及原始日志 SHA。没有上传参考补丁、原始 solution 日志或私有配置。

这些结果支持“本机执行条件需要进一步排查”，仍不能唯一确定是 Docker／WSL、依赖、固件、硬件还是其他条件。云端六次通过也不证明永不波动。公开 CPython 问题中也有维护者建议先换机器复核、原报告者随后确认在另一台机器通过的记录；这只能作为诊断方法参考，不能代替本机因果证据。[CPython 问题记录](https://github.com/python/cpython/issues/149692)

## 当前处置

- 停止本机资格批次，完整保留已经得到的官方分数。
- 在结果根目录写入 invalid 原因，不将该批用于正式模型实验。
- 中断时的未完成试验记未知；其容器日志已经保留，专属容器和网络已确认清理。
- 正式开发与最终验收仍需稳定 Linux 执行资源，不降低原定 N，不偷偷删除失败。
- 两次模型校准的旧分数保留，不直接把这些 0 解释为全部来自产品能力；已有真实 patch 可以在独立环境另行复核。

已有 patch 的 [固定云端复核](https://github.com/saya-ch/sayacode-bench/actions/runs/39740758231) 也已完成：qutebrowser 同补丁三次通过；Ansible 同补丁三次失败、同 VM 参考解三次通过、空解失败。六次补丁都成功应用，十次原生结果和不可变镜像均核实。具体来源与边界见 [校准记录](calibration.md)。

目前完整模型对照尚未开始，不能给出可信的最终成功率或调优收益。

随后本机独立 Ubuntu WSL2／Engine 也完成了固定八次诊断：qutebrowser 参考解为 1/0/0，OpenLibrary 为 1/1/1，空解均为 0。网络探针通过，实际 Engine、存储与旧 Desktop 不同，但仍共享原 WSL 内核和硬件。原来各批 Hypothesis 随机种子没有固定一致，跨宿主差异仍可能涉及随机输入等因素；后续固定种子对照单列，不能从目前结果唯一归因 Docker Desktop、WSL 内核或硬件。见 [WSL 诊断](wsl-diagnostic.md)。

## 原生 Linux 网络门禁

[独立实际探针](https://github.com/saya-ch/sayacode-bench/actions/runs/39740819102) 已通过，未使用模型。安装与验证阶段可以访问本地 mock 和已缓存公网 IP；Agent 阶段只能经过固定网关调用指定模型路径，直接宿主 TCP、公网 TCP、其他路径、GET、查询参数与 CONNECT 均被阻断。完全断网阶段也不能访问网关。

探针结束后，独立 Docker 查询确认主容器、网关容器、隔离网络和本次公共网络均不存在。最小证据见 `reports/native-linux-network-probe-20261022/`。这补齐原生 Linux 的实际执行证据，但不表示任何 Linux 宿主都自动通过，也不替代正式执行机上的资格检查。内存另有 swap 配额，磁盘容量没有硬隔离；资源偏离仍需在正式报告中保留。
