# 评测

两条评测都把每次运行写成 JSON：git 提交、模型名、提示词版本和哈希、数据集版本或提交、种子、时间。开发切分用来检查流程，测试切分使用事先冻结的提示词。没有密钥时不要填模型分数。

告警路径的改编用例见 [evals/assetopsbench/README.md](../evals/assetopsbench/README.md)。维修文本的归一化和屏蔽见 [evals/maintnorm/README.md](../evals/maintnorm/README.md)。论文基线只抄在 [evals/maintnorm/BASELINES.md](../evals/maintnorm/BASELINES.md)。

CI 使用脚本模型和小样例，不读取 `DEEPSEEK_API_KEY`。真实运行是本地命令，结果文件放在被 git 忽略的 `runtime/`。
