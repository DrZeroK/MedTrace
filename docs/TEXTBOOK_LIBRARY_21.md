# 21 本教材的本地纯文本检索库

[English](TEXTBOOK_LIBRARY_21.en.md) | **简体中文**

状态：已生成过滤后的 21 本教材纯文本语料和 SQLite FTS5 检索库（数据库排除人体寄生虫学），全部为本地研究数据。

- 语料：`data/reference_indexes/textbooks-text-21-v2/`
- 索引：`textbooks.sqlite` 及 `textbooks.manifest.json`
- 语料规模：21 本、7,965 页、10,491,035 字
- 检索规模：20 本、7,683 页、10,105,699 字、15,146 个片段；索引约 151 MiB
- 人体寄生虫学保留语料和 OCR 提取物，但已从数据库移除；按书名查询为空
- 自检：`verification.json`；源页与切点记录：`corpus.manifest.json`
- 未过滤的 21 本语料保留在 `textbooks-text-21-v1/`

两本教材的结构化知识卡和 term/lab/rule 类型库仍在 `textbooks-kb-v1/`、`textbooks-kb-v2/`，
见 [TEXTBOOK_SEARCH.md](TEXTBOOK_SEARCH.md)。本轮只扩展纯文本检索库，未对新增 19 本做类型细分。

## 教材范围

内科学、诊断学、医学生物学、有机化学、病理生理学、皮肤性病学、外科学、病理学、生理学、
儿科学、医学遗传学、人体寄生虫学、医患沟通、生物化学与分子生物学、组织学与胚胎学、药理学、
医用高等数学、基础化学、医学心理学、麻醉学、妇产科学。

前两本沿用已有的筛选语料；其余 19 本从 PDF 正文起始页开始抽取。每本的正文起始页、偏移和
PDF SHA-256 记录在 `source_pages.json`（本地研究元数据，不进入检索文本）。人体寄生虫学因 OCR
质量与页码不可靠，仅保留语料/OCR，不进入检索数据库；其余 20 本可检索。

## 抽取与 OCR

- 19 本 PDF 使用 `scripts/pdf_text.swift`（macOS PDFKit `page.string`）逐页抽取文字；脚本只读取本地 PDF，输出页级 JSON。
- 人体寄生虫学 PDF 没有文本层，使用已有的 323 页 Apple Vision OCR 缓存；该书的 OCR 语料仍保留，
  但已从检索数据库排除。其他教材使用原生文本层。
- 抽取后的页级 JSON 通过 `scripts/pdf_json_corpus.py` 转为纯文本页标记，并用 `--copy-corpus` 合并两本已有语料。
- 检索语料和索引不保存 PDF 路径；页级 JSON、OCR 缓存和 PDF 都留在本地忽略目录。

## 过滤规则

`textbooks-text-21-v2` 由 v1 经 `textbook_search.py filter` 生成：

- 删除参考文献/推荐阅读页、索引页、空白页、广告/封底页和习题/答案页。
- 按 `data/reference_indexes/textbook_filter_21.json` 中的每本教材后置切点，删除索引、封底和答案区。
- 保留正文附录和工具表，例如寄生虫学/儿科学附录、数学公式表、化学常数表、有机化学鉴别反应表。
- 删除导航、“本章目标测试/思维导图”、出版社/封底文字、作者署名、`JOEE` 字体残留、页首页码和重复页眉。
- 被删页面保留编号空洞；`页 N` 是 v1 文本页序号，`书页 M` 是原书页码标签。

v1 的 8,247 页过滤后保留 7,965 页，删除 282 页。典型删除：医用高等数学答案页 246–261、
基础化学部分习题答案 294–307、病理生理学章节目标测试页、组织学与胚胎学中部广告页，
以及各书末尾的索引/封底。具体分类计数见 `corpus.manifest.json` 的 `removed_categories`。

## 查询

```bash
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-21-v2/textbooks.sqlite --query '细胞周期' --book 医学生物学第10版 --limit 5
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-21-v2/textbooks.sqlite --query '阑尾炎' --book 外科学第10版 --limit 5
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-text-21-v2/textbooks.sqlite --query '阿托品' --book 药理学第10版 --limit 5
```

多关键词按 AND 匹配，中文二元组和英文完整词用 BM25 排序；单个汉字用字面匹配。输出包含书名、
文本页号、书页页码、页码依据、分值和原文。人体寄生虫学因 OCR 缺页码，`printed_page` 可能为空。

## 重建与新增教材

```bash
# 1. 抽取 PDF 为页级 JSON（每本一次）
swift /Users/zerok/Documents/GitHub/MedTrace/scripts/pdf_text.swift /absolute/book.pdf /absolute/book.json
# 2. 将页级 JSON 转为纯文本原始语料；可合并已有语料
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/pdf_json_corpus.py --metadata /absolute/metadata.json --out /absolute/new/raw-corpus --copy-corpus /absolute/existing-corpus
# 3. 按后置切点过滤
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py filter --corpus /absolute/raw-corpus --out /absolute/filtered-corpus --cutoffs /absolute/cutoffs.json
# 4. 构建 FTS5 索引
python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py build --db /absolute/new/index.sqlite --corpus /absolute/filtered-corpus --exclude-book 人体寄生虫学第10版
```

新增教材时先确定正文起始页/偏移，检查末尾的参考文献、索引、附录、答案和封底，再补切点。
输出目录和数据库路径必须为新的绝对路径，现有语料与索引不会被覆盖。

## 覆盖与核验

- 20/20 本可检索教材的检索探针均返回结果，覆盖医学、化学、数学、心理、沟通、遗传等学科。
- 人体寄生虫学不在数据库；以该书书名过滤查询返回 0 条，但语料和 OCR 提取物仍保留在本地。
- `参考文献`、`中英文名词对照索引`、`推荐阅读`、`本章目标测试` 查询均无结果。
- SQLite 完整性检查通过；索引中无 `/Users/`、`file://` 或 `.pdf` 路径痕迹。
- 本库是用户提供教材的本地研究语料，不是已获再分发许可的提交资源，不替代临床或教学审核。
