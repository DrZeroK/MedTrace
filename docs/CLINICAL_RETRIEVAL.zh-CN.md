# 临床智录离线检索

本分支把本地检索接入现有 MedTrace 生成流水线。检索器使用 Python 标准库和 SQLite FTS5。输入支持自由文本，或 `history`、`symptoms`、`labs`、`exams` 字段。比赛流水线使用已按截止点处理的事实账本，检索无额外模型调用。返回的知识卡 `id` 标识证据片段，`source_id`、`version` 和 `locator` 用于审计和回查。正式输出的 `medical_record.evidence[].source_ids` 仍按赛题协议引用本病例的资料 ID。

## 指南与共识扩库

截至 2026-11-23 核对并新增 30 份来源，含 25 份指南或诊疗方案、5 份专家共识。[纯文字条目](../knowledge/guidelines.v2.jsonl) 有 54 条可检索知识卡，分别为诊断 15 条、鉴别 5 条、检查 12 条、治疗 22 条。来源包括国家卫健委、中华医学会及相关专业组织。重点补充慢阻肺、儿童肺炎支原体肺炎、高血压、房颤、慢性肾脏病、肝硬化、风湿免疫病、睡眠障碍、重症肌无力及部分肿瘤筛查。诊疗指南、专项治疗共识、筛查方案按原文适用范围分别取材。罕见病、眼科、皮肤科、精神科及肿瘤分型治疗仍有明显覆盖缺口。

正文为独立撰写的纯文本摘要，来源链接只存于 `source_url`。每条带 `id`、`source_id`、发布组织、版本、核验日期、原文章节、用途及适用人群。成人基层高血压卡限定非孕人群。新条目通过仓库原有 schema 校验，并额外检查纯正文、HTTPS 溯源和新条目的出版元数据。正式库需完成许可和临床签审。

把下方五册构建命令的 `build` 步骤加上 `--supplement knowledge/guidelines.v2.jsonl` 并指定新的绝对输出路径，得到与本轮一致的混合草稿结构。五册教材、第一批来源和本次新卡合计 12,028 条。来源核验不要求评测时联网。

```bash
python -m eval.rag_benchmark --cards knowledge/guidelines.v2.jsonl \
  --queries eval/retrieval_guidelines.v2.jsonl --output /tmp/medtrace-guideline-retrieval-v2.json
```

该合成定向集有 14 条带证据的查询和 4 条反例。仅用新版条目测试时，重排的 Recall@5 和证据相关准确率@5 均为 100%，无关信息比例为 0%，四条反例均为空返回。证据标签由项目编写，覆盖指定的检索和过滤场景。五册混合草稿在 8 份官方练习病历上覆盖 10 个主题中的 9 个，较上轮少 1 个。漏召的是短暂性局灶神经症状主题。

## 全量目录审计与离线拟合

```bash
python -m eval.fit_clinical_retrieval \
  --output /tmp/medtrace-anchor-idf.json --audit /tmp/medtrace-data-audit.json
python -m eval.clinical_intake_retrieval --index /absolute/path/to/clinical-drafts-v6.sqlite \
  --anchor-profile /tmp/medtrace-anchor-idf.json --output /tmp/medtrace-external-retrieval.json
```

`data/` 下 97 个 Git 跟踪文件按用途盘点。原始和复核合成集是一批病例的两个版本，按病例编号取复核后的 100 条唯一输入，使用截止点处理后的病例文字拟合医学检索词频率权重。词表来自指南证据卡。此实验只拟合离线检索排序的权重，生成模型继续使用赛方指定的调用方式。52 个文件在稀疏工作区未展开，审计按 Git 文件登记统计。教材作为索引语料，仓库中的数据说明、导出副本和评测报告不计作独立样本。

CMB-Clin 34 例及 TypicalCase-DC 1,319 例全部通过标准化输入与参考标签的编号对账。CMB-Clin 的仓库 NOTICE 将其限定为基准评测用途；TypicalCase-DC 的期刊正文训练许可尚待明确。两套数据留作本地评估。CHIP-CDEE 和 MedCT 的标准化目录只有报告。外部集的截止字段不同于官方输入规范，因此结果仅用于开发。TypicalCase-DC 有 603 例具备诊断评测资格，其中 13 例能严格映射到本次结构化指南的诊断相关来源，前五命中 6 例，两组相同。该指标只统计已知目标来源，不能衡量整条证据的质量或判断未映射病例是否有教材证据。

拟合权重在练习集也与原排序同为 9/10。本轮通过独立参数保留实验路径，默认排序沿用未拟合权重。病例、拟合文件和逐例练习报告均留在本地。

## 开关检索的同病例对照

