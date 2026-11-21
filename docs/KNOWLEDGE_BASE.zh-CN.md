# 离线知识部署

[English](KNOWLEDGE_BASE.md) | **简体中文**

状态：离线实现已可用；**没有 approved 的临床发布版本**。
`knowledge/entries.jsonl` 包含 300 条术语 draft、30 条检验单位 draft、
24 张成人内科卡片 draft 与 10 个非临床规则模板。
全部为 `draft`。构建器拒绝空的 approved 集合，也拒绝发布
模板。来源链接是待审核的候选，不构成许可或临床认可的凭证。不随附任何指南 PDF 或外部病例答案。

国内来源的许可与临床预审已于 2026-11-17 启动，优先处理人卫社（PMPH）教科书、中国专业学会指南与专家共识文件。
见[首次审核报告](../knowledge/reviews/2026-11-17-cn-review-01/REVIEW_REPORT.md)。
全部 364 个条目仍为 draft，许可与签核字段相互独立；AI 来源一致性检查不等于临床批准。
原始目录保留在该批次的 `before/` 快照中。国外来源仍在其中保留，供比对之用。

2026-11-17 的工程验证：在 Python 3.14.7 / SQLite 3.53.4 上全部 98 项测试通过（含 15 项知识库
测试）。15 项知识库测试在最终日志句柄修复后重跑并通过。新模块也能以 Python 3.10 语法解析；
目标 Python/运行时、指定模型与临床质量尚未验证。

[临床智录离线检索](CLINICAL_RETRIEVAL.zh-CN.md)记录新增指南草稿、教材整理、检索实验和当前发布状态。

## 内容审核与发布

1. 审核 `knowledge/sources.json` 及每个条目。取得使用与
   再分发预期内容的许可；填写确切的来源版本与章节。
   批准前冻结来源版本（包括任何修订过的指南）。
2. 审核规范名称与别名。有歧义的别名保持多匹配；
   规范化从不覆盖来源文本。显式补充简短的英文别名。
3. 对检验项，按被测物与方法审核可接受单位。初始单位
   列表并不完整，且不提供参考区间。可选的
   `reference_interval` 包含 `low`、`high` 和非空的 `requires`（明确的人群、
   标本与方法字符串）。每个必需字符串都必须出现在同一事实中。
   条件缺失时结果为 `insufficient`，而非正常。不做自动换算。
4. 用已审核的规则替换风险模板。v1 支持的数值比较
   严格限于 `above` 与 `below`，需包含被测物、单位、阈值与显式 `requires`。
   相等不构成触发条件。模板的阈值是占位用的零值，绝不能被
   设置为 approved。叙述性禁忌与药物剂量计算
   不在本数值规则评估器的范围内；它们需要经过审核的卡片与临床医生审核。
5. 对每个可发布条目，设置 `status=approved`、`reviewer`、`reviewed_at`、已获确认的 `license` 与确切的 `locator`。
   只有在替换全部模板内容后才可设置 `template=false`。批准是人工内容决策，绝不是构建器的操作。
   对于带有审核批次记录的条目，还须完成分别有证据支撑的
   `permission_review`（`cleared`）与 `clinical_review`（`signed_off`）决策，
   各含审核人/日期/证据。AI 预审不能满足上述任一决策。
6. 构建新的绝对路径目标位置。已有发布版本绝不会被覆盖。

下方示例命令使用本检出目录的绝对路径与已安装的 Python。
它们有意要求 approved 的输入；当前的 draft 目录无法发布。

```bash
/opt/homebrew/bin/python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/build_knowledge.py --source /Users/zerok/Documents/GitHub/MedTrace/knowledge/entries.jsonl --output /Users/zerok/Documents/GitHub/MedTrace/knowledge/releases/v1/knowledge.sqlite --version v1
```

输出为 `knowledge.sqlite` 与 `knowledge.manifest.json`。清单包含
数据库哈希、计数、大小、依赖以及 approved 的来源/许可记录。
保留发布版本与原始来源。不执行任何自动清理或删除。
构建失败时，保留不完整的产物并改用新的目标位置。

## 运行时与审计

官方执行在随包分发时自动加载 main.py 同目录的 `resources/knowledge.sqlite`；
若无该文件，则不启用任何外部知识。在显式开发模式下，
将 `KB_PATH` 设为 approved 数据库的绝对路径；留空即禁用。启动时校验
哈希、schema、批准元数据、只读 SQL 访问与 FTS5。显式启用
但知识库无效时，在生成前即判定为致命错误。批量与增量入口
在模型调用前预检其审计输出。病例处理中途的检索错误
会降级为既有生成流程，并产生一个可见的复核项。

