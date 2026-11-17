# Intelligent Generation of Initial Hospital Course Notes

## Consolidated Competition Rules, Technical Specifications, and FAQs

> **Editorial note:** The main rules are presented in neutral English, with geographic and institution-specific references removed or generalized. Model names are retained. All appendices are provided in both Chinese and English, and original Chinese text within sample code is preserved. Conflicting or pending requirements are identified explicitly rather than silently resolved. The latest officially released specifications take precedence.

---

## 1. Background

Clinical documentation is one of the most burdensome and repetitive aspects of clinical work. The initial hospital course note, often called the initial progress note, is a core inpatient medical record. At the beginning of a hospital stay, clinicians must use limited admission information to summarize case features, develop an evidence-based preliminary diagnostic discussion, and formulate a diagnostic and treatment plan. This process tests clinical reasoning and requires substantial time.

With the rapid development of large language models in healthcare, generative AI-assisted drafting of initial hospital course notes has become a representative application for reducing documentation burden and improving record standardization.

This challenge requires participating teams to develop a functional AI application that:

- Reads standardized teaching-case materials supplied by the organizer, including the chief complaint, history of present illness, past medical history, physical examination, and ancillary investigations.
- Uses only information available at or before a defined record cutoff.
- Calls the organizer-designated large language model (LLM) within the prescribed time and resource limits.
- Summarizes case features and produces an evidence-based preliminary diagnostic discussion and diagnostic and treatment plan.
- Identifies the sources supporting key content and lists information requiring clinician confirmation.

All outputs are intended solely for teaching, competition, and evaluation. They must not be used for real-world diagnosis or treatment.

## 2. Assessment Objectives and Technical Innovation

### 2.1 Core assessment objectives

The challenge assesses three integrated capabilities:

1. **Factual fidelity**
   - Generate strictly from the supplied information.
   - Do not invent facts.
   - Do not rewrite “not provided” as “normal.”
   - Do not introduce later diagnoses, hospital outcomes, or treatments already performed.

2. **Clinical analysis**
   - Support preliminary judgments with evidence.
   - Provide case-specific differential diagnoses.
   - Handle insufficient information appropriately and avoid unsupported conclusions.

3. **Engineering reproducibility**
   - Support batch processing.
   - Use standardized configuration.
   - Maintain complete logs.
   - Produce results that can be reviewed and reproduced.

### 2.2 Technical innovation

Participants are encouraged to build an **extract → organize → generate → validate** pipeline around LLM calls. Potential approaches include:

- **Fact extraction:** Extract structured facts to reduce omissions.
- **Temporal organization:** Filter and organize information according to the record cutoff.
- **Staged generation:** Use multiple pipeline calls to improve logical consistency.
- **Retrieval-augmented generation:** Use permitted offline retrieval resources to support differential diagnosis.
- **Post-generation validation:** Perform numerical source verification and schema validation.

Participants may independently design and justify improvements. Comparative experiments should demonstrate the actual benefit of each improvement.

## 3. Eligibility and Team Composition

- The challenge is open to enrolled undergraduate students at recognized higher education institutions.
- There are no restrictions on major or year of study.
- Participation is team-based.
- Each team must have **3–5 members**.
- Each team may have **no more than 2 faculty advisers**.

## 4. Competition Structure and Rules

The challenge consists of three stages:

1. Institutional preliminary selection and recommendation.
2. A development and unified evaluation round.
3. A final round.

The overall schedule will be announced by the organizing committee.

### 4.1 Institutional preliminary selection

Each institution organizes its own preliminary selection based on the published challenge tasks. Each institution may recommend **no more than five teams** for the development and unified evaluation round.

### 4.2 Development and unified evaluation round

This round uses the following format:

**Online development + unified submission + online review + offline verification**

During the development period, teams use Python to build programs capable of processing cases in batches. Teams considered for awards must also complete an offline algorithm-reproduction check.

#### Core Task 1: Algorithm development and model invocation

- Read the admission information supplied by the organizer.
- Remotely call the organizer-designated Qwen model.
- Generate an initial hospital course note containing three required narrative sections:
  1. Case features.
  2. Preliminary diagnostic discussion.
  3. Diagnostic and treatment plan.
- Attach traceable supporting evidence using valid `source_id` values.
- Provide review items requiring clinician confirmation.

#### Core Task 2: Unified evaluation run

- On the designated evaluation date, the organizer runs the submitted algorithm package against the official cases and collects the results.
- Programs must run in the closed-network environment supplied by the organizer.
- The unified entry point is `main.py`.
- The designated runtime is Python 3.11.

### 4.3 Submission materials

1. **Algorithm package and source code**
   - File name: `team_id_algorithm.zip`.
   - Must include a README, the required `requires.txt` dependency file, the unified entry point `main.py`, prompt texts and versions, fixed model parameters, and a random seed where supported.
   - These materials must support reproducible results.

2. **Result package and run records**
   - File name: `team_id_results.zip`.
   - Must include the result JSON file covering every official case and `run_log.json`.
   - Manually rewriting the generated narrative content is prohibited.
   - See Appendix 4, Question 9, regarding the temporary naming discrepancy between `output.json` and `results.json`.

3. **Project description**
   - Maximum length: 10 pages.
   - Must describe prompt design, the generation workflow, improvements, and limitations.

4. **Declarations**
   - Models and versions used.
   - Sources and versions of retrieval resources.
   - LLM-use declaration.
   - Data-use commitment.

### 4.4 Reference scoring dimensions

| Dimension | Evaluation content |
|---|---|
| Factual accuracy and fidelity | Important facts, values, chronology, and negation are correct, with no fabricated additions. |
| Preliminary diagnostic discussion and clinical analysis | Judgments are evidence-based, differential diagnoses are case-specific, and insufficient information is handled appropriately. |
| Relevance of the diagnostic and treatment plan | Investigations, management, and observation correspond to current problems; planned actions are distinguished from actions already performed. |
| Structural compliance and individualization | All three sections are complete and focused, reflect case-specific features, and avoid generic boilerplate. |
| Source attribution and review prompts | Key content can be checked against its sources; missing or conflicting information is clearly identified. |
| Algorithm reproducibility and improvement validation | The solution runs as documented, with complete configuration, dependencies, and logs; improvements are clearly defined and evaluated on public cases with benefits and limitations explained. |

### 4.5 Offline algorithm-reproduction verification

For teams considered for awards, the technical committee performs sampled on-site reproduction in the standardized environment supplied by the organizer. The process includes:

- Reinstalling dependencies in a clean environment.
- Running the algorithm through the unified `python main.py` entry point.
- Checking consistency between regenerated results and the submitted result package.
- Verifying the authenticity of run records, including call counts, timestamps, and case-ID mappings.

A team representative must observe the verification and respond to questions from the technical judges.

The algorithm-reproduction component receives zero if:

- Reproduction fails.
- Regenerated results differ materially from the submitted results.
- Run records cannot be reconciled with the submitted materials.

Suspected fabrication of run records or log tampering is handled under the competition's violation procedures. Offline verification does not change the existing scoring weights; it serves as an eligibility gate for awards and final-round recommendation.

### 4.6 Final round

Final-round arrangements and awards will be announced separately by the organizing committee.

## 5. Equipment, Resources, and Safety

### 5.1 Equipment and software requirements

1. **Routine development**
   - Teams must provide their own internet-connected computers for ordinary development, debugging, and testing.

2. **Evaluation environment**
   - Participants are not required to provide servers or graphics-acceleration hardware for the formal evaluation.
   - The organizer supplies the standardized runtime.
   - The formal Python version is 3.11.
   - Dependencies are installed using `pip`.

3. **Model interface**
   - The unified evaluation runs in the organizer's closed-network environment.
   - The model is supplied through a keyless interface.
   - The runtime, unified entry point, model configuration, and input/output protocol must strictly follow the technical specifications.

### 5.2 Resource support

| Support | Method and scope |
|---|---|
| Challenge materials | The organizer publishes practice cases, the model list, interface documentation, and technical specifications. |
| Evaluation resources | The formal evaluation provides a closed-network environment, a unified entry point, and a keyless model API. |
| Technical support | The technical committee responds to technical questions and interprets the rules. |

### 5.3 Safety and risk requirements

1. **Data security**
   - Competition case materials may be used only during the competition.
   - Teams must not distribute them externally or use them for other purposes.
   - Generated outputs are solely for teaching and evaluation and must not guide real-world diagnosis or treatment.

