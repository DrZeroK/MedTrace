# MedTrace — 后续步骤交接

[English](NEXT_STEPS_HANDOFF.md) | **简体中文**

编写于 2026-11-17，供接手实现的编码模型阅读。先读本文件，再读 `docs/COMPETITION_QA.md`，然后读你即将修改的代码。
不要把 README 或报告中的说法当作证据；第 2 节列出了在上述日期针对代码重新核验过的内容。

> **可复现性说明（2026-11-17）：** 生成的输出过去取决于 Python 的每进程哈希种子（验证器遍历了一个 `set`，因此
> 两次相同的运行之间待核事项顺序会发生变化）。已修复；测试
> `EndToEnd.test_output_independent_of_hash_seed` 对此加以守护。在逐字节比较两次运行时，任何剩余的
> 差异都是真实的。当顺序会影响到输出时，避免遍历 set 或由 set 构建的 dict。

## 1. 仓库状态

| 项目 | 值 |
|---|---|
| 仓库 | https://github.com/DrZeroK/MedTrace |
| 工作分支 | `medtrace-pipeline`（全部当前工作；除 PR #1 外**未合并**到 `master`） |
| 审计状态 | 提交 `69640e1`（将 `master` 合并进 `medtrace-pipeline`）；本文件在紧随其后的提交中加入 |
| `master` | `149d906`：PR #1（首个流水线版本 + 3 处评审修复）加上比赛问答文档。`medtrace-pipeline` 上约 20 个后续提交不在 `master` 上 |
| 未关闭的拉取请求 | 无（PR #1、#2 和 #4 已合并到 `master`） |
| `AGENTS.md` / `CLAUDE.md` | 仓库中没有 |

仅存在于本地、被 git 忽略、全新克隆**不会**拥有的材料：

- `.env` —— 保存项目所有者的商业 API 密钥。绝不要提交它。
- `data/raw/` —— 下载的数据集（CMB、MedCT 病历文本、CBLUE 天池压缩包）。
- `eval/results/` 和 `eval/archive/` —— 运行输出，仅保留在本地（未提交）。`eval/archive/` 保存着
  `docs/REPORT.md` §2.6 背后的真实模型开发运行；报告中的数字就是记录，原始输出不再分发。

## 2. 基线，已在审计提交上验证

命令已于 2026-11-19 在仓库根目录下使用 Python 3.11.16 重新运行。

| 检查项 | 命令 | 结果 |
|---|---|---|
| 单元 / 集成测试 | `python -m unittest discover -s tests` | 208 个测试，全部通过（约 27 s） |
| mock 端到端 | `LLM_API_BASE=mock:// python main.py --input input.example.json --output /tmp/out.json` | 退出码 0，1 个病例，符合 schema |
| 运行期导入链 | 导入 `medtrace.runner` 并列出已加载的项目模块 | 只有 `medtrace.*`；运行时不会导入 `eval/` 和 `data_pipeline/` |
| 请求负载 | 对一次 `LLMClient.chat` 调用的本地 HTTP 抓包 | `POST {base}/chat/completions`，携带 `model, messages, temperature, stream=false`；仅当 `LLM_JSON_MODE=1` 时才有 `response_format`；`LLM_EXTRA_BODY` 中的任何内容都会在顶层合并（因此 `seed` 和 `chat_template_kwargs` *可以*发送，但只能通过这个通用 JSON 选项） |
| 没有 `.env` 时的默认值 | `load_config()` | `PIPELINE=A2`，提示词 `v2`，`MAX_CALLS_PER_CASE=2`，`REPAIR_CALL` 关闭，`LLM_TIMEOUT=600`，`LLM_MAX_RETRIES=2`，`temperature=0`，无 `max_tokens`，无 JSON 模式，官方安全上限为每例 300 秒、整批 3600 秒（开发模式仍不限制），`output.json` |

本次交接未重新运行（它们需要模型端点或仅本地的数据）：任何真实模型评测、
`data_pipeline.*` 构建、CHIP-CDEE 否定评分、MedCT 压力测试。

**Python 版本：** 2026-11-19 已在 Python 3.11.16（项目任务书指定的版本）上重新运行完整测试套件，208 个测试全部通过。代码使用 `X | None` 注解并配合 `from __future__ import annotations`，因此 3.10+ 应当可用。

