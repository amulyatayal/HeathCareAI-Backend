# Journey UI Alignment — Change Notes

**Date**: 2026-02-10  
**Objective**: Align the "Update Journey" and onboarding UI forms with the backend's stage hierarchy, ensuring both flows show dynamic root stages with patient-friendly labels and consistent data is sent to the backend.

---

## 1. Problem Statement

The frontend had **two separate UI flows** for stage selection:

| Flow | Component | Issue |
|------|-----------|-------|
| First-time onboarding | `OnboardingWizard` | Used **hardcoded** `SITUATION_OPTIONS` (7 items) + `TREATMENT_FOLLOWUP_OPTIONS` (6 items) that didn't match the backend's 11 root stages |
| Returning user "Update Journey" | Re-opened `OnboardingWizard` | Same hardcoded options, no granular `detailed_stage_id` sent to backend |

The backend's `stage_hierarchy.json` defines **11 root stages** with `patient_facing_label` values, but the frontend never fetched or displayed them.

---

## 2. Backend Changes

### 2.1 `models/patient_profile.py` — Stage ID Mapping

**What**: Added `STAGE_ID_TO_PATIENT_STAGE` dictionary that maps root stage IDs (from `stage_hierarchy.json`) to the broad `PatientStage` enum values.

**Why**: When the frontend sends a `detailed_stage_id` (e.g., `"2"` for Surgery), the backend needs to derive the corresponding broad stage (`ACTIVE_TREATMENT`) for existing logic that depends on `PatientStage`.

```python
STAGE_ID_TO_PATIENT_STAGE = {
    "0":  PatientStage.PRE_DIAGNOSIS,
    "1":  PatientStage.NEWLY_DIAGNOSED,
    "2":  PatientStage.ACTIVE_TREATMENT,     # Surgery
    "3":  PatientStage.ACTIVE_TREATMENT,     # Neoadjuvant Chemo
    "4":  PatientStage.ACTIVE_TREATMENT,     # Neoadjuvant Endocrine
    "5":  PatientStage.SURVEILLANCE,         # Survivorship
    "6":  PatientStage.ACTIVE_TREATMENT,     # Further Surgery
    "7":  PatientStage.ACTIVE_TREATMENT,     # Adjuvant Radiotherapy
    "8":  PatientStage.ACTIVE_TREATMENT,     # Adjuvant Chemo
    "9":  PatientStage.POST_TREATMENT,       # Adjuvant Endocrine
    "10": PatientStage.POST_TREATMENT,       # Adjuvant Zoledronic acid
}
```

### 2.2 `services/patient_profile_service.py` — Onboarding Logic

**What**: Modified `save_onboarding()` to:
1. Check if `detailed_stage_id` is provided in the request
2. If yes, look up `STAGE_ID_TO_PATIENT_STAGE` to derive the broad stage
3. If no match, fall back to the existing `SITUATION_TO_STAGE` mapping
4. Log `to_detailed_stage_id` in `PatientStageHistory` for audit trail

**Why**: This ensures the backend correctly processes the new granular stage IDs sent from the redesigned frontend, while maintaining backward compatibility with the older situation-based mapping.

### 2.3 `data/stage_hierarchy.json` — Patient-Facing Labels

**What**: Verified that all 11 root stages already have `patient_facing_label` values. No changes needed.

**Examples**:
| Stage ID | Stage Name | Patient-Facing Label |
|----------|-----------|---------------------|
| 0 | Pre-diagnosis | Primary Tests and results pending |
| 1 | Results Clinic | I've just been Diagnosed |
| 2 | Surgery | Having Surgery |
| 3 | Neoadjuvant Chemotherapy | Chemotherapy before surgery only |
| 5 | Survivorship | Finished active treatment |

---

## 3. Frontend Changes

### 3.1 `services/api.ts` — Interface & Type Updates

