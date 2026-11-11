# 手册混合检索

`search_manual` 默认仍走 SQLite FTS5 / BM25。`RETRIEVER` 可以改成 `dense`、`hybrid` 或 `hybrid_rerank`。进程内调用和 MCP 子进程读的是同一组环境变量，草案审批和幂等写入不经过检索器。

## 为什么要混合

错误码和零件号是稀有字符串。`RUL0014` 这种查询，词面检索能直接命中唯一段落。改写过的说法则可能和手册没有共同的词，例如「机器抖得厉害」对应的是写着「振动」的段落。稠密向量按语义靠近程度找候选，词面检索按字符串找候选。两条候选名单用倒数排名融合，再交给交叉编码器看查询和段落的原文。

当前中文演示手册里没有单独的零件号。精确标识符这一类，用英文夹具里的告警码 `RUL0014`。

## 模型

嵌入模型用 `intfloat/multilingual-e5-small`（MIT，12 层，向量维度 384，权重约 470 MB）。模型卡要求查询加 `query: `、段落加 `passage: `，中文和英文都要加。模型卡的示例里就有中文查询。

没有用 `BAAI/bge-small-zh-v1.5`。它的模型卡语言标记是 `zh`，结构是 4 层中文 BERT，词表大小 21128，权重约 96 MB。这个词表对英文手册不合适。

没有用 `BAAI/bge-m3`。它是 24 层 XLM-RoBERTa，维度 1024，权重约 2.27 GB，能覆盖中英，但不是小的 CPU 模型。

重排序用 `BAAI/bge-reranker-base`（MIT，骨干是 XLM-RoBERTa-base，权重约 1.11 GB），中英都能打分。`bge-reranker-v2-m3` 约 2.27 GB，CPU 上更重，所以没有作为默认。重排序只看融合后的前 N 条，N 由 `RETRIEVAL_CANDIDATES` 决定，默认 20。

向量存在业务库的 sqlite-vec 表 `manual_vec` 里。项目本来就依赖 `sqlite-vec`，索引和手册在同一个 SQLite 文件中。sqlite-vec 0.1.9 不允许在 KNN 查询里过滤辅助列，所以先取出全部向量邻居，再按设备类型在 Python 里留下 `设备类型` 和 `general`。演示库只有十几条，这一步是精确扫描。向量在写入前做了 L2 归一化，排序用的相似度是由 L2 距离还原的余弦：`1 - 距离² / 2`。

## RRF

Cormack、Clarke 与 Buettcher，SIGIR 2009，Reciprocal Rank Fusion。两条名单里，名次从 1 开始。文档 `d` 的分数是：

```
score(d) = Σ 1 / (k + rank_r(d))
```

只对包含 `d` 的名单求和。某条名单里没有 `d`，那一条就加 0。默认 `k = 60`，可用 `RRF_K` 修改。分数相同则按手册 ID 排序，保证顺序稳定。

`hybrid` 直接取融合后的前 `top_k`。`hybrid_rerank` 先取融合后的前 N 条，再用交叉编码器重排，返回前 `top_k`。返回的命中里带有手册 `id`，引用检查仍看这个 ID。

## 索引

默认的 BM25 不建索引，也不下载模型。稠密模式在索引缺失、模型不一致或手册已经变化时返回错误码。这次调用失败，结果里不会带上 BM25 命中。

~~~powershell
py -3 -m pip install "sentence-transformers>=3,<6"
py -3 scripts/build_manual_index.py --db runtime/business.db --fixture evals/assetopsbench/fixtures/english_demo.json
$env:RETRIEVER = "hybrid_rerank"
$env:EMBEDDER = "sentence-transformers"
~~~

MCP 子进程会收到 `RETRIEVER`、`RRF_K`、`RETRIEVAL_CANDIDATES`、`EMBEDDING_MODEL`、`RERANKER_MODEL` 和 `EMBEDDER`，不接收 API 密钥。单独启动 HTTP 服务时，这几个变量要写在服务进程上。一个 HTTP 进程仍然只绑一台设备。

`EMBEDDER=fake` 使用词面哈希和词交比重叠，只给测试和 CI。它的分数不能填进下面的表。

## 评测

标注在 `evals/retrieval/labels.json`，共 10 条，开发集和测试集各 5 条。开发集有中文词面、中文改写、英文改写和错误码 `RUL0014`。测试集有中文词面、中文改写和英文词面。划分按查询类型和语言事先指定，不按分数挑选。每条查询只有一个相关段落。指标是 Recall@1、Recall@3、MRR、nDCG@3，以及查询延迟的平均值和 p50。nDCG 按二元相关计算，理想折损是 1。

可以改的只有开发集：嵌入模型、重排序模型、RRF 的 k、融合后送去重排序的前 N 条（`fused_top_n`）、重排序后保留的条数（`rerank_top_k`）。当前冻结值写在 `evals/retrieval/frozen_config.json`：`intfloat/multilingual-e5-small`、`BAAI/bge-reranker-base`、k=60、N=20、保留 10 条。模型按模型卡和权重大小选定，k 用 RRF 论文里的常用默认值。这些值在看测试集分数之前冻结。测试集命令不接受这些参数；配置文件若未标成 `frozen` 且 `frozen_before_split=test`，测试集直接退出，不写分数。

结果 JSON 里有两个哈希。`config_sha256` 是实际使用的那五项的规范 JSON（键排序、无空格）的 SHA256。`frozen_config_sha256` 是整份冻结文件的同一算法哈希。测试集上 `config_matches_frozen` 为 true。

划分写进文件之前，这 10 条曾经放在一起跑过。那次数字已经撤回，不作为测试成绩。测试集只在冻结之后单独跑一次。真实模型的测试结果文件若已存在，脚本不会覆盖。

| 模式 | Recall@1 | Recall@3 | MRR | nDCG@3 | 延迟 p50（毫秒） |
| --- | --- | --- | --- | --- | --- |
| bm25 | 待运行 | 待运行 | 待运行 | 待运行 | 待运行 |
| dense | 待运行 | 待运行 | 待运行 | 待运行 | 待运行 |
| hybrid | 待运行 | 待运行 | 待运行 | 待运行 | 待运行 |
| hybrid_rerank | 待运行 | 待运行 | 待运行 | 待运行 | 待运行 |

上表只留给测试集的真实模型运行。CI 用 `EMBEDDER=fake` 检查开发集和测试集的流程，假嵌入的分数不填进这张表。

~~~powershell
py -3 evals/retrieval/run.py --split dev --embedder fake --out runtime/retrieval-dev-fake.json
py -3 evals/retrieval/run.py --split test --embedder fake --out runtime/retrieval-test-fake.json
# 开发集上试参数。确认后再改 frozen_config.json，并保持 frozen_before_split=test。
py -3 evals/retrieval/run.py --split dev --embedder sentence-transformers --rrf-k 60 --out runtime/retrieval-dev.json
# 测试集只跑一次，不带调参参数。
py -3 evals/retrieval/run.py --split test --embedder sentence-transformers --out runtime/retrieval-test.json
~~~

后两条在未安装 `sentence-transformers` 或模型下载失败时直接退出，不写分数。
