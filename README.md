# 设备告警与维修文本受理 Agent

基于 LangGraph 官方 ReAct 模板改造的个人 FDE 项目，提供两条可运行流程：

- **设备告警**：模型选择设备、历史工单与手册工具，生成检查草案，再由人工确认是否写入工单。
- **维修文本受理**：接入公开 MaintIE 专家标注语料，模型抽取原文实体，固定工作流检索案例并生成受理草稿，人工确认后入库。

项目在 AI 辅助下开发，当前为 Windows 本地单进程 POC。设备、演示手册和初始工单为合成材料；MaintIE 为作者公开的脱敏维修短文本，二者分别记录来源。上游与许可见 [UPSTREAM.md](UPSTREAM.md)，数据接入与复查见 [docs/maintie.md](docs/maintie.md)。

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

Python 3.11+、LangGraph、DeepSeek API、FastAPI、Pydantic、SQLite FTS5/BM25、SqliteSaver。

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

## MCP、AssetOpsBench 与 MaintNorm

工具服务、传输开关和审批边界见 [docs/mcp.md](docs/mcp.md)。两条评测的命令和口径见 [docs/evals.md](docs/evals.md)。

告警评测从 AssetOpsBench 选出 12 条与告警、手册或工单有关的话语，并加 1 条标明的合成探针，共 13 条。上游计数没有对应的本地数据时，期望是 `needs_information`，不把论文或数据集里的条数当成答案。英文设备、手册和历史工单在 `evals/assetopsbench/fixtures/english_demo.json`，标明为改编后的合成数据。

MaintNorm 主评测是合并语料的英文 test。指标是词级精确率、召回率和错误下降率。论文表 7 的数字抄在 [evals/maintnorm/BASELINES.md](evals/maintnorm/BASELINES.md)。本项目三列都是“待运行”。配置好本地密钥后再跑，不要把脚本模式的输出填进那一列。

~~~powershell
python evals/assetopsbench/run.py --mode scripted --out runtime/assetopsbench-scripted.json
python evals/assetopsbench/run.py --mode live --out runtime/assetopsbench-live.json
python evals/maintnorm/fetch.py --out runtime/maintnorm
python evals/maintnorm/evaluate.py --data runtime/maintnorm --subset combined --split test --method rules --out runtime/maintnorm-test-rules.json
python evals/maintnorm/evaluate.py --data runtime/maintnorm --subset combined --split test --method llm --out runtime/maintnorm-test-llm.json
~~~

`live` 和 `llm` 需要本地 `.env` 里的 `DEEPSEEK_API_KEY`。没有密钥时命令退出，不写分数。CI 不跑这两条。

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
| src/react_agent/api.py、cli.py | REST 与命令行入口 |
| docs/maintie.md | 数据接入、评估口径、误差与复查方法 |
| docs/resume-and-interview.md | 项目正文、源码路线与面试参考 |

项目未连接真实 MES/ERP 或设备控制接口。公开维修短文本可以支撑文本处理和案例检索演示；具体维护方法仍需适用规程与维护人员判断。
