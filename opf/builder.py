"""Static API v1 builder for OPF v0.2 split product directories."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from opf import __version__
from opf.ids import api_paths_for_id
from opf.ingredients import annotate_ingredients_spans
from opf.normalize import CANONICAL_NUTRIENT_ORDER, derive_editions_lifecycle
from opf.resources import get_resource_root
from opf.validator import load_json_schema, validate_against_json_schema, validate_products_root

EVIDENCE_LEVEL_RANK: dict[str, int] = {
    "community_reported": 0,
    "official_registry_imported": 1,
    "verified": 2,
    "corroborated": 3,
}

_QUALIFIER_RANK: dict[str, int] = {
    "trace": 0,
    "<": 1,
    "<=": 1,
    "=": 2,
    "~": 2,
    ">=": 3,
    ">": 3,
}

_CANONICAL_RANGE_ORDER: tuple[str, ...] = ("energy_kj", "energy_kcal") + tuple(
    nid for nid in CANONICAL_NUTRIENT_ORDER if nid != "energy"
)


def _detect_git_commit(repo_dir: Path) -> str | None:
    if not any((cand / ".git").exists() for cand in (repo_dir, repo_dir.parent)):
        return None
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def _brand_slug(brand: str) -> str:
    ascii_part = re.sub(r"[^a-z0-9]+", "-", brand.strip().lower()).strip("-")
    if ascii_part and len(ascii_part) >= 2:
        return ascii_part
    short_hash = hashlib.sha256(brand.strip().encode("utf-8")).hexdigest()[:10]
    return f"b-{short_hash}"


def _canon_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _party_summary(p: dict[str, Any]) -> dict[str, Any]:
    return {
        k: p[k]
        for k in ("role", "name", "plant_code", "license")
        if k in p and str(p[k]).strip()
    }


def _dedup_parties(editions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for ed in editions:
        for p in (ed.get("attributes") or {}).get("parties") or []:
            summary = _party_summary(p)
            key = _canon_json(summary)
            if key not in seen:
                seen.add(key)
                out.append(summary)
    return out


def _dedup_origins(editions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for ed in editions:
        origin = (ed.get("attributes") or {}).get("origin")
        if isinstance(origin, dict) and origin:
            key = _canon_json(origin)
            if key not in seen:
                seen.add(key)
                out.append(copy.deepcopy(origin))
    return out


def _dedup_localized_texts(
    editions: list[dict[str, Any]], field: str
) -> list[dict[str, str]]:
    seen_langs: set[str] = set()
    out: list[dict[str, str]] = []
    for ed in editions:
        for item in (ed.get("attributes") or {}).get(field) or []:
            if isinstance(item, dict) and "lang" in item and "text" in item:
                if item["lang"] not in seen_langs:
                    seen_langs.add(item["lang"])
                    out.append({"lang": item["lang"], "text": item["text"]})
    return out


def _normalize_redirects_map(redirects: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for old_id in sorted(redirects.keys()):
        val = redirects[old_id]
        if isinstance(val, dict):
            out[old_id] = str(val["merged_into"])
        else:
            out[old_id] = str(val)
    return out


def _sort_editions(
    edition_records: list[dict[str, Any]], lifecycle_map: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    return sorted(
        edition_records,
        key=lambda e: (lifecycle_map[e["edition_id"]]["t_active"], e["edition_id"]),
    )


def _determine_resolution(active_editions: list[dict[str, Any]]) -> str:
    if not active_editions:
        return "inactive"
    if len(active_editions) == 1:
        return "single"
    fps = {e["core_fingerprint"] for e in active_editions}
    return "uniform" if len(fps) == 1 else "divergent"


def _build_evidence_summary(
    sorted_records: list[dict[str, Any]],
    active_editions: list[dict[str, Any]],
    lifecycle_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    non_retracted = [
        e for e in sorted_records if lifecycle_map[e["edition_id"]]["status"] != "retracted"
    ]
    pool = non_retracted or sorted_records
    by_edition = {
        e["edition_id"]: lifecycle_map[e["edition_id"]]["evidence_level"] for e in pool
    }
    if active_editions:
        active_levels = [lifecycle_map[e["edition_id"]]["evidence_level"] for e in active_editions]
        highest = max(active_levels, key=lambda lv: EVIDENCE_LEVEL_RANK[lv])
        lowest = min(active_levels, key=lambda lv: EVIDENCE_LEVEL_RANK[lv])
    else:
        highest = None
        lowest = None
    return {
        "highest_active": highest,
        "lowest_active": lowest,
        "by_edition": by_edition,
    }


def _select_representative(
    sorted_records: list[dict[str, Any]],
    active_editions: list[dict[str, Any]],
    lifecycle_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if active_editions:
        return active_editions[-1]
    non_retracted = [
        e for e in sorted_records if lifecycle_map[e["edition_id"]]["status"] != "retracted"
    ]
    return (non_retracted or sorted_records)[-1]


def build_full_doc(
    product_meta: dict[str, Any],
    edition_records: list[dict[str, Any]],
    redirects: dict[str, Any],
    lifecycle_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Assemble a v0.2 .full.json document with derived lifecycle/evidence metadata and UI spans."""
    sorted_records = _sort_editions(edition_records, lifecycle_map)
    active_editions = [
        e for e in sorted_records if lifecycle_map[e["edition_id"]]["status"] == "active"
    ]
    active_edition_ids = [e["edition_id"] for e in active_editions]
    resolution = _determine_resolution(active_editions)
    norm_redirects = _normalize_redirects_map(redirects)
    evidence_summary = _build_evidence_summary(sorted_records, active_editions, lifecycle_map)

    assembled_editions: list[dict[str, Any]] = []
    for ed in sorted_records:
        eid = ed["edition_id"]
        lc = lifecycle_map[eid]
        ed_out = copy.deepcopy(ed)
        ed_out["status"] = lc["status"]
        ed_out["evidence_level"] = lc["evidence_level"]
        ed_out["t_active"] = lc["t_active"]
        if lc.get("t_active_basis"):
            ed_out["t_active_basis"] = lc["t_active_basis"]
        if lc["superseded_by"]:
            ed_out["superseded_by"] = list(lc["superseded_by"])

        profile_id = ed["core"]["regulatory_profile"]
        text_by_lang = {
            it["lang"]: it["text"]
            for it in (ed.get("attributes") or {}).get("ingredients_text") or []
            if isinstance(it, dict) and "lang" in it and "text" in it
        }
        annotated_trees: list[dict[str, Any]] = []
        for lang_entry in ed["core"].get("ingredients_tree") or []:
            lang = lang_entry["lang"]
            raw_text = text_by_lang[lang]
            annotated_nodes = annotate_ingredients_spans(
                raw_text, lang_entry["nodes"], profile_id=profile_id
            )
            annotated_trees.append({"lang": lang, "nodes": annotated_nodes})
        ed_out["ingredients_tree_annotated"] = annotated_trees
        assembled_editions.append(ed_out)

    full_doc: dict[str, Any] = {
        "opf_schema": "0.2",
        "id": product_meta["id"],
        "resolution": resolution,
        "active_edition_ids": active_edition_ids,
        "evidence_summary": evidence_summary,
        "editions": assembled_editions,
    }
    if product_meta.get("aliases"):
        full_doc["aliases"] = list(product_meta["aliases"])
    if product_meta.get("tracks"):
        full_doc["tracks"] = copy.deepcopy(product_meta["tracks"])
    if norm_redirects:
        full_doc["edition_redirects"] = norm_redirects
    return full_doc


