"""Driver: generate a personalized one-day meal plan using the Nutrition reasoning agent.

This script bypasses the IntentAgent (we hardcode the intent as NUTRITION) and
runs the retrieval + reasoning agents directly, injecting:

  * ESPEN oncology nutrition guidelines (authoritative reference)
  * Structured patient data (personalization)

The reasoning agent (``ReasoningAgent`` running with the ``NUTRITION`` persona)
picks up both from ``context.metadata`` and produces a breakfast / mid-morning
snack / lunch / afternoon snack / dinner plan with approximate kcal + protein
per meal, grounded in ESPEN targets and the patient's specifics.

Usage:
    python -m tests.nutrition_meal_plan
    python -m tests.nutrition_meal_plan --patient path/to/patient.json --espen path/to/espen.pdf
    python -m tests.nutrition_meal_plan --question "What should I eat today during chemo?"

Supported input formats (auto-detected by extension):
    .json              -> parsed into a dict
    .txt / .md / .csv  -> loaded as plain text
    .pdf               -> text extracted via pypdf (if installed)
    anything else      -> read as UTF-8 text
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure the backend package root is importable when running as a script.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from config.pipeline_config import (  # noqa: E402
    CertaintyLevel,
    IntentCategory,
    PatientStage,
)
from models.schemas import (  # noqa: E402
    IntentResult,
    PipelineContext,
    StageResult,
)
from services.agents.reasoning_agent import get_reasoning_agent  # noqa: E402
from services.agents.retrieval_agent import RetrievalAgent  # noqa: E402
from services.agents.stage_agent_v2 import StageAgentV2  # noqa: E402


# ============================================================================
# Default data paths (override with --patient / --espen on the CLI).
# Both paths may be absolute or relative to the backend root
# (``HeathCareAI-Backend/``).
#
# ``ESPEN_GUIDELINES_PATH`` can be a single file OR a directory. When it's a
# directory, every supported file inside (``.json``, ``.pdf``, ``.txt``,
# ``.md``, ``.csv``) is loaded and concatenated with file-name headers before
# being fed to the reasoning agent.
# ============================================================================

PATIENT_DATA_PATH: str = "data/PatientData/Patient_JSON_Records/IN-BC-4002.json"
ESPEN_GUIDELINES_PATH: str = "data/EspenGuideline"

# Despite its file name, the structured ESPEN nutrition KB covers the
# FULL set of nutrition decisions (energy, protein, macros, vitamins,
# intervention escalation, exercise, pharmaconutrients, patient-subgroup
# overrides, safety, plus agent pseudocode). We feed it to the reasoning
# agent as its OWN focused metadata channel (``espen_nutrition_kb``) so
# the agent can walk its decision rules step-by-step. We also exclude it
# from the general guidelines block to avoid duplication.
ESPEN_NUTRITION_KB_FILENAME: str = "ESPEN-Energy-KnowledgeBase.json"

# Default question to ask the nutrition agent.
#
# We include a brief journey-stage hint ("undergoing AC-T adjuvant chemotherapy")
# so the production StageAgentV2 LLM classifier has something concrete to
# anchor on — otherwise it returns ``unknown`` for a generic meal-plan
# request and the meal plan loses its stage-aware personalization. Override
# with ``--question`` for ad-hoc experiments.
DEFAULT_QUESTION: str = (
    "I'm currently undergoing AC-T adjuvant chemotherapy for breast cancer. "
    "Please design a one-day meal plan for me that fits ESPEN oncology "
    "nutrition guidelines and my current situation."
)

# Default directory (relative to HeathCareAI-Backend/) where generated meal
# plans are written. Each run creates a timestamped markdown file inside this
# folder. Override with ``--save <path>`` or disable with ``--no-save``.
DEFAULT_OUTPUT_DIR: str = "tests/meal_plans"


logger = logging.getLogger("nutrition_meal_plan")


# ============================================================================
# File loading helpers
# ============================================================================

def _resolve_path(path_str: str) -> Path:
    """Resolve a path, allowing it to be relative to the backend root."""
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = (_BACKEND_ROOT / p).resolve()
    return p


def _load_pdf_text(path: Path) -> str:
    """Extract text from a PDF using pypdf if available, else fail gracefully."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                f"PDF support requires 'pypdf' (or 'PyPDF2'). "
                f"Install with: pip install pypdf  ({exc})"
            ) from exc

    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception as e:  # pragma: no cover
            logger.warning("Failed to extract page text from %s: %s", path, e)
    return "\n".join(parts).strip()