2. **Compliant use**
   - Teams must comply with all model-use restrictions.
   - Only the officially designated models may be called.

3. **Network and system security**
   - Teams must not attack, stress-test, or gain unauthorized access to the evaluation environment.
   - Discovered issues must be reported promptly to the organizing committee.
   - Fabricating run records or tampering with logs is prohibited and will be handled under the violation procedures.

## 6. Additional Provisions

1. **Review and awards**
   - Institutions complete preliminary recommendations.
   - The development and unified evaluation round conducts the formal review, grants first-, second-, and third-prize awards, and recommends teams for the final round.
   - Final-round awards follow the competition's general rules.

2. **Rule interpretation**
   - Matters not covered here are determined jointly by the technical committee and organizing committee.
   - If these rules conflict with other general competition regulations, the organizing committee's regulations take precedence.

---

# 附件 1. 学生拿到的输入入院资料与首程输出示例（中文版）

> 以下为完全人工编写的格式示例，不来自真实患者，也不是正式比赛答案。具体医学要点由赛方专家审定。

**病例编号：** `DEMO001`  
**资料截止点：** `T0`  
以下资料在 `T0` 已可获得。

## 1.1 输入资料

| source_id | 资料内容 |
|---|---|
| `S01` | 成人，乏力 2 周，活动后心悸；现有记录未见明确黑便、肉眼血尿或其他出血表现。 |
| `S02` | 结膜苍白、双下肢轻度水肿；未提供血压、尿量及其他体征。 |
| `S03` | 血红蛋白 82 g/L，实验室标低；肌酐 185 μmol/L，实验室标高；未提供既往肌酐、红细胞指数、网织红细胞或尿检。 |
| `S04` | 既往病史、药物史、肾功能基线和贫血既往检查未提供；入院初步判断为贫血及肾功能异常，原因待查。 |

## 1.2 算法应输出的首程示例

### 病例特点

成人，近 2 周乏力、活动后心悸，现有记录显示结膜苍白和双下肢轻度水肿。血红蛋白 82 g/L、肌酐 185 μmol/L，实验室分别标示降低和升高。现有记录未见明确出血表现；既往血红蛋白、肾功能基线、血压和尿量不详。

### 拟诊讨论

现有资料支持贫血及肾功能异常，需要分别明确原因及两者关系。贫血需结合红细胞指数、网织红细胞和针对性检查进一步分析，现有记录不能排除隐匿失血、营养相关因素或其他原因。单次肌酐升高不足以确定急性或慢性过程，也不足以将贫血直接归因为肾性贫血。水肿需结合血压、尿量、尿检及相关检查综合判断。目前病因待查。

### 诊疗计划

由临床医生补充既往检查、症状变化、用药及出血相关病史，核实血压、尿量和容量状态；结合病情复核血常规及肾功能，按鉴别需要安排进一步检查。观察症状和指标变化，依据补充资料调整分析与处理，治疗需结合完整临床评估确定。

### 依据说明

- 血红蛋白 82 g/L 来自 `S03`，属于事实。
- 急慢性过程未明由 `S03` 和 `S04` 支持，属于推断边界。
- 其余关键症状和体征分别对应 `S01`、`S02`。

### 待核事项

- 既往肾功能及贫血病程。
- 血压、尿量及容量状态。
- 既往病史、用药史及出血相关病史。
- 红细胞指数、网织红细胞及尿检等缺失资料。

没有提供不等于正常；不能把初步判断写成已确诊病因，也不能补写已实施治疗。

## 1.3 比赛日流程

比赛日，学生运行自己的算法，以同样方式处理正式病例，把全部结果与日志上传指定入口，并附算法包。命题方收到材料后组织评分。

---

# Appendix 1. Sample Admission Input and Expected Output (English Version)

> This example is entirely synthetic. It does not come from a real patient and is not an official competition answer. The medical points are subject to expert review by the organizer.

**Case ID:** `DEMO001`  
**Record cutoff:** `T0`  
All information below is available at `T0`.

## A1.1 Input sources

| Source ID | Content |
|---|---|
| `S01` | Adult with fatigue for 2 weeks and palpitations on exertion; the available records document no clear melena, gross hematuria, or other bleeding manifestations. |
| `S02` | Conjunctival pallor and mild bilateral lower-limb edema; blood pressure, urine output, and other examination findings are not provided. |
| `S03` | Hemoglobin 82 g/L, flagged low by the laboratory; creatinine 185 μmol/L, flagged high by the laboratory; prior creatinine, red cell indices, reticulocyte count, and urinalysis are not provided. |
| `S04` | Past medical history, medication history, baseline renal function, and previous anemia investigations are not provided; the preliminary admission assessment is anemia and renal dysfunction, with the causes under investigation. |

## A1.2 Example initial hospital course note

### Case features

An adult presents with fatigue for nearly 2 weeks and palpitations on exertion. Available records show conjunctival pallor and mild bilateral lower-limb edema. Hemoglobin is 82 g/L and creatinine is 185 μmol/L, flagged low and high by the laboratory, respectively. No clear bleeding manifestations are documented in the available records. Previous hemoglobin values, baseline renal function, blood pressure, and urine output are unknown.

### Preliminary diagnostic discussion

The available information supports anemia and renal dysfunction. The cause of each abnormality and the relationship between them require further clarification. Anemia requires further evaluation using red cell indices, reticulocyte count, and targeted investigations. Occult blood loss, nutrition-related factors, and other causes cannot be excluded from the current records. A single elevated creatinine value is insufficient to determine whether the process is acute or chronic or to attribute the anemia directly to renal anemia. Edema should be assessed together with blood pressure, urine output, urinalysis, and relevant investigations. The etiology remains under investigation.

### Diagnostic and treatment plan

The clinician should obtain previous investigations, symptom progression, medication history, and bleeding-related history; verify blood pressure, urine output, and volume status; repeat the complete blood count and renal function as clinically indicated; and arrange further investigations according to the differential diagnosis. Symptoms and laboratory trends should be monitored. Analysis and management should be adjusted as additional information becomes available, and treatment should be determined through a complete clinical assessment.

### Evidence notes

- Hemoglobin 82 g/L comes from `S03` and is a **fact**.
- The inability to determine an acute or chronic process is supported by `S03` and `S04` and represents an **inference boundary**.
- Other key symptoms and signs correspond to `S01` and `S02`.

### Review items

- Baseline renal function and the course of anemia.
- Blood pressure, urine output, and volume status.
- Past medical history, medication history, and bleeding-related history.
- Missing red cell indices, reticulocyte count, urinalysis, and other relevant investigations.

“Not provided” does not mean “normal.” A preliminary assessment must not be rewritten as a confirmed etiology, and treatment must not be described as already performed.

## A1.3 Evaluation-day workflow

On the designated evaluation date, each team runs its own algorithm to process the official cases in the same manner, uploads all results and logs through the designated channel, and attaches the algorithm package. The organizer then reviews the submitted materials.

---

# 附件 2. 评分标准（中文版）

## 2.1 评价维度

| 评价维度 | 评价内容 |
|---|---|
| 事实准确与忠实性 | 重要事实、数值、时序和否定关系正确，无凭空补写。 |
| 拟诊讨论与临床分析 | 判断有依据，鉴别有针对性，正确处理信息不足。 |
| 诊疗计划针对性 | 检查、处理和观察安排与当前问题对应，区分计划与已实施事项。 |
| 结构规范与个体化 | 三段完整，重点清楚，体现病例特征而非泛化套话。 |
| 来源说明与待核提示 | 关键内容可核对来源，缺失和冲突提示明确。 |
| 算法实现与可复现性 | 按说明能运行，代码、提示词与提交结果对应，配置、依赖和日志完整。 |
| 改进方法与验证 | 改进点明确，能用公开病例对比说明收益及局限。 |
| 其他 | 不对界面美观或产品功能另行加分。 |

## 2.2 每例五个临床维度的得分点

### 维度 1：事实准确与忠实性

| 得分点 | 做法说明 |
|---|---|
| 关键事实正确 | 症状、体征、检验数值与资料一字不差，数值带单位，如 Hb 82 g/L。 |
| 时序正确 | 保留“乏力 2 周”“入院时”等原始时间表述，不颠倒先后。 |
| 否定与缺失如实保留 | “未见黑便”“血压未提供”原样保留“未”字；缺失的写“不详/未提供”。 |
| 无凭空补写 | 资料里没有的检查、病史一律不写；不将“未提供”改写为“正常/否认”。 |

