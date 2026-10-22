# 在稳定 Linux 主机执行完整研究

本文给出主机准备、私有模型连接、门禁、正式运行和恢复的操作顺序。目标仍为预注册的 8 个开发任务与 24 个最终任务，不因迁移主机减少任务数。具体重复、候选和额度以首次正式模型运行前冻结的清单为准。

相关设计：[研究协议](protocol.md)、[环境资格门禁](fixture-gates.md)、[生产基线重建](../reproduction/README.md)、[候选假设](hypotheses.md)。

## 已验证与待执行

| 项目 | 当前边界 |
| --- | --- |
| Harbor 0.24.0、官方任务与薄适配 | 已有固定源码、依赖和容器执行证据 |
| Docker Desktop 网络探针 | 已真实运行，包含缓存宿主 IP 的 TCP 检查与独立清理确认 |
| 原生 Linux 网络探针 | GitHub Actions 运行 `39740819102` 实际成功；这不替代未来正式主机上的实际探针 |
| 无模型 oracle／nop upstream | 已统一为明确的 `http://127.0.0.1:9/v1/messages` sink，不依赖 Windows 宿主别名，不访问真实模型 |
| Linux 校准工件复核 | 运行 `39740758231`：qutebrowser 已捕获补丁三次通过，Ansible 补丁三次失败、gold 三次通过、nop 失败；全部无模型，不是新增 Agent 尝试 |
| 本机独立 Ubuntu WSL2 候选 | 已安装并核实独立 Engine／ext4，网络探针实际通过；固定八次诊断未达到就绪门槛，见 [WSL 记录](wsl-diagnostic.md) |
| 用户提供的正式 Linux 主机 | 尚待确定；本文没有连接任何已有 SSH 主机、上传凭据或创建付费资源 |
| 完整正式模型比较 | 尚未执行；校准、参考解和网络探针不是最终研究成绩 |

**当前明确边界：尚无通过全部就绪门禁的正式执行环境。** 用户已授权本机独立 WSL2 诊断，实际进展见上述记录；如果采用其他 Linux 主机，再按本文执行目标宿主门禁、校准与正式研究。8 个开发／24 个最终任务目标保持，已有云端复核不能直接替代目标宿主的资格事实。

## 一、主机与目录

建议使用原生 x86_64 Linux、可访问的 Docker Engine／Compose v2、cgroup v2，以及持续供电和稳定网络。选择的单题官方预算为 1 CPU／4 GiB 时，还需为宿主、网关和环境安装留余量；4 核／16 GiB 是操作建议，不是公开基准统一最低要求。

镜像占用随任务而变。建议准备至少 200 GiB 空闲数据空间，仍持续执行已有的 12 GiB 空闲停止门禁；这个建议不能保证缓存 64 个候选永不耗尽空间。Docker 环境没有声明每题存储硬配额，保持这一限制披露。

在用户确定主机和访问方式后执行以下只读检查：

```bash
uname -m
uname -r
docker version
docker compose version
docker info --format '{{json .}}'
free -h
df -h
```

需要确认 Linux／amd64、实际 CPU／内存／swap、Docker 数据目录所在分区、cgroup 和存储驱动。不要通过隐式模拟执行 amd64 镜像来伪装成原生相同环境。Docker 安装与账号权限依据用户选定发行版处理，不在未知主机上自动改 daemon 或用户组。

建议目录相互分离：

```bash
BENCH_CODE="$HOME/sayacode-bench"
BENCH_DATA="$HOME/sayacode-bench-data"
BENCH_PRIVATE="$HOME/.config/sayacode-bench"
mkdir -p "$BENCH_DATA/artifacts" "$BENCH_DATA/results"
mkdir -p "$BENCH_PRIVATE"
chmod 700 "$BENCH_PRIVATE"
```

源码放在 `BENCH_CODE`，源缓存放在 `BENCH_DATA/cache`，生产工件放在 `artifacts`，输出放在 `results`。私有连接不放进结果目录或源码归档。

## 二、安装固定输入

从固定提交安装，使用新目录，不覆盖现有 checkout：

```bash
BENCH_COMMIT='<本次冻结的完整评测仓库提交号>'
git clone --no-checkout https://github.com/saya-ch/sayacode-bench.git "$BENCH_CODE"
git -C "$BENCH_CODE" checkout --detach "$BENCH_COMMIT"
cd "$BENCH_CODE"
uv --version
uv sync --frozen --python 3.13
uv run --no-sync sayacode-bench --help
uv run --no-sync pytest -q
```