_SUPPORTED_EXTS = {".json", ".pdf", ".txt", ".md", ".csv"}


def _load_single_file(path: Path) -> Any:
    """Load one file, returning a dict for JSON and a str for everything else."""
    ext = path.suffix.lower()
    if ext == ".json":
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    if ext == ".pdf":
        return _load_pdf_text(path)
    # Default: treat as text (txt / md / csv / unknown).
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def load_file(path_str: str, label: str) -> Any:
    """Load a patient/ESPEN file or directory, auto-detecting format.

    * Single file -> ``dict`` (JSON) or ``str`` (everything else).
    * Directory   -> ``str`` built by concatenating every supported file
                     inside with ``--- <filename> ---`` headers.
    """
    path = _resolve_path(path_str)
    if not path.exists():
        raise FileNotFoundError(
            f"{label} file not found at: {path}\n"
            f"Update the default at the top of this script or pass --patient/--espen."
        )

    if path.is_dir():
        children = sorted(
            p for p in path.iterdir()
            if p.is_file()
            and p.suffix.lower() in _SUPPORTED_EXTS
            # The structured nutrition KB is fed to the reasoning agent
            # via its own dedicated ``espen_nutrition_kb`` metadata
            # channel — exclude it from the general guidelines block
            # so the same content isn't duplicated in the prompt.
            and p.name != ESPEN_NUTRITION_KB_FILENAME
        )
        if not children:
            raise FileNotFoundError(
                f"{label} directory contains no supported files "
                f"({', '.join(sorted(_SUPPORTED_EXTS))}): {path}"
            )

        parts: List[str] = []
        for child in children:
            loaded = _load_single_file(child)
            if isinstance(loaded, (dict, list)):
                try:
                    body = json.dumps(loaded, ensure_ascii=False, indent=2)
                except Exception:
                    body = str(loaded)
            else:
                body = str(loaded).strip()
            parts.append(f"--- {child.name} ---\n{body}")
        return "\n\n".join(parts)

    return _load_single_file(path)


def _load_espen_nutrition_kb_text(espen_path_str: str) -> Optional[str]:
    """Locate the structured nutrition KB and return it as a JSON string,
    or ``None`` if it can't be found.

    Looks for ``ESPEN-Energy-KnowledgeBase.json`` next to the resolved
    ``--espen`` path:
      * if ``--espen`` is a directory, search inside it,
      * if ``--espen`` is a file, search alongside it,
      * always fall back to the project default at
        ``data/EspenGuideline/<filename>``.
    Returns the file contents as JSON-pretty text so the reasoning
    agent can drop it straight into the prompt.
    """
    candidates: List[Path] = []
    resolved = _resolve_path(espen_path_str)
    if resolved.is_dir():
        candidates.append(resolved / ESPEN_NUTRITION_KB_FILENAME)
    elif resolved.is_file():
        candidates.append(resolved.parent / ESPEN_NUTRITION_KB_FILENAME)
    candidates.append(
        _resolve_path(f"data/EspenGuideline/{ESPEN_NUTRITION_KB_FILENAME}")
    )

    for candidate in candidates:
        if candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as f:
                    return json.dumps(
                        json.load(f), ensure_ascii=False, indent=2
                    )
            except Exception as e:
                logger.warning(
                    "Failed to parse ESPEN nutrition KB %s: %s",
                    candidate, e,
                )
                return None
    return None


# ============================================================================
# Prompt-block formatters
#
# The ReasoningAgent expects ``context.metadata["espen_guidelines"]`` and
# ``context.metadata["patient_data"]`` to be prompt-ready strings. This driver
# owns the conversion from raw file contents (dict/list/str) into those
# strings, so the agent itself stays a thin consumer.
# ============================================================================

