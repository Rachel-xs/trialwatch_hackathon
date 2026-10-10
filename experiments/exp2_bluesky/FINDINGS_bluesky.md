## 2026-10-09（续三）Bluesky 印尼测试

范围：只测 Bluesky，只做印尼，只用印尼语和英语。其他社媒平台没有申请，一律跳过。
含土耳其语的旧指令作废。打分、抽取、agent 代码没有动，GDELT / RSS / 网页来源没有重测。

社媒在这里只当线索，不当证据。要回答的只有一个问题：
**哪些关键词和 hashtag 在真实讨论"记者被报案、被传唤、被拘留"。**

脚本 `scripts/test_bluesky_id.py`，可重复运行，结论由测量值推导。
配置 `config/keywords.yaml`、`config/hashtag_seeds.yaml`、`config/watchlist_search_names.yaml`，
队友可以直接改，脚本不写死任何词。

### 钥匙处理

- 只从项目根目录 `.env` 经 python-dotenv 读取，变量名 `BSKY_HANDLE`、`BSKY_APP_PASSWORD`。
- `.env` 已加入 `.gitignore`；另附 `.env.example` 供队友填。
- 全程没有 `cat`、`echo`、`print` 过 `.env` 内容；access token 只在内存里，不落盘。
- 提交前扫描：密码字符串在 `data/social_test.json`、`data/watchlist_candidates.json`、
  脚本和所有 config 里命中 **0 次**；`git diff --cached` 已检查。

> **一个安全提醒**：这次的 app password 是直接贴在对话里给我的，所以它已经留在会话记录里了。
> 建议今晚用完后到 Bluesky 的 Settings → Privacy and security → App passwords 把它撤销重发一个。

### 接口（先查官方 lexicon 再写，没有凭记忆）

| 接口 | 类型 | 关键参数 |
|---|---|---|
| `com.atproto.server.createSession` | procedure (POST) | `identifier`、`password`（必填） |
| `app.bsky.feed.searchPosts` | query (GET) | `q` **必填**、`sort`=top\|latest、`lang`、`tag[]`（多个为 AND）、`limit` 1..100、`cursor` |
| `app.bsky.actor.searchActors` | query (GET) | `q`、`limit` 1..100；**不需要登录** |

实测：`searchPosts` **未登录一律 403**（6 种参数组合都试过），必须带 token。
`tag` 参数要求同时给 `q`，所以用 `q=*` + `tag=<种子>`；7 个种子里 6 个这样可用，
`uuite` 这一个被拒后回退到 `q=#uuite`，每条记录都写明了用的哪种形式（`query_form_used`）。

### 执行结果

| | |
|---|---|
| 登录 | **成功**，HTTP 200，handle 与 .env 一致，账号 active |
| 请求总数 | 47，间隔 ≥1.2 秒 |
| 401 / 403 / 429 | **0 次**（未登录探测时的 403 不计入正式运行），没有重试，没有换方式硬试 |
| 错误 | 0 |
| 存下的帖子 | 200 行，去重后 188 条 |

### 关键词查询：30 个查询，只有 13 个有返回

**英语基本是空的：12 个英语查询里 11 个返回 0 条**，唯一一条还是 21222 小时（2.4 年）前的。
印尼语 18 个查询里 12 个有返回。

| 查询 | 条数 | 双词命中 | 比例 | 链接转发占比 | 最新一条距今 |
|---|---|---|---|---|---|
| wartawan "UU ITE" | 1 | 1 | 1.00 | 100% | 9272.7h |
| wartawan ditahan | 6 | 5 | 0.83 | 100% | 3446.9h |
| jurnalis ditahan | 22 | 14 | 0.64 | 100% | 1383.4h |
| wartawan tersangka | 22 | 13 | 0.59 | 100% | 5452.3h |
| jurnalis kriminalisasi | 10 | 5 | 0.50 | 100% | 6614.5h |
| **wartawan dilaporkan** | 14 | 5 | 0.36 | 86% | **206.9h（8.6 天）** |
| **jurnalis dilaporkan** | 25 | 6 | 0.24 | 76% | **360.7h（15 天）** |
| **wartawan dipanggil** | 5 | 1 | 0.20 | 80% | **399.2h（16.6 天）** |
| jurnalis tersangka | 23 | 4 | 0.17 | 100% | 741.3h |
| wartawan kriminalisasi | 1 | 0 | 0.00 | 0% | 6302.7h |
| jurnalis dijerat | 1 | 0 | 0.00 | 100% | 13169.4h |
| jurnalis "UU ITE" | 1 | 0 | 0.00 | 100% | 7285.8h |
| journalist defamation Indonesia | 1 | 0 | 0.00 | 0% | 21222.6h |

