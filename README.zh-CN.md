# MedTrace — 可溯源的首次病程草稿

[English](README.md) | **简体中文**

用于教学、比赛及评测：从入院资料生成病例特点、拟诊讨论、诊疗计划、依据与待核事项。生成结果须经医生审核，不直接用于诊疗。

## 比赛入口

统一环境Python 3.11。执行 `python -m pip install -r requires.txt` 后，无参数运行 `python main.py`。输入输出以main.py所在目录为基准，不依赖启动目录。

主办方放入input.json和.env；.env只允许两项非空配置：

```dotenv
MODEL_NAME=replace_with_model_name
ENDPOINT=http://127.0.0.1:8000/v1/chat/completions
```

ENDPOINT是完整请求地址，不再拼接路径。官方运行不发送鉴权头，不继承代理、netrc凭据或开发环境的模型、路径、提示词和参数设置。

input.json为数组：case_id是文件内唯一非空字符串，record_cutoff是有效时间或T0，sources内含唯一非空字符串source_id及非空字符串content。病例标识或顶层协议错误退出2；单例截止点、资料或生成失败，保留failed记录并继续。

output.json在整批处理结束后原子发布。每条包含case_id、status、medical_record、error。成功的medical_record含case_features、diagnostic_discussion、plan、evidence、review_items。evidence每条含statement、source_ids、kind（fact/inference）；review_items为字符串数组。失败时medical_record=null，error含code及message。顺序与标识匹配输入，空输入输出[]。缺段结果在调用预算内重生成，仍无效则失败。

退出码：0为完整输出已写入（允许单例失败）；1为任务运行或输出/日志写入失败；2为配置或基本输入协议错误。根目录run_log.json对应本次完整运行；logs/run_log.jsonl保留追加记录。日志含运行标识、时间戳、病例映射、逐次请求信息、调用/重试次数、token用量和输入输出摘要。

默认固定参数：A2、v2提示词、temperature=0、seed=42、每例最多2次逻辑调用、每次最多2次瞬时错误重试、请求超时600秒、单工作线程、额外模型修复关闭。正式限额须按赛方最终附件确认，当前参数不代表已获赛方批准。若服务不支持 seed，须显式记录变更；客户端不会静默丢弃。

## 测试打包

当前未分配队伍编号，打包仅用于测试。`python scripts/build_submission.py --output /绝对路径/新目录/submission.zip`生成白名单包，拒绝覆盖已有归档。包内含文件哈希、提示词指纹和源码版本，不含真实.env、开发数据、评测脚本、测试、开发配置模板或本地日志。

从解压算法包完成一次运行后，用 `python scripts/build_submission.py --results-from /绝对路径/解压目录 --output /绝对路径/新目录/results.zip`生成测试结果包。程序核对完整日志、病例映射、计数、输入输出哈希和源码清单，只打包output.json、run_log.json及算法清单。模拟结果不得当作正式比赛结果。

可选--knowledge只接受已校验知识库并随包分发；官方运行自动读取resources/knowledge.sqlite。当前没有获批的临床知识库。

## 开发与验证

离线测试：将ZIP解压至新目录，设置进程环境LLM_API_BASE=mock://、OUTPUT_PROTOCOL=official，再执行 `python main.py --development --input /绝对路径/input.example.json --output /绝对路径/test_output.json`。这是显式模拟运行。

开发实验须加--development；可在独立工作目录使用.env.development.example，启用模型别名、路径与参数配置，默认输出与官方模式相同（`OUTPUT_PROTOCOL=legacy` 可改用旧扁平输出）。评测模块显式使用开发配置。

运行 `python -m unittest discover -s tests -v`检查回归；测试包含本地HTTP模拟服务下、仅两项.env配置的无参数比赛入口，测试产物保留。

## 方法与证据

项目采用事实台账、带来源生成与确定性校验。规则不能证明临床推断正确，也不能发现所有遗漏。历史公开数据上的非指定模型结果不替代指定服务验收。

第一阶段开发候选加入中文 ConText 式作用域与 DSPy MIPROv2 组织指令优化，共享持久化300次请求预算。正式默认值不变，候选待临床盲评；分组、续跑、报告与使用方法见仓库中的 [第一阶段实验](https://github.com/DrZeroK/MedTrace/blob/codex/context-prompt-experiments/docs/PHASE1_EXPERIMENTS.md)。

详见[项目说明](docs/PROJECT_DESCRIPTION.md)、[协议及待验收项](docs/REQUIREMENTS.md)、[声明](docs/DECLARATIONS.md)、[资源登记](docs/RESOURCE_REGISTRATION.md)、[知识库说明](docs/KNOWLEDGE_BASE.md)。