ESPEN_MAX_CHARS: int = 6000  # Budget for the ESPEN block in the final prompt.


def format_espen_guidelines(espen: Any, max_chars: int = ESPEN_MAX_CHARS) -> str:
    """Render raw ESPEN guideline contents (str, list, or dict) into a
    prompt-safe block. Truncated to ``max_chars`` so the overall prompt still
    fits the model context window.
    """
    if not espen:
        return "No ESPEN guidelines were provided."

    if isinstance(espen, dict):
        try:
            text = json.dumps(espen, ensure_ascii=False, indent=2)
        except Exception:
            text = str(espen)
    elif isinstance(espen, list):
        text = "\n".join(str(x) for x in espen)
    else:
        text = str(espen)

    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return text


def format_patient_data(patient: Any, fallback: str = "") -> str:
    """Render raw patient data (dict or str) as a readable bullet list.

    Key lookup is case-insensitive so the function works with both the
    lowercase schema (``weight_kg``) and the PascalCase Indian dataset
    schema (``Weight_kg``, ``Cancer_Stage``, ``Treatment_Modality``, ...).
    """
    if not patient:
        return fallback or "No structured patient data provided."

    if isinstance(patient, str):
        return patient.strip()

    if not isinstance(patient, dict):
        return str(patient)

    # Preferred fields rendered first (lowercase, compared case-insensitively
    # against whatever the JSON actually uses). Covers both our generic schema
    # and the richer ``IN-BC-4xxx`` patient records.
    preferred_order = [
        # Identification
        "patient_id", "name",
        # Demographics
        "age", "sex", "gender",
        "region", "region_india", "socioeconomic_status",
        "dietary_pattern", "cuisine", "cultural_preferences",
        # Body metrics
        "height_cm", "height", "weight_kg", "weight",
        "bmi", "bmi_category_indian_icmr", "bmi_clinical_note",
        "waist_circumference_cm", "waist_risk_indian",
        "hand_grip_strength_kg", "grip_strength_category",
        # Diagnosis
        "cancer_type", "bc_subtype", "cancer_stage",
        "menopausal_status", "diagnosis", "stage",
        # Treatment
        "treatment_modality", "treatment", "current_treatment", "treatment_phase",
        "chemotherapy_regimen", "hormone_therapy", "surgery_type",
        "lymphedema_risk", "bone_density_concern",
        # Symptoms / nutritional status
        "nutrition_impact_symptoms", "symptoms", "side_effects",
        "pg_sga_score", "pg_sga_category", "nutritional_status",
        # Nutrition targets
        "total_energy_kcal_per_day", "energy_kcal_per_kg",
        "protein_g_per_day", "protein_g_per_kg",
        "fat_g_per_day", "carbohydrate_g_per_day", "fat_carb_ratio_note",
        "vitamin_d_iu_per_day", "calcium_mg_per_day", "iron_mg_per_day",
        "folate_mcg_per_day", "zinc_mg_per_day", "dietary_fibre_g_per_day",
        "omega3_recommendation", "protein_source_note", "soy_food_guidance",
        "alcohol_guidance", "fluid_intake_ml_per_day",
        "icmr_nin_2020_reference", "nutrition_route_espen",
        "supplement_recommendation", "exercise_plan_espen_india",
        "espen_guidelines_india", "diet_chart_indian_meal_plan",
        # Allergies / preferences / misc
        "allergies", "food_allergies", "intolerances",
        "dietary_preferences", "preferences", "dislikes",
        "comorbidities", "medications",
        "goals", "notes",
    ]

    def _render(orig_key: str, value: Any) -> Optional[str]:
        if value is None or value == "" or value == [] or value == {}:
            return None
        pretty_key = orig_key.replace("_", " ").strip()
        if isinstance(value, (list, tuple, set)):
            value_str = ", ".join(str(v) for v in value)
        elif isinstance(value, dict):
            value_str = ", ".join(f"{k}: {v}" for k, v in value.items())
        else:
            value_str = str(value)
        return f"- {pretty_key}: {value_str}"

    # Preserve the JSON's original keys in the output by mapping lowercased
    # key -> original key for case-insensitive lookup.
    lowered: Dict[str, str] = {k.lower(): k for k in patient.keys()}
    lines: List[str] = []
    seen_lower: set = set()

    for key in preferred_order:
        orig = lowered.get(key.lower())
        if not orig or orig.lower() in seen_lower:
            continue
        line = _render(orig, patient[orig])
        if line:
            lines.append(line)
        seen_lower.add(orig.lower())

    for orig_key, value in patient.items():
        if orig_key.lower() in seen_lower:
            continue
        line = _render(orig_key, value)
        if line:
            lines.append(line)
        seen_lower.add(orig_key.lower())

    return "\n".join(lines) if lines else "No usable patient data fields found."


