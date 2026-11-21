# 化工分离设计 Few-shot 示例

这里的 Notebook 是三个化工角色的提示词示范，作用与原工程 few_shots 相对应。
模型在调用时阅读少量案例，学习如何提出任务、引用证据和响应审查；不更新模型权重。

## 当前示例与来源

包含设计澄清、初始筛查、简捷初始化、修改与细化、两种工具执行计划，
以及相平衡、级数、初步接受、计算失败和负荷超限审查，共 12 个示例。

所有案例均标记为 synthetic_illustration，expert_validated=false。
这是人工编写的行为示意数据，尚未经化工专家独立审定，不能作为实验数据或真实性能证据。
其中的 demo_* 证据编号只属于示例，不能用于当前任务的证据引用。

## Notebook 格式

1. Markdown：案例标题、角色与来源说明。
2. Raw 单元：JSON，metadata.separation_example=true，保存唯一的机器可读示例。
3. Markdown：简短的工程判断说明与适用限制。

JSON 必须包含 example_id、role、phase、title、provenance、expert_validated、context、response。
response 按角色分别满足 DesignProposal、ExecutionPlan 或 ReviewRecommendation 契约。
context.available_evidence_ids 声明示例可引用的编号。

加载器只解析标记的 JSON，不执行 Notebook 代码，也不使用 Notebook 的历史输出。

## 加载方式

sepmind/shortcut/utils/few_shots.py 按角色和阶段选取匹配案例，默认每次最多两个。
sepmind/shortcut/agents/base.py 将示例加入真实模型提示词，实际工具证据仍由 DWSIM 返回。
运行记录的 few_shot_context 事件保存案例 ID、文件名和 SHA-256，以便复现。
规则模式不调用模型，因此不会注入示例。

```python
from sepmind.shortcut import SeparationOrchestrator
from sepmind.shortcut.llm import make_backend

team = SeparationOrchestrator(backend=make_backend())
# 对照实验：关闭示例，其他设置保持一致
baseline = SeparationOrchestrator(backend=make_backend(), use_few_shots=False)
```

CLI 使用 --no-few-shots 关闭，或 --few-shots-dir 指定其他化工 Notebook 目录。
API 使用 use_few_shots=false 关闭。

## 与教程、计算结果和评估数据的区别

- notebooks/08_separation_agents.ipynb：给开发者逐步运行的教程。
- few_shots/separation/*.ipynb：给模型阅读的示范，不作为当前任务证据。
- output/separation/：实际运行生成的计算结果与报告。
- tests/：软件测试；后续科研评估集需独立维护，避免与示例重叠。

正式实验应记录启用的案例版本，并将这些示例及其同源变体排除在独立测试集之外。
