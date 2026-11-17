# 两本教材的本地正文检索

已完成离线全文索引：1554个正文/附录范围内的PDF页，3379个重叠片段。
数据库约32.3 MiB，位于 `data/reference_indexes/textbooks-v1/textbooks.sqlite`，已排除在Git与提交包之外。
两个原始PDF仍在用户提供的Downloads路径，没有移动或改写。

## 查询

检索只使用Python标准库，不需要模型、网络或额外安装。多关键词按AND匹配，中文二元组及英文完整词用BM25排序；
单个汉字用字面匹配。每页最多返回一个片段。支持书名筛选，`--full-page`返回该PDF页的全部可提取文字。

```bash
/opt/homebrew/bin/python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-v1/textbooks.sqlite --query '心力衰竭' --limit 5
/opt/homebrew/bin/python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py search --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-v1/textbooks.sqlite --query '低血糖' --book 内科学第10版 --full-page
```

输出包含书名、PDF页码、书内页码、页码依据、原文件绝对路径、排序分值和原文文本。
`printed_page_basis=header`表示从页面开头取得页码；`offset_inferred`表示按已核查的起始偏移推算，须回看页面确认。
PDF页码始终指向实际文件位置。由于正文解析会保留换行，跨行断开的词可能漏检，可拆成较短关键词。
检索不会做医学同义词推断，不会将教材内容自动转成诊疗规则。

## 覆盖与核验

- 内科学：PDF第32页起，包含绪论、正文及后续附录/索引；前31页未入库。
- 诊断学：PDF第24页起；前23页未入库。
- 无可提取文字的页已在manifest中列明：内科学PDF982；诊断学PDF105、624–626。
  这类页面以及图内文字未做OCR，图表应回原PDF核对；PDF文本解析不保证表格行列关系正确。
- 自检覆盖心力衰竭、低血糖、血糖、BNP、单字查询与无匹配查询，并通过SQLite完整性检查。
  本机首次心衰查询约365 ms，后续示例约2–97 ms；这是少量查询探针，不是全面性能基准。
- 实测定位包含心衰印刷页176、低血糖748、血糖检测355，对应PDF207、779、378。

数据库旁的 `.manifest.json` 保存原PDF路径、SHA-256、页数与范围；`.verification.json` 保存本轮自检结果。
重新构建需使用有pypdf的Python和新数据库路径，现有索引不覆盖：

```bash
/Users/zerok/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 /Users/zerok/Documents/GitHub/MedTrace/scripts/textbook_search.py build --db /Users/zerok/Documents/GitHub/MedTrace/data/reference_indexes/textbooks-v2/textbooks.sqlite --source 内科学第10版 '/Users/zerok/Downloads/02《内科学（第10版）》.pdf' 32 31 --source 诊断学第10版 '/Users/zerok/Downloads/09《诊断学（第10版）》.pdf' 24 23
```

这是用户提供教材的本地研究索引，不是已获得再分发许可的提交资源，也不替代临床知识卡签审。
