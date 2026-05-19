"""Clinical parameter categorizer.

Loads thresholds from ``config/clinical_thresholds.json`` and exposes a
small, pure-function API for classifying patient measurements:

    >>> get_category("BMI", 29.1)
    {'metric': 'BMI', 'value': 29.1, 'label': 'Obese Class I', ...}

    >>> get_category("Waist_Circumference_cm", 81.9, sex="Female")
    {'label': 'Central Obesity', ...}

    >>> get_category("Hand_Grip_Strength_kg", 23.5, sex="Female", age=43)
    {'label': 'Normal', ...}

    >>> categorize_patient(patient_dict)
    {'BMI': {...}, 'Waist_Circumference_cm': {...}, ...}

Design:

* Thresholds live in JSON so non-engineers can audit / edit them.
* All bins use HALF-OPEN intervals: ``min <= value < max``. ``min`` /
  ``max`` of ``null`` means unbounded on that side.
* Each metric declares its stratification axes (``stratify_by``) — e.g.
  ``["sex"]`` for waist, ``["sex", "age_band"]`` for grip strength,
  ``["standard"]`` for BMI. The lookup walks those axes one at a time.
* ``age_band`` is the only axis that requires light Python logic
  (mapping a raw ``age`` to a band id), so the JSON stays declarative.
* Add a new metric = edit JSON only. Add a new axis type = one branch
  in ``_resolve_axis_key``.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Resolve config path relative to this file: services/ -> backend root -> config/
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _BACKEND_ROOT / "config" / "clinical_thresholds.json"


# ============================================================================
# Loading + validation
# ============================================================================

class ClinicalConfigError(ValueError):
    """Raised when the JSON config is malformed."""


@lru_cache(maxsize=1)
def _load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load and lightly validate the thresholds JSON. Cached for the process."""
    config_path = Path(path) if path else _CONFIG_PATH
    if not config_path.exists():
        raise ClinicalConfigError(f"clinical thresholds config not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    metrics = data.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ClinicalConfigError(f"'metrics' missing or empty in {config_path}")

    for name, spec in metrics.items():
        if "rules" not in spec:
            raise ClinicalConfigError(f"metric '{name}': missing 'rules'")
        axes = spec.get("stratify_by", []) or []
        if not isinstance(axes, list):
            raise ClinicalConfigError(f"metric '{name}': 'stratify_by' must be a list")
        if "age_band" in axes and "age_bands" not in spec:
            raise ClinicalConfigError(
                f"metric '{name}': stratifies by 'age_band' but no 'age_bands' defined"
            )

    return data


def reload_config() -> None:
    """Drop the cached config (e.g. after editing the JSON in dev)."""
    _load_config.cache_clear()


def list_metrics() -> List[str]:
    """Names of all configured metrics."""
    return sorted(_load_config()["metrics"].keys())


def get_metric_spec(metric: str) -> Dict[str, Any]:
    """Raw spec for one metric (for introspection / UI rendering)."""
    cfg = _load_config()["metrics"]
    if metric not in cfg:
        raise KeyError(f"unknown metric: {metric!r}. Known: {sorted(cfg)}")
    return cfg[metric]


# ============================================================================
# Bin lookup (the only "logic")
# ============================================================================

def _categorize_bins(value: float, bins: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the bin whose [min, max) interval contains ``value``."""
    for r in bins:
        lo, hi = r.get("min"), r.get("max")
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return r
    raise ValueError(f"no bin matched value={value!r} in {bins!r}")


def _resolve_axis_key(axis: str, spec: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Translate a context value into the dict key used in ``rules``."""
    if axis == "age_band":
        if "age" not in context or context["age"] is None:
            raise ValueError(f"context missing 'age' (needed for age_band)")
        age = int(context["age"])
        for band in spec["age_bands"]:
            if band["min"] <= age <= band["max"]:
                return band["id"]
        raise ValueError(f"age {age} fits no configured age_band")

    if axis == "standard":
        std = context.get("standard")
        if std is None:
            std = (spec.get("default_context") or {}).get("standard")
        if std is None:
            raise ValueError(f"context missing 'standard' (no default configured)")
        return str(std).lower()

    # Generic axis: just lowercase the supplied value (sex, ethnicity, etc.).
    if axis not in context or context[axis] is None or context[axis] == "":
        raise ValueError(f"context missing {axis!r}")
    return str(context[axis]).lower()


# ============================================================================
# Public API
# ============================================================================

def get_category(metric: str, value: Any, **context: Any) -> Dict[str, Any]:
    """Classify a single measurement.

    Args:
        metric: One of ``list_metrics()`` (e.g. ``"BMI"``).
        value:  The raw measurement (numeric).
        **context: Stratification context (``sex``, ``age``, ``standard`` …).
            Only the keys declared in the metric's ``stratify_by`` are read.

    Returns:
        A dict like::

            {
                "metric": "BMI",
                "value": 29.1,
                "label": "Obese Class I",
                "risk": "high",
                "min": 25.0, "max": 30.0,
                "unit": "kg/m^2",
                "standard": "indian_icmr",
                "source": "...",
                "context": {"standard": "indian_icmr"},
            }

    Raises:
        KeyError:   unknown metric.
        ValueError: missing context, value out of all bins, malformed config.
    """
    if value is None:
        raise ValueError(f"{metric}: value is None")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{metric}: value {value!r} is not numeric") from exc
    if numeric != numeric:  # NaN guard
        raise ValueError(f"{metric}: value is NaN")

    spec = get_metric_spec(metric)
    rules: Any = spec["rules"]
    axes: List[str] = spec.get("stratify_by", []) or []

    # Apply per-metric default context (e.g. {"standard": "indian_icmr"}).
    effective_ctx = dict(spec.get("default_context") or {})
    effective_ctx.update({k: v for k, v in context.items() if v is not None})

    resolved_axes: Dict[str, str] = {}
    for axis in axes:
        key = _resolve_axis_key(axis, spec, effective_ctx)
        resolved_axes[axis] = key
        if not isinstance(rules, dict) or key not in rules:
            available = sorted(rules.keys()) if isinstance(rules, dict) else "<not a dict>"
            raise ValueError(
                f"{metric}: no rules for {axis}={key!r} (available: {available})"
            )
        rules = rules[key]

    if not isinstance(rules, list):
        raise ClinicalConfigError(
            f"{metric}: expected list of bins after resolving {resolved_axes}, "
            f"got {type(rules).__name__}"
        )

    bin_match = _categorize_bins(numeric, rules)

    return {
        "metric": metric,
        "value": numeric,
        "label": bin_match["label"],
        "risk": bin_match.get("risk"),
        "min": bin_match.get("min"),
        "max": bin_match.get("max"),
        "unit": spec.get("unit"),
        "source": spec.get("source"),
        "context": resolved_axes,
    }


def categorize_patient(
    patient: Dict[str, Any],
    *,
    standard: Optional[str] = None,
    metrics: Optional[Iterable[str]] = None,
    skip_missing: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """Bulk classify everything we can on a patient record.

    * Looks up each metric by case-insensitive key match against the patient dict.
    * Pulls common context (``sex``, ``age``) from the patient if present.
    * Skips metrics that are missing from the patient or whose context is missing
      (when ``skip_missing=True``); raises otherwise.
    """
    cfg = _load_config()["metrics"]
    targets = list(metrics) if metrics else list(cfg.keys())

    # Case-insensitive lookup over the patient dict.
    lower_map = {str(k).lower(): k for k in patient.keys()}

    def _patient_get(*keys: str) -> Any:
        for k in keys:
            orig = lower_map.get(k.lower())
            if orig is not None and patient[orig] not in (None, ""):
                return patient[orig]
        return None

    base_ctx: Dict[str, Any] = {}
    sex = _patient_get("sex", "gender")
    if sex is not None:
        base_ctx["sex"] = str(sex).lower()
    age = _patient_get("age", "age_years")
    if age is not None:
        base_ctx["age"] = age
    if standard is not None:
        base_ctx["standard"] = standard

    out: Dict[str, Dict[str, Any]] = {}
    for metric in targets:
        if metric not in cfg:
            if skip_missing:
                logger.debug("Unknown metric %s; skipping.", metric)
                continue
            raise KeyError(f"unknown metric: {metric!r}")

        value = _patient_get(metric)
        if value is None:
            if skip_missing:
                continue
            raise ValueError(f"{metric}: not present in patient record")

        try:
            out[metric] = get_category(metric, value, **base_ctx)
        except (ValueError, KeyError) as exc:
            if skip_missing:
                logger.debug("Skipping %s: %s", metric, exc)
                continue
            raise

    return out


# ============================================================================
# Convenience: pretty single-line summary (handy for logs / prompts)
# ============================================================================

def format_summary(result: Dict[str, Any]) -> str:
    """One-liner like ``BMI 29.1 kg/m^2 -> Obese Class I (high) [25.0-30.0]``."""
    rng_lo = result.get("min")
    rng_hi = result.get("max")
    rng = (
        f"[{rng_lo if rng_lo is not None else '-inf'}-"
        f"{rng_hi if rng_hi is not None else '+inf'})"
    )
    risk = f" ({result['risk']})" if result.get("risk") else ""
    unit = f" {result['unit']}" if result.get("unit") else ""
    return (
        f"{result['metric']} {result['value']}{unit} "
        f"-> {result['label']}{risk} {rng}"
    )


def format_patient_report(results: Dict[str, Dict[str, Any]]) -> str:
    """Multi-line report from a ``categorize_patient`` output."""
    if not results:
        return "(no metrics classified)"
    return "\n".join(format_summary(r) for r in results.values())


__all__ = [
    "ClinicalConfigError",
    "get_category",
    "categorize_patient",
    "list_metrics",
    "get_metric_spec",
    "reload_config",
    "format_summary",
    "format_patient_report",
]