### 维度 2：拟诊讨论与临床分析

| 得分点 | 做法说明 |
|---|---|
| 初步判断有依据 | 每个判断对应到具体资料，如“贫血待查（Hb 82 g/L，见 S03）”。 |
| 鉴别有针对性 | 围绕本例特点列 2—3 个鉴别方向并说明理由，不照搬教科书清单。 |
| 正确处理信息不足 | 资料不够时写“需进一步检查明确”；写“病因待查”不为缺点，不硬下结论。 |

### 维度 3：诊疗计划针对性

| 得分点 | 做法说明 |
|---|---|
| 计划对应当前问题 | 检查、处理与观察安排跟本例问题对应，不列无关的大而全清单。 |
| 区分计划与已实施 | 用“拟/建议/复查”表述，绝不把计划写成“已予/已完成”。 |
| 有观察安排 | 写明观察什么症状、复查什么指标。 |

### 维度 4：结构规范与个体化

| 得分点 | 做法说明 |
|---|---|
| 三段完整 | 病例特点、拟诊讨论、诊疗计划每段非空。 |
| 重点清楚 | 病例特点按“重要阳性→有价值的阴性→病程”排列，不写流水账。 |
| 个体化表达 | 输出体现本例特征，换一个病例无法直接套用。 |

### 维度 5：来源说明与待核提示

| 得分点 | 做法说明 |
|---|---|
| 依据可溯源 | `evidence` 列 3—5 条，不足 3 条按实际写；每条标注 `source_ids`，且编号真实存在于本病例。 |
| 事实推断区分 | 资料中原有内容标 `fact`，由算法推理得出的标 `inference`。 |
| 待核事项明确 | 缺失、冲突、需医生确认的问题列入 `review_items`；确实没有时写 `[]`。 |

## 2.3 整体评分部分的得分点

| 评分项 | 得分点 | 做法说明 |
|---|---|---|
| 算法复现 | 可重新运行 | 干净环境 `pip install -r requires.txt` 后，`python main.py` 能自动处理全部病例并正常退出。 |
| 算法复现 | 材料相互对应 | 代码、提示词、参数与提交结果一致；固定随机种子。 |
| 算法复现 | 配置日志完整 | `main.py`、`requires.txt`、`.env.example`、README 齐备；`run_log` 字段齐全且不含密钥。 |
| 改进验证 | 改进点明确 | 说清改进内容及解决的问题，如“数值回溯核对拦截抄错”。 |
| 改进验证 | 同条件对比 | 基线版与改进版在同一批公开练习病例上的结果对比。 |
| 改进验证 | 局限分析 | 说明代价（耗时/调用量）或尚未解决的问题。 |

## 2.4 评审与复核建议

- 每例由两名医学评委独立评分，依据赛前准备的逐例参考要点，允许合理的不同表达，不以文字相似度代替医学评价。
- 总分小计差异超过 10 分，或重大错误等级不一致时，由第三位医学专家复核争议项。
- 算法部分由技术评委结合线下复现核验评定：在统一环境现场抽样重跑队伍算法包，核对代码、提示词、配置与提交结果的对应关系。
- 复现未通过或运行记录不实的队伍，算法复现记零分，并视情节按赛事违规程序处理。
- 抽样病例与条件对各队一致；差异先核查模型随机性和版本，不直接认定作弊。

## 2.5 缺失输出、错误与处罚

- 所有正式病例进入分母。
- 未提交、病例错配、无法读取或缺任一正文必需部分的病例记 0 分；合格输出中一般错误在相应维度扣分。
- 编造关键事实、关键时序或数值错误并明显影响判断的，该例总分小计最高计满分的 50%。
- 基于题内明确证据会导致严重伤害的建议或严重遗漏，经第三位医学专家复核后，该例记 0 分。
- 先合并双评分及争议裁决，再应用一次封顶，不对同一错误另加重复罚分。

## 2.6 排名与同分处理

- 按未舍入总分排序，展示两位小数。
- 同分依次比较：临床前四项得分、事实忠实性、严重错误例数较少者。
- 用于同分比较的分项按封顶后总分与原始小计之比同比缩放，零分病例分项也记 0。
- 仍相同则并列，由组委会决定名额。

## 2.7 违规与公共接口故障

故意人工代写正式结果、获取答案、篡改日志或使用未获准外部模型，按赛事违规程序处理。

公共 API 故障由赛方统一处理，不让个别队伍自行选择重跑结果。正式发布前由技术委员会负责解释。

---

# Appendix 2. Detailed Scoring Criteria (English Version)

## A2.1 Scoring dimensions

| Dimension | Evaluation content |
|---|---|
| Factual accuracy and fidelity | Important facts, values, chronology, and negation are correct, with no fabricated additions. |
| Preliminary diagnostic discussion and clinical analysis | Judgments are evidence-based, differential diagnoses are case-specific, and insufficient information is handled appropriately. |
| Relevance of the diagnostic and treatment plan | Investigations, management, and observation correspond to current problems; planned actions are distinguished from actions already performed. |
| Structural compliance and individualization | All three sections are complete and focused, reflect case-specific features, and avoid generic boilerplate. |
| Source attribution and review prompts | Key content can be checked against its sources; missing or conflicting information is clearly identified. |
| Algorithm implementation and reproducibility | The solution runs as documented; code, prompts, and submitted results correspond; configuration, dependencies, and logs are complete. |
| Improvement methods and validation | Improvements are clearly defined, with comparisons on public cases demonstrating benefits and limitations. |
| Other | No additional points are awarded for interface aesthetics or unrelated product features. |

## A2.2 Per-case clinical scoring points

### Dimension 1: Factual accuracy and fidelity

| Scoring point | Required practice |
|---|---|
| Correct key facts | Preserve symptoms, signs, laboratory values, and source wording accurately; retain units, such as Hb 82 g/L. |
| Correct chronology | Preserve original temporal expressions such as “fatigue for 2 weeks” and “on admission,” without reversing the sequence. |
| Preserve negation and missing information | Retain negations such as “no melena” and “blood pressure not provided”; describe missing data as “unknown” or “not provided.” |
| No fabricated additions | Do not include investigations or history absent from the sources; never rewrite “not provided” as “normal” or “denies.” |

### Dimension 2: Preliminary diagnostic discussion and clinical analysis

| Scoring point | Required practice |
|---|---|
| Evidence-based preliminary judgments | Link each judgment to specific information, for example, “anemia under investigation (Hb 82 g/L; see S03).” |
| Case-specific differential diagnosis | Provide 2–3 differential directions based on the case and explain the rationale; do not copy a generic textbook list. |
| Appropriate handling of insufficient information | State that further investigation is needed when evidence is insufficient. “Etiology under investigation” is acceptable; do not force a conclusion. |

### Dimension 3: Relevance of the diagnostic and treatment plan

| Scoring point | Required practice |
|---|---|
| Plan addresses current problems | Investigations, management, and observation must correspond to the case; avoid irrelevant, exhaustive checklists. |
| Plans distinguished from completed actions | Use wording such as “plan,” “recommend,” or “repeat”; never describe planned actions as already administered or completed. |
| Observation arrangements included | Specify which symptoms to monitor and which indicators to repeat. |

### Dimension 4: Structural compliance and individualization

| Scoring point | Required practice |
|---|---|
| Three complete sections | Case features, preliminary diagnostic discussion, and diagnostic and treatment plan must each be non-empty. |
| Clear priorities | Organize case features around important positive findings, relevant known negative findings, and the clinical course; avoid a chronological laundry list. |
| Individualized expression | The output must reflect case-specific features and not be directly reusable for an unrelated case. |

### Dimension 5: Source attribution and review prompts

| Scoring point | Required practice |
|---|---|
| Traceable evidence | Provide 3–5 evidence entries, or fewer if fewer key facts are available. Each entry must contain `source_ids` that actually exist in the current case. |
| Facts distinguished from inferences | Label content directly present in the sources as `fact`; label algorithm-derived reasoning or inference boundaries as `inference`. |
| Clear review items | Place missing information, conflicts, and matters requiring clinician confirmation in `review_items`; use `[]` if there are genuinely none. |

## A2.3 Overall algorithm and improvement scoring

