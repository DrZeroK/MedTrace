# 两本教材的本地纯文本检索与结构化知识卡

[English](TEXTBOOK_SEARCH.en.md) | **简体中文**

## 21 本教材统一检索

过滤后的 21 本纯文本语料位于 `data/reference_indexes/textbooks-text-21-v2/`，共 7,965 页、
10,491,035 字；检索数据库排除人体寄生虫学，实际收录 20 本、7,683 页、10,105,699 字、15,146 个片段。
已删除参考文献/推荐阅读、索引、习题/答案、广告/封底和重复页眉，保留正文附录与工具表；
逐本后置切点、抽取方式和 OCR 说明见 [TEXTBOOK_LIBRARY_21.md](TEXTBOOK_LIBRARY_21.md)。

```bash
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-21-v2/textbooks.sqlite --query '阑尾炎' --book 外科学第10版 --limit 5
```

去掉 `--book` 可跨书检索。人体寄生虫学仅保留语料/OCR，不进入检索数据库，按书名查询为空；
其余教材的临床或教学核对仍须回合法取得的原 PDF。本文件其余部分描述两本教材的结构化知识卡与
term/lab/rule 类型库。

已完成筛选后的离线纯文本语料与检索索引：2 本教材、1515 页、2,176,489 字。
语料位于 `data/reference_indexes/textbooks-text-v2/`，由 `内科学第10版.txt`、`诊断学第10版.txt`
和 `corpus.manifest.json` 组成；`textbooks.sqlite` 及其 `.manifest.json` 是由语料生成的可重建索引，
`verification.json` 保存本轮自检结果。整个目录已排除在 Git 与提交包之外。
未筛选的原文语料保留在 `textbooks-text-v1/`，用于回溯或调整筛选规则。

在纯文本语料之上，`textbooks-kb-v1/` 按知识库条目规范生成了 4493 张 `card` 草稿
（内科学 2640、诊断学 1853，共 2,121,289 字）；`textbooks-kb-v2/` 再按 PDF 原文
细分出 326 条 `term`、118 条 `lab`、7 条 `rule`，与卡片合计 4944 条。层级和字段见下文。

纯文本检索与索引不依赖 PDF：构建与查询只用 Python 标准库，不导入 PDF 解析器、不做 OCR，
语料与索引中也不保存 PDF 路径或 PDF 页码。类型细分另有一次性的 PDF 审校步骤
（`scripts/pdf_text.swift` + `scripts/textbook_types.py`），只把核对证据写入条目元数据，运行时不读取 PDF。

## 筛选规则

v2 由 v1 纯文本语料生成，可重复执行：

- 删除各篇末尾的“推荐阅读”页；从最后一个“推荐阅读”页起，删除其后所有页（中英文名词对照索引、附图、空白页）。
- 删除空页。
- 删除“本章数字资源”“本节数字资源”“本章目标测试”“本节目标测试”等导航行，以及 `JOEE` 字体残留行。
- 删除页首页码；篇、章、节的重复页眉只保留首次出现，后续删除。

筛选结果：

- 内科学：951 页删除 23 页（8 个推荐阅读页、10 页索引、4 页附图、1 页空白），保留 928 页。
- 诊断学：603 页删除 16 页（1 个推荐阅读页、11 页索引、4 页空白），保留 587 页。
- 同时删除内科学 744 条导航/字体残留行、873 条页首页码、738 条重复页眉；
  诊断学对应为 159、564、503 条。
- 被删页面保留编号空洞，例如内科学第 168 页删除后从 167 直接到 169。`页 N` 仍是 v1 的文本页序号，
  不是重新编号，便于和原文语料对照。

## 语料格式

每本书一个 UTF-8 文本文件，开头是书名与说明，之后逐页排列：

```text
# 书名：内科学第10版
# 说明：纯文本正文库；页序号为文本内顺序，书页为原书页码标签，推算表示页码由起始偏移推断、未经页眉核对。
--- 页 1（书页 1，推算） ---
第一篇
绪论
--- 页 2（书页 2，页眉） ---
第一篇　绪论
一、　内科学概况
...
```

`页 N` 是 v1 语料中的顺序页号，可能因筛选出现空洞；`书页 M` 是原书印刷页码标签，可能因附录重新编号而重复。
`页眉`表示页码取自该页开头，`推算`表示按已核查的起始偏移推算，须回看正文确认。

## 查询

```bash
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-v2/textbooks.sqlite --query '心力衰竭' --limit 5
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-v2/textbooks.sqlite --query '低血糖' --book 内科学第10版 --full-page
```

多关键词按 AND 匹配，中文二元组及英文完整词用 BM25 排序；单个汉字用字面匹配。
每页最多返回一个片段，支持书名筛选；`--full-page` 返回该文本页的全部正文。

