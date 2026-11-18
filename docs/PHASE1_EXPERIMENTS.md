# 第一阶段：中文上下文与提示词候选

本阶段仅增加显式开发候选。正式入口仍使用固定 v2 提示词、legacy 上下文与原有比赛输出协议，不读取 `CONTEXT_MODE` 或 `PROMPT_CANDIDATE_PATH`。DSPy 只在开发依赖中，实验、缓存和候选均不进入算法提交包。

中文规则采用 [ConText 的作用域思路](https://doi.org/10.1016/j.jbi.2009.05.002)，规则由本项目编写，不引入外部词库、预训练权重或临床本体。每段作用域记录原文偏移、规则、断言、时间或主体属性；原始事实与数字保持不变。覆盖否定、不确定、未记录、家族成员、既往、当前和条件句，歧义保留为待核实。共享短语触发的冲突只是复核提示。

DSPy 固定为 `dspy[optuna,numpy]==3.5.0`。使用 MIPROv2、seed42、3 个指令候选、4 次优化试验、批量4、单线程。v3.5 内部即使演示上限为零仍会为提议阶段引导生成演示，项目的版本固定适配器关闭这一步；引导演示和标注演示均为零。提议数据摘要仅使用18例公开病例，不提供参考病程或虚构的金标准记录。优化内容只是前置的组织建议，固定 v2 事实约束、截止时间、来源和 JSON 协议随后完整保留。该候选仍须人工审阅。

## 数据与选择

- 仅固定路径的公开 CMB-Clin 可进入实验服务；不接受任意病例路径。组织方病例和本地真实病历不得用于外部接口实验。
- dev26 经 seed42 确定性划为提议18、选择8；候选只在选择8上评分。test30 在候选冻结后用于一次确认，缓存支持续跑。曾用于开发的 validation17 不作为未触碰的独立验证集。
- CMB-Clin 无时间轨迹；空截止时间在内存中标为符号 T0，不推定真实日期，也不能验证具体日期截止过滤。原始数据文件不改写，哈希写入实验身份。
- A 为 legacy；B 为中文上下文规则；C 为规则加优化组织建议。选择8上 C 的搜索分数严格高于 B 才选 C，否则选 B。这只冻结确认候选，不决定正式推广。
- 输出失败或结构/来源引用不合规则搜索分数为0；其他病例为数值覆盖与参考诊断字面命中的均值。无合格诊断指标时只用数值覆盖。规则告警、字面诊断命中、同模型诊断评审都是代理指标，不能代表临床正确率。
- CHIP-CDEE 仅本地评估，只保存汇总。train 可调规则，dev 只报告；两模式采用同一合格出现集合。三分类含肯定、否定、不确定；原始空倾向标注按肯定处理。missing/unknown 计为弃权错误，不从分母剔除。门槛为否定 F1 不下降超过0.005、不确定误判为否定的次数不增加。

## 预算与续跑

所有提议、生成、评审和解析失败后的重生成请求都经过同一 `RequestBudget`。开发最多120，确认保留180，合计最多300次 HTTP。HTTP 自动重试关闭；DSPy 缓存关闭，仅使用本项目校验过的实验缓存。没有 SDK 隐式服务路由。每次请求发送前追加并同步落盘预约；崩溃或失败同样消耗额度。进程锁阻止同目录并发。身份包含程序、数据、提示词和去凭据的配置摘要，配置或代码改变后拒绝续跑。不要另建目录重置同一实验额度。

日志不保存认证头或密钥。记录请求哈希、用途、模型、状态与服务报告的 token 数；未核验单价时费用明确为未知。生成缓存包含公开病例和输出，不可用来存储私人病历。所有实验产物保留，工具不做清理。

先在项目根目录加载已授权的开发 `.env`，将下列绝对路径中的 Python 替换为已安装开发依赖的解释器；三个阶段必须使用同一目录：

```sh
/absolute/path/to/python -m eval.phase1 rules --directory /Users/zerok/Documents/GitHub/MedTrace/eval/results/phase1_20261118
/absolute/path/to/python -m eval.phase1 develop --directory /Users/zerok/Documents/GitHub/MedTrace/eval/results/phase1_20261118
/absolute/path/to/python -m eval.phase1 confirm --directory /Users/zerok/Documents/GitHub/MedTrace/eval/results/phase1_20261118
/absolute/path/to/python -m eval.phase1 report --directory /Users/zerok/Documents/GitHub/MedTrace/eval/results/phase1_20261118
```

产物包括 `experiment.json`、`splits.json`、追加式 `requests.jsonl`、候选 JSON、生成缓存、`optimization.json`、冻结的 `selection.json`、确认汇总和 JSON/Markdown 报告快照。来源文件改变、预算耗尽或服务失败会保留已完成工作；不要绕过身份检查。`JUDGE_MODEL` 若显式指定则纳入实验身份，否则使用生成模型，并在评审结果标明同模型评审。

`confirmation/review/packet.md` 与空白 `scores_R1.csv`、`scores_R2.csv` 供临床独立盲评；`key.json` 是揭盲映射，评分前不提供给评审者。须完成严重错误、事实准确率、来源支持、推理和计划评分及分歧裁决，才讨论推广。工具不填造专家评分、不自动改正式默认值。
