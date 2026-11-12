# 设备告警与维修文本受理 Agent

基于 LangGraph 官方 ReAct 模板改造的个人 FDE 项目，提供两条可运行流程：

- **设备告警**：模型选择设备、历史工单与手册工具，生成检查草案，再由人工确认是否写入工单。
- **维修文本受理**：接入公开 MaintIE 专家标注语料，模型抽取原文实体，固定工作流检索案例并生成受理草稿，人工确认后入库。

项目在 AI 辅助下开发，当前为 Windows 本地单进程 POC。设备、演示手册和初始工单为合成材料；MaintIE 为作者公开的脱敏维修短文本，二者分别记录来源。上游与许可见 [UPSTREAM.md](UPSTREAM.md)，数据接入与复查见 [docs/maintie.md](docs/maintie.md)。

这条分支已经接上 MCP 工具服务、四种手册检索，以及 AssetOpsBench、MaintNorm 两套评测。检索测试集的数字在 `reports/`，口径在 [docs/retrieval.md](docs/retrieval.md)。告警评测和 MaintNorm 的 DeepSeek 分数还没跑，对应位置留空。

## 本轮实际结果

| 检查 | 实际结果 | 记录 |
|---|---|---|
| MaintIE 原始文件 | 固定作者提交，1,076 条 gold 文本；原始字节 SHA256 验证通过 | data/maintie/manifest.json |
| 数据分区 | 869 条参考、207 条评估（203 个不同归一化文本）；评估区未进入检索索引 | [数据说明](docs/maintie.md) |
| 真实 DeepSeek 抽取 | 固定哈希顺序的 24 条评估文本，24 条输出通过结构校验；顶层实体严格跨度 micro-F1 **0.8105** | [原始预测与计分](reports/maintie-v1/evaluation.json) |
| 真实模型工作流 | 确认后创建 1 单；拒绝与信息不足各 0 单；重建服务后可审批，重复确认不重复创建 | [流程验收](reports/maintie-v1/workflow-live.json) |
| 实际本机 HTTP | 使用公开评估记录作为输入，验证原文来源、案例隔离、重复事件与待审批状态 | [HTTP 记录](reports/maintie-v1/http-live.json) |

micro-F1 是 24 条指定文本上“跨度和顶层类别同时一致”的实体指标，不是工单解决率。当前只抽取 PhysicalObject、State、Process、Activity、Property 五类；没有复现细粒度类别或关系抽取。主要误差见数据说明。

原告警路径的 24 项回归和三例真实模型结果保留在 [原验收记录](reports/live-verification.json)。新增回归与最新本地结果见 [tests/](tests/) 和 [本轮测试报告](reports/maintie-v1/local-tests.xml)。GitHub Actions 在 Windows 运行回归，无需模型密钥。

## 技术与工作流

Python 3.11+、LangGraph、DeepSeek API、FastAPI、Pydantic、SQLite FTS5/BM25、可选的 sqlite-vec 混合检索、SqliteSaver。

~~~mermaid
flowchart TD
  A[设备告警] --> B[模型选业务工具]
  B --> C[设备 历史工单 手册]
  C --> B
  B --> D[检查草案]
  T[维修短文本] --> E[模型抽取实体与token跨度]
  E --> F[参考分区案例检索]
  F --> G[固定规则生成受理草稿]
  G --> H[人工确认与持久化检查点]
  D --> H
  H -->|确认| I[幂等写入本地工单]
  H -->|拒绝| J[保留拒绝状态]
  G -->|缺少对象 事项或参考| K[请求补充信息]
~~~

告警工具：query_device、query_work_orders、search_manual、draft_work_order。默认在进程内调用。`TOOL_TRANSPORT=mcp` 时改由 MCP 服务执行，草案仍然不写库，人工确认和幂等插入不变。维修文本在抽取前有一个归一化节点，默认走规则，不额外调用模型；`TEXT_NORMALISER=llm` 才使用冻结的少样本提示。实体抽取后的检索、草稿与审批仍由固定节点执行。案例不是设备履历或维修操作规程。

## Windows 本地启动

~~~powershell
git clone https://github.com/GuoJianFei666/fde-maintenance-agent.git
Set-Location fde-maintenance-agent
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
& .\.venv\Scripts\python.exe -m pip install -e '.[dev]' --no-deps
Copy-Item .env.example .env
# 在本地 .env 填写 DEEPSEEK_API_KEY。
& .\.venv\Scripts\python.exe -m uvicorn react_agent.api:create_app --factory --host 127.0.0.1 --port 8766 --workers 1
~~~