| Category | Scoring point | Required practice |
|---|---|---|
| Algorithm reproduction | Rerunnable | After `pip install -r requires.txt` in a clean environment, `python main.py` automatically processes every case and exits normally. |
| Algorithm reproduction | Materials correspond | Code, prompts, parameters, and submitted results are consistent; use a fixed random seed where supported. |
| Algorithm reproduction | Complete configuration and logs | `main.py`, `requires.txt`, `.env.example`, and README are present; `run_log` fields are complete and contain no credentials. |
| Improvement validation | Clearly defined improvements | Explain each improvement and the problem it solves, such as numerical source verification preventing transcription errors. |
| Improvement validation | Controlled comparison | Compare the baseline and improved versions on the same public practice cases. |
| Improvement validation | Limitation analysis | Explain costs, such as runtime or call volume, and unresolved problems. |

## A2.4 Review and verification

- Two medical judges independently score each case using case-specific reference points prepared before the competition.
- Reasonable alternative wording is allowed. Textual similarity must not replace medical judgment.
- If the judges' subtotal scores differ by more than 10 points, or if they assign inconsistent major-error severity levels, a third medical expert reviews the disputed items.
- Technical judges assess the algorithm component using the offline reproduction results.
- Sampled reproduction cases and conditions must be identical across teams. When differences arise, model randomness and model version must be investigated before any allegation of misconduct is considered.

## A2.5 Missing outputs, errors, and penalties

- Every official case is included in the scoring denominator.
- A case receives zero if it was not submitted, was mismatched, cannot be read, or lacks any required narrative section.
- For otherwise valid outputs, ordinary errors are deducted within the relevant dimension.
- If key facts are fabricated, or key chronology or numerical errors materially affect clinical judgment, the case's total subtotal is capped at **50% of the maximum score**.
- If a recommendation based on explicit case evidence could cause serious harm, or a serious omission occurs, the case receives **zero** after review by a third medical expert.
- The two judges' scores and dispute decisions are combined first, and the cap is then applied once. The same error must not receive duplicate penalties.

## A2.6 Ranking and ties

- Rank teams using unrounded total scores and display totals to two decimal places.
- Break ties in the following order:
  1. Combined score for the first four clinical dimensions.
  2. Factual fidelity score.
  3. Fewer cases with serious errors.
- Component scores used for tie-breaking are scaled by the ratio of the capped total to the original subtotal. Component scores for zero-score cases remain zero.
- If scores remain identical, the teams are tied, and the organizing committee determines the available advancement places.

## A2.7 Misconduct and service failures

The following are handled under the competition's violation procedures:

- Deliberately writing official results manually.
- Obtaining answers improperly.
- Tampering with logs.
- Using unauthorized external models.

Failures of the shared model API are handled centrally by the organizer. Individual teams may not choose their own rerun results. The technical committee is responsible for interpretation before the official release.

---

# 附件 3. 技术规范（中文版）

## 3.1 源码包与运行文件

提交文件命名为 `队伍编号_algorithm.zip`。ZIP 解压后的根目录须直接包含以下文件，不再套一层目录：

```text
main.py             # 统一启动入口
requires.txt        # Python 依赖清单
.env.example        # 配置模板，仅包含 MODEL_NAME 和 ENDPOINT
README.md           # 方法、运行步骤、模型参数、改进点及局限
src/                # 其他代码，可选
prompts/            # Prompt 文件，可选
```

主办方在正式运行时，将以下文件放入源码根目录：

```text
.env                # 主办方提供的模型配置
input.json          # 正式测试输入
```

程序运行完成后，须在源码根目录生成 `output.json`。根目录指 `main.py` 所在目录；所有相对路径均以该目录为基准。

提交包须包含运行所需的全部代码、Prompt 和静态资源。不得依赖参赛者本机绝对路径、未提交的文件或人工操作。模型由主办方提供接口，提交包无需包含模型权重。

## 3.2 运行环境与统一启动入口

本技术规范采用 Python 3.11 作为统一运行环境，正式版本随赛前技术附件发布。主办方按以下命令安装依赖并启动程序：

```bash
cd <源码解压目录>
python -m pip install -r requires.txt
python main.py
```

`main.py` 为唯一启动入口，无需额外命令行参数。程序启动后自动读取 `.env` 和 `input.json`，完成全部病例处理、写入 `output.json` 后退出，不依赖交互输入、IDE 或额外启动的本地服务。

依赖文件统一命名为 `requires.txt`，采用可被 `pip install -r requires.txt` 解析的标准格式。只列实际使用的依赖，并建议固定已测试版本。以下仅为依赖名称示例，参赛者可按实现调整：

```text
python-dotenv
requests
```

## 3.3 模型配置与无密钥调用

`.env` 只包含以下两项模型配置：

```dotenv
MODEL_NAME=replace_with_model_name
ENDPOINT=http://127.0.0.1:8000/v1/chat/completions
```

上述值仅为占位示例，实际值由主办方提供。

| 配置项 | 说明 |
|---|---|
| `MODEL_NAME` | 模型服务实际使用的模型标识，作为请求体中的 `model` 值。 |
| `ENDPOINT` | 完整推理请求地址，包含实际请求路径；程序直接使用，不再拼接 `/v1` 或 `/chat/completions`。 |

模型接口无需 API Key、Token 或其他密钥。程序不得要求配置密钥，不得因缺少密钥而拒绝启动，模型请求不发送 `Authorization` 鉴权头。

程序须从 `main.py` 所在目录的 `.env` 文件读取上述两项配置，不得将实际模型标识或地址硬编码在源码中。输入输出文件名固定为 `input.json` 和 `output.json`，不通过 `.env` 配置。

本技术规范按 Chat Completions 兼容协议说明调用方式，最终请求和响应协议由主办方随技术附件确认。请求方式为 `POST`，请求体示例：

```json
{
  "model": "replace_with_model_name",
  "messages": [
    {
      "role": "system",
      "content": "生成教学比赛中的住院首次病程记录草稿。仅依据截止点及此前可获得的资料，输出病例特点、拟诊讨论、诊疗计划、依据说明和待核事项。区分事实与推断，不虚构事实，不把计划写成已实施治疗，仅返回约定的JSON对象。"
    },
    {
      "role": "user",
      "content": "此处填入当前病例的原始资料。"
    }
  ],
  "stream": false
}
```

以下为配置读取和模型调用示例，不是完整参赛程序；参赛者仍须实现输入读取、病历生成、输出解析、异常处理和结果写入。

```python
from pathlib import Path

import requests
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "input.json"
OUTPUT_FILE = BASE_DIR / "output.json"

config = dotenv_values(BASE_DIR / ".env")
model_name = (config.get("MODEL_NAME") or "").strip()
endpoint = (config.get("ENDPOINT") or "").strip()

if not model_name or not endpoint:
    raise ValueError(".env 必须提供非空的 MODEL_NAME 和 ENDPOINT")

# 不从系统代理或凭据配置中引入额外设置。
session = requests.Session()
session.trust_env = False


def call_model(messages):
    response = session.post(
        endpoint,
        headers={"Content-Type": "application/json"},
        json={
            "model": model_name,
            "messages": messages,
            "stream": False,
        },
        timeout=120,  # 示例值，正式限制由主办方发布
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]
```

生成参数、调用次数、并发、超时和重试限制由主办方统一发布。参赛代码应遵守这些限制，不自行调用其他模型或未经允许的外部服务。

## 3.4 输入文件规范

输入文件固定为 `input.json`，采用 UTF-8 编码，内容为标准 JSON 数组。数组中的每个对象代表一例待生成首次病程记录的入院资料，不采用 JSONL 格式。

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 非空的病例唯一标识，文件内不得重复。 |
| `record_cutoff` | string | 资料截止点，可以是时间或赛方约定的标识，例如 `T0`。 |
| `sources` | array | 资料片段数组，每个对象包含 `source_id` 和 `content`。 |
| `sources[].source_id` | string | 该病例内唯一、非空的资料片段标识。 |
| `sources[].content` | string | 资料片段正文，保留原始事实、数值、时序及不确定性。 |

资料可包括主诉、现病史、既往史、体格检查、辅助检查和入院初步判断。未提供的资料保持缺失，仅使用截至资料截止点（含该时点）已可获得的信息。

赛方在发题前筛选资料，排除目标首次病程、后续确诊、出院记录及截止点之后的检查结果。

### 输入示例

以下沿用赛题中的人工编写教学样例，不来自真实患者，也不是正式比赛答案；具体医学要点由赛方专家审定。`sources` 和 `content` 是本执行手册约定的资料承载字段。

