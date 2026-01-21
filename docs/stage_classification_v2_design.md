# Stage Classification & Orchestration Architecture (V2)

**Version**: 2.0  
**Date**: 2026-01-20  
**Status**: Implemented  

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
## 11. Incremental Fixes & Refinements (Post-V2 Launch)

### 11.1 Broad Category Display Mapping
To align with the onboarding experience, the system now maps granular internal IDs (e.g., `2.1.2`) to high-level display names (e.g., "Active Treatment") in all user-facing confirmation and proposal messages.

### 11.2 Flexible Confirmation Detection
Confirmation detection now uses `message.startswith(word)` instead of exact string matching. This allows users to provide compound affirmations like *"yes, please tell me more about recovery"* without breaking the flow.

### 11.3 Clarification Integration
If a confirmation message (e.g., "yes") is too short to determine intent, the system triggers a clarification request. The stage update confirmation is now explicitly prepended to these clarification requests so the user knows their profile was updated successfully.

### 11.4 Context Preservation (Original Question Carry-over)
A major UX refinement: After a user says "yes" to a stage update, the system automatically retrieves the message sent *before* the "yes" and uses it as the query for the RAG pipeline. This prevents "context loss" where the bot would otherwise forget what the user was originally asking about.

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

## 10. Future Improvements
- **Multi-Turn Persuasion**: If a user consistently mentions symptoms of a different stage but ignores prompts, gently resurface the suggestion after N turns.
- **Guest-to-Auth Upgrade**: If a Guest confirms a stage (implicitly), prompt them to "Sign Up to save this info".
- **Granular Sub-Stage Detection**: Improve `StageAgentV2` prompt to distinguish between very similar sub-stages (e.g., "Lumpectomy" vs "Mastectomy") with higher precision using detailed definitions.
- **Confidence Calibration**: Track confirmation accuracy to fine-tune certainty thresholds.