# ============================================================================
# Context construction
# ============================================================================

def _ci_get(d: Dict[str, Any], *keys: str) -> Any:
    """Case-insensitive ``dict.get`` that returns the first truthy match."""
    if not isinstance(d, dict):
        return None
    lower_map = {k.lower(): k for k in d.keys()}
    for key in keys:
        orig = lower_map.get(key.lower())
        if orig is None:
            continue
        val = d[orig]
        if val not in (None, "", [], {}):
            return val
    return None


def _derive_stage(patient_data: Any) -> Tuple[PatientStage, CertaintyLevel]:
    """Best-effort mapping from patient data to PatientStage / CertaintyLevel.

    Journey stage (pre-diagnosis / active-treatment / etc.) is DIFFERENT from
    tumor stage (``Stage I/II/III/IV``). This helper first looks for an
    explicit journey-stage field, then falls back to keyword heuristics over
    the treatment-modality / regimen fields so that records like the
    ``IN-BC-4xxx`` dataset (which only carry ``Cancer_Stage`` +
    ``Treatment_Modality``) still map to a useful journey stage.
    """
    if not isinstance(patient_data, dict):
        return PatientStage.UNKNOWN, CertaintyLevel.LOW

    # 1) Explicit journey-stage field, if present.
    raw = _ci_get(patient_data, "journey_stage", "patient_stage")
    if raw:
        norm = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
        try:
            return PatientStage(norm), CertaintyLevel.HIGH
        except ValueError:
            alias = {
                "diagnosed": PatientStage.NEWLY_DIAGNOSED,
                "new_diagnosis": PatientStage.NEWLY_DIAGNOSED,
                "in_treatment": PatientStage.ACTIVE_TREATMENT,
                "on_treatment": PatientStage.ACTIVE_TREATMENT,
                "chemo": PatientStage.ACTIVE_TREATMENT,
                "chemotherapy": PatientStage.ACTIVE_TREATMENT,
                "radiation": PatientStage.ACTIVE_TREATMENT,
                "recovery": PatientStage.POST_TREATMENT,
                "follow_up": PatientStage.SURVEILLANCE,
                "followup": PatientStage.SURVEILLANCE,
            }
            mapped = alias.get(norm)
            if mapped:
                return mapped, CertaintyLevel.MEDIUM

    # 2) Keyword heuristic over treatment / modality fields.
    treatment_parts = [
        _ci_get(
            patient_data,
            "treatment_modality", "treatment", "current_treatment",
            "treatment_phase",
        ),
        _ci_get(patient_data, "chemotherapy_regimen"),
        _ci_get(patient_data, "hormone_therapy"),
    ]
    treatment_text = " ".join(str(v) for v in treatment_parts if v).lower()

    if treatment_text:
        if any(kw in treatment_text for kw in (
            "palliative", "end of life", "end-of-life",
        )):
            return PatientStage.PALLIATIVE_SUPPORT, CertaintyLevel.MEDIUM
        if any(kw in treatment_text for kw in (
            "chemo", "radiation", "radiotherapy",
            "adjuvant", "neoadjuvant",
            "on treatment", "in treatment", "active treatment",
            "surgery +",
        )):
            return PatientStage.ACTIVE_TREATMENT, CertaintyLevel.MEDIUM
        if any(kw in treatment_text for kw in (
            "post treatment", "post-treatment", "recovery",
        )):
            return PatientStage.POST_TREATMENT, CertaintyLevel.MEDIUM
        if any(kw in treatment_text for kw in (
            "surveillance", "follow-up", "follow up", "followup",
        )):
            return PatientStage.SURVEILLANCE, CertaintyLevel.MEDIUM
        if any(kw in treatment_text for kw in (
            "newly diagnosed", "new diagnosis",
        )):
            return PatientStage.NEWLY_DIAGNOSED, CertaintyLevel.MEDIUM

    logger.warning(
        "Unable to derive patient journey stage from data; defaulting to UNKNOWN."
    )
    return PatientStage.UNKNOWN, CertaintyLevel.LOW


