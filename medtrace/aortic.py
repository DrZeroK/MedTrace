"""Antithrombotic safety for acute aortic syndromes (AAS: dissection, intramural haematoma, penetrating ulcer).

Implements docs/AORTIC_ANTITHROMBOTIC_RULE.md (rule spec, decision matrix, evidence R01-R10). A safety check on
GENERATED plan text, not a prescribing system: it keeps unsafe model suggestions out of the executable plan and raises
clinician-visible review items. Engineering policy, not guideline grades. Clinical review status: PENDING.

aortic_findings(case) -> derive_state(); recorded_indications(case); units(sentence) -> medication intent and source;
decide() -> PASS / BLOCK / REVIEW / REVIEW_URGENT; render() -> safe text. Deciding and rewriting are separate.
Offline, deterministic, idempotent (screening its own output changes nothing).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from . import textutil as T

RULE_ID, RULE_VERSION = "AORTIC_ANTITHROMBOTIC_SAFETY", "2026-11-24.1"
DICTIONARY_VERSION = "B01A-local-2026-11-24"
CLINICAL_REVIEW_STATUS = "PENDING"

# ---------------------------------------------------------------------------------------------------- disease state
CONFIRMED_ACTIVE, SUSPECTED_ACTIVE = "CONFIRMED_ACTIVE", "SUSPECTED_ACTIVE"
STABLE_CHRONIC, STABLE_POST_REPAIR, PERIOPERATIVE = "STABLE_CHRONIC", "STABLE_POST_REPAIR", "PERIOPERATIVE"
RULED_OUT, HISTORY_ONLY, UNKNOWN, ABSENT = "RULED_OUT", "HISTORY_ONLY", "UNKNOWN", "ABSENT"
ACTIVE_STATES = (CONFIRMED_ACTIVE, SUSPECTED_ACTIVE)
STABLE_STATES = (STABLE_CHRONIC, STABLE_POST_REPAIR)
QUIET_STATES = (RULED_OUT, HISTORY_ONLY, ABSENT)      # the rule passes everything

# (entity, pattern, context needed): "source" = the record must mention the aorta somewhere (Chinese 壁内/壁间血肿,
# which also occur as 肠壁间血肿 etc.); "sentence" = the same sentence must (abbreviations: IMH, PAU, AAS).
_ENTITY = [
    ("aortic_dissection", re.compile(r"主动脉夹层|主动脉剥离|aortic dissection"), None),
    ("intramural_hematoma", re.compile(r"主动脉壁[内间]血肿|aortic intramural ha?ematoma|intramural ha?ematoma"), None),
    ("intramural_hematoma", re.compile(r"(?<!主动脉)壁[内间]血肿(?:形成)?"), "source"),
    ("intramural_hematoma", re.compile(r"(?<![a-z])imh(?![a-z])"), "sentence"),
    ("penetrating_ulcer", re.compile(r"穿透性(?:主动脉)?(?:粥样硬化性)?溃疡|主动脉穿透性溃疡|penetrating aortic ulcer"), None),
    ("penetrating_ulcer", re.compile(r"(?<![a-z])pau(?![a-z])"), "sentence"),
    ("acute_aortic_syndrome", re.compile(r"急性主动脉综合征|acute aortic syndrome"), None),
    ("acute_aortic_syndrome", re.compile(r"(?<![a-z])aas(?![a-z])"), "sentence"),
]
ENTITY_NAME = {"zh": {"aortic_dissection": "主动脉夹层", "intramural_hematoma": "主动脉壁内血肿",
                      "penetrating_ulcer": "穿透性主动脉溃疡", "acute_aortic_syndrome": "急性主动脉综合征"},
               "en": {"aortic_dissection": "aortic dissection", "intramural_hematoma": "aortic intramural haematoma",
                      "penetrating_ulcer": "penetrating aortic ulcer", "acute_aortic_syndrome": "acute aortic syndrome"}}
_AORTIC_CONTEXT = re.compile(r"主动脉|aort|stanford|debakey")
_NOT_AAS = re.compile(r"主动脉(?:附壁|壁)血栓|(?:肠|子宫肌|肌|胃)壁[内间]血肿|aortic (?:mural )?thromb")
_FAMILY = re.compile(r"家族|父亲|母亲|其父|其母|兄|姐|弟|妹|子女|family|mother|father|sibling")
_EXCLUDED_RESULT = re.compile(r"(?:已|明确|基本|可以|可|予以)\s*(?:排除|除外)|排除了|除外了|ruled out|excluded|no evidence of")
# "需排除" / "rule out" / "cannot exclude" are open questions: suspicion, never negation.
_SUSPECT = re.compile(r"疑似|可疑|可能|待排|需(?:要)?排除|以排除|为排除|待除外|不除外|不能(?:排除|除外)|考虑|怀疑|待查|"
                      r"\bsuspect|possible|probable|rule out|r/o|cannot (?:be )?exclude")
_PAST = re.compile(r"既往|病史|曾(?:患|行|于)|[0-9一二三四五六七八九十]+\s*(?:年|个月|月)前|history of|\bprior\b|previous")
_REPAIR = re.compile(r"修复|置换|术后|腔内隔绝|tevar|evar|bentall|repair|post-?op")
_PERIOP = re.compile(r"术后\s*(?:第?\s*[0-9一二三四五六七八九十]+\s*(?:天|日|周)|早期|当天|止血)|围术期|术前|拟.{0,6}手术|"
                     r"post-?op(?:erative)? day|perioperative|pre-?op")
_LESION_STABLE = re.compile(r"病情稳定|病变稳定|夹层稳定|血肿稳定|无进展|未见进展|随访.{0,6}(?:稳定|无变化)|"
                            r"stable (?:dissection|lesion|disease)|no progression")
_CHRONIC = re.compile(r"慢性|陈旧|chronic")
_CURRENT = re.compile(r"本次|此次|新发|新出现|进展|急性|突发|急诊|入院|收入|current|acute|\bnew\b")
_ACUTE_PHASE = re.compile(r"急性|突发|[0-9一二三四五六七八九十]+\s*(?:小时|h\b)|acute|hyperacute")
_CLAUSE_SPLIT = re.compile(r"[，,；;。！？!?\n]")


@dataclass
class AorticFinding:
    entity: str
    assertion: str        # CONFIRMED | SUSPECTED | RULED_OUT | NEGATED
    temporality: str      # CURRENT | HISTORY
    activity: str         # ACTIVE | STABLE | UNKNOWN
    repair_status: str    # UNREPAIRED | PERIOPERATIVE | POST_REPAIR | UNKNOWN
    phase: str            # ACUTE | CHRONIC | UNKNOWN (time-based phase is auxiliary only)
    subject: str          # PATIENT | FAMILY
    evidence: list        # ["<source_id>: <exact clause>"]


def _finding(entity: str, term: str, clause: str, sentence: str, sid: str) -> AorticFinding:
    i = clause.find(term)
    subject = "FAMILY" if _FAMILY.search(clause) else "PATIENT"
    if _EXCLUDED_RESULT.search(clause[max(0, i - 12):i]) or _EXCLUDED_RESULT.search(clause[i + len(term):i + len(term) + 8]):
        assertion = "RULED_OUT"
    elif not T.term_positive_in(term, clause):
        assertion = "NEGATED"
    elif _SUSPECT.search(clause):
        assertion = "SUSPECTED"
    else:
        assertion = "CONFIRMED"
    past = bool(_PAST.search(clause) or (_REPAIR.search(clause) and not _PERIOP.search(clause)))
    temporality = "HISTORY" if past and not _CURRENT.search(clause) else "CURRENT"
    repair = "PERIOPERATIVE" if _PERIOP.search(sentence) else "POST_REPAIR" if _REPAIR.search(clause) else "UNREPAIRED"
    chronic = bool(_CHRONIC.search(clause))
    stable = (temporality == "HISTORY" or chronic) and _LESION_STABLE.search(sentence)
    activity = "STABLE" if stable else "ACTIVE" if temporality == "CURRENT" and not chronic else "UNKNOWN"
    phase = "CHRONIC" if chronic else "ACUTE" if _ACUTE_PHASE.search(sentence) else "UNKNOWN"
    return AorticFinding(entity, assertion, temporality, activity, repair, phase, subject, [f"{sid}: {clause.strip()}"])


def aortic_findings(case) -> list[AorticFinding]:
    """Every AAS mention in the input records, one per clause, with the exact source clause as evidence."""
    out = []
    for s in case.sources:
        src = T.fw(s.content).lower()
        for sent in T.split_sentences(src):
            for clause in _CLAUSE_SPLIT.split(sent):
                masked = _NOT_AAS.sub(" ", clause)
                seen = set()
                for entity, rx, ctx in _ENTITY:
                    m = rx.search(masked)
                    if not m or entity in seen:
                        continue
                    if (ctx == "source" and not _AORTIC_CONTEXT.search(_NOT_AAS.sub(" ", src))
                            or ctx == "sentence" and not _AORTIC_CONTEXT.search(sent)):
                        continue
                    seen.add(entity)
                    out.append(_finding(entity, m.group(0), clause, sent, getattr(s, "raw_id", s.sid)))
    return out


def derive_state(findings: list[AorticFinding]) -> tuple[str, AorticFinding | None]:
    """A current active lesion outranks history and an old repaired lesion never cancels a new one; a current
    exclusion resolves a current suspicion but an old negative test does not; conflicting current evidence and
    history without documented stability are UNKNOWN."""
    pts = [f for f in findings if f.subject == "PATIENT"]
    cur = [f for f in pts if f.temporality == "CURRENT"]
    confirmed = [f for f in cur if f.assertion == "CONFIRMED" and f.activity == "ACTIVE" and f.repair_status != "PERIOPERATIVE"]
    excluded = [f for f in cur if f.assertion in ("RULED_OUT", "NEGATED")]
    suspected = [f for f in cur if f.assertion == "SUSPECTED"]
    if confirmed and any(e.entity == c.entity and e.assertion == "RULED_OUT" for e in excluded for c in confirmed):
        return UNKNOWN, confirmed[0]
    if confirmed:
        return CONFIRMED_ACTIVE, confirmed[0]
    if suspected and not any(e.assertion == "RULED_OUT" for e in excluded):
        return SUSPECTED_ACTIVE, suspected[0]
    periop = [f for f in pts if f.repair_status == "PERIOPERATIVE" and f.assertion == "CONFIRMED"]
    if periop:
        return PERIOPERATIVE, periop[0]
    if suspected:
        return RULED_OUT, next(e for e in excluded if e.assertion == "RULED_OUT")
    known = [f for f in pts if f.assertion == "CONFIRMED"]          # history, chronic or stable mentions
    stable = [f for f in known if f.activity == "STABLE"]
    if stable:
        return (STABLE_POST_REPAIR if stable[0].repair_status == "POST_REPAIR" else STABLE_CHRONIC), stable[0]
    if known:
        return UNKNOWN, known[0]                        # history without documented stability is not assumed stable
    if pts:
        return RULED_OUT, pts[0]
    if findings:
        return HISTORY_ONLY, None                       # family history only
    return ABSENT, None


def aortic_state(case) -> tuple[str, AorticFinding | None]:
    return derive_state(aortic_findings(case))


# ------------------------------------------------------------------------------------------ independent indications
# (name, regex, drug class it supports, urgent competing risk). "房颤" alone is not a confirmed anticoagulation
# indication, so it never makes a REVIEW_URGENT; an ACS label or a troponin rise is not an indication at all.
_INDICATIONS = [
    ("机械瓣膜", re.compile(r"机械瓣|人工(?:心脏)?瓣膜|瓣膜置换|mechanical (?:heart )?valve"), "anticoagulant", True),
    ("急性肺栓塞", re.compile(r"肺栓塞|肺动脉栓塞|pulmonary embol"), "anticoagulant", True),
    ("急性深静脉血栓", re.compile(r"深静脉血栓|(?<![a-z])dvt(?![a-z])|deep vein thromb"), "anticoagulant", True),
    ("心腔内血栓", re.compile(r"心腔内血栓|左心耳血栓|左室血栓|心室内血栓|intracardiac thromb|lv thromb"), "anticoagulant", True),
    ("近期冠脉支架", re.compile(r"支架植入|植入支架|置入支架|支架置入|冠脉支架|pci术后|(?<![a-z])stent"), "antiplatelet", True),
    ("心房颤动", re.compile(r"房颤|心房颤动|atrial fibrillation"), "anticoagulant", False),
]
_PROPHYLAXIS_WORD = re.compile(r"预防|prophyla")      # "预防DVT" in a record is prophylaxis, not a thrombosis


@dataclass
class Indication:
    name: str
    drug_class: str
    urgent: bool
    evidence: str


def recorded_indications(case) -> list[Indication]:
    """Affirmed patient indications from the input records (not "否认房颤", "肺栓塞待排", family, prophylaxis)."""
    out = []
    for s in case.sources:
        for sent in T.split_sentences(T.fw(s.content).lower()):
            for clause in _CLAUSE_SPLIT.split(sent):
                if _FAMILY.search(clause) or _SUSPECT.search(clause) or _PROPHYLAXIS_WORD.search(clause):
                    continue
                for name, rx, cls, urgent in _INDICATIONS:
                    m = rx.search(clause)
                    if m and T.term_positive_in(m.group(0), clause) and name not in {i.name for i in out}:
                        out.append(Indication(name, cls, urgent, f"{getattr(s, 'raw_id', s.sid)}: {clause.strip()}"))
    return out


_CORONARY_INVOLVEMENT = re.compile(r"累及冠(?:状动)?脉(?:开口)?|冠(?:状动)?脉开口受累|冠脉灌注不良|coronary (?:ostium|ostial|malperfusion)")


# ------------------------------------------------------------------------------------------------- drug dictionary
# Local versioned dictionary after WHO ATC B01A: (canonical, ATC, group, pattern: Chinese, INN, brands, abbreviations).
# Brand names checked against their ingredient: 拜阿司匹灵 aspirin, 波立维/泰嘉 clopidogrel, 倍林达 ticagrelor,
# 拜瑞妥 rivaroxaban, 泰毕全 dabigatran, 克赛 enoxaparin.
DRUGS = [
    ("warfarin", "B01AA03", "vka", r"华法林|warfarin"), ("acenocoumarol", "B01AA07", "vka", r"醋硝香豆素|acenocoumarol"),
    ("lmwh", "B01AB", "heparin", r"低分子(?:量)?肝素|(?<![a-z])lmwh(?![a-z])|low.molecular.weight heparin"),
    ("enoxaparin", "B01AB05", "heparin", r"依诺肝素|克赛|enoxaparin"), ("dalteparin", "B01AB04", "heparin", r"达肝素|dalteparin"),
    ("nadroparin", "B01AB06", "heparin", r"那屈肝素|nadroparin"), ("tinzaparin", "B01AB10", "heparin", r"亭扎肝素|tinzaparin"),
    ("heparin", "B01AB01", "heparin", r"普通肝素|(?<![a-z])ufh(?![a-z])|肝素|(?<![a-z])heparin"),
    ("aspirin", "B01AC06", "cox", r"阿司匹林|拜阿司匹灵|aspirin|(?<![a-z])asa(?![a-z])"),
    ("indobufen", "B01AC10", "cox", r"吲哚布芬|indobufen"),
    ("clopidogrel", "B01AC04", "p2y12", r"氯吡格雷|波立维|泰嘉|clopidogrel"),
    ("ticagrelor", "B01AC24", "p2y12", r"替格瑞洛|倍林达|ticagrelor"), ("prasugrel", "B01AC22", "p2y12", r"普拉格雷|prasugrel"),
    ("ticlopidine", "B01AC05", "p2y12", r"噻氯匹定|ticlopidine"), ("cangrelor", "B01AC25", "p2y12", r"坎格瑞洛|cangrelor"),
    ("tirofiban", "B01AC17", "gp2b3a", r"替罗非班|tirofiban"), ("eptifibatide", "B01AC16", "gp2b3a", r"依替巴肽|eptifibatide"),
    ("abciximab", "B01AC13", "gp2b3a", r"阿昔单抗|abciximab"),
    ("cilostazol", "B01AC23", "other_ap", r"西洛他唑|cilostazol"), ("dipyridamole", "B01AC07", "other_ap", r"双嘧达莫|dipyridamole"),
    ("prourokinase", "B01AD", "fibrinolytic", r"重组人尿激酶原|尿激酶原|prourokinase"),
    ("alteplase", "B01AD02", "fibrinolytic", r"阿替普酶|alteplase|rt-?pa|(?<![a-z])tpa(?![a-z])"),
    ("tenecteplase", "B01AD11", "fibrinolytic", r"替奈普酶|tenecteplase"), ("reteplase", "B01AD07", "fibrinolytic", r"瑞替普酶|reteplase"),
    ("urokinase", "B01AD04", "fibrinolytic", r"尿激酶|urokinase"), ("streptokinase", "B01AD01", "fibrinolytic", r"链激酶|streptokinase"),
    ("dabigatran", "B01AE07", "dti", r"达比加群(?:酯)?|泰毕全|dabigatran"), ("bivalirudin", "B01AE06", "dti", r"比伐芦定|bivalirudin"),
    ("argatroban", "B01AE03", "dti", r"阿加曲班|argatroban"),
    ("rivaroxaban", "B01AF01", "xa", r"利伐沙班|拜瑞妥|rivaroxaban"), ("apixaban", "B01AF02", "xa", r"阿哌沙班|apixaban"),
    ("edoxaban", "B01AF03", "xa", r"艾多沙班|edoxaban"), ("fondaparinux", "B01AX05", "other_ac", r"磺达肝癸钠|fondaparinux"),
    ("dapt", "B01AC", "dapt", r"双联抗血小板|双抗(?!生素|菌|感染|体|原)|(?<![a-z])dapt(?![a-z])"),
    ("antiplatelet", "B01AC", "antiplatelet", r"(?<![a-z])sapt(?![a-z])|抗血小板(?:聚集)?|antiplatelet"),
    ("oral_anticoagulant", "B01A", "anticoagulant", r"(?<![a-z])(?:doac|noac|oac)(?![a-z])|口服抗凝药"),
    ("anticoagulation", "B01A", "anticoagulant", r"抗凝|anticoagul"),
    ("fibrinolysis", "B01AD", "fibrinolytic", r"溶栓|纤溶(?!亢进)|thromboly|fibrinoly"),
    ("antithrombotic", "B01A", "antithrombotic", r"抗栓|antithrombotic"),
]
_DRUGS = [(c, atc, g, re.compile(p)) for c, atc, g, p in DRUGS]
_GROUP_CLASS = {"vka": "anticoagulant", "heparin": "anticoagulant", "dti": "anticoagulant", "xa": "anticoagulant",
                "other_ac": "anticoagulant", "anticoagulant": "anticoagulant", "cox": "antiplatelet", "p2y12": "antiplatelet",
                "gp2b3a": "antiplatelet", "other_ap": "antiplatelet", "antiplatelet": "antiplatelet", "dapt": "antiplatelet",
                "fibrinolytic": "fibrinolysis", "antithrombotic": "antithrombotic"}
_AGENT_GROUPS = {"cox", "p2y12", "gp2b3a", "other_ap"}
# Semantic exceptions, masked before matching: tests and sample tubes, catheter locks, local lysis, risk assessments,
# reversal agents, "双联降压/抗感染", aortic mural thrombus.
_NOT_DRUG = re.compile(r"抗凝血酶(?:iii|ⅲ|3)?(?:测定|活性)?|凝血(?:功能|指标|象|四项)(?:检查|监测)?|"
                       r"枸橼酸(?:钠)?抗凝(?:血)?(?:标本|采血管|管)?|抗凝(?:采血)?管|肝素(?:钠)?(?:盐水)?封管|肝素帽|肝素锁|"
                       r"导管(?:内|局部)?(?:接触)?溶栓|局部溶栓|(?:抗凝|抗栓|出血|血栓)(?:作用)?(?:风险)?(?:评估|分层|评分)|"
                       r"抗凝(?:作用)?逆转|逆转抗凝|鱼精蛋白|维生素\s*k\d?|依达赛珠单抗|andexanet|idarucizumab|protamine|"
                       r"双联(?!抗血小板)|主动脉(?:附壁|壁)血栓")


def drug_mentions(text: str) -> list[tuple[str, str, str, str]]:
    """[(canonical, ATC, group, surface)] for antithrombotics named in `text`; longest/earliest match wins, traps masked."""
    low = _NOT_DRUG.sub(lambda m: " " * len(m.group(0)), T.fw(text).lower())
    found = []
    for canon, atc, group, rx in _DRUGS:
        for m in rx.finditer(low):
            found.append((m.start(), m.end(), canon, atc, group, m.group(0)))
    found.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    out, end = [], -1
    for s, e, canon, atc, group, surface in found:
        if s >= end:
            out.append((canon, atc, group, surface))
            end = e
    return out


def drug_classes(text: str) -> set[str]:
    return {_GROUP_CLASS[g] for _, _, g, _ in drug_mentions(text)}


def has_antithrombotic(text: str) -> bool:
    return bool(drug_mentions(text))


# ------------------------------------------------------------------------------------------- intent and its source
_A_CONTINUE = re.compile(r"继续|维持|continu|maintain")
_A_RESUME = re.compile(r"恢复|重新(?:启用|使用|开始)|resum|restart")
_A_INCREASE = re.compile(r"加量|增加剂量|加大剂量|increase")
_A_START = re.compile(r"给予|(?<![评参])予(?!以评估)|加用|启动|开始|启用|泵入|静滴|静推|皮下注射|负荷|口服|使用|服用|应用|联合|注射|"
                      r"预防|(?<!调整)治疗(?!调整|方案|策略|原则)|\bstart|\bgive|administer|\bload|initiat|\buse\b|therapy|prophyla")
_A_HOLD = re.compile(r"暂停|暂缓|暂不|\bhold")
_A_STOP = re.compile(r"停用|停止|停药|discontinu|\bstop")
_A_AVOID = re.compile(r"禁用|避免|禁忌|不宜|不建议|不予|无需|avoid|contraindicat|not recommended")
_A_MONITOR = re.compile(r"监测|复查|观察|monitor")
_A_ASSESS = re.compile(r"评估|必要性|时机|适应证|由.{0,20}(?:评估|决定|确定)|需经.{0,8}评估|会诊|assess|evaluat|to be decided")
_ALT_OPTION = re.compile(r"或(?:谨慎|酌情|小剂量|减量)(?:使用|应用|服用|继续)?|or (?:use with caution|continue)")
_HISTORY_CUE = re.compile(r"已(?:经)?(?:服用|口服|予|给予|使用|应用|接受)|曾(?:予|服|用|给予)|院外|外院|入院前|此前|"
                          r"previously|already|prior to admission")
_CONDITIONAL = re.compile(r"若|如(?!期|下|前)|假如|一旦|待.{0,12}(?:后|稳定)|稳定后|择期|可考虑|\bif\b|\bonce\b|consider")
_DOSE = re.compile(r"\d+(?:\.\d+)?\s*(?:mg|μg|ug|iu|单位|万单位|ml/h)|(?<![a-z])(?:qd|bid|tid|q12h|qn)(?![a-z])|/日|/天|每日|每天")
_PROPHYLAXIS = re.compile(r"预防|vte|prophyla")
_THERAPEUTIC = re.compile(r"治疗量|治疗剂量|足量|therapeutic|治疗性|(?<![a-z])inr")
_PROCEDURAL = re.compile(r"术中|体外循环|ecmo|介入(?:术)?中|造影时|透析|intra-?op|bypass|procedur")

# Fixed replacement wording (spec §5.4, §6, §10.1); every one defers the decision to a clinician.
_TEXT = {
    "zh": {
        "block_antiplatelet": "鉴于{lesion}及潜在出血风险，不建议常规{cont}{dual}抗血小板治疗；进一步明确病变分型、范围及并发症，"
                              "评估独立抗栓适应证，由经治医师结合心内科及心血管外科意见确定抗栓方案",
        "block_anticoagulant": "鉴于{lesion}及潜在出血风险，不建议常规{cont}抗凝治疗；评估独立抗凝适应证，"
                               "由经治医师结合心内科及心血管外科意见确定抗凝方案",
        "block_antithrombotic": "鉴于{lesion}及潜在出血风险，不建议常规{cont}抗栓治疗；评估独立抗栓适应证，"
                                "由经治医师结合心内科及心血管外科意见确定抗栓方案",
        "block_fibrinolysis": "当前存在或不能排除急性主动脉综合征，属全身溶栓禁忌；再灌注策略由经治医师结合主动脉影像结果确定",
        "review_prophylactic": "评估VTE风险与出血风险；在无相关禁忌时考虑机械性预防，药物性预防的适应证和启动时机"
                               "由经治医师结合主动脉病变及止血情况确定",
        "review_conditional": "结合复查影像、主动脉病变稳定性及{kind}适应证，由专科医师评估恢复治疗的必要性和时机",
        "review_option": "{kind}治疗的必要性及安全性需由专科医师评估确定",
        "review_hold": "评估暂停{kind}治疗的必要性及时机，由经治医师结合主动脉病变及出血风险确定",
        "review_generic": "{kind}治疗与当前主动脉病变存在潜在冲突，其必要性、时机及方案由经治医师结合主动脉病变稳定性及出血风险评估确定",
        "urgent": "{risk}与当前主动脉病变出血风险并存，需心内科与心血管外科紧急联合评估{kind}方案",
    },
    "en": {
        "block_antiplatelet": "Given {lesion} and the bleeding risk, routine {cont}{dual}antiplatelet therapy is not recommended; "
                              "clarify lesion type, extent and complications, assess any independent antithrombotic indication, "
                              "and the treating physician decides the regimen with cardiology and cardiovascular surgery",
        "block_anticoagulant": "Given {lesion} and the bleeding risk, routine {cont}anticoagulation is not recommended; assess any "
                               "independent indication, and the treating physician decides the regimen with cardiology and "
                               "cardiovascular surgery",
        "block_antithrombotic": "Given {lesion} and the bleeding risk, routine {cont}antithrombotic therapy is not recommended; "
                                "assess any independent indication, and the treating physician decides the regimen with "
                                "cardiology and cardiovascular surgery",
        "block_fibrinolysis": "An acute aortic syndrome is present or not excluded, which contraindicates systemic fibrinolysis; "
                              "the treating physician decides the reperfusion strategy with the aortic imaging",
        "review_prophylactic": "Assess VTE and bleeding risk; consider mechanical prophylaxis if not contraindicated; the treating "
                               "physician decides the indication and timing of pharmacological prophylaxis given the aortic "
                               "lesion and haemostasis",
        "review_conditional": "A specialist assesses the necessity and timing of resuming treatment against repeat imaging, "
                              "aortic stability and the {kind} indication",
        "review_option": "The necessity and safety of {kind} therapy are to be decided by a specialist",
        "review_hold": "The treating physician assesses the necessity and timing of holding {kind} therapy given the aortic "
                       "lesion and bleeding risk",
        "review_generic": "{kind} therapy potentially conflicts with the current aortic lesion; the treating physician assesses "
                          "its necessity, timing and regimen given aortic stability and bleeding risk",
        "urgent": "{risk} coexists with the bleeding risk of the current aortic lesion; cardiology and cardiovascular surgery "
                  "need to urgently assess the {kind} regimen together",
    },
}
_LESION = {"zh": {CONFIRMED_ACTIVE: "当前主动脉病变", SUSPECTED_ACTIVE: "尚未排除的急性主动脉综合征"},
           "en": {CONFIRMED_ACTIVE: "the current aortic lesion", SUSPECTED_ACTIVE: "a not yet excluded acute aortic syndrome"}}
_KIND = {"zh": {"antiplatelet": "抗血小板", "anticoagulant": "抗凝", "fibrinolysis": "溶栓", "antithrombotic": "抗栓"},
         "en": {"antiplatelet": "antiplatelet", "anticoagulant": "anticoagulant", "fibrinolysis": "fibrinolytic",
                "antithrombotic": "antithrombotic"}}
_RISK = {"zh": {"机械瓣膜": "机械瓣膜相关血栓栓塞风险", "急性肺栓塞": "急性肺栓塞的抗凝需求", "急性深静脉血栓": "深静脉血栓的抗凝需求",
                "心腔内血栓": "心腔内血栓栓塞风险", "近期冠脉支架": "近期冠脉支架相关血栓风险"},
         "en": {"机械瓣膜": "Mechanical-valve thromboembolic risk", "急性肺栓塞": "The anticoagulation need of acute PE",
                "急性深静脉血栓": "The anticoagulation need of DVT", "心腔内血栓": "Intracardiac thrombus embolic risk",
                "近期冠脉支架": "Recent coronary stent thrombosis risk"}}


def _part_regex(part: str) -> re.Pattern:
    # placeholders become short wildcards; whitespace and case are ignored
    return re.compile(re.sub(r"\\\{\w+\\\}", ".{0,24}", re.escape(T.squash(part))))


_TEMPLATE_PARTS = [_part_regex(p) for lang in _TEXT.values() for t in lang.values()
                   for p in re.split(r"[；;]", t) if len(p) >= 8]


def is_template(text: str) -> bool:
    """True if `text` is (a ；-part of) this rule's own fixed wording: screening it again must pass."""
    low = T.squash(text)
    return bool(low) and any(rx.search(low) for rx in _TEMPLATE_PARTS)