## 3. 需求：已确认、假设、未解决

"已确认"的依据：`docs/COMPETITION_QA.md`（由项目所有者提供的组织方答复；没有官方文档 URL 或版本）。后续的官方规范优先于它。

### 3.1 经组织方问答确认的内容

| # | 需求 | 当前实现 |
|---|---|---|
| C1 | 评测时不调用外部第三方 API；推理只能通过指定的自托管 vLLM Qwen 服务进行。比赛练习用例和评测用例绝不能上传到第三方平台（Q8） | 运行时只调用配置的端点。**但是**，目前唯一的真实模型证据使用的是所有者的商业 `qwen4-max` / `qwen-plus` 端点，且只用于公开的 CMB-Clin 用例。`.env.example` 中有一行商业端点示例，措辞应修改（WP-5） |
| C2 | 评测期间不接入公共互联网；运行时不安装或下载任何内容（Q3） | 运行时除模型端点外不需要网络。`data_pipeline/acquire.py` 会下载数据，但仅用于开发，运行时不会被导入 |
| C3 | 若来源合法、版本锁定、随包捆绑并离线运行，则允许使用本地知识库、规则库、检索和多阶段算法（Q1） | 不存在知识库或检索。验证器是规则代码，不是已注册的资源 |
| C4 | 资源必须登记（名称、来源、版本、用途、大小、依赖）；没有资源的团队填写 "None"（Q2）。模板待定 | 不存在登记文档（WP-4） |
| C5 | 完整的依赖说明文档，"例如 `requirements.txt`"（Q3） | 只有 `requires.txt`（名称取自最初的项目任务书）。没有 `requirements.txt`（WP-4） |
| C6 | `seed` 可在请求体顶层传递；若不支持，可省略并说明（Q4） | **已完成（WP-1，0aaad62；2026-11-19 更新）：** 一等参数 `LLM_SEED`；官方入口默认发送 42；若 400 明确拒绝 `seed`，则剥离该字段并重试一次，本次运行后续请求沿用该决定 |
| C7 | Thinking 通过 `chat_template_kwargs: {"enable_thinking": false}` 控制；省略即表示服务器默认值，而服务器默认值不一定是"关闭"（Q7） | **已完成（WP-1，0aaad62；2026-11-19 更新）：** 一等参数 `LLM_ENABLE_THINKING`；官方入口发送 `false`；开发模式未设置时省略；若 400 明确点名该字段，则剥离并重试一次 |
| C8 | 原则上，参赛方算法发起的重试会计入模型调用预算（Q5） | **已完成（WP-2，0aaad62）：** `MAX_REQUESTS_PER_CASE` 统计每一次 HTTP 尝试，包括重试（默认 0 = 不限制，直至主办方公布上限）；`MAX_CALLS_PER_CASE` 仍统计逻辑调用；官方时间上限约束实际总量 |

### 3.2 原则上允许，但取决于部署版本 / 统一 API 规范

- `temperature` 和 `response_format`（Q6）。已实现为 `LLM_TEMPERATURE` 和 `LLM_JSON_MODE`；尚未针对比赛服务测试。
- 按策略选择 Thinking 模式（Q7）；"具体支持情况将通过统一 API 示例确认"。
- 合理的第三方 Python 依赖（Q3）；兼容性要求待定。

### 3.2a 主办方 Q10-Q13 答复（2026-11-18）

- **前缀缓存（Q10）：** 由赛事方统一管理，正式评测拟关闭；请求输入/输出无需 cachemark。不要把缓存命中计入延迟或成本预算。
- **可复现性（Q11）：** 允许固定 seed，但不保证逐字一致；参赛方须固定代码、依赖和知识资源版本，并控制算法内随机性。
- **Embedding（Q12）：** 计划在昇腾技术栈提供内网 Embedding API（如 BGE-M3）；原则上不支持自部署 GPU/NPU Embedding 模型；可提交本地知识库和预构建索引，大小限制待公布。
- **硬件（Q13）：** 模型推理由主办方昇腾技术栈统一部署；参赛算法在隔离的纯 CPU 环境运行，不得额外部署 LLM 或 GPU/NPU 推理服务；操作系统/CPU/内存/存储/时限仍待公布。
- **与当前设计的关系：** 运行时使用确定性台账和可选 SQLite FTS，不使用 Embedding、GPU/NPU 或前缀缓存；未来若做向量 RAG，必须使用主办方的 Embedding API。

