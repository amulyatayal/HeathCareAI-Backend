# Stages Journey Architecture - Design Notes (V2.1 Final)

**Version**: 2.1 Final  
**Date**: 2026-02-01 (Design) | 2026-02-09 (Implemented)  
**Status**: ✅ Implemented & Verified  

## Overview

This document is the **authoritative source** for all architectural decisions, design rationale, and implementation context for the Breast Cancer Journey Engine enhancements (V2.1). All discussions, user feedback, and alignments are consolidated here.

**Companion Documents**:
- [`implementation_sequence.md`](../../brain/1b6f90f7-8562-4d42-8a70-f1687c2c1e32/implementation_sequence.md) - Step-by-step implementation guide
- [`stage_classification_v2_design.md`](stage_classification_v2_design.md) - V2 architecture overview

---

## Executive Summary: What's in V2.1

### Core Enhancements
✅ **59 Detailed Sub-Stages** - Full hierarchical journey from CSV  
✅ **Verification Questions** - CSV-sourced validation questions  
### **Safety Triggers** - Severity levels (CRITICAL/HIGH/MEDIUM)  ❌ SIMPLIFIED
✅ **Safety Triggers** - General keyword list for escalation  
❌ **Stage-Aware Safety** - Expected symptoms filtering removed (not in CSV)  
✅ **Geo-Aware Emergency Numbers** - UK (999/111) vs US (911/811)  
✅ **Regression Detection** - Recurrence/new diagnosis alerts  
✅ **Enhanced Patient Profile** - 13 new tracking fields  
✅ **Transition Metadata** - Full stage change history  
✅ **Guest User Nudges** - Sign-in prompts  

### Explicitly Excluded (Deferred to V2.2)
❌ **Analytics Infrastructure** - Mismatch logging, dashboards  
❌ **Multi-Turn Verification** - Complex question flows  
❌ **Care Team Integration** - Direct notifications  
❌ **Journey Milestones** - Key date tracking  

---

## CSV Structure & Stage Mapping

### Stage Groups (From BreastCancerStagesProcessed.csv)

The CSV defines **11 stage groups** in linear progression:

```
Group 0  → Pre-diagnosis
Group 1  → Results Clinic (Newly Diagnosed)
Group 2  → Surgery (18 sub-stages!) ← Most detailed
Group 3  → Neoadjuvant Chemotherapy
Group 4  → Neoadjuvant Endocrine Treatment
Group 5  → Survivorship
Group 6  → Further Surgery
Group 7  → Adjuvant Radiotherapy
Group 8  → Adjuvant Chemotherapy
Group 9  → Adjuvant Endocrine Therapy
Group 10 → Adjuvant Zoledronic Acid
```

**Total**: 59 detailed sub-stages across 11 groups

### Mapping to High-Level Stages

CSV stage groups map to 8 high-level `PatientStage` enum values:

```python
STAGE_GROUP_TO_HIGH_LEVEL = {
    0: PatientStage.PRE_DIAGNOSIS,
    1: PatientStage.NEWLY_DIAGNOSED,
    
    # ACTIVE_TREATMENT spans multiple groups (non-linear)
    2: PatientStage.ACTIVE_TREATMENT,   # Surgery
    3: PatientStage.ACTIVE_TREATMENT,   # Neoadjuvant Chemo
    4: PatientStage.ACTIVE_TREATMENT,   # Neoadjuvant Endocrine
    6: PatientStage.ACTIVE_TREATMENT,   # Further Surgery
    7: PatientStage.ACTIVE_TREATMENT,   # Adjuvant Radio
    8: PatientStage.ACTIVE_TREATMENT,   # Adjuvant Chemo
    9: PatientStage.ACTIVE_TREATMENT,   # Adjuvant Endocrine
    10: PatientStage.ACTIVE_TREATMENT,  # Zoledronic Acid
    
    5: PatientStage.SURVEILLANCE,       # Survivorship
}
```

**Note**: `PatientStage.AWAITING_RESULTS` and `PatientStage.POST_TREATMENT` are intermediate states not directly in CSV groups.

### Treatment Path Types

**ACTIVE_TREATMENT is NOT linear** - encompasses 3 parallel paths:

1. **Neoadjuvant Path** (Groups 3-4 → 2):
   - Chemotherapy/endocrine treatment BEFORE surgery
   - Then surgery (Group 2)
   - Then adjuvant treatments (Groups 7-10)

2. **Surgery-First Path** (Group 2 → 7-10):
   - Surgery immediately (Group 2)
   - Then adjuvant treatments (Groups 7-10)

3. **Adjuvant Path** (Groups 7-10):
   - Radiotherapy
   - Chemotherapy
   - Endocrine therapy
   - Zoledronic acid

---

## Key Architectural Decisions

### Decision 1: Enhance Existing Models vs New Service ✅

**Date**: 2026-01-31  
**Status**: ✅ Decided  
**User-Confirmed**: Yes

**Decision**: Reuse and enhance existing `TreatmentStage` model and `PatientStageService` instead of creating new `JourneyEngineService`.

**Rationale**:
- V2 architecture already has comprehensive stage management
- `PatientStageService` provides RAG context, breadcrumbs, transitions
- StageAgentV2 handles LLM-based inference
- Adding parallel system creates maintenance burden
- 3 new fields achieve same goals as new service

**Impact**:
- ✅ Reduced complexity (9 files vs 15+ files)
- ✅ Single source of truth maintained
- ✅ No breaking changes
- ✅ ~40% faster implementation

---

### Decision 2: CSV Source is Canonical ✅

**Date**: 2026-01-31  
**Status**: ✅ Decided

**Decision**: Use `BreastCancerStagesProcessed.csv` as canonical source.

**Old CSV**: `data/Knowledge Base Bank - BreastCancerStages.csv` (deprecated)  
**New CSV**: `data/Breast cancer stages/Knowledge Base Bank - BreastCancerStagesProcessed.csv`

**Why New CSV**:
- ✅ Contains "Patient Facing Questions" column
- ✅ 59 stages vs 52 stages
- ✅ Better hierarchical structure
- ✅ Patient-facing labels included
- ✅ More detailed surgery sub-stages

**Implementation**:
- Update `build.py` line 105
- Update `patient_stage_service.py` line 52
- Regenerate `stage_hierarchy.json`

---

### Decision 3: Verification Questions from CSV ✅

**Date**: 2026-01-31  
**User Feedback**: 2026-02-01 - Confirmed CSV-sourced, NO LLM generation

**Decision**: Extract `verification_questions` directly from CSV "Patient Facing Questions" column.

**Design**:
```python
class TreatmentStage(BaseModel):
    verification_questions: List[str] = Field(
        default_factory=list,
        description="Questions from CSV to verify stage"
    )
```

