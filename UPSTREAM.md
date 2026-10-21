# 上游来源与改造范围

本项目改造自 [langchain-ai/react-agent](https://github.com/langchain-ai/react-agent)。

- 上游固定提交：`087d90d0c876668956b733a104f1708cef0128e2`（2026-10-20）。
- 许可：MIT，保留 LICENSE 中 LangChain 的版权和许可。
- 复用基础：graph.py 的 StateGraph、模型与工具循环、条件路由，以及 state.py 的消息累积结构。
- 本项目增量：设备档案与历史工单工具、中文手册检索、受约束工单草案、人工确认中断、SQLite持久化和幂等写入、REST接口、运行轨迹、测试及交付说明。
- 上游默认 Tavily/Anthropic 搜索示例改为 DeepSeek 和本地演示数据。应用不依赖 LangGraph Studio、Docker 或 GPU。

开发使用 AI 辅助。设备、手册及工单是本项目构造的演示数据，不对应真实工业客户或生产系统。
