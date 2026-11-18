"""Synthetic engineering fixtures only; artifacts are retained, never exit-cleaned."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from medtrace.config import Config
from medtrace.inputs import parse_case
from medtrace.knowledge import KnowledgeBase, KnowledgeError, build_database, search_tokens, validate_entry, write_audit
from medtrace.ledger import build_ledger
from medtrace.llm import LLMClient
from medtrace.note import Statement, note_from_model
from medtrace.pipeline import Pipeline, apply_patches
from medtrace.verify import check_statement


def entry(kid="K1", **kw):
    return dict(dict(id=kid, type="card", title="测试血钾", text="测试血钾阈值 6 mmol/L。", aliases=["测试血钾", "potassium"],
                     source="synthetic engineering fixture", version="test-only", locator="fixture:1", scope="adult",
                     status="approved", license="self-authored-test-only", reviewer="engineering fixture", reviewed_at="2026-11-17"), **kw)


CASE = {"case_id": "KB-test", "record_cutoff": "2026-03-01", "sources": [
    {"source_id": "S1", "content": "患者50岁。成人 serum methodA 血钾 7 mmol/L。测试血钾待核实。"},
    {"source_id": "late", "time": "2026-03-03", "content": "未来肺炎。"}]}


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="medtrace-kb-test-"))
        self.path = self.directory / "test.sqlite"
        self.entries = [entry(), entry("T1", type="term", title="测试血钾", text="测试血钾", aliases=["K", "potassium"]),
                        entry("L1", type="lab", title="血钾", aliases=["potassium"], units=["mmol/L"]),
                        entry("R1", type="rule", title="测试规则", analyte="血钾", aliases=["potassium"], unit="mmol/L",
                              operator="above", threshold=6, requires={"population":"成人", "specimen":"serum", "method":"methodA"})]
        build_database(self.entries, self.path, "engineering-test")
        self.kb = KnowledgeBase(str(self.path))
        self.case = parse_case(CASE, 0)

    def test_tokenizer(self):
        t = search_tokens("血钾血钾 Na K potassium")
        self.assertEqual(t.count("血钾"), 2)
        self.assertIn("na", t)
        self.assertIn("k", t)
        self.assertIn("potassium", t)

    def test_draft_and_duplicate_guard(self):
        with self.assertRaises(KnowledgeError):
            build_database([entry(status="draft")], self.directory / "empty.sqlite", "draft")
        with self.assertRaises(KnowledgeError):
            build_database([entry(), entry()], self.directory / "duplicate.sqlite", "x")
        with self.assertRaises(KnowledgeError):
            build_database(self.entries, self.path, "overwrite")
        with self.assertRaises(KnowledgeError):
            validate_entry(entry(license="pending"))
        with self.assertRaises(KnowledgeError):
            validate_entry(entry(template=True))
        with self.assertRaises(KnowledgeError):
            validate_entry(entry(permission_review={"status":"not_granted"}))
        with self.assertRaises(KnowledgeError):
            validate_entry(entry(clinical_review={"status":"source_alignment_checked", "pre_review_by":"AI"}))

    def test_readonly_integrity(self):
        with self.kb.connect() as db:
            with self.assertRaises(Exception):
                db.execute("INSERT INTO entries VALUES ('X','{}')")
        m = self.path.with_suffix(".manifest.json")
        obj = json.loads(m.read_text()); obj["sha256"] = "bad"
        m.write_text(json.dumps(obj))
        with self.assertRaises(KnowledgeError):
            KnowledgeBase(str(self.path))

    def test_retrieve_alias_and_no_answer(self):
        self.assertEqual([e["id"] for e in self.kb.retrieve("50岁 potassium")], ["K1"])
        self.assertEqual(self.kb.retrieve("50岁 牙齿松动"), [])
        self.assertEqual(self.kb.retrieve("5岁 测试血钾"), [])
        self.assertEqual(self.kb.retrieve("测试血钾"), [])
        self.assertEqual(self.kb.normalize("skin"), [])
        self.assertTrue(self.kb.normalize("K 7 mmol/L"))

    def test_rules_three_states_and_boundary(self):
        def state(text):
            c = parse_case({"case_id":1,"sources":[{"source_id":"S","content":"50岁。"+text}]}, 0)
            return next(r["state"] for r in self.kb.check_rules(build_ledger(c)) if r["id"] == "R1")
        self.assertEqual(state("成人 serum methodA 血钾 7 mmol/L。"), "triggered")
        self.assertEqual(state("成人 serum methodA 血钾 6 mmol/L。"), "not_triggered")
        self.assertEqual(state("成人 serum methodA 血钾 5 mmol/L。"), "not_triggered")
        for t in ("血钾 7 mmol/L。", "成人 serum methodA 血钾 7 mg/L。", "成人 serum methodA 血钾待回报。"):
            self.assertEqual(state(t), "insufficient", t)

    def test_number_quotation_and_patient_values(self):
        L = build_ledger(self.case); L.knowledge_cards = {"K1":self.entries[0]}
        def codes(st, sec="diagnostic_discussion"):
            return {f.code for f in check_statement(sec,0,st,self.case,L)}
        quote = Statement(self.entries[0]["text"], [], "", "knowledge", ["K1"])
        self.assertNotIn("number_not_in_source", codes(quote))
        self.assertIn("number_not_in_source", codes(Statement("患者血钾 6 mmol/L。", ["S1"], "", "record", ["K1"])))
        self.assertIn("unverified_knowledge_number", codes(Statement("患者血钾 7 mmol/L。", ["S1"], "", "knowledge", ["K1"])))
        self.assertIn("invalid_knowledge_ref", codes(Statement("说明", [], "", "knowledge", ["FORGED"])))
        self.assertIn("knowledge_in_features", codes(quote, "case_features"))

    def test_parse_copy_and_patch(self):
        n = note_from_model({"diagnostic_discussion":[{"text":self.entries[0]["text"],"basis":"knowledge","knowledge_ids":["K1"]}]})
        self.assertEqual(n.copy().sections["diagnostic_discussion"][0].knowledge_ids, ["K1"])
        L = build_ledger(self.case); L.knowledge_cards={"K1":self.entries[0]}
        result = apply_patches(n,[{"section":"diagnostic_discussion","index":0,"action":"replace","text":"伪造知识", "basis":"knowledge","knowledge_ids":["BAD"]}], self.case,L,"review",set())
        self.assertEqual(result["rejected"],1)

    def test_variants_context_and_audit(self):
        class Client:
            def __init__(self): self.prompts=[]
            def chat(me, system, user, *args):
                me.prompts.append(user)
                return json.dumps({"case_features":[{"text":"患者50岁。","sources":["S1"]}],
                    "diagnostic_discussion":[{"text":self.entries[0]["text"],"basis":"knowledge","knowledge_ids":["K1"]}],
                    "treatment_plan":[{"text":"建议复查血钾。","sources":["S1"],"basis":"inference"}]},ensure_ascii=False)
        for variant in ("A0","A1","A2","S2","A3"):
            c = Config(kb_path=str(self.path),pipeline=variant,repair_call=False,output_protocol="legacy")
            client=Client(); result=Pipeline(c,client).run_case(self.case)
            self.assertEqual(result.status,"ok")
            if variant == "A0":
                self.assertNotIn("<knowledge_context>",client.prompts[0])
            else:
                self.assertTrue(any("<knowledge_context>" in p for p in client.prompts))
                self.assertNotIn("未来肺炎", "".join(client.prompts))
                self.assertEqual(result.log["knowledge"]["citations"][0]["knowledge_ids"],["K1"])
            self.assertFalse(any("knowledge_ids" in e for e in result.record["evidence"]))
        out=self.directory/'out.json'; out.write_text(json.dumps(result.record))
        write_audit(out,[result],self.kb)
        self.assertEqual(json.loads(Path(str(out)+'.knowledge_audit.json').read_text())["knowledge_version"],"engineering-test")

    def test_degraded_retrieval(self):
        c=Config(kb_path=str(self.path), api_base="mock://", repair_call=False, output_protocol="legacy")
        pipe=Pipeline(c,LLMClient(c))
        with patch.object(pipe.kb,"retrieve",side_effect=OSError("unavailable")):
            res=pipe.run_case(self.case)
        self.assertEqual(res.log["knowledge"]["status"],"degraded")
        self.assertTrue(any("知识检索失败" in r["description"] for r in res.record["review_items"]))

    def test_same_reply_with_no_library_no_hits_error_and_cards(self):
        reply = json.dumps({
            "case_features": [{"text": "患者50岁。", "sources": ["S1"]}],
            "diagnostic_discussion": [{"text": "结合病史及检查综合评估。", "basis": "knowledge"}],
            "treatment_plan": [{"text": "建议复核病历。", "sources": ["S1"], "basis": "inference"}],
        }, ensure_ascii=False)

        def run(kb, found, error=None):
            prompts = []
            def transport(url, headers, payload, timeout):
                prompts.append(payload["messages"])
                return 200, json.dumps({"choices": [{"message": {"content": reply}}]})
            cfg = Config(endpoint="http://127.0.0.1/stub", model="test", repair_call=False)
            pipe = Pipeline(cfg, LLMClient(cfg, transport=transport))
            pipe.kb = kb
            with patch.object(self.kb, "retrieve", return_value=found, side_effect=error):
                result = pipe.run_case(self.case)
            self.assertEqual(result.status, "ok")
            return prompts, result

        baseline, plain = run(None, [])
        for found, error, status in (([], None, "no_hits"), ([], OSError("failure"), "degraded"),
                                      ([self.entries[0]], None, "ok")):
            with self.subTest(status=status):
                prompts, result = run(self.kb, found, error)
                self.assertEqual(result.log["knowledge"]["status"], status)
                codes = {f.code for f in result.final_findings}
                self.assertEqual("missing_knowledge_ref" in codes, bool(found))
                if not found:
                    self.assertEqual(prompts, baseline)
                    self.assertEqual(result.final_findings, plain.final_findings)
                if status == "no_hits":
                    self.assertTrue(any(r["state"] == "triggered" for r in result.log["knowledge"]["rules"]))
                    self.assertTrue(any(self.entries[-1]["text"] in item for item in result.record["medical_record"]["review_items"]))
                if status == "degraded":
                    self.assertTrue(any("知识检索失败" in item for item in result.record["medical_record"]["review_items"]))

    def test_fabricated_knowledge_id_checked_without_a_library(self):
        ledger = build_ledger(self.case)
        st = Statement("患者血钾 99 mmol/L。", ["S1"], "", "record", ["FORGED"])
        codes = {f.code for f in check_statement("case_features", 0, st, self.case, ledger)}
        self.assertTrue({"invalid_knowledge_ref", "knowledge_in_features", "number_not_in_source"} <= codes)

    def test_package_with_knowledge(self):
        from scripts.build_submission import build_zip
        import zipfile
        root=Path(__file__).resolve().parents[1]
        dest=self.directory/'package.zip'
        names,_=build_zip(root,dest,self.path)
        self.assertIn('resources/knowledge.sqlite',names)
        self.assertNotIn('knowledge/entries.jsonl',names)
        with zipfile.ZipFile(dest) as z:
            z.extractall(self.directory/'package')
        KnowledgeBase(str(self.directory/'package/resources/knowledge.sqlite'))

    def test_reference_interval_requires_applicability(self):
        entries=[entry('L2', type='lab', title='血钾', units=['mmol/L'], aliases=[],
                       reference_interval={'low':3,'high':5,'requires':{'method':'methodA','specimen':'serum'}})]
        path=self.directory/'interval.sqlite'; build_database(entries,path,'test')
        kb=KnowledgeBase(str(path))
        def state(text):
            case=parse_case({'case_id':1,'sources':[{'source_id':'S','content':text}]},0)
            return kb.check_rules(build_ledger(case))[0]['state']
        self.assertEqual(state('50岁。serum methodA 血钾 7 mmol/L。'),'triggered')
        self.assertEqual(state('50岁。serum methodA 血钾 4 mmol/L。'),'not_triggered')
        self.assertEqual(state('50岁。血钾 4 mmol/L。'),'insufficient')
        self.assertEqual(state('8岁。serum methodA 血钾 4 mmol/L。'),'insufficient')

    def test_batch_sidecar_and_write_failure_preflight(self):
        from medtrace import runner
        from medtrace.knowledge import digest_file
        inp=self.directory/'input.json'; inp.write_text(json.dumps([CASE,CASE]))
        out=self.directory/'output.json'
        cfg=Config(input_path=str(inp),output_path=str(out),log_dir=str(self.directory/'logs'),
                   kb_path=str(self.path),api_base='mock://',workers=2,repair_call=False,output_protocol="legacy")
        with patch.object(runner,'load_config',return_value=cfg):
            self.assertEqual(runner.main([]),0)
        audit=json.loads(Path(str(out)+'.knowledge_audit.json').read_text())
        self.assertEqual(audit['output_sha256'],digest_file(out))
        self.assertEqual([r['index'] for r in audit['cases']],[0,1])
        with patch.object(runner,'load_config',return_value=cfg), patch.object(runner,'atomic_write_json',side_effect=OSError('not writable')), patch.object(Pipeline,'run_case') as run:
            self.assertEqual(runner.main([]),1)
            run.assert_not_called()

    def test_incremental_sidecar(self):
        from medtrace import update
        inp=self.directory/'update-input.json'; inp.write_text(json.dumps([CASE]))
        out=self.directory/'update-output.json'
        cfg=Config(kb_path=str(self.path),api_base='mock://',repair_call=False,output_protocol="legacy")
        with patch.object(update,'load_config',return_value=cfg):
            self.assertEqual(update.main([str(inp),str(inp),'--output',str(out)]),0)
        audit=json.loads(Path(str(out)+'.knowledge_audit.json').read_text())
        self.assertEqual(audit['cases'][0]['index'],0)
        self.assertEqual(audit['cases'][0]['status'],'ok')

    def test_retrieval_metrics(self):
        from eval.knowledge import evaluate
        report=evaluate(self.kb,[{'id':'answer','query':'50岁 potassium','relevant_ids':['K1']},
                                 {'id':'none','query':'50岁 牙齿松动','relevant_ids':[]}])
        self.assertEqual(report['recall_at_5'],1)
        self.assertEqual(report['false_injection_rate'],0)

    def test_draft_catalog_and_question_split(self):
        root=Path(__file__).resolve().parents[1]
        entries=[json.loads(l) for l in (root/'knowledge/entries.jsonl').read_text().splitlines()]
        for e in entries:
            validate_entry(e)
            self.assertEqual(e['status'],'draft')
        self.assertEqual({t:sum(e['type']==t for e in entries) for t in ('term','lab','card','rule')},
                         {'term':300,'lab':30,'card':24,'rule':10})
        doc=json.loads((root/'eval/knowledge_questions.json').read_text())
        self.assertEqual(len({q['id'] for q in doc['questions']}),80)
        for split in ('dev','heldout'):
            qs=[q for q in doc['questions'] if q['split']==split]
            self.assertEqual(len(qs),40)
            self.assertEqual(sum(not q['relevant_ids'] for q in qs),8)


if __name__ == "__main__":
    unittest.main()