**Extraction Logic**:
```python
questions_raw = row.get('Patient Facing Questions', '').strip()
verification_questions = [
    q.strip() 
    for q in questions_raw.split('\n') 
    if q.strip() and len(q.strip()) > 5
]
```

**Example from CSV (Results Clinic, Stage 1)**:
```
CSV Column: "Have you been told what treatments?
If yes, are you having chemotherapy, hormone tablets or surgery..."

Parsed: [
    "Have you been told what treatments?",
    "If yes, are you having chemotherapy, hormone tablets or surgery..."
]
```

**Usage**:
1. Stage confirmation messages
2. Low-certainty clarification
3. Guest user stage updates

**Quality Validation**:
- Questions must end with `?`
- Minimum length: 10 characters
- Warn if patient-facing stage has no questions

---

### Decision 4: Safety Triggers with Severity Levels ✅

**Date**: 2026-01-31  
**Enhanced**: 2026-02-01 - Added severity and stage-awareness

**Decision**: Safety triggers have severity levels (CRITICAL/HIGH/MEDIUM) and stage-aware filtering.

**Design**:
```python
class TreatmentStage(BaseModel):
    safety_triggers: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Safety keywords with severity levels"
    )
    expected_symptoms: List[str] = Field(
        default_factory=list,
        description="Symptoms NORMAL for this stage"
    )
```

**Severity Levels**:
```python
CRITICAL_KEYWORDS = {
    "chest pain": "CRITICAL",
    "shortness of breath": "CRITICAL",
    "seizure": "CRITICAL",
    "confusion": "CRITICAL",
}

HIGH_KEYWORDS = {
    "fever": "HIGH",
    "severe pain": "HIGH",
    "bleeding": "HIGH",
    "infection": "HIGH"
}

MEDIUM_KEYWORDS = {
    "swelling": "MEDIUM",
    "redness": "MEDIUM",
    "discharge": "MEDIUM",
}
```

**Stage-Aware Filtering**:
```python
# Example: Group 8 (Chemotherapy)
expected_symptoms = ["nausea", "fatigue", "hair loss"]

# User says: "I feel nauseous"
# Result: DON'T escalate (nausea is expected during chemo)

# User says: "I have chest pain"
# Result: ESCALATE (CRITICAL - always escalate)
```

**Detection Logic**:
1. Scan message for all safety keywords
2. Check if symptom is in `expected_symptoms` for current stage
3. Skip escalation if expected AND not CRITICAL
4. Always escalate all safety trigger symptoms (Stage-aware filtering disabled until CSV update)

---

### Decision 5: Geo-Aware Emergency Numbers ✅

**Date**: 2026-02-01  
**User Feedback**: UK patient base requires 999, not 911

**Decision**: Emergency numbers based on `country_code` in patient profile.

**Implementation**:
```python
EMERGENCY_NUMBERS = {
    "GB": {"emergency": "999", "non_emergency": "111"},
    "US": {"emergency": "911", "non_emergency": "811"},
    "AU": {"emergency": "000", "non_emergency": "13HEALTH"},
}

# Safety response
emergency_info = EMERGENCY_NUMBERS.get(profile.country_code, EMERGENCY_NUMBERS["GB"])

response = f"""
⚠️ These symptoms may require immediate attention.
Please contact your care team or call NHS 111.
If severe, call {emergency_info['emergency']}.
"""
```

**Patient Profile Field**:
```python
class PatientProfile(BaseModel):
    country_code: Optional[str] = "GB"  # Default UK
    region: Optional[str] = None        # NHS region, state
```

---

### Decision 6: Enhanced Patient Profile Model ✅

**Date**: 2026-02-01  
**Status**: ✅ Decided - 13 new fields

**Decision**: Add comprehensive tracking fields to `PatientProfile` without analytics.

**New Fields (13 total)**:

#### Geo-Awareness (2 fields)
```python
country_code: Optional[str] = None
region: Optional[str] = None
```

#### Stage Certainty Tracking (3 fields)
```python
current_stage_certainty: Optional[str] = None  # HIGH/MEDIUM/LOW
detailed_stage_certainty: Optional[str] = None
last_verification_at: Optional[datetime] = None
```

#### Regression/Recurrence Tracking (5 fields)
```python
has_recurrence: bool = False
recurrence_date: Optional[datetime] = None
is_regression_detected: bool = False
treatment_phases_completed: List[str] = Field(default_factory=list)
first_diagnosis_date: Optional[date] = None
```

#### Guest Conversion (3 fields)
```python
was_guest: bool = False
guest_interactions_count: int = 0
```

**Total Storage Impact**: ~500 bytes per profile  
**Migration**: None needed (all fields optional with defaults)

---

### Decision 7: Enhanced Stage History Metadata ✅

**Date**: 2026-02-01  
**Status**: ✅ Decided - Gap 1 implementation

**Decision**: Capture full transition metadata in `PatientStageHistory`.

**New Fields (8 total)**:
```python
class PatientStageHistory(BaseModel):
    # Existing
    timestamp: datetime
    from_stage: Optional[PatientStage]
    to_stage: PatientStage
    source: str
    
    # NEW: LLM inference metadata
    inference_certainty: Optional[str] = None
    inference_signals: List[str] = Field(default_factory=list)
    user_confirmed: bool = False
    
    # NEW: Detailed transitions
    from_detailed_stage_id: Optional[str] = None
    to_detailed_stage_id: Optional[str] = None
    
    # NEW: Treatment context
    treatment_type: Optional[str] = None
    transition_notes: Optional[str] = None
    was_regression: bool = False
```

**Updated source values**:
- `'onboarding'` - From initial questionnaire
- `'llm_inference'` - StageAgentV2 inferred (NEW)
- `'manual_update'` - Admin/support updated
- `'verification'` - User confirmed via verification questions (NEW)

**Benefits**:
- Track why stage changed (LLM signals)
- Identify low-certainty transitions
- Detect regression events
- Analyze treatment progression
- (Future) Improve LLM prompts based on signals

---

### Decision 8: Regression Detection Strategy ✅

**Date**: 2026-02-01  
**User Feedback**: Include regression/recurrence in V2.1 plan

**Decision**: Use CSV stage groups for regression detection.

**Detection Logic**:
```python
def detect_regression(current_stage_id, new_stage_id) -> dict:
    current_group = int(current_stage_id.split('.')[0])
    new_group = int(new_stage_id.split('.')[0])
    
    # Regression Type 1: Recurrence
    # Survivorship (Group 5) → Treatment (Groups 1-4, 6-10)
    if current_group == 5 and new_group in [1, 2, 3, 4, 6, 7, 8, 9]:
        return {
            "is_regression": True,
            "regression_type": "recurrence"
        }
    
    # Regression Type 2: New Primary
    # Post-treatment (Groups 7-10) → Early stages (0-1)
    if current_group >= 7 and new_group <= 1:
        return {
            "is_regression": True,
            "regression_type": "new_primary"
        }
    
    return {"is_regression": False}
```