@dataclass
class Unit:
    text: str
    classes: set = field(default_factory=set)
    action: str = "UNKNOWN"          # START CONTINUE RESUME INCREASE HOLD STOP AVOID MONITOR HISTORY ASSESS_ONLY UNKNOWN
    category: str = ""               # spec §4 drug category
    modality: str = "UNCONDITIONAL"  # UNCONDITIONAL | CONDITIONAL | ASSESS_ONLY | OPTION | NEGATED
    source: str = "GENERATED_PLAN"   # SOURCE_FACT | SOURCE_CLINICIAN_ORDER | GENERATED_PLAN


def _residue(text: str) -> str:
    """What is left of a unit once drug names, doses, frequencies and connectives are removed."""
    low = _NOT_DRUG.sub(" ", T.fw(text).lower())
    for _, _, _, rx in _DRUGS:
        low = rx.sub(" ", low)
    low = _DOSE.sub(" ", low)
    return re.sub(r"\b(?:with|and|plus|or|po|iv|ih)\b|[+/、及和与：:（）()\s，,.。；;-]|片|粒", "", low)


def classify(text: str, source_text: str = "") -> Unit:
    """Medication action, category, modality and source of one decision unit."""
    u = Unit(text, drug_classes(text))
    if not u.classes:
        return u
    if is_template(text):
        u.action, u.modality = "ASSESS_ONLY", "ASSESS_ONLY"
        return u
    bare = re.sub(r"[（(][^（）()]*[）)]", "", T.fw(text).lower())
    src_low, src_sq = T.fw(source_text).lower(), T.squash(source_text)
    core = T.squash(re.sub(r"^[^：:]{0,12}[：:]", "", text))
    if len(core) >= 6 and core in src_sq:
        u.source = "SOURCE_CLINICIAN_ORDER"
    if _HISTORY_CUE.search(bare) and not _A_CONTINUE.search(bare):
        u.action = "HISTORY"
        # a history claim is a source fact only if the records name the same drugs (spec §4: never trust the draft)
        named = [rx for canon, _, _, rx in _DRUGS for c, *_ in drug_mentions(text) if c == canon]
        u.source = "SOURCE_FACT" if named and all(rx.search(src_low) for rx in named) else "GENERATED_PLAN"
    elif _A_HOLD.search(bare) or _A_STOP.search(bare) or _A_AVOID.search(bare):
        u.action = "HOLD" if _A_HOLD.search(bare) else "STOP" if _A_STOP.search(bare) else "AVOID"
        u.modality = "OPTION" if _ALT_OPTION.search(bare) else "NEGATED"
    elif _CONDITIONAL.search(bare) and any(rx.search(bare) for rx in (_A_RESUME, _A_START, _A_CONTINUE, _DOSE)):
        # a conditional ORDER ("若稳定，可考虑恢复双抗"); "待病情稳定后由多学科讨论决定后续抗栓策略" orders nothing
        u.action, u.modality = ("RESUME" if _A_RESUME.search(bare) else "START"), "CONDITIONAL"
    elif _A_MONITOR.search(bare) and not (_A_CONTINUE.search(bare) or _DOSE.search(bare)):
        u.action, u.modality = "MONITOR", "ASSESS_ONLY"
    elif _A_ASSESS.search(bare) and not (_A_CONTINUE.search(bare) or _DOSE.search(bare)):
        u.action, u.modality = "ASSESS_ONLY", "ASSESS_ONLY"
    elif _A_CONTINUE.search(bare):
        u.action = "CONTINUE"
    elif _A_RESUME.search(bare):
        u.action = "RESUME"
    elif _A_INCREASE.search(bare):
        u.action = "INCREASE"
    elif _A_START.search(bare) or _DOSE.search(bare) or len(_residue(text)) <= 4:
        u.action = "START"         # explicit verb, a dose, or an item that is nothing but drug names ("DAPT with ASA")
    u.category = _category(u, bare)
    return u


