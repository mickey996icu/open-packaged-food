"""Deterministic v0.2 normalization, canonical ordering, fingerprints, and build-time lifecycle derivation."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from opf.ingredients import strip_ingredient_spans
from opf.media import normalize_evidence_region
from opf.registries import get_profile, load_nutrients_dict

CANONICAL_NUTRIENT_ORDER: tuple[str, ...] = (
    "energy",
    "protein",
    "fat_total",
    "fat_saturated",
    "fat_trans",
    "fat_monounsaturated",
    "fat_polyunsaturated",
    "cholesterol",
    "carbs_available",
    "carbs_total",
    "sugars_total",
    "sugars_added",
    "sugar_alcohols",
    "dietary_fiber",
    "sodium",
    "salt_equivalent",
    "calcium",
    "iron",
    "potassium",
    "vitamin_a",
    "vitamin_c",
    "vitamin_d",
)

SUPPLEMENTAL_NUTRIENT_SPECS: dict[str, dict[str, Any]] = {
    "fat_monounsaturated": {"dimension": "mass", "allowed_units": ["g"], "normalized_unit": "g"},
    "fat_polyunsaturated": {"dimension": "mass", "allowed_units": ["g"], "normalized_unit": "g"},
    "vitamin_a": {"dimension": "mass", "allowed_units": ["ug", "mg"], "normalized_unit": "ug"},
}

_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")
_OPF_MEDIA_RE = re.compile(r"^opf-media://sha256/([a-f0-9]{64})$")
_YEAR_4DIGIT_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def get_nutrients_registry() -> dict[str, Any]:
    """Return merged nutrient dictionary including SPEC §3 supplemental nutrients."""
    merged = dict(load_nutrients_dict())
    for nid, spec in SUPPLEMENTAL_NUTRIENT_SPECS.items():
        if nid not in merged:
            merged[nid] = spec
    return merged


def _nutrient_order_index() -> dict[str, int]:
    order: dict[str, int] = {nid: idx for idx, nid in enumerate(CANONICAL_NUTRIENT_ORDER)}
    next_idx = len(CANONICAL_NUTRIENT_ORDER)
    for nid in load_nutrients_dict():
        if nid not in order:
            order[nid] = next_idx
            next_idx += 1
    return order


def nutrient_row_sort_key(row: dict[str, Any]) -> tuple[int, int, str, str]:
    """Canonical §3 sort key for nutrition_declared.rows (energy kJ precedes energy kcal)."""
    order_map = _nutrient_order_index()
    nid = str(row.get("nutrient", ""))
    unit = str(row.get("unit", ""))
    base_rank = order_map.get(nid, len(order_map) + 1000)
    if nid == "energy":
        unit_rank = 0 if unit == "kJ" else (1 if unit == "kcal" else 2)
    else:
        unit_rank = 0
    return (base_rank, unit_rank, nid, unit)


def format_canonical_decimal(val: str | Decimal) -> str:
    """Format a non-negative Decimal/string into canonical DecimalString without redundant trailing zeros."""
    d = val if isinstance(val, Decimal) else Decimal(str(val).strip())
    if not d.is_finite() or d < Decimal("0"):
        raise ValueError(f"DecimalString must be non-negative and finite, got {val!r}")
    if d == Decimal("0"):
        return "0"
    s = format(d.normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


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


def _nfkc_str(val: Any) -> str:
    return unicodedata.normalize("NFKC", str(val).strip())


def _nfkc_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return _nfkc_str(obj)
    if isinstance(obj, list):
        return [_nfkc_obj(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): _nfkc_obj(v) for k, v in obj.items()}
    return obj


def _collect_tree_metadata(
    ingredients_tree: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Extract sorted INS codes, inferred allergens, and span-free canonical node signatures."""
    ins_set: set[str] = set()
    allergen_set: set[str] = set()

    def _sig_node(node: dict[str, Any]) -> dict[str, Any]:
        if node.get("ins"):
            ins_set.add(str(node["ins"]))
        for alg in node.get("allergens") or []:
            allergen_set.add(str(alg))
        sig: dict[str, Any] = {"name": _nfkc_str(node["name"])}
        if node.get("qualifier"):
            sig["qualifier"] = _nfkc_str(node["qualifier"])
        if node.get("functional_class"):
            sig["functional_class"] = _nfkc_str(node["functional_class"])
        if node.get("ins"):
            sig["ins"] = _nfkc_str(node["ins"])
        if node.get("is_additive") is True:
            sig["is_additive"] = True
        node_algs = sorted({_nfkc_str(a) for a in (node.get("allergens") or []) if str(a).strip()})
        if node_algs:
            sig["allergens"] = node_algs
        if node.get("children"):
            sig["children"] = [_sig_node(c) for c in node["children"]]
        return sig

    tree_sigs: list[dict[str, Any]] = []
    for lang_entry in sorted(ingredients_tree, key=lambda item: str(item.get("lang", ""))):
        tree_sigs.append(
            {
                "lang": _nfkc_str(lang_entry["lang"]),
                "nodes": [_sig_node(n) for n in lang_entry.get("nodes", [])],
            }
        )
    return sorted(ins_set), sorted(allergen_set), tree_sigs


