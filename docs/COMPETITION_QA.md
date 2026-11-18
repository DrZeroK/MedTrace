# Competition Technical Q&A

**English** | [简体中文](COMPETITION_QA.zh-CN.md)

- Compiled on: 2026-11-17. Updated on: 2026-11-18: the Chinese Q&A now reproduces the organizer's original text verbatim, plus four supplementary organizer answers (Q10-Q13).
- Source: the organizer's full Q&A supplied by the project owner in conversation, plus the supplementary answers supplied on 2026-11-18. No original announcement URL, publication date, or version number was provided.
- Editorial approach: the Chinese Q&A text is reproduced verbatim from the organizer (only heading levels and Q numbering are normalized); the English version is a paragraph-by-paragraph translation with consistent headings and code formatting.
- Applicability: this document records the supplied answers. Subsequent unified technical specifications, actual API examples, and official evaluation configurations take precedence. This document does not certify that the repository implements or satisfies every requirement.

## Rules at a Glance

| Topic | Organizer's answer | Conditions or pending details |
|---|---|---|
| Local knowledge bases, rule bases, retrieval, and multi-stage algorithms | Permitted to bundle | Resources must be lawfully and compliantly sourced, version-pinned, bundled with the algorithm, and able to run independently offline |
| Resource registration | Required | Name, source, version, purpose, file size, and necessary dependencies; the registration template is provided by the organizing committee |
| Dependencies and deployment | Reasonable third-party dependencies are supported in principle | Complete dependency documentation required; package size and compatibility requirements pending |
| Official evaluation network | Only designated internal services are accessible | No public internet access or runtime online installation or downloading of resources |
| `seed` | May be passed at the top level of the request body | May be omitted with an explanation if unsupported; exact reproducibility is not guaranteed |
| vLLM automatic prefix caching | Native to the self-deployed service; centrally managed | No cachemark needs to be manually added to request input or output; planned to be disabled for official evaluation; final published environment configuration prevails |
| Reproducibility | Model version, inference framework, runtime environment, and evaluation conditions are unified; fixed random seed permitted within interface support | A fixed seed does not guarantee identical outputs; organizers guarantee consistent conditions and verifiable results, not word-for-word-identical generations; participants must pin their own code, dependency, and knowledge-resource versions and control internal randomness |
| Embedding models (e.g., BGE-M3) | Unified internal-network Embedding API planned on the Huawei Ascend stack | Self-deployment of embedding models requiring GPU/NPU not supported in principle; local knowledge bases and pre-built indexes may be submitted, size limits pending |
| Enterprise-track hardware | Model inference served by a unified Huawei Ascend stack deployment; participant algorithms run in an isolated CPU environment without direct GPU/NPU allocation | Python, rule computation, local retrieval, and lightweight computing allowed within resource limits; no additional self-deployed LLMs or GPU/NPU inference services; special CPU dependencies require advance declaration and compatibility assessment; OS, CPU, memory, storage, and runtime limits pending |
| Token, call, and runtime budgets | No explicit total token limit during the current development and testing stage | Official timeout, runtime, token, call, and retry limits pending; retries actively initiated by participant algorithms count toward the call budget |
| `temperature` and `response_format` | Participants permitted to set them independently in principle | Subject to the actual deployed version and unified interface specification |
| Thinking | Strategy-dependent selection permitted in principle | Controlled through `chat_template_kwargs`; omission uses the actual server-side default configuration |
| External third-party APIs | Prohibited | Includes commercial large models, online Embedding, and online retrieval; competition cases must not be uploaded to third-party platforms |
| Result filename | Not yet unified | Prechecks will accommodate `output.json` and `results.json` where possible; official submissions must follow the updated unified technical specification |

## 1. Knowledge Bases, Rule Bases, and Algorithm Deployment

### Q1. May medical knowledge bases, rule bases, and local retrieval modules be bundled?