def _extract_user_data(patient_data: Any) -> Dict[str, Any]:
    """Project the patient record into ``context.metadata['user_data']`` using
    the lowercase production schema (the same shape ``StageAgentV2`` produces).

    This is intentionally a *flattening / renaming* step only — no derivations,
    no categorizations. We feed raw measurements + demographics to downstream
    agents (StageAgent, RetrievalQueryBuilder, ReasoningAgent) and let them
    decide what to do with them (compute BMI, classify into ICMR buckets,
    build retrieval queries, …).

    Case-insensitive lookups so it works with both the lowercase production
    schema (``weight_kg``) and the PascalCase ``IN-BC-4xxx`` dataset
    (``Weight_kg``, ``Hand_Grip_Strength_kg``, …).
    """
    if not isinstance(patient_data, dict):
        return {}

    # (output_key, *source_aliases) — first non-empty wins.
    field_map: List[Tuple[str, Tuple[str, ...]]] = [
        # Demographics
        ("age", ("age", "age_years")),
        ("sex", ("sex", "gender")),
        # Body metrics (raw)
        ("weight", ("weight", "weight_kg")),
        ("height_cm", ("height_cm", "height")),
        ("bmi", ("bmi",)),
        ("waist_circumference_cm", ("waist_circumference_cm", "waist_cm")),
        ("hand_grip_strength_kg", ("hand_grip_strength_kg", "grip_strength_kg")),
        # Nutritional assessment
        ("pg_sga_score", ("pg_sga_score",)),
        # Diagnosis / treatment hints (used by StageAgent + retrieval query)
        ("cancer_type", ("cancer_type",)),
        ("cancer_stage", ("cancer_stage",)),
        ("treatment_modality", ("treatment_modality", "treatment", "current_treatment")),
        ("dietary_pattern", ("dietary_pattern", "dietary_preferences")),
    ]

    out: Dict[str, Any] = {}
    for out_key, aliases in field_map:
        value = _ci_get(patient_data, *aliases)
        if value is not None:
            out[out_key] = value
    return out