实验使用 uv 0.12.5 与已提交锁文件。Host Python 与 Docker／内核版本记录为主机条件；产品在任务容器中使用适配器固定的独立 Python 3.13.7，不覆盖任务本身用于官方测试的 Python。

优先转移已保存的非秘密原始 wheel 和 requirements 文件，逐字节核对 [identity.json](../reproduction/identity.json)：

```text
sayacode-3.2.4-py3-none-any.whl
7892afcd50bd0ee786ed3ea5ba73015af32da11cd3eeff5474ce7e64d039dffe

requirements.txt
9eab06fb395d7b9bb84e14bfea83b79b4ab66d904c941c3b1606d39ed9712073
```

requirements 已包含 Linux／Windows 的环境标记。原文件的导出注释含旧路径；Linux 仍使用原始字节，以保持输入身份。若重新导出或清理注释，必须作为新工件在正式开发前统一冻结。重建 wheel 也必须以实际 SHA 为准，不能只核对版本号。

主机确定后，转移评测源码、公开选样、原始 wheel／requirements 和公开生产源码归档。旧 Windows 原始记录另作证据保存，不作为 Linux 活动结果目录继续写入。

## 三、私有模型连接

两种已授权路由继续使用同一规范模型 `DeepSeek-V4.1-Flash`。接口差别不是研究对照因素。每个任务配对块固定连接；连接参数在 Linux cohort 开始前冻结。

### 路径 A：Linux 直接访问已授权接口

主机确定后，在该机器上建立权限为 0600 的私有 profile，使用已验证的 Messages 协议、准确 base URL／路由模型 ID、密钥与统一模型参数。密钥不出现在命令行、Git 或公开日志。

当前研究声明的窗口为 65,536、最大输出 8,192、摘要比例 0.8、保留 12 条消息、上下文编辑关闭。其他参数继承已冻结配置，不能借迁移主机改变候选条件。按次接口使用已授权付费预算与价格快照；不把订阅用量估算为零费用。

### 路径 B：Windows 反代的回环 SSH 隧道

这条路径让真实模型凭据继续留在 Windows 反代。需要 Windows 与 Linux 在实验期间保持连接；SSH 中断属于外部故障，已有停止门禁仍生效。

在用户确定 Linux 访问方式并核验主机身份后，从 Windows 运行：

```powershell
ssh -NT `
  -o ExitOnForwardFailure=yes `
  -o ServerAliveInterval=30 `
  -o ServerAliveCountMax=3 `
  -o StrictHostKeyChecking=yes `
  -R 127.0.0.1:18787:127.0.0.1:8787 `
  <linux-user>@<linux-host>
```

远端 18787 只绑定 Linux 回环。任务网关容器不能直接访问宿主回环，需要一个只在 Docker 私有桥地址监听的固定 HTTP 转接。先读取默认桥 Gateway，并校验为唯一 RFC1918 IPv4：

```bash
docker network inspect bridge --format '{{json .IPAM.Config}}'
BENCH_BRIDGE_IP='<上面实际的私有 IPv4 Gateway>'
uv run --no-sync python - "$BENCH_BRIDGE_IP" <<'PY'
import ipaddress, sys
address = ipaddress.ip_address(sys.argv[1])
assert address.version == 4 and any(address in ipaddress.ip_network(cidr) for cidr in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'
))
PY
```

将下面配置中的 `<BRIDGE_IP>` 换成已校验地址，保存为私有目录下的 `relay.conf`。它不含密钥，仅开放固定 POST 路径，不提供通用 HTTP 转发：

```nginx
worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 128; }
http {
    access_log off;
    client_body_temp_path /tmp/client;
    proxy_temp_path /tmp/proxy;
    fastcgi_temp_path /tmp/fastcgi;
    uwsgi_temp_path /tmp/uwsgi;
    scgi_temp_path /tmp/scgi;
    server {
        listen <BRIDGE_IP>:18788;
        client_max_body_size 64m;
        location = /v1/messages {
            if ($request_method != POST) { return 405; }
            if ($args != "") { return 400; }
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_buffering off;
            proxy_request_buffering off;
            proxy_next_upstream off;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
            proxy_pass http://127.0.0.1:18787/v1/messages;
        }
        location / { return 404; }
    }
}
```

Linux 上可复用项目固定的 nginx 镜像运行该转接；这是一次实验的传输设施，不是 Agent Server：

```bash
chmod 644 "$BENCH_PRIVATE/relay.conf"
docker run --detach --name saya-private-model-relay \
  --network host --read-only --user 101:101 --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 128m --cpus 0.25 \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m,mode=1777 \
  --mount "type=bind,src=$BENCH_PRIVATE/relay.conf,dst=/etc/nginx/nginx.conf,readonly" \
  nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236 \
  nginx -g 'daemon off;'
```

