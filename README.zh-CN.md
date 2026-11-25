# MedTrace — 可溯源的首次病程草稿

[English](README.md) | **简体中文**

用于教学、比赛及评测：从入院资料生成病例特点、拟诊讨论、诊疗计划、依据与待核事项。生成结果须经医生审核，不直接用于诊疗。

## 项目现状（2026-11-25）

**本项目未通过校赛验收，现已停止开发，仓库转为公开，仅供参考与学习。** 代码、知识卡和文档保持最后状态，不再维护；所有临床内容均未经医生签审，不得用于真实诊疗。

赛题原文（背景、评分标准、技术规范）见 [docs/比赛要求.pdf](docs/比赛要求.pdf)。

### 开发进度

| 阶段 | 状态 |
|---|---|
| 比赛入口与输出协议（无参 `main.py`、两项 `.env`、`output.json`/`run_log.json`、退出码） | 已完成，有回归测试 |
| 生成流水线 A0–A3/S2，默认 A2 | 已完成；官方默认 A2、提示词 v3、temperature 0、seed 37 |
| 确定性校验与安全修复（数值、单位、否定、时间、来源编号） | 已完成 |
| 临床安全规则（主动脉综合征禁抗栓、药物过敏、出血风险、剂量引擎） | 已完成，属规则筛查，未经临床验证 |
| 离线知识库与检索（127 张指南卡 + 教材分块，SQLite FTS5） | 已接入流水线；知识卡仅 AI 核对，未签审，默认不随包发布已批准知识库 |
| 第一阶段实验（中文 ConText 规则、DSPy MIPROv2 指令搜索） | 已完成并出报告，候选未推广为默认 |
| 指定模型 qwen3.8-27b 验收 | **未通过**：随机 10 例中 4 例输出 JSON 解析失败，全流程完成 4/10，见[故障复盘](docs/QWEN38_RANDOM10_JSON_RCA.zh-CN.md) |
| 临床医生盲评 | 材料已备，未完成 |
| JSON 修复 | 部分完成：已能修复资料原文中未转义的 ASCII 双引号；按错误类型恢复、评分完整性校验仍只有计划（复盘文档 P1/P2） |
| 病例触发的安全要点、肺炎严重度计算、评分裁判第三方复核 | 已合入，阈值出处见[核对表](docs/SAFETY_POINTS_SOURCES.zh-CN.md)，裁判松紧度未校准 |

### 算法与技术

- **事实台账（Fact ledger）**：基于正则与中文规则的确定性抽取，保留每条事实的原句与 `source_id`，按 `record_cutoff` 截断，生成可追溯的提示上下文。
- **证据约束生成**：LLM（OpenAI 兼容 Chat Completions，vLLM 部署的 Qwen）按逐句来源标注输出结构化 JSON；缺段在调用预算内重新生成，失败时输出保守的仅抽取草稿。
- **确定性校验**：比对生成语句与台账中的数值、单位、否定、时间顺序和引用；只做可证明安全的自动修改（如删除不存在的来源编号、改写无依据的“已完成”为“拟”），其余列为待核事项。
- **中文 ConText 式上下文规则**：参考 Harkema 等 ConText（2009）自编规则，判定否定/不确定/假设及经历者（患者或家属）作用域；CHIP-CDEE dev 三分类宏 F1 0.786→0.919。
- **离线检索（RAG）**：SQLite FTS5 + BM25，叠加作用域感知的查询构造、人群过滤和规则重排；无 Embedding、无 GPU，检索不额外调用模型。v4 测试集前 5 召回 100%、证据准确率 81.2%。
- **临床规则筛查**：主动脉综合征抗栓分级筛查（含时间分期与适应证窗口）、过敏与出血风险筛查、剂量引擎、严重度守卫；按病例触发 7 条安全要点（过敏、卒中再灌注、异位妊娠、维生素 B1、低钾、降糖药低血糖、脓毒症休克）注入提示词，并计算社区获得性肺炎严重度。
- **提示词优化实验**：DSPy MIPROv2 指令搜索，持久化 300 次请求上限与断点续跑。
- **评测**：数值覆盖、诊断字面命中、LLM 五维评分裁判、配对盲评材料生成。
- **工程**：Python 3.11，运行时只依赖 `requests`、`python-dotenv`、`jsonschema`；`unittest` 回归测试；带 SHA-256 清单与提示词指纹的提交打包脚本。

### 已知问题

- 指定模型下 JSON 输出不稳定是验收失败的直接原因；目前只修复了未转义引号，其他语法错误仍靠通用格式提醒重试，解析器的去尾逗号还会误改字符串内容。
- 评分裁判可能缓存不完整的五维分数。
- 公开实验只用了非指定模型和公开数据，不能代表指定服务上的表现。