def build_nutrition_context(
    question: str,
    patient_data: Any,
    espen_guidelines: Any,
    espen_nutrition_kb: Optional[str] = None,
) -> PipelineContext:
    """Build a PipelineContext pre-populated for the Nutrition reasoning agent.

    The raw ``patient_data`` and ``espen_guidelines`` values are rendered into
    prompt-ready strings HERE (in the driver), then passed through
    ``context.metadata`` to the ReasoningAgent. The agent consumes them as-is
    and drops them straight into its nutrition meal-plan template.

    ``espen_nutrition_kb`` is the structured ESPEN nutrition KB serialized
    as JSON text. When provided, the ReasoningAgent uses it verbatim for
    the dedicated ``ESPEN NUTRITION KNOWLEDGE BASE`` prompt block (which
    drives ALL nutrition targets — energy, protein, macros, vitamins,
    intervention escalation, subgroup overrides, safety). When omitted,
    the agent falls back to its own on-disk loader.
    """
    stage, certainty = _derive_stage(patient_data)

    # Pre-format before handing off to the reasoning agent.
    espen_block = format_espen_guidelines(espen_guidelines)
    patient_block = format_patient_data(patient_data)

    # IMPORTANT: this driver only feeds raw measurements into context. It
    # does NOT classify anything — clinical categorization (BMI category,
    # waist risk, PG-SGA bucket, ...) is the StageAgent's job in
    # production. By pushing the parameters through ``metadata["user_data"]``
    # we let the real production agents do the work, so this test exercises
    # the same code path real users hit.
    ctx = PipelineContext(
        user_message=question,
        conversation_history=[],
        intent_result=IntentResult(
            intent=IntentCategory.NUTRITION,
            confidence=1.0,
            reasoning="Hardcoded NUTRITION intent (driver script).",
            clarification_needed=False,
        ),
        stage_result=StageResult(
            stage=stage,
            certainty=certainty,
            certainty_score=1.0 if certainty == CertaintyLevel.HIGH else 0.6,
            signals=["driver_script"],
        ),
        metadata={
            # Pre-rendered strings — the ReasoningAgent uses these verbatim.
            "patient_data": patient_block,
            "espen_guidelines": espen_block,
            # Structured ESPEN nutrition KB (JSON text). Authoritative for
            # ALL nutrition targets — energy / protein / macros / vitamins
            # / intervention escalation / subgroup overrides / safety.
            # Only attached when we successfully loaded the file; the
            # reasoning agent has its own on-disk fallback otherwise.
            **(
                {"espen_nutrition_kb": espen_nutrition_kb}
                if espen_nutrition_kb else {}
            ),
            # Keep the original structured dict around for any downstream
            # consumer that wants it (e.g. logging/debugging).
            "patient_data_raw": patient_data,
            # Raw measurements + demographics, normalized to the lowercase
            # production schema. This is the ONLY channel through which
            # downstream agents (StageAgent, RetrievalQueryBuilder, ...)
            # see the patient's clinical signals — exactly as in production.
            # StageAgentV2 will honor this as a high-priority source and
            # then categorize it (BMI / waist / grip / PG-SGA buckets).
            "user_data": _extract_user_data(patient_data),
            # Tell StageAgentV2 to skip the per-field "has it changed?"
            # confirmation prompts. Tests aren't multi-turn conversations,
            # and we trust the patient record we just loaded.
            "skip_user_data_confirmations": True,
            # Mark this as a guest session so StageAgentV2 doesn't try to
            # hit DynamoDB for biomarkers / persist anything.
            "is_guest": True,
        },
    )
    return ctx


# ============================================================================
# Pipeline execution
# ============================================================================

async def run_pipeline(ctx: PipelineContext) -> PipelineContext:
    """Run StageAgent -> RetrievalAgent -> Nutrition ReasoningAgent.

    The driver hardcodes the intent (NUTRITION) and seeds a fallback
    ``stage_result`` derived from the patient record, but every other
    pipeline behavior — user-data merge, BMI derivation, clinical
    categorization, journey-stage LLM classification, KB retrieval,
    grounded reasoning — runs through the real production agents. This is
    what makes this script a true integration test rather than a parallel
    implementation.

    Each agent's ``AgentTrace`` is stashed on ``ctx.metadata["agent_traces"]``
    so ``render_result`` can surface error details when an agent fails
    silently (``BaseAgent.run`` catches exceptions and returns a trace with
    ``status=FAILED`` rather than raising).
    """
    stage_agent = StageAgentV2()
    retrieval_agent = RetrievalAgent()
    reasoning_agent = get_reasoning_agent(IntentCategory.NUTRITION)

    traces: Dict[str, Any] = {}
    if ctx.metadata is None:
        ctx.metadata = {}
    ctx.metadata["agent_traces"] = traces

    logger.info("Running StageAgentV2 (user_data merge + categorization + stage LLM)...")
    ctx, stage_trace = await stage_agent.run(ctx)
    traces["stage"] = stage_trace
    logger.info(
        "Stage trace: status=%s latency=%sms summary=%s",
        stage_trace.status, stage_trace.latency_ms, stage_trace.output_summary,
    )
    if ctx.should_abort:
        logger.warning(
            "StageAgentV2 aborted the pipeline (reason=%s). Skipping retrieval + reasoning.",
            ctx.abort_reason,
        )
        return ctx

    logger.info("Running RetrievalAgent (nutrition KB)...")
    ctx, retrieval_trace = await retrieval_agent.run(ctx)
    traces["retrieval"] = retrieval_trace
    logger.info(
        "Retrieval trace: status=%s latency=%sms summary=%s",
        retrieval_trace.status, retrieval_trace.latency_ms, retrieval_trace.output_summary,
    )

    logger.info("Running ReasoningAgent (nutrition persona)...")
    ctx, reasoning_trace = await reasoning_agent.run(ctx)
    traces["reasoning"] = reasoning_trace
    logger.info(
        "Reasoning trace: status=%s latency=%sms summary=%s error=%s",
        reasoning_trace.status, reasoning_trace.latency_ms,
        reasoning_trace.output_summary, reasoning_trace.error_message,
    )

    return ctx


