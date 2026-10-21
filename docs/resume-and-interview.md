# 项目经历与面试展开

设备告警处置Agent与工单工作流｜2026.10｜AI辅助开源改造与本地POC
技术栈：Python、LangGraph、DeepSeek API、FastAPI、SQLite FTS5、Pydantic
基于LangGraph官方ReAct模板改造设备告警处置Agent，封装设备查询、手册检索、历史工单和草案生成4类工具，接入DeepSeek真实Tool Calling。
采用中文二元词组与FTS5/BM25检索手册，校验本次检索证据及设备范围，输出原文、来源和版本；编排人工确认、SQLite检查点与幂等工单写入。
完成REST接口、过程记录和Markdown报告；24项本地回归通过，3个真实模型样例验证确认、拒绝与信息不足分支，另完成真实HTTP联调。

# FDE项目面试参考问答

以下为基于本轮实际代码与检查的参考表达，尚未进行用户模拟面试考核。

## 1 你从上游复用了什么，实际新增了什么？
我在AI辅助下，以LangGraph官方ReAct模板的模型—工具循环和消息状态为基础，固定了上游提交。原例子使用通用搜索工具。我将其改为设备档案、历史工单、手册检索和工单草案四类业务工具，新增人工确认节点、SQLite持久化和幂等写入，以及REST接口、运行轨迹和交付报告。许可和来源保留在UPSTREAM及LICENSE。

## 2 Agent和工作流各自负责什么？
Agent根据告警和查询结果选择工具、填写参数并生成草案。固定图结构负责进入待审批状态、接受外部确认和执行写库。模型工具列表中没有直接创建工单的工具，因而“模型说已写入”不会改变数据库。

## 3 一条请求怎样流转？
POST /api/alarms提交事件号、设备编号、告警说明和级别。系统先检查设备和事件是否存在，再进入StateGraph。模型查询设备、历史工单和手册，调用draft_work_order形成草案。human_review通过interrupt暂停并保存检查点。确认请求带草案哈希，恢复后才进入commit_order；拒绝则保留rejected状态。报告保存引用和实际模型用量。

## 4 你的RAG怎样实现，引用怎样检查？
我把演示手册保存为带ID、设备类型、原文、来源和版本的片段，用中文重叠二元词组构造FTS5索引，按BM25排序。检索只返回当前设备类型及通用片段。生成草案时再检查evidence_ids是否属于本次运行已返回的片段，并再次检查设备类型。这个检查保证出处和范围合法，语义是否充分仍要结合手册与人工复核。

## 5 如何处理重复请求和中途重启？
event_id绑定告警内容哈希，相同事件相同内容返回原运行，同号不同内容返回409。工单表的source_run有唯一约束，重复确认只返回已存在工单。LangGraph检查点用SQLite，thread_id是run_id。实测服务关闭后重建实例，待审批任务能继续确认，确认阶段没有再调用模型。

## 6 DeepSeek或工具失败时怎么办？
缺少密钥返回503；供应商调用失败返回502并记录安全的错误类别，不记录认证请求头。工具参数错误、越权设备编号、未检索引用或先草案后查询会返回显式工具错误给模型，并保留轨迹。模型最多运行配置的轮数，耗尽后保留failed状态。缺少依据则是needs_information，不算工单创建成功。

## 7 实际验证了哪些结果？
本地24项回归检查覆盖检索、引用、审批、重复事件、重启及错误状态。另用真实DeepSeek测试三个指定样例：泵告警确认后写入；电机告警拒绝后不写入；未知固件错误码返回待补信息。还通过真实HTTP检查接口并留下待确认运行。这是三个选定样例的POC结果，不能推广为生产准确率。

## 8 这个项目如何对应客户交付？
它展示需求拆解、工具与数据契约、知识配置、模型联调、审批流、问题定位和交付文档。当前是个人演示业务。真实客户交付的下一步是确认业务权限、真实字段与接口契约、验收样例和负责人，再增加访问控制与多进程部署方案。我没有把本地演示写成已对接真实MES或已有工业客户。

# 核心代码讲解路线

1. api.py:create_app / cli.py:main：输入告警、人工确认或报告请求。
2. models.py：字段、类型、范围和草案哈希；Approval.approved使用严格布尔值。
3. service.py:diagnose：设备检查和event_id内容绑定；run_id传为LangGraph thread_id。
4. graph.py:call_model：真实DeepSeek调用、轮数限制、模型/工具名、实际tokens和耗时。
5. tools.py:execute_tool：4类工具；校验调用顺序、当前设备和本次检索引用。
6. store.py:search：中文二元词组 → 参数化FTS5 MATCH → BM25 → 原文与版本。
7. graph.py:human_review：interrupt保存位置；没有确认前不执行写入。
8. service.py:decide与graph.py:commit_order：绑定草案哈希、恢复检查点、幂等写工单。
9. store.py:create_order：source_run唯一；service.py:report_markdown与trace交付运行记录。
10. llm.py：DeepSeek兼容Chat Completion Tool Calls，显式禁用thinking以简化工具历史，错误类别不含密钥。

入口（PowerShell）：.venv/Scripts/python.exe -m uvicorn react_agent.api:create_app --factory --host 127.0.0.1 --port 8765 --workers 1。
演示：打开/docs，提交/api/alarms，读取proposal和report.proposal_sha256，再调用approval；查看trace和report。
失败例：本轮未知SIG900错误码没有充分手册依据，真实模型返回needs_information，未写工单。
