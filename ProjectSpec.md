
# Patient Education Multi-Agent System — Requirements Specification

**Version:** 1.2
**Status:** Canonical (single source of truth)
**Audience:** Engineers, Cursor, AI Platform
**Domain:** Patient-facing medical education (non-clinical)
**Last Updated:** January 14, 2026

### Changelog
- v1.2: Added KB integration, thresholds, error handling, performance optimization, extended logging
- v1.1: Expanded agent_map with knowledge_base and model routing
- v1.0: Initial specification

---

## 0. How to Use This Document (IMPORTANT)

This file is the **only authoritative specification** for the system.

Rules:

* If a behavior is not explicitly allowed, assume it is **disallowed**
* Cursor should generate code **exactly** matching this spec
* Safety > completeness > convenience

---

## 1. System Goal

Build a **patient-facing, educational-only AI system** that answers medical questions using a **deterministic, multi-step pipeline**.

The system:

* Explains concepts
* Provides general education
* Supports informed discussion with clinicians

The system must **never**:

* Diagnose
* Recommend treatment
* Suggest medication changes
* Act like a clinician
* Track users over time

---

## 2. Core Design Invariants (NON-NEGOTIABLE)

These must hold in all implementations.

1. **Educational Only**
2. **Stateless Agents**
3. **Explicit Context Passing**
4. **Deterministic Orchestration**
5. **Validator Is Final Authority**
6. **Safe Abstention Is Allowed**
7. **Clarification Before Assumption**

Violating any invariant = non-compliant implementation.

---

## 3. High-Level Architecture

```
User Query
   ↓
Intent Extraction Agent
   ↓
(Clarification if needed)
   ↓
Patient Stage Identification Agent
   ↓
Category-Specific Reasoning Agent
   ↓
Inference Validator / Guardrails Agent
   ↓
Final Response
```

* Agents never call each other
* Agents never store state
* Orchestrator controls all flow

---

## 4. Execution Model

### 4.1 Orchestrator Responsibilities

The orchestrator:

* Receives user input
* Calls agents in fixed order
* Builds and passes context
* Handles clarification and abstention
* Returns the final response

Agents:

* Receive input
* Produce output
* Do nothing else

---

## 5. Context Model

### 5.1 Pipeline Context

```ts
interface PipelineContext {
  intent: IntentResult;
  stage: PatientStageResult;
  session_context?: SessionContext;
  pathway_context?: PathwayContext;
}
```

* Created fresh per request
* Immutable to agents
* Owned exclusively by orchestrator

---

### 5.2 Session Context (Optional, Read-Only)

```ts
interface SessionContext {
  conversation_id: string;
  turns: Array<{
    user_query: string;
    inferred_intent: string;
    inferred_stage: string;
  }>;
  created_at: timestamp;
  expires_at: timestamp;
}
```

Rules:

* Short-lived
* Never persisted beyond session
* Read-only to agents
* Never treated as truth

---

## 6. Intent Extraction

### 6.1 Purpose

Determine **what the user is asking about**, not medical meaning.

### 6.2 Intent Categories (Config-Driven)

```json
{
  "intent_categories": [
    "medication_info",
    "side_effects",
    "diet_nutrition",
    "symptom_management",
    "emotional_support",
    "logistics_navigation",
    "test_results_explanation",
    "treatment_overview",
    "lifestyle_activity",
    "unknown"
  ]
}
```

---

### 6.3 Input

```ts
{
  user_query: string;
  intent_categories: string[];
}
```

---

### 6.4 Output

```ts
interface IntentResult {
  primary_intent: string;
  confidence: number; // 0.0–1.0
  secondary_intents?: string[];
}
```

OR

```ts
interface IntentClarificationRequest {
  status: "clarification_required";
  question: string;
  options?: string[];
}
```

---

### 6.5 Rules

* Exactly one primary intent OR clarification
* If confidence < threshold → ask **one** clarification question
* Clarification must be:

  * Neutral
  * Non-medical
  * Intent-focused only
* Pipeline must **pause** until clarified
* If still unclear → intent = `unknown`

---

## 7. Patient Stage Identification