输出包含书名、文本页号、书页页码、页码依据、排序分值和原文片段，不包含 PDF 路径。
由于正文保留了原有换行，跨行断开的词可能漏检，可拆成较短关键词。
检索不做医学同义词推断，也不会把教材内容自动转成诊疗规则。

## 结构化知识卡

`data/reference_indexes/textbooks-kb-v1/` 按 `medtrace/knowledge.py` 的条目规范保存正文：

- `entries.jsonl`：4493 张 `card`，2,121,289 字（内科学 2640、诊断学 1853）。
  每张卡包含 `id`、`type`、`title`、`text`、`source`、`version`、`locator`、`license`、`status`、`scope`、`aliases`，
  以及 `permission_review`、`clinical_review`、`candidate_source_ids`、`source_id`、`source_note`、
  `structure`、`page_start`/`page_end`、`printed_page_start`/`printed_page_end`、`page_basis`。
- `outline.json`：按 `part → chapter → section → topic → subtopic → label` 记录每张卡的层级归属。
- `manifest.json`：来源教材哈希、卡片数量、`validate_entry` 校验结果与许可状态。
- `cards.sqlite` / `cards.manifest.json`：由卡片生成的本地草稿索引，`release=false`。
- `verification.json`：结构化校验与检索探针结果。

`source` 是 `knowledge/sources.json` 中的官方目录元数据 URL；正文来自用户提供的第 10 版电子版，
`source_note` 记录这一许可边界。以下命令用于首次构建或新目录；已有输出不会被覆盖，重建请换新路径。

层级解析识别“第X篇/章/节”“【...】”“一、...”“（一）...”；行内“【...】”会拆成独立标签。
超过 1800 字的卡片在行边界切分，并加 `（1/N）` 后缀。`scope` 初步设为内科学 `adult`、
诊断学 `general`；全部条目为 `status=draft`、`license=pending`、`permission_review=not_granted`、
`clinical_review=not_signed`，不能发布。v1 的卡片类型统一为 `card`；`term`/`lab`/`rule`
细分见下节。

```bash
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_kb.py structure --corpus /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-v2 --out /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v1
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_kb.py build --entries /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v1/entries.jsonl --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v1/cards.sqlite
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_kb.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v1/cards.sqlite --query '低血糖' --limit 5
```

`structure` 使用 `knowledge/sources.json` 中的 PMPH-IM10/PMPH-DX10 元数据；新增教材需要先登记来源映射。
`cards.sqlite` 只是草稿研究索引，不是 approved 知识库发布版；`scripts/build_knowledge.py` 仍会拒绝全部 draft 条目。
由于教材正文尚未取得再分发许可，结构化卡片保存在 `data/reference_indexes/`（Git 忽略），
评审并取得许可后才能按同一 schema 迁入正式知识库目录。

## term/lab/rule 细分与 PDF 审校

`textbooks-kb-v2/` 在 v1 的 4493 张卡之上新增受 PDF 原文审校的类型条目：

- `entries.jsonl`：4944 条 = 4493 `card` + 326 `term` + 118 `lab` + 7 `rule`。
- `typed.jsonl`：451 条 `term`/`lab`/`rule`；`typed_outline.json` 记录其层级归属。
- `typed_audit.json`：候选/命中/跳过清单、PDF 文件名与 SHA-256、页数和审校依据。
- `index.sqlite` / `.manifest.json`：合并索引，`release=false`。
- `verification.json`：`validate_entry`、索引完整性、类型计数和检索探针结果。

PDF 审校方式：`scripts/pdf_text.swift` 用 macOS PDFKit 逐页抽取原文；内科学 PDF 页 = 书页 + 31，
诊断学 = 书页 + 23。每个类型条目的 `pdf_audit` 记录 `pdf_pages`、命中的标题/单位/阈值证据与抽取方法；
`locator` 继续使用书页和文本页，不保存 PDF 路径。

细分规则：

- `term`：取章/节标题，排除“总论/病因/临床表现/治疗/检查/测定/穿刺”等结构词和操作、检验标题；
  在 PDF 页面按标题行核对；别名只从该卡正文的英文括注中提取，并在 PDF 页面复核。共 326 条。
- `lab`：取诊断学 `【参考区间】` 卡中层级最具体的检验名，排除组套、多项目和单位不明条目；
  单位从原文提取并在 PDF 页面核对；`reference_interval` 全部置空，因为人群、标本和方法尚未签审。
  共 118 条。
- `rule`：只保留原文可核对的严格 `>`/`<` 阈值，共 7 条：血清钾 >5.3、FEV1/FVC <70%、
  中性粒细胞绝对值 <1.5 / <0.5、血尿酸男性 >420 / 女性 >360、血糖 <2.8。
  `requires` 只写原文明确条件，缺少的写“未注明”；条件不足时规则返回 `insufficient`，不自动放行。
  这些不是临床发布规则，不能用于诊疗。

