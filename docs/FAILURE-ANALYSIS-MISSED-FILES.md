# 失败模式拆解：主要矛盾是「漏改」而非「不敢下手」（2026-11-08）

> 三轮实验都在猜「提示词是不是太长」，从没看过失败的 patch 长什么样。
> 这次把 40 个 trial 的产物全拆了。

## 1. 失败分布（40 trial，通过 26 = 65%）

| 失败类型 | 数量 | 占失败 | 说明 |
|---|---:|---:|---|
| **漏改** | **8** | **57%** | 改对了主要文件，漏掉关联文件 |
| 空 patch | 4 | 29% | 完全没动手；其中 2 个是 gold 改 8–12 文件的大题 |
| 内容错 | 2 | 14% | 文件选对了，写法不对 |
| 合计失败 | 14 | 100% | |

**这直接否定了前两轮的方向选择**：`ExploreBudgetMiddleware` 和 v2 提示词都在治「不敢下手」，
但空 patch 只占 29%（实际真正的「不敢下手」只有 2 个），54% 的失败是漏改。

---

## 2. 漏改的具体模式

8 个漏改案例全部是「改对了核心文件，但没同步同一功能的其他层面」：

| 仓库 | gold 文件数 | 模型文件数 | 漏掉的关键文件 | 漏的层面 |
|---|---:|---:|---|---|
| navidrome | 6 | 3 | `db/migration/20221219112733_add_album_image_paths.go` | **数据迁移** |
| navidrome | 6 | 2 | 同上 + `scanner/refresher.go`、`scanner/tag_scanner.go` | 数据迁移 + 调用方 |
| element | 9 | 4 | `src/i18n/strings/en_EN.json` | **国际化文案** |
| element | 9 | 3 | `res/css/.../_FilteredDeviceList.pcss`、`_AccessibleButton.pcss` | **样式** |
| element | 9 | 4 | `src/components/views/elements/AccessibleButton.tsx` | 组件契约 |
| flipt | 12 | 6 | `internal/cmd/grpc.go`、`internal/server/evaluation/ofrep_bridge.go` | **调用链上游** |
| vuls | 3 | 2 | `report/stdout.go` | **输出层** |
| ansible | 5 | 4 | `lib/ansible/galaxy/collection/galaxy_api_proxy.py` | 代理层 |
| qutebrowser | 4 | 4 | `doc/help/settings.asciidoc` | 文档（唯一只漏文档的）|

**归纳成四类关联**：

1. **数据模型变了 → 要有数据库迁移**（navidrome）
2. **界面变了 → 要有 i18n 文案 + CSS**（element）
3. **接口/行为变了 → 调用方要跟着改**（flipt、ansible、vuls）
4. **配置项变了 → 文档要更新**（qutebrowser，但这类不影响测试）

前 3 类都会导致隐藏测试失败。第 4 类不影响评分。

---

## 3. 空 patch 的两种成因

| trial | gold 规模 | 模型行为 | 成因 |
|---|---|---|---|
| flipt-756f00f | 8 文件 / 155 行 | 编辑 0 次，40 次工具调用 | **任务太大，模型只读不写** |
| flipt-9d25c18 | 12 文件 / 881 行 | 编辑 0 次，51 次工具调用 | 同上（另一个 trial 跑满 50 分钟超时）|
| navidrome | 6 文件 / 87 行 | 编辑 8 次但 patch 空 | 改被回退了？ |
| navidrome | 6 文件 / 87 行 | 编辑 5 次，patch 2478B | 改错位置 |

真正「不敢下手」的只有 flipt 那 2 个，而且都是 gold 改 8+ 文件的大题。

---

## 4. 验证行为：不是主要矛盾

| | 改完后跑过命令 | 没跑 | 合计 |
|---|---|---|---|
| 失败 | 11 | 3 | 14 |
| 通过 | **26** | **0** | 26 |

Fisher 精确 **p = 0.0368**。

「没验证」与「失败」强相关，但**只有 3 个失败 trial 没验证**，其余 11 个验证了仍失败。
所以「加验证机制」最多能救 3 个（其中 2 个还是压根没动手的），
**不能作为主攻方向**。

---

## 5. 下一步：针对「漏改」

### 要验证的假设

**如果给模型一份「改动影响面检查清单」，漏改率会下降。**

检查项（对应四类关联）：

1. 我改了数据结构或字段 → 需要数据库迁移吗？
2. 我改了用户可见的文案 → 需要加/改 i18n 条目吗？
3. 我改了界面组件 → 需要同步样式吗？
4. 我改了函数签名或行为 → 全仓库里还有谁调用它？
5. 我改了配置项 → 需要改文档或示例配置吗？

### 实验设计（按 n≥30 的教训）

| 项 | 值 |
|---|---|
| 题集 | 20 题（复用 `sample-20.json`，镜像已就位）|
| 重复 | 2（20 × 2 = 40 配对，满足 n≥30）|
| 组 | main（3.3.0）vs 加了影响面清单的变体 |
| 主指标 | **漏改率**（模型 patch 的文件覆盖 gold patch 文件的比例）|
| 次指标 | 通过率、空 patch 数 |
| 预期 | 漏改率明显下降；通过率若提升需 p<0.05 才可宣称 |

**关键：主指标用「漏改率」这个连续量**，而不是只看通过率——
它抗噪声，且直接对应观察到的失败模式。

### 不建议现在做的

- ❌ 加「改完必须验证」：只能救 3 个，且其中 2 个会因「没动手」而无效
- ❌ 再调提示词长度：已被 v1/v2 证伪
- ❌ 加运行时 middleware：ExploreBudgetMiddleware 的副作用教训还在

---

## 6. 数据与脚本

| 项 | 路径 |
|---|---|
| 40 trial 的失败分类 | `C:\sb\tmp\failure_modes.py` |
| 验证行为分析 | `C:\sb\tmp\verify_after_edit.py` |
| gold 对比 | `C:\sb\tmp\diff_vs_gold.py` |
| 对比样本（14 组 model/gold patch）| `C:\sb\hard\ab-ctx\failure-diffs\` |
| 数据集（731 题，含 gold patch）| `C:\sb\tmp\hard\cache\swe-bench-pro-v2-*\helper_code\sweap_eval_full_v2.jsonl` |