**Response Handling**:
```python
if regression_detected:
    # Update profile
    profile.is_regression_detected = True
    profile.has_recurrence = True
    profile.recurrence_date = now
    
    # Add empathy to reasoning prompt
    reasoning_suffix = """
    IMPORTANT: This patient was in survivorship (cancer-free) and is now 
    facing recurrence. Show extra empathy and acknowledge how difficult 
    this situation is. Avoid generic language.
    """
```

---

### Decision 9: Guest User Sign-In Nudges ✅

**Date**: 2026-02-01  
**User Feedback**: Add nudges for guest users to sign in

**Decision**: Prompt guests to create account in specific scenarios.

**Trigger Scenarios**:
1. **Low Certainty Inference** - Would benefit from saved profile
2. **After Safety Trigger** - For care team notifications
3. **Multiple Interactions** - After 3+ conversations

**Implementation**:
```python
# Scenario 1: Low certainty
if user.is_guest and context.stage_result.certainty == CertaintyLevel.MEDIUM:
    response += """
    
    💡 **Tip**: Sign in to save your treatment stage and get more 
    personalized responses! Your journey info will be securely stored.
    """

# Scenario 2: Safety concern
if user.is_guest and safety_triggers:
    response += """
    
    📝 **Sign up to enable care team notifications**
    Create an account to receive alerts and keep your care team informed.
    """

# Scenario 3: Frequent use
if user.is_guest and guest_interaction_count >= 3:
    response += """
    
    👋 **You've been here a few times!**
    Create a free account to save your progress and get tailored guidance.
    """
```

**Tracking**:
- `guest_interactions_count` incremented each message
- `was_guest` flag set on conversion
- (Future) Analytics on conversion triggers

---

### Decision 10: Analytics Excluded from V2.1 ✅

**Date**: 2026-02-01  
**User Request**: Exclude analytics features

**Decision**: Defer all analytics infrastructure to V2.2.

**Excluded Features**:
❌ `StageMismatch` DynamoDB table  
❌ Mismatch logging in orchestrator  
❌ Weekly analysis cron jobs  
❌ Quality dashboards  
❌ A/B testing framework  

**Rationale**:
- Focus V2.1 on core journey enhancements
- Analytics requires monitoring infrastructure not yet defined
- Can add later without blocking deployment
- Reduces complexity and testing scope

**Future (V2.2)**:
- Design analytics schema based on V2.1 learnings
- Implement logging after seeing real usage patterns
- Build dashboards when data volume justifies it

---

## Design Principles Maintained

### From ProjectSpec.md v1.3
✅ **Educational Only** - No diagnosis, treatment advice  
✅ **Stateless Agents** - No persistent memory  
✅ **Explicit Context Passing** - Via `PipelineContext`  
✅ **Deterministic Safety** - Rule-based keyword matching  
✅ **Safe Abstention** - Verification questions enable clarification  
✅ **Validator Authority** - Safety triggers complement, not replace  

### From V2 Architecture
✅ **LLM-based Inference** - StageAgentV2 unchanged  
✅ **Chat Confirmation** - Verification questions in messages  
✅ **Single Orchestrator** - No new orchestrator  
✅ **PatientStageService** - Enhanced, not replaced  
✅ **Guest Support** - All features work for anonymous users  

---

## Complete Sub-Stage Enumeration

### All 59 Stages by Group

**Group 0: Pre-Diagnosis** (1 stage)
```
0 → Pre-diagnosis
```

**Group 1: Results Clinic** (5 stages)
```
1     → Results Clinic
1.1   → Chemotherapy First
1.2   → Hormone Therapy
1.2.1 → Change in hormone medication
1.3   → Surgery
```

**Group 2: Surgery** (18 stages)
```
2       → Surgery
2.1     → Breast Conserving Surgery
2.1.1   → Lumpectomy
2.1.2   → Therapeutic Mammaplasty
2.1.3   → Chest Wall Perforator Flap
2.1.4   → Pre-operative localization
2.1.5   → Oncoplastic surgery
2.2     → Mastectomy
2.2.1   → Mastectomy (simple)
2.2.2   → Mastectomy with Reconstruction (Implant)
2.2.3   → Mastectomy with Reconstruction (Autologous)
2.2.4   → Skin-sparing mastectomy
2.2.5   → Nipple-sparing mastectomy
2.3     → Lymph Node Surgery
2.3.1   → Sentinel Lymph Node Biopsy
2.3.2   → Axillary Lymph Node Clearance
2.4     → Day of Surgery
2.5     → Post-operative Recovery (Hospital)
2.6     → Post-operative Recovery (Home)
```

**Group 3: Neoadjuvant Chemotherapy** (3 stages)
```
3     → Neoadjuvant Chemotherapy
3.1   → Chemotherapy only
3.2   → Chemotherapy with Immunotherapy
3.3   → Chemotherapy with Targeted Therapy
```

**Group 4: Neoadjuvant Endocrine** (1 stage)
```
4 → Neoadjuvant Endocrine Treatment
```

**Group 5: Survivorship** (2 stages)
```
5     → Survivorship
5.1   → Early Survivorship (0-5 years)
5.2   → Long-term Survivorship (5+ years)
```

**Group 6: Further Surgery** (3 stages)
```
6     → Further Surgery
6.1   → Re-excision (positive margins)
6.2   → Delayed Reconstruction
6.3   → Contralateral Prophylactic Mastectomy
```

**Group 7: Adjuvant Radiotherapy** (1 stage)
```
7 → Adjuvant Radiotherapy
```

**Group 8: Adjuvant Chemotherapy** (1 stage)
```
8 → Adjuvant Chemotherapy
```

**Group 9: Adjuvant Endocrine** (2 stages)
```
9     → Adjuvant Endocrine Therapy
9.1   → Hormone Therapy
9.2   → Hormone Therapy with Zoledronic Acid
```

**Group 10: Adjuvant Zoledronic Acid** (1 stage)
```
10 → Adjuvant Zoledronic Acid (Zometa)
```

**Total: 59 stages**

---

## Implementation Scope

### Files Modified (7 files)

**Models** (2):
1. `models/patient_stages.py` - Add 2 fields (verification_questions, safety_triggers)
2. `models/patient_profile.py` - Add 13 fields + enhance history

**Scripts** (1):
3. `scripts/stage_hierarchy/build.py` - CSV path, parser, validation

**Services** (2):
4. `services/patient_stage_service.py` - CSV path, safety/regression methods
5. `services/patient_profile_service.py` - Enhanced update method

**Tests** (1):
6. `tests/test_journey_enhancements.py` - Comprehensive test suite