### 7.1 Purpose

Infer **where the user appears to be** in their medical journey, based only on text.

### 7.2 Allowed Stages

```json
{
  "patient_stages": [
    "pre_diagnosis",
    "awaiting_results",
    "newly_diagnosed",
    "active_treatment",
    "post_treatment",
    "surveillance",
    "palliative_support",
    "unknown"
  ]
}
```

---

### 7.3 Input

```ts
{
  user_query: string;
  intent: IntentResult;
  pathway_kb?: PathwayKnowledgeBase;
}
```

---

### 7.4 Output

```ts
interface PatientStageResult {
  stage: string;
  certainty: "high" | "medium" | "low";
  evidence_snippets: string[];
}
```

---

### 7.5 Rules

* Evidence must quote user text
* Stage inferred per request
* No reuse of prior stage inference
* If uncertain → `unknown`

---

## 8. Reasoning Agents

### 8.1 Purpose

Generate **educational content only**, tailored to intent and stage.

### 8.2 Routing (Intent → Agent → Knowledge Base)

```json
{
  "agent_map": {
    "diet_nutrition": {
      "agent": "NutritionEducationAgent",
      "knowledge_base": "nutrition_assistant",
      "model": "fast"
    },
    "medication_info": {
      "agent": "MedicationEducationAgent",
      "knowledge_base": "breast_cancer_knowledge",
      "model": "accurate"
    },
    "side_effects": {
      "agent": "SideEffectsEducationAgent",
      "knowledge_base": "breast_cancer_knowledge",
      "model": "accurate"
    },
    "symptom_management": {
      "agent": "SymptomEducationAgent",
      "knowledge_base": "breast_cancer_knowledge",
      "model": "accurate"
    },
    "emotional_support": {
      "agent": "SupportiveCareAgent",
      "knowledge_base": "breast_cancer_knowledge",
      "model": "fast"
    },
    "lifestyle_activity": {
      "agent": "LifestyleEducationAgent",
      "knowledge_base": "breast_cancer_knowledge",
      "model": "fast"
    },
    "treatment_overview": {
      "agent": "TreatmentEducationAgent",
      "knowledge_base": "breast_cancer_knowledge",
      "model": "accurate"
    },
    "test_results_explanation": {
      "agent": "TestResultsEducationAgent",
      "knowledge_base": "breast_cancer_knowledge",
      "model": "accurate"
    },
    "logistics_navigation": {
      "agent": "LogisticsAgent",
      "knowledge_base": null,
      "model": "fast"
    },
    "unknown": {
      "agent": "GeneralEducationAgent",
      "knowledge_base": "breast_cancer_knowledge",
      "model": "fast"
    }
  }
}
```

Notes:
* `model: "fast"` → Use Claude Haiku or equivalent for speed
* `model: "accurate"` → Use Claude Sonnet or equivalent for medical precision
* `knowledge_base: null` → No KB retrieval needed (general guidance only)

---

### 8.3 Input

```ts
{
  user_query: string;
  patient_context: PipelineContext;
}
```

---

### 8.4 Output

```ts
interface DraftAnswer {
  content: string;
  citations?: string[];
  limitations: string[];
}
```

---

### 8.5 Hard Constraints

* ❌ No “you should”
* ❌ No treatment advice
* ❌ No medication changes
* ❌ No assumptions
* ✅ Population-level phrasing only

---

### 8.6 Multi-Intent Handling

* Primary intent drives agent
* Secondary intents may be acknowledged
* Never silently drop secondary intent

---

## 9. Validator / Guardrails Agent

### 9.1 Purpose

Final safety enforcement.

### 9.2 Input

```ts
{
  draft_answer: DraftAnswer;
  intent: IntentResult;
  stage: PatientStageResult;
}
```

---

### 9.3 Output

```ts
interface ValidatedAnswer {
  final_text: string;
  safety_flags: string[];
  disclaimer_added: boolean;
}
```

OR

```ts
interface AbstentionResult {
  status: "abstained";
  reason: string;
  safe_response: string;
}
```

---

### 9.4 Validation Rules

Validator must ensure:

* No diagnosis
* No treatment advice
* No imperatives
* No prior-session references
* Plain, supportive language
* Educational framing only

---

### 9.5 Required Disclaimer

Append when medical content exists:

> “This information is educational and not a substitute for medical advice. For guidance specific to your situation, please consult your care team.”

---

## 10. Confidence-Based Behavior

* Low intent confidence → clarify or generalize
* Low stage certainty → avoid stage-specific claims
* Medium certainty → conditional phrasing
* Confidence must **never** increase claim strength

---

## 11. Abstention Rules

Agents must abstain if:

* Clinical judgment would be required
* Guardrails cannot be satisfied
* Clarification failed and safety is at risk

Fallback responses must:

* Acknowledge question
* State limitation
* Redirect to general education or care team

---

## 12. Orchestration Reference Logic

```ts
function answerPatientQuestion(query, sessionContext?) {
  intent = IntentAgent.run(query)

  if (intent.status === "clarification_required") {
    return intent
  }

  stage = StageAgent.run(query, intent)

  context = { intent, stage, session_context }

  draft = ReasoningAgent.run(query, context)

  validated = ValidatorAgent.run(draft, intent, stage)

  return validated
}
```

---

## 13. Knowledge Base Integration

### 13.1 Available Knowledge Bases

```json
{
  "knowledge_bases": {
    "breast_cancer_knowledge": {
      "description": "Medical leaflets and patient education materials",
      "content_type": "PDF chunks with page references",
      "use_cases": ["medication", "treatment", "side_effects", "symptoms"]
    },
    "nutrition_assistant": {
      "description": "Recipes and dietary advice for patients",
      "content_type": "Structured recipes and nutrition guidance",
      "use_cases": ["diet_nutrition", "lifestyle_activity"]
    }
  }
}
```

### 13.2 Retrieval Configuration

```ts
interface RetrievalConfig {
  index_name: string;
  search_type: "hybrid";  // vector + keyword
  min_chunks: number;     // Minimum chunks for evidence
  min_score: number;      // Relevance threshold
  max_chunks: number;     // Limit for context window
}
```

Default values by intent type:

| Intent Type | min_chunks | min_score | require_keyword |
|-------------|-----------|-----------|-----------------|
| Medical (medication, treatment, side_effects) | 2 | 2.0 | true |
| Nutrition (diet_nutrition) | 1 | 1.0 | false |
| General (emotional_support, lifestyle) | 1 | 1.5 | false |

### 13.3 Retrieval Flow

1. Orchestrator determines KB from agent_map
2. If `knowledge_base: null` → skip retrieval
3. Query KB using hybrid search (vector + keyword)
4. Pass retrieved chunks to Reasoning Agent
5. Reasoning Agent MUST cite sources in response

### 13.4 Pathway Knowledge Base (Future)

```ts
interface PathwayKnowledgeBase {
  pathway_name: string;
  stages: Record<string, string>;
  allowed_topics_per_stage: Record<string, string[]>;
}
```

Pathway-specific filtering is a future enhancement.

---

## 14. Logging & Observability (Summary)

Every step must log (see Section 20 for full schema):

```ts
{
  step_name: string;
  input_summary: string;
  output_summary: string;
  latency_ms: number;
  safety_flags?: string[];
  spec_version: string;
}
```

---

## 15. Testing Requirements

Must include tests for:

* Safety boundary violations
* Clarification flow
* Abstention behavior
* Memory leakage
* Overconfident stage inference

---

## 16. Explicit Non-Goals

* Persistent user memory
* EHR integration
* Clinical workflows
* Autonomous agent planning
* Tool calling
* Follow-up care logic

---

## 17. Confidence Thresholds

### 17.1 Intent Confidence Thresholds

```json
{
  "intent_thresholds": {
    "clarification_required": 0.6,
    "low_confidence": 0.7,
    "high_confidence": 0.85
  }
}
```

Behavior:
* `confidence < 0.6` → Request clarification from user
* `0.6 ≤ confidence < 0.7` → Proceed with hedged language
* `confidence ≥ 0.7` → Proceed normally
* `confidence ≥ 0.85` → High confidence, direct response