检索使用**经记录截止点过滤后**的病例文本、带词频的中文二元组、完整英文词
与简短别名；FTS5 BM25 将标题排在正文之前。
检索要求精确的主题/别名锚点，最多选择 5 张完整卡片，合计
2,500 个文本字符。成人卡片要求明确记录的年龄 18–120；
年龄未知或冲突时不启用该卡片。明确否定或缺失的线索不作为患者阳性检索依据，台账与审计保留原始极性。
仅凭症状的语义匹配与跨句规则适用性有意不做
推断。在考虑嵌入方案前，先用 dev 划分改进别名。

只有 A1/A2/S2/A3 接收知识；A0 仍为对照基线。检索没有
额外的模型调用。通用数值知识必须在单独的 `basis=knowledge` 语句中
精确引用已提供的 approved 卡片；仅数字
匹配不能绕过患者数值校验。对 approved 内容的精确引用只能
证明其出处：它并不能确立对该患者的适用性。

`output.json` 保持其现有 schema。`output.json.knowledge_audit.json` 记录
运行 ID、输入/输出哈希、知识库版本/哈希、来源元数据、逐例
带极性的规范化结果、检索到的卡片、规则状态与最终语句引用。
ID 有效的引用仍需临床支持审查。使用审计前先比对
输出哈希；两个文件各自原子写入，不构成事务。
增量更新同样生成该附属文件；逐例日志也携带审计
数据，供现有评测工具使用。该附属文件属于本地临床输出，应
像生成的病程记录一样保留与保护。

## 评测与发布门禁

`eval/knowledge_questions.json` 包含 80 道自编的暂定问题：
40 道 dev、40 道 heldout，每个划分含 32 道可回答问题与 8 道无答案问题。
heldout 划分不得用于别名/卡片调优。临床相关性标注
尚待完成；这是检索脚手架，不是临床验证，也不是性能结论。

在检出目录下、显式设置 Python 模块搜索路径后运行：

```bash
PYTHONPATH=/Users/zerok/Documents/GitHub/MedTrace /opt/homebrew/bin/python3 -m eval.knowledge --kb-path /Users/zerok/Documents/GitHub/MedTrace/knowledge/releases/v1/knowledge.sqlite --questions /Users/zerok/Documents/GitHub/MedTrace/eval/knowledge_questions.json --split dev --output /Users/zerok/Documents/GitHub/MedTrace/eval/results/kb-v1-dev.json
```

完成临床标注后，目标为 Recall@5 ≥90%、误注入 ≤5%，并在目标机器上
稳态检索/规则路径 P95 ≤100 ms。评估器报告检索
延迟；组合规则路径需单独做基准测试。工程测试夹具不能
确立这些目标。来源元数据与被引用的 ID 必须完整有效。

为进行生成对比，构建仅含 P0 的发布版本（approved 术语/检验项）与
P0+P1 发布版本。运行既有的 `eval.run_external` 入口三次，分别令 `KB_PATH` 留空、为 P0 与 P0+P1，
使用不同的运行名称、相同的公开病例、模型、随机种子、提示词版本、策略 A2 与调用预算。
绝不可将评测答案用作知识。在赛题数据上，只能使用指定服务。
由临床医生盲法比较诊断特异性、鉴别相关性、
计划相关性、数值错误、引用与严重错误。任何新的严重错误
都会阻断 P1 启用；须修订并在独立病例上测试后方可重试。

## 打包与回滚

提交构建器接受可选的 `--knowledge /absolute/path/knowledge.sqlite`。
它会校验该发布版本，并将数据库与清单精确地随包分发至
`resources/knowledge.sqlite` 与 `resources/knowledge.manifest.json`，同时附上资源
说明文档。draft 内容、评测问题与临床答案数据集均被
排除。官方执行会自动解析随包资源路径；不要向官方仅含两项配置的 .env
添加 KB_PATH，也不要把开发机器的路径带入其中。
不要将发布版本与其配套清单分开移动。

在目标环境验证 Python >=3.10 与 SQLite FTS5；在无公共网络访问的情况下
运行 mock 冒烟测试。记录数据库哈希、提示词指纹、模型配置
与包大小。为官方执行，从保留的先前发布版本（或不带知识库）
构建新包；保留原始包与日志。开发时，
将 KB_PATH 切换到保留的发布版本，或留空该设置。嵌入、向量服务与病例检索仍暂缓，
直到实测的词汇检索失败证明有必要为止。