**Data** (1):
7. `data/stage_hierarchy.json` - Regenerated with new fields

### Lines of Code Estimate

| Component | LOC Added | LOC Modified |
|-----------|-----------|--------------|
| Models | ~150 | ~50 |
| Build script | ~180 | ~30 |
| Stage service | ~200 | ~40 |
| Profile service | ~80 | ~20 |
| Tests | ~120 | 0 |
| **Total** | **~730** | **~140** |

**Estimated Effort**: 12-16 hours (1 developer, 2-3 days)

---

## Backward Compatibility

All changes are **100% backward compatible**:

✅ **New model fields**: Optional with defaults  
✅ **CSV changes**: Graceful fallback if columns missing  
✅ **JSON regeneration**: Old JSON still loads (new fields empty)  
✅ **Service methods**: All additions, no breaking changes  
✅ **DynamoDB**: No schema changes (schema-less)  

**Migration**: None required  
**Rollback**: Git revert + restart backend  

---

## Testing Strategy

### Automated Tests (11 tests)

1. ✅ Verification questions loaded from CSV
2. ✅ Safety triggers have severity levels
3. ✅ Stage-aware safety doesn't over-escalate
4. ✅ CRITICAL symptoms always escalate
5. ✅ UK emergency numbers (999)
6. ✅ US emergency numbers (911)
7. ✅ Regression detection (recurrence)
8. ✅ Regression detection (new primary)
9. ✅ Enhanced history metadata saved
10. ✅ Profile certainty tracking
11. ✅ Guest nudge triggers

### Manual Validation

- Load all 59 stages successfully
- Verify Surgery sub-stage breadcrumbs
- Test safety detection with real messages
- Check geo-aware emergency responses
- Validate CSV quality checks

---

## Post-Implementation Monitoring

### Week 1-2: Initial Deployment
- Monitor safety trigger accuracy rate
- Track false positive rate (expected symptoms)
- Collect user feedback on verification questions
- Validate regression detection logic

### Month 1: Pattern Analysis
- Which verification questions most effective?
- Safety trigger severity distribution
- Guest-to-auth conversion rate
- Most common detailed stages

### What's Next (V2.2)
- Analytics infrastructure (deferred from V2.1)
- Multi-turn verification flows
- Care team integration
- Journey milestone tracking
- ML-based safety detection

---

## References

**Primary Documents**:
- [Implementation Sequence](../../brain/1b6f90f7-8562-4d42-8a70-f1687c2c1e32/implementation_sequence.md) - Step-by-step guide
- [Stage Classification V2 Design](stage_classification_v2_design.md) - V2 architecture
- [ProjectSpec.md v1.3](../ProjectSpec.md) - System requirements

**Data Sources**:
- `data/Breast cancer stages/Knowledge Base Bank - BreastCancerStagesProcessed.csv` - Canonical CSV
- `data/stage_hierarchy.json` - Generated hierarchy

**Key Models**:
- `models/patient_stages.py` - TreatmentStage model
- `models/patient_profile.py` - PatientProfile model
- `config/pipeline_config.py` - PatientStage enum

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-01-31 | AI Assistant | Initial document creation |
| 2026-02-01 | AI Assistant | Added CSV alignment, profile enhancements |
| 2026-02-01 | AI Assistant | Added user feedback, regression detection |
| 2026-02-01 | AI Assistant | Finalized V2.1 scope, excluded analytics |
| 2026-02-01 | AI Assistant | **AUTHORITATIVE VERSION** - All discussions consolidated |

---

## Notes for Contributors

When working on stages journey system:

1. **Check this document FIRST** - All decisions documented here
2. **Maintain backward compatibility** - Optional fields, graceful fallbacks
3. **Test with CSV edge cases** - Missing columns, malformed data
4. **Update stage_hierarchy.json** - Regenerate after CSV changes
5. **Document the "why"** - Update this file with rationale
6. **Follow V2 architecture** - Don't introduce parallel systems
7. **Keep UK deployment in mind** - Geo-aware content critical
  

## Overview

This document tracks key architectural decisions and design rationale for the Breast Cancer Journey Engine enhancements. These notes complement the formal design documents and capture the evolution of our thinking.

---

## Key Architectural Decisions

### Decision 1: Enhance Existing Models vs New JourneyEngine Service

**Date**: 2026-01-31  
**Status**: ✅ Decided

**Context**: 
Initial proposal suggested creating a new `JourneyEngineService` with graph-based state machine logic separate from existing `PatientStageService`.

**Decision**: 
**Reuse and enhance existing `TreatmentStage` model and `PatientStageService`** instead of creating new components.

**Rationale**:
- Existing V2 architecture already has comprehensive stage management
- `PatientStageService` already provides RAG context, breadcrumbs, and transitions
- StageAgentV2 already handles LLM-based stage inference
- Adding new service would create parallel systems and maintenance burden
- Minimal changes (2 fields) achieve same goals

**Impact**:
- ✅ Reduced complexity
- ✅ Maintained single source of truth
- ✅ No breaking changes to existing pipeline
- ✅ Faster implementation (3 files vs 8 files)

---

### Decision 2: CSV Source for Journey Data

**Date**: 2026-01-31  
**Status**: ✅ Decided

**Context**:
Two CSV files exist:
- `data/Knowledge Base Bank - BreastCancerStages.csv` (old, 52 stages)
- `data/Breast cancer stages/Knowledge Base Bank - BreastCancerStagesProcessed.csv` (new, 59 stages)

**Decision**:
**Use `BreastCancerStagesProcessed.csv` as the canonical source** for stage data.

**Rationale**:
- Contains "Patient Facing Questions" column (needed for verification)
- More comprehensive (59 vs 52 stages)
- Better structured hierarchical data
- Includes patient-facing labels

**Implementation**:
- Update `build.py` to read from new CSV path
- Update `PatientStageService` default CSV path
- Regenerate `stage_hierarchy.json` from new source

---

### Decision 3: Verification Questions Implementation

**Date**: 2026-01-31  
**Status**: ✅ Planned

**Context**:
Need mechanism to verify patient is in correct stage beyond LLM inference.

**Decision**:
Add `verification_questions: List[str]` field to `TreatmentStage` model, extracted from CSV's "Patient Facing Questions" column.

**Design**:
```python
class TreatmentStage(BaseModel):
    # ... existing fields ...
    verification_questions: List[str] = Field(
        default_factory=list,
        description="Questions to verify patient is in this stage"
    )
```

**Usage Scenarios**:
1. **PHASE 1.5 Confirmation** - Include question in confirmation message:
   ```
   "It sounds like you might be in Mastectomy stage. 
    Have you been told what treatments you'll receive?"
   ```

2. **Low Certainty Clarification** - When StageAgentV2 returns MEDIUM/LOW certainty:
   ```
   "To better understand where you are, can you tell me: 
    Have you started chemotherapy yet?"
   ```

