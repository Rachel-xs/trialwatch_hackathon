# TrialWatch 检索对照实验：测试库

50 篇合成新闻（土耳其语 25 + 印尼语 25）和 30 条英文查询。全部是虚构的，人名、媒体、案件都不是真的。
每篇文档 6 个段落，段落 ID 格式是 `文档ID#p001`。

## 放哪里
- `data/docs/tr/*.json` 放进项目的 `data/docs/tr/`
- `data/docs/id/*.json` 放进项目的 `data/docs/id/`
- `data/queries.jsonl` 覆盖项目的 `data/queries.jsonl`
- 先删掉原来的 6 篇占位文档

## 字段
- 文档：`doc_id, lang, title, published, synthetic, paragraphs`
- 查询：`qid, query, facet, gold_docs, evidence`

如果你项目里的 queries 模板字段名不一样，改 `build_corpus.py` 里最后写 jsonl 那一段，再跑一次 `python3 build_corpus.py`。

## 里面有什么
- 20 个案件，每个案件 2 篇报道（立案、开庭或判决），再加 10 篇干扰文档
- 干扰文档里有 4 篇是同条款但被告不是记者的案子，用来测假阳性
- 有两组同名不同案：Mehmet Yıldız（土）、Ahmad Fauzi（印尼）
- 有几个翻译容易出错的法律词：HAGB（hükmün açıklanmasının geri bırakılması）、kuasa hukum、pidana percobaan、bilirkişi
- 30 条查询按 7 类分：named-entity 5，legal-provision 5，procedural-event 5，fair-trial-right 5，paraphrase 4，multi-doc 3，cross-lingual-pair 3

## 标注怎么来的
标注是生成时按模板位置直接记下来的，生成后脚本又自动核对过（证据段落里确实有对应的字符串）。所以 gold 不用再人工检查。

## 限制
文本是模板生成的，比真实新闻规整。结果能比较 A 和 B，但绝对分数会偏高。
`answer_key_case_index.json` 是答案对照表，不要喂给检索流程。