def _category(u: Unit, bare: str) -> str:
    if "fibrinolysis" in u.classes:
        return "SYSTEMIC_FIBRINOLYSIS"
    if "anticoagulant" in u.classes or u.classes == {"antithrombotic"}:
        if _PROCEDURAL.search(bare):
            return "PROCEDURAL_ANTICOAGULATION"
        if _PROPHYLAXIS.search(bare):
            return "PROPHYLACTIC_ANTICOAGULATION"
        return "THERAPEUTIC_ANTICOAGULATION" if _THERAPEUTIC.search(bare) else "ANTICOAGULATION_UNSPECIFIED"
    agents = {c for c, _, g, _ in drug_mentions(u.text) if g in _AGENT_GROUPS}
    if re.search(r"双联抗血小板|双抗|dapt", bare) or len(agents) > 1:
        return "DUAL_ANTIPLATELET"
    return "SINGLE_ANTIPLATELET" if agents else "ANTIPLATELET_UNSPECIFIED"


_OWN_ACTION = (_A_CONTINUE, _A_RESUME, _A_START, _A_HOLD, _A_STOP, _A_AVOID, _HISTORY_CUE)


def units(sentence: str, source_text: str = "") -> list[Unit]:
    """Decision units of one ；/。 sentence. A clause naming a drug opens a unit when it carries its own action or a new
    class; otherwise ("…，氯吡格雷300mg/日") it continues the open unit. Drug-free clauses join the open unit and leading
    ones join the first, so a unit is never a dangling fragment and rewriting one never leaves one behind."""
    parts = re.split(r"([，,])", sentence)
    clauses = [parts[i] + (parts[i + 1] if i + 1 < len(parts) else "") for i in range(0, len(parts), 2)]
    raw: list[list] = []
    lead = ""
    for c in clauses:
        cls = drug_classes(c)
        low = T.fw(c).lower()
        own = any(rx.search(low) for rx in _OWN_ACTION)
        if cls and (not raw or not raw[-1][1] or own or cls - raw[-1][1]):
            raw.append([lead + c, set(cls)])
            lead = ""
        elif raw:
            raw[-1][0] += c
            raw[-1][1] |= cls
        else:
            lead += c
    if lead:
        if raw:
            raw[-1][0] += lead
        else:
            raw.append([lead, set()])
    return [classify(t, source_text) for t, _ in raw]


