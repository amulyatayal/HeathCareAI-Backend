# Stage Classification & Orchestration Architecture (V2)

**Version**: 2.1  
**Date**: 2026-02-01 (Design) | 2026-02-09 (Implemented) | 2026-02-10 (Refactored)  
**Status**: ✅ V2.0 Implemented + V2.1 Implemented & Verified + Codebase Refactored  

## 1. Overview
This document details the refactored architecture for identifying and confirming a patient's treatment stage in the app 

The V2 architecture shifts from a proposal-card-based, embedding-heavy approach to a **Natural Language Chat-Based Confirmation** flow driven by a specialized LLM agent (`StageAgentV2`). This simplifies the user experience and consolidates orchestration logic.

## 2. Core Architecture Components

### 2.1 Pipeline Orchestrator (`orchestrator.py`)
The central brain of the system. It replaces the separate `PathwayOrchestrator`.
- **Responsibilities**:
  - Manages parallel execution of `IntentAgent` and `StageAgentV2`.
  - Determines when to trigger a stage confirmation workflow.
  - Handles the **Stateless Loop Prevention** logic to avoid repetitive prompting.
  - Updates the `PatientProfile` upon user confirmation.

### 2.2 StageAgentV2 (`stage_agent_v2.py`)
A fast, "Pure Function" LLM agent.
- **Model**: Anthropic Claude 3 Haiku (or similar fast model).
- **Input**: Current User Message + Conversation History (last 3-5 turns).
- **Output**: `StageResult` containing:
  - `stage`: Inferred High-Level Stage (e.g., `ACTIVE_TREATMENT`)
  - `certainty`: HIGH, MEDIUM, LOW
  - `signals`: List of strings explaining why (e.g., "User mentioned 'surgery yesterday'").
- **Logic**: It does **not** check the user's profile. It relies solely on the conversation content to infer the *apparent* stage.

### 2.3 PatientStageService (`patient_stage_service.py`)
The unified data service for stage definitions.
- **Responsibilities**:
  - Loads stage hierarchy from JSON/CSV.
  - Provides RAG Context (`get_rag_context`): Generates rich descriptions, breadcrumbs, and next steps for the `ReasoningAgent`.
  - Maps detailed IDs (`2.1.1`) to High-Level Enums (`ACTIVE_TREATMENT`).
  - Stores Response Guidelines (Tone, Emphasis, Avoidance rules).

## 3. The Stage Confirmation Workflow

The system uses a chat-based confirmation loop instead of UI cards.

### 3.1 Detection Phase
1. **User Message**: "I just had my mastectomy." (Profile: `PRE_DIAGNOSIS`)
2. **Parallel Inference**: `Orchestrator` runs `IntentAgent` and `StageAgentV2`.
3. **Stage Mismatch**: 
   - `StageAgentV2` returns `stage=ACTIVE_TREATMENT`, `certainty=HIGH`.
   - `Orchestrator` compares with `Profile.current_stage` (`PRE_DIAGNOSIS`).
   - Mismatch Detected.

### 3.2 Loop Prevention & Decision
The `Orchestrator` inspects the **Conversation History** (specifically the last Assistant message).

**Case A: First Detection (No previous Question)**
- **Action**: **Interrupt Pipeline**.
- **Response**: "It sounds like you might be in the **Mastectomy** stage based on what you said. Is that correct?"
- **State**: No profile update yet.

**Case B: User Confirms ("Yes", "Correct")**
- **Condition**: History shows Assistant asked "Is that correct?" AND User says "Yes" (detected via `startswith` for flexibility).
- **Action**: **Update Profile**.
  - Persists BOTH `current_stage` and `detailed_stage_id` to prevent session loops.
  - Maps internal IDs to user-friendly **Broad Categories** (e.g., "Active Treatment") for display.
- **Context Preservation**: The Orchestrator extracts the *original question* from conversation history (the message that triggered the proposal) and re-runs the pipeline with it. This ensures the user gets their answer immediately after confirming, rather than being asked to repeat themselves.
- **Response**: "Thanks, I've updated your stage to **Active Treatment**. [Answer to original question...]"

**Case C: User Ignores/Negates ("What is the weather?", "No")**
...
...


## 4. Guest vs. Authenticated Users

| Feature | Authenticated User | Guest User |
| :--- | :--- | :--- |
| **Stage Source** | `PatientProfile` (Database) | None (Transient) |
| **Inference** | `StageAgentV2` runs | `StageAgentV2` runs |
| **Confirmation** | Prompted if Mismatch | **Never Prompted** |
| **Context** | Persistent Profile + Override | Transient Inferred Stage (Single Turn) |

