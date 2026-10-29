# 模型路由漂移：评测可比性的根本风险（2026-10-29）

> 发现：Magpie 是模型路由，同一请求别名会落到**本质不同的后端模型**。这不是 temperature 能解决的，它直接威胁评测的同一性。

## 一、实测（最近 4000 次调用）

请求别名 `group/auto-deepseek-v4-1-flash`（3924 次）：

| 实际 served | provider | 占比 | avgCredits | avgOutput |
|---|---|---:|---:|---:|
| deepseek-v4.1-flash | workbuddy | 43% | 0.147 | 611 |
| **glm-5.3-flash** | workbuddy | **40%** | 0.534 | 345 |
| deepseek/deepseek-v4.1-flash | commandcode | 6% | 0.000 | 590 |
| deepseek-v4.1-flash | workbuddy-ai | 6% | 0.000 | 629 |
| DeepSeek-Flash | qoder | 4% | 0.000 | 769 |

请求别名 `auto/deepseek-v4.1-flash`（35 次）：57% → `deepseek/deepseek-v4.1-flash`，43% → `glm-5.3-flash`。

## 二、含义

1. **同一"模型名"下混入了至少两种本质不同的模型**（DeepSeek 与 GLM）与 4 个 provider。40% 的运行并不是我们声称的模型。
2. **这很可能就是"同题一过一败、token 大幅波动"的主因**——不是 temperature，而是路由到了不同后端。
3. **跨批次、单次结论的可比性受损**：不同批次命中的模型比例不同，结果不可直接比较。此前所有探索性数字（holdout 通过率、token 控制、提示词翻盘）都受此污染，**只能作为方向性观察，不能作为可比成绩**。

## 三、修复（比 temperature 更根本）

1. **pin 具体来源**：评测请求不要用会漂移的组路由别名，改用能固定到单一 provider/模型的名称（如 `deepseek/deepseek-v4.1-flash` 走 commandcode）；先用少量探测确认 served 稳定。
2. **记录实际 served**：每个 trial 记录 usage 的 `served`/`provider`，评测前统计 served 分布，**分布不唯一则本轮结果标为"未固定来源，不可比"**。
3. **加路由校验门禁**：正式跑前后各取 N 次探测，served 必须一致，否则中止。
4. temperature 仍应固定（可复现），但它是次要项；**来源同一性优先**。

## 三之补充、pin 实测（2026-10-29）

`GET /v1/models` 显示模型名有两类：会漂移的 `auto/...`、`group/...`，以及带具体 provider 前缀的 `<provider>/<model>`。小样本探测（每名 2 次）：

| 模型名 | 实测 served / provider | 说明 |
|---|---|---|
| `auto/deepseek-v4.1-flash` | workbuddy-ai | 短请求看似稳定，但历史 3924 次实测 **40% 漂到 glm-5.3-flash**（长对话/负载下漂移） |
| **`workbuddy/deepseek-v4.1-flash`** | workbuddy | **2/2 稳定**，pin 可用 |
| `commandcode-plan/deepseek/deepseek-v4.1-flash` | HTTPError | 需额外认证/额度，暂不可用 |
| `bailian/...`、`sensenova/...` | HTTPError | 同上 |

**建议**：评测 profile 的 `model_id` 从 `auto/deepseek-v4.1-flash` 改为 **`workbuddy/deepseek-v4.1-flash`**，并在每轮正式跑前后各探测 8 次 served 以确认未漂移。注意这只是小样本验证，正式使用前需按门禁再确认。

**对既有结论的影响**：此前所有探索性数字（holdout 通过率、token 控制、提示词翻盘）均在 `auto/` 别名下产生、混入约 40% glm 后端，**只能作方向性观察，不能作为可比成绩**。

## 四、对工作流的影响

- `ITERATION-WORKFLOW.md` 的指标与流程不变，但**新增前置门槛**：来源未固定 → 只能做开发诊断，不能作配对结论。
- `EVALUATION-METHOD-REVIEW.md` 的"温度未固定"缺口应升级为"**模型来源未固定**"（更根本）。

## 五、复现

```powershell
python C:\sb\tmp\route_drift.py   # 读取 ~/.config/magpie/usage.jsonl 统计 req→served/provider
```

## 六、auto-hy3 组（用户确认三条是同一模型，2026-10-29 复测）

**重要更正**：`auto-hy3` 组的三条成员 `workbuddy/hy3`、`workbuddy-ai/hy3`、`workbuddy/hy3-x` 是**同一个腾讯 hy3 模型**，仅分为国际版/国内版、免费/付费额度来源（用户确认）。此前"hy3-x 是降配变体"的判断作废。

用户调整路由权重后复测（8 次）：
| 落点 | 次数 |
|---|---|
| hy3 / workbuddy | 4/8 |
| hy3 / workbuddy-ai | 4/8 |
| hy3-x / workbuddy（偶发） | 少量 |

- hy3 正常输出（含 `reasoning_content`，是推理模型）；单次 credits 0–0.01 量级。
- **含义**：组内是「同一模型 × 多额度池」，路由分摊到免费（workbuddy-ai Free plan，Credits 100%）与付费来源，**能力一致、可分摊额度**——这比 `auto/deepseek` 混入 glm 有本质不同，可以作为评测模型。
- **使用注意**：评测时记录每 trial 的 `served`/`provider`；若要完全确定性可 pin `workbuddy-ai/hy3`（免费池）。hy3 与 deepseek-v4.1-flash 是**不同模型**，两者的成绩不可混比。
