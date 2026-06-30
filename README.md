# SeekGoods

面向货运找货比赛的连续决策 Agent 项目。

项目围绕卡车司机多轮找货任务，构建以最终得分为目标的 Agent 决策系统：在每轮决策中综合司机偏好、货源收益、空驶成本、路线方向、休息窗口与后续约束可行性，输出接单、等待或空驶动作。

## Highlights

- Agent 决策架构：约束防火墙 + 软偏好 tradeoff + MPC 滚动规划。
- 偏好理解：将司机自然语言偏好解析为结构化约束 JSON。
- 二阶段对齐：基于离线回放轨迹构建 chosen/rejected 决策对，并使用 IPO 对齐货源排序偏好。
- 策略评测：支持本地回放、策略 profile 对比、动作日志与收益统计。
- 可视化：基于 Vue 3 / MapLibre 的找货过程回放页面。

## Repository Layout

```text
demo/
  agent/     # Agent 决策逻辑、策略参数、偏好解析与训练数据脚本
  server/    # 本地评测服务与数据接口
  simkit/    # 仿真接口封装
docs/        # 赛题、数据、评测与提交说明
vis/         # 前端可视化项目
```

## Notes

大型比赛数据、模型权重、训练输出、运行日志、依赖目录和部署密钥不会纳入 Git 仓库。运行前请根据 `docs/` 和 `demo/README.md` 准备本地数据与环境。

