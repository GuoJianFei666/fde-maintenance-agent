# 上游来源与改造范围

本项目改造自 [langchain-ai/react-agent](https://github.com/langchain-ai/react-agent)。

- 上游固定提交：`087d90d0c876668956b733a104f1708cef0128e2`（2026-10-20）。
- 许可：MIT，保留 LICENSE 中 LangChain 的版权和许可。
- 复用基础：graph.py 的 StateGraph、模型与工具循环、条件路由，以及 state.py 的消息累积结构。
- 本项目增量：设备档案与历史工单工具、中文手册检索、受约束工单草案、人工确认中断、SQLite持久化和幂等写入、REST接口、运行轨迹、测试及交付说明。
- 上游默认 Tavily/Anthropic 搜索示例改为 DeepSeek 和本地演示数据。应用不依赖 LangGraph Studio、Docker 或 GPU。

开发使用 AI 辅助。设备、手册及工单是本项目构造的演示数据，不对应真实工业客户或生产系统。

## 本轮公开数据来源

新增MaintIE维修文本受理路径，使用作者仓库[nlp-tlp/maintie](https://github.com/nlp-tlp/maintie)的专家标注集，固定提交825e7710e4129598da997276a38b3cb40b200bc2。原始JSON、作者MIT许可和README原字节保存在src/react_agent/data/maintie，manifest记录来源、SHA256与条数。作者论文见[MaintIE，LREC-COLING 2024](https://aclanthology.org/2024.lrec-main.954/)。

本轮未复用作者的模型训练代码，也未声称研发或标注该语料。本项目新增的是文件校验、参考/评估分区、案例索引、DeepSeek顶层实体抽取与计分、受理草稿、审批接口和交付报告。公开案例单独存放，不作为演示设备的真实历史。

## 工具协议与后续公开评测

MCP 服务使用官方 Python SDK `mcp`，MIT 许可。本项目没有改 SDK 源码，只注册了四个已有工具。

AssetOpsBench 来自 IBM，Apache-2.0，固定提交 `e844f6468c6c68b328022e7ca8e31da140842cc7`。话语样本来自 Hugging Face 数据集 `ibm-research/AssetOpsBench`，修订 `5e25bb7f2cd37fb68b9a9e1f99d170ca5be7ce17`。本仓库只保留 12 条话语和一条标明的合成探针，不收录 CouchDB 或传感器归档。英文演示手册是本项目编写的。出处和许可见 `evals/assetopsbench/NOTICE.md`。

MaintNorm 来自 [nlp-tlp/maintnorm](https://github.com/nlp-tlp/maintnorm)，MIT，固定提交 `e98ca406f7afffbb0ab3243aa7c922f3b64bc7c8`。语料按脚本下载，不放进 Git。论文基线只抄 W-NUT 2024 表 7，见 `evals/maintnorm/BASELINES.md`。少样本例句是本项目编写的，不是从官方测试集抽出来的。
