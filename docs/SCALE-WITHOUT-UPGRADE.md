# 不升级硬件的扩样方案（2026-11-03）

> 前提：不买内存、不买磁盘。结论：**扩样 100 题仍然可行**，关键是「回收 Docker 空间 + 滚动镜像」，内存只影响时间。

## 一、关键发现：Docker 内有 109.9GB 可回收

```
TYPE            TOTAL   ACTIVE   SIZE       RECLAIMABLE
Images          58      1        129.1GB    109.9GB (85%)
Containers      1       1        6.1MB      0B
Local Volumes   5       1        3.66GB     3.48GB (95%)
Build Cache     88      0        3.22GB     2.21GB
```

- 58 个镜像里 **110GB 是未使用的旧批次/悬空镜像**（v1、musllinux、旧 base 等）。
- 这些**不需要买盘**，`docker image prune -a` 就能删（删后 vhdx 内部空闲，但**vhdx 不自动缩容**，需 compact）。

## 二、三步回收（无需硬件）

1. **prune（普通权限即可）**：
   ```powershell
   docker image prune -a -f        # 删未使用镜像（会删旧批次与 dangling；40 题镜像跑批时可按需重拉）
   docker volume prune -f
   docker builder prune -f
   ```
   预期：Images 129GB → ~19GB。
2. **compact vhdx（管理员一次）**：
   ```powershell
   wsl --shutdown
   # diskpart: select vdisk file="C:\...\docker_data.vhdx"; compact vdisk
   # 脚本：C:\sb\hard\v2\logs\compact-docker-vhdx.ps1
   ```
   预期：vhdx 名义 190GB → ~25GB，**C: 空闲 +100~160GB**。
3. 结果：C: 空闲可从 61GB 升到 **150GB+**，远超扩样所需的 ~115GB。

> 若不做第 2 步（无管理员）：vhdx 内部有约 60GB 空闲可复用，扩到 **60 题可行**，100 题会紧张。

## 三、滚动镜像（控制磁盘峰值）

即使不 compact，也不该同时保留 100 个镜像。做法：
- **分片**：5 片 × 20 题。
- 每片只拉当前 20 题的镜像（~20GB），跑完 `docker rmi` 删除，再拉下一片。
- 任一时点磁盘峰值 < 30GB（20GB 镜像 + 15GB 结果 + cache）。

## 四、内存（15.6GB 固定，无法升）

- 并发只能 **2**（验证器峰值 2.26GB/容器 + Docker VM 7GB）。
- 跑批前**关闭桌面应用**（ChatGPT/WorkBuddy/codex，v2 实测释放 ~2.4GB），把宿主空闲稳在 3–4GB。
- 时间代价：600 trial ≈ **4 天**（若并发 4 则 ~2 天）。

## 五、扩样 100 题执行计划（不升级）

| 步骤 | 动作 | 磁盘峰值 |
|---|---|---|
| 0 | `docker image prune -a` + volume/builder prune + compact vhdx | 回收 100GB+ |
| 1–5 | 每片 20 题：拉镜像 → 20×2×3=120 trial（并发 2）→ verify → 记结果 → `docker rmi` | <30GB |
| 合计 | 600 trial，约 **4 天** | 峰值 <30GB |

## 六、分级结论（在「不升级」约束下）

| 目标 | 不升级能否做 | 条件 |
|---|---|---|
| 40 题 A/B、多模型 40 题 pilot | ✅ | 直接跑（1–3 天） |
| 60 题扩样 | ✅ | 滚动镜像（不必 compact） |
| **100 题扩样** | ✅（4 天） | **prune + compact 一次**（回收 100GB+） |
| 并发 4–6 提速 | ❌ | 内存 32GB（无法升） |

## 七、一句话

**「硬件升不了」不等于「扩样做不了」——先把 Docker 里 110GB 旧镜像 prune 掉、compact 一次，磁盘就够了；再配「分片 + 滚动镜像 + 并发 2」，100 题约 4 天能跑完。真正的不可解只有「并发提速」，那需要内存，但那是时间问题不是可行性问题。**
