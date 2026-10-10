# 样本外检验：冻结规则 on 20261010T165830Z_v2_q1-id-keywords_sample.csv

generated 2026-10-10T17:14:31.419893+00:00

规则来自 `x_precision_rules.yaml`，未作任何修改。frozen order: ['automated_accounts', 'length_ceiling', 'actor_event_proximity', 'attribution_frame']

样本 40 条：relevant 2、uncertain 13、noise 25

## 累计

| 规则（累计） | 保留 | 严格精度 | 宽松精度 | relevant 保留 | uncertain 保留 | 事件 |
|---|---|---|---|---|---|---|
| baseline (no rule) | 40 | 5.0% | 37.5% | 2/2 | 13/13 | 7/7 |
| + automated_accounts | 40 | 5.0% | 37.5% | 2/2 | 13/13 | 7/7 |
| + length_ceiling | 32 | 3.1% | 43.8% | 1/2 | 13/13 | 7/7 |
| + actor_event_proximity | 14 | 7.1% | 64.3% | 1/2 | 8/13 | 5/7 |
| + attribution_frame | 13 | 7.7% | 69.2% | 1/2 | 8/13 | 5/7 |

## 被丢掉的已标注帖

```
  length_ceiling: #7 (relevant, Baubau) -- 1867 chars > 1500
  actor_event_proximity: #21 (uncertain, Lampung) -- no event term
  actor_event_proximity: #24 (uncertain, Bogor) -- no event term
  actor_event_proximity: #26 (uncertain, Bekasi) -- no event term
  actor_event_proximity: #28 (uncertain, Lampung) -- no event term
  actor_event_proximity: #32 (uncertain, 事件不明) -- no event term
```

保留事件 ['Baubau', 'Bekasi', 'Makassar-TNI', 'Nias', 'Serang']；完全丢掉 ['Bogor', 'Lampung']

## 单独

| 规则（单独） | 保留 | 严格精度 | 宽松精度 | 丢掉的已标注 |
|---|---|---|---|---|
| automated_accounts | 40 | 5.0% | 37.5% | 无 |
| length_ceiling | 32 | 3.1% | 43.8% | #7(relevant) |
| actor_event_proximity | 15 | 13.3% | 66.7% | #21(uncertain), #24(uncertain), #26(uncertain), #28(uncertain), #32(uncertain) |
| attribution_frame | 28 | 7.1% | 53.6% | 无 |