### 3.3 未解决 —— 等待组织方答复。不要硬编码假设的取值

- 每请求超时、每例总运行时长、token 预算、模型调用上限、重试上限（Q5）。
- 最终结果文件名（`output.json` 还是 `results.json`）以及结果数据结构（Q9）。
- 算法包大小限制、依赖兼容性规则、资源登记模板（Q2、Q3）。
- 模型名称、端点配置方式、默认 Thinking 模式、支持的参数、API 示例。
- 完整的输入和输出 schema、退出码规则、平台故障处理。

### 3.4 实现假设（我们自己的，而非组织方的）

`docs/REQUIREMENTS.md` 的全部 20 行都是在问答**之前**写的，其中若干行如今已过时（第 6、10、11、
12、13、15 行）。代码中仍保留的关键假设：输出字段名（`treatment_plan`；项目任务书曾写作
`plan`）、信封镜像、`evidence` / `review_items` 作为额外数组、截止点语义、退出码 0/1/2、
bearer-token 鉴权、环境变量名（`LLM_API_BASE` 及别名）。

## 4. 审计发现

### 4.1 输入 / 输出与失败处理 —— 稳固，但 schema 未确认
- `medtrace/inputs.py`：接受列表、包裹的列表或单个病例；畸形病例会被隔离；截止点在资料级和句子级都应用（仅显式日期；UTC 偏移已处理）。
- `medtrace/runner.py`：先写入一个完整、有效的输出文件作为种子，再逐例替换，原子重命名；退出码 0 / 1 / 2（`STRICT_EXIT`）。
- 缺口：只有一个输出路径（没有 `results.json` 别名）；schema 和退出码都是假设。

### 4.2 指定 Qwen / vLLM 集成 —— 通用实现，尚未针对性适配
- `medtrace/llm.py` 使用 OpenAI 兼容的 chat completions 协议。`seed` 和 `chat_template_kwargs` 已是一等参数；官方入口发送 seed 42 和 `enable_thinking: false`。若 400 明确点名不支持的字段，则剥离该字段并重试一次，本次运行后续沿用。响应中的 `reasoning_content` 被忽略（这是正确的），`<think>` 块会被剥离。
- 尚未针对比赛 vLLM 服务器运行；真实模型证据来自商业托管端点。

### 4.2a 端点验收脚本
- `python scripts/api_acceptance.py` 使用官方两键 `.env`；`--development` 使用开发环境；支持 `--repeats 1-5`、`--timeout`、`--json-out`。
- 只发送一个极小的合成 JSON 提示，不上传病例。报告 endpoint 是否原样使用、是否携带 Authorization、seed/thinking 兼容性、HTTP/JSON 状态、延迟，以及 prompt/completion/total/reasoning/cached token。
- 退出码 0 = HTTP 与 JSON 检查通过（官方模式且无 Authorization）；1 = HTTP/JSON 失败或官方模式带了 Authorization；2 = 配置错误或 mock 端点。
- 脚本仅用于开发，不随提交 ZIP 分发。

### 4.3 运行时间、token、调用、超时、重试的核算 —— 最薄弱的环节
- Token：`CallStats` 累计 prompt/completion/total token 与 `usage_missing`；`run_end` 带有运行总计。
- 调用：`CallStats` 跟踪 `calls`、`http_attempts`、`retries`；`MAX_REQUESTS_PER_CASE` 统计每次 HTTP 尝试，`MAX_CALLS_PER_CASE` 统计逻辑调用（见 C8）。
- 时间：官方无参数入口应用每例 300 秒、整批 3600 秒的安全上限；开发模式的 `CASE_TIMEOUT`/`TOTAL_TIMEOUT` 仍默认不限制。这些不是主办方 Q5 的限额，公布后必须更新。到达截止时间时会生成符合 schema 的兜底记录，并仍写完整批次。
- `logs/run_log.jsonl` 记录每例的调用数、尝试数、重试数、token 用量、延迟、请求字段兼容事件和最终校验发现详情；`run_end` 带有运行总计。

