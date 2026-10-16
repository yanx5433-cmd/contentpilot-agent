# ContentPilot Agent 评测报告

- 用例数：18　通过：18　**通过率 100.0%**
- 平均时延：1 ms（全部离线确定性执行）

## 分维度得分

| 维度 | 通过/总数 | 通过率 |
|---|---|---|
| 护栏行为 | 5/5 | 100.0% |
| 结果质量 | 4/4 | 100.0% |
| 异常鲁棒 | 3/3 | 100.0% |
| 意图路由 | 6/6 | 100.0% |

## 用例明细

### 全部用例

| 用例 | 维度 | 结果 | 时延 | 工具调用 |
|---|---|---|---|---|
| G01 | guardrail | ✅ | 1ms | 0 |
| G02 | guardrail | ✅ | 1ms | 1 |
| G03 | guardrail | ✅ | 0ms | 0 |
| G04 | guardrail | ✅ | 0ms | 1 |
| G05 | guardrail | ✅ | 1ms | 1 |
| Q01 | quality | ✅ | 1ms | 2 |
| Q02 | quality | ✅ | 1ms | 2 |
| Q03 | quality | ✅ | 1ms | 1 |
| Q04 | quality | ✅ | 1ms | 2 |
| X01 | robustness | ✅ | 1ms | 2 |
| X02 | robustness | ✅ | 1ms | 2 |
| X03 | robustness | ✅ | 0ms | 1 |
| R01 | routing | ✅ | 1ms | 2 |
| R02 | routing | ✅ | 1ms | 2 |
| R03 | routing | ✅ | 1ms | 1 |
| R04 | routing | ✅ | 0ms | 1 |
| R05 | routing | ✅ | 0ms | 1 |
| R06 | routing | ✅ | 1ms | 1 |