**Changes**:
- Added `detailed_stage_id`, `treatment_type`, `age_range`, `postal_code` to `OnboardingRequest` interface
- Added `patient_facing_label?: string` to `TreatmentStage` interface

**Why**: The `OnboardingRequest` needed to carry the new granular stage ID and demographic data. The `TreatmentStage` type was missing the `patient_facing_label` field that the backend returns in the stage tree API.

### 3.2 `components/OnboardingWizard.tsx` — First-Time Onboarding (Rewritten)

**Before**: Used hardcoded `SITUATION_OPTIONS` array with 7 static options and `TREATMENT_FOLLOWUP_OPTIONS` with 6 static treatment types. None of these aligned with the backend's 11 root stages.

**After**: Complete rewrite that:
- **Fetches dynamic root stages** from `getStageTree()` API on mount
- **Shows `patient_facing_label`** only (no stage name or description)
- **Keeps age & area fields** at the top (inline row)
- **Maps stage IDs to icons** via `STAGE_ICONS` constant
- **Sends `detailed_stage_id`** to backend via `submitOnboarding()`
- **Derives `current_situation`** from `STAGE_ID_TO_SITUATION` mapping for backward compatibility
- **Includes "I'm not sure / Prefer not to say"** option
- **Preserves account linking** functionality

**Key mappings in the component**:

```typescript
// Maps stage IDs to Lucide icons for visual display
const STAGE_ICONS = { '0': Activity, '1': ClipboardList, '2': Scissors, ... }

// Maps stage IDs to situation strings for backend compatibility
const STAGE_ID_TO_SITUATION = { '0': 'worried_about_symptoms', '1': 'recently_diagnosed', ... }
```

### 3.3 `components/StageSelector.tsx` — Update Journey (Redesigned)

**Before**: A dark-themed drill-down component that always showed stage names + descriptions + checkmarks on every item. When `rootOnly` was added, it still used the dark theme and showed confusing checkmarks on all stages.

**After**: Completely redesigned for `rootOnly` mode with a **dedicated light-theme form** (`journey-form`):
- **White card** matching the app's cream/rose design system
- **Rose gradient icon** + "Update Your Journey" heading (Crimson Pro serif font)
- **Age dropdown + Area input** (inline row, same pattern as OnboardingWizard)
- **Radio-style stage selection**: empty circle → rose-filled dot on click (CSS-only, no icon library)
- **Two-step UX**: user selects a stage → clicks "Save Changes" button (rose gradient CTA)
- **"I'm not sure"** option at bottom
- **Privacy note** with lock icon
- **Scroll** within options list when many stages

The drill-down mode (`rootOnly=false`) is completely unchanged — it still uses the original dark theme for detailed stage navigation.

**Key design decision**: Used CSS variables from the app's `index.css` (`--rose-*`, `--cream-*`, `--font-serif`, `--font-sans`, `--radius-*`, `--shadow-*`) instead of hardcoded colors to ensure the form stays in sync with any future theme changes.

### 3.4 `components/StageSelector.css` — Dual-Theme Styling

**Structure**:
- **Top section**: Original dark drill-down styles (`.stage-selector`, `.stage-option`, etc.) — unchanged
- **Bottom section**: New `journey-form` light-theme styles using app CSS variables

**Key new classes**:
| Class | Purpose |
|-------|---------|
| `.journey-form` | Container with max-height scroll |
| `.journey-header` | Rose icon + serif title |
| `.journey-fields-row` | Inline age + area fields |
| `.journey-option` | White card with light border, rose highlight on selection |
| `.journey-radio` / `.journey-radio-dot` | CSS-only radio button with animated rose dot |
| `.journey-save-btn` | Rose gradient pill button with glow shadow |
| `.journey-privacy` | Lock icon + muted privacy text |

### 3.5 `styles/App.css` — Overlay & Modal

**Before**: Dark overlay (`rgba(0,0,0,0.6)`) with dark glassmorphism modal (`#1a1a2e`)

