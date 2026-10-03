"""
Reasoning Agent Factory
Creates specialized reasoning agents for each intent category.

Spec Reference: ProjectSpec.md v1.2, Section 8
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional, Dict, Any, List

from services.agents.base_agent import BaseAgent, AgentError
from services.agents.retrieval_agent import format_chunks_for_prompt, get_citations_from_chunks
from services.agents.base_agent import BaseAgent
from services.agents.retrieval_agent import RetrievalAgent
from services.patient_stage_service import get_stage_guidelines
from models.schemas import (
    PipelineContext,
    ReasoningResult,
    Citation
)
from config.pipeline_config import (
    IntentCategory,
    PatientStage,
    CertaintyLevel,
    ModelType,
    MEDICAL_DISCLAIMER,
    SAFE_FALLBACK_RESPONSE
)
from config.agent_routing import (
    get_route_for_intent,
    get_agent_prompt,
    is_medical_intent,
    is_strict_rag,
    is_citation_only,
    ReasoningAgentType
)

logger = logging.getLogger(__name__)


# ================================
# Response Generation Prompt
# ================================

# Template for STRICT RAG mode (KB evidence only)
REASONING_STRICT_TEMPLATE = """{agent_prompt}

RESPONSE GUIDELINES:
{stage_guidelines}

EVIDENCE CONTEXT:
{evidence_context}

IMPORTANT RULES (STRICT MODE - Evidence Only):
1. Base your response ONLY on the provided evidence. Do not make up information.
2. If the evidence is insufficient, acknowledge limitations and suggest consulting the care team.
3. Use clear, accessible language appropriate for patients.
4. Be empathetic and supportive in tone.
5. Include specific citations when referencing sources (e.g., "According to [Source 1]...").
6. For medical information, always recommend consulting healthcare providers for personalized advice.
{additional_rules}

{disclaimer_instruction}"""

# Template for FLEXIBLE mode (KB + LLM general knowledge)
REASONING_FLEXIBLE_TEMPLATE = """{agent_prompt}

RESPONSE GUIDELINES:
{stage_guidelines}

EVIDENCE CONTEXT (if available):
{evidence_context}

IMPORTANT RULES (FLEXIBLE MODE):
1. Use the provided evidence when available, citing sources appropriately.
2. You MAY supplement with your general knowledge for this topic category.
3. Clearly distinguish between sourced information and general advice.
4. Use clear, accessible language appropriate for patients.
5. Be empathetic and supportive in tone.
6. For any medical-adjacent advice, recommend consulting healthcare providers.
{additional_rules}

{disclaimer_instruction}"""


# Template for CITATION-ONLY mode (verbatim quotes only)
REASONING_CITATION_TEMPLATE = """{agent_prompt}

You are providing information using ONLY verbatim quotes from trusted medical sources.

PATIENT STAGE CONTEXT:
{stage_guidelines}

Use the patient's stage to personalize your intro and closing (but NOT the medical quotes).

SOURCE MATERIALS (use EXACT text from these):
{evidence_context}

CRITICAL RULES (CITATION-ONLY MODE):
1. You MUST use the EXACT wording from the sources. DO NOT paraphrase, summarize, or rewrite ANY medical content.
2. Select the 2-3 MOST RELEVANT source excerpts that answer the patient's question.
3. PERSONALIZE the intro based on patient stage:
   - Pre-diagnosis: "I know waiting for answers can be stressful..."
   - Newly diagnosed: "Being newly diagnosed can feel overwhelming..."
   - In treatment: "I understand treatment can bring many questions..."
   - Post-treatment: "As you're moving forward after treatment..."
4. PERSONALIZE the closing based on patient stage:
   - Pre-diagnosis: Reassure that many findings are benign, encourage follow-up
   - Newly diagnosed: Acknowledge emotions, encourage taking time to understand options
   - In treatment: Validate challenges, remind them their care team is there
   - Post-treatment: Celebrate progress, acknowledge ongoing concerns are normal
5. Your intro and closing should NOT contain any medical information or summary of the quotes.
6. FORMAT EACH QUOTE AS A STYLED BLOCK using this exact markdown structure:

   > "Verbatim quote text goes here..."
   >
   > — [📄 Source Name, page number](URL)

   - Use markdown blockquote (>) for the quote
   - Put the verbatim text in quotation marks
   - Add the source link on a new line with "—" prefix
   - IMPORTANT: Use the ACTUAL page number from the source (e.g., "p.1", "p.5", "pp.2-3") - do NOT use "p.XX"
   - Use the URL provided with each source (shown as "URL: https://...")
   - Leave a blank line between each quote block

