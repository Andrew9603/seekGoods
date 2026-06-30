# SeekGoods 偏好解析微调数据

该目录用于训练“司机自然语言偏好 → 结构化约束 JSON”的模型，不用于直接生成接单动作。

## 数据文件

- `train.jsonl`：2,500 条训练样本
- `val.jsonl`：300 条验证样本
- `test.jsonl`：400 条常规泛化测试样本
- `challenge.jsonl`：200 条含模糊、缺参和未知硬约束的困难样本
- `*_messages.jsonl`：可直接用于聊天式 SFT 的 `messages` 格式
- `public_seeds.jsonl`：12 条公开比赛偏好的人工结构化种子，默认不混入训练集
- `dataset_report.json`：数量、规则分布和重复文本检查
- `generate_dataset.py`：确定性生成器

总合成样本数为 3,400 条。训练、验证和测试使用互不相同的表达模板，避免同一句话的简单改写同时落入不同集合。

## 标签结构

标签与 `demo/agent/core/preference_parser.py` 对齐，覆盖：

- 禁运或尽量避免的货物品类
- 固定休息窗口和每日连续休息
- 月度完整休息日
- 全局及指定日期区域限制
- 接货空驶和干线里程上限
- 指定区域订单覆盖天数
- 指定日期、坐标和停留时间
- 每日回家要求
- 限定运营区域
- 无法可靠解析的硬约束

## 重新生成

```powershell
python demo\agent\datasets\preference_sft\generate_dataset.py
```

生成过程固定随机种子 `20260623`，可复现。

## 使用建议

1. 先用 `train_messages.jsonl` 做 SFT。
2. 用 `val.jsonl` 选择训练轮次和超参数。
3. 最终只在 `test.jsonl` 与 `challenge.jsonl` 上报告结果。
4. 指标至少包含 JSON 有效率、字段级 Micro/Macro F1、硬约束召回率、数值准确率。
5. `public_seeds.jsonl` 建议作为人工回归集；是否加入训练需确认赛事数据许可。