For Guests, the system uses the `StageAgentV2` result *for that specific turn only* to personalize the response, but never interrupts the flow to ask for confirmation.

## 5. Integration with Reasoning Agent

The `ReasoningAgent` (which generates the final medical answer) relies on `PatientStageService` for context.

- **Input**: `context.stage_result` (Confirmed or Inferred).
- **Process**: 
  - Calls `PatientStageService.get_rag_context(stage_id)`.
  - Receives text block: `CURRENT STAGE: Mastectomy (2.1)... Journey: Surgery -> Mastectomy...`
  - Injects this into the System Prompt.
- **Outcome**: The answer is personalized (e.g., "Recovery from mastectomy typically takes...") without hard-coding medical knowledge in the prompt.

## 6. Deprecated & Removed Components
- **`PathwayOrchestrator`**: Removed. Logic moved to `PipelineOrchestrator`.
- **`StageClassifierAgent` (Embedding-based)**: Removed. Replaced by LLM `StageAgentV2`.
- **`stage_embeddings.json`**: No longer needed.
- **Proposal Cards**: Replaced by Chat Confirmation.

## 7. Key Architectural Improvements

### 7.1 Simplified User Experience
- **Before**: User sees a proposal card, must click "Accept" or "Ignore"
- **After**: Natural conversation flow with inline confirmation

### 7.2 Stateless Loop Prevention
- Uses conversation history inspection to avoid asking the same question repeatedly
- Handles user negation gracefully

### 7.3 Consolidated Orchestration
- Single `PipelineOrchestrator` instead of separate orchestrators
- Clearer separation of concerns between agents

### 7.4 Guest User Support
- Guests get personalized responses without authentication friction
- No profile updates or confirmation prompts for guests

## 8. Migration from V1

### What Changed
1. **Stage Detection**: Embedding-based classifier → LLM-based `StageAgentV2`
2. **Confirmation**: UI Proposal Cards → Natural language chat
3. **Orchestration**: `PathwayOrchestrator` + `PipelineOrchestrator` → Single `PipelineOrchestrator`
4. **Context Generation**: Moved to `PatientStageService.get_rag_context()`

### Files Deleted
- `services/pathway_orchestrator.py`
- `services/agents/stage_classifier.py`
- `services/agents/stage_agent.py` (old LLM version)
- `tests/unit/test_pathway_orchestrator.py`
- `tests/unit/test_stage_classifier.py`
- `tests/integration/test_proposal_flow.py`

### Files Modified
- `services/agents/orchestrator.py` - Added PHASE 1.5 for stage confirmation
- `services/agents/stage_agent_v2.py` - Enhanced with conversation history
- `services/patient_stage_service.py` - Added `get_rag_context()` and `map_to_high_level()`
- `services/agents/reasoning_agent.py` - Updated to use `PatientStageService`

## 9. Testing

### Integration Tests
- `tests/integration/test_stage_personalization.py` - Validates stage context in prompts
- `scripts/verify_integration.py` - End-to-end confirmation flow testing

### Test Scenarios Covered
1. First stage proposal (interrupt pipeline)
2. User confirmation ("Yes") → Profile update
3. User negation/ignore → Skip update

## 11. Incremental Fixes & Refinements (Post-V2 implementation)

### 11.1 Broad Category Display Mapping
To align with the onboarding experience, the system now maps granular internal IDs (e.g., `2.1.2`) to high-level display names (e.g., "Active Treatment") in all user-facing confirmation and proposal messages.

### 11.2 Flexible Confirmation Detection
Confirmation detection now uses `message.startswith(word)` instead of exact string matching. This allows users to provide compound affirmations like *"yes, please tell me more about recovery"* without breaking the flow.

### 11.3 Clarification Integration
If a confirmation message (e.g., "yes") is too short to determine intent, the system triggers a clarification request. The stage update confirmation is now explicitly prepended to these clarification requests so the user knows their profile was updated successfully.

### 11.4 Context Preservation (Original Question Carry-over)
A major UX refinement: After a user says "yes" to a stage update, the system automatically retrieves the message sent *before* the "yes" and uses it as the query for the RAG pipeline. This prevents "context loss" where the bot would otherwise forget what the user was originally asking about.

## 12. Journey Engine Enhancements (V2.1) ✅