真实任务里的本机连接 profile 将 `base_url` 设为 `http://<BRIDGE_IP>:18788`，使用已验证的 `deepseek/deepseek-v4.1-flash` 路由 ID。`api_key="proxy-managed"` 是反代支持的非秘密标记；真实凭据仍由 Windows 反代持有。Linux profile 依然按私有文件保存，参数与其他连接一致。

接口的流式往返与工具调用必须在正式模型研究前小规模验证，计入校准与用量账本。此手册中的 SSH／relay 命令尚未在用户正式主机运行，不能将语法准备当成链路已经验证。

## 四、新 Linux cohort 的门禁

在最终主机实际运行网络探针，并保留 cleanup_confirmed 和代码身份：

```bash
cd "$BENCH_CODE"
uv run --no-sync sayacode-bench doctor --output "$BENCH_DATA/results/docker-doctor.json"
SAYACODE_BENCH_DOCKER_TESTS=1 \
SAYACODE_BENCH_PROBE_OUTPUT="$BENCH_DATA/results/network-probe.json" \
uv run --no-sync pytest tests/test_network.py::test_real_docker_network_isolation -q
```

继续使用公开初始 selection 的完整候选池、seed 和校准修复组排除规则。在 Linux 的新输出目录执行资格检查：

```bash
uv run --no-sync python scripts/qualify_fixtures.py \
  --selection studies/primary-selection-v1.json \
  --cache "$BENCH_DATA/cache" \
  --output "$BENCH_DATA/results/primary-fixtures-linux-v1" \
  --oracle-repeats 3 --max-candidates 64
```

不把 Windows 失败 fix 缓存带入这个新 cohort 当成 Linux 资格事实。Oracle／nop 的固定失败、替补版本和实际镜像都在新主机重新记录。若 64 个候选内未填满原目标，保持 incomplete；主机改变本身不是修改 N 的理由。

生产 wheel 在原生主机的安装、真实图与无模型 HTTP mock 往返、非 root 日志权限、Shell 取消也需要实际验证。已有 Linux 容器执行证据说明依赖链可工作，但不能替代新宿主 bind mount／权限／网络的 smoke。

## 五、冻结和完整运行

以下变量指向已核对的实际文件；预算值和源提交在校准后填定，不通过示例创建额度授权：

```bash
WHEEL="$BENCH_DATA/artifacts/sayacode-3.2.4-py3-none-any.whl"
REQUIREMENTS="$BENCH_DATA/artifacts/requirements.txt"
SELECTION="$BENCH_DATA/results/primary-fixtures-linux-v1/selection.json"
SANITY="$BENCH_DATA/results/primary-fixtures-linux-v1/sanity.json"
DEV_MANIFEST="$BENCH_DATA/results/dev-linux-v1.manifest.json"
DEV_OUTPUT="$BENCH_DATA/results/dev-linux-v1"
```

冻结 8 题、3 配置、2 次重复的开发阶段；`<...>` 必须由实际校准与已有授权决定：

```bash
uv run --no-sync sayacode-bench freeze --phase dev \
  --selection "$SELECTION" --sanity "$SANITY" \
  --network-probe "$BENCH_DATA/results/network-probe.json" \
  --seed '<固定试验顺序seed>' --repeats 2 \
  --reported-token-limit '<已冻结的报告token阈值>' \
  --wheel "$WHEEL" --requirements "$REQUIREMENTS" \
  --variant baseline=studies/baseline.json \
  --variant diagnostic=studies/diagnostic.json \
  --variant focused=studies/focused.json \
  --connection local="$BENCH_PRIVATE/local.json" \
  --output "$DEV_MANIFEST"
```

若计划使用第二连接，冻结与执行两处都增加 `--connection remote=...`，并提前声明接口轮转与付费预算。当前执行器按重复编号选择连接，同一配对块保持一致。不要在执行中更改 profile 来绕过服务停止；新连接或预算事实需要单独记录。

在持续会话管理器中启动，SSH 终端断开不结束研究进程：

```bash
tmux new -s sayacode-dev
cd "$BENCH_CODE"
uv run --no-sync sayacode-bench run \
  --manifest "$DEV_MANIFEST" --cache "$BENCH_DATA/cache" \
  --output "$DEV_OUTPUT" --private-home "$BENCH_PRIVATE" \
  --wheel "$WHEEL" --requirements "$REQUIREMENTS" \
  --variant baseline=studies/baseline.json \
  --variant diagnostic=studies/diagnostic.json \
  --variant focused=studies/focused.json \
  --connection local="$BENCH_PRIVATE/local.json"
```

