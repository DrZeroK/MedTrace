# Notice

`cases.json` and `references.json` are derived from **CMB-Clin**, part of *CMB: A Comprehensive Medical Benchmark
in Chinese* (Wang et al., arXiv:2308.08833), https://github.com/FreedomIntelligence/CMB, licensed under the
Apache License 2.0 (http://www.apache.org/licenses/LICENSE-2.0).

Changes made (see `data_pipeline/cmb_clin.py`): case descriptions were split into sections and written as
`sources`; case titles, empty figure-caption sections and post-admission course sections were left out of
`sources`; leading patient names were replaced by "患者"; expert answers were copied unedited into `references.json`;
classification, quality flags, splits and rule-derived fact lists were added. The underlying cases are textbook
teaching material, not hospital records. This is a benchmark: do not use the `validation` or `test` splits for
prompt development, and do not train on any of it.

项目用户于 2026-11-18 确认以下标点勘误。更正适用于标准化病例及规则派生事实。专家答案与上游文件保留原文。

- `cmbclin-019-hpi` 改为“否认高血压、糖尿病史，否认手术病史。”，“否认”包含糖尿病史。
- `cmbclin-026-hpi` 改为“大便色浅，不伴寒战高热、恶心呕吐”，“不伴”包含恶心呕吐。
