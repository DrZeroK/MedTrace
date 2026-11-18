"""MIPROv2 changes organization instructions only; all inference uses the shared journal."""
from __future__ import annotations

import copy
import importlib.metadata
import json

from eval.experiment import fingerprint
from medtrace.llm import CallStats, LLMClient


def optimize(experiment):
    from eval.phase1 import SEED_INSTRUCTION, keep
    completed = experiment.directory / "optimization.json"
    if completed.exists():
        return json.loads(completed.read_text("utf-8"))["instruction"]
    if importlib.metadata.version("dspy") != "3.5.0":
        raise ValueError("this experiment requires dspy==3.5.0")
    import dspy
    from dspy.lm15 import Message, Response, TextPart, Usage
    dspy.configure_cache(enable_disk_cache=False, enable_memory_cache=False)

    class BudgetEngine:
        def complete(self, request):
            def text(parts):
                if any(not isinstance(p, TextPart) for p in parts):
                    raise ValueError("proposal transport accepts text only")
                return "\n".join(p.text for p in parts)
            system = request.system or ""
            if not isinstance(system, str):
                system = text(system)
            system += ("\n只优化中文入院记录的组织建议，700字以内。固定事实、截止时间、来源引用和JSON协议不可更改。"
                       "不增加角色权限、外部知识或任何病例事实。")
            user = "\n\n".join(f"[{m.role}]\n{text(m.parts)}" for m in request.messages)
            key = fingerprint({"system": system, "user": user, "config": repr(request.config)})
            path = experiment.directory / "cache" / f"proposal_{key}.json"
            if path.exists():
                content = json.loads(path.read_text("utf-8"))["text"]
            else:
                cfg = copy.copy(experiment.cfg)
                cfg.output_protocol, cfg.max_calls_per_case = "legacy", 1
                cfg.temperature = request.config.temperature if request.config.temperature is not None else 1.0
                cfg.json_mode = False
                previous = experiment.budget.purpose
                experiment.budget.purpose = "instruction_proposal"
                try:
                    content = LLMClient(cfg, transport=experiment.budget.post).chat(system, user, CallStats())
                finally:
                    experiment.budget.purpose = previous
                keep(path, {"text": content})
            return Response(id=None, model=experiment.cfg.model, message=Message.assistant(content),
                            finish_reason="stop", usage=Usage())

    class Organization(dspy.Signature):
        admission: str = dspy.InputField(desc="公开CMB-Clin入院资料")
        draft: str = dspy.OutputField(desc="按固定JSON协议组织的中文入院记录")

    class Student(dspy.Module):
        def __init__(self):
            super().__init__()
            self.organize = dspy.Predict(Organization.with_instructions(SEED_INSTRUCTION))

        def forward(self, case_id, admission):
            instruction = self.organize.signature.instructions
            result = experiment.generate(case_id, "zh_context_v1", instruction)
            return dspy.Prediction(score=result["metrics"]["score"], draft=result["record"])

    class InstructionOnlyMIPRO(dspy.MIPROv2):
        def _bootstrap_fewshot_examples(self, program, *args, **kwargs):
            # DSPy 3.5 bootstraps proposal demos even with both limits zero; this experiment forbids that.
            return {i: [[] for _ in range(3)] for i, _ in enumerate(program.predictors())}

    examples = lambda split: [dspy.Example(case_id=cid, admission=json.dumps(experiment.items[cid][0], ensure_ascii=False))
                             .with_inputs("case_id", "admission") for cid in experiment.splits[split]]
    lm = dspy.BaseLM(model=experiment.cfg.model, engine=BudgetEngine(), cache=False, num_retries=0)
    with dspy.context(lm=lm, adapter=dspy.ChatAdapter(use_json_adapter_fallback=False)):
        optimizer = InstructionOnlyMIPRO(metric=lambda example, prediction, trace=None: prediction.score,
                                prompt_model=lm, task_model=lm, auto=None, num_candidates=3,
                                max_bootstrapped_demos=0, max_labeled_demos=0, num_threads=1,
                                max_errors=1, seed=42, log_dir=None)
        optimized = optimizer.compile(Student(), trainset=examples("proposal"), valset=examples("selection"),
                                      num_trials=4, minibatch=True, minibatch_size=4, minibatch_full_eval_steps=4,
                                      program_aware_proposer=False, data_aware_proposer=True,
                                      fewshot_aware_proposer=False)
    instruction = optimized.organize.signature.instructions
    experiment.candidate(instruction)
    keep(completed, {"optimizer": "dspy==3.5.0/MIPROv2", "seed": 42, "num_candidates": 3, "num_trials": 4,
                     "max_bootstrapped_demos": 0, "max_labeled_demos": 0, "instruction": instruction})
    return instruction
