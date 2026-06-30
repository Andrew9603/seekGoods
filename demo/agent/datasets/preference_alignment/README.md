# SeekGoods 决策偏好对齐数据

这个目录用于把离线回放日志转成 `chosen/rejected` 决策偏好对，为后续 DPO / IPO 优化货源排序策略提供数据基础。

## 为什么选 DPO / IPO

本项目的比赛目标是连续多轮决策得分最大化，但当前已经有稳定的规则环境、离线回放日志和可解释打分器，因此最适合先做离线偏好优化：

- **IPO 优先**：对规则/回放生成的偏好对更稳，目标不会像 DPO 那样过度拉大 chosen 与 rejected 的概率差，适合样本量不大、偏好标签来自程序策略的场景。
- **DPO 备选**：适合在后续加入人工审核或强模型裁判后的高质量偏好对，用于让模型学习“哪个货源更符合最终得分目标”。
- **PPO / GRPO 暂不作为主线**：需要在线 rollout、reward model 或环境批量交互，工程成本更高；在当前比赛阶段，收益不如先把离线偏好对和 SFT 闭环做扎实。

## 数据来源

`build_decision_pairs.py` 从 `demo/results/experiments/robust_mpc_adaptive/agent_debug/*.jsonl` 读取每轮决策日志，抽取：

- 当前司机状态、风险等级、约束余量、adaptive mode；
- top-5 候选货源的分数、净收益和软偏好 tradeoff；
- 最终被 Agent / MPC 选择的货源；
- 被拒绝的候选货源。

当 MPC 选择的货源不是即时分数最高的候选时，会生成 `mpc_overrides_greedy` 样本，用来表达“短期高分不一定是长期最优”的比赛策略。

## 文件

- `decision_pairs_train.jsonl`：训练用偏好对。
- `decision_pairs_val.jsonl`：验证用偏好对。
- `decision_pairs_report.json`：样本数量和类型统计。
- `build_decision_pairs.py`：可复现的数据生成脚本。

## 重新生成

```powershell
python demo\agent\datasets\preference_alignment\build_decision_pairs.py
```

当前生成结果：

- 总偏好对：271
- 训练集：230
- 验证集：41
- `mpc_overrides_greedy`：14
- `ranked_lower`：257

## IPO 对齐结果

在 Qwen3.5-4B 的偏好理解 SFT adapter 基础上，使用 `loss_type=ipo` 进行二阶段偏好对齐。为了快速验证收益，先训练到 `checkpoint-20`，并在 41 条验证偏好对上与 SFT-only baseline 对比。

| 指标 | SFT-only | IPO checkpoint-20 |
| --- | ---: | ---: |
| Pairwise Accuracy | 95.12% | 100.00% |
| Avg Margin | 0.42 | 3.13 |
| mpc_overrides_greedy Accuracy | 0.00% | 100.00% |
| ranked_lower Accuracy | 100.00% | 100.00% |

其中 `mpc_overrides_greedy` 表示“即时分数更高，但 MPC 认为会破坏后续约束空间”的样本。该子集从 0% 提升到 100%，说明 IPO 对齐后模型更能学习比赛中的长期决策偏好，而不仅是复现当前轮次的贪心分数。

## 简历表述建议

可以写“基于离线回放构建 chosen/rejected 决策对，将高收益但违规、短期高分但破坏后续约束空间的候选货源作为 rejected，在 SFT adapter 基础上继续进行 IPO 二阶段对齐，使验证集 pairwise accuracy 从 95.12% 提升至 100%，并将 mpc_overrides_greedy 子集准确率从 0% 提升至 100%”。