# ============================================================================
# Output rendering
# ============================================================================

def render_result(ctx: PipelineContext) -> str:
    """Render the final meal plan + retrieval/citation info into a single string."""
    out_lines = []

    out_lines.append("=" * 78)
    out_lines.append("NUTRITION MEAL PLAN")
    out_lines.append("=" * 78)

    # If a downstream agent (e.g. StageAgent) attached pre-classified
    # clinical categories to ``metadata["clinical_categories"]``, surface
    # them here for auditability. This driver does NOT populate them — it
    # only renders whatever the real production agents produced. No-op
    # today; lights up automatically once categorization is wired into
    # StageAgent in production.
    categories = (ctx.metadata or {}).get("clinical_categories") if ctx.metadata else None
    if categories:
        out_lines.append("\n[Clinical categories produced by upstream agents]")
        for cat in categories.values():
            unit = f" {cat['unit']}" if cat.get("unit") else ""
            risk = f" — risk: {cat['risk']}" if cat.get("risk") else ""
            ctx_axes = (
                f" [{', '.join(f'{k}={v}' for k, v in cat['context'].items())}]"
                if cat.get("context") else ""
            )
            out_lines.append(
                f"  - {cat['metric']}: {cat['value']}{unit} -> "
                f"{cat['label']}{risk}{ctx_axes}"
            )

    if ctx.retrieval_result:
        r = ctx.retrieval_result
        out_lines.append(
            f"\n[Retrieval] kb={r.knowledge_base_used} "
            f"chunks={r.total_retrieved} above_threshold={r.above_threshold} "
            f"sufficient={r.sufficient_evidence}"
        )

    if ctx.reasoning_result:
        rr = ctx.reasoning_result
        out_lines.append(
            f"[Reasoning] agent={rr.agent_type} abstained={rr.abstained} "
            f"confidence={rr.confidence:.2f}"
        )
        if rr.abstained and rr.abstention_reason:
            out_lines.append(f"[Reasoning] abstention_reason={rr.abstention_reason}")
        out_lines.append("\n" + "-" * 78)
        out_lines.append(rr.response_text)
        out_lines.append("-" * 78)

        if rr.citations:
            out_lines.append("\nCitations:")
            for i, c in enumerate(rr.citations, 1):
                pages = ""
                if c.page_start:
                    pages = f", p.{c.page_start}"
                    if c.page_end and c.page_end != c.page_start:
                        pages = f", pp.{c.page_start}-{c.page_end}"
                out_lines.append(
                    f"  [{i}] {c.source_file}{pages} (score={c.relevance_score:.2f})"
                )
    else:
        out_lines.append("\n(No reasoning result produced.)")
        # Surface why each agent stage failed (or didn't run). Without
        # this the only signal in the saved markdown is the line above,
        # which makes silent BaseAgent failures (timeout, Bedrock outage,
        # missing AWS creds, etc.) look like a configuration bug.
        traces = (ctx.metadata or {}).get("agent_traces") or {}
        for stage_name in ("stage", "retrieval", "reasoning"):
            tr = traces.get(stage_name)
            if tr is None:
                out_lines.append(
                    f"  - {stage_name}: (did not run — pipeline halted earlier)"
                )
                continue
            status = getattr(tr.status, "value", str(tr.status))
            err = getattr(tr, "error_message", None)
            line = f"  - {stage_name}: status={status} latency={tr.latency_ms}ms"
            if err:
                line += f" error={err}"
            out_lines.append(line)
        if ctx.should_abort:
            out_lines.append(f"  - pipeline_aborted: reason={ctx.abort_reason}")

    return "\n".join(out_lines)