# ------------------------------------------------------------------------------------------------------ decisions
PASS, BLOCK, REVIEW, REVIEW_URGENT = "PASS", "BLOCK", "REVIEW", "REVIEW_URGENT"
_ORDER_ACTIONS = ("START", "CONTINUE", "RESUME", "INCREASE")


@dataclass
class Decision:
    action: str
    reason_code: str
    template: str = ""                     # key into _TEXT ("" = keep the text)
    indication: Indication | None = None


def _relevant(indications: list[Indication], classes: set) -> list[Indication]:
    want = classes | ({"anticoagulant", "antiplatelet"} if "antithrombotic" in classes else set())
    return [i for i in indications if i.drug_class in want]


def decide(state: str, u: Unit, indications: list[Indication], receiving: set = frozenset()) -> Decision:
    """Spec §5.2 matrix for generated suggestions. Source facts and real orders copied from the records are never
    rewritten (§5.1); a conflict with them is a visible REVIEW with the text kept."""
    if not u.classes or u.action in ("MONITOR", "ASSESS_ONLY", "UNKNOWN"):
        return Decision(PASS, "NOT_A_SYSTEMIC_ORDER")
    if u.action == "HISTORY":
        return Decision(PASS, "SOURCE_HISTORY" if u.source == "SOURCE_FACT" else "HISTORY_NOT_IN_SOURCE_DEFERRED_TO_FACT_CHECK")
    if state in QUIET_STATES:
        return Decision(PASS, "NO_CURRENT_AAS")
    order = u.action in _ORDER_ACTIONS
    fib = u.category == "SYSTEMIC_FIBRINOLYSIS"
    if u.source == "SOURCE_CLINICIAN_ORDER":
        if state in STABLE_STATES and not fib:
            return Decision(PASS, "STABLE_AAS")
        return Decision(REVIEW, "SOURCE_ORDER_CONFLICT_REVIEW")
    if state in STABLE_STATES:
        if fib and order:
            return Decision(REVIEW, "STABLE_AAS_FIBRINOLYSIS_REVIEW", "review_generic")
        return Decision(PASS, "STABLE_AAS")
    if state in (PERIOPERATIVE, UNKNOWN):
        if not order and u.modality != "CONDITIONAL":
            return Decision(PASS, "NO_ORDER")
        key = "review_prophylactic" if u.category == "PROPHYLACTIC_ANTICOAGULATION" else "review_generic"
        return Decision(REVIEW, f"{state}_AAS_REVIEW", key)
    # current confirmed or suspected AAS
    kind = _kind(u)
    if u.modality == "OPTION":
        return Decision(REVIEW, "WITHHOLD_OR_CAUTION_OPTION", "review_option")
    if u.action in ("HOLD", "STOP", "AVOID"):
        return Decision(REVIEW, "AUTOMATIC_STOP_NOT_AUTHORISED", "review_hold" if kind in receiving else "review_option")
    if u.modality == "CONDITIONAL":
        return Decision(REVIEW, "CONDITIONAL_RESUMPTION", "review_conditional")
    if fib:
        return Decision(BLOCK, "AAS_FIBRINOLYSIS_CONTRAINDICATED", "block_fibrinolysis")
    if u.category in ("PROPHYLACTIC_ANTICOAGULATION", "PROCEDURAL_ANTICOAGULATION"):
        key = "review_prophylactic" if u.category == "PROPHYLACTIC_ANTICOAGULATION" else "review_generic"
        return Decision(REVIEW, u.category + "_REVIEW", key)
    rel = _relevant(indications, u.classes)
    urgent = [i for i in rel if i.urgent]
    if urgent:
        return Decision(REVIEW_URGENT, "COMPETING_INDICATION", "urgent", urgent[0])
    if rel:
        return Decision(REVIEW, "POSSIBLE_INDICATION", "review_generic", rel[0])
    return Decision(BLOCK, "AAS_WITHOUT_INDEPENDENT_INDICATION", "block_" + kind)