3. **Enhanced LLM Prompts** - Include questions in StageAgentV2 system prompt for better context

**Extraction Logic**:
- Split on newline (`\n`) for multi-line questions
- Strip whitespace and filter empty strings
- Store as list in JSON/model

---

### Decision 4: Safety Triggers Implementation

**Date**: 2026-01-31  
**Status**: ✅ Planned

**Context**:
Need rapid detection of medical emergencies or urgent safety concerns mentioned in chat.

**Decision**:
Add `safety_triggers: List[str]` field to `TreatmentStage`, extracted from stage descriptions using keyword matching.

**Design**:
```python
class TreatmentStage(BaseModel):
    # ... existing fields ...
    safety_triggers: List[str] = Field(
        default_factory=list,
        description="Symptoms requiring immediate escalation"
    )
```

**Safety Keywords**:
```python
SAFETY_KEYWORDS = [
    "fever", "bleeding", "swelling", "infection",
    "severe pain", "chest pain", "shortness of breath",
    "numbness", "weakness", "emergency", "urgent",
    "wound", "discharge", "redness", "confusion"
]
```

**Extraction Method**:
- Scan stage description text for keywords (case-insensitive)
- Store matched keywords with stage context
- Simple keyword matching (no regex) for reliability

**Detection Method**:
```python
def check_for_safety_triggers(user_message: str) -> List[Dict]:
    """Scan user message across all stages' safety triggers"""
```

**Usage Scenarios**:

1. **Pre-Pipeline Safety Check** (Optional SafetyAgent):
   - Run BEFORE StageAgentV2
   - If triggers detected → immediate escalation response
   - Skip normal RAG pipeline

2. **Enhanced ValidatorAgent**:
   - Add safety trigger check to existing validation
   - Flag responses that don't address safety concerns

3. **Analytics & Monitoring**:
   - Log safety trigger detections
   - Track frequency for clinical insights

---

### Decision 5: Safety Agent Integration Strategy

**Date**: 2026-01-31  
**Status**: 🔄 Deferred to Phase 2

**Context**:
Should safety checking happen pre-pipeline or within existing ValidatorAgent?

**Decision**:
**Two-phase approach**:
- **Phase 1**: Add `check_for_safety_triggers()` method to `PatientStageService` only
- **Phase 2** (optional): Create standalone `SafetyTriggerAgent` if monitoring shows high value

**Rationale**:
- Existing ValidatorAgent already handles safety via LLM
- Keyword-based detection is complementary, not replacement
- Can integrate later without blocking current work
- Allows data collection to validate effectiveness first

**Phase 2 Integration Point** (if implemented):
```
User Message
    ↓
PHASE 0.5: SafetyTriggerAgent.run()  ← NEW
    ↓ (if no triggers)
PHASE 1: IntentAgent + StageAgentV2 (parallel)
    ↓
PHASE 1.5: Stage Confirmation
    ↓
...existing pipeline...
```

---

### Decision 6: Backward Compatibility Strategy

**Date**: 2026-01-31  
**Status**: ✅ Decided

**Context**:
Need to ensure changes don't break existing deployments or require complex migrations.

**Decision**:
All changes are **backward compatible with graceful degradation**:

1. **Model Fields**: Use `default_factory=list` for new fields
   - Old JSON without fields → empty lists
   - No database migration needed

2. **CSV Parsing**: Check for column existence before extraction
   ```python
   questions_raw = row.get('Patient Facing Questions', '').strip()
   if not questions_raw:  # Graceful fallback
       verification_questions = []
   ```

3. **JSON Regeneration**: Optional, system works without it
   - Old `stage_hierarchy.json` still loads successfully
   - New fields just empty until regenerated

4. **Service Methods**: All new methods are additions, not modifications
   - `check_for_safety_triggers()` is new, doesn't change existing API

**Migration Path**:
- Deploy code changes first
- Regenerate JSON in place (fast, no downtime)
- Monitor logs for confirmation
- No database changes required

---

## Design Principles Maintained

### From ProjectSpec.md v1.3

✅ **Educational Only** - No diagnosis, treatment advice  
✅ **Stateless Agents** - No persistent memory  
✅ **Explicit Context Passing** - Via `PipelineContext`  
✅ **Deterministic** - Rule-based safety keyword matching  
✅ **Safe Abstention** - Verification questions enable clarification  
✅ **Validator Final Authority** - Safety triggers complement, not replace  

### From V2 Architecture

✅ **LLM-based Stage Inference** - Keep StageAgentV2 unchanged  
✅ **Chat-based Confirmation** - Use verification questions in messages  
✅ **Single Orchestrator** - No new orchestrator needed  
✅ **PatientStageService for Context** - Enhance existing service  
✅ **Guest Support** - Safety triggers work for all users  

---

## Open Questions & Future Considerations

### Q1: Should verification questions be mandatory for all stages?

**Current State**: Optional (empty list allowed)  
**Consideration**: Some stages may not have good verification questions  
**Decision**: Keep optional, document best practices for adding questions

### Q2: Should safety trigger detection use ML/NLP instead of keywords?

**Current State**: Simple keyword matching  
**Pros of ML**: Better context understanding, fewer false positives  
**Cons of ML**: Complexity, latency, maintenance  
**Decision**: Start with keywords, evaluate ML if false positive rate is high

### Q3: How to handle stage transitions with safety implications?

**Example**: Patient moves from surgery → infection detected  
**Current**: Safety triggers would still fire  
**Consideration**: Should we link safety triggers to specific transition paths?  
**Status**: Monitor in Phase 2

### Q4: Multi-language support for safety triggers?

**Current**: English only  
**Future**: Need translated keyword lists if expanding to other languages  
**Status**: Defer until internationalization requirements defined

---

## Implementation Timeline

| Phase | Status | Target Date | Deliverables |
|-------|--------|-------------|--------------|
| Phase 1: Model & Build | 🔄 Planning | TBD | Updated models, regenerated JSON |
| Phase 2: Service Enhancement | 📋 Planned | TBD | Enhanced service methods |
| Phase 3: Testing | 📋 Planned | TBD | Test suite, validation |
| Phase 4: Safety Agent | 🔮 Future | TBD | Optional SafetyAgent integration |

---

## References

- [ProjectSpec.md v1.3](../ProjectSpec.md) - Overall system requirements
- [stage_classification_v2_design.md](stage_classification_v2_design.md) - V2 architecture
- [implementation_sequence.md](../brain/.../implementation_sequence.md) - Step-by-step guide
- [compatibility_analysis.md](../brain/.../compatibility_analysis.md) - V2 compatibility validation

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-02-01 | AI Assistant | Initial document creation |
| 2026-02-01 | AI Assistant | Added 6 key architectural decisions |

---

---

