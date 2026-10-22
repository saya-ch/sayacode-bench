# 真实分片链路的合成 smoke fixture

本 fixture 不来自 SWE-bench、Terminal-Bench 或真实用户任务，也不评价 DeepSeek。模型回复为本机确定性 Anthropic HTTP/SSE stub，usage 数字用于验证计量传播，不能当作真实供应商 token 或费用。

真实执行部分包括：固定原始生产 wheel、LangChain/LangGraph 图、文件工具、Harbor Job、Docker、实际资源观测、一次 oracle、两次独立 source 与原始官方 PatchReplayAgent 的 pristine replay、跨片前缀和归并。一次 oracle 只用于建立本 smoke 的真实 runtime，不构成正式三加一资格检查。

基础 Python 镜像与既有基础设施 smoke 使用同一 digest。派生镜像安装 Git、初始化固定 `/app` HEAD；测试会构建一个独占镜像 tag，并将 task 模板占位值替换为这个实际 tag。两个 source 和两个 pristine 均从同一原始镜像启动，oracle 的答案不会写回镜像。

默认跳过真实 Docker 测试。只有显式设置以下环境变量才执行：

```text
SAYACODE_BENCH_SHARD_SMOKE=1
SAYACODE_BENCH_SMOKE_WHEEL=<原始冻结 wheel 路径>
SAYACODE_BENCH_SMOKE_REQUIREMENTS=<原始冻结 requirements 路径>
SAYACODE_BENCH_SMOKE_OUTPUT=<尚不存在的独占输出目录>
```

原件 SHA 对照公开 `reproduction/identity.json`，不会自动下载不同 wheel 或导出替代依赖。测试不读取任何真实供应商密钥，profile 仅包含固定 dummy key，唯一模型上游为当前宿主的本地 HTTP stub。Linux 宿主地址选择复用真实网络探针的默认桥检查。

测试会获取固定公开源码缓存，以原始字节复制其官方 `v2/tooling`。只将 `study.fetch_source` 映射为合成 task 目录，不 mock 生产 App、原生图、单次执行、replay 或 native validators。`benchmark` 字段仅用于选择既有 SWE pristine 适配路径，`phase=calibration`、合成 revision、scope 和不具备正式资格的断言阻止其被当作 SWE 成绩。

真实执行环境尚需实测；代码和默认跳过不能当作 Docker 已通过。失败时保留完整原生现场和 stub 元数据，仅清理本次拥有的镜像 tag，不 prune 用户 Docker。

两个分片在同一 Linux 宿主内顺序执行。本 smoke 不覆盖跨虚拟机工件归档与恢复、GitHub DAG 调度或宿主 cohort 守门；这些仍需独立验证。