**After**: 
- Lighter overlay: `rgba(0,0,0,0.25)` with `blur(6px)` backdrop
- White modal: `border-radius: var(--radius-xl)`, subtle shadow, `slideUp` entrance animation
- Max-width reduced from 500px to 460px for better proportions

### 3.6 `App.tsx` — Wiring

**Changes**:
- Imported `StageSelector` component and `selectDetailedStage` API function
- Added `showStageSelector` state
- Changed "Update Journey" button handler from `setShowOnboardingWizard(true)` → `setShowStageSelector(true)`
- Added stage-selector overlay/modal JSX that renders `StageSelector` with `rootOnly={true}`
- On stage selection: calls `selectDetailedStage()` API, closes modal, marks profile as complete

### 3.7 `components/OnboardingWizard.css` — Loading Spinner

**Added**:
- `.spinner-icon` with `spin` animation for the `Loader2` icon
- `.stages-loading` flex container for centered loading state

---

## 4. Data Flow

### First-Time Onboarding (OnboardingWizard)

```
User opens app (no profile) 
  → OnboardingWizard renders
  → Fetches GET /api/v2/profile/stages (stage_hierarchy.json)
  → Shows 11 root stages with patient_facing_label
  → User selects: age, area, stage
  → POST /api/v2/profile/onboarding {
      current_situation: "currently_in_treatment",  // derived from STAGE_ID_TO_SITUATION
      detailed_stage_id: "2",                       // Surgery
      age_range: "50-59",
      postal_code: "SW1"
    }
  → Backend: STAGE_ID_TO_PATIENT_STAGE["2"] → ACTIVE_TREATMENT
  → Saves PatientStage + detailed_stage_id to profile
```

### Returning User Update (StageSelector rootOnly)

```
User clicks "Update Journey" in sidebar
  → StageSelector (rootOnly=true) opens in light-theme overlay
  → Fetches GET /api/v2/profile/stages
  → Shows same 11 root stages + age/area fields
  → User updates selection → clicks "Save Changes"
  → POST /api/v2/profile/stage/select { stage_id: "5" }
  → Backend updates profile stage to Survivorship
```

---

## 5. Files Changed Summary

| File | Repo | Type | Lines Changed |
|------|------|------|---------------|
| `models/patient_profile.py` | Backend | Add mapping | ~25 |
| `services/patient_profile_service.py` | Backend | Logic update | ~50 |
| `services/api.ts` | Frontend | Interface | ~5 |
| `components/OnboardingWizard.tsx` | Frontend | Full rewrite | ~260 |
| `components/OnboardingWizard.css` | Frontend | Add styles | ~20 |
| `components/StageSelector.tsx` | Frontend | Full rewrite | ~280 |
| `components/StageSelector.css` | Frontend | Full rewrite | ~340 |
| `styles/App.css` | Frontend | Restyle | ~15 |
| `App.tsx` | Frontend | Wiring | ~25 |

---

## 6. Design Decisions

1. **Root stages only for simplicity**: Both flows show only 11 root stages (not the full hierarchy) because the sub-stage drill-down is too clinical for most patients.

2. **Patient-friendly labels**: Display `patient_facing_label` (e.g., "Having Surgery") instead of clinical `name` (e.g., "Surgery") for better UX.

3. **Two separate UX patterns**: OnboardingWizard (first-time) has the full wizard flow with icons. StageSelector rootOnly (update) is a simpler form — users who already have a profile just need to quickly change their stage.

4. **Light theme for Update Journey**: Matches the app's overall warm cream/rose aesthetic rather than the dark glassmorphism that was inconsistent.

5. **Backend derivation**: The backend is responsible for mapping `detailed_stage_id` → broad `PatientStage` via `STAGE_ID_TO_PATIENT_STAGE`, keeping the frontend simple.

6. **Backward compatibility**: The `current_situation` field is still sent for backward compat with existing code that reads `OnboardingSituation` enum.