# ---------------------------------------------------------------------------------------------------- rendering
def _kind(u: Unit) -> str:
    for k in ("fibrinolysis", "antiplatelet", "anticoagulant", "antithrombotic"):
        if k in u.classes:
            return k
    return "antithrombotic"


def render(u: Unit, d: Decision, lang: str, state: str, receiving: set) -> str:
    """Safe text for a unit: the fixed wording of its decision, or the unit unchanged."""
    if not d.template:
        return u.text
    lang = "zh" if lang == "zh" else "en"
    kind = d.indication.drug_class if d.indication else _kind(u)
    if d.template.startswith("block_") and d.template != "block_fibrinolysis":
        kind = d.template[6:]
    text = _TEXT[lang][d.template].format(
        kind=_KIND[lang][kind], lesion=_LESION[lang].get(state, _LESION[lang][CONFIRMED_ACTIVE]),
        dual=("双联" if lang == "zh" else "dual ") if u.category == "DUAL_ANTIPLATELET" else "",
        cont=("继续" if lang == "zh" else "continued ") if kind in receiving and u.action == "CONTINUE" else "",
        risk=_RISK[lang].get(d.indication.name, d.indication.name) if d.indication else "")
    if lang == "en" and text[:1].islower():
        text = text[0].upper() + text[1:]
    return text