### 4.4 离线部署与资源登记 —— 尚未开始
- 没有打包脚本，没有 `requirements.txt`，没有登记文档，没有离线安装检查。
- 仓库中包含不应随包发布的开发材料（`eval/archive/` 4 MB、`data/standardized/`、`data_pipeline/`、`tests/`）。
- 如果缺少 `requests`、`python-dotenv` 或 `jsonschema`，运行时会回退到标准库（此前已在裸 venv 中测试过）。

### 4.5 患者事实可追溯性与医学知识
- 每条生成的陈述都携带 `sources`；`evidence` 以确定性方式派生；无效 id 会被丢弃（A2）。
- 官方 `review_items` 不包含引用草稿原文的校验/QA 消息；这些发现保留在运行日志中。`overconfident` 因影响处理决策而进入白名单，以干净话术呈现。模型、台账、截止时间与知识降级提示仍面向临床复核。
- 官方叙述段落按散文式输出（每节一段）；legacy 输出仍保留编号列表。证据仍在独立的 `evidence` 数组中。
- 批次 A 已 **APPROVED**（2026-11-19）：改动一同意；改动二修改后同意（加入 `初步诊断` / `working diagnosis` 措辞）。项目负责人已豁免正式签名。批准记录与修订快照哈希见 `docs/CLINICAL_REVIEW_BATCH_A.zh-CN.md`（英文：`docs/CLINICAL_REVIEW_BATCH_A.md`）。已批准话术应在回归测试中保持冻结。
- 确定性验证器严格检查病例特点，对拟诊讨论检查较轻（带单位的数字、低严重度的否定翻转），对诊疗计划几乎不检查。
- 在拟诊讨论和诊疗计划内部，患者事实与模型的医学知识之间**没有显式区分**：陈述的 `kind` 为 `assessment|differential|uncertainty|investigation|treatment|monitoring`，没有 "knowledge" 标记。目前完全没有检索到的知识，因此没有可登记的内容。
- 验证器在未见过的模型文本上的精确率**尚未确立**：每一批新数据都会产生新的误报模式（`docs/REPORT.md` §2.6）。高严重度的发现只作为待核事项呈现；修复调用默认关闭。

### 4.6 中文临床数据与评测
- `data_pipeline/`：经审计的数据集注册表；CMB-Clin（74 例，Apache-2.0，已提交）；TypicalCase-DC（2,578 例，836 例干净，仅本地）；CHIP-CDEE 否定测试（留出集 F1 0.982）；MedCT 真实病历压力测试（逐字文本上 0 误报）。
- `eval/`：`run_ablation`（16 个合成病例，mock 故障注入）、`run_external`（标准化数据集）、`judge_dx`（裁判模型诊断评分）、`reverify`（离线验证器回放）、`perturb`、`blind_review`。
- 没有任何数据集包含可作为参照的首次病程记录文本；也没有任何临床医生评审过任何输出。

### 4.7 真实模型证据与仅 mock 证据

| 证据 | 模型 | 状态 |
|---|---|---|
| 26 例开发 + 17 例验证 CMB-Clin 病例，变体 A0 / A1 / A2，提示词 v1 和 v2 | 商业 `qwen4-max`，裁判 `qwen-plus` | 真实，归档于 `eval/archive/`。**不是指定模型。** 诊断评分是 13–20 例上的裁判模型代理指标 |
| 故障注入消融、扰动机制、所有失败处理测试 | mock | 仅代表软件行为；不能说明临床质量 |
| 否定 F1、逐字误报率 | 无模型 | 规则层面，真实文本 |
| CMB-Clin 测试集（30 例）、TypicalCase-DC、合成 `must_not` 检查、S2、A3、使用真实模型的扰动、盲评 | — | **未完成** |
| 任何在比赛的 vLLM Qwen 上的工作 | — | **未完成；尚无访问权限** |

## 5. 工作包

每个工作包的规则：保持无参数运行 `python main.py` 可用；保持输出记录字段以及
`OUTPUT_FIELD_MAP` / `OUTPUT_FIELDS` 的行为不变；除非工作包明确说明，否则不要更改影响生成文本的
默认值；添加或更新测试；现有 50 个测试必须仍全部通过；绝不要提交 `.env`、`data/raw/`
或任何天池下载内容；绝不要将比赛用例发送到指定服务以外的任何端点。

