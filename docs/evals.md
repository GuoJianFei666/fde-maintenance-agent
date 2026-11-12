# 评测

两条评测都把每次运行写成 JSON：git 提交、模型名、提示词版本和哈希、数据集版本或提交、种子、时间。开发切分用来检查流程，测试切分使用事先冻结的提示词。没有密钥时不要填模型分数。给面试阅读的摘要，包括检索表、129 条告警用例能测什么、以及留空的 DeepSeek 分数，写在仓库 [README.md](../README.md)。

MaintNorm 按给定的原始 token 逐词计分。论文表 7 的 ByT5 基线是自回归解码。两套设置不同，本项目的三列保持「待运行」，不把抄录的论文数字写成自己的复现。

告警路径的改编用例见 [evals/assetopsbench/README.md](../evals/assetopsbench/README.md)。129 条来自 AssetOpsBench 话语，5 条护栏是合成的，分开报告。维修文本的归一化和屏蔽见 [evals/maintnorm/README.md](../evals/maintnorm/README.md)。论文基线只抄在 [evals/maintnorm/BASELINES.md](../evals/maintnorm/BASELINES.md)。手册检索的四种模式，以及 TechManualQA-700、TechQA-RAG-Eval，见 [retrieval.md](retrieval.md)。域内中英手册查询仍是原来的 10 条。

AssetOpsBench 的官方场景小样本已经装进告警评测库。129 条里，6 条能用资产档案回答检索，4 条只能部分对照，116 条仍然没有对应的官方记录；能起草的仍是原来的 3 条。冷机 6 全时序和 PHMForge 信号都按需下载，命令在 [evals/assetopsbench/README.md](../evals/assetopsbench/README.md)。

PHMForge（`ibm-research/PHMForge`，CC BY 4.0，修订 `7a7e8a5f140d89c562c0b2f870f500e259237b8e`）的场景文件 `data/all.jsonl` 有 99 条。工具名是 `load_dataset`、`train_rul_model` 一类。这次没有把这些场景装进四个告警工具，也没有下载大约 2 GB 的信号。

CI 使用脚本模型和小样例，不读取 `DEEPSEEK_API_KEY`。真实运行是本地命令，结果文件放在被 git 忽略的 `runtime/`。