Permitted. The competition encourages participants to adopt different technical approaches, including but not limited to Prompt Engineering, RAG, rule engines, multi-stage reasoning, Agent workflows, and so on.

Participants may integrate fixed versions of medical knowledge bases, rule bases, and local retrieval modules into the algorithm ZIP, provided that the relevant resources are lawfully and compliantly sourced, can run independently in the designated competition environment, and do not depend on external online services.

### Q2. How are knowledge materials registered?

At submission, register each resource's name, source, version, purpose, file size, and necessary runtime dependencies.

The organizing committee will provide a unified registration template. Teams that do not use additional knowledge bases or rule bases may simply state "None."

### Q3. What restrictions apply to algorithm package size, Python dependencies, and internet access?

Reasonable third-party Python dependencies and local retrieval and computation components are supported in principle.

Participants must provide complete dependency documentation (such as `requirements.txt`) to ensure that the solution can be deployed and run in the competition environment.

The upper limit on algorithm package size and dependency compatibility requirements will be clarified uniformly before official evaluation. For larger knowledge bases or special dependencies, participants are advised to communicate with the organizing committee in advance.

The official evaluation environment does not provide public internet access and permits calls only to the competition's designated internal services. During algorithm execution, additional dependencies or resources must not be downloaded or installed online.

## 2. Model Request Parameters and Evaluation Resources

### Q4. Is the seed parameter supported?

The competition uses a self-deployed vLLM model service. vLLM natively supports a request-level seed parameter, which can be passed directly at the top level of the HTTP JSON request body, for example, `"seed": 42`.

Participants may use a fixed random seed. If the actual interface does not support this field, it may be omitted and noted in the submission documentation; this will not be judged as a violation.

Note that a fixed seed helps improve reproducibility, but does not mean that model outputs will necessarily be completely identical under different runtime conditions.

### Q5. How are limits on tokens, call counts, timeouts, and retries set?

At the current development and testing stage, no explicit total token limit has been set.

In the official evaluation stage, based on the unified resource configuration, limits will be specified for the timeout of each model request, total runtime per case, token consumption, number of model calls, number of retries, and related items.

In principle, retries actively initiated by the participant's algorithm count toward the model-call budget; calls confirmed to be caused by faults of the competition platform itself will be handled under unified exception-handling rules.

Specific limits will be published uniformly before the official submission deadline, with time reserved for participants to adjust their solutions.

### Q6. May response_format and temperature be configured?

The self-deployed vLLM OpenAI-compatible interface natively supports temperature and, in supported versions, provides structured output capability through response_format, for example:

```json
{
  "temperature": 0.1,
  "response_format": {
    "type": "json_object"
  }
}
```

In principle, the competition permits participants to set the above parameters independently, subject to the actual deployed competition version and the unified interface specification.

For parameters that are prohibited or unsupported by the interface, explicit error messages will be provided where possible, to avoid misunderstanding caused by silent ignoring.

### Q7. How are Qwen Thinking parameters passed?

For services using vLLM's native OpenAI-compatible interface, Thinking can be disabled through the following field in the HTTP request body:

```json
{
  "chat_template_kwargs": {
    "enable_thinking": false
  }
}
```

If this field is not passed, the actual server-side default configuration is used. The default mode does not necessarily disable Thinking; the final behavior is subject to the model configuration published by the competition.

In principle, the competition permits participants to select the Thinking mode according to their algorithm strategy; specific support will be confirmed through unified interface examples.

## 3. External APIs and Data Security

### Q8. May commercial Qwen APIs or other third-party services be used?

This competition prohibits the use of any external third-party APIs.

The competition provides a unified self-deployed Qwen model service; participating algorithms should complete model inference through the competition's designated interface.

Calls to external commercial large models, online Embedding, online knowledge retrieval, or other third-party services are prohibited.

Neither the practice cases nor the official evaluation cases provided by the competition may be uploaded to external third-party platforms.

Participants may use local knowledge bases, rule bases, retrieval algorithms, and other offline components, but the relevant resources must be registered in advance, and must be able to run independently in the designated competition environment.