图例：**[ORG]** 需要组织方澄清 · **[MODEL]** 需要指定模型的访问权限 · **[CLIN]** 需要临床评审。

### P0 —— 合规提交所必需

#### WP-1 一等 vLLM 请求参数与 token 用量捕获
*依赖：无。建议作为第一个工作包。*
- 文件：`medtrace/config.py`、`medtrace/llm.py`、`medtrace/pipeline.py`（仅日志字段）、`.env.example`、`tests/test_medtrace.py`。
- 步骤：
  1. 在 `Config` 和 `load_config` 中新增设置 `LLM_SEED`（int，空 = 省略）和 `LLM_ENABLE_THINKING`（`true` / `false`，空 = 省略）。
  2. 在 `LLMClient._chat` 中，当已设置时，在顶层发送 `"seed": <int>` 和 `"chat_template_kwargs": {"enable_thinking": <bool>}`。最后应用 `LLM_EXTRA_BODY`，以便它仍能覆盖。未设置时，这些字段必须缺席（服务器默认）。
  3. 当存在时解析响应中的 `usage` 对象；将 `prompt_tokens`、`completion_tokens`、`total_tokens` 加入 `CallStats`（对返回 200 的尝试求和）。缺少 `usage` 不得导致调用失败。
  4. 将这三个字段加入 `Pipeline.run_case` 中按例记录的日志条目，并将运行总计（token、调用、HTTP 尝试）加入 `runner.py` 的 `run_end` 事件。
  5. 在 `.env.example` 中按问答的措辞记录这两项设置（seed 可选；省略 thinking 设置 = 服务器默认）。
- 验收：负载捕获测试证明 (a) 默认情况下两个字段都不发送，(b) 配置后各自正确发送，(c) `LLM_EXTRA_BODY` 可覆盖；返回 `usage` 的测试服务器得到正确的按例总计和运行总计；没有 `usage` 的响应仍然成功；mock 上的生成记录在改动前后逐字节相同。
- 验证：`env -u LLM_API_BASE python -m unittest discover -s tests` 和 `LLM_API_BASE=mock:// python main.py --input input.example.json --output /tmp/out.json`。

#### WP-2 统一的模型调用预算（重试计数）
*依赖：WP-1（相同文件）。上限取值 **[ORG]**。*
- 文件：`medtrace/llm.py`、`medtrace/config.py`、`medtrace/pipeline.py`、测试。
- 步骤：引入 `MAX_REQUESTS_PER_CASE`（0 = 不限制），统计**每一次 HTTP 尝试**，含重试；拒绝会超过它的尝试（抛出 `BudgetExceeded`，它已会降级为带标记的记录）；保留 `MAX_CALLS_PER_CASE` 的语义；在病例日志中记录 `budget_exhausted`。不要臆造官方数字。2026-11-19 更新：官方入口应用每例 300 秒、整批 3600 秒的安全上限（不是主办方限额）；`MAX_REQUESTS_PER_CASE` 仍为 0。
- 验收：当 `MAX_REQUESTS_PER_CASE=2` 且服务器对每个请求都失败时，该病例恰好发出 2 个 HTTP 请求，且输出仍然符合 schema；现有重试测试通过。

#### WP-3 结果文件名兼容性 **[ORG]**
*依赖：无。*
- 文件：`medtrace/config.py`、`medtrace/runner.py`、`.env.example`、测试。
- 步骤：添加 `OUTPUT_ALIASES`（逗号列表，默认空）；每次对主文件完成原子写入后，将相同内容原子地写入同目录下的每个别名。不要更改默认的主文件名。说明 `OUTPUT_ALIASES=results.json` 可在预检期间同时覆盖两个名称（Q9）。
- 验收：设置别名时，两个文件在每个检查点都存在、逐字节相同且有效；未设置时，行为不变。

