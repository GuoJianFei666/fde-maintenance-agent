# MaintNorm 归一化与屏蔽

语料来自 [nlp-tlp/maintnorm](https://github.com/nlp-tlp/maintnorm)，MIT 许可，固定提交 `e98ca406f7afffbb0ab3243aa7c922f3b64bc7c8`。Hugging Face 数据集为 `nlp-tlp/MaintNorm`。论文是 Bikaun、Hodkiewicz 与 Liu，W-NUT 2024。正文见 [BASELINES.md](BASELINES.md)。

仓库不保存这 12,000 条文本。`fetch.py` 按官方 `train.norm`、`val.norm`、`test.norm` 下载四个子集：`combined`、`company_a`、`company_b`、`company_c`。`val.norm` 是论文里的开发集。主评测是合并语料的英文 test。

每条记录用空行分开，每一行是 `原始 token<TAB>标准形式`。标准形式可以是多个词、`<id>`、`<num>`、`<date>`、`<sensitive>`，也可以为空，表示删掉这个 token。计分按原始 token，不把 1:N 拆开。需要修改并且预测相同，记 TP；不该改却改了，记 FP；该改但没改对，只记 FN。E.R.R. = (TP − FP) / (TP + FN)。模型接口按给定的原始 token 逐词返回，避免自己重新分词。这和论文里的 ByT5 自回归解码不是同一种设置，所以结果不能写成复现了 ByT5。

规则基线只做少量缩写展开、日期和纯数字屏蔽、形如 `XH531` 的资产编号屏蔽，以及一份很短的全大写普通词小写表。它不调用模型。词频替换只从当前子集的训练集统计，测试集不参与统计。少样本提示写在 `src/react_agent/data/normalise_prompt.json`，例句是本项目编写的，并标成在看测试集之前冻结。测试集评分会拒绝未冻结的提示，也会拒绝例句原文出现在待评分切分里。

维修文本图在抽取之前有 `normalise_text` 节点。默认 `TEXT_NORMALISER=rules`。带公开 MaintIE 记录编号、且原文被锁定的输入不会改写。`off` 保持原文。`llm` 会多一次模型调用。

## 本地命令

~~~powershell
python evals/maintnorm/fetch.py --out runtime/maintnorm
python evals/maintnorm/evaluate.py --data runtime/maintnorm --subset combined --split val --method rules --out runtime/maintnorm-val-rules.json
python evals/maintnorm/evaluate.py --data runtime/maintnorm --subset combined --split test --method lai --out runtime/maintnorm-test-lai.json
python evals/maintnorm/evaluate.py --data runtime/maintnorm --subset combined --split test --method rules --out runtime/maintnorm-test-rules.json
python evals/maintnorm/evaluate.py --data runtime/maintnorm --subset combined --split test --method mfr --out runtime/maintnorm-test-mfr.json
# 下面这条才会调用 DeepSeek。没有 DEEPSEEK_API_KEY 时直接退出，不写分数。
python evals/maintnorm/evaluate.py --data runtime/maintnorm --subset combined --split test --method llm --out runtime/maintnorm-test-llm.json
~~~

结果 JSON 含 git 提交、模型名、提示词版本和哈希、数据提交、切分文件哈希、种子和时间。`scores_are_model_results` 只在真实模型名下为真。CI 用 `evals/maintnorm/fixtures/mini` 里的人造小样例，不下载语料，也不调用接口。