This rule is intended to safeguard data security, evaluation fairness, and result reproducibility.

## 4. Result Submission and Compatibility

### Q9. Should the result file be named output.json or results.json?

At present, the technical specification and submission materials are inconsistent in file naming. The organizing committee will revise them uniformly and clarify the final file naming and data structure requirements.

During the compatibility precheck stage, both naming conventions found in existing documents will be accommodated as far as possible, to avoid affecting participant testing due to documentation differences.

Official submissions should follow the updated unified technical specification.

## 5. Supplementary Answers: Inference Infrastructure and Runtime Environment

### Q10. On vLLM prefix caching and cachemark

The competition uses a self-deployed vLLM inference service. vLLM natively supports an automatic prefix caching mechanism; participants do not need to manually add a cachemark to the input or output of requests.

Whether prefix caching is enabled and its specific configuration are managed uniformly by the competition organizer; participants do not need to handle it themselves. For official evaluation, automatic prefix caching is planned to be disabled uniformly to reduce the influence of cache state on the evaluation process; the final published environment configuration prevails.

### Q11. On the reproducibility of inference results

We understand that during large-model inference, floating-point computation, concurrent scheduling, and inference optimization may introduce a certain degree of nondeterminism.

The competition will unify the model version, inference framework, runtime environment, and evaluation conditions, and permits participants to set a fixed random seed within the range supported by the interface.

It should be noted that a fixed random seed is not equivalent to a guarantee that model outputs will be completely identical. The competition primarily guarantees that evaluation conditions are consistent and results are verifiable, and does not require each generation to be identical word for word.

Participants only need to ensure that their own code, dependencies, and knowledge resources are pinned to fixed versions, and to reasonably control random behavior within their algorithms.

### Q12. On BGE-M3 and other Embedding models

Considering that the competition uses the Huawei Ascend technology stack, and to reduce deployment complexity and ensure evaluation fairness, the competition plans to provide a unified internal-network Embedding API.

Participants can generate vectors through the unified interface and implement knowledge base construction, vector retrieval, hybrid recall, and other RAG algorithm logic themselves.

In principle, participants are not supported in self-deploying Embedding models that require GPU/NPU resources. Submitting local knowledge bases and pre-built indexes is permitted; specific resource size limits will be published uniformly.

### Q13. On enterprise-track hardware and local inference

Enterprise-track model inference services are deployed uniformly on the Huawei Ascend technology stack.

Participating algorithms in principle run in an isolated CPU environment and are not directly allocated GPU/NPU resources.

Within the prescribed resource limits, participants may execute Python programs, rule computation, local retrieval, and other lightweight computing tasks.

Participants may not self-deploy and run additional large models or GPU/NPU inference services. Special CPU computing dependencies may be declared in advance for a compatibility assessment.

The specific operating system, CPU, memory, storage, and runtime limits will be clarified uniformly in the official evaluation environment specification.

## Items Awaiting Organizer Clarification

The following items were not finalized in this Q&A and must not be replaced with assumed official limits:

- Algorithm package size limit, Python dependency compatibility requirements, and resource registration template.
- Per-request timeout, total runtime per case, token consumption, model-call limits, and retry limits.
- How platform faults are confirmed and handled under the unified exception-handling rules.
- Actual model configuration, default Thinking mode, supported parameters, and unified API examples.
- Final result filename and data structure.
- Final evaluation environment configuration, including whether vLLM automatic prefix caching is disabled for official evaluation.
- Specification of the unified internal-network Embedding API, including endpoint, model name, vector dimensions, batching, and rate limits.
- Size limits for local knowledge bases and pre-built indexes submitted with the algorithm.
- Operating system, CPU, memory, storage, and runtime limits of the isolated CPU evaluation environment.

This Q&A does not specify the exact model name, ENDPOINT configuration method, complete input/output schemas, or exit-code rules. These items must be checked separately against the official technical specification.
