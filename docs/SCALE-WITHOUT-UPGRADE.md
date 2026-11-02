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

> **实测更正（重要）**：`docker_data.vhdx` **名义 185GB、内部 used≈136GB（其中 40 题 SWE-bench 镜像本身约 119GB + 其他 ~17GB）、内部空闲≈49GB**。**注意：那 109.9GB「可回收」主要就是 40 题镜像本身，扩样要用，不能 prune 掉。** 真正的路径是：**保留 40 题镜像，利用内部 49GB 空闲做「每片 20 题」的滚动**（20 题镜像实测约 30–40GB < 49GB），跑完一片删一片再拉下一片，峰值 ≈136+35=171GB < 185GB 名义，**C: 盘不变、也不需要 compact**。compact（管理员）只是把内部空闲还给 C:（+49GB），可选；跑完 40 题后删其镜像会更宽松。

## 三、滚动镜像（控制磁盘峰值）

即使不 compact，也不该同时保留 100 个镜像。做法：
- **分片**：5 片 × 20 题。
- 每片只拉当前 20 题的镜像（实测约 30–40GB），跑完 `docker rmi` 删除，再拉下一片。
- 任一时点 **vhdx 内部占用峰值 ≈136+40=176GB < 185GB 名义**（C: 盘不变）；结果与 cache 另计 < 15GB。

## 四、内存（15.6GB 固定，无法升）

- 并发只能 **2**（验证器峰值 2.26GB/容器 + Docker VM 7GB）。
- 跑批前**关闭桌面应用**（ChatGPT/WorkBuddy/codex，v2 实测释放 ~2.4GB），把宿主空闲稳在 3–4GB。
- 时间代价：600 trial ≈ **4 天**（若并发 4 则 ~2 天）。

## 五、扩样 100 题执行计划（不升级）

| 步骤 | 动作 | 磁盘峰值 |
|---|---|---|
| 0 | **保留 40 题镜像**，只 `docker builder prune -f`；compact vhdx 可选（+49GB 给 C:） | C: 不变（compact 则 +49GB） |
| 1–5 | 每片 20 题：拉镜像 → 20×2×3=120 trial（并发 2）→ verify → 记结果 → `docker rmi` | 内部峰值 <185GB |
| 合计 | 600 trial，约 **4 天** | 峰值 <30GB |

## 六、分级结论（在「不升级」约束下）

| 目标 | 不升级能否做 | 条件 |
|---|---|---|
| 40 题 A/B、多模型 40 题 pilot | ✅ | 直接跑（1–3 天） |
| 60 题扩样 | ✅ | 滚动镜像（不必 compact） |
| **100 题扩样** | ✅（约 4 天） | **保留 40 题 + 每片 20 题滚动**（20 题≈35GB < 内部空闲 49GB）；C: 不变，compact 可选 |
| 并发 4–6 提速 | ❌ | 内存 32GB（无法升） |

## 七、一句话

**「硬件升不了」不等于「扩样做不了」——40 题镜像已占 vhdx 大部分，但它本就该保留；真正要做的只是「保留 40 题 + 每片 20 题滚动」（内部还剩 49GB 够一片），C: 盘不用变大。配「并发 2」，100 题约 4 天。若要 C: 也腾空，再 compact 一次（管理员，+49GB）。真正不可解的只有「并发提速」——那需要内存，是时间问题不是可行性问题。**