# ============================================================================
# CLI
# ============================================================================

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--patient", default=PATIENT_DATA_PATH,
        help=f"Path to patient data file (default: {PATIENT_DATA_PATH})",
    )
    parser.add_argument(
        "--espen", default=ESPEN_GUIDELINES_PATH,
        help=f"Path to ESPEN guidelines file (default: {ESPEN_GUIDELINES_PATH})",
    )
    parser.add_argument(
        "--question", default=DEFAULT_QUESTION,
        help="Patient question to send to the nutrition agent.",
    )
    parser.add_argument(
        "--save", default=None,
        help=(
            f"Path to save the rendered meal plan (markdown). "
            f"If omitted, a timestamped file is written to '{DEFAULT_OUTPUT_DIR}/' "
            f"relative to the backend root."
        ),
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="Do not save the meal plan to disk (only print to stdout).",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logger verbosity (default: INFO).",
    )
    return parser.parse_args()


_SLUG_SAFE_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)


def _slugify(value: str, default: str = "unknown") -> str:
    """Turn an arbitrary string into a filesystem-safe slug."""
    value = str(value).strip()
    if not value:
        return default
    cleaned = "".join(c if c in _SLUG_SAFE_CHARS else "-" for c in value)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or default


def _extract_patient_id(patient_data: Any, fallback_path: Optional[str] = None) -> str:
    """Best-effort extraction of a patient identifier for filenames.

    Looks at the common id fields on the loaded patient record (case-
    insensitive), then falls back to the patient file's stem.
    """
    if isinstance(patient_data, dict):
        pid = _ci_get(
            patient_data,
            "patient_id", "patientid", "id",
            "mrn", "medical_record_number",
        )
        if pid:
            return _slugify(str(pid))

    if fallback_path:
        return _slugify(Path(fallback_path).stem)

    return "unknown"


def _default_save_path(patient_id: str) -> Path:
    """Build a default path under ``tests/meal_plans/`` that includes the
    patient id and a timestamp, e.g. ``meal_plan_IN-BC-4001_20260425_000918.md``.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify(patient_id)
    return _resolve_path(
        f"{DEFAULT_OUTPUT_DIR}/meal_plan_{slug}_{timestamp}.md"
    )


async def _async_main() -> int:
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("Loading patient data from %s", args.patient)
    patient_data = load_file(args.patient, "Patient data")

    logger.info("Loading ESPEN guidelines from %s", args.espen)
    espen_guidelines = load_file(args.espen, "ESPEN guidelines")

    espen_nutrition_kb = _load_espen_nutrition_kb_text(args.espen)
    if espen_nutrition_kb:
        logger.info(
            "Loaded ESPEN nutrition KB (%s, %d chars)",
            ESPEN_NUTRITION_KB_FILENAME, len(espen_nutrition_kb),
        )
    else:
        logger.warning(
            "ESPEN nutrition KB (%s) not found near %s; "
            "the reasoning agent will use its on-disk fallback.",
            ESPEN_NUTRITION_KB_FILENAME, args.espen,
        )

    ctx = build_nutrition_context(
        question=args.question,
        patient_data=patient_data,
        espen_guidelines=espen_guidelines,
        espen_nutrition_kb=espen_nutrition_kb,
    )

    ctx = await run_pipeline(ctx)

    rendered = render_result(ctx)
    print(rendered)

    # Save by default (timestamped file under tests/meal_plans/), unless the
    # caller opted out with --no-save. An explicit --save path overrides the
    # default location.
    if not args.no_save:
        if args.save:
            save_path = _resolve_path(args.save)
        else:
            patient_id = _extract_patient_id(patient_data, fallback_path=args.patient)
            save_path = _default_save_path(patient_id)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(rendered, encoding="utf-8")
        logger.info("Saved meal plan to %s", save_path)

    return 0 if (ctx.reasoning_result and not ctx.reasoning_result.abstained) else 1


def main() -> int:
    try:
        return asyncio.run(_async_main())
    except FileNotFoundError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
