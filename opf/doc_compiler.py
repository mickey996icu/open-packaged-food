"""Single-product Full (.full.json) and Compact (.json) endpoint document compiler for OPF v0.3."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from typing import Any

from opf.fingerprints import CANONICAL_NUTRIENT_ORDER, canonicalize_special_indicator
from opf.ingredients import annotate_ingredients_spans
from opf.json_schema import load_json_schema, validate_against_json_schema

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


def sort_editions(
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


def select_representative(
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
    """Assemble a v0.3 .full.json document with derived lifecycle/evidence metadata and UI spans."""
    sorted_records = sort_editions(edition_records, lifecycle_map)
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
        "opf_schema": "0.3",
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
    if (
        len(
            {
                str((e["core"].get("nutrition_exemption") or {}).get("category") or "")
                for e in active_editions
            }
        )
        > 1
    ):
        diffs.append("nutrition_exemption")
    if (
        len(
            {
                _canon_json(
                    sorted(
                        [
                            canonicalize_special_indicator(it)
                            for it in (e["core"].get("special_indicators") or [])
                        ],
                        key=_canon_json,
                    )
                )
                for e in active_editions
            }
        )
        > 1
    ):
        diffs.append("special_indicators")
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
    if (
        len(
            {
                str((e.get("attributes") or {}).get("quality_grade") or "").strip()
                for e in active_editions
            }
        )
        > 1
    ):
        diffs.append("quality_grade")
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
    """Compile a v0.3 Compact Agent endpoint document and validate against compact.v0.3.schema.json."""
    sorted_records = sort_editions(edition_records, lifecycle_map)
    active_editions = [
        e for e in sorted_records if lifecycle_map[e["edition_id"]]["status"] == "active"
    ]
    active_edition_ids = [e["edition_id"] for e in active_editions]
    resolution = _determine_resolution(active_editions)
    norm_redirects = _normalize_redirects_map(redirects)
    evidence_summary = _build_evidence_summary(sorted_records, active_editions, lifecycle_map)
    rep = select_representative(sorted_records, active_editions, lifecycle_map)
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
        "opf_schema": "0.3",
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
        if ed["core"].get("nutrition_exemption"):
            compact["nutrition_exemption"] = copy.deepcopy(ed["core"]["nutrition_exemption"])
        if attrs.get("origin"):
            compact["origin_summary"] = copy.deepcopy(attrs["origin"])
        parties = _dedup_parties([ed])
        if parties:
            compact["parties_summary"] = parties
        if attrs.get("product_standard"):
            compact["product_standard"] = list(attrs["product_standard"])
        if attrs.get("packaging_code"):
            compact["packaging_code"] = attrs["packaging_code"]
        if attrs.get("quality_grade"):
            compact["quality_grade"] = attrs["quality_grade"]
        if ed["core"].get("special_indicators"):
            compact["special_indicators"] = copy.deepcopy(ed["core"]["special_indicators"])
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
        if rep["core"].get("nutrition_exemption"):
            compact["nutrition_exemption"] = copy.deepcopy(rep["core"]["nutrition_exemption"])
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
        grades = [
            str((e.get("attributes") or {}).get("quality_grade") or "").strip()
            for e in active_editions
        ]
        if grades and all(grades) and len(set(grades)) == 1:
            compact["quality_grade"] = grades[0]
        if rep["core"].get("special_indicators"):
            compact["special_indicators"] = copy.deepcopy(rep["core"]["special_indicators"])
        compact["normalized"] = copy.deepcopy(rep["normalized"])
        compact["ingredients_text"] = _dedup_localized_texts(active_editions, "ingredients_text")
        compact["quality_flags"] = copy.deepcopy(rep.get("quality_flags") or [])
    else:  # divergent
        bases = {e["normalized"]["basis"] for e in active_editions}
        common_basis = next(iter(bases)) if len(bases) == 1 else "mixed"

        seen_nc: set[str] = set()
        net_content_values: list[dict[str, Any]] = []
        for e in active_editions:
            for nc in e["core"].get("net_content") or []:
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
            if e["core"].get("nutrition_exemption"):
                variant["nutrition_exemption"] = copy.deepcopy(e["core"]["nutrition_exemption"])
            if attrs.get("origin"):
                variant["origin"] = copy.deepcopy(attrs["origin"])
            v_parties = _dedup_parties([e])
            if v_parties:
                variant["parties_summary"] = v_parties
            if attrs.get("product_standard"):
                variant["product_standard"] = list(attrs["product_standard"])
            if attrs.get("packaging_code"):
                variant["packaging_code"] = attrs["packaging_code"]
            if attrs.get("quality_grade"):
                variant["quality_grade"] = attrs["quality_grade"]
            if e["core"].get("special_indicators"):
                variant["special_indicators"] = copy.deepcopy(e["core"]["special_indicators"])
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

    schema_errs = validate_against_json_schema(compact, load_json_schema("compact.v0.3.schema.json"))
    if schema_errs:
        raise ValueError(f"Compact schema validation failed for {product_meta['id']}: {schema_errs}")
    return compact