```json
[
  {
    "case_id": "DEMO001",
    "record_cutoff": "T0",
    "sources": [
      {
        "source_id": "S01",
        "content": "成人，乏力2周，活动后心悸；现有记录未见明确黑便、肉眼血尿或其他出血表现"
      },
      {
        "source_id": "S02",
        "content": "结膜苍白、双下肢轻度水肿；未提供血压、尿量及其他体征"
      },
      {
        "source_id": "S03",
        "content": "血红蛋白82 g/L，实验室标低；肌酐185 μmol/L，实验室标高；未提供既往肌酐、红细胞指数、网织红细胞或尿检"
      },
      {
        "source_id": "S04",
        "content": "既往病史、药物史、肾功能基线和贫血既往检查未提供；入院初步判断为贫血及肾功能异常，原因待查"
      }
    ]
  }
]
```

示例数组展示一例病例；正式文件可包含多例，每例按相同结构组成一个对象。公开样例和正式测试数据遵循同一字段协议，正式数据的内容及数量可不同。输入为空数组时，输出也应为空数组。

## 3.5 输出文件规范

输出文件固定为 `output.json`，采用 UTF-8 编码，内容为标准 JSON 数组。

- 输出条数和顺序与输入一致，并原样保留每条记录的 `case_id`。
- 每条记录包含 `case_id`、`status`、`medical_record`、`error`，不得遗漏失败记录。
- 成功时 `status` 为 `"success"`，`medical_record` 为病历对象，`error` 为 `null`。
- 失败时 `status` 为 `"failed"`，`medical_record` 为 `null`，`error` 为包含 `code` 和 `message` 字符串的对象。
- 成功结果的三段正文均为非空字符串；资料不足时在相应正文和待核事项中说明，不补造事实。
- `evidence` 为依据对象数组，`review_items` 为待核事项字符串数组；没有待核事项时使用 `[]`，不省略字段。
- 最终文件须可直接解析为 JSON，不包含 Markdown 代码围栏、说明文字或日志。

`medical_record` 固定包含以下五个医学字段：

| 字段 | 类型 | 内容要求 |
|---|---|---|
| `case_features` | string | 病例特点：凝练重要阳性、有鉴别价值的已知阴性及病程信息。 |
| `diagnostic_discussion` | string | 拟诊讨论：有依据的初步判断、鉴别分析及需要进一步明确的问题。 |
| `plan` | string | 诊疗计划：对应当前问题的进一步检查、处理及观察安排。 |
| `evidence` | array | 依据说明：列出 3—5 条关键事实或判断及对应资料标识；关键事实不足 3 条时按实际列出。 |
| `review_items` | array | 待核事项：列出资料缺失、冲突及需医生确认的问题。 |

每条 `evidence` 对象包含以下字段：

| 字段 | 类型 | 内容要求 |
|---|---|---|
| `statement` | string | 可核对的事实或判断，说明简短清楚。 |
| `source_ids` | array | 该条依据对应的一个或多个 `source_id`，须属于当前病例。 |
| `kind` | string | `fact` 表示资料中的事实，`inference` 表示基于资料的推断或推断边界。 |

三段正文建议合计 800—1600 字，以清楚完整为准，不按长短加分。不要求输出模型内部思维链，只需要可核对的结论与简短依据。以下教学样例用于展示结构。

### 与上述输入对应的输出示例

```json
[
  {
    "case_id": "DEMO001",
    "status": "success",
    "medical_record": {
      "case_features": "成人，近2周乏力、活动后心悸，现有记录显示结膜苍白和双下肢轻度水肿。血红蛋白82 g/L、肌酐185 μmol/L，实验室分别标示降低和升高。现有记录未见明确出血表现；既往血红蛋白、肾功能基线、血压和尿量不详。",
      "diagnostic_discussion": "现有资料支持贫血及肾功能异常，需要分别明确原因及两者关系。贫血需结合红细胞指数、网织红细胞和针对性检查进一步分析，现有记录不能排除隐匿失血、营养相关因素或其他原因。单次肌酐升高不足以确定急性或慢性过程，也不足以将贫血直接归因为肾性贫血。水肿需结合血压、尿量、尿检及相关检查综合判断。目前病因待查。",
      "plan": "由临床医生补充既往检查、症状变化、用药及出血相关病史，核实血压、尿量和容量状态；结合病情复核血常规及肾功能，按鉴别需要安排进一步检查。观察症状和指标变化，依据补充资料调整分析与处理，治疗需结合完整临床评估确定。",
      "evidence": [
        {
          "statement": "近2周乏力、活动后心悸，现有记录未见明确出血表现。",
          "source_ids": ["S01"],
          "kind": "fact"
        },
        {
          "statement": "结膜苍白、双下肢轻度水肿，血压和尿量未提供。",
          "source_ids": ["S02"],
          "kind": "fact"
        },
        {
          "statement": "血红蛋白82 g/L、肌酐185 μmol/L，实验室分别标低和标高。",
          "source_ids": ["S03"],
          "kind": "fact"
        },
        {
          "statement": "仅有单次肌酐及缺失的肾功能基线资料，肾功能异常的急慢性过程尚不能确定。",
          "source_ids": ["S03", "S04"],
          "kind": "inference"
        }
      ],
      "review_items": [
        "既往肾功能及贫血病程",
        "血压、尿量及容量状态",
        "既往病史、用药史及出血相关病史",
        "红细胞指数、网织红细胞及尿检等缺失资料"
      ]
    },
    "error": null
  }
]
```

### 单条处理失败示例

单条处理失败时，在结果数组中的对应位置保留以下结构：

```json
{
  "case_id": "DEMO001",
  "status": "failed",
  "medical_record": null,
  "error": {
    "code": "MODEL_TIMEOUT",
    "message": "模型请求超时，已达到允许的重试次数。"
  }
}
```

### 医学内容要求

- 忠实于给定资料，正确保留重要事实、数值、时序及否定关系，不虚构正常结果或已完成治疗。
- 初步判断、鉴别分析和诊疗计划须有资料依据，并说明信息不足及不确定性。
- 不将“未提供”改写为“正常”或“否认”，不将入院初步判断写成已确诊病因。
- 不把计划写成已实施的检查或治疗，不提前引入后续诊断或住院结局。
- 病例特点和诊疗计划应体现该病例的问题，避免泛化套话；资料缺失及冲突须在待核事项中提示。

## 3.6 执行步骤与异常处理

程序按以下流程执行：

1. 读取 `.env`，校验 `MODEL_NAME` 和 `ENDPOINT`。
2. 读取 `input.json`，校验 JSON 格式和病例标识。
3. 在允许的调用次数及并发范围内处理各条病例。
4. 解析并校验模型结果，整理为约定的病历结构。
5. 写入完整的 `output.json`。
6. 返回退出码并结束运行。

| 退出码 | 含义 |
|---|---|
| `0` | 全部输入均已处理，并生成符合协议的输出文件；允许存在单条失败记录。 |
| `1` | 发生任务级运行错误，未能完成输出。 |
| `2` | 必要配置缺失，或输入文件不符合基本协议。 |

输入无法解析、顶层不是数组、病例标识缺失或重复，按任务级输入错误处理。单条病例的截止点或资料片段无效、模型请求失败或结果无法解析时，应记录该条失败并继续处理后续病例。

结果校验须检查三段正文、依据和待核事项的类型及完整性，并确认 `evidence[].source_ids` 均来自当前病例。模型接口响应与最终结果文件属于不同结构，不能直接把完整 HTTP 响应写入 `output.json`。

程序应先写入同一目录下的临时文件，全部处理完成后再替换为 `output.json`，避免将部分结果误认为完整结果。正常完成空输入时也须写入 `[]`。日志可输出到终端，正式评测以本次成功完成运行后生成的 `output.json` 为准。

## 3.7 赛前技术约束与评测要求

主办方将在赛前统一发布以下详细约束：

| 类别 | 需明确的内容 |
|---|---|
| 运行环境 | 操作系统、Python 版本、CPU、内存及网络访问范围。 |
| 模型服务 | 实际 `MODEL_NAME`、完整 `ENDPOINT`、请求及响应协议；接口无需密钥。 |
| 调用限制 | 生成参数、每条病例调用预算、并发上限。 |
| 时间限制 | 依赖安装时限、单次请求超时、任务总运行时限。 |
| 重试规则 | 可重试的错误类型、最大次数，以及重试是否计入预算。 |
| 数据协议 | 截止点表示方式、资料片段格式、首次病程输出字段及缺失值规则。 |
| 评测规则 | 格式检查、内容质量、失败记录及超时任务的计分方式。 |