def _compute_nutrient_ranges(active_editions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    total_variants = len(active_editions)
    all_keys: set[str] = set()
    for ed in active_editions:
        all_keys.update((ed["normalized"].get("nutrients") or {}).keys())

    ordered_keys = [k for k in _CANONICAL_RANGE_ORDER if k in all_keys] + sorted(
        k for k in all_keys if k not in _CANONICAL_RANGE_ORDER
    )

    ranges: dict[str, dict[str, Any]] = {}
    for nk in ordered_keys:
        entries = [
            ed["normalized"]["nutrients"][nk]
            for ed in active_editions
            if nk in (ed["normalized"].get("nutrients") or {})
        ]
        if not entries:
            continue
        units = {en["unit"] for en in entries}
        if len(units) != 1:
            continue
        unit = next(iter(units))

        def _sort_val(en: dict[str, Any]) -> tuple[Decimal, int]:
            q = en.get("qualifier") or "="
            return (Decimal(en["value"]), _QUALIFIER_RANK.get(q, 2))

        lo = min(entries, key=_sort_val)
        hi = max(entries, key=_sort_val)
        rng: dict[str, Any] = {
            "min": lo["value"],
            "max": hi["value"],
            "unit": unit,
        }
        lo_q = lo.get("qualifier")
        if lo_q and lo_q != "=":
            rng["min_qualifier"] = lo_q
        hi_q = hi.get("qualifier")
        if hi_q and hi_q != "=":
            rng["max_qualifier"] = hi_q
        if len(entries) < total_variants:
            rng["partial"] = True
            rng["declared_in_variants"] = len(entries)
            rng["total_variants"] = total_variants
        ranges[nk] = rng
    return ranges


def _compute_differing_fields(active_editions: list[dict[str, Any]]) -> list[str]:
    diffs: list[str] = []
    if len({e["core"]["regulatory_profile"] for e in active_editions}) > 1:
        diffs.append("regulatory_profile")
    if len({_canon_json(e["core"]["net_content"]) for e in active_editions}) > 1:
        diffs.append("net_content")
    if (
        len(
            {
                _canon_json((e["normalized"]["basis"], e["normalized"]["nutrients"]))
                for e in active_editions
            }
        )
        > 1
    ):
        diffs.append("nutrients")
    if len({_canon_json(e["core"]["ingredients_tree"]) for e in active_editions}) > 1:
        diffs.append("ingredients")
    if (
        len(
            {
                tuple((e["normalized"].get("allergens") or {}).get("contains") or [])
                for e in active_editions
            }
        )
        > 1
    ):
        diffs.append("allergens.contains")
    if (
        len(
            {
                tuple((e["normalized"].get("allergens") or {}).get("may_contain") or [])
                for e in active_editions
            }
        )
        > 1
    ):
        diffs.append("allergens.may_contain")
    if len({tuple(e["normalized"].get("additives_ins") or []) for e in active_editions}) > 1:
        diffs.append("additives_ins")
    if len({_canon_json((e.get("attributes") or {}).get("origin") or {}) for e in active_editions}) > 1:
        diffs.append("origin")

    def _sorted_parties_sig(ed: dict[str, Any]) -> str:
        parties = [_party_summary(p) for p in ((ed.get("attributes") or {}).get("parties") or [])]
        return _canon_json(sorted(parties, key=_canon_json))

    if len({_sorted_parties_sig(e) for e in active_editions}) > 1:
        diffs.append("parties")
    if (
        len(
            {
                tuple(sorted((e.get("attributes") or {}).get("product_standard") or []))
                for e in active_editions
            }
        )
        > 1
    ):
        diffs.append("product_standard")
    return diffs


def _build_disambiguation(
    product_meta: dict[str, Any], active_editions: list[dict[str, Any]]
) -> dict[str, Any]:
    track_defs = {
        t["track"]: t
        for t in (product_meta.get("tracks") or [])
        if isinstance(t, dict) and isinstance(t.get("track"), str)
    }
    by_track: dict[str, list[dict[str, Any]]] = {}
    for ed in active_editions:
        by_track.setdefault(ed["track"], []).append(ed)

    tracks_order = list(by_track.keys())
    all_distinct_documented = len(tracks_order) == len(active_editions) and all(
        not tr.endswith("/default") and tr in track_defs for tr in tracks_order
    )
    if all_distinct_documented:
        mode = "by_track"
    elif len(tracks_order) == 1:
        mode = "unsplit_ambiguity"
    else:
        mode = "mixed"

    tracks_guide: list[dict[str, Any]] = []
    for tr in tracks_order:
        eds = by_track[tr]
        guide_item: dict[str, Any] = {
            "track": tr,
            "market": tr.split("/", 1)[0],
        }
        if len(eds) == 1:
            guide_item["edition_id"] = eds[0]["edition_id"]
        else:
            guide_item["edition_ids"] = [e["edition_id"] for e in eds]

        tdef = track_defs.get(tr)
        if tdef:
            if tdef.get("label"):
                guide_item["label"] = copy.deepcopy(tdef["label"])
            if tdef.get("discriminator"):
                guide_item["discriminator"] = copy.deepcopy(tdef["discriminator"])
        elif tr.endswith("/default"):
            guide_item["instructions"] = [
                {
                    "lang": "zh-Hans",
                    "text": "同一默认轨道下存在多个不同配方的活跃版本，请核对包装营养成分表、净含量或厂商信息。",
                },
                {
                    "lang": "en",
                    "text": "Multiple active formulations share this default track; match nutrition values, net content, or manufacturer text on the package.",
                },
            ]
        tracks_guide.append(guide_item)

    disamb: dict[str, Any] = {
        "mode": mode,
        "tracks_guide": tracks_guide,
    }
    if mode in ("unsplit_ambiguity", "mixed"):
        disamb["instructions"] = [
            {
                "lang": "zh-Hans",
                "text": "请勿直接猜测营养数值：请核对用户手头包装的净含量、营养成分表数值、配料表或生产商（SC证号）并从 variants[] 中选择对应 edition_id。",
            },
            {
                "lang": "en",
                "text": "Do not guess nutrition values: ask the user to verify printed net content, nutrition values, ingredients, or manufacturer/SC license on the package and select a concrete edition_id from variants[].",
            },
        ]
    return disamb


def build_compact_doc(
    product_meta: dict[str, Any],
    edition_records: list[dict[str, Any]],
    redirects: dict[str, Any],
    lifecycle_map: dict[str, dict[str, Any]],
    full_rel_path: str,
) -> dict[str, Any]:
    """Compile a v0.2 Compact Agent endpoint document and validate against compact.v0.2.schema.json."""
    sorted_records = _sort_editions(edition_records, lifecycle_map)
    active_editions = [
        e for e in sorted_records if lifecycle_map[e["edition_id"]]["status"] == "active"
    ]
    active_edition_ids = [e["edition_id"] for e in active_editions]
    resolution = _determine_resolution(active_editions)
    norm_redirects = _normalize_redirects_map(redirects)
    evidence_summary = _build_evidence_summary(sorted_records, active_editions, lifecycle_map)
    rep = _select_representative(sorted_records, active_editions, lifecycle_map)
    rep_attrs = rep.get("attributes") or {}
    full_url = full_rel_path if full_rel_path.startswith("/") else f"/{full_rel_path}"

    editions_summary: list[dict[str, Any]] = []
    for ed in sorted_records:
        eid = ed["edition_id"]
        lc = lifecycle_map[eid]
        item: dict[str, Any] = {
            "edition_id": eid,
            "rev": ed["rev"],
            "track": ed["track"],
            "status": lc["status"],
            "t_active": lc["t_active"],
            "evidence_level": lc["evidence_level"],
            "core_fingerprint": ed["core_fingerprint"],
            "label_fingerprint": ed["label_fingerprint"],
        }
        if lc.get("t_active_basis"):
            item["t_active_basis"] = lc["t_active_basis"]
        if lc["superseded_by"]:
            item["superseded_by"] = list(lc["superseded_by"])
        pkg_code = (ed.get("attributes") or {}).get("packaging_code")
        if pkg_code:
            item["packaging_code"] = pkg_code
        editions_summary.append(item)

    product_name_list = (
        _dedup_localized_texts(active_editions, "product_name")
        if active_editions
        else copy.deepcopy(rep_attrs["product_name"])
    )

    compact: dict[str, Any] = {
        "opf_schema": "0.2",
        "id": product_meta["id"],
        "resolution": resolution,
        "active_edition_ids": active_edition_ids,
        "evidence_summary": evidence_summary,
        "brand": rep_attrs["brand"],
        "product_name": product_name_list,
    }
    if product_meta.get("aliases"):
        compact["aliases"] = list(product_meta["aliases"])
    if norm_redirects:
        compact["edition_redirects"] = norm_redirects
    if rep_attrs.get("category"):
        compact["category"] = rep_attrs["category"]
    if rep_attrs.get("declared_category"):
        compact["declared_category"] = rep_attrs["declared_category"]

    if resolution == "inactive":
        pass
    elif resolution == "single":
        ed = active_editions[0]
        attrs = ed.get("attributes") or {}
        lc = lifecycle_map[ed["edition_id"]]
        compact["active_tracks"] = [ed["track"]]
        compact["regulatory_profile"] = ed["core"]["regulatory_profile"]
        compact["core_fingerprint"] = ed["core_fingerprint"]
        compact["label_fingerprint"] = ed["label_fingerprint"]
        compact["t_active"] = lc["t_active"]
        if lc.get("t_active_basis"):
            compact["t_active_basis"] = lc["t_active_basis"]
        compact["net_content"] = copy.deepcopy(ed["core"]["net_content"])
        if ed["core"].get("serving_size"):
            compact["serving_size"] = copy.deepcopy(ed["core"]["serving_size"])
        if attrs.get("origin"):
            compact["origin_summary"] = copy.deepcopy(attrs["origin"])
        parties = _dedup_parties([ed])
        if parties:
            compact["parties_summary"] = parties
        if attrs.get("product_standard"):
            compact["product_standard"] = list(attrs["product_standard"])
        if attrs.get("packaging_code"):
            compact["packaging_code"] = attrs["packaging_code"]
        if attrs.get("special_indicators"):
            compact["special_indicators"] = copy.deepcopy(attrs["special_indicators"])
        if attrs.get("shelf_life"):
            compact["shelf_life"] = copy.deepcopy(attrs["shelf_life"])
        if attrs.get("storage_text"):
            compact["storage_text"] = attrs["storage_text"]
        compact["normalized"] = copy.deepcopy(ed["normalized"])
        compact["ingredients_text"] = copy.deepcopy(attrs["ingredients_text"])
        compact["quality_flags"] = copy.deepcopy(ed.get("quality_flags") or [])
    elif resolution == "uniform":
        compact["active_tracks"] = list(dict.fromkeys(e["track"] for e in active_editions))
        compact["regulatory_profile"] = rep["core"]["regulatory_profile"]
        compact["core_fingerprint"] = rep["core_fingerprint"]
        top_t_ed = max(
            active_editions,
            key=lambda e: (
                lifecycle_map[e["edition_id"]]["t_active"],
                1 if lifecycle_map[e["edition_id"]].get("t_active_basis") == "vintage_month" else 0,
            ),
        )
        top_t_lc = lifecycle_map[top_t_ed["edition_id"]]
        compact["t_active"] = top_t_lc["t_active"]
        if top_t_lc.get("t_active_basis"):
            compact["t_active_basis"] = top_t_lc["t_active_basis"]
        compact["net_content"] = copy.deepcopy(rep["core"]["net_content"])
        if rep["core"].get("serving_size"):
            compact["serving_size"] = copy.deepcopy(rep["core"]["serving_size"])
        origins = _dedup_origins(active_editions)
        if origins:
            compact["origins_summary"] = origins
        parties = _dedup_parties(active_editions)
        if parties:
            compact["parties_summary"] = parties
        std_union = sorted(
            {
                s
                for e in active_editions
                for s in ((e.get("attributes") or {}).get("product_standard") or [])
            }
        )
        if std_union:
            compact["product_standard"] = std_union
        compact["normalized"] = copy.deepcopy(rep["normalized"])
        compact["ingredients_text"] = _dedup_localized_texts(active_editions, "ingredients_text")
        compact["quality_flags"] = copy.deepcopy(rep.get("quality_flags") or [])
    else:  # divergent
        bases = {e["normalized"]["basis"] for e in active_editions}
        common_basis = next(iter(bases)) if len(bases) == 1 else "mixed"

        seen_nc: set[str] = set()
        net_content_values: list[dict[str, Any]] = []
        for e in active_editions:
            for nc in e["core"]["net_content"]:
                key = _canon_json(nc)
                if key not in seen_nc:
                    seen_nc.add(key)
                    net_content_values.append(copy.deepcopy(nc))

        nutrient_ranges = (
            _compute_nutrient_ranges(active_editions) if common_basis != "mixed" else {}
        )
        contains_union = sorted(
            {
                alg
                for e in active_editions
                for alg in ((e["normalized"].get("allergens") or {}).get("contains") or [])
            }
        )
        contains_set = set(contains_union)
        may_contain_union = sorted(
            {
                alg
                for e in active_editions
                for alg in ((e["normalized"].get("allergens") or {}).get("may_contain") or [])
            }
            - contains_set
        )
        additives_union = sorted(
            {
                ins
                for e in active_editions
                for ins in (e["normalized"].get("additives_ins") or [])
            }
        )

        compact["common_summary"] = {
            "basis": common_basis,
            "net_content_values": net_content_values,
            "nutrient_ranges_not_for_logging": nutrient_ranges,
            "allergens_union": {
                "contains": contains_union,
                "may_contain": may_contain_union,
            },
            "additives_ins_union": additives_union,
            "differing_fields": _compute_differing_fields(active_editions),
        }
        compact["disambiguation"] = _build_disambiguation(product_meta, active_editions)

        variants: list[dict[str, Any]] = []
        for e in active_editions:
            eid = e["edition_id"]
            lc = lifecycle_map[eid]
            attrs = e.get("attributes") or {}
            variant: dict[str, Any] = {
                "edition_id": eid,
                "rev": e["rev"],
                "track": e["track"],
                "evidence_level": lc["evidence_level"],
                "regulatory_profile": e["core"]["regulatory_profile"],
                "core_fingerprint": e["core_fingerprint"],
                "label_fingerprint": e["label_fingerprint"],
                "t_active": lc["t_active"],
                "net_content": copy.deepcopy(e["core"]["net_content"]),
            }
            if lc.get("t_active_basis"):
                variant["t_active_basis"] = lc["t_active_basis"]
            if e["core"].get("serving_size"):
                variant["serving_size"] = copy.deepcopy(e["core"]["serving_size"])
            if attrs.get("origin"):
                variant["origin"] = copy.deepcopy(attrs["origin"])
            v_parties = _dedup_parties([e])
            if v_parties:
                variant["parties_summary"] = v_parties
            if attrs.get("product_standard"):
                variant["product_standard"] = list(attrs["product_standard"])
            if attrs.get("packaging_code"):
                variant["packaging_code"] = attrs["packaging_code"]
            if attrs.get("special_indicators"):
                variant["special_indicators"] = copy.deepcopy(attrs["special_indicators"])
            if attrs.get("shelf_life"):
                variant["shelf_life"] = copy.deepcopy(attrs["shelf_life"])
            if attrs.get("storage_text"):
                variant["storage_text"] = attrs["storage_text"]
            variant["normalized"] = copy.deepcopy(e["normalized"])
            variant["ingredients_text"] = copy.deepcopy(attrs["ingredients_text"])
            variant["quality_flags"] = copy.deepcopy(e.get("quality_flags") or [])
            variants.append(variant)
        compact["variants"] = variants

    compact["editions_summary"] = editions_summary
    compact["full_url"] = full_url

    schema_errs = validate_against_json_schema(compact, load_json_schema("compact.v0.2.schema.json"))
    if schema_errs:
        raise ValueError(f"Compact schema validation failed for {product_meta['id']}: {schema_errs}")
    return compact


def _format_net_content_str(items: list[dict[str, Any]]) -> str:
    return " / ".join(
        f"{item.get('qualifier', '') if item.get('qualifier') not in (None, '=') else ''}{item['value']}{item['unit']}"
        for item in items
    )


def _compute_energy_kcal_100_summary(
    compact_doc: dict[str, Any], resolution: str
) -> str | None:
    if resolution in ("single", "uniform"):
        nutrients = compact_doc["normalized"].get("nutrients") or {}
        kcal = nutrients.get("energy_kcal")
        if not kcal:
            return None
        q = kcal.get("qualifier") or ""
        return f"{'' if q == '=' else q}{kcal['value']}"
    if resolution == "divergent":
        common = compact_doc["common_summary"]
        if common["basis"] == "mixed":
            return None
        rng = common["nutrient_ranges_not_for_logging"].get("energy_kcal")
        if not rng:
            return None
        lo = f"{rng.get('min_qualifier', '')}{rng['min']}"
        hi = f"{rng.get('max_qualifier', '')}{rng['max']}"
        return lo if lo == hi else f"{lo}–{hi}"
    return None


def _compute_energy_kcal_num(
    compact_doc: dict[str, Any], resolution: str
) -> float | None:
    """Return numeric per-100 kcal estimate strictly for catalog sorting (None when inactive/mixed)."""
    if resolution in ("single", "uniform"):
        kcal = (compact_doc["normalized"].get("nutrients") or {}).get("energy_kcal")
        if not kcal:
            return None
        return round(float(Decimal(kcal["value"])), 2)
    if resolution == "divergent":
        common = compact_doc["common_summary"]
        if common["basis"] == "mixed":
            return None
        rng = common["nutrient_ranges_not_for_logging"].get("energy_kcal")
        if not rng:
            return None
        mid = (Decimal(rng["min"]) + Decimal(rng["max"])) / Decimal("2")
        return round(float(mid), 2)
    return None


def _collect_ingredients_tokens(editions: list[dict[str, Any]]) -> list[str]:
    """Collect NFKC-normalized lowercase ingredient texts, node names, and INS tags for client search."""
    tokens: set[str] = set()

    def _add_norm(raw: Any) -> None:
        if isinstance(raw, str):
            norm = unicodedata.normalize("NFKC", raw).strip().lower()
            if norm:
                tokens.add(norm)

    def _walk_nodes(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            _add_norm(node.get("name"))
            _add_norm(node.get("functional_class"))
            ins = node.get("ins")
            if isinstance(ins, str) and ins.strip():
                _add_norm(ins)
                _add_norm(f"ins {ins}")
            if isinstance(node.get("children"), list):
                _walk_nodes(node["children"])

    for ed in editions:
        attrs = ed.get("attributes") or {}
        for item in attrs.get("ingredients_text") or []:
            if isinstance(item, dict):
                _add_norm(item.get("text"))
        core = ed.get("core") or {}
        for lang_entry in core.get("ingredients_tree") or []:
            if isinstance(lang_entry, dict) and isinstance(lang_entry.get("nodes"), list):
                _walk_nodes(lang_entry["nodes"])

    return sorted(tokens)


def _compute_nutrients_100(
    compact_doc: dict[str, Any],
    active_editions: list[dict[str, Any]],
    resolution: str,
) -> dict[str, dict[str, Any]]:
    """Build per-100g/100ml min/max/upper-bound/partial nutrient index for strict rule filtering."""
    out: dict[str, dict[str, Any]] = {}
    if resolution in ("single", "uniform"):
        norm = compact_doc["normalized"]
        if norm.get("basis") not in ("100g", "100ml"):
            return out
        for k, entry in (norm.get("nutrients") or {}).items():
            val_f = round(float(Decimal(entry["value"])), 4)
            out[k] = {
                "min": val_f,
                "max": val_f,
                "unit": entry["unit"],
                "has_upper_bound": entry.get("qualifier") in ("<", "<="),
                "partial": False,
            }
        return out

    if resolution == "divergent":
        common = compact_doc["common_summary"]
        if common.get("basis") not in ("100g", "100ml"):
            return out
        ranges = common.get("nutrient_ranges_not_for_logging") or {}
        for k, rng in ranges.items():
            entries_k = [
                e["normalized"]["nutrients"][k]
                for e in active_editions
                if k in ((e.get("normalized") or {}).get("nutrients") or {})
            ]
            has_ub = any(en.get("qualifier") in ("<", "<=") for en in entries_k)
            out[k] = {
                "min": round(float(Decimal(rng["min"])), 4),
                "max": round(float(Decimal(rng["max"])), 4),
                "unit": rng["unit"],
                "has_upper_bound": has_ub,
                "partial": bool(rng.get("partial", False)),
            }
        return out

    return out


def build_static_api(
    data_dir: Path,
    out_dir: Path,
    canonical_base: str = "",
    allow_empty: bool = True,
    media_base_url: str = "",
) -> dict[str, Any]:
    """Validate v0.2 split product directories under data_dir and generate static /v1/ API."""
    root = Path(data_dir)
    val_errors = validate_products_root(root, allow_empty=allow_empty)
    if val_errors:
        raise ValueError("Validation failed during build:\n" + "\n".join(val_errors))

    product_items: list[tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]] = []
    for pjson in sorted(root.rglob("product.json")):
        pdir = pjson.parent
        meta = json.loads(pjson.read_text(encoding="utf-8"))
        editions_dir = pdir / "editions"
        records: list[dict[str, Any]] = []
        redirects: dict[str, str] = {}
        for ef in sorted(editions_dir.glob("*.json")):
            edoc = json.loads(ef.read_text(encoding="utf-8"))
            if "merged_into" in edoc:
                redirects[edoc["edition_id"]] = edoc["merged_into"]
            else:
                records.append(edoc)
        product_items.append((meta, records, redirects))

    product_items.sort(key=lambda item: item[0]["id"])

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    brands_map: dict[str, dict[str, Any]] = {}
    catalog_rows: list[dict[str, Any]] = []
    counts_by_resolution: dict[str, int] = {}
    counts_by_evidence: dict[str, int] = {}
    counts_by_market: dict[str, int] = {}

    for product_meta, records, redirects in product_items:
        pid = product_meta["id"]
        lifecycle_map = derive_editions_lifecycle(records)
        compact_rel, full_rel = api_paths_for_id(pid)

        full_doc = build_full_doc(product_meta, records, redirects, lifecycle_map)
        compact_doc = build_compact_doc(product_meta, records, redirects, lifecycle_map, full_rel)

        compact_out = out_path / compact_rel
        full_out = out_path / full_rel
        compact_out.parent.mkdir(parents=True, exist_ok=True)
        with compact_out.open("w", encoding="utf-8") as f:
            json.dump(compact_doc, f, ensure_ascii=False, separators=(",", ":"))
        with full_out.open("w", encoding="utf-8") as f:
            json.dump(full_doc, f, ensure_ascii=False, indent=2)
            f.write("\n")

        resolution = compact_doc["resolution"]
        counts_by_resolution[resolution] = counts_by_resolution.get(resolution, 0) + 1

        ev_summary = compact_doc["evidence_summary"]
        if ev_summary["highest_active"] is not None:
            top_ev_level = ev_summary["highest_active"]
        elif ev_summary["by_edition"]:
            top_ev_level = max(
                ev_summary["by_edition"].values(),
                key=lambda lv: EVIDENCE_LEVEL_RANK[lv],
            )
        else:
            top_ev_level = "community_reported"
        counts_by_evidence[top_ev_level] = counts_by_evidence.get(top_ev_level, 0) + 1

        sorted_records = _sort_editions(records, lifecycle_map)
        active_editions = [
            e for e in sorted_records if lifecycle_map[e["edition_id"]]["status"] == "active"
        ]
        for mkt in sorted({e["track"].split("/", 1)[0] for e in active_editions}):
            counts_by_market[mkt] = counts_by_market.get(mkt, 0) + 1

        rep = _select_representative(sorted_records, active_editions, lifecycle_map)
        rep_attrs = rep.get("attributes") or {}
        names_i18n = {
            item["lang"]: item["text"]
            for item in compact_doc["product_name"]
            if isinstance(item, dict) and "lang" in item and "text" in item
        }
        brand_names_i18n: dict[str, str] = {}
        for ed_src in [rep, *sorted_records]:
            ed_attrs = ed_src.get("attributes") or {}
            for tr in ed_attrs.get("translations") or []:
                if not isinstance(tr, dict) or not tr.get("lang") or not tr.get("text"):
                    continue
                if tr.get("field") == "product_name":
                    names_i18n.setdefault(tr["lang"], tr["text"])
                elif tr.get("field") == "brand":
                    brand_names_i18n.setdefault(tr["lang"], tr["text"])

        if resolution in ("single", "uniform"):
            net_str = _format_net_content_str(compact_doc["net_content"])
            basis_str = compact_doc["normalized"]["basis"]
        elif resolution == "divergent":
            net_str = _format_net_content_str(compact_doc["common_summary"]["net_content_values"])
            basis_str = compact_doc["common_summary"]["basis"]
        else:
            net_str = _format_net_content_str(rep["core"]["net_content"])
            basis_str = rep["normalized"]["basis"]

        brand_name = compact_doc["brand"]
        if compact_doc["product_name"]:
            first_lang = compact_doc["product_name"][0].get("lang")
            if first_lang and first_lang not in brand_names_i18n:
                brand_names_i18n[first_lang] = brand_name
        b_slug = _brand_slug(brand_name)
        namespace = pid.split(":", 1)[0]
        markets = sorted({e["track"].split("/", 1)[0] for e in (active_editions or sorted_records)})
        filter_editions = active_editions or [rep]
        profiles_list = sorted(
            {
                e["core"]["regulatory_profile"]
                for e in filter_editions
                if (e.get("core") or {}).get("regulatory_profile")
            }
        )
        category_val = compact_doc.get("category") or rep_attrs.get("category") or None
        allergens_contains = sorted(
            {
                alg
                for e in filter_editions
                for alg in ((e["normalized"].get("allergens") or {}).get("contains") or [])
            }
        )
        allergens_may_contain = sorted(
            {
                alg
                for e in filter_editions
                for alg in ((e["normalized"].get("allergens") or {}).get("may_contain") or [])
            }
            - set(allergens_contains)
        )
        additives_ins_list = sorted(
            {ins for e in filter_editions for ins in (e["normalized"].get("additives_ins") or [])}
        )
        additives_count = len(additives_ins_list)
        ingredients_tokens = _collect_ingredients_tokens(filter_editions)
        nutrients_100 = _compute_nutrients_100(compact_doc, active_editions, resolution)

        summary_row: dict[str, Any] = {
            "id": pid,
            "namespace": namespace,
            "name": compact_doc["product_name"][0]["text"],
            "names": names_i18n,
            "brand": brand_name,
            "brand_names": dict(sorted(brand_names_i18n.items())),
            "brand_slug": b_slug,
            "markets": markets,
            "profiles": profiles_list,
            "resolution": resolution,
            "active_edition_ids": compact_doc["active_edition_ids"],
            "evidence_level": top_ev_level,
            "lowest_active_evidence_level": ev_summary["lowest_active"],
            "net_content": net_str,
            "basis": basis_str,
            "energy_kcal_100": _compute_energy_kcal_100_summary(compact_doc, resolution),
            "energy_kcal_num": _compute_energy_kcal_num(compact_doc, resolution),
            "allergens_contains": allergens_contains,
            "allergens_may_contain": allergens_may_contain,
            "additives_ins": additives_ins_list,
            "additives_count": additives_count,
            "ingredients_tokens": ingredients_tokens,
            "nutrients_100": nutrients_100,
            "compact_url": f"/{compact_rel}",
            "full_url": f"/{full_rel}",
        }
        if category_val:
            summary_row["category"] = category_val
        if product_meta.get("aliases"):
            summary_row["aliases"] = list(product_meta["aliases"])

        if b_slug not in brands_map:
            brands_map[b_slug] = {
                "brand_slug": b_slug,
                "brand": brand_name,
                "brand_names": {},
                "count": 0,
                "index_url": f"/v1/index/brand/{b_slug}.json",
                "items": [],
            }
        for lang_k, txt_v in brand_names_i18n.items():
            brands_map[b_slug]["brand_names"].setdefault(lang_k, txt_v)
        brands_map[b_slug]["count"] += 1
        brands_map[b_slug]["items"].append(summary_row)
        catalog_rows.append(summary_row)

    index_dir = out_path / "v1" / "index"
    brand_index_dir = index_dir / "brand"
    brand_index_dir.mkdir(parents=True, exist_ok=True)

    brands_directory = []
    for b_slug, b_info in sorted(brands_map.items()):
        sorted_brand_names = dict(sorted(b_info["brand_names"].items()))
        b_file = brand_index_dir / f"{b_slug}.json"
        with b_file.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "brand_slug": b_slug,
                    "brand": b_info["brand"],
                    "brand_names": sorted_brand_names,
                    "count": b_info["count"],
                    "products": b_info["items"],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.write("\n")
        brands_directory.append(
            {
                "brand_slug": b_slug,
                "brand": b_info["brand"],
                "brand_names": sorted_brand_names,
                "count": b_info["count"],
                "index_url": b_info["index_url"],
            }
        )

    with (index_dir / "brands.json").open("w", encoding="utf-8") as f:
        json.dump({"brands": brands_directory}, f, ensure_ascii=False, indent=2)
        f.write("\n")

    with (index_dir / "catalog.jsonl").open("w", encoding="utf-8") as f:
        for row in catalog_rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    tool_commit = _detect_git_commit(Path(__file__).resolve().parent.parent)
    data_commit = _detect_git_commit(root)

    meta_out: dict[str, Any] = {
        "opf_schema": "0.2",
        "opf_version": __version__,
        "canonical_base": canonical_base,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_products": len(product_items),
        "counts_by_resolution": counts_by_resolution,
        "counts_by_evidence_level": counts_by_evidence,
        "counts_by_market": counts_by_market,
        "endpoints": {
            "gtin_compact": "/v1/gtin/{p1}/{p2}/{gtin14}.json",
            "gtin_full": "/v1/gtin/{p1}/{p2}/{gtin14}.full.json",
            "opf_compact": "/v1/opf/{brand}/{product}/{spec}.json",
            "opf_full": "/v1/opf/{brand}/{product}/{spec}.full.json",
            "brands_index": "/v1/index/brands.json",
            "brand_products": "/v1/index/brand/{brand_slug}.json",
            "catalog_jsonl": "/v1/index/catalog.jsonl",
        },
    }
    if media_base_url:
        meta_out["media_base_url"] = media_base_url.rstrip("/")
    if tool_commit:
        meta_out["opf_tool_commit"] = tool_commit
    if data_commit:
        meta_out["opf_data_commit"] = data_commit

    with (out_path / "v1" / "meta.json").open("w", encoding="utf-8") as f:
        json.dump(meta_out, f, ensure_ascii=False, indent=2)
        f.write("\n")

    _copy_web_assets(out_path)
    return meta_out


def _copy_web_assets(out_dir: Path) -> None:
    """Copy the static explorer (web/) and locale files into the site root."""
    web_dir = get_resource_root() / "web"
    if not web_dir.is_dir():
        return
    assets = out_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(web_dir / "index.html", out_dir / "index.html")
    for name in ("style.css", "app.js", "scanner.js"):
        shutil.copyfile(web_dir / name, assets / name)
    vendor_src = web_dir / "vendor"
    if vendor_src.is_dir():
        vendor_dst = assets / "vendor"
        vendor_dst.mkdir(parents=True, exist_ok=True)
        for vfile in sorted(vendor_src.iterdir()):
            if vfile.is_file() and not vfile.name.startswith("."):
                shutil.copyfile(vfile, vendor_dst / vfile.name)
    locales_src = web_dir / "locales"
    if locales_src.is_dir():
        locales_dst = out_dir / "locales"
        locales_dst.mkdir(parents=True, exist_ok=True)
        for lfile in sorted(locales_src.glob("*.json")):
            shutil.copyfile(lfile, locales_dst / lfile.name)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