def compute_core_fingerprint(core: dict[str, Any]) -> str:
    """Compute canonical JSON SHA-256 over NFKC-normalized v0.2 core layer."""
    _ins, _alg, tree_sigs = _collect_tree_metadata(core.get("ingredients_tree") or [])

    def _canon_qty(qty: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "value": format_canonical_decimal(qty["value"]),
            "unit": _nfkc_str(qty["unit"]),
        }
        q = qty.get("qualifier")
        if q and q != "=":
            out["qualifier"] = _nfkc_str(q)
        return out

    decl = core["nutrition_declared"]
    canon_rows: list[dict[str, Any]] = []
    for row in sorted(decl.get("rows") or [], key=nutrient_row_sort_key):
        r_out: dict[str, Any] = {
            "nutrient": _nfkc_str(row["nutrient"]),
            "value": format_canonical_decimal(row["value"]),
            "unit": _nfkc_str(row["unit"]),
        }
        q = row.get("qualifier")
        if q and q != "=":
            r_out["qualifier"] = _nfkc_str(q)
        if "nrv_pct" in row and row["nrv_pct"] is not None:
            r_out["nrv_pct"] = format_canonical_decimal(row["nrv_pct"])
        canon_rows.append(r_out)

    allergens_decl = core.get("allergens_declared") or {}
    payload: dict[str, Any] = {
        "regulatory_profile": _nfkc_str(core["regulatory_profile"]),
        "net_content": [_canon_qty(nc) for nc in core.get("net_content") or []],
        "nutrition_declared": {
            "basis": _canon_qty(decl["basis"]),
            "rows": canon_rows,
        },
        "ingredients_tree": tree_sigs,
        "allergens_declared": {
            "contains": sorted(
                {_nfkc_str(a) for a in (allergens_decl.get("contains") or []) if str(a).strip()}
            ),
            "may_contain": sorted(
                {_nfkc_str(a) for a in (allergens_decl.get("may_contain") or []) if str(a).strip()}
            ),
        },
    }
    if core.get("serving_size"):
        payload["serving_size"] = _canon_qty(core["serving_size"])

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonical_parties(attributes: dict[str, Any]) -> list[dict[str, str]]:
    """Order-independent signature of legal/supply-chain parties (role, name, plant_code, license)."""
    sigs: list[dict[str, str]] = []
    for p in attributes.get("parties") or []:
        sig = {
            "role": _nfkc_str(p.get("role", "")),
            "name": _nfkc_str(p.get("name", "")),
        }
        if p.get("plant_code"):
            sig["plant_code"] = _nfkc_str(p["plant_code"])
        if p.get("license"):
            sig["license"] = _nfkc_str(p["license"])
        sigs.append(sig)
    return sorted(
        sigs,
        key=lambda s: json.dumps(s, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


def _canonical_origin(attributes: dict[str, Any]) -> dict[str, str]:
    origin = attributes.get("origin") or {}
    out: dict[str, str] = {}
    if origin.get("country"):
        out["country"] = _nfkc_str(origin["country"])
    if origin.get("region"):
        out["region"] = _nfkc_str(origin["region"])
    return out


def compute_label_fingerprint(
    core_fingerprint: str,
    attributes: dict[str, Any],
) -> str:
    """Compute sha256 label fingerprint from core_fingerprint + parties, origin, product_standard, packaging_code."""
    payload = {
        "core_fingerprint": core_fingerprint,
        "parties": _canonical_parties(attributes),
        "origin": _canonical_origin(attributes),
        "product_standard": sorted(
            {_nfkc_str(s) for s in (attributes.get("product_standard") or []) if str(s).strip()}
        ),
        "packaging_code": _nfkc_str(attributes.get("packaging_code") or ""),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _canonicalize_core_in_place(core: dict[str, Any]) -> None:
    """Enforce §3/§8.2 canonical order, decimal formatting, and span-free AST on core in-place."""
    def _clean_qty(qty: dict[str, Any]) -> None:
        qty["value"] = format_canonical_decimal(qty["value"])
        if qty.get("qualifier") in (None, "="):
            qty.pop("qualifier", None)

    for nc in core.get("net_content") or []:
        _clean_qty(nc)
    if "serving_size" in core and isinstance(core["serving_size"], dict):
        _clean_qty(core["serving_size"])

    decl = core["nutrition_declared"]
    _clean_qty(decl["basis"])

    rows = decl.get("rows") or []
    seen_pairs: set[tuple[str, str]] = set()
    for row in rows:
        pair = (str(row["nutrient"]), str(row["unit"]))
        if pair in seen_pairs:
            raise ValueError(f"Duplicate (nutrient, unit) pair in nutrition_declared.rows: {pair!r}")
        seen_pairs.add(pair)
        row["value"] = format_canonical_decimal(row["value"])
        if row.get("qualifier") in (None, "="):
            row.pop("qualifier", None)
        if "nrv_pct" in row and row["nrv_pct"] is not None:
            row["nrv_pct"] = format_canonical_decimal(row["nrv_pct"])
    decl["rows"] = sorted(rows, key=nutrient_row_sort_key)

    def _clean_node_list(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned = strip_ingredient_spans(nodes)
        for node in cleaned:
            if "allergens" in node and isinstance(node["allergens"], list):
                node["allergens"] = sorted({str(a) for a in node["allergens"]})
            if "children" in node and isinstance(node["children"], list):
                node["children"] = _clean_node_list(node["children"])
        return cleaned

    trees = core.get("ingredients_tree") or []
    for lang_entry in trees:
        lang_entry["nodes"] = _clean_node_list(lang_entry.get("nodes") or [])
    core["ingredients_tree"] = sorted(trees, key=lambda item: str(item.get("lang", "")))

    if "allergens_declared" in core and isinstance(core["allergens_declared"], dict):
        ad = core["allergens_declared"]
        if "contains" in ad and isinstance(ad["contains"], list):
            ad["contains"] = sorted({str(a) for a in ad["contains"]})
        if "may_contain" in ad and isinstance(ad["may_contain"], list):
            ad["may_contain"] = sorted({str(a) for a in ad["may_contain"]})


def normalize_edition(edition: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize v0.2 core/supersedes and compile normalized, quality_flags, core_fingerprint, label_fingerprint."""
    core = edition["core"]
    _canonicalize_core_in_place(core)

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

    kj_per_kcal = Decimal(profile.get("kj_per_kcal", "4.184"))
    salt_per_sodium = Decimal(profile.get("salt_per_sodium_ratio", "2.5"))
    zero_thresholds_serving: dict[str, str] = profile.get("zero_thresholds_per_serving", {})
    zero_thresholds_100: dict[str, str] = profile.get("zero_thresholds_per_100", {})
    nrv_reference: dict[str, str] = profile.get("nrv_reference", {})

    panel = core["nutrition_declared"]
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

    quality_flags: list[dict[str, str]] = []
    if is_scaled:
        quality_flags.append(
            {
                "code": "DERIVED_FROM_SERVING_BASIS",
                "field": "nutrition_declared.basis",
                "detail": f"Normalized to {norm_basis} from declared basis {basis_obj['value']}{basis_obj['unit']}",
            }
        )

    nutrients_dict = get_nutrients_registry()
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
                entry = {
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

        # Standard non-energy nutrients
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

    # Cross-derive energy_kcal <-> energy_kj
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

    # Cross-derive sodium (mg) <-> salt_equivalent (g)
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

    # Handle carbohydrate basis flag & optional available carbs derivation
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

    ins_codes, tree_allergens, _tree_sigs = _collect_tree_metadata(ingredients_tree)
    declared_allergens = core.get("allergens_declared") or {}
    declared_contains_alg = sorted(set(declared_allergens.get("contains") or []))
    contains_alg = sorted(set(tree_allergens) | set(declared_contains_alg))
    may_contain_alg = sorted(set(declared_allergens.get("may_contain") or []))

    per_unit_obj: dict[str, Any] | None = None
    unit_source = core.get("serving_size") or (
        core["net_content"][0] if core.get("net_content") else None
    )
    if unit_source:
        u_val_raw = Decimal(unit_source["value"])
        u_val, u_base_unit = _unit_to_base(u_val_raw, unit_source["unit"])
        expected_base = "ml" if norm_basis == "100ml" else "g"
        if u_base_unit.lower() == expected_base and u_val != Decimal("100"):
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
            per_unit_obj = {
                "unit_amount": dict(unit_source),
                "nutrients": per_unit_nutrients,
            }

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


def derive_evidence_level(edition: dict[str, Any]) -> str:
    """Deterministically derive build-time evidence_level from evidence[] per SPEC §8.6."""
    evidence = edition.get("evidence") or []
    photo_contributors: set[str] = set()
    has_official_import = False

    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        if etype == "label_photo":
            sha = str(ev.get("cropped_sha256") or "")
            mref = str(ev.get("media_ref") or "")
            contrib = str(ev.get("contributor") or "").strip()
            if _SHA256_HEX_RE.match(sha) and mref:
                m_media = _OPF_MEDIA_RE.match(mref)
                if mref.startswith("opf-media://") and (not m_media or m_media.group(1) != sha):
                    continue
                if contrib:
                    photo_contributors.add(contrib)
        elif etype in ("official_registry_import", "official_document"):
            has_official_import = True

    if len(photo_contributors) >= 2:
        return "corroborated"
    if len(photo_contributors) == 1:
        return "verified"
    if has_official_import:
        return "official_registry_imported"
    return "community_reported"


def compute_t_active_with_basis(edition: dict[str, Any]) -> tuple[str, str]:
    """Compute (YYYY-MM, basis) where basis is 'vintage_month' or 'earliest_reported_at'."""
    evidence = edition.get("evidence") or []
    vintage_months = [
        str(ev["vintage_month"])
        for ev in evidence
        if isinstance(ev, dict) and ev.get("vintage_month")
    ]
    if vintage_months:
        return max(vintage_months), "vintage_month"

    reported_months = [
        str(ev["reported_at"])[:7]
        for ev in evidence
        if isinstance(ev, dict) and ev.get("reported_at")
    ]
    if not reported_months:
        raise ValueError(
            f"Edition {edition.get('edition_id')!r} has no evidence reported_at or vintage_month"
        )
    return min(reported_months), "earliest_reported_at"


def compute_t_active(edition: dict[str, Any]) -> str:
    """Compute effective market presence month YYYY-MM (max vintage_month, else min reported_at[:7])."""
    ym, _basis = compute_t_active_with_basis(edition)
    return ym


def compute_stale_window_months(edition: dict[str, Any]) -> int:
    """Compute clamped stale window N(E) in [3, 18] months from attributes.shelf_life (default 12)."""
    attributes = edition.get("attributes") or {}
    shelf_life = attributes.get("shelf_life")
    if not isinstance(shelf_life, dict):
        return 12
    val = Decimal(str(shelf_life["value"]))
    unit = str(shelf_life["unit"]).strip().lower()
    if unit in ("month", "months", "mo"):
        months = math.ceil(val)
    elif unit in ("year", "years", "yr"):
        months = math.ceil(val * Decimal("12"))
    elif unit in ("day", "days", "d"):
        months = math.ceil(val / Decimal("30"))
    elif unit in ("week", "weeks", "wk"):
        months = math.ceil((val * Decimal("7")) / Decimal("30"))
    else:
        raise ValueError(f"Unsupported shelf_life unit: {shelf_life['unit']!r}")
    return max(3, min(18, int(months)))


def _months_between(older_ym: str, newer_ym: str) -> int:
    y1, m1 = map(int, older_ym.split("-"))
    y2, m2 = map(int, newer_ym.split("-"))
    return (y2 - y1) * 12 + (m2 - m1)


def _extract_standard_year(edition: dict[str, Any]) -> int:
    candidates: list[int] = []
    profile_id = str((edition.get("core") or {}).get("regulatory_profile") or "")
    for m in _YEAR_4DIGIT_RE.findall(profile_id):
        candidates.append(int(m))
    for std in (edition.get("attributes") or {}).get("product_standard") or []:
        for m in _YEAR_4DIGIT_RE.findall(str(std)):
            candidates.append(int(m))
    return max(candidates) if candidates else 0


def derive_editions_lifecycle(editions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Deterministically derive status, evidence_level, t_active, and superseded_by for all EditionRecords."""
    records: dict[str, dict[str, Any]] = {}
    for ed in editions:
        if isinstance(ed, dict) and "merged_into" not in ed and "edition_id" in ed:
            records[ed["edition_id"]] = ed

    superseded_by: dict[str, list[str]] = {eid: [] for eid in records}
    for eid, ed in records.items():
        state = (ed.get("lifecycle") or {}).get("state")
        if state == "retracted":
            continue
        for target_id in ed.get("supersedes") or []:
            if target_id in superseded_by:
                superseded_by[target_id].append(eid)
    for eid in superseded_by:
        superseded_by[eid] = sorted(set(superseded_by[eid]))

    t_active_pairs = {eid: compute_t_active_with_basis(ed) for eid, ed in records.items()}
    t_active_map: dict[str, str] = {eid: pair[0] for eid, pair in t_active_pairs.items()}
    t_active_basis_map: dict[str, str] = {eid: pair[1] for eid, pair in t_active_pairs.items()}
    ev_level_map: dict[str, str] = {eid: derive_evidence_level(ed) for eid, ed in records.items()}
    status_map: dict[str, str] = {}

    remaining_by_track: dict[str, list[dict[str, Any]]] = {}
    for eid, ed in records.items():
        state = (ed.get("lifecycle") or {}).get("state")
        if state == "retracted":
            status_map[eid] = "retracted"
        elif state == "discontinued":
            status_map[eid] = "discontinued"
        elif superseded_by[eid]:
            status_map[eid] = "superseded"
        else:
            track = str(ed.get("track") or "")
            remaining_by_track.setdefault(track, []).append(ed)

    for _track, candidates in remaining_by_track.items():
        head = max(
            candidates,
            key=lambda e: (
                t_active_map[e["edition_id"]],
                _extract_standard_year(e),
                str((e.get("attributes") or {}).get("packaging_code") or ""),
                e["edition_id"],
            ),
        )
        head_id = head["edition_id"]
        head_t = t_active_map[head_id]
        status_map[head_id] = "active"
        for ed in candidates:
            eid = ed["edition_id"]
            if eid == head_id:
                continue
            gap = _months_between(t_active_map[eid], head_t)
            window = compute_stale_window_months(ed)
            status_map[eid] = "stale" if gap >= window else "active"

    return {
        eid: {
            "status": status_map[eid],
            "evidence_level": ev_level_map[eid],
            "t_active": t_active_map[eid],
            "t_active_basis": t_active_basis_map[eid],
            "superseded_by": superseded_by[eid],
        }
        for eid in records
    }