参赛者可设计 Prompt、事实提取、时间整理、分段生成和生成后校验等处理流程。使用检索资料时，须限于赛方提供或赛前登记的允许资料，固定版本并附来源清单。

正式评测仅允许使用指定模型和主办方允许的服务，不临时联网搜索病例答案，不使用预先缓存的测试答案，也不得绕过调用限制。

正式评测使用同一提交版本批量处理全部病例。可对全部病例一致执行字段解析、格式校验和规则检查，不得逐例人工改写医学正文、调整提示词或挑选某次最好结果。服务错误按赛方统一重试规则处理。

提交前应确认：源码包能够在干净环境中安装依赖，通过 `python main.py` 自动运行，从 `.env` 读取模型名称和完整请求地址，在无需密钥的情况下调用模型，并生成可解析、条数一致、病例标识正确的 `output.json`。

---

# Appendix 3. Technical Specifications (English Version)

## A3.1 Source package and runtime files

The submission file must be named `team_id_algorithm.zip`. After extraction, the following files must be located directly in the ZIP root directory, without an additional enclosing folder:

```text
main.py             # 统一启动入口
requires.txt        # Python 依赖清单
.env.example        # 配置模板，仅包含 MODEL_NAME 和 ENDPOINT
README.md           # 方法、运行步骤、模型参数、改进点及局限
src/                # 其他代码，可选
prompts/            # Prompt 文件，可选
```

For the official run, the organizer places the following files in the source-code root directory:

```text
.env                # 主办方提供的模型配置
input.json          # 正式测试输入
```

After execution, the program must generate `output.json` in the source-code root directory. The root directory is the directory containing `main.py`, and all relative paths must be resolved from that directory.

The submission package must include all code, prompts, and static resources required for execution. It must not depend on:

- Absolute paths on a participant's own computer.
- Files not included in the submission.
- Manual intervention.

The organizer supplies the model interface; model weights do not need to be included.

## A3.2 Runtime and unified entry point

The standardized runtime is Python 3.11. Final runtime details will be released with the pre-competition technical materials. The organizer installs dependencies and starts the program using:

```bash
cd <源码解压目录>
python -m pip install -r requires.txt
python main.py
```

`main.py` is the only entry point and requires no additional command-line arguments. After startup, the program must automatically:

1. Read `.env` and `input.json`.
2. Process every case.
3. Write `output.json`.
4. Exit.

Execution must not depend on interactive input, an IDE, or a separately started local service.

The dependency file must be named `requires.txt` and use a standard format accepted by:

```bash
python -m pip install -r requires.txt
```

List only dependencies actually used, and pin tested versions where practical. The following names are examples only and may be adjusted according to the implementation:

```text
python-dotenv
requests
```

## A3.3 Model configuration and keyless invocation

The `.env` file contains only the following two model settings:

```dotenv
MODEL_NAME=replace_with_model_name
ENDPOINT=http://127.0.0.1:8000/v1/chat/completions
```

These values are placeholders. The organizer supplies the actual values.

| Setting | Description |
|---|---|
| `MODEL_NAME` | The model identifier used by the model service and passed as the `model` value in the request body. |
| `ENDPOINT` | The complete inference request URL, including the actual request path. The program uses it directly without appending `/v1` or `/chat/completions`. |

The model interface requires no API key, token, or other credential. Therefore:

- The program must not request credential configuration.
- The program must not refuse to start because credentials are absent.
- Model requests must not send an `Authorization` authentication header.
- The program must read both settings from the `.env` file in the directory containing `main.py`.
- Actual model identifiers and addresses must not be hard-coded in the source code.
- Input and output file names are fixed as `input.json` and `output.json`; they are not configured through `.env`.

The calling convention below follows a Chat Completions-compatible protocol. The organizer will confirm the final request and response protocol with the technical materials.

**Method:** `POST`

**Example request body:**

```json
{
  "model": "replace_with_model_name",
  "messages": [
    {
      "role": "system",
      "content": "生成教学比赛中的住院首次病程记录草稿。仅依据截止点及此前可获得的资料，输出病例特点、拟诊讨论、诊疗计划、依据说明和待核事项。区分事实与推断，不虚构事实，不把计划写成已实施治疗，仅返回约定的JSON对象。"
    },
    {
      "role": "user",
      "content": "此处填入当前病例的原始资料。"
    }
  ],
  "stream": false
}
```

The following example demonstrates configuration loading and model invocation only. It is not a complete competition program. Participants must still implement input reading, record generation, output parsing, exception handling, and result writing.

```python
from pathlib import Path

import requests
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "input.json"
OUTPUT_FILE = BASE_DIR / "output.json"

config = dotenv_values(BASE_DIR / ".env")
model_name = (config.get("MODEL_NAME") or "").strip()
endpoint = (config.get("ENDPOINT") or "").strip()

if not model_name or not endpoint:
    raise ValueError(".env 必须提供非空的 MODEL_NAME 和 ENDPOINT")

# 不从系统代理或凭据配置中引入额外设置。
session = requests.Session()
session.trust_env = False


def call_model(messages):
    response = session.post(
        endpoint,
        headers={"Content-Type": "application/json"},
        json={
            "model": model_name,
            "messages": messages,
            "stream": False,
        },
        timeout=120,  # 示例值，正式限制由主办方发布
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]
```

The organizer will publish unified limits for generation parameters, call counts, concurrency, timeouts, and retries. Submitted code must comply with these limits and must not call other models or unauthorized external services.

## A3.4 Input file specification

The input file is fixed as `input.json`, encoded in UTF-8, and contains a standard JSON array. JSONL is not used. Each array object represents one case requiring an initial hospital course note.

| Field | Type | Description |
|---|---|---|
| `case_id` | string | Non-empty unique case identifier; duplicates are prohibited within the file. |
| `record_cutoff` | string | Record cutoff, represented as a timestamp or an organizer-defined marker such as `T0`. |
| `sources` | array | Source-segment array; each object contains `source_id` and `content`. |
| `sources[].source_id` | string | Non-empty source-segment identifier unique within the case. |
| `sources[].content` | string | Source-segment text preserving original facts, values, chronology, and uncertainty. |

Sources may include the chief complaint, history of present illness, past medical history, physical examination, ancillary investigations, and preliminary admission assessment.

Missing information must remain missing. Use only information available at or before the record cutoff, inclusive. Before releasing the task, the organizer screens the materials to exclude the target initial hospital course note, later confirmed diagnoses, discharge records, and investigation results after the cutoff.

### Example input

This synthetic teaching example does not come from a real patient and is not an official competition answer. The fields `sources` and `content` carry the source materials under this protocol.

```json
[
  {
    "case_id": "DEMO001",
    "record_cutoff": "T0",
    "sources": [
      {
        "source_id": "S01",
        "content": "成人，乏力2周，活动后心悸；现有记录未见明确黑便、肉眼血尿或其他出血表现"
      },
      {
        "source_id": "S02",
        "content": "结膜苍白、双下肢轻度水肿；未提供血压、尿量及其他体征"
      },
      {
        "source_id": "S03",
        "content": "血红蛋白82 g/L，实验室标低；肌酐185 μmol/L，实验室标高；未提供既往肌酐、红细胞指数、网织红细胞或尿检"
      },
      {
        "source_id": "S04",
        "content": "既往病史、药物史、肾功能基线和贫血既往检查未提供；入院初步判断为贫血及肾功能异常，原因待查"
      }
    ]
  }
]
```

The example array contains one case. The official file may contain multiple cases using the same structure. Public examples and official test data follow the same field protocol, although their content and case counts may differ. If the input is an empty array, the output must also be an empty array.

## A3.5 Output file specification

The output file is fixed as `output.json`, encoded in UTF-8, and contains a standard JSON array.

- Output count and order must match the input, and every `case_id` must be preserved exactly.
- Every record must contain `case_id`, `status`, `medical_record`, and `error`, including failed cases.
- On success, `status` is `"success"`, `medical_record` is a medical-record object, and `error` is `null`.
- On failure, `status` is `"failed"`, `medical_record` is `null`, and `error` is an object containing string fields `code` and `message`.
- All three required narrative sections of a successful result must be non-empty strings. If information is insufficient, explain this in the relevant narrative and review items without inventing facts.
- `evidence` is an array of evidence objects, and `review_items` is an array of strings. If no review items exist, use `[]`; do not omit the field.
- The final file must be directly parseable as JSON and must not contain Markdown code fences, explanatory text, or logs.

