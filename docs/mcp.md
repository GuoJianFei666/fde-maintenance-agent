# 工具的 MCP 接口

四个业务工具是 `query_device`、`query_work_orders`、`search_manual`、`draft_work_order`。MCP 服务在 `mcp_server/`，使用官方 `mcp` Python SDK。默认传输是 stdio，也可以起 streamable HTTP。

草案工具只返回待确认提案。工单插入仍在 LangGraph 的 `commit_order` 节点，而且只在人工确认的提案 SHA256 与当前提案一致时执行。同一 `source_run` 重复确认不会插入第二张工单。这些约束在进程内模式和 MCP 模式里用的是同一份 `execute_tool`。

`TOOL_TRANSPORT=inprocess` 是默认值，工具在当前进程执行。`TOOL_TRANSPORT=mcp` 时，图的工具节点通过 MCP 客户端调用服务。stdio 模式会为一次运行拉起一个子进程，并用 `MAINT_BUSINESS_DB` 和 `MAINT_DEVICE_ID` 绑住数据库和告警设备。子进程不继承 API 密钥。已有的 HTTP 服务可以用 `MCP_URL` 连接，例如 `http://127.0.0.1:8000/mcp`。这个 HTTP 进程一次只绑一台设备，适合外部客户端调试，不适合并发跑多台设备。

客户端使用官方 SDK 的 `ClientSession`。`langchain-mcp-adapters` 包的是同一套会话接口；这里直接调用 SDK，避免再装一套代理依赖。

单独启动服务：

~~~powershell
$env:MAINT_BUSINESS_DB = "runtime/business.db"
$env:MAINT_DEVICE_ID = "P-101"
python -m mcp_server
python -m mcp_server --transport streamable-http --port 8000
~~~

服务进程的标准输出是协议通道，日志打到标准错误。不要把密钥写进启动参数。
