# MedTrace — 基于证据的首次病程记录生成系统

[English](README.md) | **简体中文**

读取结构化入院记录（`input.json`），调用配置的指定大语言模型（LLM），并生成 `output.json`。每个病例包含：**病例特点（Case Features）**、**诊断讨论（Diagnostic Discussion）**、**诊疗计划（Diagnostic and Treatment Plan）**、**证据（evidence，陈述 → 来源 ID）**以及**待审核事项（review items，缺失 / 冲突 / 待核实）**。

> **项目状态。** 已使用模拟模型完成端到端测试，并基于**公开数据**，在 26 个开发集和 17 个验证集 CMB-Clin 病例上使用**非指定商用模型**（qwen4-max，评审模型为 qwen-plus）完成测试；尚未在竞赛指定服务上运行。关于该测试能说明什么、不能说明什么，请参阅 `docs/REPORT.md` 第 2.6 节。在与官方技术说明核对之前，下述输入 / 输出约定仍属假设。请参阅 `docs/REQUIREMENTS.md`（必须确认的事项）和 `docs/REPORT.md`（已测量与未测量的内容）。本项目是研究 / 竞赛系统，并非医疗器械；每份病程记录都必须由临床医生审核。

## 竞赛问答

请参阅[竞赛技术问答](docs/COMPETITION_QA.md)，其中收录了项目所有者提供的全部 9 条主办方答复，涵盖离线资源、vLLM 参数、第三方 API 限制以及尚待明确的提交要求。该文档仅记录所提供的答复，不证明当前实现已经合规。

## 运行

用户提供的教材 PDF 可通过独立的本地全文索引使用；请参阅[教材检索](docs/TEXTBOOK_SEARCH.md)，了解如何按关键词查询并定位来源页码。

离线知识支持已经实现，但默认关闭。首版内容目录仍为**草案，尚未通过临床审核**。请参阅[知识库部署](docs/KNOWLEDGE_BASE.md)，了解审核、构建、评估、打包和回滚流程。将 `KB_PATH` 设置为已获批 SQLite 版本的绝对路径即可启用。引用信息会单独写入 `<output>.knowledge_audit.json`，结果 JSON 的结构保持兼容。

```bash
pip install -r requirements.txt    # requests、python-dotenv、jsonschema（与 requires.txt 一致；Python >= 3.10）
cp .env.example .env               # 设置 LLM_API_BASE / LLM_API_KEY / LLM_MODEL
python main.py                     # input.json -> output.json，日志写入 logs/run_log.jsonl
```

离线运行（无需模型）：保留 `LLM_API_BASE=mock://`，执行 `cp input.example.json input.json`，然后运行 `python main.py`。

退出码：`0` 表示输出已写入且通过 Schema 校验；`1` 表示致命错误（输入不可读、输出不可写、模型未配置）；仅当设置 `STRICT_EXIT=1` 且任意病例发生降级时返回 `2`。

## 提交包

```bash
python scripts/build_submission.py            # 仅按白名单生成 ZIP -> dist/submission.zip（打印文件列表、大小和 Git 提交号）
```

压缩包仅包含运行所需材料（`main.py`、包含提示词的 `medtrace/`、`requirements.txt`、`requires.txt`、`.env.example`、`README.md`、`docs/RESOURCE_REGISTRATION.md`、`input.example.json`），绝不包含 `.env`、`data/`、`eval/`、`data_pipeline/` 或 `tests/`。可选参数 `--knowledge /absolute/path/knowledge.sqlite` 用于打包经过校验且已获批的知识库版本及清单。资源登记见 `docs/RESOURCE_REGISTRATION.md`；目前尚无获批的临床知识库版本，主办方模板仍待提供。

## 输入 / 输出（假定约定——可配置）

```json
[{"case_id": "…", "record_cutoff": "2026-03-02T18:00:00",
  "sources": [{"source_id": "S1", "content": "…"}]}]
```

支持顶层列表、包含列表的对象（`cases` / `data` / `records`）或单个病例；输出会保持输入的外层结构和顺序。

```json
[{"case_id": "…",
  "case_features": "…", "diagnostic_discussion": "…", "treatment_plan": "…",
  "evidence": [{"section": "case_features", "statement": "…", "source_ids": ["S1"]}],
  "review_items": [{"type": "missing|conflict|verify", "description": "…", "source_ids": []}]}]
```

字段名、字段选择、外层结构、正文内引用和语言均可在 `.env` 中配置（`OUTPUT_FIELD_MAP`、`OUTPUT_FIELDS`、`OUTPUT_ENVELOPE`、`INLINE_CITATIONS`、`OUTPUT_LANG`）；官方 Schema 确认后无需修改代码。病程记录会使用病历记录的语言（英文 / 中文）撰写。

## 工作原理

```text
input.json ─ A 输入处理 ─ B 事实台账 ─ D 生成（LLM） ─ E1 确定性校验 ─ F output.json
              校验、截断     数值和单位、   提示词包含          数值、单位、否定、       原子写入、
             （来源级和      否定、         台账与规则；        日期 / 截断、引用、       有序、
              句子级）       待定 / 缺失、   陈述级来源 ID       已完成与计划、支持度     病例间隔离
                            冲突                                  │
                                                                  └─ 定向修复 / E2 语义审核（受控补丁）
```