### Required `medical_record` fields

| Field | Type | Content requirement |
|---|---|---|
| `case_features` | string | Case features: concise important positive findings, relevant known negative findings, and clinical-course information. |
| `diagnostic_discussion` | string | Preliminary diagnostic discussion: evidence-based preliminary judgments, differential analysis, and matters requiring clarification. |
| `plan` | string | Diagnostic and treatment plan: further investigations, management, and observation corresponding to current problems. |
| `evidence` | array | Evidence notes: 3–5 key facts or judgments with corresponding source identifiers; list fewer if fewer key facts are available. |
| `review_items` | array | Review items: missing information, conflicts, and issues requiring clinician confirmation. |

### Required fields for each `evidence` object

| Field | Type | Content requirement |
|---|---|---|
| `statement` | string | A concise, verifiable fact or judgment. |
| `source_ids` | array | One or more corresponding `source_id` values belonging to the current case. |
| `kind` | string | `fact` for information directly present in the sources; `inference` for source-based reasoning or an inference boundary. |

A combined length of approximately 800–1,600 characters is recommended for the three narrative sections, with clarity and completeness taking precedence over length. No additional points are awarded for length. Do not request the model's internal chain of thought; only verifiable conclusions and concise supporting evidence are required.

### Example successful output

```json
[
  {
    "case_id": "DEMO001",
    "status": "success",
    "medical_record": {
      "case_features": "成人，近2周乏力、活动后心悸，现有记录显示结膜苍白和双下肢轻度水肿。血红蛋白82 g/L、肌酐185 μmol/L，实验室分别标示降低和升高。现有记录未见明确出血表现；既往血红蛋白、肾功能基线、血压和尿量不详。",
      "diagnostic_discussion": "现有资料支持贫血及肾功能异常，需要分别明确原因及两者关系。贫血需结合红细胞指数、网织红细胞和针对性检查进一步分析，现有记录不能排除隐匿失血、营养相关因素或其他原因。单次肌酐升高不足以确定急性或慢性过程，也不足以将贫血直接归因为肾性贫血。水肿需结合血压、尿量、尿检及相关检查综合判断。目前病因待查。",
      "plan": "由临床医生补充既往检查、症状变化、用药及出血相关病史，核实血压、尿量和容量状态；结合病情复核血常规及肾功能，按鉴别需要安排进一步检查。观察症状和指标变化，依据补充资料调整分析与处理，治疗需结合完整临床评估确定。",
      "evidence": [
        {
          "statement": "近2周乏力、活动后心悸，现有记录未见明确出血表现。",
          "source_ids": ["S01"],
          "kind": "fact"
        },
        {
          "statement": "结膜苍白、双下肢轻度水肿，血压和尿量未提供。",
          "source_ids": ["S02"],
          "kind": "fact"
        },
        {
          "statement": "血红蛋白82 g/L、肌酐185 μmol/L，实验室分别标低和标高。",
          "source_ids": ["S03"],
          "kind": "fact"
        },
        {
          "statement": "仅有单次肌酐及缺失的肾功能基线资料，肾功能异常的急慢性过程尚不能确定。",
          "source_ids": ["S03", "S04"],
          "kind": "inference"
        }
      ],
      "review_items": [
        "既往肾功能及贫血病程",
        "血压、尿量及容量状态",
        "既往病史、用药史及出血相关病史",
        "红细胞指数、网织红细胞及尿检等缺失资料"
      ]
    },
    "error": null
  }
]
```

### Example failed-case output

If a single case fails, retain the following structure at its corresponding position in the result array:

```json
{
  "case_id": "DEMO001",
  "status": "failed",
  "medical_record": null,
  "error": {
    "code": "MODEL_TIMEOUT",
    "message": "模型请求超时，已达到允许的重试次数。"
  }
}
```

## A3.6 Medical-content requirements

- Remain faithful to the supplied information and correctly preserve important facts, values, chronology, and negation.
- Do not invent normal findings or completed treatments.
- Support preliminary judgments, differential analysis, and the diagnostic and treatment plan with source evidence.
- Explain insufficient information and uncertainty.
- Do not rewrite “not provided” as “normal” or “denies.”
- Do not rewrite a preliminary admission assessment as a confirmed etiology.
- Do not describe planned investigations or treatment as already performed.
- Do not introduce later diagnoses or hospital outcomes prematurely.
- Ensure case features and the plan reflect the specific case rather than generic boilerplate.
- Identify missing and conflicting information in `review_items`.

## A3.7 Execution steps and exception handling

The program follows this workflow:

1. Read `.env` and validate `MODEL_NAME` and `ENDPOINT`.
2. Read `input.json` and validate the JSON format and case identifiers.
3. Process each case within the permitted call-count and concurrency limits.
4. Parse and validate model results and assemble the required medical-record structure.
5. Write the complete `output.json`.
6. Return an exit code and terminate.

| Exit code | Meaning |
|---|---|
| `0` | All inputs were processed and a protocol-compliant output file was generated; individual failed-case records are permitted. |
| `1` | A task-level runtime error prevented completion of the output. |
| `2` | Required configuration is missing, or the input file violates the basic protocol. |

Unparseable input, a non-array top level, or missing or duplicate case identifiers must be treated as task-level input errors.

If an individual case has an invalid cutoff or source segment, a failed model request, or an unparseable result, record that case as failed and continue processing subsequent cases.

Result validation must check:

- The types and completeness of the three narrative sections, evidence, and review items.
- That every `evidence[].source_ids` value belongs to the current case.

The model-interface response and final result file have different structures. Do not write the complete HTTP response directly into `output.json`.

The program should first write a temporary file in the same directory and replace `output.json` only after all processing is complete, preventing partial results from being mistaken for complete results. Normal completion with empty input must still write `[]`. Logs may be printed to the terminal; the formal evaluation uses the `output.json` generated by the successful run.

## A3.8 Pre-evaluation constraints and assessment requirements

The organizer will publish the following detailed constraints before the competition:

| Category | Details to be specified |
|---|---|
| Runtime environment | Operating system, Python version, CPU, memory, and network-access scope. |
| Model service | Actual `MODEL_NAME`, complete `ENDPOINT`, request and response protocols, and keyless interface details. |
| Invocation limits | Generation parameters, per-case call budget, and concurrency ceiling. |
| Time limits | Dependency-installation limit, per-request timeout, and total task runtime. |
| Retry rules | Retryable error types, maximum attempts, and whether retries count toward the budget. |
| Data protocol | Cutoff representation, source-segment format, initial-note output fields, and missing-value rules. |
| Evaluation rules | Format checks, content quality, failed records, and scoring of timed-out tasks. |

Participants may design workflows involving prompts, fact extraction, temporal organization, staged generation, and post-generation validation.

When retrieval materials are used, they must be limited to resources supplied by the organizer or permitted resources registered before the competition. Versions must be fixed, and a source list must be attached.

During the formal evaluation:

- Only designated models and organizer-approved services may be used.
- Searching online for case answers is prohibited.
- Precached test answers are prohibited.
- Circumventing invocation limits is prohibited.
- The same submitted version must process all cases in batch.
- Field parsing, format validation, and rule checks may be applied consistently across all cases.
- Medical narrative, prompts, and parameters must not be manually adjusted case by case.
- Teams must not select the best result from multiple runs.
- Service errors are handled under the organizer's unified retry rules.

Before submission, confirm that the source package can install its dependencies in a clean environment, run automatically through `python main.py`, read the model name and complete request URL from `.env`, call the model without credentials, and generate a parseable `output.json` with the correct record count and case identifiers.

---

# 附件 4. 技术问答（中文版）

## 一、知识库、规则库及算法部署

### 1. 是否允许携带医学知识库、规则库和本地检索模块？

允许。赛事鼓励参赛方采用不同的技术路线，包括但不限于 Prompt Engineering、RAG、规则引擎、多阶段推理、Agent 工作流等。

参赛方可将固定版本的医学知识库、规则库及本地检索模块集成到算法 ZIP 中，前提是相关资源来源合法合规，能够在赛事指定环境中独立运行，不依赖外部在线服务。

### 2. 知识资料如何登记？