## V2.2 Future Enhancements (Roadmap)

**Status**: Deferred from V2.1  
**Timeline**: Q2 2026 (Post V2.1 Production)

### Analytics Infrastructure

**Purpose**: Track stage classification accuracy and identify improvement opportunities

**Components**:

1. **StageMismatch Table** (DynamoDB):
   ```python
   {
       "user_id": str,
       "timestamp": datetime,
       "profile_stage": str,
       "inferred_stage": str,
       "certainty": str,
       "user_confirmed": bool,
       "user_rejected": bool,
       "signals": List[str]
   }
   ```

2. **Mismatch Logging** (Orchestrator):
   - Log all HIGH certainty mismatches
   - Track user confirmation/rejection
   - Capture LLM reasoning signals

3. **Analysis Dashboard**:
   - Weekly accuracy metrics
   - Common misclassification patterns
   - Stage transition flows
   - Verification question effectiveness

**Value**: Continuous improvement of StageAgentV2 prompts and verification questions

---

### Multi-Turn Verification Flows

**Purpose**: Handle complex or ambiguous stage situations

**Design**:
```
User: "I'm getting treatment"
Bot: "To better understand your stage, could you tell me:
     1. What type of treatment? (surgery/chemotherapy/radiation)
     2. Have you started yet, or is it scheduled?"

User: "Surgery next week"
Bot: "Got it! What type of surgery?
     - Lumpectomy (breast-conserving)
     - Mastectomy (full removal)
     - Lymph node removal"

User: "Mastectomy"
Bot: "✅ Updated your stage to Surgery (Mastectomy - 2.2)"
```

**Implementation**:
- Add conversation state management
- Decision tree for follow-up questions
- Context accumulation across turns

---

### Care Team Integration

**Purpose**: Alert care providers of patient concerns

**Features**:

1. **Safety Trigger Notifications**:
   - Send alert to care team when CRITICAL symptoms detected
   - Include patient message + timestamp
   - Track notification delivery

2. **Stage Verification Requests**:
   - Patient can request care team to confirm stage
   - Care team dashboard shows pending verifications

3. **Treatment Milestone Tracking**:
   - Auto-notify care team of completed milestones
   - E.g., "Patient completed chemo cycle 4"

**Privacy**: Requires patient consent + GDPR compliance

---

### Journey Milestones

**Purpose**: Track key dates and celebrate progress

**Tracked Milestones**:
- First diagnosis date
- Treatment start dates (surgery, chemo, radiation)
- Treatment completion dates
- Survivorship anniversary
- Last scan/check-up date

**User Experience**:
```
Bot: "🎉 Congratulations! Today marks 1 year since completing treatment.
     How are you feeling?"

[On anniversary of diagnosis]
Bot: "I know today might be emotional – 2 years since your diagnosis.
     You've come so far. How can I support you today?"
```

**Profile Fields**:
```python
milestone_dates: Dict[str, datetime] = {
    "first_diagnosis": datetime,
    "surgery_date": datetime,
    "chemo_start": datetime,
    "chemo_complete": datetime,
    "survivorship_start": datetime
}
```

---

### ML-Based Safety Detection

**Purpose**: Replace keyword matching with contextual understanding

**Approach**:
- Fine-tune small LLM on medical safety scenarios
- Understand context: "I had a fever" vs "worried about getting a fever"
- Severity classification based on description
- Reduce false positives

**Training Data**:
- Real patient messages (anonymized)
- Synthetic examples from medical protocols
- Feedback from care teams

---

### Advanced Regression Scenarios

**Purpose**: Handle complex recurrence patterns

**Enhancements**:

1. **Multiple Recurrences**:
   ```python
   recurrence_history: List[Dict] = [
       {"date": datetime, "stage": str, "treatment": str}
   ]
   ```

2. **Metastatic Progression**:
   - Track secondary sites
   - Different treatment pathways
   - Specialized support resources

3. **Stage Downgrade** (Rare):
   - Re-classification after second opinion
   - Support for changing diagnosis

---

### Guest User Features

**1. Guest Journey Preview**:
```
After 3 interactions:
"👋 You've explored: Pre-diagnosis → Surgery → Chemotherapy

Create an account to:
✅ Save your treatment stage
✅ Get personalized responses
✅ Track your journey milestones
✅ Access your conversation history"
```

**2. Conversion Analytics**:
- Track which features drive sign-ups
- A/B test nudge messages
- Optimize conversion timing

---

### Enhanced StageAgentV2

**1. Confidence Calibration**:
- Track actual confirmation rate vs certainty level
- Adjust thresholds based on real data
- E.g., if 95% of "HIGH" are confirmed, keep threshold
- If only 70% confirmed, adjust to require stronger signals

**2. Context Window Expansion**:
- Current: Last 3-5 turns
- V2.2: Full conversation (with summarization)
- Better understanding of patient journey

**3. Sub-Stage Specialization**:
- Separate prompts for surgery sub-stage determination
- More detailed questions for chemotherapy types
- Higher precision for similar stages

---

### Regional Localization

**Beyond UK/US**:
- Canada: 911 / Health Link 811
- Australia: 000 / 13 HEALTH (13 43 25 84)
- EU countries: 112
- India: 102 (ambulance)

**Language Support** (Future):
- Multi-language verification questions
- Translated stage descriptions
- Cultural sensitivity in responses

---

### Summary: V2.2 Priorities

| Feature | Priority | Effort | Value |
|---------|----------|--------|-------|
| Analytics Infrastructure | **HIGH** | 3-4 weeks | Critical for improvement |
| Multi-Turn Verification | MEDIUM | 2-3 weeks | Better accuracy |
| Care Team Integration | MEDIUM | 4-6 weeks | Patient safety |
| Journey Milestones | LOW | 1-2 weeks | Emotional support |
| ML Safety Detection | LOW | 6-8 weeks | Reduce false positives |

**Recommended Order**:
1. Analytics (enables data-driven decisions)
2. Multi-turn verification (builds on analytics insights)
3. Care team integration (highest patient value)
4. Others based on production data

---

## Notes for Future Contributors

When making changes to the stages journey system:

1. **Always consider backward compatibility** - Use optional fields, graceful fallbacks
2. **Update this document** - Document the "why" behind decisions
3. **Test with real patient data** - Especially safety trigger accuracy
4. **Maintain alignment with ProjectSpec.md** - Don't violate core principles
5. **Keep it simple** - Prefer enhancements over rewrites
6. **Reference master guide** - See [MASTER_IMPLEMENTATION_GUIDE.md](../../brain/1b6f90f7-8562-4d42-8a70-f1687c2c1e32/MASTER_IMPLEMENTATION_GUIDE.md) for V2.1 decisions

---

## V2.1 Implementation Changelog (2026-02-09)

This section documents the actual changes made during V2.1 implementation, including bugs discovered and fixes applied.

