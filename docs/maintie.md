# MaintIE 数据接入与维修文本受理

## 数据与来源

本轮使用作者仓库 nlp-tlp/maintie 的 gold_release.json，固定提交 825e7710e4129598da997276a38b3cb40b200bc2。原始 JSON 为 817,880 字节，SHA256 为 ef811cf4ffd0c90e6a13b1369e24e9d1d08f9a294d873ab4fb1a580096d7d6e0。逐条读取实际有 1,076 条记录；上游 README 有一处 1,067 的文字差异，本项目按原文件实数记录。

作者将文本、标注方案及模型按 MIT 发布。原始 JSON、原 LICENSE 与原 README 字节随包保存在 src/react_agent/data/maintie；manifest.json 记录文件哈希、固定 URL、论文、许可与获取日期。原始数据没有改写；本项目新增索引、分区、中文术语别名和模型预测。保留作者署名与论文引用：

Tyler K. Bikaun, Tim French, Michael Stewart, Wei Liu, Melinda Hodkiewicz. 2024. MaintIE: A Fine-Grained Annotation Schema and Benchmark for Information Extraction from Maintenance Short Texts. LREC-COLING 2024, pp.10939–10951. <https://aclanthology.org/2024.lrec-main.954/>

记录字段为 text、tokens、entities、relations。start/end 是左闭右开的 token 跨度；关系端点指向实体列表。导入前检查原文件哈希、条数、实体类别、跨度与关系端点，任何一项失败即停止导入。

文本已规范化和脱敏，含 <id>、<num>、<date>、<sensitive> 占位符。语料不是完整设备履历，也不提供标准维修规程。本轮未使用 silver 数据，也未训练、下载上游实体模型。

## 分区与检索

归一化仅用于分组、检索去重与分区，不覆盖原文。先去掉脱敏占位符、统一大小写、提取英文词与中文字符，再计算 SHA256。前8个十六进制字符转整数，模5等于0的记录进入评估区，其余进入参考区。同一归一化文本总在同一分区。

实际分区为参考869条、评估207条；评估区含203个不同归一化文本。SQLite FTS5 只索引参考区。检索按 BM25 排序，排除与查询归一化文本完全相同的记录；返回 ID、原文、行序号、来源、版本、文本哈希和原始文件哈希，不返回金标实体或关系。

案例 ID 为 MAINTIE-GOLD-加四位从0开始的原文件记录序号；source URL 的 record-N 是本项目定义的记录定位符，精确定位仍以 row_index 和原始哈希为准。

中文检索使用公开的小型术语别名表，例如“泵→pump/pumps”“漏油→oil/leak/leaking”。它是词法检索，不是向量检索或完整中英翻译。当前没有独立人工标注的案例相关性集合，因此没有报告检索准确率或 Recall@K。

## 请求与工作流

POST /api/maintenance-texts 接收 event_id、device_id、message、severity，可附 source_record_id。message 最多500字符和160个本项目分词 token；超出返回422。若填写公开来源编号，服务先核对原文完全一致，再使用原始 token。

1. 检查设备与事件号；相同事件相同输入直接返回原运行。
2. DeepSeek 接收原文和 token，一次 submit_extraction 调用返回五类实体的跨度。
3. 校验结构、类别、索引范围、重复跨度和纯占位符；显示文本由原 token 切片生成。
4. 固定节点检索参考案例；检查是否有对象、事项及可检索参考。
5. 缺项则 needs_information；材料可用于受理时，固定模板生成复核草稿。
6. LangGraph interrupt 保存检查点；外部确认绑定草稿 SHA256。
7. 确认后写入本地受理工单；拒绝不写入；同一 source_run 只创建一次。

实体跨度校验保证输出取自原 token，不证明类别语义正确。模型不生成维修指令；原文的 change out/replace 等词仅作为记录中的活动提取，草稿要求现场复核，不能直接当成对当前设备的执行命令。

P-101 等编号仍是本项目的演示资产。公开文本与该编号的关联是请求中的演示映射；公开案例没有插入 query_work_orders 所返回的设备历史。记录分别标明 public_maintie_short_text、user_supplied_text 与 public_corpus_demo_intake。

## 实际评估

执行脚本 scripts/evaluate_maintie.py，使用真实 DeepSeek deepseek-flash。从203个不同评估文本中按文本 SHA256 升序选前24条，不按主题筛选。Prompt 固定为 maintie-intake-v1，内置一个本项目手写示例，没有读取待测标注；模型输入只有原文及原始 token。实体抽取发生在案例检索之前。

金标细粒度类别投影到 PhysicalObject、State、Process、Activity、Property 五类。以 (start,end,顶层类别) 集合严格匹配，保留嵌套实体；重复金标三元组只计一次。失败输出按空预测计入漏检，不从分母删除。

| 指标 | 实际结果 |
|---|---|
| 文本数量与结构校验 | 24条；24条输出通过结构校验 |
| 实体计数 | TP=62、FP=17、FN=12 |
| micro-Precision | 0.7848 |
| micro-Recall | 0.8378 |
| micro-F1 | 0.8105 |
| 整条实体集合完全一致 | 9/24 |
| 实际API返回总用量 | 21,463 tokens |

这是一份固定小样本评估，未覆盖全部203个不同评估文本，也不是 MaintIE 原论文复现。原始预测、原始工具参数、逐条期望、实际模型名、用量和计分均保存在 reports/maintie-v1/evaluation.json。

误差集中在 PhysicalObject 的嵌套名称与边界，如“TV”与“TV monitor”的范围不同，物理对象F1为0.7416。Property 在该24条样本中有1个金标，未命中，并有2个误报；保留原始结果，未为提高指标删除该类或改变计分。本轮没有根据这24条的答案修改 Prompt 后再重报同组结果。

## 实际流程与HTTP验证

scripts/verify_maintie_live.py 的三个手写受理场景均调用真实模型：

- hydraulic pump leaking oil：待审批阶段0单，重建服务后确认写1单，重复确认仍1单。
- electric motor bearings damaged：拒绝后0单。
- please help：缺少对象与事项，needs_information，0单。

验收脚本确认动作标为 acceptance_script。三个场景实际用量共2,615 tokens。

另通过真实本机 TCP HTTP 接口，以公开评估记录 MAINTIE-GOLD-0256 为输入，完成来源匹配、抽取、案例隔离、重复事件、待审批不写单和 Markdown 报告检查。该请求实际用量893 tokens，保留待审批运行供人工查看。

本轮共28次真实模型调用，API返回用量合计24,971 tokens；包括24次评估、3次流程验收和1次HTTP演示。这些记录不能作为工业故障诊断准确率或生产收益。

## 复查入口

- 数据版本与分区：GET /api/datasets/maintie，或 CLI dataset。
- 案例检索：GET /api/cases/search?q=pump%20leaking。
- 原始数据复下：scripts/fetch_maintie.py，所有文件哈希一致才写入；不会执行上游代码。
- 离线回归：tests/test_maintie.py、tests/test_evaluation.py 与原告警测试。
- 实测结果：reports/maintie-v1/evaluation.json、workflow-live.json、http-live.json。

后续若优化 Prompt，应先另设开发集，再用尚未观察答案的评估样本报告新结果。若补充真实设备数据，应另行确认资产映射、适用规程和接口契约。
