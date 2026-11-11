# 评测

两条评测都把每次运行写成 JSON：git 提交、模型名、提示词版本和哈希、数据集版本或提交、种子、时间。开发切分用来检查流程，测试切分使用事先冻结的提示词。没有密钥时不要填模型分数。

告警路径的改编用例见 [evals/assetopsbench/README.md](../evals/assetopsbench/README.md)。129 条来自 AssetOpsBench 话语，5 条护栏是合成的，分开报告。维修文本的归一化和屏蔽见 [evals/maintnorm/README.md](../evals/maintnorm/README.md)。论文基线只抄在 [evals/maintnorm/BASELINES.md](../evals/maintnorm/BASELINES.md)。手册检索的四种模式，以及 TechManualQA-700、TechQA-RAG-Eval，见 [retrieval.md](retrieval.md)。域内中英手册查询仍是原来的 10 条。

PHMForge（`ibm-research/PHMForge`，CC BY 4.0）有 99 个场景和 `required_tools` 字段，适合做 MCP 工具编排对照。这次没有跑。数据集大约 2 GB，里面是轴承和发动机的信号，不是这四个告警工具能调用的接口。场景要求的工具包括 `load_dataset`、`train_rul_model` 一类，和 `query_device`、`search_manual`、`draft_work_order` 对不上。留作后续。

CI 使用脚本模型和小样例，不读取 `DEEPSEEK_API_KEY`。真实运行是本地命令，结果文件放在被 git 忽略的 `runtime/`。