进入 tmux 前设置的路径变量应使用 `export` 或在新会话中重新定义。tmux 是进程存活措施，不是断电恢复或自动重试服务。

开发完整结束后签收，不用最终任务重新挑候选：

```bash
uv run --no-sync sayacode-bench lock-candidate \
  --manifest "$DEV_MANIFEST" --records "$DEV_OUTPUT/records.jsonl" \
  --variant baseline=studies/baseline.json \
  --variant diagnostic=studies/diagnostic.json \
  --variant focused=studies/focused.json \
  --output "$BENCH_DATA/results/candidate-linux-v1.json"
```

之后以同一 wheel／依赖、完整资格证据和 `--candidate-lock` 冻结最终 24 题：选择不同候选时使用 baseline＋selected 的 holdout，保留 baseline 时使用单组 validation。默认继续每题两次；不能为了缩短时间临时改为一次或跳过失败。

## 六、当前恢复能力与命令

当前 `sayacode-bench run` 对完整记录跳过，对已有完整 source job 且输入相同的情况复用原生结果。再次执行上面的同一条 run 命令，只有满足下列条件才可继续未开始任务：

- 相同主机、相同目录、相同冻结清单与输入文件身份。
- 没有 `abort.json`，所有已写记录均 `record_complete=true`。
- 没有需要人工处置的未收尾 job；模型连接与代码没有改变。

中止批次保留原始事实，建立明确的复验批次。不要删除中止标记或改写失败记录来强行恢复。正常模型错误、人工强停或资源止损可能留下 abort，不能将“有 checkpoint 文件”宣传为全部阶段都可直接续跑。

Harbor 0.24 本身提供：

```bash
uv run --no-sync harbor jobs resume --job-path '<已有官方job目录>'
```

它恢复的是 Harbor job，不保证 SAYACODE 同一个图节点的副作用已经确认；`--filter-error-type` 还会移除错误 trial 的选择状态。正式模型任务应由薄控制器核对原始证据后处置，不直接把该命令当作无条件安全续写。无模型 oracle／replay 的诊断恢复也保留旧 job，确认旧资源已经清理。

### replay_pending 的精确窗口与最小补齐建议

| 中断位置 | 当前行为 | 可行的薄恢复 |
| --- | --- | --- |
| source normalized 已完成，总 records 尚未写入 | 同名 job 输入相同可复用，不会重新调用模型 | 沿用现有缓存检查 |
| 已写 source 的 `record_complete=false`，尚未开始 replay | `remaining_order` 当前拒绝启动 | 核对 source 完整原生结果、原 patch SHA、输入身份与无在途进程后，只继续官方 verifier |
| replay 已完成但总 records 尚未原子更新 | 仍可能被未完成标记阻止 | 读取已经确认的 replay normalized／raw 证据，原子归并，不重新运行模型或挑选更高 reward |
| replay job 本身未收尾 | 现有执行入口拒绝静默重跑 | 先收集并核对已有有效判分；仅对无法确认完成的验证阶段按预注册恢复规则创建新 pristine 环境，保存全部旧尝试 |
| 模型或写工具仍在途，宿主退出／断电 | 不能从检查点推断副作用没有发生 | 保存不确定标记与账本，不自动重放写入；单独制定整块复验策略 |

最小扩展可以是一个显式 `recover-verifier` 操作：只读检查 source 与 replay 状态，输出恢复计划；只复用已确认 source 结果和唯一补丁，调用现有官方重判入口，并按原 request/source job 身份去重用量。它不需要新 Agent Runner、队列或 worker 服务。上述 replay_pending 扩展尚未实现，不能在手册中当成已经可用的 CLI。

## 七、迁移与报告的边界

跨机迁移建立新的 Linux cohort。当前 manifest／receipt／JobConfig 包含绝对路径，私有 profile 地址与原生 runtime 也会变化，复制 Windows 活动目录不构成透明恢复。

完整保留旧校准、无效资格与失败费用；新 cohort 重用原任务池、目标数量和预定候选方法，重新建立主机门禁、校准与冻结身份。报告同时列 host 条件、Docker／内核、实际镜像、资源限制、网络实现、连接、版本和服务故障。

与主机无关的剩余工程项是恢复窗口的离线故障注入、最后一条 fatal 服务错误门禁，以及工件传输和私有 relay 的无模型校验。它们由对应实现与 CI 记录确认，不能在手册中标为已完成。本文仅提供执行和暂停边界，不创建新的执行器或云资源；目标主机确定前不启动正式模型批次。