打开 <http://127.0.0.1:8766/docs>。完整固定语料已随项目提供，启动无需下载或训练模型。默认模型为 deepseek-flash；密钥、运行库和虚拟环境均排除出 Git。原始种子数据库无需替换，升级会保留原运行和审批记录。

## 维修文本演示

在 POST /api/maintenance-texts 提交：

~~~json
{
  "event_id": "maintie-demo-001",
  "device_id": "P-101",
  "message": "<id> differential lube pump leaking PO",
  "severity": "warning",
  "source_record_id": "MAINTIE-GOLD-0256"
}
~~~

这条输入来自公开评估分区；P-101 是操作者选择的演示设备映射，不是原始数据中的真实设备编号。source_record_id 可省略；填写时 message 必须与对应原文完全一致，否则返回 409。

返回 awaiting_approval 后，查看 proposal、report.text_extraction、report.evidence 与 report.input_source。将 run_id 和 report.proposal_sha256 用于 POST /api/runs/{run_id}/approval：

~~~json
{"approved": true, "proposal_sha256": "从当前报告复制64位哈希", "note": "已人工核对受理内容"}
~~~

同事件同内容返回原运行；同号不同内容返回 409。草案哈希不匹配也返回 409。重启后使用同一 OPS_DATA_DIR 即可继续审批。

只读入口：

- GET /api/datasets/maintie：固定版本、文件哈希、分区数量与检索规则。
- GET /api/cases/search?q=泵漏油：中文关键词别名检索，返回英文原文与来源。
- GET /api/cases/MAINTIE-GOLD-0256：公开记录和原始 token，不返回标注答案。
- GET /api/runs/{run_id}/trace 与 /report：模型、节点轨迹及 Markdown 报告。

CLI 支持相同流程：

~~~powershell
& .\.venv\Scripts\python.exe -m react_agent.cli dataset
& .\.venv\Scripts\python.exe -m react_agent.cli cases '泵漏油'
& .\.venv\Scripts\python.exe -m react_agent.cli intake --event cli-maintie-001 --device P-101 --message 'hydraulic pump leaking oil'
& .\.venv\Scripts\python.exe -m react_agent.cli report '<run_id>' --out runtime/intake-report.md
~~~

## 复查与评估

~~~powershell
& .\.venv\Scripts\python.exe -m ruff check src tests scripts
& .\.venv\Scripts\python.exe -m pytest -q
# 重新下载固定文件并验证哈希；--direct仅为本次下载绕过系统代理。
& .\.venv\Scripts\python.exe scripts/fetch_maintie.py --out runtime/maintie-download --direct
# 以下命令调用本地配置的真实 DeepSeek，产生 API 用量；选择新路径保留旧记录。
& .\.venv\Scripts\python.exe scripts/evaluate_maintie.py --limit 24 --out runtime/my-evaluation.json
& .\.venv\Scripts\python.exe scripts/verify_maintie_live.py --out runtime/my-workflow.json
& .\.venv\Scripts\python.exe scripts/verify_maintie_http.py --url http://127.0.0.1:8766 --out runtime/my-http.json
~~~

回归的模型替身明确标为 scripted_test；生产 API/CLI 使用真实 DeepSeek。缺少密钥返回 503，供应商或模型输出协议错误返回 502，失败记录保留。验收脚本中的确认动作标为 acceptance_script，不代表用户已完成现场维护。

## MCP 工具服务

四个告警工具是 `query_device`、`query_work_orders`、`search_manual`、`draft_work_order`。`mcp_server/` 用官方 `mcp` Python SDK 暴露它们，传输可以是 stdio，也可以是 streamable HTTP。图的默认仍是 `TOOL_TRANSPORT=inprocess`。`TOOL_TRANSPORT=mcp` 时，同一次工具调用改由 MCP 客户端执行，约束还是同一份 `execute_tool`。

`draft_work_order` 只返回待确认提案，不写工单。写入在 LangGraph 的 `commit_order`，并且只在人工确认附带的提案 SHA256 与当前提案一致时发生。同一 `source_run` 再确认不会插入第二张工单。stdio 子进程不继承 API 密钥。HTTP 进程一次只绑一台设备。细节见 [docs/mcp.md](docs/mcp.md)。

~~~powershell
$env:MAINT_BUSINESS_DB = "runtime/business.db"
$env:MAINT_DEVICE_ID = "P-101"
python -m mcp_server
python -m mcp_server --transport streamable-http --port 8000
~~~

## 混合检索