def receiving_classes(case) -> set:
    """Antithrombotic classes the records show the patient received (e.g. a loading dose before transfer)."""
    got = set()
    for s in case.sources:
        for sent in T.split_sentences(s.content):
            low = T.fw(sent).lower()
            if _HISTORY_CUE.search(low) or _A_START.search(low) or _A_CONTINUE.search(low):
                got |= drug_classes(sent)
    return got


@dataclass
class Event:
    rule_id: str
    rule_version: str
    action: str
    disease_state: str
    source_evidence: list
    drug_classes: list
    medication_intent: str
    indication_status: str
    indication_evidence: list
    original_candidate: str        # internal audit only, never in the official record
    replacement: str
    reason_code: str
    reference_ids: list
    entity: str = ""
    indication: str = ""
    coronary_involvement: bool = False

    def as_dict(self):
        return asdict(self)


_REFS = {"AAS_FIBRINOLYSIS_CONTRAINDICATED": ["R04"], "PROPHYLACTIC_ANTICOAGULATION_REVIEW": ["R06", "R07"],
         "COMPETING_INDICATION": ["R03", "R05"], "POSSIBLE_INDICATION": ["R03"], "STABLE_AAS_FIBRINOLYSIS_REVIEW": ["R04"]}


@dataclass
class Context:
    state: str
    finding: AorticFinding | None
    indications: list
    receiving: set
    source_text: str
    coronary: bool


