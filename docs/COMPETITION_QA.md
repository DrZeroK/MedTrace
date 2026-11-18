# Competition Technical Q&A

**English** | [简体中文](COMPETITION_QA.zh-CN.md)

- Compiled on: 2026-11-17. Updated on: 2026-11-18 with four supplementary organizer answers (Q10-Q13).
- Source: the organizer's full Q&A supplied by the project owner in conversation, plus the supplementary answers supplied on 2026-11-18. No original announcement URL, publication date, or version number was provided.
- Editorial approach: all questions and answers are translated into English, with consistent headings, paragraphs, and code formatting.
- Applicability: this document records the supplied answers. Subsequent unified technical specifications, actual API examples, and official evaluation configurations take precedence. This document does not certify that the repository implements or satisfies every requirement.

## Rules at a Glance

| Topic | Organizer's answer | Conditions or pending details |
|---|---|---|
| Local knowledge bases, rule bases, retrieval, and multi-stage algorithms | Permitted | Resources must be lawfully sourced, version-pinned, bundled with the algorithm, and able to run independently offline |
| Resource registration | Required | Name, source, version, purpose, file size, and necessary dependencies; registration template pending |
| Dependencies and deployment | Reasonable third-party dependencies are supported in principle | Complete dependency documentation required; package size and compatibility requirements pending |
| Official evaluation network | Only designated internal services are accessible | No public internet access or runtime online installation or downloading of resources |
| `seed` | May be passed at the top level of the request body | May be omitted with an explanation if unsupported; exact reproducibility is not guaranteed |
| vLLM automatic prefix caching | Native to the self-hosted service; centrally managed | No cache marker (`cachemark`) needed in request input or output; planned to be disabled for official evaluation; final published environment configuration prevails |
| Reproducibility | Model version, inference framework, runtime environment, and evaluation conditions are unified; fixed random seed permitted within interface support | A fixed seed does not guarantee identical outputs; organizers guarantee consistent conditions and verifiable results, not word-for-word-identical generations; participants must pin their own code, dependency, and knowledge-resource versions and control internal randomness |
| Embedding models (e.g., BGE-M3) | Unified internal-network embedding API planned on the Ascend stack | Self-deployment of embedding models requiring GPU/NPU not supported in principle; local knowledge bases and prebuilt indexes may be submitted, size limits pending |
| Enterprise-track hardware | Model inference served on a unified Huawei Ascend deployment; participant algorithms run in an isolated CPU environment without direct GPU/NPU allocation | Python, rule computation, local retrieval, and lightweight computing allowed within resource limits; no additional self-deployed LLMs or GPU/NPU inference services; special CPU dependencies require advance declaration and compatibility review; OS, CPU, memory, storage, and runtime limits pending |
| Token, call, and runtime budgets | No explicit total token limit during the current development and testing stage | Official timeout, runtime, token, call, and retry limits pending; participant-initiated retries count toward the call budget |
| `temperature` and `response_format` | Participant configuration permitted in principle | Subject to the deployed version and unified API specification |
| Thinking | Strategy-dependent selection permitted in principle | Controlled through `chat_template_kwargs`; omission uses the server default |
| External third-party APIs | Prohibited | Includes commercial models, online embedding, and online retrieval; competition cases must not be uploaded to third-party platforms |
| Result filename | Not yet unified | Prechecks will accommodate `output.json` and `results.json` where possible; final submissions must follow the updated specification |

## 1. Knowledge Bases, Rule Bases, and Algorithm Deployment

### Q1. May participants include medical knowledge bases, rule bases, and local retrieval modules?

Yes. The competition encourages different technical approaches, including but not limited to prompt engineering, RAG, rule engines, multi-stage reasoning, and agent workflows.

Participants may integrate fixed versions of medical knowledge bases, rule bases, and local retrieval modules into the algorithm ZIP package, provided that the resources are lawfully sourced, can run independently in the designated competition environment, and do not depend on external online services.

### Q2. How should knowledge resources be registered?

At submission, register each resource's name, source, version, purpose, file size, and necessary runtime dependencies.

The organizing committee will provide a unified registration template. Teams that do not use additional knowledge bases or rule bases should indicate "None."

### Q3. What restrictions apply to algorithm package size, Python dependencies, and internet access?

Reasonable third-party Python dependencies and local retrieval and computation components are supported in principle.

Participants must provide complete dependency documentation, such as `requirements.txt`, and ensure that their solution can be deployed and run in the competition environment.

The algorithm package size limit and dependency compatibility requirements will be clarified uniformly before official evaluation. Teams planning to use large knowledge bases or special dependencies are advised to contact the organizing committee in advance.

The official evaluation environment will not provide public internet access. Only designated internal competition services may be called. Algorithms must not install or download additional dependencies or resources online during execution.

## 2. Model Request Parameters and Evaluation Resources

### Q4. Is the seed parameter supported?

The competition uses a self-hosted vLLM model service. vLLM natively supports a request-level seed parameter, which can be passed directly at the top level of the HTTP JSON request body, for example, `"seed": 42`.

Participants may use a fixed random seed. If the actual API does not support this field, participants may omit it and explain the omission in their submission documentation; this will not be considered a violation.

A fixed seed helps improve reproducibility but does not guarantee identical model outputs under different runtime conditions.

### Q5. What limits apply to tokens, model calls, timeouts, and retries?

At the current development and testing stage, no explicit total token limit has been set.

For official evaluation, the organizers will define limits based on the shared resource configuration, including the timeout for each model request, total runtime per case, token consumption, number of model calls, and number of retries.

In principle, retries initiated by a participant's algorithm count toward the model-call budget. Calls confirmed to have been affected by faults in the competition platform itself will be handled under unified exception-handling rules.