请在提交时登记相关资源的名称、来源、版本、用途、文件大小及必要的运行依赖。

具体登记模板由组委会统一提供。未使用额外知识库或规则库的团队，注明“无”即可。

### 3. 算法包大小、Python 依赖和联网访问有何限制？

原则上支持合理的 Python 第三方依赖及本地检索、计算组件。

参赛方需提供完整依赖说明（如 `requirements.txt`），确保方案能够在赛事环境中部署运行。

算法包大小上限和依赖兼容性要求将在正式评测前统一明确。对于较大的知识库或特殊依赖，建议提前与组委会沟通。

正式评测环境不开放公网访问，仅允许调用赛事指定的内部服务。算法运行期间不得在线下载安装额外依赖或资源。

## 二、模型调用参数及评测资源

### 4. 是否支持 seed 参数？

赛事采用自部署 vLLM 模型服务。vLLM 原生支持请求级 seed 参数，可直接在 HTTP JSON 请求体顶层传入，例如：

```json
{
  "seed": 42
}
```

参赛方可使用固定随机种子。若实际接口不支持该字段，允许不传并在提交说明中注明，不因此判定违规。

需要说明的是，固定 seed 有助于提高可复现性，但不代表不同运行条件下模型输出一定完全一致。

### 5. Token、调用次数、超时和重试限制如何设置？

当前开发测试阶段暂未设置明确的 Token 总量限制。

正式评测阶段将根据统一资源配置，对单次模型请求超时、单病例总运行时长、Token 消耗、模型调用次数及重试次数等进行规范。

原则上，参赛算法主动发起的重试计入模型调用预算；经确认属于赛事平台自身故障的调用，将按统一异常处理规则处理。

具体限制将在正式提交截止前统一发布，并为参赛方预留调整时间。

### 6. 是否允许设置 response_format 和 temperature？

自部署 vLLM 的 OpenAI 兼容接口原生支持 temperature，并在支持的版本中提供 response_format 结构化输出能力，例如：

```json
{
  "temperature": 0.1,
  "response_format": {
    "type": "json_object"
  }
}
```

赛事原则上允许参赛方自主设置上述参数，最终以赛事实际部署版本及统一接口规范为准。

对于赛事禁止或接口不支持的参数，将尽量提供明确的错误提示，避免静默忽略造成理解偏差。

### 7. Qwen Thinking 参数如何传递？

对于采用 vLLM 原生 OpenAI 兼容接口的服务，可以通过 HTTP 请求体中的以下字段关闭 Thinking：

```json
{
  "chat_template_kwargs": {
    "enable_thinking": false
  }
}
```

如果不传该字段，则使用服务端实际配置的默认模式。默认模式并不必然是关闭 Thinking，最终以赛事发布的模型配置为准。

赛事原则上允许参赛方根据算法策略选择 Thinking 模式，具体支持情况将通过统一接口示例确认。

## 三、外部 API 与数据安全

### 8. 能否使用商业 Qwen API 或其他第三方服务？

本次赛事禁止使用任何外部第三方 API。

赛事提供统一的自部署 Qwen 模型服务，参赛算法应通过赛事指定接口完成模型推理。

禁止调用外部商业大模型、在线 Embedding、在线知识检索或其他第三方服务。

赛事提供的练习病例及正式评测病例均不得上传至外部第三方平台。

参赛方可以使用本地知识库、规则库、检索算法及其他离线组件，但相关资源需提前登记，并确保在赛事指定环境中独立运行。

此项规定旨在保障数据安全、评测公平性及结果可复现性。

## 四、结果提交与兼容性

### 9. 结果文件名应使用 output.json 还是 results.json？

目前技术规范与提交材料在文件命名上存在不一致，组委会将统一修订，并明确最终的文件命名和数据结构要求。

在兼容性预检阶段，将尽可能兼容已有文档中的两种命名方式，避免因文档差异影响参赛方测试。

正式提交请以更新后的统一技术规范为准。

---

# Appendix 4. Consolidated Technical FAQs (English Version)

## 1. Are medical knowledge bases, rule bases, and local retrieval modules allowed?

Yes. Participants are encouraged to adopt different technical approaches, including but not limited to prompt engineering, retrieval-augmented generation (RAG), rule engines, multi-stage reasoning, and agent workflows.

Participants may integrate fixed-version medical knowledge bases, rule bases, and local retrieval modules into their algorithm ZIP package, provided that all resources are legally and compliantly sourced, can operate independently in the designated evaluation environment, and do not rely on external online services.

## 2. How should knowledge resources be registered?

Upon submission, participants must register the name, source, version, intended use, file size, and necessary runtime dependencies of each resource.

A standardized registration template will be provided by the organizing committee. Teams that do not use any additional knowledge bases or rule bases should indicate “None.”

## 3. What restrictions apply to algorithm package size, Python dependencies, and internet access?

Reasonable Python third-party dependencies and local retrieval or computing components are generally supported.

Participants must provide complete dependency documentation in the mandated `requires.txt` file to ensure that their solution can be deployed and run in the evaluation environment.

The maximum algorithm package size and dependency compatibility requirements will be specified before the formal evaluation. Participants planning to use large knowledge bases or special dependencies should consult the organizing committee in advance.

The formal evaluation environment will not provide public internet access. Only designated internal services may be accessed. Algorithms must not download or install additional dependencies or resources online during execution.

## 4. Is the `seed` parameter supported?

The competition uses a self-hosted vLLM model service. vLLM natively supports the request-level `seed` parameter, which can be passed directly at the top level of the HTTP JSON request body:

```json
{
  "seed": 42
}
```

Participants may use a fixed random seed. If the actual interface does not support this field, it may be omitted, with a note included in the submission documentation. This will not be considered a violation.

A fixed seed improves reproducibility but does not guarantee completely identical model outputs under different runtime conditions.

## 5. How will limits on tokens, model calls, timeouts, and retries be set?

No explicit total token limit has currently been set for the development and testing phase.

For the formal evaluation, standardized resource limits will be established for:

- Individual model-request timeouts.
- Total runtime per case.
- Token consumption.
- Number of model calls.
- Retry attempts.

In principle, retries actively initiated by a participant's algorithm count toward the model-call budget. Calls affected by confirmed platform failures are handled according to standardized exception-handling rules.

Specific limits will be published before the formal submission deadline, with sufficient time provided for participants to adjust their solutions.

## 6. May `response_format` and `temperature` be configured?

The OpenAI-compatible interface provided by self-hosted vLLM natively supports `temperature` and, in supported versions, provides structured output through `response_format`:

```json
{
  "temperature": 0.1,
  "response_format": {
    "type": "json_object"
  }
}
```

In principle, participants may configure these parameters according to their needs, subject to the deployed service version and standardized interface specifications.

Where possible, explicit error messages will be provided for prohibited or unsupported parameters to avoid confusion caused by silently ignored settings.

## 7. How should the Qwen Thinking parameter be passed?

For services using vLLM's native OpenAI-compatible interface, Thinking mode can be disabled by including the following field in the HTTP request body:

```json
{
  "chat_template_kwargs": {
    "enable_thinking": false
  }
}
```

If this field is omitted, the server's configured default mode applies. The default mode does not necessarily disable Thinking; the final behavior depends on the officially published model configuration.

In principle, participants may select the Thinking mode according to their algorithmic strategy. Supported configurations will be confirmed through standardized API examples.

## 8. May commercial Qwen APIs or other third-party services be used?

No external third-party APIs may be used.

The competition provides a unified, self-hosted Qwen model service, and all model inference must be completed through the designated interface.

The following are prohibited:

- External commercial Qwen APIs or other commercial LLMs.
- Online embedding services.
- Online knowledge-retrieval services.
- Other third-party services.

Neither practice cases nor formal evaluation cases may be uploaded to external third-party platforms.

Participants may use local knowledge bases, rule bases, retrieval algorithms, and other offline components. These resources must be registered in advance and must operate independently in the designated evaluation environment.

These requirements protect data security, ensure evaluation fairness, and support reproducible results.

## 9. Should the result file be named `output.json` or `results.json`?

The current technical specifications and submission materials are inconsistent regarding the result-file name. The technical runtime specification uses `output.json`, while the result-package instructions refer to `results.json`.

The organizing committee will revise the documentation and clarify the final file-naming and data-structure requirements. During compatibility pre-checks, both names will be supported where possible so that documentation discrepancies do not affect participant testing.

Formal submissions must follow the updated, unified technical specifications.