### 17.2 Stage Certainty Thresholds

```json
{
  "stage_thresholds": {
    "low": 0.5,
    "medium": 0.75,
    "high": 0.9
  }
}
```

Behavior:
* `certainty < 0.5` → Stage = "unknown", avoid stage-specific content
* `0.5 ≤ certainty < 0.75` → Use conditional phrasing ("if you are in treatment...")
* `certainty ≥ 0.75` → Can reference stage context
* `certainty ≥ 0.9` → Direct stage-appropriate content

---

## 18. Error Handling

### 18.1 Agent Failure Policy

```ts
interface ErrorPolicy {
  max_retries: number;           // 1
  retry_delay_ms: number;        // 500
  timeout_per_agent_ms: number;  // 30000
  fallback_on_failure: boolean;  // true
}
```

### 18.2 Failure Scenarios

| Scenario | Action |
|----------|--------|
| Intent Agent fails | Retry once, then classify as "unknown" |
| Stage Agent fails | Retry once, then set stage to "unknown" |
| Reasoning Agent fails | Retry once, then abstain with safe message |
| Validator Agent fails | Return draft answer WITH disclaimer (fail-open for safety) |
| KB Retrieval fails | Proceed without KB context, add disclaimer about limited info |
| Timeout exceeded | Abstain with "unable to process" message |

### 18.3 Safe Fallback Response

When the pipeline cannot complete:

```
"I'm sorry, I wasn't able to fully process your question. For accurate information, 
please speak with your healthcare team or call the support helpline at 0808 800 6000."
```

---

## 19. Performance Optimization

### 19.1 Parallelization

The following agents CAN run in parallel (no dependencies):
* Intent Agent ← depends only on user query
* Stage Agent ← depends only on user query (intent is informational, not blocking)

Updated flow:
```
User Query
   ↓
┌──────────────────────┐
│  Intent Agent        │  ← Run in parallel
│  Stage Agent         │  ← Run in parallel
└──────────────────────┘
   ↓
(Clarification if needed)
   ↓
Knowledge Base Retrieval
   ↓
Reasoning Agent
   ↓
Validator Agent
   ↓
Final Response
```

### 19.2 Model Selection

| Agent | Recommended Model | Rationale |
|-------|------------------|-----------|
| Intent Agent | Claude Haiku / fast | Simple classification task |
| Stage Agent | Claude Haiku / fast | Simple inference task |
| Reasoning Agent | Claude Sonnet / accurate | Complex generation with citations |
| Validator Agent | Claude Haiku / fast | Rule-based checking |

Expected latency:
* Without parallelization: ~8-12 seconds
* With Intent+Stage parallel: ~5-8 seconds

### 19.3 Caching (Optional)

Intent classification for identical queries MAY be cached for 5 minutes:
```ts
interface IntentCache {
  query_hash: string;
  result: IntentResult;
  cached_at: timestamp;
  ttl_seconds: 300;
}
```

Stage inference MUST NOT be cached (could change based on context).

---

## 20. Logging & Destinations

### 20.1 Log Structure (Extended)

```ts
interface PipelineLog {
  // Identification
  request_id: string;
  conversation_id?: string;
  timestamp: string;
  
  // Pipeline steps
  steps: Array<{
    step_name: string;
    agent_name: string;
    input_summary: string;
    output_summary: string;
    latency_ms: number;
    model_used?: string;
    safety_flags?: string[];
  }>;
  
  // Overall
  total_latency_ms: number;
  final_status: "success" | "clarification" | "abstained" | "error";
  spec_version: string;
}
```

### 20.2 Log Destinations

* **CloudWatch Logs**: All pipeline logs (default)
* **DynamoDB**: Conversation history (when session_context enabled)
* **Metrics**: Latency, error rates, abstention rates → CloudWatch Metrics

---

## 21. Cursor Implementation Directive (AUTHORITATIVE)

> Implement exactly what is specified here.
> Do not add memory, autonomy, or shortcuts.
> If unsure, choose the safer behavior.

---

**END OF REQUIREMENTS**