**Status**: Ready for Implementation  
**Complete Guide**: See [MASTER_IMPLEMENTATION_GUIDE.md](../../brain/1b6f90f7-8562-4d42-8a70-f1687c2c1e32/MASTER_IMPLEMENTATION_GUIDE.md)

### 12.1 Overview

V2.1 enhances the V2 architecture with **CSV-aligned progression**, **verification questions**, **safety triggers**, and **improved patient tracking** — all without breaking existing V2.0 components.

**Key Metrics**:
- **Files Modified**: 8 files
- **New Code**: ~755 LOC
- **Implementation Time**: 14-18 hours
- **Backward Compatible**: ✅ 100%

### 12.2 Core Enhancements

#### 59 Detailed Sub-Stages
- Full hierarchical journey from `BreastCancerStagesProcessed.csv`
- 11 stage groups (0-10) with 59 granular stages
- Most detailed: Surgery (Group 2) with 18 sub-stages
- Examples: `2.1.1` (Lumpectomy), `2.2.2` (Mastectomy with Implant Reconstruction)

#### Verification Questions
- **Source**: CSV "Patient Facing Questions" column
- **Field**: `TreatmentStage.verification_questions: List[str]`
- **Usage**: Added to orchestrator Phase 1.5 stage confirmation
- **Example**: 
  ```
  "It sounds like you might be in the Surgery stage.
   Have you been scheduled for a lumpectomy or mastectomy? Is that correct?"
  ```

#### Safety Triggers (Simplified)
- **Design**: General keyword list for chat escalation
- **Field**: `TreatmentStage.safety_triggers: List[str]`
- **Keywords**: `fever`, `bleeding`, `severe pain`, `infection`, `swelling`, etc.
- **NOT included** (user-requested simplification):
  - ❌ Severity levels (CRITICAL/HIGH/MEDIUM)
  - ❌ Stage-aware filtering
  - ❌ Expected symptoms field
- **Usage**: Orchestrator Phase 0 pre-check adds safety context for reasoning agent

#### Geo-Aware Emergency Numbers
- **Countries**: UK (999/111), US (911/811)
- **Profile Fields**: `country_code`, `region`
- **Default**: UK (primary deployment)

#### Enhanced Patient Profile (13 new fields)
- **Geo-awareness** (2): `country_code`, `region`
- **Stage certainty** (3): `current_stage_certainty`, `detailed_stage_certainty`, `last_verification_at`
- **Regression/Recurrence** (5): `has_recurrence`, `is_regression_detected`, `treatment_phases_completed`, etc.
- **Guest conversion** (3): `was_guest`, `guest_interactions_count`

#### Regression Detection
- **Logic**: CSV stage group comparison
- **Type 1 - Recurrence**: Survivorship (Group 5) → Treatment groups
- **Type 2 - New Primary**: Post-treatment (Groups 7-10) → Early stages (0-1)

