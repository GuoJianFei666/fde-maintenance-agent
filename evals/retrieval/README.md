# 手册检索评测

说明和 RRF 公式见 [docs/retrieval.md](../../docs/retrieval.md)。标注文件是 `labels.json`，开发集和测试集各 5 条。调参只改开发集。测试集读取 `frozen_config.json`，拒绝命令行上的模型、k、N 和 top-k。

~~~powershell
py -3 evals/retrieval/run.py --split dev --embedder fake --out runtime/retrieval-dev-fake.json
py -3 evals/retrieval/run.py --split test --embedder fake --out runtime/retrieval-test-fake.json
py -3 -m pip install "sentence-transformers>=3,<6"
py -3 evals/retrieval/run.py --split dev --embedder sentence-transformers --out runtime/retrieval-dev.json
py -3 evals/retrieval/run.py --split test --embedder sentence-transformers --out runtime/retrieval-test.json
~~~

`fake` 的 JSON 里 `scores_are_model_results` 为 false。测试集结果里的 `config_sha256` 和 `frozen_config_sha256` 用来核对冻结配置。真实模型的测试表见 [docs/retrieval.md](../../docs/retrieval.md)。