def context(case) -> Context:
    state, finding = aortic_state(case)
    return Context(state, finding, recorded_indications(case), receiving_classes(case),
                   "\n".join(s.content for s in case.sources),
                   any(_CORONARY_INVOLVEMENT.search(T.fw(s.content).lower()) for s in case.sources))


def screen_text(text: str, case, lang: str, ctx: Context | None = None) -> tuple[str, list[Event]]:
    """(safe text, non-PASS events) for one plan statement. Rewritten units become their own ；-delimited sentence."""
    if not has_antithrombotic(text):
        return text, []
    ctx = ctx or context(case)
    if ctx.state in QUIET_STATES:
        return text, []
    chunks = re.split(r"([；;。])", text)
    events = []
    for i in range(0, len(chunks), 2):
        if not has_antithrombotic(chunks[i]):
            continue
        pieces = []                                      # (text, rewritten?)
        for u in units(chunks[i], ctx.source_text):
            d = decide(ctx.state, u, ctx.indications, ctx.receiving)
            new = render(u, d, lang, ctx.state, ctx.receiving)
            if d.action != PASS:
                rel = _relevant(ctx.indications, u.classes)
                f = ctx.finding
                events.append(Event(
                    RULE_ID, RULE_VERSION, d.action, ctx.state, f.evidence if f else [], sorted(u.classes),
                    f"{u.category or 'UNSPECIFIED'}:{u.action}:{u.modality}:{u.source}",
                    "DOCUMENTED" if rel else "NOT_DOCUMENTED", [x.evidence for x in rel], u.text, new,
                    d.reason_code, _REFS.get(d.reason_code, ["R01", "R02", "R03"]), f.entity if f else "",
                    d.indication.name if d.indication else "", ctx.coronary))
            pieces.append((new, new != u.text))
        out = ""
        for j, (piece, rewritten) in enumerate(pieces):
            nxt_rewritten = j + 1 < len(pieces) and pieces[j + 1][1]
            if rewritten or nxt_rewritten:
                piece = piece.rstrip("，, ")
                if j + 1 < len(pieces):
                    piece += "；"
            out += piece
        chunks[i] = out
    return "".join(chunks), events