实验使用同一个 A2 生成流程、同一个模型、同一份截止时点的病例输入以及同样的采样设置和调用预算。两组交替先跑，程序逐例核对第一次生成请求的基础提示词哈希；开启组额外加入检索到的知识片段。对照只测量检索上下文的作用，因此实验关闭知识库规则触发的待核项。

```bash
python -m eval.rag_ablation \
  --practice-archive /absolute/path/to/practice.zip \
  --index /absolute/path/to/clinical-drafts-v3.sqlite \
  --output eval/results/rag_ablation_mock
```

`summary.json` 记录两组的成功数、提示词一致性、检索片段 ID 和调用情况。模拟器用来核对流程，它不评估医学写作质量。实测 8 份练习病例均生成了两组合法输出，8 对的基础提示词哈希一致，开启组均收到检索上下文，模拟输出 8 对一致。

赛方指定的模型接口可用后，使用赛方要求的 `.env` 配置，给同一命令加 `--official`，切换到经许可、临床审核且已发布的 SQLite 知识库，把输出目录改为一个新目录。也可用 `--input` 传入官方格式的 JSON 病例。模型地址使用赛方给出的完整端点。真实对照保持与模拟演练相同的结构审计。结果、病例和盲评文件保存在本地；`review/key.json` 由汇总人保留，评分员只读取盲评包并填写各自的评分表。

```bash
python -m eval.blind_review score eval/results/rag_ablation_official
```

盲评同时检查严重错误、事实错误、引用支持、鉴别分析和诊疗计划。同一病例由同一评分员完成两组评分时，汇总其中的配对差值；缺失的评分不计入该项差值。自动结构检查与人工医学评分均保留。

## 赛方练习病历的本地演练

第三阶段使用赛方提供的 8 份练习入院记录检验长文本检索。评估从主诉开始读取，保留年龄、性别，在首次病史小结或初步诊断标题前停止。检索与评估在本地运行，逐例报告仅写出样例编号、检索证据 ID 和目标主题排名。练习原文、逐例主题标签和报告放在本地。

给主诉和记录中明确的病理结果增加检索权重，合并按重点段落召回的候选。指南摘要在推荐候选中另有补充路径，仍需通过关键词与适用人群过滤。数值和单位不能单独作为证据命中的关键词。

以团队标注的 10 个宽主题检查前五条证据。第二阶段覆盖 7 个主题、5 份病历；第三阶段覆盖 10 个主题、8 份病历。排在第一条的主题从 3 个增至 6 个。练习病历参与了调试。主题命中按证据标题检查，仍需逐段判断准确性。数据未用于测量模型写作得分或正式比赛表现。

```bash
python -m eval.practice_retrieval \
  --archive /absolute/path/to/practice.zip \
  --labels /absolute/path/to/local-topic-labels.json \
  --index /absolute/path/to/clinical-drafts-v3.sqlite \
  --output /absolute/path/to/local-report.json
```

标签文件是按样例编号索引的 JSON 对象，每个编号对应一组主题名和证据标题正则。构建 v3 索引复用下方五册教材命令，将数据库输出文件改为 `clinical-drafts-v3.sqlite`，并使用当前版本的指南草稿。

## 第二阶段扩展

本地草稿索引增加第十版《儿科学》《妇产科学》《外科学》的 6,225 个片段。五册教材共 11,941 个片段，加上 33 条指南、共识和参考摘要，共 11,974 个片段。三册新增来源的书号与出版社目录核对，原文定位和页码置信来源随卡保存。页码可能来自页眉或页码偏移推算。资料仍为开发草稿。

口语检索在识别否定、缺失和家属线索后，再补充低权重的医学检索词。短暂言语障碍的扩展需要同处的突然起病线索和附近的恢复信息。检索词扩展只参与候选排序，病例账本保留原始文字。教材排序允许不同子句提供互补的匹配线索。

| 数据集 | Recall@5 扩展前 → 后 | 证据相关准确率@5 扩展后 | 无关信息比例@5 扩展后 |
| --- | ---: | ---: | ---: |
| 原 50 条开发查询 | 93.50% → 100% | 96.88% | 3.13% |
| 16 条定向口语及反例查询 | 39.58% → 100% | 100% | 0% |

以上是同一指南语料的合成相关性对照。16 条定向集含 8 条可回答查询和 8 条反例，8 条反例均返回空结果。该集合覆盖这次选择测试的语言现象，尚无正式病例或独立临床评估。五册混合索引另做了 6 条教材来源抽查，5 条在前五命中预期教材；儿童肾病综合征检查分类仍有漏召。

构建五册索引时，先参考下方命令生成两册原有索引的 `textbook-cards.jsonl`，再处理三册补充教材。