## 比赛入口

统一环境Python 3.11。执行 `python -m pip install -r requires.txt` 后，无参数运行 `python main.py`。输入输出以main.py所在目录为基准，不依赖启动目录。

主办方放入input.json和.env；.env只允许两项非空配置：

```dotenv
MODEL_NAME=qwen3.8-27b
ENDPOINT=http://127.0.0.1:8000/v1/chat/completions
```

ENDPOINT是完整请求地址，不再拼接路径。官方运行不发送鉴权头，不继承代理、netrc凭据或开发环境的模型、路径、提示词和参数设置。

input.json为数组：case_id是文件内唯一非空字符串，record_cutoff是有效时间或T0，sources内含唯一非空字符串source_id及非空字符串content。病例标识或顶层协议错误退出2；单例截止点、资料或生成失败，保留failed记录并继续。

output.json在整批处理结束后原子发布。每条包含case_id、status、medical_record、error。成功的medical_record含case_features、diagnostic_discussion、plan、evidence、review_items。evidence每条含statement、source_ids、kind（fact/inference）；review_items为字符串数组。失败时medical_record=null，error含code及message。顺序与标识匹配输入，空输入输出[]。缺段结果在调用预算内重生成，仍无效则失败。

退出码：0为完整输出已写入（允许单例失败）；1为任务运行或输出/日志写入失败；2为配置或基本输入协议错误。根目录run_log.json对应本次完整运行；logs/run_log.jsonl保留追加记录。日志含运行标识、时间戳、病例映射、逐次请求信息、调用/重试次数、token用量和输入输出摘要。

默认固定参数：A2、v3提示词、temperature=0、seed=37、每例最多2次逻辑调用、每次最多2次瞬时错误重试、请求超时600秒、单工作线程、额外模型修复关闭。正式限额须按赛方最终附件确认，当前参数不代表已获赛方批准。若服务明确拒绝 seed，客户端会去掉该字段重试，并记录变更。即使使用相同 seed，重复请求也可能生成不同文本。

## 测试打包

当前未分配队伍编号，打包仅用于测试。`python scripts/build_submission.py --output /绝对路径/新目录/submission.zip`生成白名单包，拒绝覆盖已有归档。包内含文件哈希、提示词指纹和源码版本，不含真实.env、开发数据、评测脚本、测试、开发配置模板或本地日志。

从解压算法包完成一次运行后，用 `python scripts/build_submission.py --results-from /绝对路径/解压目录 --output /绝对路径/新目录/results.zip`生成测试结果包。程序核对完整日志、病例映射、计数、输入输出哈希和源码清单，只打包output.json、run_log.json及算法清单。模拟结果不得当作正式比赛结果。

可选--knowledge只接受已校验知识库并随包分发；官方运行自动读取resources/knowledge.sqlite。当前没有获批的临床知识库。

## 开发与验证

离线测试：将ZIP解压至新目录，设置进程环境LLM_API_BASE=mock://、OUTPUT_PROTOCOL=official，再执行 `python main.py --development --input /绝对路径/input.example.json --output /绝对路径/test_output.json`。这是显式模拟运行。

开发实验须加--development；可在独立工作目录使用.env.development.example，启用模型别名、路径与参数配置，默认输出与官方模式相同（`OUTPUT_PROTOCOL=legacy` 可改用旧扁平输出）。评测模块显式使用开发配置。

运行 `python -m unittest discover -s tests -v`检查回归；测试包含本地HTTP模拟服务下、仅两项.env配置的无参数比赛入口，测试产物保留。

## 方法与证据

项目采用事实台账、带来源生成与确定性校验。规则不能证明临床推断正确，也不能发现所有遗漏。历史公开数据上的非指定模型结果不替代指定服务验收。

第一阶段开发候选加入中文 ConText 式作用域与 DSPy MIPROv2 组织指令优化，共享持久化300次请求预算。正式默认值不变，候选待临床盲评；分组、续跑、报告与使用方法见仓库中的 [第一阶段实验](https://github.com/DrZeroK/MedTrace/blob/codex/context-prompt-experiments/docs/PHASE1_EXPERIMENTS.md)。

详见[项目说明](docs/PROJECT_DESCRIPTION.md)、[协议及待验收项](docs/REQUIREMENTS.md)、[声明](docs/DECLARATIONS.md)、[资源登记](docs/RESOURCE_REGISTRATION.md)、[知识库说明](docs/KNOWLEDGE_BASE.md)。
