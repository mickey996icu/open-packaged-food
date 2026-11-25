"""Deterministic v0.3 nutrition normalization compiler (re-exports fingerprints & lifecycle APIs)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from opf.fingerprints import (
    CANONICAL_NUTRIENT_ORDER,
    SUPPLEMENTAL_NUTRIENT_SPECS,
    _collect_tree_metadata,
    canonicalize_core_in_place,
    canonicalize_special_indicator,
    compute_core_fingerprint,
    compute_label_fingerprint,
    format_canonical_decimal,
    get_nutrients_registry,
    nutrient_row_sort_key,
)
from opf.lifecycle import (
    compute_stale_window_months,
    compute_t_active,
    compute_t_active_with_basis,
    derive_editions_lifecycle,
    derive_evidence_level,
)
from opf.media import normalize_evidence_region
from opf.registries import get_profile

__all__ = [
    "CANONICAL_NUTRIENT_ORDER",
    "SUPPLEMENTAL_NUTRIENT_SPECS",
    "canonicalize_core_in_place",
    "canonicalize_special_indicator",
    "compute_core_fingerprint",
    "compute_label_fingerprint",
    "compute_stale_window_months",
    "compute_t_active",
    "compute_t_active_with_basis",
    "derive_editions_lifecycle",
    "derive_evidence_level",
    "format_canonical_decimal",
    "get_nutrients_registry",
    "normalize_edition",
    "nutrient_row_sort_key",
]


def _fmt_dec(val: Decimal, quant: str = "0.01") -> str:
    """Quantize a Decimal with ROUND_HALF_UP and format without redundant trailing zeros."""
    q = val.quantize(Decimal(quant), rounding=ROUND_HALF_UP)
    if q == Decimal("0"):
        return "0"
    s = format(q, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _unit_to_base(value: Decimal, unit: str) -> tuple[Decimal, str]:
    """Convert mass/volume units to base g or ml for basis scaling."""
    u = unit.strip().lower()
    if u == "kg":
        return value * Decimal("1000"), "g"
    if u == "l":
        return value * Decimal("1000"), "ml"
    if u in ("g", "ml", "mg", "ug", "kj", "kcal"):
        return value, unit.strip()
    return value, unit.strip()


def _compile_declared_rows(
    *,
    panel: dict[str, Any],
    profile_id: str,
    norm_basis: str,
    scale_factor: Decimal,
    is_scaled: bool,
    zero_thresholds_serving: dict[str, str],
    zero_thresholds_100: dict[str, str],
    nrv_reference: dict[str, str],
    quality_flags: list[dict[str, str]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """Normalize nutrition_declared.rows into per-100g/ml values with regulatory zero bounds."""
    nutrients_dict = get_nutrients_registry()
    basis_obj = panel["basis"]
    norm_nutrients: dict[str, dict[str, Any]] = {}
    declared_energy_kj: dict[str, Any] | None = None
    declared_energy_kcal: dict[str, Any] | None = None

    for row in panel.get("rows", []):
        nid = row["nutrient"]
        val_dec = Decimal(row["value"])
        unit = row["unit"]
        qual = row.get("qualifier")

        if nid == "energy":
            threshold_key = "energy_kcal" if unit == "kcal" else "energy_kj"
            if (
                is_scaled
                and val_dec == Decimal("0")
                and qual in (None, "=")
                and threshold_key in zero_thresholds_serving
            ):
                thresh = Decimal(zero_thresholds_serving[threshold_key])
                scaled_ub = thresh * scale_factor
                entry: dict[str, Any] = {
                    "qualifier": "<",
                    "value": _fmt_dec(scaled_ub, "0.01"),
                    "unit": unit,
                    "basis": "regulatory_upper_bound",
                }
                quality_flags.append(
                    {
                        "code": "REGULATORY_ZERO_ROUNDING_ARTIFACT",
                        "field": f"energy_{unit.lower()}",
                        "detail": (
                            f"Declared 0 {unit} per {basis_obj['value']}{basis_obj['unit']} under {profile_id} "
                            f"implies <{thresh} {unit}/serving (<{_fmt_dec(scaled_ub, '0.01')} {unit}/{norm_basis})"
                        ),
                    }
                )
            elif (
                val_dec == Decimal("0")
                and qual in (None, "=")
                and threshold_key in zero_thresholds_100
            ):
                thresh = Decimal(zero_thresholds_100[threshold_key])
                entry = {
                    "qualifier": "<",
                    "value": _fmt_dec(thresh, "0.01"),
                    "unit": unit,
                    "basis": "regulatory_upper_bound",
                }
                quality_flags.append(
                    {
                        "code": "REGULATORY_ZERO_ROUNDING_ARTIFACT",
                        "field": f"energy_{unit.lower()}",
                        "detail": (
                            f"Declared 0 {unit} under {profile_id} zero-threshold rule "
                            f"implies <{_fmt_dec(thresh, '0.01')} {unit}/{norm_basis}"
                        ),
                    }
                )
            else:
                scaled_val = val_dec * scale_factor
                quant = "0.01" if qual in ("<", "<=") else "0.1"
                basis_tag = (
                    "regulatory_upper_bound"
                    if qual in ("<", "<=")
                    else ("derived" if is_scaled else "reported")
                )
                entry = {
                    "value": row["value"] if basis_tag == "reported" else _fmt_dec(scaled_val, quant),
                    "unit": unit,
                    "basis": basis_tag,
                }
                if qual and qual != "=":
                    entry["qualifier"] = qual

            if unit == "kJ":
                declared_energy_kj = entry
                norm_nutrients["energy_kj"] = entry
            elif unit == "kcal":
                declared_energy_kcal = entry
                norm_nutrients["energy_kcal"] = entry

            if "nrv_pct" in row and qual in (None, "=") and threshold_key in nrv_reference:
                ref_val = Decimal(nrv_reference[threshold_key])
                expected_pct = (val_dec / ref_val) * Decimal("100")
                declared_pct = Decimal(row["nrv_pct"])
                if abs(declared_pct - expected_pct) > Decimal("2.5"):
                    quality_flags.append(
                        {
                            "code": "NRV_PCT_DECLARED_MISMATCH",
                            "field": threshold_key,
                            "detail": (
                                f"Declared NRV% {row['nrv_pct']}% for {row['value']} {unit} differs from "
                                f"{profile_id} reference ({ref_val} {unit} -> {_fmt_dec(expected_pct, '0.1')}%)"
                            ),
                        }
                    )
            continue

        target_unit = nutrients_dict.get(nid, {}).get("normalized_unit", unit)
        val_in_target = val_dec
        if unit == "g" and target_unit == "mg":
            val_in_target = val_dec * Decimal("1000")
        elif unit == "mg" and target_unit == "g":
            val_in_target = val_dec / Decimal("1000")
        elif unit == "mg" and target_unit == "ug":
            val_in_target = val_dec * Decimal("1000")

        if (
            is_scaled
            and val_in_target == Decimal("0")
            and qual in (None, "=")
            and nid in zero_thresholds_serving
        ):
            thresh = Decimal(zero_thresholds_serving[nid])
            scaled_ub = thresh * scale_factor
            entry = {
                "qualifier": "<",
                "value": _fmt_dec(scaled_ub, "0.01"),
                "unit": target_unit,
                "basis": "regulatory_upper_bound",
            }
            quality_flags.append(
                {
                    "code": "REGULATORY_ZERO_ROUNDING_ARTIFACT",
                    "field": nid,
                    "detail": (
                        f"Declared 0 {unit} per {basis_obj['value']}{basis_obj['unit']} under {profile_id} "
                        f"implies <{thresh} {target_unit}/serving (<{_fmt_dec(scaled_ub, '0.01')} {target_unit}/{norm_basis})"
                    ),
                }
            )
        elif (
            val_in_target == Decimal("0")
            and qual in (None, "=")
            and nid in zero_thresholds_100
        ):
            thresh = Decimal(zero_thresholds_100[nid])
            quant = "0.001" if (nid == "salt_equivalent" and thresh < Decimal("0.01")) else "0.01"
            entry = {
                "qualifier": "<",
                "value": _fmt_dec(thresh, quant),
                "unit": target_unit,
                "basis": "regulatory_upper_bound",
            }
            quality_flags.append(
                {
                    "code": "REGULATORY_ZERO_ROUNDING_ARTIFACT",
                    "field": nid,
                    "detail": (
                        f"Declared 0 {unit} under {profile_id} zero-threshold rule "
                        f"implies <{_fmt_dec(thresh, quant)} {target_unit}/{norm_basis}"
                    ),
                }
            )
        else:
            scaled_val = val_in_target * scale_factor
            quant = "0.01" if (nid == "salt_equivalent" or qual in ("<", "<=")) else "0.1"
            basis_tag = (
                "regulatory_upper_bound"
                if qual in ("<", "<=")
                else ("derived" if (is_scaled or unit != target_unit) else "reported")
            )
            entry = {
                "value": row["value"] if basis_tag == "reported" else _fmt_dec(scaled_val, quant),
                "unit": target_unit,
                "basis": basis_tag,
            }
            if qual and qual != "=":
                entry["qualifier"] = qual

        norm_nutrients[nid] = entry

        if "nrv_pct" in row and qual in (None, "=") and nid in nrv_reference:
            ref_val = Decimal(nrv_reference[nid])
            expected_pct = (val_in_target / ref_val) * Decimal("100")
            declared_pct = Decimal(row["nrv_pct"])
            if abs(declared_pct - expected_pct) > Decimal("2.5"):
                quality_flags.append(
                    {
                        "code": "NRV_PCT_DECLARED_MISMATCH",
                        "field": nid,
                        "detail": (
                            f"Declared NRV% {row['nrv_pct']}% for {row['value']} {unit} differs from "
                            f"{profile_id} reference ({ref_val} {target_unit} -> {_fmt_dec(expected_pct, '0.1')}%)"
                        ),
                    }
                )

    return norm_nutrients, declared_energy_kj, declared_energy_kcal


def _apply_cross_derivations(
    *,
    norm_nutrients: dict[str, dict[str, Any]],
    declared_energy_kj: dict[str, Any] | None,
    declared_energy_kcal: dict[str, Any] | None,
    kj_per_kcal: Decimal,
    salt_per_sodium: Decimal,
    profile_id: str,
    quality_flags: list[dict[str, str]],
) -> None:
    """Derive reciprocal energy, sodium/salt, and available carbohydrate entries."""
    if declared_energy_kj and not declared_energy_kcal:
        kj_val = Decimal(declared_energy_kj["value"])
        kcal_val = kj_val / kj_per_kcal
        qual = declared_energy_kj.get("qualifier")
        quant = "0.01" if qual in ("<", "<=") else "0.1"
        basis_tag = (
            "regulatory_upper_bound"
            if declared_energy_kj["basis"] == "regulatory_upper_bound"
            else "derived"
        )
        kcal_entry: dict[str, Any] = {
            "value": _fmt_dec(kcal_val, quant),
            "unit": "kcal",
            "basis": basis_tag,
        }
        if qual:
            kcal_entry["qualifier"] = qual
        norm_nutrients["energy_kcal"] = kcal_entry
    elif declared_energy_kcal and not declared_energy_kj:
        kcal_val = Decimal(declared_energy_kcal["value"])
        kj_val = kcal_val * kj_per_kcal
        qual = declared_energy_kcal.get("qualifier")
        quant = "0.01" if qual in ("<", "<=") else "0.1"
        basis_tag = (
            "regulatory_upper_bound"
            if declared_energy_kcal["basis"] == "regulatory_upper_bound"
            else "derived"
        )
        kj_entry: dict[str, Any] = {
            "value": _fmt_dec(kj_val, quant),
            "unit": "kJ",
            "basis": basis_tag,
        }
        if qual:
            kj_entry["qualifier"] = qual
        norm_nutrients["energy_kj"] = kj_entry
    elif declared_energy_kj and declared_energy_kcal:
        kj_val = Decimal(declared_energy_kj["value"])
        kcal_val = Decimal(declared_energy_kcal["value"])
        if kj_val > Decimal("0") and kcal_val > Decimal("0"):
            expected_kcal = kj_val / kj_per_kcal
            rel_err = abs(expected_kcal - kcal_val) / expected_kcal
            if rel_err > Decimal("0.05"):
                quality_flags.append(
                    {
                        "code": "ENERGY_KJ_KCAL_DECLARED_MISMATCH",
                        "field": "energy",
                        "detail": (
                            f"Declared {kj_val} kJ and {kcal_val} kcal differ from 4.184 ratio by "
                            f"{_fmt_dec(rel_err * Decimal('100'), '0.1')}%"
                        ),
                    }
                )

    if "sodium" in norm_nutrients and "salt_equivalent" not in norm_nutrients:
        na_entry = norm_nutrients["sodium"]
        na_mg = Decimal(na_entry["value"])
        salt_g = (na_mg / Decimal("1000")) * salt_per_sodium
        qual = na_entry.get("qualifier")
        basis_tag = (
            "regulatory_upper_bound"
            if na_entry["basis"] == "regulatory_upper_bound"
            else "derived"
        )
        salt_entry: dict[str, Any] = {
            "value": _fmt_dec(salt_g, "0.01"),
            "unit": "g",
            "basis": basis_tag,
        }
        if qual:
            salt_entry["qualifier"] = qual
        norm_nutrients["salt_equivalent"] = salt_entry
        if salt_g > Decimal("0"):
            quality_flags.append(
                {
                    "code": "SALT_DERIVED_FROM_SODIUM",
                    "field": "salt_equivalent",
                    "detail": f"Derived from sodium using ratio {salt_per_sodium}",
                }
            )
    elif "salt_equivalent" in norm_nutrients and "sodium" not in norm_nutrients:
        salt_entry = norm_nutrients["salt_equivalent"]
        salt_g = Decimal(salt_entry["value"])
        na_mg = (salt_g / salt_per_sodium) * Decimal("1000")
        qual = salt_entry.get("qualifier")
        basis_tag = (
            "regulatory_upper_bound"
            if salt_entry["basis"] == "regulatory_upper_bound"
            else "derived"
        )
        na_entry = {
            "value": _fmt_dec(na_mg, "0.1"),
            "unit": "mg",
            "basis": basis_tag,
        }
        if qual:
            na_entry["qualifier"] = qual
        norm_nutrients["sodium"] = na_entry
        if na_mg > Decimal("0"):
            quality_flags.append(
                {
                    "code": "SODIUM_DERIVED_FROM_SALT",
                    "field": "sodium",
                    "detail": f"Derived from salt_equivalent using ratio {salt_per_sodium}",
                }
            )

    if "carbs_total" in norm_nutrients:
        quality_flags.append(
            {
                "code": "CARBS_TOTAL_INCLUDES_FIBER",
                "field": "carbs_total",
                "detail": f"{profile_id} declares total carbohydrates including dietary fiber",
            }
        )
        if (
            "carbs_available" not in norm_nutrients
            and "dietary_fiber" in norm_nutrients
            and not norm_nutrients["carbs_total"].get("qualifier")
            and not norm_nutrients["dietary_fiber"].get("qualifier")
        ):
            ct = Decimal(norm_nutrients["carbs_total"]["value"])
            df = Decimal(norm_nutrients["dietary_fiber"]["value"])
            avail = max(Decimal("0"), ct - df)
            norm_nutrients["carbs_available"] = {
                "value": _fmt_dec(avail, "0.1"),
                "unit": "g",
                "basis": "derived",
            }


def _compute_per_unit(
    core: dict[str, Any], norm_basis: str, norm_nutrients: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    unit_source = core.get("serving_size") or (
        core["net_content"][0] if core.get("net_content") else None
    )
    if not unit_source:
        return None
    u_val_raw = Decimal(unit_source["value"])
    u_val, u_base_unit = _unit_to_base(u_val_raw, unit_source["unit"])
    expected_base = "ml" if norm_basis == "100ml" else "g"
    if u_base_unit.lower() != expected_base or u_val == Decimal("100"):
        return None
    u_factor = u_val / Decimal("100")
    per_unit_nutrients: dict[str, dict[str, Any]] = {}
    for k, v in norm_nutrients.items():
        scaled = Decimal(v["value"]) * u_factor
        quant = (
            "0.001"
            if (k == "salt_equivalent" and scaled < Decimal("0.01") and scaled > Decimal("0"))
            else ("0.01" if (k == "salt_equivalent" or v.get("qualifier") in ("<", "<=")) else "0.1")
        )
        pu_entry: dict[str, Any] = {
            "value": _fmt_dec(scaled, quant),
            "unit": v["unit"],
            "basis": "regulatory_upper_bound" if v["basis"] == "regulatory_upper_bound" else "derived",
        }
        if v.get("qualifier"):
            pu_entry["qualifier"] = v["qualifier"]
        per_unit_nutrients[k] = pu_entry
    return {
        "unit_amount": dict(unit_source),
        "nutrients": per_unit_nutrients,
    }


def normalize_edition(edition: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize v0.3 core/supersedes and compile normalized, quality_flags, core_fingerprint, label_fingerprint."""
    core = edition["core"]
    canonicalize_core_in_place(core)

    if "supersedes" in edition and isinstance(edition["supersedes"], list):
        edition["supersedes"] = sorted({str(u) for u in edition["supersedes"]})

    if "evidence" in edition and isinstance(edition["evidence"], list):
        for ev in edition["evidence"]:
            if isinstance(ev, dict) and ev.get("region") is not None:
                ev["region"] = normalize_evidence_region(str(ev["region"]))

    profile_id = core["regulatory_profile"]
    profile = get_profile(profile_id)
    attributes = edition.get("attributes") or {}
    ingredients_tree = core.get("ingredients_tree", [])

    panel = core.get("nutrition_declared")
    quality_flags: list[dict[str, str]] = []
    norm_nutrients: dict[str, dict[str, Any]] = {}
    per_unit_obj: dict[str, Any] | None = None

    if panel is None:
        nc_items = core.get("net_content") or []
        first_nc_unit = str((nc_items[0] if nc_items else {}).get("unit") or "").strip().lower()
        norm_basis = "100ml" if first_nc_unit in ("ml", "l") else "100g"
        ex = core["nutrition_exemption"]
        legal_suffix = f" ({ex['legal_basis']})" if ex.get("legal_basis") else ""
        quality_flags.append(
            {
                "code": "NUTRITION_LABEL_EXEMPT",
                "field": "nutrition_declared",
                "detail": (
                    f"Nutrition panel legally exempt under category '{ex['category']}'{legal_suffix}; "
                    "normalized.nutrients is intentionally empty."
                ),
            }
        )
    else:
        kj_per_kcal = Decimal(profile.get("kj_per_kcal", "4.184"))
        salt_per_sodium = Decimal(profile.get("salt_per_sodium_ratio", "2.5"))
        zero_thresholds_serving: dict[str, str] = profile.get("zero_thresholds_per_serving", {})
        zero_thresholds_100: dict[str, str] = profile.get("zero_thresholds_per_100", {})
        nrv_reference: dict[str, str] = profile.get("nrv_reference", {})

        basis_obj = panel["basis"]
        raw_basis_val = Decimal(basis_obj["value"])
        basis_val, basis_base_unit = _unit_to_base(raw_basis_val, basis_obj["unit"])
        if basis_val <= Decimal("0"):
            raise ValueError(
                f"core.nutrition_declared.basis.value must be positive, got {basis_obj['value']!r}"
            )

        norm_basis = "100ml" if basis_base_unit.lower() == "ml" else "100g"
        scale_factor = Decimal("100") / basis_val
        is_scaled = scale_factor != Decimal("1")

        if is_scaled:
            quality_flags.append(
                {
                    "code": "DERIVED_FROM_SERVING_BASIS",
                    "field": "nutrition_declared.basis",
                    "detail": f"Normalized to {norm_basis} from declared basis {basis_obj['value']}{basis_obj['unit']}",
                }
            )

        norm_nutrients, declared_energy_kj, declared_energy_kcal = _compile_declared_rows(
            panel=panel,
            profile_id=profile_id,
            norm_basis=norm_basis,
            scale_factor=scale_factor,
            is_scaled=is_scaled,
            zero_thresholds_serving=zero_thresholds_serving,
            zero_thresholds_100=zero_thresholds_100,
            nrv_reference=nrv_reference,
            quality_flags=quality_flags,
        )
        _apply_cross_derivations(
            norm_nutrients=norm_nutrients,
            declared_energy_kj=declared_energy_kj,
            declared_energy_kcal=declared_energy_kcal,
            kj_per_kcal=kj_per_kcal,
            salt_per_sodium=salt_per_sodium,
            profile_id=profile_id,
            quality_flags=quality_flags,
        )
        per_unit_obj = _compute_per_unit(core, norm_basis, norm_nutrients)

    ins_codes, tree_allergens, _tree_sigs = _collect_tree_metadata(ingredients_tree)
    declared_allergens = core.get("allergens_declared") or {}
    declared_contains_alg = sorted(set(declared_allergens.get("contains") or []))
    contains_alg = sorted(set(tree_allergens) | set(declared_contains_alg))
    may_contain_alg = sorted(set(declared_allergens.get("may_contain") or []))

    normalized: dict[str, Any] = {
        "basis": norm_basis,
        "nutrients": norm_nutrients,
        "additives_ins": ins_codes,
        "allergens": {
            "contains": contains_alg,
            "declared_contains": declared_contains_alg,
            "inferred_from_ingredients": tree_allergens,
            "may_contain": may_contain_alg,
        },
    }
    if per_unit_obj is not None:
        normalized["per_unit"] = per_unit_obj

    edition["normalized"] = normalized
    edition["quality_flags"] = quality_flags
    edition["core_fingerprint"] = compute_core_fingerprint(core)
    edition["label_fingerprint"] = compute_label_fingerprint(
        edition["core_fingerprint"], attributes
    )
    return edition
