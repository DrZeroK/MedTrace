# 临床智录离线检索

本分支把本地检索接入现有 MedTrace 生成流水线。检索器使用 Python 标准库和 SQLite FTS5。输入支持自由文本，或 `history`、`symptoms`、`labs`、`exams` 字段。比赛流水线使用已按截止点处理的事实账本，检索无额外模型调用。返回的知识卡 `id` 标识证据片段，`source_id`、`version` 和 `locator` 用于审计和回查。正式输出的 `medical_record.evidence[].source_ids` 仍按赛题协议引用本病例的资料 ID。

## 2026-11-24 扩库与教材分块

新增 [24 条纯文字知识卡](../knowledge/guidelines.v3.jsonl)，来自 13 份文件，其中 10 份是指南、3 份是专家共识。补充皮炎湿疹、皮肤鳞癌、脓疱型银屑病、药疹、儿童春季角膜结膜炎、原发性闭角型青光眼、近视、乳腺癌、原发性肝癌、成人幽门螺杆菌感染、帕金森病、急性肺栓塞和成人惊厥性癫痫持续状态。来源版本和适用范围按各机构原文件登记。三批合计 111 条纯文字卡。

教材分块保留目录层级、标点和原始定位。块长目标 760 字符，优先使用保留的换行、句末或分句断点；分割避开检验值及单位。每块保留父条目、字符区间、`source_id`、版次及页码依据。由纯文本页重新整理时，页码只覆盖该块涉及的页面；已存在的旧父卡没有页内偏移时，子块沿用父卡页范围。用途根据原有标签或小节标题填写。

```bash
root="$(mktemp -d)"
python scripts/textbook_kb.py structure \
  --corpus data/reference_indexes/textbooks-text-21-v2 --out "$root/structure"
python scripts/textbook_kb.py organize \
  --entries "$root/structure/entries.jsonl" --output "$root/chunks.jsonl" > "$root/chunk-audit.json"
python scripts/textbook_kb.py build --entries "$root/chunks.jsonl" \
  --exclude-book 人体寄生虫学第10版 --db "$root/textbook-search.sqlite"
python scripts/textbook_kb.py build --entries "$root/chunks.jsonl" --clinical-only \
  --supplement knowledge/guidelines.v1.jsonl \
  --supplement knowledge/guidelines.v2.jsonl \
  --supplement knowledge/guidelines.v3.jsonl \
  --db "$root/clinical-drafts.sqlite"
python -m eval.rag_benchmark --cards knowledge/guidelines.v3.jsonl \
  --queries eval/retrieval_guidelines.v3.jsonl
```

全量命令需要私有仓库已提供的纯文字教材及其语料清单。实际整理 21 册，共 20,144 个父条目、26,110 个证据片段，片段均在 760 字符内。通用检索库含 20 册、25,226 片，逐册探针 20/20 命中。人体寄生虫学的 884 片保留供本地审阅，因为 OCR 和页码质量仍待复核。临床库选择 10 册与诊疗直接相关的教材，叠加三批指南和共识，共 17,571 条，逐册探针 10/10 命中。新增书目的版次和文件哈希来自既有教材语料，未经核对的 ISBN 不填。

新增指南的 16 条合成查询含 13 条正例和 3 条反例。新版卡单独索引时，Recall@5 和证据相关准确率@5 均为 100%，三条反例均为空。测试样例由团队编写，用于检查继续扩库后的基础检索和范围过滤。临床混合库在官方 8 份练习病历的 10 个主题中命中 9 个，原有短暂性局灶神经症状漏召仍需处理。

## 指南与共识扩库

