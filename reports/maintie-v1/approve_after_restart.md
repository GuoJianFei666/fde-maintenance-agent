# 维修文本受理记录

运行编号：7c67e1840e764d9a8cc09e3780ab73be
状态：completed
设备：P-101
告警：hydraulic pump leaking oil
执行方式：live_deepseek
数据类型：公开MaintIE案例与本地演示受理流程；所选设备为演示资产

## 工单草案

维修受理复核：hydraulic pump leaking oil
优先级：medium

依据用户原始描述抽取受理字段，并附公开维修短文本供人工比较；未推断故障原因或维修效果。

- 核对所选设备编号、现场部件与用户原始描述是否一致。
- 补充发生时间、当前状态、相关测量值及适用作业规程，再由维护人员判断处理方法。
- 相似案例仅作受理参考；原文中的历史活动不能直接转成当前设备的维修指令。

## 原文实体抽取

跨度使用从0开始、左闭右开的token编号；仅评估五个顶层类别。

- PhysicalObject [0, 2): hydraulic pump
- PhysicalObject [1, 2): pump
- Process [2, 3): leaking
- PhysicalObject [3, 4): oil

保留英文原文；中文段落为本项目生成的受理说明。公开案例不代表当前设备的维修履历或适用操作规程。
MaintIE版本：825e7710e4129598da997276a38b3cb40b200bc2
原始数据SHA256：ef811cf4ffd0c90e6a13b1369e24e9d1d08f9a294d873ab4fb1a580096d7d6e0

## 引用原文

[MAINTIE-GOLD-0429] https://github.com/nlp-tlp/maintie/blob/825e7710e4129598da997276a38b3cb40b200bc2/data/gold_release.json#record-429 / 825e7710e4129598da997276a38b3cb40b200bc2

replace hydraulic pump coupling

[MAINTIE-GOLD-0631] https://github.com/nlp-tlp/maintie/blob/825e7710e4129598da997276a38b3cb40b200bc2/data/gold_release.json#record-631 / 825e7710e4129598da997276a38b3cb40b200bc2

<id> - hydraulic oil leak from environmental

[MAINTIE-GOLD-0152] https://github.com/nlp-tlp/maintie/blob/825e7710e4129598da997276a38b3cb40b200bc2/data/gold_release.json#record-152 / 825e7710e4129598da997276a38b3cb40b200bc2

<id> change out leaking hydraulic hose

## 写入结果

工单编号：WO-7C67E1840E76
人工确认后已写入本地演示工单库。

## 运行版本

Prompt：maintie-intake-v1
语料：demo-v1
模型调用次数：1
用量：{'input_tokens': 787, 'output_tokens': 114, 'total_tokens': 901}