返回 0 条的查询：`wartawan dipolisikan`、`jurnalis dipolisikan`、`wartawan dijerat`、
`wartawan "pencemaran nama baik"`、`jurnalis "pencemaran nama baik"`、`jurnalis dipanggil`，
以及除 defamation 外的全部 11 个英语查询。
**注意 `dipolisikan`（被报案）这个最贴题的词，两个组合都是 0 条。**

语言分布：id 137、en 33、未声明 28、de 1、it 1。抓取延迟中位数 8273 小时。

### 那个"比例"是假的，人工看样本就露馅

上表的 0.5–0.83 看着不错，但双词规则在这批数据上几乎全是误报。随机样本（每条前 120 字符）：

- `jurnalis ditahan` → 「40 jurnalis Palestina **ditahan** di penjara Israel」「Swiss Bebaskan Jurnalis Palestina…」
  —— 以色列羁押巴勒斯坦记者，不是印尼。还有一条「**Ditahan** imbang Fiorentina, Maignan…」是足球「逼平」。
- `wartawan dilaporkan` → 「Sejumlah wartawan **dilaporkan** hilang」—— 喀拉喀托采访失联，是"报告失踪"不是"被报案"。
- `wartawan tersangka` → 「Polres Serang tetapkan lima **tersangka** pengeroyokan … wartawan」——
  记者是被害人；还有「Tersenyum Jadi **Tersangka** Korupsi Pasar Cinde」完全无关。
- `wartawan dipanggil` → 「Eks Istri Andre Taulany Laporkan Rieke ke MKD DPR: Akan **Dipanggil**」—— 国会传唤。

188 条里：**64% 带链接**（自动转发新闻标题的机器人账号，不是讨论），
26 条含「hilang」（失联搜救），23 条含 Israel/Palestina/Gaza，7 条是 DPR/MKD 传唤。

整批数据里真正贴题的只有一条：
**「Wartawan Tetap Bisa Dipanggil Aparat Meski Ada Putusan MK」**（Tempo，399 小时前）——
而且它也只是一条新闻链接转发。

### 种子 hashtag 验证：7 个全部不合格

| 种子 | 返回条数 | 含人物或事件词 | **同时含两类词** | 最新一条距今 |
|---|---|---|---|---|
| #pressfreedom | 25 | 3 | **0** | 3.8h |
| #wartawan | 23 | 20 | **0** | 6936.1h |
| #jurnalis | 11 | 8 | **0** | 634.4h |
| #dewanpers | 6 | 2 | **0** | 440.4h |
| #kebebasanpers | 2 | 0 | **0** | 3824.1h |
| #uuite | 1 | 0 | **0** | 9645.0h |
| #kriminalisasijurnalis | **0** | 0 | **0** | 无 |

七个种子**没有一个**返回过同时含人物词和事件词的帖子。
`#kriminalisasijurnalis` 这个最贴题的标签在 Bluesky 上一条都没有。
配置文件里的 `verified: false` 保持不变——验证结果只写进 JSON，不回写人类拥有的配置。

### 发现的 hashtag 前 30：按你的规则 28 个"相关"，按严格规则只剩 2 个

你指定的规则是"同帖含人物词**或**事件词"。这条规则在这批数据上把 30 个里的 28 个标成相关，
包括 `#rumahsubsidi`（记者住房补贴）、`#alqaeda`、`#yaman`、`#culik`（也门记者被绑架）、
`#malaysia`、`#tempolab` 这类显然无关的。原因是只要帖子里出现「wartawan」就算命中。

我保留了你的规则（`classified_loose`），另加一列「同时含人物词**且**事件词」（`classified_strict`）。
严格规则下 30 个里只剩 **2 个**：`#pu608` 和 `#sigapmembangunnegeriuntukrakyat`——
都是公共工程部关于喀拉喀托记者搜救的宣传标签。

**也就是说：发现层没有找到任何一个真正关于记者被刑事追诉的 hashtag。**