def screen_plan(note, case, lang: str) -> list[Event]:
    """Apply the screen to the treatment plan in place. Never empties it: blocked units are replaced, not deleted."""
    ctx = context(case)
    if ctx.state in QUIET_STATES:
        return []
    events = []
    for st in note.sections["treatment_plan"]:
        st.text, ev = screen_text(st.text, case, lang, ctx)
        events += ev
    return events


_MSG = {
    "zh": {
        "lead": {CONFIRMED_ACTIVE: "当前资料提示{name}。", SUSPECTED_ACTIVE: "当前资料尚未排除{name}。",
                 PERIOPERATIVE: "资料记录{name}处于围术期。", UNKNOWN: "资料记录有{name}，当前病变状态不明。",
                 STABLE_CHRONIC: "资料记录有{name}。", STABLE_POST_REPAIR: "资料记录有{name}修复术后。"},
        "generated": "生成的{kinds}建议存在安全风险，未作为可执行给药方案输出。请结合主动脉病变稳定性{ind}及出血风险，由经治医师确定治疗策略。",
        "ind": "、已记录的{names}",
        "urgent": "{risk}与当前主动脉病变出血风险并存，需心内科与心血管外科紧急联合评估{kind}方案。",
        "coronary": "主动脉病变累及冠脉开口可致冠脉灌注不良，需紧急联合评估主动脉及冠脉病变。",
        "source_order": "资料记录的{kinds}医嘱与当前主动脉病变存在潜在出血风险冲突，原医嘱未作改动，请经治医师核对。",
    },
    "en": {
        "lead": {CONFIRMED_ACTIVE: "The records indicate {name}. ", SUSPECTED_ACTIVE: "The records do not yet exclude {name}. ",
                 PERIOPERATIVE: "The records document perioperative {name}. ",
                 UNKNOWN: "The records document {name}; its current status is unclear. ",
                 STABLE_CHRONIC: "The records document {name}. ", STABLE_POST_REPAIR: "The records document repaired {name}. "},
        "generated": "The generated {kinds} suggestion carries a safety risk and was not output as an executable order. The "
                     "treating physician decides the strategy given aortic stability{ind} and bleeding risk.",
        "ind": ", the documented {names}",
        "urgent": "{risk} coexists with the bleeding risk of the current aortic lesion; cardiology and cardiovascular surgery "
                  "need to urgently assess the {kind} regimen together.",
        "coronary": "Aortic involvement of the coronary ostium can cause coronary malperfusion; assess the aortic and "
                    "coronary lesions together, urgently.",
        "source_order": "A recorded {kinds} order potentially conflicts with the bleeding risk of the current aortic lesion; "
                        "it was left unchanged for the treating physician to check.",
    },
}
_IND_EN = {"机械瓣膜": "mechanical valve", "急性肺栓塞": "acute pulmonary embolism", "急性深静脉血栓": "deep vein thrombosis",
           "心腔内血栓": "intracardiac thrombus", "近期冠脉支架": "recent coronary stent", "心房颤动": "atrial fibrillation"}


def review_messages(events: list[Event], lang: str) -> list[str]:
    """Clinician-visible review items for the official record (spec §9). They name the lesion and drug classes only,
    never quote the draft, and never claim a drug was stopped, a consultation done or a diagnosis confirmed."""
    if not events:
        return []
    lang = "zh" if lang == "zh" else "en"
    m, sep = _MSG[lang], "、" if lang == "zh" else ", "
    e0 = events[0]
    name = ENTITY_NAME[lang].get(e0.entity, ENTITY_NAME[lang]["acute_aortic_syndrome"])
    lead = m["lead"].get(e0.disease_state, "").format(name=name)
    kinds = lambda evs: sep.join(dict.fromkeys(_KIND[lang][_kind(Unit("", set(e.drug_classes)))] for e in evs))
    out = []
    gen = [e for e in events if e.action in (BLOCK, REVIEW) and e.reason_code != "SOURCE_ORDER_CONFLICT_REVIEW"]
    if gen:
        inds = list(dict.fromkeys(e.indication for e in gen if e.indication))
        ind = m["ind"].format(names=sep.join(inds if lang == "zh" else [_IND_EN.get(i, i) for i in inds])) if inds else ""
        out.append(lead + m["generated"].format(kinds=kinds(gen), ind=ind))
    for e in events:
        if e.action == REVIEW_URGENT:
            kind = _KIND[lang]["anticoagulant" if "anticoagulant" in e.drug_classes else "antiplatelet"]
            out.append(m["urgent"].format(risk=_RISK[lang].get(e.indication, e.indication), kind=kind))
    src = [e for e in events if e.reason_code == "SOURCE_ORDER_CONFLICT_REVIEW"]
    if src:
        out.append(m["source_order"].format(kinds=kinds(src)))
    if any(e.coronary_involvement for e in events):
        out.append(m["coronary"])
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------------------- dose check (independent of AAS)
# A loading-size dose given per day (spec §8). Maintenance examples: aspirin 75-100 mg/d, clopidogrel 75 mg/d. Flagged
# only, never rewritten; no global cross-disease dose limits beyond these loading-size thresholds.
_LOADING = {"aspirin": 300, "clopidogrel": 300, "prasugrel": 60}
_PER_DAY = re.compile(r"^\s*(?:/\s*(?:日|天|d\b|day)|每日|每天|qd|daily|once daily|1次/日|一日一次)")
_LOADING_CUE = re.compile(r"负荷|首剂|顿服|一次性|loading|single dose|\bstat\b")


def loading_as_maintenance(text: str) -> list[tuple[str, float]]:
    """(drug, mg) where a plan clause gives a loading-size dose per day ("阿司匹林300mg/日") without saying loading."""
    out = []
    for clause in re.split(r"[，,；;。]", T.fw(text).lower()):
        if _LOADING_CUE.search(clause):
            continue
        for canon, _, _, rx in _DRUGS:
            if canon not in _LOADING:
                continue
            for m in rx.finditer(clause):
                d = re.match(r"[^\d，,]{0,8}?(\d+(?:\.\d+)?)\s*mg", clause[m.end():])
                if d and float(d.group(1)) >= _LOADING[canon] and _PER_DAY.search(clause[m.end() + d.end():]):
                    out.append((canon, float(d.group(1))))
    return out
