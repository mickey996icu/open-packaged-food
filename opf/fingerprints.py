"""Canonical ordering, decimal formatting, NFKC signatures, and SHA-256 fingerprints for OPF v0.3."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from decimal import Decimal
from typing import Any

from opf.ingredients import strip_ingredient_spans
from opf.registries import load_nutrients_dict

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


def canonicalize_special_indicator(item: dict[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize a single SpecialIndicator entry (no trailing zeros, mutex constraints)."""
    if not isinstance(item, dict):
        raise ValueError("SpecialIndicator entry must be an object")
    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("core.special_indicators[].name must be non-empty")
    val_s = format_canonical_decimal(item["value"])
    val_dec = Decimal(val_s)

    raw_qual = item.get("qualifier")
    qual = str(raw_qual).strip() if raw_qual not in (None, "=", "") else None
    raw_tol = item.get("tolerance")
    raw_vmax = item.get("value_max")
    has_tol = raw_tol is not None and str(raw_tol).strip() != ""
    has_vmax = raw_vmax is not None and str(raw_vmax).strip() != ""

    if has_tol and has_vmax:
        raise ValueError("core.special_indicators[]: tolerance and value_max are mutually exclusive")
    if has_tol and qual is not None:
        raise ValueError("core.special_indicators[]: tolerance and qualifier are mutually exclusive")
    if has_vmax and qual is not None:
        raise ValueError("core.special_indicators[]: value_max and qualifier are mutually exclusive")

    out: dict[str, Any] = {"name": name}
    if qual is not None:
        out["qualifier"] = qual
    out["value"] = val_s
    if has_vmax:
        vmax_s = format_canonical_decimal(raw_vmax)
        if Decimal(vmax_s) < val_dec:
            raise ValueError(
                f"core.special_indicators[]: value_max ({vmax_s}) must be >= value ({val_s})"
            )
        out["value_max"] = vmax_s
    if has_tol:
        tol_s = format_canonical_decimal(raw_tol)
        if Decimal(tol_s) <= Decimal("0"):
            raise ValueError(f"core.special_indicators[]: tolerance ({tol_s}) must be > 0")
        out["tolerance"] = tol_s
    raw_unit = item.get("unit")
    if raw_unit is not None and str(raw_unit).strip():
        out["unit"] = str(raw_unit).strip()
    return out


def compute_core_fingerprint(core: dict[str, Any]) -> str:
    """Compute canonical JSON SHA-256 over NFKC-normalized v0.3 core layer."""
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

    decl = core.get("nutrition_declared")
    if decl is None:
        ex = core.get("nutrition_exemption") or {}
        if not isinstance(ex, dict) or not str(ex.get("category") or "").strip():
            raise ValueError("core.nutrition_exemption.category is required when nutrition_declared is null")
        nut_decl_fp: Any = None
    else:
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
        nut_decl_fp = {
            "basis": _canon_qty(decl["basis"]),
            "rows": canon_rows,
        }

    allergens_decl = core.get("allergens_declared") or {}
    payload: dict[str, Any] = {
        "regulatory_profile": _nfkc_str(core["regulatory_profile"]),
        "net_content": [_canon_qty(nc) for nc in core.get("net_content") or []],
        "nutrition_declared": nut_decl_fp,
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
    if decl is None:
        payload["nutrition_exemption"] = {
            "category": _nfkc_str(core["nutrition_exemption"]["category"])
        }
    if core.get("serving_size"):
        payload["serving_size"] = _canon_qty(core["serving_size"])
    if core.get("special_indicators"):
        canon_inds = [_nfkc_obj(canonicalize_special_indicator(it)) for it in core["special_indicators"]]
        payload["special_indicators"] = sorted(
            canon_inds,
            key=lambda it: json.dumps(it, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )

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


def canonicalize_core_in_place(core: dict[str, Any]) -> None:
    """Enforce §3/§8.2 canonical order, decimal formatting, and span-free AST on core in-place."""
    def _clean_qty(qty: dict[str, Any]) -> None:
        qty["value"] = format_canonical_decimal(qty["value"])
        if qty.get("qualifier") in (None, "="):
            qty.pop("qualifier", None)

    for nc in core.get("net_content") or []:
        _clean_qty(nc)
    if "serving_size" in core and isinstance(core["serving_size"], dict):
        _clean_qty(core["serving_size"])

    decl = core.get("nutrition_declared")
    if decl is None:
        ex = core.get("nutrition_exemption")
        if not isinstance(ex, dict) or not str(ex.get("category") or "").strip():
            raise ValueError(
                "core.nutrition_exemption with non-empty category is required when core.nutrition_declared is null"
            )
        ex["category"] = str(ex["category"]).strip()
        for opt_key in ("legal_basis", "note"):
            if opt_key in ex:
                cleaned_val = str(ex[opt_key] or "").strip()
                if cleaned_val:
                    ex[opt_key] = cleaned_val
                else:
                    ex.pop(opt_key, None)
    else:
        if core.get("nutrition_exemption") is not None:
            raise ValueError(
                "core.nutrition_exemption is forbidden when core.nutrition_declared is present"
            )
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

    if "special_indicators" in core:
        raw_inds = core.get("special_indicators")
        if not raw_inds:
            core.pop("special_indicators", None)
        else:
            canon_inds: list[dict[str, Any]] = []
            seen_inds: set[str] = set()
            for item in raw_inds:
                c_item = canonicalize_special_indicator(item)
                sig = json.dumps(c_item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if sig in seen_inds:
                    raise ValueError(f"Duplicate entry in core.special_indicators: {c_item!r}")
                seen_inds.add(sig)
                canon_inds.append(c_item)
            core["special_indicators"] = canon_inds

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
