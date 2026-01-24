# Patient Stage Classification - Design Document (V1)

> [!CAUTION]
> **This document describes the V1 architecture which has been deprecated.**
> 
> **Current Version**: See [stage_classification_v2_design.md](stage_classification_v2_design.md)
> 
> **Migration Date**: 2026-01-20
> 
> **Key Changes in V2**:
> - Embedding-based classifier replaced with LLM-based `StageAgentV2`
> - Proposal cards replaced with natural language chat confirmation
> - `PathwayOrchestrator` consolidated into `PipelineOrchestrator`

---

## 1. Overview

A system that:
1. **Detects** when a patient's treatment stage changes from chat messages
2. **Proposes** updates via a confirmation card (not auto-update)
3. **Allows** manual stage selection via onboarding/settings

---

## 2. Data Pipeline: Building the Stage Hierarchy

### Step 1: Source Data (CSV)
```
data/Knowledge Base Bank - BreastCancerStages.csv
```
Contains 52 clinical stages with stage IDs, names, descriptions, and transitions.

### Step 2: Build JSON Hierarchy
```bash
python scripts/build_stage_hierarchy.py
```
- Parses CSV → extracts stage_id, name, description, transitions
- Builds parent-child relationships (e.g., 2.1.2 → parent 2.1)
- Outputs: `data/stage_hierarchy.json`

### Step 3: Enrich with Search Terms
```bash
python scripts/enrich_stage_hierarchy.py
```
- Adds `display_name` (user-friendly names)
- Adds `search_terms` (patient phrases like "had my breast removed")

### Step 4: Validate Hierarchy
```bash
python scripts/validate_stage_hierarchy.py
```
- Checks for orphan stages, valid links, broken transitions

### Rebuild Process
```bash
python scripts/build_stage_hierarchy.py
python scripts/enrich_stage_hierarchy.py
python scripts/validate_stage_hierarchy.py
rm data/stage_embeddings.json  # Force embedding recompute
```

---

## 3. Embedding Computation & Caching

### On Server Startup
```
StageClassifierAgent.initialize()
        ↓
If data/stage_embeddings.json exists → Load (instant)
        ↓
Else → Compute via AWS Bedrock Titan (amazon.titan-embed-text-v1):
       
       # Text Construction
       text = f"{stage.name}: {stage.description}"
       if stage.transition_notes:
           text += f" Note: {stage.transition_notes}"
       if stage.search_terms:
           text += f" Keywords: {', '.join(stage.search_terms)}"
           
       # Example String
       # "Breast surgery: Operations to remove cancer... Keywords: having surgery, going for operation"
       
       embedding = 1024-dim vector
       Save to cache file
```

### 3b. Keyword Matching Strategy
We rely on **Semantic Expansion**. The `Keywords:` suffix significantly alters the vector's position in latent space, pulling it closer to patient-language queries.
- **Without Keywords:** "Breast surgery" vector is near clinical terms.
- **With "had surgery":** Vector shifts towards "past tense action" terms.
- **Match:** When user says "I had surgery", their vector (past tense action) aligns better with the enriched stage vector.

### Benefits
| | Without Cache | With Cache |
|--|---------------|------------|
| Startup | ~30 sec | ~1 sec |
| API Calls | 52 | 0 |

---

## 4. Agents & Personalization

### Agent Overview

| Agent | Purpose | Uses Stage Context? |
|-------|---------|---------------------|
| **IntentAgent** | Classifies what user wants (diagnosis, treatment, support) | No |
| **RetrievalAgent** | Fetches relevant docs from knowledge base | Yes |
| **ReasoningAgent** | Generates the final response using LLM | Yes |
| **ValidatorAgent** | Safety checks on response | No |

### How Stage Context Enables Personalization

```
PHASE 0: Load from profile
         stage_result = profile.detailed_stage_id (e.g., "2.1.2")
                ↓
PathwayOrchestrator.get_rag_context(patient_id)
         → "CURRENT STAGE: Mastectomy
            DESCRIPTION: Full breast removal surgery...
            NEXT STEPS: Recovery, Radiotherapy..."
                ↓
This context is injected into:
  - RetrievalAgent: Filters docs relevant to current stage
  - ReasoningAgent: LLM prompt includes stage context
                ↓
Result: Response is personalized to patient's journey position
```

**Example:**
- Patient at "Mastectomy" stage asks "What should I expect?"
- Stage context tells LLM they're in surgery phase
- Response focuses on post-surgery recovery, not general treatment

---

## 5. Flow A: Chat-Triggered Stage Detection