审校统计：term 327 个候选命中 326 个；lab 150 个候选命中 118 个（24 个标题/单位未在 PDF 窗口命中，
8 个组套或单位不明条目人工排除）；rule 7 个全部命中。未命中项和排除原因保留在 `typed_audit.json`。
所有类型条目仍为 `status=draft`、`license=pending`、`permission_review=not_granted`、
`clinical_review=not_signed`，0 条 approved；PDF 审校只证明来源与数值位置，不构成临床签审。
以下命令用于首次生成；`textbook_types.py` 和 `textbook_kb.py build` 都拒绝覆盖已有输出，重建请换新路径。

```bash
swift /Users/zerok/Documents/GitHub/MedTrace/scripts/pdf_text.swift "$HOME/Downloads/02《内科学（第10版）》.pdf" /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/pdf_text_audit/im10.json
swift /Users/zerok/Documents/GitHub/MedTrace/scripts/pdf_text.swift "$HOME/Downloads/09《诊断学（第10版）》.pdf" /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/pdf_text_audit/dx10.json
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_types.py --cards /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v1/entries.jsonl --pdf-audit /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/pdf_text_audit --out /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v2 --pdf-manifest /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-v1/textbooks.manifest.json
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_kb.py build --entries /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v2/entries.jsonl --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v2/index.sqlite
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_kb.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-kb-v2/index.sqlite --query '血钾测定' --limit 5
```

`textbook_types.py` 只处理 `knowledge/sources.json` 已映射的两本教材；新增教材需要同时补来源映射和 PDF 审校文本。
`textbooks-kb-v2/` 仍是本地研究数据，不进入提交包，也不并入 `knowledge/entries.jsonl`；评审并取得许可后才能迁移。

## 重建与迁移

首次迁移与筛选已完成；如需重建，使用新目录，现有语料和索引不会被覆盖：

```bash
# 一次性迁移：只读取旧索引中已提取的文字，不读取 PDF
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py export --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-v1/textbooks.sqlite --corpus /absolute/new/raw-corpus
# 筛选：删除参考文献、索引、附图、空白页和页眉页码噪声
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py filter --corpus /absolute/raw-corpus --out /absolute/filtered-corpus
# 从筛选后的纯文本语料构建索引
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py build --db /absolute/new/index.sqlite --corpus /absolute/filtered-corpus
```

`build` 会校验 `corpus.manifest.json` 中每个文本文件的 SHA-256，再生成 `pages`、`chunks` 和 FTS5 索引。
`filter` 会在新语料的 manifest 中记录被删页面和各类删除行的数量。

## 覆盖与核验

- 内科学：v1 的 951 页中保留 928 页，最后保留到第 935 页；第 951 页空白已删除。
- 诊断学：v1 的 603 页中保留 587 页，最后保留到第 588 页；第 82、601–603 页空白已删除。
- 自检覆盖心力衰竭、低血糖、血糖、BNP、单字查询、无匹配查询，以及“推荐阅读”“中英文名词对照索引”
  “本章数字资源”等噪声查询；噪声查询均无结果，SQLite 完整性检查通过。
- 结构化卡片共 4493 张，全部通过 `validate_entry`，ID 无重复；`cards.sqlite` 完整性检查通过，
  manifest 标记 `release=false`。
- 类型细分合计 4944 条（4493 card + 326 term + 118 lab + 7 rule），全部通过 `validate_entry`，0 条 approved；
  `index.sqlite` 完整性检查通过，`release=false`。
- PDF 审校统计：term 326/327 命中，lab 118/150 命中（其余为 PDF 窗口未命中或人工排除的组套/单位不明条目），
  rule 7/7 命中；证据和跳过原因见 `typed_audit.json`。
- 类型检索探针：`低血糖症` 命中 term 表；`血钾测定` 命中 lab 表；`高钾血症 5.3` 命中 rule 表；
  `白细胞计数 参考区间` 命中“白细胞计数”lab 条目；`肺脓肿 治疗` 命中 card 表；
  “推荐阅读”“本章数字资源”无结果。
- 本机文本页查询约 0.2–11 ms；这是少量查询探针，不是全面性能基准。卡片/类型检索未做性能基准。
- 实测定位包含心衰书页 176/180、低血糖 748、血糖检测 355，均直接以文本页号和书页页码返回。
- 筛选是启发式规则；如临床核对需要参考文献、索引或附图，请查阅保留的 v1 语料或合法取得的教材原件。
- 结构化卡片和类型条目仍是 draft：临床内容、适用人群、检验单位和引用条款均未签审，不能作为诊疗依据；
  7 条 rule 在条件不足时返回 `insufficient`，不是可直接启用的临床规则。

这是用户提供教材的本地研究语料，不是已获得再分发许可的提交资源，也不替代临床知识卡签审。