截至 2026-11-23 核对并新增 30 份来源，含 25 份指南或诊疗方案、5 份专家共识。[纯文字条目](../knowledge/guidelines.v2.jsonl) 有 54 条可检索知识卡，分别为诊断 15 条、鉴别 5 条、检查 12 条、治疗 22 条。来源包括国家卫健委、中华医学会及相关专业组织。重点补充慢阻肺、儿童肺炎支原体肺炎、高血压、房颤、慢性肾脏病、肝硬化、风湿免疫病、睡眠障碍、重症肌无力及部分肿瘤筛查。诊疗指南、专项治疗共识、筛查方案按原文适用范围分别取材。罕见病、眼科、皮肤科、精神科及肿瘤分型治疗仍有明显覆盖缺口。

正文为独立撰写的纯文本摘要，来源链接只存于 `source_url`。每条带 `id`、`source_id`、发布组织、版本、核验日期、原文章节、用途及适用人群。成人基层高血压卡限定非孕人群（`nonpregnant_adult`），普通人群糖尿病诊断和治疗卡限定非孕人群（`nonpregnant`）。入库校验只接受 `general`、`adult`、`pediatric`、`pregnancy`、`nonpregnant`、`nonpregnant_adult` 六种人群标签。新条目通过仓库原有 schema 校验，并额外检查纯正文、HTTPS 溯源和新条目的出版元数据。正式库需完成许可和临床签审。

每份病历都会出现的常规检查名，如 BMI、腰围、空腹血糖、HbA1c、eGFR、UACR、淀粉酶、脂肪酶、心脏超声、BNP、TSH、骨密度、LDL-C、乙肝核心抗体，不作为疾病卡的检索关键词。否则一份结果全部正常的体检病历会召回糖尿病、心衰、胰腺炎和慢性肾脏病等卡。疾病卡改由病名或异常所见触发，例如"糖尿病""血压反复升高""白蛋白尿"。

把下方五册构建命令的 `build` 步骤加上 `--supplement knowledge/guidelines.v2.jsonl` 并指定新的绝对输出路径，得到与本轮一致的混合草稿结构。五册教材、第一批来源和本次新卡合计 12,028 条。来源核验不要求评测时联网。

```bash
python -m eval.rag_benchmark --cards knowledge/guidelines.v2.jsonl \
  --queries eval/retrieval_guidelines.v2.jsonl --output /tmp/medtrace-guideline-retrieval-v2.json
```

该合成定向集有 14 条带证据的查询和 6 条反例。新增的两条反例是结果全部正常的体检病历，以及孕 26 周的 OGTT 异常病例。仅用新版条目测试时，重排的 Recall@5 和证据相关准确率@5 均为 100%，无关信息比例为 0%，六条反例均为空返回。查询、证据标签和知识卡出自同一作者，这个成绩只说明卡片能被预期的说法召回，不代表真实病历上的效果。

五册混合草稿在 8 份官方练习病历上曾覆盖 10 个主题中的 9 个，漏召的是短暂性局灶神经症状主题。用指南卡模拟一份合并高血压、糖尿病和房颤的 TIA 入院记录时，修正前糖尿病诊断卡凭 HbA1c 和空腹血糖排在全部 TIA 卡之前，修正后 TIA 卡回到前三。练习病历需在本地用新索引重跑确认。

## 外部数据的本地评估

```bash
python -m eval.clinical_intake_retrieval --index /absolute/path/to/clinical-drafts-v6.sqlite \
  --output /tmp/medtrace-external-retrieval.json
```

CMB-Clin 34 例及 TypicalCase-DC 1,319 例全部通过标准化输入与参考标签的编号对账。CMB-Clin 的仓库 NOTICE 将其限定为基准评测用途；TypicalCase-DC 的期刊正文训练许可尚待明确。两套数据只做本地评估。外部集的截止字段不同于官方输入规范，因此结果仅用于开发。TypicalCase-DC 有 603 例具备诊断评测资格，其中 13 例能严格映射到本次结构化指南的诊断相关来源，前五命中 6 例。该指标只统计已知目标来源，样本很小，不能衡量整条证据的质量或判断未映射病例是否有教材证据。

曾试验用 100 份合成病历拟合检索词权重。练习集和 TypicalCase-DC 上的结果与未拟合排序完全相同，该实验已移除。

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
