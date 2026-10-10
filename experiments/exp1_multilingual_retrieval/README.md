# FairTrial Track 1 — 跨语言检索对照实验

英文查询检索印尼语 / 土耳其语记者刑事案件资料。对照两条 pipeline：

| | Pipeline A | Pipeline B |
| --- | --- | --- |
| 策略 | multilingual-first | translate-first |
| 索引内容 | 印尼语 / 土耳其语原文 chunk | 同一批 chunk 的英文译文 |
| Embedding | BGE-M3 (dense) | BGE-M3 (dense) |
| 查询 | 英文 | 英文 |

两条 pipeline 使用**同一个 embedding 模型**、**同一套 chunk 划分**、**同一批查询向量**，唯一变量是"是否先翻译成英文"。

## 当前状态

已完成首轮 pilot（2026-10-09）：50 篇 `trialwatch_corpus` 合成语料 + 30 条标注查询，A/B 双跑完成。

**结论：这批数据上 A 和 B 统计上无法区分**，点估计轻微偏向 A。详见 [`results/track1_baseline/FINDINGS.md`](results/track1_baseline/FINDINGS.md)。

最有价值的发现是翻译审计：`kuasa hukum`（辩护律师）在 21 处被 Marian 译成 "legal authority"（法律当局，语义反转），印尼语人名被当普通名词翻译（`Dewi Anggraini` → "Goddess Anggraini"、`Bagus Setiawan` → "good"）。所以当前结论只适用于 opus-mt，不能推广到 translate-first 策略本身。

注意语料是模板生成的合成数据，绝对分数偏高，不可引用为真实语料性能。

## 安装

```bash
pip install -r requirements.txt
```

首次运行会自动下载 BGE-M3（约 2.2GB）和两个 Marian 翻译模型（各约 300MB）。Mac 上自动使用 MPS。

## 三步跑完实验

```bash
python3 scripts/01_translate.py      # Pipeline B：翻译并缓存到 data/translations/
python3 scripts/02_evaluate.py       # A/B 双跑 + 配对显著性检验 + 报告
python3 -m pytest tests/ -q          # 指标与 chunk 对齐的单元测试
```

产出在 `results/<run_name>/`：

| 文件 | 内容 |
| --- | --- |
| `comparison.md` | 主报告：A/B 对照表、Δ、95% CI、p 值 |
| `comparison.json` | 同上的机器可读版本 + 运行元数据 |
| `per_query.csv` | 逐查询 A/B/Δ，用来找 B 赢在哪、A 赢在哪 |
| `pipeline_A.json` / `pipeline_B.json` | 每条查询的 top-5 命中明细 |
| `chunk_plan.json` | 本次运行的 chunk 划分，复现的凭据 |

翻译结果会缓存，重跑 `01_translate.py` 不会重复翻译（要重译加 `--overwrite`）。

## 数据格式

### 文档：`data/docs/{id,tr}/<doc_id>.json`

```json
{
  "doc_id": "id-001",
  "lang": "id",
  "title": "文档标题",
  "source": "媒体名称",
  "url": "https://...",
  "date": "2024-03-11",
  "paragraphs": ["第一段……", "第二段……"]
}
```

`paragraphs` 是**必需**的，因为段落是整个实验的对齐单位。也接受 `.txt`（按空行切段，`doc_id` 取文件名），但建议用 JSON 以便保留 source / url / date 这些溯源字段。

命名建议 `id-001`…`id-025`、`tr-001`…`tr-025`，`doc_id` 全局唯一（重复会直接报错）。

段落 ID 自动生成为 `id-001#p001`、`id-001#p002`…（从 1 开始）。

### 查询：`data/queries.jsonl`

每行一条：

```json
{
  "qid": "q01",
  "query": "Which journalist was charged with defamation over a procurement investigation?",
  "facet": "named-entity",
  "relevant_docs": ["id-001"],
  "evidence": ["id-001#p001", "id-001#p002"],
  "lang_scope": null,
  "notes": "标注依据"
}
```

- `relevant_docs`：相关文档的 `doc_id`。**没填的条目会被跳过**（并打印原因），所以可以分批标注、随时试跑。
- `evidence`：承载答案的**段落 ID**，Evidence Recall 的金标准。留空则该条查询不参与 Evidence Recall（但仍计入其他指标）。
- `lang_scope`：`null` 表示在全部 50 篇里检索（默认，也是真实场景）。填 `["id"]` 可做单语言受控检索。

`scripts/make_query_template.py` 生成的模板预设了 7 类 facet 配额（named-entity / legal-provision / procedural-event / fair-trial-right / paraphrase / multi-doc / cross-lingual-pair），目的是避免 30 条查询全是同一种形状——否则结论只对那一种查询成立。`facet` 字段会留在数据里，方便事后按类别切分看差异。

## 指标定义

逐查询计算后在查询间取平均。`k` 默认取 1 / 3 / 5 / 10。

| 指标 | 定义 |
| --- | --- |
| `hit@k` | top-k 的 chunk 中只要有一个属于相关文档就算 1 |
| `recall_doc@k` | top-k 覆盖的相关文档数 / 相关文档总数 |
| `mrr@k` | 第一个命中相关文档的 chunk 的 1/排名，k 内没有则为 0 |
| `evidence_recall@k` | top-k 的 chunk 覆盖到的金标准段落数 / 金标准段落总数 |

