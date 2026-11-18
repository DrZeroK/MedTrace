# 资源登记（MedTrace）

[English](RESOURCE_REGISTRATION.md) | **简体中文**

状态：**draft —— 主办方的登记模板有待发布 [ORG]**（赛题问答 Q2）。
本文档遵循问答所要求的字段（名称、来源、版本、用途、大小、依赖），
并将在官方模板发布后重新排版。每个代码资源的权威版本是提交包的 git commit；
`python scripts/build_submission.py` 在构建时打印该 commit 与提示词指纹；
`submission.manifest.json` 还会记录每个文件的 SHA-256。

## 知识库

**尚无 approved 的临床发布版本。** 可选的 SQLite 知识支持已实现；
默认不启用任何外部知识。`knowledge/` 下的 draft 内容不随包分发。
当向 `build_submission.py --knowledge` 提供 approved 的发布版本时，其数据库
与清单随包分发至 `resources/` 下；官方执行会自动加载该随包数据库。清单登记每个条目的来源、
版本、用途/类型、适用范围、许可与审核人，以及总体大小、SHA-256 与
依赖（Python >=3.10、SQLite FTS5）。见 `docs/KNOWLEDGE_BASE.md`。

## 规则库

**尚无 approved 的外部规则库发布版本。** 确定性校验器是普通 Python 实现（`medtrace/verify.py`、
`medtrace/textutil.py`、`medtrace/ledger.py`）；其否定/不确定线索列表在公开
数据集（CHIP-CDEE train 划分）上调优，但运行时不分发也不加载任何带标注数据。

## 代码资源

| 名称 | 来源 | 版本 | 用途 | 依赖 |
|---|---|---|---|---|
| 提示词模板 `medtrace/prompts/v1`、`medtrace/prompts/v2` | 自研 | 包的 git commit；由构建脚本打印指纹（默认 v2） | 生成 / 抽取 / 修复 / 复核指令（中文 + 英文） | 无 |
| 校验规则 `medtrace/verify.py`、`medtrace/textutil.py`、`medtrace/ledger.py` | 自研 | 包的 git commit | 确定性事实溯源、否定/数值/单位检查、遗漏标记 | 无 |
| 流水线 / 客户端 / 运行器 `medtrace/*.py`、`main.py` | 自研 | 包的 git commit | 编排、兼容 OpenAI 的客户端、批量 I/O | 见下文 |

## 第三方依赖（`requirements.txt`，与 `requires.txt` 相同）

| 包 | 固定版本 | 用途 | 缺失时的回退 |
|---|---|---|---|
| requests | ==2.34.2 | HTTP 客户端 | urllib（标准库）—— `medtrace/llm.py` `_post` |
| python-dotenv | ==1.2.4 | `.env` 加载 | 精简解析器 —— `medtrace/config.py` |
| jsonschema | ==4.26.0 | 旧版/开发用输出模式校验 | 手工检查 —— `medtrace/note.py`；官方校验始终使用同一套标准库实现 |

传递依赖也已在两个依赖文件中按经验证的 Python 3.11 环境固定版本。

在三者均未安装的情况下运行时仍可完成（标准库回退）。运行时不执行安装或
下载；唯一的网络使用是配置的模型端点（赛题问答 Q3）。

## 数据

提交包中不随附任何数据集。开发数据集（CMB-Clin、TypicalCase-DC、
CHIP-CDEE、MedCT）位于 `data/` 下；原始下载内容保持 git 忽略，仅离线用于
评测。依天池条款获取的数据仅保存在私有仓库中，不得发布或再分发。

## 待主办方提供的事项 [ORG]

- 官方登记模板与必填字段（Q2）。
- 算法包大小上限与依赖兼容性规则（Q3）。