| `PIPELINE` | 增加的能力 | 模型调用次数 |
|---|---|---|
| `A0` | 直接结构化提示词（基线） | 1 |
| `A1` | 在提示词中加入事实台账、硬性证据规则和陈述级归因 | 1 |
| `A2` *（默认，策略 S1）* | 确定性校验；删除不存在的来源 ID；所有未解决事项均写入 `review_items`。`REPAIR_CALL=1` 时，会在发现高严重度问题后增加一次定向修复调用（默认关闭） | 1（启用修复时为 2） |
| `S2` | 先由模型提取问题清单并逐字核对原文引用，再执行 A2 | 2–3 |
| `A3` *（策略 S3）* | 通过语义审核调用返回补丁；每个补丁都必须通过确定性校验，否则拒绝应用 | 2 |

提示词可选 `PROMPT_VERSION=v2`（精简版，默认）或 `v1`（原始长版本）。除上述情况外，第二次调用仅用于重新生成无法解析的输出；`MAX_CALLS_PER_CASE=1` 会禁止包括重新生成在内的第二次调用。

可靠性特性（均有测试覆盖）：从运行第一秒起即存在完整、有效的 `output.json`（先写入逐字提取的病程记录，再逐病例替换，采用原子重命名）；单个病例不会中断整个批次；模型故障、JSON 格式错误、超时和预算耗尽时，会降级为带标记的纯提取病程记录；任何晚于 `record_cutoff` 的内容都不会发送给模型；校验器绝不会改写临床文本。

## 目录结构

```text
main.py                 入口程序                        medtrace/prompts/v1/{en,zh}/   版本化提示词
medtrace/inputs.py      A  输入与截断                    medtrace/mock_llm.py           离线模拟与故障注入
medtrace/ledger.py      B  事实台账                      medtrace/mock_server.py        HTTP 模拟（500、超时、无效内容）
medtrace/pipeline.py    C–E 流程编排与保护机制            medtrace/update.py             增量病历更新
medtrace/verify.py      E1 确定性校验                    eval/                          病例、消融、扰动、盲法评审
medtrace/llm.py         模型客户端与重试                  tests/                         83 项回归 / 故障注入测试
medtrace/runner.py      F  批处理、日志与退出码           docs/                          需求、评分标准、报告、数据集
data_pipeline/          数据集审计、获取、质控、标准化     data/standardized/             标准化外部病例
```

## 复现实验

```bash
python -m unittest discover -s tests                         # 或：pytest
python -m eval.run_ablation --name my_run                     # 使用配置的模型，在 eval/cases.json 上运行 A0/A1/A2/S2/A3
python -m eval.run_ablation --name heldout --split heldout    # 未触碰的验证子集——仅用于最终选择
python -m eval.perturb --variant A2                           # 单事实变更鲁棒性测试
python -m eval.blind_review export eval/results/my_run        # 生成盲法、随机化材料包和评分表
python -m eval.blind_review score  eval/results/my_run        # 各变体指标、Kappa 和仲裁清单
python -m medtrace.update previous_input.json new_input.json  # 病历变化后重新生成
```

每次运行目录都会保存输出、逐病例指标、完整配置（不含密钥）、提示词指纹和随机种子。即使温度为 0，远程推理也不保证逐字节一致；请通过指标而非 diff 比较运行结果。

## 外部数据（中文临床数据集）

```bash
python -m data_pipeline.acquire --list                 # 已审计数据集及其是否支持自动获取
python -m data_pipeline.acquire cmb_clin               # 下载（Apache-2.0）、许可证检查、固定 sha256 -> data/raw/（Git 忽略）
python -m data_pipeline.cmb_clin                       # 标准化 + 质控 -> data/standardized/cmb_clin/
python main.py --input data/standardized/cmb_clin/cases.json --output out.json   # 标准化病例可直接作为输入
python -m eval.run_external --dataset cmb_clin --split dev --variants A0,A1,A2  # 诊断命中、鉴别诊断召回、覆盖率
python -m data_pipeline.acquire medct_clinical_notes && python -m data_pipeline.medct_stress   # 真实病历压力测试（仅汇总结果）
```

TypicalCase-DC 是规模更大的评估集（2,591 篇病例报告，按入院记录分节并带金标准诊断），但不能重新分发：请将天池下载文件放入 `data/raw/cblue/TypicalCase-DC/`，运行 `python -m data_pipeline.typicalcase_dc`，然后运行 `python -m eval.run_external --dataset typicalcase_dc --split dev --tier A --limit 40`。

审计与排名：`docs/DATASETS.md`。标注规则：`docs/ANNOTATION_GUIDELINES.md`。质控报告：`data/standardized/cmb_clin/qc_report.md`。

## 声明

- **模型：** 仅使用 `.env` 中配置的端点。可选检索完全通过 `KB_PATH` 在本地完成，不使用在线检索或嵌入模型。
- **数据：** `eval/cases.json` 包含为本项目编写的 16 个合成教学病例，不含患者数据。`data/standardized/cmb_clin/` 派生自 CMB-Clin（Apache-2.0，教材病例；请参阅其 `NOTICE.md`），仅用于评估。
- **方法：** 提示词位于 `medtrace/prompts/`，规则位于 `medtrace/verify.py`；不进行微调，不使用隐藏的参考答案。