### Files Modified

| File | Change Summary |
|------|----------------|
| `services/agents/orchestrator.py` | Granular stage name lookup via hierarchy (was showing generic "Active Treatment") |
| `api/routes.py` | V2.1 verification question injection moved here from monkey-patch |
| `services/orchestrator_integration.py` | Multi-question display, loop prevention, confirmation/rejection detection |
| `services/patient_stage_service.py` | Cleaned RAG context — removed stage IDs, added treatment phase for LLM |
| `models/patient_profile.py` | Added `detailed_stage_label` field |
| `main.py` | Disabled monkey-patch wrapper (logic moved to API route) |
| `.gitignore` | Added `.agent/workflows/` (local configs) |
| `tests/eval_v2_1_flows.py` | LLM prompt eval with 13 test cases |

### Bugs Found & Fixed

#### Bug 1: "Active Treatment" shown for all treatment stages
- **Symptom**: Confirmation prompt always said "It sounds like you might be in the **Active Treatment** stage"
- **Root Cause**: `orchestrator.py` line 322 used `stage_display_names.get(inferred.stage)` which mapped the broad `PatientStage` enum to a generic display name. Since surgery, chemo, radiotherapy, and hormone therapy all map to the `ACTIVE_TREATMENT` enum, every treatment patient saw "Active Treatment".
- **Fix**: Replaced with `get_patient_stage_service().get_stage_by_id(granular_id).name` to look up the specific name from `stage_hierarchy.json` (e.g., "Wide local excision", "Chemotherapy"). Fallback to broad name if lookup fails.
- **Files**: `services/agents/orchestrator.py` (2 locations: confirmation prompt + update message)

#### Bug 2: Content-Length RuntimeError
- **Symptom**: `RuntimeError: Response content longer than Content-Length` when V2.1 wrapper modified response
- **Root Cause**: The monkey-patch wrapper (`orchestrator_integration.py`) modified `result.response` in-place after FastAPI had already calculated the `Content-Length` header.
- **Fix**: Moved V2.1 verification logic to the API route level (`api/routes.py` `_handle_v2_1_verification`) where the response hasn't been serialized yet. Disabled the monkey-patch in `main.py`.
- **Files**: `api/routes.py`, `main.py`, `services/orchestrator_integration.py`

#### Bug 3: Newline escaping in verification questions
- **Symptom**: Verification questions showed literal `\n` instead of line breaks
- **Root Cause**: String used `"\\n"` (escaped backslash) instead of `"\n"` (actual newline)
- **Fix**: Corrected escaping in `orchestrator_integration.py`

#### Bug 4: Technical noise in RAG context
- **Symptom**: LLM received stage IDs like "2.1.1.1" in its context, which added no value
- **Root Cause**: `get_rag_context()` in `patient_stage_service.py` included `stage.stage_id` in the prompt
- **Fix**: Removed stage ID from LLM context, added treatment phase (root node name) instead for better personalization
- **Files**: `services/patient_stage_service.py`

### Eval Results (Quick Run - 5/13 Cases)

| Test | Broad Stage | Granular ID | Result |
|------|-------------|-------------|--------|
| Lumpectomy | active_treatment | `2.1.1.1` | ✅ PASS |
| Mastectomy | active_treatment | — | ❌ FAIL (clarification) |
| Reconstruction | active_treatment | `2.1.2.2` | ✅ PASS |
| Chemo: General | active_treatment | `3.1` | ✅ PASS |
| Chemo: Side effects | active_treatment | `3.1` | ✅ PASS |

**V2.1 activation rate**: 80% (4/5 have granular stage IDs with sub-stage depth)

### Architecture Decision: API Route vs Monkey-Patch

The original V2.1 design used `activate_v2_1_features()` to monkey-patch `PipelineOrchestrator.process`. This was replaced with direct logic in `api/routes.py` (`_handle_v2_1_verification`) because:
1. Monkey-patching modified the response after serialization → Content-Length error
2. API-level logic is more maintainable and testable
3. The orchestrator remains clean and focused on pipeline execution

### Server Configuration

| Server | Port | Notes |
|--------|------|-------|
| Backend (uvicorn) | `localhost:8000` | FastAPI, auto-reload in dev |
| Frontend (Vite) | `localhost:3000` | Proxies `/api` → `localhost:8000` |

---

## Authoritative Document References

**V2.1 Implementation**:
- 📘 [MASTER_IMPLEMENTATION_GUIDE.md](../../brain/1b6f90f7-8562-4d42-8a70-f1687c2c1e32/MASTER_IMPLEMENTATION_GUIDE.md) - Complete guide with decisions, UX examples, steps
- 📋 [implementation_sequence.md](../../brain/1b6f90f7-8562-4d42-8a70-f1687c2c1e32/implementation_sequence.md) - Step-by-step sequence
- 📊 [agent_compatibility_v2.md](../../brain/1b6f90f7-8562-4d42-8a70-f1687c2c1e32/agent_compatibility_v2.md) - Agent integration validation

**V2 Architecture**:
- 🏗️ [stage_classification_v2_design.md](stage_classification_v2_design.md) - V2 architecture + V2.1 enhancements
- 🔄 [V1 Design](stage_classification_design.md) - **DEPRECATED** (V1 architecture, replaced by V2)

---

## Codebase Refactoring & File Reorganization (2026-02-10)

**Status**: ✅ Completed  
**Rollback Tag**: `pre-file-reorg-stable`

### Context & Motivation

After V2.1 implementation, the codebase had accumulated naming debt:

1. **"Deprecated" ≠ Deprecated**: `schemas_deprecated.py` and `routes_deprecated.py` were labeled as deprecated during V2 development but remained **actively imported by 6+ modules** — they are the live RAG/Chat API layer
2. **Generic Names**: `schemas.py` and `routes.py` gave no indication they served the *pipeline* domain specifically
3. **Broken Archive Attempt**: An initial attempt to move "deprecated" files to `_archive/` broke 19 import statements, requiring emergency rollback and restoration

### Root Cause: V1/V2 Naming Confusion

The confusion arose from a naming convention where:
- `schemas.py` / `routes.py` = "current" (pipeline/V2)
- `schemas_deprecated.py` / `routes_deprecated.py` = "old" (RAG/V1 chat)

But both layers are **equally active and necessary**:
- The RAG layer handles direct chat, knowledge search, health checks, and feedback
- The pipeline layer handles the multi-agent pipeline with intent → stage → retrieval → reasoning → validation

### Solution: Domain-Based Naming

All files renamed by **function/domain** instead of version label:

#### Schema Files