#### WP-4 离线打包、依赖文件与资源登记 **[ORG] 针对模板和大小限制**
*依赖：无。*
- 文件：新增 `requirements.txt`、新增 `scripts/build_submission.py`、新增 `docs/RESOURCE_REGISTRATION.md`、`README.md`。
- 步骤：(1) 添加 `requirements.txt`，与 `requires.txt` 保持相同的固定版本，并用测试保持两者同步；(2) 编写构建脚本，生成一个 ZIP，其中只包含 `main.py`、`medtrace/`（含提示词，不含 `__pycache__`）、`requirements.txt`、`requires.txt`、`.env.example`、`README.md` 和登记文档 —— 不含 `eval/`、`data/`、`data_pipeline/`、`tests/`、`.env`；打印文件列表和总大小；(3) 编写登记文档：知识库为 "None"，规则库为 "None beyond program code"，将提示词和验证器规则列为代码，版本 = git 提交，依赖标明版本；将模板标记为待定。
- 验收：解压到空目录，创建全新的虚拟环境，`pip install -r requirements.txt`，在不使用其他网络的情况下对 `input.example.json` 运行 `LLM_API_BASE=mock:// python main.py`；一项测试断言 ZIP 中不含 `.env`、不含 `data/`、不含 `eval/`。

#### WP-5 文档与问答的口径协调
*依赖：WP-1 至 WP-4 以确定最终措辞；现在即可开始。*
- 文件：`docs/REQUIREMENTS.md`、`README.md`、`.env.example`、`docs/REPORT.md`（仅状态行）。
- 步骤：按本文件第 3 节将 `REQUIREMENTS.md` 改写为三张表（已确认 / 原则上允许 / 未解决），保留问答中的每一条限定说明；将 `.env.example` 中的商业端点示例替换为中性的占位符，并加警告说明比赛用例只可使用指定服务；在 `README.md` 中说明，迄今为止的真实模型结果来自未指定的商业模型，且基于公开数据。
- 验收：这些文件中没有任何陈述把假设呈现为官方规则；`grep -n dashscope` 在 `eval/archive/` 之外不返回任何结果。

#### WP-6 时间预算安全网 **[ORG] 针对限制，[MODEL] 针对测量**
*依赖：WP-1、WP-2。*
- 文件：`medtrace/runner.py`、`medtrace/pipeline.py`、`medtrace/config.py`、测试。
- 步骤：设置 `CASE_TIMEOUT` 时，用剩余病例时间限制每个请求的超时（已实现），**并**在剩余时间低于可配置的保留值时跳过可选步骤（重新生成、修复）；记录 `time_budget_skipped`。向运行日志添加 `--dry-run-latency` 风格的汇总（按例 p50 / 最大值）。不得臆造任何默认限制。
- 验收：使用缓慢的 mock 服务器并设置 `CASE_TIMEOUT=5` 时，每个病例在约 5 s 加开销内完成，并产生有效的带标记记录；总计出现在 `run_end` 中。

### P1 —— 形成可辩护结果所必需

#### WP-7 首次针对指定 vLLM 服务运行 **[MODEL]**
- 在提供端点、模型名称和 API 示例之前被阻塞。之后：确认 `seed`、`response_format`、`chat_template_kwargs` 中哪些被接受（组织方称不支持的参数应显式报错）；在 CMB-Clin dev 上测量开启和关闭 Thinking 时的延迟与 token（`python -m eval.run_external --dataset cmb_clin --split dev --variants A0,A2 --workers 1`）；将结果记录到 `docs/REPORT.md` 的新章节中，与 §2.6 明确分开。
- 除非组织方声明练习用例可以发送到该服务（它是指定服务，因此推测可以；需确认），否则只使用公开或自行编写的病例。

#### WP-8 验证器对未见文本的精确率
**已完成（见 `docs/REPORT.md` §2.7）。** 在 20 例 tier-A 开发样本上调优（22 条高严重度发现，全部为误报，修复了六个反复出现的模式）；在留出的、不相交的 40 例 A2 样本上产生了 0 条高严重度发现。CHIP-CDEE dev F1 0.9818 和 CMB-Clin 逐字 0 误报保持不变。MedCT 回归未重新运行（原始数据不在本机上）。中等严重度的发现仍未标注；词法验证器无法捕获真正的临床错误。
*依赖：一个允许用于所用数据的模型端点（所有者的商业端点仅可用于公开数据集）。*
- 文件：`medtrace/verify.py`、`medtrace/textutil.py`、测试、`docs/REPORT.md`。
- 步骤：为 40 例 TypicalCase-DC tier-A 开发样本生成记录（`--tier A --limit 40`）；人工将每条高严重度发现标注为真或假；只修复至少出现过两次的模式；用 `python -m eval.reverify` 回放；然后在*另一个* 40 例样本上测量一次，并在不再调优的情况下报告精确率。每次规则变更后重新运行 CHIP-CDEE 和 MedCT 回归脚本。
- 验收：在第二个、未触碰过的样本上报告高严重度精确率；CHIP-CDEE dev F1（0.982）或逐字零误报检查无回归。

