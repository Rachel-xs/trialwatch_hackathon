# 实验三：X（Twitter）印尼记者案件线索测试

这个文件夹是 X 测试的代码、配置、标注和汇总结果。

## 里面有什么
- scripts/：抓取（test_x_id.py、x_fetch_broad.py）、规则评估（x_precision_eval.py、x_rules_oos.py）、与 RSS 对比（x_vs_rss.py）等脚本。
- config/：关键词、查询、事件匹配器、精度规则。
- labels/：人工标注，只有标签、事件名和噪声类型，不含账号和链接。
- results/：样本内精度、样本外检验、X 与 RSS 先后对比三份汇总。
- FINDINGS_x.md：前两轮的完整记录。

## 没放什么
- 没放 .env。需要的话复制 .env.example，填自己的 X Bearer token。
- 没放原始帖子和 out/ 目录。里面有账号名和帖子正文，按项目隐私规则不外发。
- 没放 RSS 文章语料。x_vs_rss.py 需要 data/articles 和 data/id，在主仓库里。

## 复现
1. 配好 .env。
2. 先跑 python3 scripts/x_fetch_broad.py --dry-run 看计划请求数。X 按请求计费，超长查询的 400 也算一个请求。
3. 规则评估只读本地文件，不花请求：scripts/x_precision_eval.py、scripts/x_rules_oos.py。