```
POST /api/v2/chat with message "I had surgery yesterday"
        ↓
PipelineOrchestrator.process_message_v2()
│
├─ PHASE 0: Load stage from profile (e.g., "1")
├─ PHASE 0.5: PathwayOrchestrator.determine_current_stage()
│     → StageClassifierAgent.classify(text, current_stage="1")
│     → Embed text, compare to stage embeddings
│     → Score 0.75 for stage "2.1" > threshold 0.70
│     → Return ModificationProposal
│
├─ PHASE 1: IntentAgent → intent="post_surgery"
├─ PHASE 2: RetrievalAgent → fetch relevant docs (uses stage context)
├─ PHASE 3: ReasoningAgent → generate response (uses stage context)
└─ PHASE 4: ValidatorAgent → safety check
        ↓
Response + ModificationProposal → Frontend
        ↓
ProposalCard: [Accept] updates profile / [Ignore] hides for session
```

---

## 6. Flow B: Manual Stage Update (Form)

```
User clicks "Update My Journey" in header
        ↓
Frontend: StageSelector component opens
        ↓
GET /api/v2/profile/stages
   → Returns hierarchical stage list
        ↓
User navigates: Treatment → Surgery → Mastectomy
        ↓
User clicks "Confirm"
        ↓
PUT /api/v2/profile/stage/select {stage_id: "2.1.2"}
        ↓
PathwayOrchestrator.determine_current_stage(explicit_stage_id="2.1.2")
   → Detects explicit_stage_id → SKIPS AI classification
   → Returns StageUpdateType.EXPLICIT_OVERRIDE
        ↓
PatientProfileService.update_stage_detailed(patient_id, "2.1.2")
   → Updates DynamoDB profile
        ↓
Future chat messages now use "2.1.2" for personalization
```

---

## 7. Components

| Component | Status | Purpose |
|-----------|--------|---------|
| `PipelineOrchestrator` | EXISTED | Main chat pipeline |
| `IntentAgent` | EXISTED | Classify user intent |
| `RetrievalAgent` | EXISTED | Fetch knowledge base docs |
| `ReasoningAgent` | EXISTED | Generate LLM response |
| `ValidatorAgent` | EXISTED | Safety checks |
| ~~StageAgent~~ | ❌ REMOVED | Replaced by embedding-based |
| **PathwayOrchestrator** | 🆕 NEW | Proposal generation logic |
| **StageClassifierAgent** | 🆕 NEW | Embedding-based matching |
| **PatientStageService** | 🆕 NEW | Loads stage_hierarchy.json |
| **ProposalCard** | 🆕 NEW | Frontend Accept/Ignore UI |

---

## 8. Thresholds

| Search | Threshold | Action |
|--------|-----------|--------|
| Local | > 0.70 | Propose change |
| Local low | < 0.65 | Fallback to global |
| Global | > 0.25 | Propose change (Lowered from 0.45 due to conversational noise) |

### Rationale for Low Global Threshold (0.25)
In natural conversation, users often wrap clinical keywords in long sentences ("I had surgery yesterday..."), which dilutes the vector similarity score (Vector Signal Dilution).
- **Pure Text:** "Breast surgery" vs "Breast surgery" ≈ 1.0
- **User Text:** "I had surgery yesterday. tell me what to expect next?" vs "Breast surgery" ≈ 0.25 - 0.30
A threshold of 0.25 is sufficient when combined with **strong keyword presence** in the embedding text.

---

## 9. Future Improvements (Long Term)

To improve matching accuracy without relying on low thresholds:

1. **Hybrid Search (Dense + Sparse):**
   - Combine vector similarity (Dense) with BM25 keyword matching (Sparse).
   - This prevents "signal dilution" where semantic meaning is lost in noise.

2. **Scoped Embeddings:**
   - Instead of embedding the entire stage description, embed *only* the keywords or a concise summary.
   - `embedding = embed("Breast surgery, had surgery, operation")`

3. **Reranking Model:**
   - Use a cross-encoder (e.g., BGE-Reranker) to rescore top 5 candidates.
   - Cross-encoders are slower but much more accurate for query-doc pairs.

4. **Query Expansion:**
   - Use an LLM to extract the core clinical intent before embedding.
   - "I had surgery yesterday..." -> LLM -> "patient completed surgery" -> Embedding.

---

## 10. Testing

### Test Files
| File | Coverage |
|------|----------|
| `test_pathway_orchestrator.py` | Proposals, thresholds |
| `test_stage_classifier.py` | Embedding matching |
| `test_proposal_flow.py` | API flow |
| `test_stage_personalization.py` | Stage context in prompts |

### Run Tests
```bash
# All tests
python -m pytest tests/ -v

# Before pushing
python -m pytest tests/ -v --tb=short
```

---

## 10. Quick Reference

### Key Files
| File | Purpose |
|------|---------|
| `data/stage_hierarchy.json` | 52 stages with metadata |
| `data/stage_embeddings.json` | Cached embeddings |
| `services/pathway_orchestrator.py` | Proposal logic |
| `services/agents/stage_classifier.py` | Embedding matching |