#### Orchestrator Integration
- **Phase 0**: Safety trigger pre-check (adds context, doesn't short-circuit)
- **Phase 1.5**: Verification questions in stage confirmation

### 12.3 User Experience: Before & After

#### Example 1: Verification Question Flow

**BEFORE (V2.0)**:
```
User: "I'm scheduled for a lumpectomy next week."
Bot: [Generic lumpectomy info]
```

**AFTER (V2.1)**:
```
User: "I'm scheduled for a lumpectomy next week."
Bot: "It sounds like you might be in the Lumpectomy stage.

      Have you been scheduled for breast-conserving surgery? Is that correct?"
      
User: "Yes!"
Bot: "✅ Updated your stage to Surgery (Lumpectomy)
     
     [Stage-specific lumpectomy information]"
```

**Improvements**:
- ✅ CSV-sourced verification question
- ✅ User confirms before profile update
- ✅ Detailed sub-stage tracking (2.1.1)

#### Example 2: Safety Trigger Detection

**BEFORE (V2.0)**:
```
User: "I have a fever and the surgical site looks red"
Bot: [Generic post-surgical care info]
```

**AFTER (V2.1)**:
```
User: "I have a fever and the surgical site looks red"
Bot: "⚠️ I noticed you mentioned fever and redness at your surgical site.

     These symptoms may require medical attention. Please contact your 
     care team today. For urgent concerns, call NHS 111. For emergencies, 
     call 999.
     
     [Educational content about post-surgical healing]"
```

**Improvements**:
- ✅ Safety triggers detected (fever, redness)
- ✅ UK emergency numbers (999/111)
- ✅ Safety guidance prioritized
- ✅ Educational content still provided

#### Example 3: Recurrence Detection

**BEFORE (V2.0)**:
```
User (Profile: Surveillance): "Starting chemo again for recurrence"
Bot: [Updates to Active Treatment, no empathy adjustment]
```

**AFTER (V2.1)**:
```
User (Profile: Early Survivorship - 5.1): "Starting chemo again"
[System detects: Group 5 → Group 8 = Recurrence]

Profile updated:
  - is_regression_detected = True
  - has_recurrence = True
  - recurrence_date = now

Bot: "I'm sorry to hear about your recurrence. I know this must be 
     incredibly difficult, especially after reaching survivorship.
     
     [Recurrence-aware, empathetic treatment information]"
```

**Improvements**:
- ✅ Automatic recurrence detection
- ✅ Profile flags set
- ✅ Extra empathy in response

### 12.4 Implementation Plan

**14 Steps Across 6 Phases**:

1. **Phase 1**: Model enhancements (Steps 1-2)
2. **Phase 2**: Build script & CSV processing (Steps 3-5)
3. **Phase 3**: Service enhancements (Steps 6-9)
4. **Phase 4**: Profile service updates (Step 10)
5. **Phase 5**: Orchestrator integration (Step 11)
6. **Phase 6**: Testing & validation (Steps 12-14)

**Files Modified**:
- Models: `patient_stages.py`, `patient_profile.py`
- Build: `scripts/stage_hierarchy/build.py`
- Services: `patient_stage_service.py`, `patient_profile_service.py`, `agents/orchestrator.py`
- Tests: `tests/test_journey_enhancements.py` (NEW)
- Data: `data/stage_hierarchy.json` (regenerated)

### 12.5 Agent Compatibility

**✅ Fully Compatible** - No breaking changes required:

| Agent | Changes Needed | Notes |
|-------|----------------|-------|
| StageAgentV2 | ✅ None | Auto-loads enhanced stages from service |
| IntentAgent | ✅ None | No stage data used |
| RetrievalAgent | ✅ None | No stage data used |
| ReasoningAgent | ✅ None | Can optionally add safety context |
| ValidatorAgent | ✅ None | Can optionally verify safety guidance |
| **Orchestrator** | ⚠️ **2 additions** | Safety pre-check + verification questions |

**Why Compatible**:
- StageAgentV2 calls `PatientStageService.get_all_stages()` which returns enhanced `TreatmentStage` objects
- New fields ignored by existing code
- Pydantic models handle missing fields gracefully

### 12.6 Excluded from V2.1 (Deferred to V2.2)

❌ **Analytics Infrastructure**
- `StageMismatch` DynamoDB table
- Mismatch logging in orchestrator
- Weekly analysis cron jobs
- Quality dashboards

**Rationale**: Focus V2.1 on core enhancements, defer analytics to future version.

### 12.7 Design Alignment

✅ **Maintains V2 Architecture**:
- LLM-based stage inference (StageAgentV2) unchanged
- Chat-based confirmation flow enhanced (not replaced)
- Pipeline orchestrator enhanced (2 small additions)
- PatientStageService enhanced (2 new methods)
- Stateless loop prevention unchanged

✅ **Maintains ProjectSpec.md Compliance**:
- Educational only (no medical diagnosis)
- Explicit context passing
- Rule-based safety checks (keyword matching)
- Safe abstention via verification questions

### 12.8 V2.1 Implementation Status (2026-02-09)

✅ **Completed & Verified**

#### Key Changes from Original Design

1. **Monkey-Patch → API Route**: The original design used `activate_v2_1_features()` to monkey-patch `PipelineOrchestrator.process`. This caused a `Content-Length RuntimeError` because response modification happened after FastAPI serialization. **Fix**: Moved V2.1 logic to `api/routes.py` (`_handle_v2_1_verification`). The monkey-patch in `main.py` is disabled.

2. **Granular Stage Name in Prompts**: The confirmation prompt "It sounds like you might be in the **Active Treatment** stage" was incorrect — it used the broad `PatientStage` enum display name. **Fix**: `orchestrator.py` now uses `get_patient_stage_service().get_stage_by_id(granular_id).name` to show specific names (e.g., "Wide local excision", "Chemotherapy").

3. **RAG Context Cleanup**: Removed technical stage IDs (e.g., "2.1.1.1") from the LLM's RAG context in `patient_stage_service.py`. Added treatment phase (root node name) instead for better personalization.

#### Bugs Resolved

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| Always shows "Active Treatment" | `stage_display_names.get(inferred.stage)` maps broad enum | Lookup granular name from `stage_hierarchy.json` |
| Content-Length RuntimeError | Monkey-patch modified response after serialization | Move logic to API route level |
| Literal `\n` in questions | Double-escaped `"\\n"` | Corrected to `"\n"` |
| Stage IDs in LLM context | `get_rag_context()` included `stage.stage_id` | Removed ID, added treatment phase name |

#### Eval Results

V2.1 granular flows verified with `tests/eval_v2_1_flows.py` (13 test cases).
Quick run (5 cases): **80% V2.1 activation rate** — 4/5 responses returned granular sub-stage IDs.

### 12.9 References

**Authoritative Documents**:
- 📘 [MASTER_IMPLEMENTATION_GUIDE.md](../../brain/1b6f90f7-8562-4d42-8a70-f1687c2c1e32/MASTER_IMPLEMENTATION_GUIDE.md) - Complete V2.1 guide with decisions, UX examples, and implementation steps
- 📋 [implementation_sequence.md](../../brain/1b6f90f7-8562-4d42-8a70-f1687c2c1e32/implementation_sequence.md) - Step-by-step implementation sequence
- 📊 [agent_compatibility_v2.md](../../brain/1b6f90f7-8562-4d42-8a70-f1687c2c1e32/agent_compatibility_v2.md) - Agent integration analysis
- 📝 [stages_journey_notes.md](stages_journey_notes.md) - Detailed decision rationale

**CSV Source**:
- `data/Breast cancer stages/Knowledge Base Bank - BreastCancerStagesProcessed.csv` (59 stages, canonical)

---

## 13. Future Improvements (V2.2+)
- **Multi-Turn Persuasion**: If a user consistently mentions symptoms of a different stage but ignores prompts, gently resurface the suggestion after N turns.
- **Guest-to-Auth Upgrade**: If a Guest confirms a stage (implicitly), prompt them to "Sign Up to save this info".
- **Granular Sub-Stage Detection**: Improve `StageAgentV2` prompt to distinguish between very similar sub-stages (e.g., "Lumpectomy" vs "Mastectomy") with higher precision using detailed definitions.
- **Confidence Calibration**: Track confirmation accuracy to fine-tune certainty thresholds.
- **ML-based Safety Detection**: Upgrade from keyword matching to NLP-based context understanding for safety triggers.
- **Analytics Infrastructure**: `StageMismatch` DynamoDB table, mismatch logging, weekly analysis cron jobs, quality dashboards.

## 14. Codebase Refactoring & File Reorganization (2026-02-10)

**Status**: ✅ Completed  
**Rollback**: `git tag pre-file-reorg-stable`

### 14.1 Problem Statement

The codebase had accumulated confusing naming conventions:
- Files labeled `_deprecated` (e.g., `schemas_deprecated.py`, `routes_deprecated.py`) were **actively used** by 6+ modules
- `schemas.py` and `routes.py` gave no indication of *what domain* they served
- V1/V2 labeling was misleading — the "deprecated" files were actually the **RAG/Chat** layer, while `schemas.py`/`routes.py` were the **pipeline** layer
- An early attempt to archive these files to `_archive/` broke 19 import statements across the codebase

### 14.2 Root Cause Analysis

| File | Label Implied | Actual Purpose |
|------|--------------|----------------|
| `models/schemas_deprecated.py` | Old, unused | **Active** RAG/chat models (ChatRequest, ChatResponse, KnowledgeDocument, SourceCitation) |
| `models/schemas.py` | Current, general | Pipeline-specific models (PipelineContext, IntentResult, StageResult, PipelineResponse) |
| `api/routes_deprecated.py` | Old, unused | **Active** RAG routes: chat, knowledge, health, categories (4 routers) |
| `api/routes.py` | Current, general | Pipeline routes: pipeline, health_v2, debug (3 routers) |

### 14.3 Solution: Domain-Based Naming

Renamed all files by **purpose/domain** instead of version:

#### Models

| Before | After | Contents |
|--------|-------|----------|
| `models/schemas_deprecated.py` | `models/schemas_rag.py` | ChatRequest, ChatResponse, SourceCitation, KnowledgeDocument, KnowledgeSearchRequest, FeedbackRequest, HealthCheckResponse, QueryCategory, ContentType, MessageRole |
| `models/schemas.py` | `models/schemas_pipeline.py` | PipelineRequest, PipelineResponse, PipelineContext, IntentResult, StageResult, ReasoningResult, RetrievalResult, ValidationResult, AgentTrace, AgentStatus |

#### Routes

| Before | After | Routers |
|--------|-------|---------|
| `api/routes_deprecated.py` | `api/routes_chat.py` | `chat_router` — POST /chat, POST /chat/feedback, DELETE /chat/session/{id} |
| `api/routes_deprecated.py` | `api/routes_knowledge.py` | `knowledge_router` — POST /knowledge/search, POST/DELETE /knowledge/document, GET /knowledge/stats, GET /knowledge/indexes; `categories_router` — GET /categories/query, GET /categories/content |
| `api/routes_deprecated.py` | `api/routes_health.py` | `health_router` — GET /health, GET /health/ping |
| `api/routes.py` | `api/routes_pipeline.py` | `pipeline_router`, `health_v2_router`, `debug_router` + V2.1 verification logic |

### 14.4 Import Updates (21 statements across 17 files)

**RAG schema imports** (`schemas_deprecated` → `schemas_rag`):
- `models/__init__.py`
- `services/ai_agent.py`
- `services/knowledge_base.py`
- `scripts/opensearch/ingest_csv_to_opensearch.py`
- `scripts/opensearch/ingest_qa_data.py`

**Pipeline schema imports** (`models.schemas` → `models.schemas_pipeline`):
- `api/routes_pipeline.py`
- `services/agents/base_agent.py`
- `services/agents/intent_agent.py`
- `services/agents/stage_agent_v2.py`
- `services/agents/retrieval_agent.py`
- `services/agents/reasoning_agent.py`
- `services/agents/validator_agent.py`
- `services/agents/video_retrieval_agent.py`
- `services/agents/orchestrator.py`
- `scripts/stage_hierarchy/verify_integration.py` (2 imports)
- `tests/stage_classification/test_int_stage_personalization.py`
- `tests/stage_classification/test_stage_agent.py`

**Route imports** (`api/__init__.py`):
```diff
-from .routes_deprecated import (chat_router, knowledge_router, health_router, categories_router)
-from .routes import (pipeline_router, health_v2_router, debug_router)
+from .routes_chat import chat_router
+from .routes_knowledge import knowledge_router, categories_router
+from .routes_health import health_router
+from .routes_pipeline import pipeline_router, health_v2_router, debug_router
```

### 14.5 Other Refactoring (Pre-Reorg)

| Change | Details |
|--------|---------|
| Build script fix | Updated `scripts/stage_hierarchy/build.py` CSV path |
| Test file relocation | Moved eval/test files to `tests/stage_classification/` |
| V2.1 extension consolidation | Merged `v2_1_extensions.py` functions into main service classes |
| Dead code removal | Deleted unused files identified via import analysis |
| Import verification | Validated all imports after each change |

### 14.6 Current File Structure (Post-Refactoring)

```
models/
├── __init__.py              # Re-exports from schemas_rag
├── schemas_rag.py           # RAG/Chat domain models
├── schemas_pipeline.py      # Pipeline domain models
├── patient_profile.py       # Patient profile model
└── patient_stages.py        # TreatmentStage model

api/
├── __init__.py              # Central router wiring
├── routes_chat.py           # Chat, feedback, session endpoints
├── routes_knowledge.py      # Knowledge search, documents, indexes, categories
├── routes_health.py         # Service health checks
├── routes_pipeline.py       # Multi-agent pipeline + V2.1 verification
├── profile_routes.py        # Patient profile endpoints
└── forum_routes.py          # Forum/community endpoints

services/
├── ai_agent.py              # Single-agent RAG chat (uses schemas_rag)
├── knowledge_base.py        # Knowledge base service (uses schemas_rag)
├── patient_stage_service.py # Stage hierarchy + RAG context
├── patient_profile_service.py
└── agents/
    ├── orchestrator.py      # Pipeline orchestrator (uses schemas_pipeline)
    ├── stage_agent_v2.py    # LLM stage inference
    ├── intent_agent.py      # Intent classification
    ├── reasoning_agent.py   # Medical reasoning
    ├── retrieval_agent.py   # RAG retrieval
    ├── validator_agent.py   # Safety validation
    ├── video_retrieval_agent.py
    └── base_agent.py        # Agent base class
```

### 14.7 Verification Results

- ✅ `grep -rn "schemas_deprecated\|routes_deprecated"` → **0 results**
- ✅ All 6 critical import chains verified (schemas_rag, schemas_pipeline, 4 route modules)
- ✅ Server starts cleanly with `uvicorn main:app`
- ✅ No breaking changes to API endpoints or behavior