#### WP-9 最终留出集对比与临床医生评审 **[CLIN]**
**进行中 —— 材料已就绪，等待临床医生 + 指定模型。** 已在 CMB-Clin 的**验证**集（17 例，商业 qwen3.5-27b，公开数据）上运行了一次 A0 与 A2 的代理对比（提示词 v2），并将双评审者盲评包导出到 `eval/results/cmbclin_val_proxy/review/`（packet.md、scores_R1/R2.csv、密封的 key.json）。自动代理指标：A0 dx_hit 53.8% / coverage 86.2% / 2 份记录含高严重度发现；A2 dx_hit 46.2% / coverage 90.8% / 1 份（n=13 符合条件；不显著）。**测试集（30 例）被刻意保留**，用于在指定模型上进行最终对比。临床医生评分/裁决、评分量表签核，以及 716+1 个 `review_required` 病例的处置决定，仍是有待完成的人工任务。
- 在 CMB-Clin 测试集（30 例）上按预注册方案运行一次对比：基线 A0 与默认 A2（提示词 v2）。用 `python -m eval.blind_review export <run>` 为两位评审者导出，评审使用 `docs/CLINICAL_RUBRIC.md`；进行评分和裁决。临床医生还必须处置作为 `review_required` 保留的 716 个 TypicalCase-DC 病例和 1 个 CMB-Clin 病例，并签核评分量表。

#### WP-10 标记源自知识的陈述
**已完成。** 拟诊讨论/诊疗计划陈述上的可选 `basis`（record/knowledge/inference），设置后带入 evidence；验证器标记 `knowledge_record_value`；提示词 v2 a1 和 mock 已更新；解析时丢弃枚举外的 basis。已在真实模型留出集上验证（WP-8）。
*依赖：无；提示词变更需要 WP-7 或另一次模型运行来验证。*
- 文件：`medtrace/prompts/v2/*/a1.txt`、`medtrace/note.py`、`medtrace/verify.py`、测试。
- 步骤：为拟诊讨论和诊疗计划陈述添加可选的逐条字段 `basis: "record" | "knowledge" | "inference"`；将其带入 `evidence` 条目；要求 `record` 必须有 `sources`，禁止 `knowledge` 陈述中出现患者特定数值（验证器检查）。三个文本字段保持不变。
- 验收：schema 仍能校验通过；mock 已更新；一项测试表明，包含记录数值的 `knowledge` 陈述会被标记。

#### WP-11 Python 3.11 与持续检查
**已完成。** `.github/workflows/ci.yml` 仅在安装 `requirements.txt`、仅使用 mock 的情况下在 Python 3.10/3.11/3.13 上运行单元测试套件（包括打包冒烟测试）；全部通过（GitHub Actions 运行在 Node 24 上）。没有 3.11 特有的问题。
- 添加一个 GitHub Actions 工作流，在仅安装 `requirements.txt` 的 Python 3.10、3.11 和 3.13 上运行单元测试，并加上 WP-4 的打包冒烟测试。修复 3.11 暴露出的任何问题。

### P2 —— 可选改进，仅在收益经过测量后实施

- **WP-12 本地知识库 / 检索**（Q1 允许；必须在 WP-4 下登记并离线捆绑）。本地磁盘上已有的候选来源：CMeIE-V2 关系三元组 —— 但它们受天池条款约束，因此捆绑前必须先厘清许可。先在留出病例上与无检索的默认方案对比评估。
- **WP-13 账本中的逐条发现不确定性**（目前是句子级；65 条不确定的 CHIP-CDEE 发现中覆盖了 47 条）。
- **WP-14 使用真实模型的 S2 和 A3**；只有在公布的调用和时间限制下优于 A2 时才保留。
- **WP-15 扩展评测集**，朝计划的 60 例临床医生评审病例努力；合成集为 16 例。
- **WP-16 将 `medtrace-pipeline` 合并到 `master`**：P0 完成后通过拉取请求进行（由所有者决定）。