出现次数前十：#wartawan 23、#pressfreedom 22、#news 15、#jurnalis 12、#update 11、
#seketika 11、#dewanpers 9、#journalism 8、#terbunuh 6、#pers 5。

### 账号候选：八个机构基本不在 Bluesky 上

结果写进 `data/watchlist_candidates.json`，**没有自动加进 watchlist，等你人工确认**。

| 搜索的名字 | 结果 |
|---|---|
| AJI Indonesia | 没有机构账号；首位是个人记者，简介里提到 AJI |
| LBH Pers | 无关（德语、荷兰语账号） |
| SAFEnet | `safenet-eu` 是欧洲生物多样性项目，不是印尼那个数字权利组织 |
| Dewan Pers | 无关 |
| Komite Keselamatan Jurnalis | 返回的全是土耳其语账号 |
| Tempo | Toronto Tempo（WNBA 球队）、Jess Temporal、Bits & Bops |
| Tirto | `tirto.id.web.brid.gy` —— Bridgy Fed 的 **RSS 桥接镜像**，不是官方账号 |
| Project Multatuli | `projectm-poster.bsky.social`，简介原文「Bukan akun resmi. Otomatis posting via RSS.」（**不是官方账号，RSS 自动转发**） |

唯二像的两个，自己都声明是 RSS 自动镜像。

**一个接口限制要说清楚**：你要的粉丝数，`searchActors` 返回的 `profileView` 里**没有这个字段**
（`followersCount` 在 `getProfile` 的 `profileViewDetailed` 里）。
所以候选记录里 `followers_count` 全是 `null`。
要补粉丝数需要对这些账号调 `getProfile`，那超出了你说的"只做搜索"，**我没有做，等你发话。**

### 隐私处理

`data/social_test.json` 每条帖子只存：平台、发布时间、抓取时间、正文前 280 字符、语言、
账号类型、query_id，帖子 id 是 `sha256(at-uri)`。
**没有存任何个人账号的 handle、显示名或 DID**，没有头像、粉丝列表、私信。
账号类型目前全部是 `unconfirmed`——只有你确认并写进 `config/watchlist.yaml` 的机构账号才会被标成 `org_confirmed`。
hashtag 统计只存标签文字和次数。
`watchlist_candidates.json` 里有机构账号名，这是你明确要求的，且文件头写明了 UNCONFIRMED。

### 结论

**Bluesky 周五不值得用在印尼记者案件的早期预警上。**

三个理由，每个都有数据：

1. **太慢，谈不上"早期"。** sort=latest 的前提下，最贴题的那几个查询最新一条分别是
   8.6 天、15 天、16.6 天前。我们的 RSS 发现层同一批来源是 1–7 小时。
   社媒本该比新闻快，这里反过来慢了一到两个数量级。
2. **没有讨论，只有机器人转发。** 188 条里 64% 是"标题 + 链接"的自动转发，
   贴题性最高的那几个查询是 100%。这些内容我们已经从 RSS 直接拿到了，经 Bluesky 绕一圈只会更晚。
3. **最贴题的词和标签是空的。** `dipolisikan`、`pencemaran nama baik` 查询返回 0 条，
   `#kriminalisasijurnalis` 返回 0 条，7 个种子标签没有一个出现过"人物词+事件词"同现。
   八个印尼新闻和权利机构里没有一个有真实的 Bluesky 存在。

**相对而言命中率最高的（但都没有达到可用标准）：**
- 关键词：`wartawan dilaporkan`（8.6 天，是全部查询里最新的）、`jurnalis dilaporkan`、`wartawan dipanggil`
  —— 这三个是唯一能返回近两周内容的，但双词比例只有 0.20–0.36，且样本显示大多是"报告失踪"不是"被报案"。
- hashtag：`#pressfreedom` 流量最大（25 条、最新 3.8 小时）但基本是英文国际内容，印尼案件相关为 0；
  `#jurnalis` 和 `#dewanpers` 是印尼语里最活的两个，但同样没有案件相关命中。

**建议**：印尼的早期预警继续靠已经跑通的 RSS 发现层（`lbhpers.org`、`titastory.id`、
`kendariinfo.com`、`potretmalut.com`、`tirto.id` 等），Bluesky 先不接。
如果以后要再看社媒，值得试的不是 Bluesky 而是印尼记者实际在用的平台，但那些我们都没有申请，本轮按规矩跳过。

---