```bash
python scripts/textbook_kb.py structure \
  --corpus data/reference_indexes/textbooks-text-21-v2 \
  --book 儿科学第10版 --book 妇产科学第10版 --book 外科学第10版 \
  --out "$work_dir/specialty"
python scripts/textbook_kb.py organize \
  --entries "$work_dir/specialty/entries.jsonl" --output "$work_dir/specialty-cards.jsonl"
python scripts/textbook_kb.py build \
  --entries "$work_dir/textbook-cards.jsonl" \
  --supplement "$work_dir/specialty-cards.jsonl" \
  --supplement knowledge/guidelines.v1.jsonl \
  --db "$work_dir/clinical-drafts-v2.sqlite"
python -m eval.rag_benchmark --queries eval/retrieval_variants.v2.jsonl
```

## 知识入库

- [指南与共识草稿](../knowledge/guidelines.v1.jsonl) 收录国家卫健委、中华医学会和其他专业机构的 18 份指南、共识及参考来源，共 33 条独立编写的摘要。来源链接、具体版本、定位、适用范围及审核状态随卡保存。覆盖诊断标准、鉴别诊断、检查建议和治疗建议。
- 人卫第十版《内科学》《诊断学》现有的 4,493 张正文草稿卡整理为 5,716 个本地证据片段，保留原版次、页码、章节、父卡 ID 和来源 ID。按原书明确的结构标签归类，2,314 个片段至少有一类用途标签。无明确标签的片段可参与通用检索。
- 新指南摘要与教材索引都沿用仓库既有的版权许可及临床签审状态。现有素材是开发草稿。正式构建器仅接收通过审核的版本化库，详见 [知识库审核说明](KNOWLEDGE_BASE.zh-CN.md)。

在仓库根目录构建本地混合草稿索引。输出路径应为新文件。

```bash
work_dir="$(mktemp -d)"
python scripts/textbook_kb.py organize \
  --entries data/reference_indexes/textbooks-kb-v2/entries.jsonl \
  --output "$work_dir/textbook-cards.jsonl"
python scripts/textbook_kb.py build \
  --entries "$work_dir/textbook-cards.jsonl" \
  --supplement knowledge/guidelines.v1.jsonl \
  --db "$work_dir/clinical-drafts.sqlite"
python - "$work_dir/clinical-drafts.sqlite" <<'PY'
import sys
from eval.textbook_rag import TextbookIndex

index = TextbookIndex(sys.argv[1])
for card in index.retrieve({"history": "62岁", "labs": "血红蛋白偏低、肌酐升高"},
                           categories=["tests"], limit=3):
    print(card["id"], card["source_id"], card["version"], card["locator"])
PY
```

教材分块优先保留整句及检验值单位。过长且无可用句界的片段单独保留，开发检索通过上下文长度上限控制进入提示的内容。召回由 FTS5 BM25 完成，随后按医学术语、单句同现、字段权重和适用人群重排。明确否定、缺失或属于家属的线索不作为患者阳性召回依据。按来源去除近重复片段，并限制同一教材章节和父卡占用的名额。

## 第一阶段检索基准

```bash
python -m eval.rag_benchmark --output /tmp/medtrace-rag-report.json
```

[50 条合成查询及标签](../eval/retrieval_queries.v1.jsonl) 含 41 条有相关证据、9 条无相关证据的查询。以下为第一阶段结果。两种排序共用同一指导资料、FTS5 候选、上下文处理及返回预算。

| 指标 | BM25 | 重排及过滤 |
| --- | ---: | ---: |
| Recall@1 | 83.41% | 82.20% |
| Recall@3 | 94.55% | 91.30% |
| Recall@5 | 96.75% | 93.50% |
| 证据准确率@5 | 44.96% | 96.49% |
| 无关信息比例@5 | 55.04% | 3.51% |
| 无相关证据时空返回率 | 44.44% | 100% |

Recall 在有答案的查询上取宏平均；证据准确率和无关信息比例按实际返回条目计算。当前指标衡量指南草稿语料上的相关性，尚缺独立临床标注和正式病例评估。混合表述组的 Recall@5 为 70.37%，口语化失语描述和腹水影像异名是主要漏召类型。教材已实际建库并做了检索核验，表中指标不包含教材。

## ZIP 交付

`python scripts/build_submission.py --output /absolute/path/algorithm.zip` 可生成比赛结构预检包。完成审核后，使用 `scripts/build_knowledge.py` 生成 SQLite 发布库，可重复指定 `--source`。打包时传入 `--knowledge /absolute/path/knowledge.sqlite`。生成的 `resource_manifest.json` 登记库文件大小、版本、SHA-256、依赖和来源。解压后的比赛入口自动加载 `resources/knowledge.sqlite` 及伴随清单。当前分支的真实指南和教材仍待签审，比赛预检包暂未携带临床发布库。