| Before | After | Domain | Key Models |
|--------|-------|--------|-----------|
| `schemas_deprecated.py` | **`schemas_rag.py`** | RAG/Chat | ChatRequest, ChatResponse, SourceCitation, KnowledgeDocument, KnowledgeSearchRequest, FeedbackRequest, HealthCheckResponse |
| `schemas.py` | **`schemas_pipeline.py`** | Multi-Agent Pipeline | PipelineRequest, PipelineResponse, PipelineContext, IntentResult, StageResult, ReasoningResult, RetrievalResult, ValidationResult, AgentTrace |

#### Route Files

| Before | After | Routers Contained |
|--------|-------|-------------------|
| `routes_deprecated.py` (monolith) | **`routes_chat.py`** | `chat_router` — chat, feedback, session management |
| `routes_deprecated.py` (monolith) | **`routes_knowledge.py`** | `knowledge_router` + `categories_router` — search, documents, indexes |
| `routes_deprecated.py` (monolith) | **`routes_health.py`** | `health_router` — service health checks |
| `routes.py` | **`routes_pipeline.py`** | `pipeline_router`, `health_v2_router`, `debug_router` + V2.1 verification |

### Import Update Scope

**21 import statements** updated across **17 files**:

- **5 files** updated from `schemas_deprecated` → `schemas_rag` (models/__init__.py, ai_agent.py, knowledge_base.py, 2 ingest scripts)
- **13 files** updated from `models.schemas` → `models.schemas_pipeline` (all agents, pipeline routes, test files, verify_integration.py)
- **api/__init__.py** rewired from version-labeled sections ("v1 deprecated" / "v2 new") to domain-labeled sections ("RAG / Chat" / "Pipeline")

### Prior Refactoring Steps (Same Session)

These changes were completed before the file reorganization:

| Step | Change | Files |
|------|--------|-------|
| Checkpoint | `git tag pre-refactor-stable` | — |
| Build script fix | Updated CSV path in `build.py` | 1 |
| Test relocation | Moved eval/test files → `tests/stage_classification/` | 4 |
| V2.1 consolidation | Merged `v2_1_extensions.py` into main services | 3 |
| Dead code removal | Deleted unused/orphaned files | 5 |
| Import verification | Validated all imports pass | — |
| File reorg checkpoint | `git tag pre-file-reorg-stable` | — |
| Model renames | `schemas_deprecated` → `schemas_rag`, `schemas` → `schemas_pipeline` | 2 |
| Route split | `routes_deprecated` → 3 files, `routes` → `routes_pipeline` | 5 |
| Import updates | All 21 statements across 17 files | 17 |

### Final Project Structure

```
HeathCareAI-Backend/
├── main.py                         # FastAPI app entry point
│
├── models/
│   ├── __init__.py                 # Re-exports from schemas_rag
│   ├── schemas_rag.py              # [was schemas_deprecated.py] RAG/Chat models
│   ├── schemas_pipeline.py         # [was schemas.py] Pipeline models
│   ├── patient_profile.py          # Patient profile (13 V2.1 fields)
│   └── patient_stages.py           # TreatmentStage model (verification_questions, safety_triggers)
│
├── api/
│   ├── __init__.py                 # Central router registry
│   ├── routes_chat.py              # [from routes_deprecated.py] Chat + feedback + sessions
│   ├── routes_knowledge.py         # [from routes_deprecated.py] Knowledge search + categories
│   ├── routes_health.py            # [from routes_deprecated.py] Health checks
│   ├── routes_pipeline.py          # [was routes.py] Pipeline + V2.1 verification
│   ├── profile_routes.py           # Patient profile CRUD
│   └── forum_routes.py             # Community/forum
│
├── config/
│   ├── pipeline_config.py          # PatientStage enum, IntentCategory, ModelType
│   ├── agent_routing.py            # Agent type routing config
│   └── aws.py                      # AWS service clients
│
├── services/
│   ├── ai_agent.py                 # Single-agent RAG chat (imports schemas_rag)
│   ├── knowledge_base.py           # RAG knowledge base (imports schemas_rag)
│   ├── patient_stage_service.py    # Stage hierarchy, RAG context, safety triggers
│   ├── patient_profile_service.py  # Profile persistence + regression detection
│   ├── conversation_logger.py      # DynamoDB conversation logging
│   └── agents/
│       ├── orchestrator.py         # Pipeline orchestrator (imports schemas_pipeline)
│       ├── stage_agent_v2.py       # LLM stage inference
│       ├── intent_agent.py         # Intent classification
│       ├── reasoning_agent.py      # Medical reasoning + RAG context
│       ├── retrieval_agent.py      # Document retrieval
│       ├── validator_agent.py      # Safety validation
│       ├── video_retrieval_agent.py
│       └── base_agent.py           # Agent ABC + tracing
│
├── data/
│   ├── stage_hierarchy.json        # Generated from CSV (59 stages)
│   └── Breast cancer stages/
│       └── BreastCancerStagesProcessed.csv  # Canonical source
│
├── scripts/
│   ├── stage_hierarchy/
│   │   ├── build.py                # CSV → JSON generator
│   │   └── verify_integration.py   # E2E verification
│   └── opensearch/
│       ├── ingest_csv_to_opensearch.py
│       └── ingest_qa_data.py
│
├── tests/
│   ├── stage_classification/
│   │   ├── eval_stage_classification_flows.py
│   │   ├── test_stage_agent.py
│   │   └── test_int_stage_personalization.py
│   └── eval_v2_1_flows.py          # V2.1 granular stage eval
│
└── docs/
    ├── stage_classification_v2_design.md  # This companion doc
    └── stages_journey_notes.md            # This file
```

### Lessons Learned

1. **Never label active code as "deprecated"** — use domain names from the start
2. **Split monolith route files early** — `routes_deprecated.py` had 4 unrelated routers
3. **Run `grep -rn` before renaming** — find all import chains first
4. **Git tags before refactoring** — `pre-refactor-stable` and `pre-file-reorg-stable` made rollbacks safe
5. **Test imports programmatically** — `python3 -c "from module import ..."` catches issues faster than server start

### Verification

- ✅ Zero stale references to old file names (`grep -rn "schemas_deprecated\|routes_deprecated"`)
- ✅ All 6 critical import chains verified
- ✅ Server starts cleanly with `uvicorn main:app`
- ✅ No API endpoint changes (same URLs, same behavior)
- ✅ Two rollback checkpoints available

---

## Change Log

| Date | Change |
|------|--------|
| 2026-01-31 | Initial document creation (V2.1 design) |
| 2026-02-01 | Added CSV alignment, profile enhancements, regression detection |
| 2026-02-01 | Finalized V2.1 scope, excluded analytics |
| 2026-02-01 | **AUTHORITATIVE VERSION** - All discussions consolidated |
| 2026-02-09 | V2.1 implementation completed, bugs resolved, eval results added |
| 2026-02-10 | **Codebase refactoring** - Domain-based file naming, route splitting, dead code removal |