`RETRIEVER=bm25|dense|hybrid|hybrid_rerank`，默认 `bm25`。`hybrid` 用 Reciprocal Rank Fusion，k=60，融合前 20 条。`hybrid_rerank` 再经交叉编码器保留 10 条。嵌入模型是 `intfloat/multilingual-e5-small`，重排序是 `BAAI/bge-reranker-base`。这五项冻结在 `evals/retrieval/frozen_config.json`。测试集命令不能改它们。域内小库的稠密检索走 sqlite-vec；公开大库因为 sqlite-vec 0.1.9 的 KNN 上限是 4096，改为同一套 L2 归一化向量的精确点积。公式和划分见 [docs/retrieval.md](docs/retrieval.md)。

下面是冻结配置各跑一次测试切分的 Recall@1 和重排序延迟 p50。完整的 Recall@3、MRR、nDCG@3 在同一篇文档和 `reports/` 里。延迟在模型加载之后，Linux CPU。

| 测试集 | 可回答条数 | bm25 | dense | hybrid | hybrid_rerank | 重排序 p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 域内手册，`reports/retrieval-test.json` | 5 | 0.600 | 1.000 | 1.000 | 0.800 | 97.223 ms |
| TechManualQA-700，`reports/retrieval-techmanualqa-test.json` | 300 | 0.360 | 0.500 | 0.427 | 0.543 | 608.182 ms |
| TechQA-RAG-Eval，`reports/retrieval-techqa-test.json` | 450 | 0.409 | 0.398 | 0.431 | 0.420 | 3529.178 ms |

域内 10 条查询没有再扩写，开发集和测试集各 5 条。上表这 5 条不能外推到更大的手册库。TechManualQA-700（CC BY 4.0，Zenodo `17410809`）没有页文本，段落是答案片段，559 段；排序指标不含 50 条不可回答问题。这是片段检索，不是整页检索。在这个片段库上，RRF 的 Recall@1（0.427）低于单独的稠密检索（0.500）。TechQA-RAG-Eval（Apache-2.0，语料 28481 篇）上，RRF 的 Recall@1 高于 BM25 和稠密检索，重排序把 Recall@1 从 0.431 降到 0.420，p50 约 3.5 秒。CI 用 `EMBEDDER=fake`，假嵌入的分数不进这张表。

## MaintNorm

维修文本在实体抽取前有 `normalise_text`。默认 `TEXT_NORMALISER=rules`，不额外调用模型。语料是 nlp-tlp/MaintNorm，MIT，固定提交 `e98ca406f7afffbb0ab3243aa7c922f3b64bc7c8`，仓库不保存约 1.2 万条原文。主评测是合并语料的英文 test。指标是词级精确率、召回率和错误下降率 E.R.R.。

论文 W-NUT 2024 表 7 已核对抄录在 [evals/maintnorm/BASELINES.md](evals/maintnorm/BASELINES.md)。合并语料上，作者的 MaintNorm 行是精确率 99.7、召回率 97.5、E.R.R. 95.8（表中的百分数）。本项目的 LLM、规则、词频替换三列都是「待运行」。

本项目按给定的原始 token 逐词判断。论文里的 ÚFAL / ByT5 基线是自回归解码。两套设置不同，跑完也不能写成复现了那一行。词频替换在并列时有一条论文没写的决胜规则，所以那一列也不是论文 MFR 的复现。

## AssetOpsBench

话语文件 152 条。映射 IoT、FMSR、Workorder、multiagent 共 129 条，`provenance` 为 `real_utterance`。TSFM 23 条未映射。划分在看模型输出之前写定：同一类别内按编号排序，偶数下标 dev，奇数下标 test。dev 66，test 63。另有 5 条合成护栏，单独计分：提示注入后仍待审批、审批哈希不符、同一事件重复、同一事件号不同内容（409）、不存在的设备。

官方场景样本来自 IBM/AssetOpsBench 提交 `e844f646`，Apache-2.0，清单在 `evals/assetopsbench/fixtures/official/MANIFEST.json`。资产档案、3 张工单、通用故障代码和分类表已装进 `query_device`、`query_work_orders` 和 `search_manual`。冷机 6 全时序 2896 行、到 2020-06-26，按需下载；仓库只留首尾两条摘录。草案、审批哈希和 `event_id` 幂等没有改。

| 范围 | 条数 | 期望 |
| --- | ---: | --- |
| 官方档案能回答的检索（1、2、3、4、5、47） | 6 | `needs_information`，禁止起草 |
| 官方数据只覆盖一部分（9、12、104、603） | 4 | `needs_information` |
| 官方样本里没有对应记录 | 116 | `needs_information` |
| 沿用合成手册起草（416、417、419） | 3 | `awaiting_approval` |