### 依赖汇总

```
WP-1 ──► WP-2 ──► WP-6 ──► WP-7 [MODEL]
WP-3, WP-4 ─────► WP-5
WP-7 ──► WP-8 ──► WP-9 [CLIN]
WP-4 ──► WP-11        WP-10 (independent)        WP-12 needs WP-4 + licence clearance
```

## 6. 需要人处理的事项

| 谁 | 什么 |
|---|---|
| 组织方 | 限制（超时、运行时长、token、调用、重试）；结果文件名和 schema；退出码；包大小；登记模板；模型名称、端点、默认 Thinking 模式、支持的参数；练习用例是否可用于提示词开发 |
| 项目所有者 | 指定服务的凭据（可用时）；是否合并到 `master` 的决定；确认本地 `.env` 中的商业端点仅用于公开数据；CMF-NERD 保密承诺允许做什么 |
| 临床医生 | 评审生成的记录（盲评）、签核评分量表、留出病例、参照的首次病程记录 |

## 7. 可直接复制、用于第一个工作包（WP-1）的提示词

```
You are working in the MedTrace repository (https://github.com/DrZeroK/MedTrace), branch `medtrace-pipeline`.
Implement work package WP-1 from docs/NEXT_STEPS_HANDOFF.md: first-class vLLM request parameters and token usage capture.

Before editing, read: docs/NEXT_STEPS_HANDOFF.md (sections 3, 4.2, 4.3 and WP-1), docs/COMPETITION_QA.md (Q4, Q5, Q7),
medtrace/config.py, medtrace/llm.py, medtrace/pipeline.py (run_case and its log dictionary), medtrace/runner.py
(the emit calls), .env.example, and the Http and EndToEnd test classes in tests/test_medtrace.py.

Scope:
1. Config: add LLM_SEED (integer; empty or unset means "do not send") and LLM_ENABLE_THINKING ("true"/"false";
   empty or unset means "do not send"). Add matching Config fields and load them in load_config().
2. medtrace/llm.py: when configured, send "seed": <int> at the top level of the request body and
   "chat_template_kwargs": {"enable_thinking": <bool>}. Apply cfg.extra_body last so LLM_EXTRA_BODY still overrides.
   When not configured, neither key may appear in the payload.
3. Token usage: read the "usage" object from successful responses when present and accumulate prompt_tokens,
   completion_tokens and total_tokens on CallStats. A response without "usage" must still succeed. The in-process
   mock path contributes zero tokens.
4. Logging: add the three token counts to the per-case log entry built in Pipeline.run_case, and add run totals
   (tokens, logical calls, HTTP attempts, retries) to the "run_end" event in medtrace/runner.py.
5. .env.example: document both settings, stating that seed is optional and that omitting the thinking setting
   leaves the server default (which is not necessarily "off").

Constraints:
- Do not change any default that alters generated text; output on the mock model must be byte-identical before and after.
- Keep `python main.py` working with no arguments; keep the output record fields unchanged.
- Do not hard-code any official limit; none has been published.
- Do not touch eval/, data_pipeline/ or prompts. Do not commit .env or anything under data/raw/.
- Do not call any real model endpoint. Use the local HTTP server pattern already used in the Http tests.

Tests to add (tests/test_medtrace.py):
- payload capture: by default neither "seed" nor "chat_template_kwargs" is sent;
- with LLM_SEED=42 and LLM_ENABLE_THINKING=false both are sent with the exact shapes above;
- extra_body overrides both;
- a server returning usage {prompt_tokens: 5, completion_tokens: 7, total_tokens: 12} yields those totals in the
  case log; a server omitting usage still returns a valid note;
- run_end in logs/run_log.jsonl carries the run totals.

Validate with:
  env -u LLM_API_BASE python -m unittest discover -s tests
  LLM_API_BASE=mock:// python main.py --input input.example.json --output /tmp/out.json

All 50 existing tests must still pass. Commit on `medtrace-pipeline` with a clear message and push (no force-push).
Report: files changed, the new settings and their defaults, test counts before and after, the commit SHA, and
anything in the scope you could not complete and why.
```