`evidence_recall` 最贴近研究问题（能不能定位到原始证据段落），**建议作为主指标**，`hit@k` 权重次之——`hit@k` 只问文档对不对，不问证据找不找得到。

## 统计检验

A/B 跑的是同一批查询，因此是**配对比较**。报告给出逐查询 Δ 的均值、配对 bootstrap（默认 10000 次重采样，在查询维度重采样）的 95% 百分位 CI、以及双侧 bootstrap p 值，另附 B 胜 / A 胜 / 平局计数。

30 条查询的统计效力很有限。**CI 跨过 0 意味着这批查询分辨不出两条 pipeline，这是实验效力的陈述，不是"两者等价"的证据。** 如果最终 CI 跨 0 而你需要结论，扩查询量比换模型更有效。

## 方法论上的几个坑（已在代码里处理，但你需要知道）

**1. chunk 划分只在原文上算一次，原样套用到译文。**
这是整个对照的命门。英译文长度和原文不同，如果各自按字符数切分，A 和 B 的 chunk 边界就会错开，Evidence Recall 失去可比性。因此 `plan_chunks()` 在**源语言段落结构**上计算分组（哪几段合成一个 chunk），`chunk_plan.json` 落盘，两条 pipeline 都读同一份。`id-001#c002` 在 A 和 B 里永远指同一段落区间。

副作用：超过 `max_chars` 的单个段落不会被切开，而是自成一个 chunk——切开会让两边边界错位。

**2. 翻译质量是 Pipeline B 的混淆变量。**
Marian (opus-mt) 小、快、离线可复现，但质量一般。实测会把印尼语 `kuasa hukum`（法律代理人）译成 "Hartono's legal power"，还会插入伪省略号。**B 输了只能说明"用这个翻译器的 translate-first 输了"，不等于 translate-first 这个策略输了。**

要换更强的 MT：把 `config.yaml` 的 `translator.name` 改成 `manual`，自己按格式把译文放到 `data/translations/<lang>/<doc_id>.json`：

```json
{"doc_id": "id-001", "src_lang": "id", "tgt_lang": "en",
 "translator": "你用的翻译器名称",
 "title": "译文标题", "paragraphs": ["译文第一段", "译文第二段"]}
```

`paragraphs` 数量必须和原文**严格一致**，否则直接报错（保护段落对齐）。`translator` 字段会写进报告，避免两次不同 MT 的运行被混着比。

**3. 不要跨 pipeline 比较余弦分数绝对值。**
实测 B 的分数系统性高于 A（英-英匹配天然抬高相似度），即使排序质量相同。只有排名和上面那些指标可比；在一条 pipeline 上调好的分数阈值不能直接搬到另一条。

**4. 查询向量两条 pipeline 共用。**
查询都是英文、模型相同，所以 `02_evaluate.py` 只编码一次查询并复用同一批向量。查询侧不只是"等价"，而是逐比特相同——彻底排除了这一侧的噪声。

## 可替换的部件

| 部件 | 配置项 | 可选值 |
| --- | --- | --- |
| Embedding | `embedder.name` | `bge-m3`（默认）、`stub` |
| 翻译 | `translator.name` | `marian`（默认）、`manual`、`identity` |

- `embedder.name: stub` 是哈希字符 n-gram 向量，**没有任何跨语言能力**，仅用于不下载模型就跑通流程。它产出的报告会被标记警告。
- `translator.name: identity` 是对照组：B 变成 A 的副本，所有 Δ 构造上应为 0。拿它验证流水线无泄漏。

## 后续可做的对照（当前未实现）

- BGE-M3 的 sparse 与 multi-vector 模式，以及 dense+sparse 混合检索（设计文档里提到的下一步）
- Pipeline C：原文 + 译文双索引合并
- 加入一个非多语言的英文 embedding 模型，量化"多语言能力"本身值多少
- reranker 阶段

## 目录结构

```
config.yaml                  # 全部实验参数
data/docs/{id,tr}/           # 源文档（现在是 6 篇合成占位）
data/translations/{id,tr}/   # 英译缓存（01_translate.py 生成）
data/queries.jsonl           # 30 条查询（现在是空白模板，待标注）
data/queries.sample.jsonl    # 配合合成文档的示例查询
src/fairtrial/
  corpus.py                  # 文档加载、段落 ID、共享 chunk plan
  translate.py               # 翻译层（marian / manual / identity）
  embedders.py               # embedding 层（bge-m3 / stub）
  index.py                   # flat dense 索引（50 篇用精确检索即可）
  metrics.py                 # 四个指标 + 配对 bootstrap
  pipelines.py               # Pipeline A / B 构建与查询执行
  report.py                  # Markdown / CSV 报告
scripts/01_translate.py      # 翻译全部文档
scripts/02_evaluate.py       # A/B 对照评测
scripts/make_query_template.py   # 生成 30 条空白查询模板
scripts/make_sample_data.py      # 生成合成占位语料
tests/test_metrics.py        # 指标与 chunk 对齐测试
results/_demo_synthetic/     # 占位数据的输出示例（非实验结果）
```