6 条问的是站点、MAIN 资产或冷机 6 的档案，不是工单，所以期望仍是 `needs_information`。9 和 12 要到 2020-06-30，文件在 6 月 26 日结束。104 和 603 的 characteristic form 列了 10 个传感器，档案有 12 个。116 条里包括 CWC04009、CWC04013 的年度工单；官方工单只有 3 张，上游话语里的 33、14 不是答案。这 129 条的 DeepSeek 决策分数还没跑。出处、哈希和下载见 [evals/assetopsbench/README.md](evals/assetopsbench/README.md)。

PHMForge（CC BY 4.0，修订 `7a7e8a5f`）有 99 条场景，工具是 `load_dataset`、`train_rul_model` 一类。场景文本可按需下载，约 2 GB 的信号不下载，也没有导入这四个工具。

## 离线测试与真实模型

离线命令不调用 DeepSeek。CI 只跑下面前两行：

~~~powershell
python -m ruff check src tests scripts mcp_server evals
python -m pytest -q
python evals/assetopsbench/run.py --mode scripted --out runtime/assetopsbench-scripted.json
python evals/assetopsbench/run.py --mode scripted --cases evals/assetopsbench/cases/guardrails.jsonl --out runtime/assetopsbench-guardrails.json
python evals/retrieval/run.py --split test --embedder fake --out runtime/retrieval-test-fake.json
python evals/maintnorm/evaluate.py --fixture evals/maintnorm/fixtures/mini --split test --method rules --out runtime/maintnorm-mini-rules.json
~~~

本地 `pytest` 为 71 项。GitHub Actions 工作流 `Check maintenance workflow` 的 `test` 作业在 `windows-latest`、Python 3.11 上跑 `ruff` 和 `pytest`，不读 `DEEPSEEK_API_KEY`，不下载嵌入权重或大数据。官方样本在 `.gitattributes` 里标成 `-text`，Windows 检出不改换行。

下面这些命令会调用本地 `.env` 里的 `DEEPSEEK_API_KEY`。没有密钥时退出，不写分数。本次没有跑，所以没有告警决策分数，也没有 MaintNorm 的 LLM 分数：

~~~powershell
python evals/assetopsbench/run.py --mode live --out runtime/assetopsbench-live.json
python evals/maintnorm/fetch.py --out runtime/maintnorm
python evals/maintnorm/evaluate.py --data runtime/maintnorm --subset combined --split test --method llm --out runtime/maintnorm-test-llm.json
python evals/retrieval/run.py --split test --embedder sentence-transformers --out runtime/retrieval-test.json
~~~

检索那条如果指向已有的 `reports/retrieval-test.json`，脚本会拒绝覆盖。公开语料的对应命令在 [docs/retrieval.md](docs/retrieval.md)。评测索引见 [docs/evals.md](docs/evals.md)。

## 文件导读

| 文件 | 职责 |
|---|---|
| src/react_agent/maintie.py | 固定文件校验、分区、独立案例索引与来源 |
| src/react_agent/extraction.py | 维修文本 Prompt、工具协议及原文跨度校验 |
| src/react_agent/intake.py | 实体抽取、案例检索、缺项检查与受理草稿节点 |
| src/react_agent/evaluation.py | 顶层类别投影与严格实体计分 |
| src/react_agent/graph.py | 两条路径路由、人工确认及工单写入 |
| src/react_agent/service.py | 持久化运行、审批恢复、轨迹和报告 |
| src/react_agent/tools.py、store.py | 原告警业务工具、手册检索与工单幂等 |
| mcp_server/ | 四个工具的 MCP 服务，草案不写库 |
| evals/assetopsbench/ | AssetOpsBench 子集转换和告警评测 |
| evals/maintnorm/ | MaintNorm 下载、词级指标和论文对照表 |
| evals/retrieval/ | BM25、稠密、RRF 和重排序的手册检索评测 |
| src/react_agent/api.py、cli.py | REST 与命令行入口 |
| docs/mcp.md | MCP 传输、审批哈希和设备绑定 |
| docs/retrieval.md | 冻结配置、三份测试集的完整指标 |
| docs/evals.md | 告警评测与 MaintNorm 的命令索引 |
| docs/maintie.md | 数据接入、评估口径、误差与复查方法 |
| docs/resume-and-interview.md | 项目正文、源码路线与面试参考 |

项目未连接真实 MES/ERP 或设备控制接口。公开维修短文本可以支撑文本处理和案例检索演示；具体维护方法仍需适用规程与维护人员判断。
