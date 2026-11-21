# 临床智录离线检索

本分支把本地检索接入现有 MedTrace 生成流水线。检索器使用 Python 标准库和 SQLite FTS5。输入支持自由文本，或 `history`、`symptoms`、`labs`、`exams` 字段。比赛流水线使用已按截止点处理的事实账本，检索无额外模型调用。返回的知识卡 `id` 标识证据片段，`source_id`、`version` 和 `locator` 用于审计和回查。正式输出的 `medical_record.evidence[].source_ids` 仍按赛题协议引用本病例的资料 ID。

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

## 检索评估

```bash
python -m eval.rag_benchmark --output /tmp/medtrace-rag-report.json
```

[50 条合成查询及标签](../eval/retrieval_queries.v1.jsonl) 含 41 条有相关证据、9 条无相关证据的查询。两种排序共用同一指导资料、FTS5 候选、上下文处理及返回预算。

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