7. Example of properly formatted citation (note the real page number "p.5"):

   > "Chemotherapy destroys cancer cells by affecting their ability to divide and grow."
   >
   > — [📄 Chemotherapy for Breast Cancer, p.5](https://breastcancernow.org/media-assets/bcc17.pdf)

RESPONSE FORMAT:
1. Stage-personalized empathetic intro (1-2 sentences, NO medical content)

2. **From the sources:**

   > "Quote 1..."
   >
   > — [📄 Source](URL)

   > "Quote 2..."
   >
   > — [📄 Source](URL)

3. Stage-personalized empathetic closing (1-2 sentences, NO medical summary) with 💜

{disclaimer_instruction}"""


REASONING_USER_TEMPLATE = """Recent conversation:
{conversation_history}

Current question: {question}

Patient Stage: {stage} ({stage_certainty})
{stage_context}

Patient Profile Details:
{user_profile_context}

Please provide a helpful, evidence-based response."""


# Nutrition-specific user prompt. Used when intent == NUTRITION and ESPEN
# guidelines and/or structured patient data are available in metadata. The
# template demands a comprehensive, ESPEN-grounded, citation-rich meal plan.
REASONING_NUTRITION_USER_TEMPLATE = """Patient Question: {question}

Patient Stage: {stage} ({stage_certainty})
{stage_context}

PATIENT DATA (authoritative for personalization — respect allergies, preferences, treatment, side effects):
{patient_data_block}

PRE-CLASSIFIED CLINICAL CATEGORIES (authoritative — use these labels verbatim, do NOT re-derive them from raw numbers):
{clinical_categories_block}

ESPEN NUTRITION KNOWLEDGE BASE (AUTHORITATIVE for ALL nutrition targets and care decisions — energy, protein, macros, vitamins, intervention escalation, exercise, pharmaconutrients, patient-subgroup overrides, safety; walk its decision rules step-by-step before writing the meal plan and cite the recommendation_id from this KB next to every target):
{nutrition_kb_block}

SUPPLEMENTARY ESPEN NOTES (general background and any patient-population-specific summaries that complement the KB above):
{espen_block}

KB Evidence (if any) was supplied in the system prompt as numbered [Source N] entries.

TASK:
Design a practical one-day meal plan for this patient that:
1. Derives EVERY nutrition target by EXPLICITLY walking the ESPEN NUTRITION KB above. For each target you write, name which KB rule fired and show the arithmetic in the "Nutrition Target Derivation" section below.
   a. ENERGY — apply `energy_requirements.agent_decision_rules_for_energy_target` and `reasoning_logic_for_agent.energy_target_pseudocode` IN ORDER: refeeding gate → default 25–30 kcal/kg/day [ESPEN B2-1] → obesity adjust (BMI > 30 → 22–25 kcal/kg adjusted body weight) → cachexia / inflammation upweight (weight-losing + elevated CRP → upper end + fat-shifted [ESPEN B2-3]) → subgroup override → titration plan. If severe malnutrition (BMI < 18.5 OR weight loss > 10–15% over 6 mo OR minimal intake ≥5 days), START at 5–10 kcal/kg/day and ramp over 4–7 days with thiamine 200–300 mg/day + K (2–4 mmol/kg/day) + PO4 (0.3–0.6 mmol/kg/day) + Mg (0.2 IV / 0.4 PO mmol/kg/day) per [ESPEN B3-4].
   b. PROTEIN — apply `protein_requirements.decision_rules`: default 1.0–1.5 g/kg/day [ESPEN B2-2]; cap at 1.0 g/kg in acute renal failure; cap at 1.2 g/kg in chronic renal failure without dialysis; aim 1.2–1.5 g/kg in old age, inactivity, or systemic inflammation; up to ~2.0 g/kg with normal renal function in advanced cachexia.
   c. MACROS — apply `macronutrient_composition.decision_rules`: shift fat ↑ / CHO ↓ if weight-losing + insulin-resistant / inflamed [ESPEN B2-3]; advance CHO slowly over 4–7 days when refeeding [ESPEN B3-4].
   d. VITAMINS / MINERALS — RDA-level multivitamin / multimineral [ESPEN B2-4]; correct documented deficiencies (e.g. vitamin D); AVOID high-dose β-carotene / vitamin A / vitamin E; AVOID selenium > 140 µg/day in early prostate cancer.
   e. INTERVENTION LEVEL — apply `intervention_decision_logic.feeding_route_algorithm` (counselling → fortified diet + ONS → EN → PN); flag triggers for artificial nutrition (>1 wk no intake OR intake < 60% for >1–2 wks).
   f. PHARMACONUTRIENTS — when relevant flag long-chain n-3 / fish oil ≥2 g EPA/day in advanced-cancer chemotherapy weight loss [ESPEN B5-7]; consider corticosteroids / progestins / prokinetics per `pharmaconutrients_and_drugs` only when criteria fit.
   g. SUBGROUP OVERRIDES — pull the patient's `treatment_phase` from `patient_subgroups.<group>` and `reasoning_logic_for_agent.subgroup_dispatch_table` (surgery → ERAS [C1-1], RT → ensure intake + tube feeding if severe mucositis [C2-1/C2-2], curative_CHT → [C3-1/C3-2], HCT → [C4-1/C4-2], advanced_no_treatment → [C6-1/C6-2], survivor → [C5-1/C5-2], terminal → [C6-3]).
   h. SAFETY — confirm no contraindication is being violated (refeeding syndrome guards, "do not feed unselected CHT patients aggressively", no aggressive nutrition in dying patients).
2. Personalizes to the pre-classified clinical categories above (e.g. adjust for "Obese Class I" / "Central Obesity" / PG-SGA bucket — never re-derive these labels).
3. Respects the patient's stage, current treatment, side effects, allergies, dislikes, and cultural / dietary preferences.
4. Cites the exact recommendation_id from the KB INLINE next to every claim (e.g. "[ESPEN B2-1]", "[ESPEN B2-2]", "[ESPEN B3-4]", "[ESPEN B5-7]", "[ESPEN C3-2]") and any retrieval-KB chunks used as "[Source N]".

OUTPUT FORMAT (markdown — produce ALL sections in this order):

## Nutrition Target Derivation
- **Inputs used**: weight=<kg>, BMI=<value> (<category>), weight_loss_6mo=<%>, ECOG=<n>, treatment_phase=<phase>, kidney_function=<status>, CRP/inflammation=<status>, performance status / nutrition impact symptoms=<list>.
- **Refeeding-syndrome gate**: <"not triggered" | "TRIGGERED — start at 5–10 kcal/kg/day, ramp over 4–7 days, supplement thiamine 200–300 mg/day + K/PO4/Mg per [ESPEN B3-4]">.
- **Energy rule fired**: <"25–30 kcal/kg/day × actual body weight" | "22–25 kcal/kg × adjusted body weight (BMI > 30)" | "refeeding ramp"> → ~<kcal> kcal/day (= <kcal/kg> × <weight> kg) [ESPEN B2-1].
- **Cachexia / inflammation modifier**: <"none" | "weight-losing + elevated CRP → keep upper end of 25–30 kcal/kg AND shift kcal toward fat per [ESPEN B2-3]">.
- **Protein rule fired**: <"1.2–1.5 g/kg (normal renal)" | "1.0 g/kg cap (acute renal failure)" | "1.2 g/kg cap (chronic renal, no dialysis)" | "approaching 2.0 g/kg (advanced cachexia, normal renal)"> → ~<g> g/day [ESPEN B2-2].
- **Macronutrient split**: <"standard ~55–60% CHO / 25–30% fat" | "fat-shifted: ~50–55% CHO, ~30–35% fat per [ESPEN B2-3]"> → CHO ~<g>, fat ~<g>.
- **Vitamins / minerals**: <one line — multivitamin at RDA [ESPEN B2-4]; flag any deficiency-driven supplementation (e.g. vitamin D); list anything to AVOID for this patient>.
- **Intervention level chosen**: <"oral counselling + fortified meals + ONS" | "supplemental EN" | "PN"> per `intervention_decision_logic.feeding_route_algorithm` [ESPEN B3-1 / B3-3].
- **Pharmaconutrients flagged**: <"none" | "n-3 / EPA ≥ 2 g/day [ESPEN B5-7]" | "prokinetic for early satiety [ESPEN B5-8]" | …>.
- **Subgroup override (treatment phase)**: <one line, e.g. "curative_CHT — ensure adequate intake [ESPEN C3-1]; supplement EN/PN if intake < 60% [ESPEN C3-2]">.
- **Safety guards verified**: <one line confirming no contraindication violated (refeeding ramp respected, not over-feeding unselected CHT, etc.)>.
- **Titration plan**: reassess weight + muscle mass at 1–4 weeks; adjust kcal target ±10–20% to stabilise weight and FFM [ESPEN B2-1 commentary].

## Daily Nutrition Targets

### Macronutrients
- **Energy**: ~<kcal> kcal/day  (rule fired: <which>; basis: <kcal/kg> × <weight> kg) [ESPEN B2-1]
- **Protein**: ~<g> g/day  (rule fired: <which>; basis: <g/kg> × <weight> kg) [ESPEN B2-2]
- **Carbohydrates**: ~<g> g/day  (~50–60% of energy; lower end if fat-shifted per [ESPEN B2-3])
- **Fat**: ~<g> g/day  (~25–35% of energy; upper end if weight-losing + insulin-resistant per [ESPEN B2-3])
- **Dietary fiber**: ~<g> g/day  (reduce if mucositis / diarrhoea)

### Hydration
- **Fluids**: ~<L>/day  (substitute ORS or coconut water during vomiting / diarrhoea)

### Key Micronutrients of Concern
- **Vitamin D**: <amount>/day [ESPEN B2-4 — supplement to correct deficiency]
- **Calcium**: <amount>/day
- **Iron**: <amount>/day
- **Folate**: <amount>/day
- **Zinc**: <amount>/day
- Add **omega-3 EPA/DHA** (≥2 g EPA/day) [ESPEN B5-7] when the patient is on chemo and at risk of weight loss; flag any others ESPEN flags for this patient's treatment.
- AVOID high-dose β-carotene / vitamin A / vitamin E megadoses [ESPEN B2-4]; AVOID selenium > 140 µg/day in early prostate cancer.

### Supplements & Special Notes
- <Supplement 1 — dose — citation>
- <Supplement 2 — dose — citation>
- Side-effect-specific adjustments: <2–3 bullets tied to the patient's reported symptoms>

### Foods to Avoid (treatment- / drug-specific)
- <e.g. "Grapefruit / kinnow — CYP3A4 interaction with Tamoxifen">
- <e.g. "Raw / undercooked meat or eggs during chemo">
- <e.g. "Alcohol — ZERO" [ESPEN C5-2]>
- <e.g. "Strict ketogenic / fad / restrictive diets — contraindicated in patients at risk of malnutrition" [ESPEN B3-2]>

## Meal Plan

### Breakfast
- **Dish**: <name>
- **Ingredients**: <comma-separated>
- **Prep**: <1–3 lines>
- **Approx**: <kcal> kcal · <g> g protein
- **Why**: <one line tying back to a target above or to a side-effect mitigation>

### Mid-Morning Snack
- (same fields)

### Lunch
- (same fields)

### Afternoon Snack
- (same fields)

### Dinner
- (same fields)

### Bedtime (optional)
- (same fields)

## Daily Totals
- **Energy**: ~<kcal> kcal vs target ~<kcal>
- **Protein**: ~<g> g vs target ~<g>
- **Coverage note**: <one line on whether targets are met or where gaps remain>

## Why This Plan Fits the Patient
- <bullet linking a meal choice to a clinical category, e.g. "Obese Class I — modest energy deficit avoided during active chemo per [ESPEN B3-2]">
- <bullet on treatment-specific consideration>
- <bullet on side-effect mitigation>
- <bullet on dietary-preference / cultural fit>

## Citations
- **ESPEN sections used**: list each with one-line description (e.g. "[ESPEN B2-1] Energy: 25–30 kcal/kg/day", "[ESPEN R4] Protein up to 2 g/kg/d safe in normal renal function").
- **Knowledge-base sources used**: list as "[Source N] <short title or summary>".
"""


# ESPEN guideline files live in the backend's data directory. We lazy-load
# them here as a production fallback so that nutrition responses are
# ESPEN-grounded even when the caller didn't pre-populate
# context.metadata["espen_guidelines"] (the test driver does, the live
# pipeline doesn't yet).
_ESPEN_DEFAULT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "EspenGuideline"
)
_ESPEN_MAX_CHARS = 6000

# The structured nutrition knowledge base (despite its filename, it covers
# the full set of ESPEN-derived nutrition decisions: energy, protein,
# macros, vitamins, intervention escalation, exercise, pharmaconutrients,
# patient subgroups, safety, and the agent pseudocode). It is exposed as
# its own focused prompt block via ``_load_espen_nutrition_kb_block``
# below so the reasoning agent can walk its decision rules step-by-step
# when computing every nutrition target. We exclude it from the general
# guideline dump to avoid duplication.
_ESPEN_NUTRITION_KB_FILENAME = "ESPEN-Energy-KnowledgeBase.json"
# Sized to fit every clinically-actionable section after pruning the
# redundant ``all_recommendations_index`` (full pruned content
# ≈ 61 KB / ~15 K tokens). If new content tips the file over the
# budget, ``patient_subgroups`` (the largest reference section) is
# truncated last by virtue of dict insertion order below.
_ESPEN_NUTRITION_KB_MAX_CHARS = 64000


@lru_cache(maxsize=1)
def _load_espen_guidelines_block(max_chars: int = _ESPEN_MAX_CHARS) -> str:
    """Concatenate every ESPEN file under data/EspenGuideline/ into one
    prompt-ready string, truncated to max_chars. Cached for the process.
    Returns an empty string if the directory is missing or empty.

    The structured nutrition KB file is intentionally skipped — it is
    surfaced as its own dedicated block via
    ``_load_espen_nutrition_kb_block``.
    """
    if not _ESPEN_DEFAULT_DIR.is_dir():
        logger.warning("ESPEN directory not found at %s", _ESPEN_DEFAULT_DIR)
        return ""

    parts: List[str] = []
    for child in sorted(_ESPEN_DEFAULT_DIR.iterdir()):
        if not child.is_file():
            continue
        if child.name == _ESPEN_NUTRITION_KB_FILENAME:
            continue
        try:
            if child.suffix.lower() == ".json":
                with child.open("r", encoding="utf-8") as f:
                    body = json.dumps(json.load(f), ensure_ascii=False, indent=2)
            else:
                body = child.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning("Failed to load ESPEN file %s: %s", child, e)
            continue
        parts.append(f"--- {child.name} ---\n{body.strip()}")

    if not parts:
        return ""

    text = "\n\n".join(parts).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return text


@lru_cache(maxsize=1)
def _load_espen_nutrition_kb_block(
    max_chars: int = _ESPEN_NUTRITION_KB_MAX_CHARS,
) -> str:
    """Load and prune the structured ESPEN nutrition knowledge base into
    a focused, citation-rich prompt block.

    Despite the file name, this KB covers the FULL set of ESPEN-derived
    decisions the reasoning agent needs to translate patient medical
    parameters into a meal plan: definitions, mandatory inputs, screening
    + assessment thresholds (muscle mass / weight loss / handgrip /
    waist / inflammation), energy / protein / macronutrient / vitamin
    requirements, intervention escalation logic (oral → ONS → EN → PN),
    exercise prescription, pharmaconutrients (corticosteroids, n-3 fatty
    acids, prokinetics, ...), patient-subgroup overrides (surgery / RT /
    CHT / HCT / survivors / advanced / terminal), safety guards
    (refeeding syndrome, contraindications), the consolidated
    recommendations index, and the agent pseudocode for energy /
    protein / macros / feeding-route / subgroup dispatch.

    The few sections that are pure metadata or audit-only are dropped to
    keep the prompt focused. Returns an empty string if the file is
    missing or unreadable.
    """
    path = _ESPEN_DEFAULT_DIR / _ESPEN_NUTRITION_KB_FILENAME
    if not path.is_file():
        logger.warning("ESPEN nutrition KB not found at %s", path)
        return ""
    try:
        with path.open("r", encoding="utf-8") as f:
            kb = json.load(f)
    except Exception as e:
        logger.warning("Failed to parse ESPEN nutrition KB %s: %s", path, e)
        return ""

    document_metadata = kb.get("document_metadata", {}) or {}

    # Whitelist of clinically-actionable sections, ORDERED by priority
    # (most action-critical first) so that if any future content tips
    # over the char budget, only the lowest-priority reference sections
    # are truncated. ``all_recommendations_index`` is intentionally
    # dropped — it's a redundant index of rules whose details already
    # live in the per-section objects.
    pruned: Dict[str, Any] = {
        "source": {
            "preferred_citation_short": document_metadata.get(
                "preferred_citation_short"
            ),
            "preferred_citation_full": document_metadata.get(
                "preferred_citation_full"
            ),
            "doi": document_metadata.get("doi"),
            "url": document_metadata.get("url"),
        },
        # Agent pseudocode FIRST — this is the step-by-step decision
        # tree the model walks for every target. Must never be
        # truncated.
        "reasoning_logic_for_agent": kb.get("reasoning_logic_for_agent"),
        "definitions": kb.get("definitions"),
        "assessment_inputs": kb.get("assessment_inputs"),
        "screening": kb.get("screening"),
        # Core targets next — energy / protein / macros / vitamins.
        "energy_requirements": kb.get("energy_requirements"),
        "protein_requirements": kb.get("protein_requirements"),
        "macronutrient_composition": kb.get("macronutrient_composition"),
        "vitamins_and_minerals": kb.get("vitamins_and_minerals"),
        # Intervention escalation + safety guards.
        "intervention_decision_logic": kb.get("intervention_decision_logic"),
        "safety": kb.get("safety"),
        # Supplementary (still actionable, smaller impact on the meal
        # plan): exercise, pharmaconutrients, deeper assessment
        # thresholds, and finally the bulky patient-subgroup
        # overrides — placed last because it's the largest section
        # and the only one safe-ish to truncate if a future addition
        # blows past the budget.
        "exercise_recommendations": kb.get("exercise_recommendations"),
        "pharmaconutrients_and_drugs": kb.get("pharmaconutrients_and_drugs"),
        "assessment": kb.get("assessment"),
        "patient_subgroups": kb.get("patient_subgroups"),
    }
    pruned = {k: v for k, v in pruned.items() if v not in (None, {}, [])}

    if not pruned:
        return ""

    text = json.dumps(pruned, ensure_ascii=False, indent=2).strip()
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return text


def _format_clinical_categories_block(metadata: Optional[Dict[str, Any]]) -> str:
    """Render context.metadata['clinical_categories'] as a bullet block the
    LLM can read verbatim. Returns a fallback string when no categories
    have been computed yet.
    """
    if not metadata:
        return "(none — clinical categorization was not computed for this patient)"
    categories = metadata.get("clinical_categories") or {}
    if not isinstance(categories, dict) or not categories:
        return "(none — clinical categorization was not computed for this patient)"

    lines: List[str] = []
    for cat in categories.values():
        if not isinstance(cat, dict):
            continue
        unit = f" {cat['unit']}" if cat.get("unit") else ""
        risk = f" — risk: {cat['risk']}" if cat.get("risk") else ""
        lines.append(
            f"- {cat.get('metric')}: {cat.get('value')}{unit} "
            f"→ **{cat.get('label')}**{risk}"
        )
    return "\n".join(lines) if lines else (
        "(none — clinical categorization was not computed for this patient)"
    )


def _format_patient_data_block(metadata: Optional[Dict[str, Any]]) -> str:
    """Pick the best available patient data representation for the prompt:
       1. caller-supplied prerendered string (test driver path)
       2. flatten metadata['user_data'] dict (production path)
       3. fallback message
    """
    if not metadata:
        return "No structured patient data provided."

    pre_rendered = metadata.get("patient_data")
    if isinstance(pre_rendered, str) and pre_rendered.strip():
        return pre_rendered.strip()

    user_data = metadata.get("user_data") or {}
    if isinstance(user_data, dict) and user_data:
        bullets = [
            f"- {k.replace('_', ' ')}: {v}"
            for k, v in user_data.items()
            if v not in (None, "", [], {})
        ]
        if bullets:
            return "\n".join(bullets)

    return "No structured patient data provided."


# ================================
# Reasoning Agent Base
# ================================

class ReasoningAgent(BaseAgent):
    """
    Base reasoning agent that generates responses using retrieved evidence.
    
    Uses the appropriate system prompt based on intent routing.
    Adapts response style based on patient stage.
    """
    
    # Per-intent generation budgets. The NUTRITION persona ships the entire
    # ESPEN nutrition KB (~64 KB) plus a step-by-step "Nutrition Target
    # Derivation" walkthrough and ``max_tokens=3000`` of output, which on
    # complex patients (severe malnutrition + refeeding gate + cachexia
    # + Stage IV palliative + many nutrition-impact symptoms) routinely
    # takes 60–120 s on Bedrock. Other intents are short-form and finish
    # well under 30 s. We pick the timeout per intent so we don't punish``
    # short responses with a 3-minute ceiling but also don't time out the
    # heaviest meal-plan calls.
    _DEFAULT_TIMEOUT_MS = 30000
    _NUTRITION_TIMEOUT_MS = 180000

    def __init__(
        self,
        agent_type: ReasoningAgentType,
        model_type: ModelType = ModelType.ACCURATE
    ):
        timeout_ms = (
            self._NUTRITION_TIMEOUT_MS
            if agent_type == ReasoningAgentType.NUTRITION
            else self._DEFAULT_TIMEOUT_MS
        )
        super().__init__(
            name=agent_type.value,
            model_type=model_type,
            timeout_ms=timeout_ms,
        )
        self.agent_type = agent_type
        self.base_prompt = get_agent_prompt(agent_type)
    
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Generate a response using retrieved evidence and patient context.
        
        Args:
            context: Pipeline context with intent, stage, and retrieval results
            
        Returns:
            Updated context with reasoning_result populated
        """
        logger.info(f"ReasoningAgent ({self.agent_type.value}) generating response...")
        
        # Get intent and check if strict RAG is required
        intent = context.intent_result.intent if context.intent_result else IntentCategory.UNKNOWN
        strict_mode = is_strict_rag(intent)
        citation_only_mode = is_citation_only(intent)
        
        # Check if we have sufficient evidence
        has_evidence = (
            context.retrieval_result and 
            context.retrieval_result.sufficient_evidence and
            len(context.retrieval_result.chunks) > 0
        )
        
        if not has_evidence and strict_mode:
            # Only abstain if strict RAG is required
            context.reasoning_result = self._create_abstention_result(context)
            logger.info(f"Abstaining due to insufficient evidence (strict_rag=True for {intent})")
            return context
        
        # CITATION-ONLY MODE: Use LLM for selection/presentation, but enforce verbatim quotes
        if citation_only_mode:
            logger.info(f"Citation-only mode for {intent}: LLM will select and present verbatim quotes")
        
        # If not strict mode and no evidence, we'll use LLM general knowledge
        if not has_evidence:
            logger.info(f"No KB evidence but strict_rag=False for {intent}, using LLM general knowledge")
        
        try:
            # Build the prompts
            system_prompt = self._build_system_prompt(context)
            user_prompt = await self._build_user_prompt(context)
            
            # Nutrition meal plans need extra room for macros + micros + 5–6
            # meals + citations. Other intents are unaffected by the bump.
            intent_for_budget = (
                context.intent_result.intent if context.intent_result
                else IntentCategory.UNKNOWN
            )
            max_tokens = (
                3000 if intent_for_budget == IntentCategory.NUTRITION else 1500
            )

            response_text = await self.invoke_llm(
                system_prompt=system_prompt,
                user_message=user_prompt,
                temperature=0.4,  # Balanced creativity/consistency
                max_tokens=max_tokens,
            )
            
            # Extract citations from chunks (if available)
            citations = []
            if context.retrieval_result and context.retrieval_result.chunks:
                citations = [
                    Citation(
                        source_file=c.get("source_file", "Unknown"),
                        section=c.get("section"),
                        page_start=c.get("page_start"),
                        page_end=c.get("page_end"),
                        relevance_score=c.get("relevance_score", 0.0)
                    )
                    for c in get_citations_from_chunks(context.retrieval_result.chunks)
                ]
            
            context.reasoning_result = ReasoningResult(
                response_text=response_text,
                citations=citations,
                abstained=False,
                confidence=self._calculate_confidence(context),
                agent_type=self.agent_type.value
            )
            
            logger.info(
                f"Response generated: {len(response_text)} chars, "
                f"{len(citations)} citations"
            )
            
        except Exception as e:
            logger.error(f"Reasoning failed: {e}")
            context.reasoning_result = ReasoningResult(
                response_text=SAFE_FALLBACK_RESPONSE,
                citations=[],
                abstained=True,
                abstention_reason=f"Generation error: {str(e)}",
                confidence=0.0,
                agent_type=self.agent_type.value
            )
        
        return context
    
    def _build_system_prompt(self, context: PipelineContext) -> str:
        """Build the system prompt with context."""
        # Get intent and mode settings
        intent = IntentCategory.UNKNOWN
        if context.intent_result:
            intent = context.intent_result.intent
        strict_mode = is_strict_rag(intent)
        citation_only_mode = is_citation_only(intent)
        
        # Get stage guidelines
        stage = PatientStage.UNKNOWN
        if context.stage_result:
            stage = context.stage_result.stage
        
        stage_info = get_stage_guidelines(stage)
        stage_guidelines = (
            f"- Tone: {stage_info.get('tone', 'warm and supportive')}\n"
            f"- Emphasize: {stage_info.get('emphasis', 'general support')}\n"
            f"- Avoid: {stage_info.get('avoid', 'making assumptions')}"
        )
        
        # Format evidence (PDF sources only - videos are shown separately in UI)
        # For citation_only mode, use verbatim source text; otherwise use derived answers
        evidence_context = "No evidence retrieved from knowledge base."
        if context.retrieval_result and context.retrieval_result.chunks:
            evidence_context = format_chunks_for_prompt(
                context.retrieval_result.chunks,
                max_chars=6000,  # Leave room for rest of prompt
                use_citation_only=citation_only_mode
            )
        
        # Note: Video suggestions are NOT included in prompt - they appear in UI only
        # This ensures the answer text only references approved PDF content
        
        # Add intent-specific rules
        additional_rules = self._get_additional_rules(context)
        
        # Determine if disclaimer needed
        disclaimer_instruction = ""
        if is_medical_intent(intent):
            disclaimer_instruction = (
                f"\nIMPORTANT: End your response with this disclaimer:\n"
                f'"{MEDICAL_DISCLAIMER}"'
            )
        
        # Choose template based on mode
        if citation_only_mode:
            template = REASONING_CITATION_TEMPLATE
            mode_name = "CITATION-ONLY"
        elif strict_mode:
            template = REASONING_STRICT_TEMPLATE
            mode_name = "STRICT"
        else:
            template = REASONING_FLEXIBLE_TEMPLATE
            mode_name = "FLEXIBLE"
        
        logger.debug(f"Using {mode_name} mode for intent: {intent}")
        
        # Citation template doesn't use additional_rules or video suggestions
        if citation_only_mode:
            return template.format(
                agent_prompt=self.base_prompt,
                stage_guidelines=stage_guidelines,
                evidence_context=evidence_context,
                disclaimer_instruction=disclaimer_instruction
            )
        
        return template.format(
            agent_prompt=self.base_prompt,
            stage_guidelines=stage_guidelines,
            evidence_context=evidence_context,
            additional_rules=additional_rules,
            disclaimer_instruction=disclaimer_instruction
        )
    
    async def _build_user_prompt(self, context: PipelineContext) -> str:
        """Build the user prompt with question and context."""
        # Get basic stage info
        stage = PatientStage.UNKNOWN
        stage_certainty = "unknown"
        if context.stage_result:
            stage = context.stage_result.stage
            stage_certainty = context.stage_result.certainty
        
        # Build stage context
        stage_context = ""
        
        try:
             # Use PatientStageService for RAG context
            from services.patient_stage_service import get_patient_stage_service
            stage_service = get_patient_stage_service()
            
            target_stage_id = None
            
            # 1. Prefer explicit override from metadata (e.g. detailed navigation)
            if hasattr(context, 'metadata') and context.metadata and context.metadata.get('detailed_stage_id'):
                target_stage_id = context.metadata.get('detailed_stage_id')
                
            # 2. Fallback to user profile if authenticated
            elif context.user_id:
                from services.patient_profile_service import get_patient_profile_service
                profile_service = get_patient_profile_service()
                # Async get_profile
                profile = await profile_service.get_profile(context.user_id)
                if profile:
                    target_stage_id = profile.current_stage_id
            
            # 3. If we have a target ID, get the rich context
            if target_stage_id:
                stage_context = stage_service.get_rag_context(target_stage_id)
            else:
                # 4. Fallback to signal string if no specific stage ID
                if context.stage_result and context.stage_result.signals:
                    stage_context = f"Stage signals: {', '.join(context.stage_result.signals)}"
                    
        except Exception as e:
            logger.warning(f"Stage context generation failed: {e}")
            if context.stage_result and context.stage_result.signals:
                stage_context = f"Stage signals: {', '.join(context.stage_result.signals)}"
        
        # Determine certainty string
        certainty_str = stage_certainty.value if hasattr(stage_certainty, 'value') else str(stage_certainty)

        # Build a short summary of mandatory user profile fields (if provided),
        # plus any pre-classified clinical categories StageAgent attached. The
        # categories are AUTHORITATIVE (computed from configured thresholds);
        # the LLM should use these labels verbatim instead of re-deriving them.
        user_profile_context = "No additional details available."
        try:
            if context.metadata:
                lines: List[str] = []

                user_data = context.metadata.get("user_data") or {}
                if isinstance(user_data, dict) and user_data:
                    if user_data.get("weight") is not None:
                        lines.append(f"- Weight: {user_data.get('weight')} kg")

                categories_block = _format_clinical_categories_block(context.metadata)
                if not categories_block.startswith("(none"):
                    lines.append(
                        "- Pre-classified clinical categories "
                        "(authoritative — use these labels verbatim):"
                    )
                    for entry in categories_block.split("\n"):
                        lines.append("    " + entry)

                if lines:
                    user_profile_context = "\n".join(lines)
        except Exception as e:
            logger.warning(f"Failed to format user profile context: {e}")

        # Nutrition path: route to the comprehensive ESPEN-grounded template
        # whenever this is a NUTRITION reasoning call. ESPEN guidelines come
        # from metadata if pre-loaded (test driver), otherwise we lazy-load
        # them from data/EspenGuideline/ so production responses are
        # ESPEN-grounded too.
        intent = (
            context.intent_result.intent if context.intent_result
            else IntentCategory.UNKNOWN
        )
        if intent == IntentCategory.NUTRITION:
            try:
                espen_block = ""
                if context.metadata:
                    raw = context.metadata.get("espen_guidelines")
                    if isinstance(raw, str) and raw.strip():
                        espen_block = raw.strip()
                if not espen_block:
                    espen_block = _load_espen_guidelines_block()
                if not espen_block:
                    espen_block = (
                        "(ESPEN guideline reference unavailable — fall back "
                        "to the standard ~25–30 kcal/kg/day energy and "
                        "1.0–1.5 g/kg/day protein targets and flag the gap "
                        "in the response.)"
                    )

                # Dedicated, pruned ESPEN nutrition KB block. Caller
                # override first (test driver / orchestrator), then the
                # focused on-disk loader pulls every clinically-actionable
                # subtree from ESPEN-Energy-KnowledgeBase.json (energy /
                # protein / macros / vitamins / intervention logic /
                # exercise / pharmaconutrients / patient subgroups /
                # safety / agent pseudocode) so the model can walk its
                # decision rules step-by-step.
                nutrition_kb_block = ""
                if context.metadata:
                    raw_kb = context.metadata.get("espen_nutrition_kb")
                    if isinstance(raw_kb, str) and raw_kb.strip():
                        nutrition_kb_block = raw_kb.strip()
                if not nutrition_kb_block:
                    nutrition_kb_block = _load_espen_nutrition_kb_block()
                if not nutrition_kb_block:
                    nutrition_kb_block = (
                        "(ESPEN nutrition KB unavailable — fall back to "
                        "the standard ~25–30 kcal/kg/day energy [ESPEN "
                        "B2-1] and 1.0–1.5 g/kg/day protein [ESPEN "
                        "B2-2] targets, ~50–60% CHO / 25–35% fat split "
                        "(fat-shifted if weight-losing + insulin-"
                        "resistant per [ESPEN B2-3]), RDA-level "
                        "vitamins/minerals [ESPEN B2-4], oral "
                        "counselling → ONS → EN → PN escalation "
                        "[ESPEN B3-3], and refeeding-syndrome guards "
                        "[ESPEN B3-4]; flag the gap in the response.)"
                    )

                patient_data_block = _format_patient_data_block(context.metadata)
                clinical_categories_block = _format_clinical_categories_block(
                    context.metadata
                )

                return REASONING_NUTRITION_USER_TEMPLATE.format(
                    question=context.user_message,
                    stage=stage,
                    stage_certainty=certainty_str,
                    stage_context=stage_context,
                    patient_data_block=patient_data_block,
                    clinical_categories_block=clinical_categories_block,
                    nutrition_kb_block=nutrition_kb_block,
                    espen_block=espen_block,
                )
            except Exception as e:
                logger.warning(
                    "Nutrition template build failed (%s); "
                    "falling back to default user template.",
                    e,
                )

        conversation_history = self._format_conversation_history(
            context.conversation_history
        )

        return REASONING_USER_TEMPLATE.format(
            conversation_history=conversation_history,
            question=context.user_message,
            stage=stage,
            stage_certainty=certainty_str,
            stage_context=stage_context,
            user_profile_context=user_profile_context,
        )

    def _format_conversation_history(self, history: list) -> str:
        """Format recent conversation for the reasoning prompt."""
        if not history:
            return "No previous conversation."

        recent = history[-6:] if len(history) > 6 else history
        lines = []
        for msg in recent:
            role = msg.get("role", "user")
            label = "Patient" if role == "user" else "Assistant"
            content = msg.get("content", "")[:500]
            if content:
                lines.append(f"{label}: {content}")
        return "\n".join(lines) if lines else "No previous conversation."
    
    def _get_additional_rules(self, context: PipelineContext) -> str:
        """Get intent-specific additional rules."""
        intent = IntentCategory.UNKNOWN
        if context.intent_result:
            intent = context.intent_result.intent
        
        rules = {
            IntentCategory.SAFETY_RED_FLAGS: (
                "7. If describing emergency symptoms, ALWAYS advise seeking immediate medical care.\n"
                "8. Do not minimize potentially serious symptoms.\n"
                "9. Provide clear guidance on when to call emergency services."
            ),
            IntentCategory.MEDICATION_INFO: (
                "7. Never recommend specific medications or dosages.\n"
                "8. Always defer to the prescriber's instructions.\n"
                "9. Emphasize importance of taking medications as prescribed."
            ),
            IntentCategory.STATISTICS: (
                "7. Emphasize that statistics are population-level, not individual predictions.\n"
                "8. Present data with appropriate context about limitations.\n"
                "9. Be honest but not discouraging."
            ),
            IntentCategory.EMOTIONAL_SUPPORT: (
                "7. Lead with empathy and validation.\n"
                "8. Normalize the patient's feelings.\n"
                "9. Suggest professional support resources when appropriate."
            ),
            IntentCategory.NUTRITION: (
                "7. Provide practical, actionable food suggestions.\n"
                "8. Consider common treatment side effects (nausea, taste changes).\n"
                "9. Keep recipes and suggestions simple and accessible.\n"
                "10. Always show the FULL ESPEN-aligned daily nutrition targets "
                "(energy, protein, carbs, fat, fiber, fluids, key micronutrients) "
                "computed from the patient's weight before listing meals.\n"
                "11. The ESPEN NUTRITION KB block is AUTHORITATIVE for ALL "
                "nutrition targets and care decisions \u2014 energy, protein, "
                "macronutrient split, vitamins/minerals, intervention "
                "escalation, exercise, pharmaconutrients, patient-subgroup "
                "overrides, and safety. You MUST walk its decision rules in "
                "order for EACH target (refeeding gate \u2192 energy rule "
                "\u2192 cachexia/inflammation modifier \u2192 protein rule "
                "by kidney function/age/inflammation \u2192 macronutrient "
                "split \u2192 vitamins \u2192 intervention level \u2192 "
                "pharmaconutrients \u2192 subgroup override \u2192 safety "
                "guards \u2192 titration plan), show which rule fired and "
                "the arithmetic in the \"Nutrition Target Derivation\" "
                "section, and cite the exact recommendation_id from the KB "
                "next to every claim (e.g. \"[ESPEN B2-1]\", \"[ESPEN "
                "B2-2]\", \"[ESPEN B2-3]\", \"[ESPEN B2-4]\", \"[ESPEN "
                "B3-3]\", \"[ESPEN B3-4]\", \"[ESPEN B5-7]\", \"[ESPEN "
                "C3-2]\").\n"
                "12. Cite ESPEN recommendation IDs INLINE next to every "
                "nutrition claim or target, and cite retrieval-KB chunks "
                "as \"[Source N]\". Do not aggregate citations only at the "
                "end.\n"
                "13. Use the pre-classified clinical category labels verbatim "
                "(e.g. \"Obese Class I\", \"Central Obesity\") \u2014 never "
                "re-derive them from raw measurements.\n"
                "14. Personalize ingredients to the patient's region / dietary "
                "pattern / cultural preferences; avoid foods listed as "
                "allergies, intolerances or treatment-incompatible (e.g. "
                "grapefruit on Tamoxifen)."
            ),
        }
        
        return rules.get(intent, "")
    
    def _calculate_confidence(self, context: PipelineContext) -> float:
        """Calculate response confidence based on evidence quality."""
        base_confidence = 0.7
        
        if context.retrieval_result:
            # Boost for more chunks above threshold
            above_threshold = context.retrieval_result.above_threshold
            if above_threshold >= 5:
                base_confidence += 0.15
            elif above_threshold >= 3:
                base_confidence += 0.1
            elif above_threshold >= 2:
                base_confidence += 0.05
        
        if context.intent_result:
            # Boost for high intent confidence
            if context.intent_result.confidence >= 0.85:
                base_confidence += 0.05
        
        if context.stage_result:
            # Boost for high stage certainty
            if context.stage_result.certainty == CertaintyLevel.HIGH:
                base_confidence += 0.05
        
        return min(base_confidence, 0.95)
    
    def _create_abstention_result(self, context: PipelineContext) -> ReasoningResult:
        """Create an abstention result when evidence is insufficient."""
        intent = IntentCategory.UNKNOWN
        if context.intent_result:
            intent = context.intent_result.intent
        
        # Customize abstention message based on intent
        abstention_messages = {
            IntentCategory.NUTRITION: (
                "I don't have enough specific nutrition information to answer your question confidently. "
                "For personalized dietary advice, please speak with your oncology dietitian or care team."
            ),
            IntentCategory.MEDICATION_INFO: (
                "I don't have sufficient information about this medication in my knowledge base. "
                "Please consult your pharmacist or prescribing doctor for accurate medication information."
            ),
            IntentCategory.SAFETY_RED_FLAGS: (
                "If you're experiencing concerning symptoms, please don't wait for my response. "
                "Contact your care team immediately or go to the emergency room if symptoms are severe."
            ),
        }
        
        default_message = (
            "I don't have enough reliable information to answer this question confidently. "
            "For accurate information about your specific situation, please consult your healthcare team."
        )
        
        return ReasoningResult(
            response_text=abstention_messages.get(intent, default_message),
            citations=[],
            abstained=True,
            abstention_reason="Insufficient evidence in knowledge base",
            confidence=0.0,
            agent_type=self.agent_type.value
        )
    
    def _build_citation_only_response(self, context: PipelineContext) -> ReasoningResult:
        """
        Build a response using ONLY verbatim text from sources.
        No LLM paraphrasing - returns exact quotes with source links.
        """
        chunks = context.retrieval_result.chunks if context.retrieval_result else []
        
        if not chunks:
            return self._create_abstention_result(context)
        
        # Build response with verbatim text and source citations
        response_parts = []
        citations = []
        seen_content = set()
        
        for i, chunk in enumerate(chunks[:5], 1):  # Limit to top 5 sources
            # Get the verbatim text (source_excerpt if available, else content)
            content = chunk.content.strip()
            
            # Skip duplicates
            content_key = content[:100]
            if content_key in seen_content:
                continue
            seen_content.add(content_key)
            
            # Extract just the answer part if it's a Q&A format
            answer_text = content
            if "Answer:" in content:
                parts = content.split("Answer:", 1)
                if len(parts) > 1:
                    answer_text = parts[1].strip()
            
            # Format source info for hyperlink
            source_file = chunk.source_file or "Source"
            source_name = source_file.replace(".pdf", "").replace("-", " ").replace("_", " ")
            if len(source_name) > 40:
                source_name = source_name[:37] + "..."
            
            page_info = ""
            if chunk.page_start:
                page_info = f" (p.{chunk.page_start}"
                if chunk.page_end and chunk.page_end != chunk.page_start:
                    page_info = f" (pp.{chunk.page_start}-{chunk.page_end}"
                page_info += ")"
            
            # Format: verbatim text with source link icon
            # Using markdown link format: [📄](source_url)
            # Use actual source_url from metadata if available, otherwise fall back to source_file
            source_url = chunk.metadata.get("source_url") or chunk.source_file or "#"
            source_link = f"[📄 {source_name}{page_info}]({source_url})"
            
            response_parts.append(f"{answer_text}\n\n*Source: {source_link}*")
            
            # Add citation
            citations.append(Citation(
                source_file=chunk.source_file or "Unknown",
                section=chunk.section,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                relevance_score=chunk.score
            ))
        
        # Join all verbatim quotes
        if len(response_parts) > 1:
            response_text = "\n\n---\n\n".join(response_parts)
        else:
            response_text = response_parts[0] if response_parts else "No information found."
        
        logger.info(f"Citation-only response: {len(response_parts)} sources, {len(response_text)} chars")
        
        return ReasoningResult(
            response_text=response_text,
            citations=citations,
            abstained=False,
            confidence=0.95,  # High confidence for verbatim quotes
            agent_type=self.agent_type.value
        )
    
    def _get_output_summary(self, context: PipelineContext) -> Optional[str]:
        """Generate output summary for logging."""
        if context.reasoning_result:
            r = context.reasoning_result
            return (
                f"abstained={r.abstained}, "
                f"confidence={r.confidence:.2f}, "
                f"chars={len(r.response_text)}"
            )
        return None


# ================================
# Agent Factory
# ================================

class ReasoningAgentFactory:
    """
    Factory for creating reasoning agents based on intent.
    
    Uses the routing configuration to determine which agent type
    and model to use for each intent.
    """
    
    _cache: Dict[ReasoningAgentType, ReasoningAgent] = {}
    
    @classmethod
    def get_agent(cls, intent: IntentCategory) -> ReasoningAgent:
        """
        Get or create a reasoning agent for the given intent.
        
        Args:
            intent: The classified intent category
            
        Returns:
            Appropriate ReasoningAgent instance
        """
        # Get routing config
        route = get_route_for_intent(intent)
        agent_type = route.agent_type
        model_type = route.model_type
        
        # Check cache
        if agent_type not in cls._cache:
            cls._cache[agent_type] = ReasoningAgent(
                agent_type=agent_type,
                model_type=model_type
            )
            logger.info(f"Created new ReasoningAgent: {agent_type.value}")
        
        return cls._cache[agent_type]
    
    @classmethod
    def clear_cache(cls):
        """Clear the agent cache."""
        cls._cache.clear()


# ================================
# Convenience Function
# ================================

def get_reasoning_agent(intent: IntentCategory) -> ReasoningAgent:
    """Get a reasoning agent for the given intent."""
    return ReasoningAgentFactory.get_agent(intent)