---

## 7. Testing Checklist

- [ ] New user → OnboardingWizard shows 11 dynamic root stages with patient-friendly labels
- [ ] OnboardingWizard → select stage + age + area → submit → profile saved correctly
- [ ] Returning user → click "Update Journey" → light-theme StageSelector opens
- [ ] StageSelector → shows same 11 stages + age/area fields
- [ ] StageSelector → radio selection works (only one selected at a time)
- [ ] StageSelector → "Save Changes" → stage updated in backend
- [ ] StageSelector → close button and backdrop click dismiss modal
- [ ] Mobile responsive (fields stack vertically on small screens)
- [x] TypeScript compiles with zero errors ✅
- [x] Stage persists correctly after Save (broad + detailed consistent)
- [x] Chat-based stage confirmation works without DynamoDB error
- [ ] Test prompt: "I just had my lumpectomy surgery last week" → confirm → stage updates

---

## 8. Stage Persistence & Consistency Fixes (2026-02-10)

### 8.1 Bugs Found

| # | Bug | Root Cause |
|---|-----|-----------|
| 1 | Stage not persisted after clicking Save in UI | `update_stage_detailed()` only set `detailed_stage_id`, never updated `current_stage` |
| 2 | `current_stage` and `detailed_stage_id` could become mismatched | `update_stage()` changed `current_stage` but left stale `detailed_stage_id` |
| 3 | `detailed_stage_label` not persisted from UI | Route handler didn't pass label to service method |
| 4 | DynamoDB error on chat stage confirmation | `to_dynamodb_item()` only converted 5 hardcoded datetime fields; missed `last_verification_at` set by `update_stage_with_metadata()` |

### 8.2 Fixes Applied

**`services/patient_profile_service.py`** (3 methods fixed):

| Method | Fix |
|--------|-----|
| `update_stage_detailed()` | Now derives `current_stage` from `STAGE_ID_TO_PATIENT_STAGE` and records stage history |
| `update_stage()` | Now clears `detailed_stage_id` + `detailed_stage_label` when broad stage changes |
| `update_stage_with_metadata()` | Added `new_detailed_stage_label` param; clears detailed fields when not provided |

**`api/profile_routes.py`** (route semantics corrected):

- `PUT /stage/select` now treats input as a **root/broad stage** (not detailed)
- Derives `PatientStage` from `STAGE_ID_TO_PATIENT_STAGE`, calls `update_stage()` (clears detailed fields)
- Rationale: UI only picks root stages; detailed stages are set only by the LLM during chat

**`services/agents/orchestrator.py`** (atomic update):

- Replaced two separate calls (`update_stage()` + `update_stage_detailed()`) with single `update_stage_with_metadata()` call
- One DynamoDB write, one history entry, all 3 fields updated atomically

**`models/patient_profile.py`** (serialization fix):

- `to_dynamodb_item()` → recursive `_convert_datetimes()` that converts **all** `datetime`/`date` objects in the entire dict
- No more hardcoded field list → future-proof

### 8.3 Consistency Rules

| Source | Sets `current_stage` | Sets `detailed_stage_id` / `label` |
|--------|---------------------|-------------------------------------|
| **UI** (Update Journey) | ✅ Derived from mapping | ❌ Cleared — user only picks root stage |
| **Chat** (LLM inference) | ✅ Set atomically | ✅ Set atomically with label |
| **Onboarding** | ✅ From mapping | ✅ If provided in request |

### 8.4 Files Changed

| File | Change |
|------|--------|
| `services/patient_profile_service.py` | 3 methods fixed for consistency |
| `api/profile_routes.py` | Route uses `update_stage()` + `STAGE_ID_TO_PATIENT_STAGE` import |
| `services/agents/orchestrator.py` | Single atomic `update_stage_with_metadata()` call |
| `models/patient_profile.py` | Recursive datetime serialization |