Specific limits will be published before the final submission deadline, with time reserved for participants to adjust their solutions.

### Q6. May participants configure response_format and temperature?

The self-hosted vLLM OpenAI-compatible API natively supports temperature and, in supported versions, structured output through response_format, for example:

```json
{
  "temperature": 0.1,
  "response_format": {
    "type": "json_object"
  }
}
```

In principle, participants may configure these parameters themselves. Final support is subject to the deployed competition version and unified API specification.

For prohibited or unsupported parameters, the organizers will try to provide explicit error messages to avoid misunderstandings caused by silently ignored parameters.

### Q7. How should Qwen Thinking parameters be passed?

For services using vLLM's native OpenAI-compatible API, Thinking can be disabled through the following field in the HTTP request body:

```json
{
  "chat_template_kwargs": {
    "enable_thinking": false
  }
}
```

If this field is omitted, the service uses its actual server-side default configuration. The default does not necessarily disable Thinking; the model configuration published by the competition determines the behavior.

In principle, participants may select a Thinking mode according to their algorithm strategy. Specific support will be confirmed through unified API examples.

## 3. External APIs and Data Security

### Q8. May participants use commercial Qwen APIs or other third-party services?

The competition prohibits all external third-party APIs.

The competition provides a unified, self-hosted Qwen model service. Participating algorithms must perform model inference through the designated competition API.

Calls to external commercial large language models, online embedding services, online knowledge retrieval, or other third-party services are prohibited.

Neither practice cases nor official evaluation cases supplied by the competition may be uploaded to external third-party platforms.

Participants may use local knowledge bases, rule bases, retrieval algorithms, and other offline components, provided that the resources are registered in advance and can run independently in the designated competition environment.

This rule is intended to protect data security, evaluation fairness, and reproducibility.

## 4. Result Submission and Compatibility

### Q9. Should the result file be named output.json or results.json?

The technical specification and submission materials currently use inconsistent filenames. The organizing committee will revise them uniformly and clarify the final filename and data structure requirements.

During compatibility prechecks, the organizers will accommodate both filenames found in existing documents where possible, to avoid disrupting participant testing because of documentation differences.

Official submissions must follow the updated unified technical specification.

## 5. Inference Infrastructure and Runtime Environment

### Q10. Does the self-hosted vLLM service use prefix caching, and must participants add a cachemark?

The competition uses a self-hosted vLLM inference service. vLLM natively supports automatic prefix caching; participants do not need to manually add any cache marker (`cachemark`) to the input or output of requests.

Whether prefix caching is enabled and its specific configuration are managed centrally by the organizing committee; participants do not need to handle it themselves. For official evaluation, automatic prefix caching is planned to be disabled uniformly to reduce the influence of cache state on the evaluation process. The final published environment configuration prevails.

### Q11. How reproducible are inference results, and what does a fixed random seed guarantee?

The organizers understand that floating-point computation, concurrent scheduling, and inference optimizations may introduce a degree of nondeterminism into large-model inference.

The competition will unify the model version, inference framework, runtime environment, and evaluation conditions, and permits participants to set a fixed random seed within the range supported by the interface.

It should be noted that a fixed random seed is not equivalent to a guarantee that model outputs will be completely identical. The competition primarily guarantees that evaluation conditions are consistent and results are verifiable; it does not require each generation to be identical word for word.

Participants only need to ensure that their own code, dependencies, and knowledge resources are pinned to fixed versions, and to reasonably control random behavior inside their algorithms.

### Q12. May participants self-deploy BGE-M3 or other embedding models?

Considering that the competition uses the Huawei Ascend technology stack, and to reduce deployment complexity and ensure evaluation fairness, the organizers plan to provide a unified internal-network embedding API. Participants can generate vectors through this unified interface and implement knowledge base construction, vector retrieval, hybrid recall, and other RAG algorithm logic themselves.

In principle, participants are not supported in self-deploying embedding models that require GPU/NPU resources. Submitting local knowledge bases and prebuilt indexes is permitted; the specific resource size limits will be published uniformly.

### Q13. What hardware is available in the enterprise track, and may participants run local inference?

Model inference in the enterprise track is deployed uniformly on the Huawei Ascend technology stack.

Participant algorithms in principle run in an isolated CPU environment and are not directly allocated GPU/NPU resources. Within the prescribed resource limits, participants may run Python programs, rule computation, local retrieval, and other lightweight computing tasks.

Participants may not deploy or run additional self-hosted large models or GPU/NPU inference services. Special CPU computing dependencies may be declared in advance for a compatibility assessment.

The specific operating system, CPU, memory, storage, and runtime limits will be specified uniformly in the official evaluation environment specification.

## Items Awaiting Organizer Clarification

The following items were not finalized in this Q&A and must not be replaced with assumed official limits:

- Algorithm package size limit, Python dependency compatibility requirements, and resource registration template.
- Per-request timeout, total runtime per case, token consumption, model-call limits, and retry limits.
- How platform faults are confirmed and handled under the unified exception-handling rules.
- Actual model configuration, default Thinking mode, supported parameters, and unified API examples.
- Final result filename and data structure.
- Final evaluation environment configuration, including whether vLLM automatic prefix caching is disabled for official evaluation.
- Specification of the unified internal-network embedding API, including endpoint, model name, vector dimensions, batching, and rate limits.
- Size limits for local knowledge bases and prebuilt indexes submitted with the algorithm.
- Operating system, CPU, memory, storage, and runtime limits of the isolated CPU evaluation environment.

This Q&A does not specify the exact model name, ENDPOINT configuration method, complete input/output schemas, or exit-code rules. These items must be checked separately against the official technical specification.
