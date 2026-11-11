# 上游许可

`fixtures/upstream_sample.jsonl` 和由它生成的用例里的话语原文，取自 IBM AssetOpsBench，许可 Apache-2.0。

- 仓库：<https://github.com/IBM/AssetOpsBench>
- 提交：`e844f6468c6c68b328022e7ca8e31da140842cc7`
- 许可文本：<https://github.com/IBM/AssetOpsBench/blob/e844f6468c6c68b328022e7ca8e31da140842cc7/LICENSE>
- 数据集：<https://huggingface.co/datasets/ibm-research/AssetOpsBench>，修订 `5e25bb7f2cd37fb68b9a9e1f99d170ca5be7ce17`

`cases/alarm_subset.jsonl` 收录上述修订里 IoT、FMSR、Workorder、multiagent 共 129 条话语原文，并改写成当前四个工具能表达的评测。TSFM 23 条没有收录。`fixtures/upstream_sample.jsonl` 仍是其中 12 条的小样。

`fixtures/official/` 里的 CSV、JSON 和 scenario 文本是上述提交中 `src/couchdb/scenarios_data` 的原字节，Apache-2.0。冷机 6 全文件、液压泵、地铁泵和电机时序按 `fixtures/official/MANIFEST.json` 的哈希下载，不放进 Git。`chiller_6_excerpt.json` 是全文件的第一条和最后一条，不是另写的读数。合成英文手册、演示历史工单和 `cases/guardrails.jsonl` 是本项目编写的，不属于上游数据。再分发这些话语和样本时请保留 Apache-2.0 许可和上述出处。
