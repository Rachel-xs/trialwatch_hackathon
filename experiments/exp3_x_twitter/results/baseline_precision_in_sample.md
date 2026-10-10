# baseline precision, local rules only (0 API requests)

generated 2026-10-10T16:00:52.040141+00:00

posts 38; relevant 3, uncertain 5, noise 30; events strict 2, loose 5

## 累计

| 规则 (累计)                      | 保留 | 严格精度 | 宽松精度 | 丢掉 relevant | 丢掉 uncertain | 事件(严格) | 事件(宽松) | 每事件噪声 |
|---|---|---|---|---|---|---|---|---|
| baseline (no rule)           |   38 |     7.9% |    21.1% | 3/3 保留 (-0) | 5/5 保留 (-0) | 2/2 | 5/5 | 6.0 |
| + automated_accounts         |   36 |     8.3% |    22.2% | 3/3 保留 (-0) | 5/5 保留 (-0) | 2/2 | 5/5 | 5.6 |
| + length_ceiling             |   27 |    11.1% |    29.6% | 3/3 保留 (-0) | 5/5 保留 (-0) | 2/2 | 5/5 | 3.8 |
| + actor_event_proximity      |   10 |    30.0% |    70.0% | 3/3 保留 (-0) | 4/5 保留 (-1) | 2/2 | 5/5 | 0.6 |
| + attribution_frame          |    9 |    33.3% |    77.8% | 3/3 保留 (-0) | 4/5 保留 (-0) | 2/2 | 5/5 | 0.4 |
| + haiku_case_lead            |    7 |    42.9% |   100.0% | 3/3 保留 (-0) | 4/5 保留 (-0) | 2/2 | 5/5 | 0.0 |

## 单独

| 规则 (单独)                  | 保留 | 严格精度 | 宽松精度 | 丢掉的已标注 |
|---|---|---|---|---|
| automated_accounts       |   36 |     8.3% |    22.2% | 无 |
| length_ceiling           |   29 |    10.3% |    27.6% | 无 |
| actor_event_proximity    |   11 |    27.3% |    63.6% | #25(uncertain) |
| attribution_frame        |   20 |    15.0% |    40.0% | 无 |
| haiku_case_lead          |   11 |    27.3% |    72.7% | 无 |

## 丢掉的已标注帖

```
  actor_event_proximity: #25 (uncertain) -- no event term
```

## length_ceiling 敏感度

| max_chars | 保留 | 严格精度 | 宽松精度 | 丢掉的已标注 |
|---|---|---|---|---|
|       500 |   16 |    18.8% |    37.5% | #11, #25 |
|       800 |   21 |    14.3% |    33.3% | #25 |
|      1000 |   22 |    13.6% |    31.8% | #25 |
|      1200 |   24 |    12.5% |    29.2% | #25 |
|      1500 |   29 |    10.3% |    27.6% | 无 |
|      2000 |   29 |    10.3% |    27.6% | 无 |
|      3000 |   34 |     8.8% |    23.5% | 无 |
|      4000 |   36 |     8.3% |    22.2% | 无 |
|     99999 |   38 |     7.9% |    21.1% | 无 |

## Haiku vs 人工

来源: out/x_label/haiku_labels_subagent.json

| haiku lead | relevant | uncertain | noise | 帖号 |
|---|---|---|---|---|
| yes | 3 | 3 | 1 | #7, #11, #12, #14, #23, #24, #37 |
| unsure | 0 | 2 | 2 | #16, #21, #25, #32 |
| no | 0 | 0 | 27 | — |
