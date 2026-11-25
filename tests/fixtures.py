"""Self-contained v0.2 unit test fixtures for OpenPackagedFood (opf)."""

from __future__ import annotations

import copy
from typing import Any

from opf.ids import generate_ulid
from opf.ingredients import parse_ingredients_semantic
from opf.normalize import normalize_edition


def _build_initial_edition(
    *,
    product_id: str,
    edition_id: str | None = None,
    track: str,
    core: dict[str, Any],
    attributes: dict[str, Any],
    evidence: list[dict[str, Any]],
    author: str = "github:tester-a",
    provenance: str = "external_contributor",
    created_at: str = "2026-01-15T00:00:00Z",
    supersedes: list[str] | None = None,
) -> dict[str, Any]:
    ev_list = []
    for ev in evidence:
        ev_copy = copy.deepcopy(ev)
        ev_copy.setdefault("provenance", provenance)
        ev_list.append(ev_copy)
    ed: dict[str, Any] = {
        "opf_schema": "0.2",
        "id": product_id,
        "edition_id": edition_id or generate_ulid(),
        "rev": 1,
        "track": track,
        "supersedes": list(supersedes or []),
        "core": core,
        "attributes": attributes,
        "evidence": ev_list,
        "revisions": [
            {
                "rev": 1,
                "kind": "initial",
                "created_at": created_at,
                "author": author,
                "provenance": provenance,
                "evidence_refs": [ev["evidence_id"] for ev in ev_list],
                "patch": [],
            }
        ],
    }
    normalize_edition(ed)
    return ed


def make_cn_tea_fixture(edition_id: str | None = None) -> dict[str, Any]:
    """Return a normalized v0.2 CN/GB28050-2011 EditionRecord for Sample Jasmine Tea."""
    raw_ing = "水、茉莉花茶（绿茶茶坯）（≥4g/L）、维生素C、碳酸氢钠"
    profile_id = "CN/GB28050-2011"
    core: dict[str, Any] = {
        "regulatory_profile": profile_id,
        "net_content": [{"value": "900", "unit": "ml"}],
        "nutrition_declared": {
            "basis": {"value": "100", "unit": "ml"},
            "rows": [
                {"nutrient": "energy", "value": "0", "unit": "kJ", "nrv_pct": "0"},
                {"nutrient": "protein", "value": "0", "unit": "g", "nrv_pct": "0"},
                {"nutrient": "fat_total", "value": "0", "unit": "g", "nrv_pct": "0"},
                {"nutrient": "carbs_available", "value": "0", "unit": "g", "nrv_pct": "0"},
                {"nutrient": "sodium", "value": "0", "unit": "mg", "nrv_pct": "0"},
            ],
        },
        "ingredients_tree": [
            {
                "lang": "zh-Hans",
                "nodes": parse_ingredients_semantic(raw_ing, lang="zh-Hans", profile_id=profile_id),
            }
        ],
    }
    attributes: dict[str, Any] = {
        "product_name": [
            {"lang": "zh-Hans", "text": "示例茉莉花茶"},
            {"lang": "en", "text": "Sample Jasmine Tea"},
        ],
        "brand": "示例茶饮",
        "category": "beverages/tea_unsweetened",
        "declared_category": "原味茶饮料",
        "ingredients_text": [{"lang": "zh-Hans", "text": raw_ing}],
        "special_indicators": [
            {"name": "tea_polyphenols", "qualifier": ">=", "value": "180", "unit": "mg/kg"}
        ],
        "product_standard": ["GB/T 21733"],
        "shelf_life": {"value": "12", "unit": "month"},
    }
    evidence = [
        {
            "evidence_id": "ev:01JTESTCNTEA00000000000001",
            "type": "community_report",
            "contributor": "github:tester-a",
            "reported_at": "2026-01-15",
            "vintage_month": "2026-01",
        }
    ]
    return copy.deepcopy(
        _build_initial_edition(
            product_id="gtin:00000000000109",
            edition_id=edition_id or "01JTESTCNTEA00000000000001",
            track="CN/default",
            core=core,
            attributes=attributes,
            evidence=evidence,
        )
    )


def make_cn_patty_fixture(edition_id: str | None = None) -> dict[str, Any]:
    """Return a normalized v0.2 CN/GB28050-2011 EditionRecord for an opf: beef patty."""
    raw_ing = "牛肉、食用盐、黑胡椒碎"
    profile_id = "CN/GB28050-2011"
    core: dict[str, Any] = {
        "regulatory_profile": profile_id,
        "net_content": [{"value": "80", "unit": "g"}],
        "nutrition_declared": {
            "basis": {"value": "100", "unit": "g"},
            "rows": [
                {"nutrient": "energy", "value": "1091", "unit": "kJ", "nrv_pct": "13"},
                {"nutrient": "protein", "value": "18.6", "unit": "g", "nrv_pct": "31"},
                {"nutrient": "fat_total", "value": "20.2", "unit": "g", "nrv_pct": "34"},
                {"nutrient": "carbs_available", "value": "1.0", "unit": "g", "nrv_pct": "0"},
                {"nutrient": "sodium", "value": "510", "unit": "mg", "nrv_pct": "26"},
            ],
        },
        "ingredients_tree": [
            {
                "lang": "zh-Hans",
                "nodes": parse_ingredients_semantic(raw_ing, lang="zh-Hans", profile_id=profile_id),
            }
        ],
    }
    attributes: dict[str, Any] = {
        "product_name": [{"lang": "zh-Hans", "text": "黑椒风味牛肉饼"}],
        "brand": "示例生鲜",
        "net_content_label": "单枚 80g",
        "ingredients_text": [{"lang": "zh-Hans", "text": raw_ing}],
        "product_standard": ["SB/T 10379"],
    }
    evidence = [
        {
            "evidence_id": "ev:01JTESTCNPATTY000000000001",
            "type": "community_report",
            "contributor": "github:tester-a",
            "reported_at": "2026-01-15",
            "vintage_month": "2026-01",
        }
    ]
    return copy.deepcopy(
        _build_initial_edition(
            product_id="opf:demo-deli/black-pepper-patty/80g",
            edition_id=edition_id or "01JTESTCNPATTY000000000001",
            track="CN/default",
            core=core,
            attributes=attributes,
            evidence=evidence,
        )
    )


def make_us_cookies_fixture(edition_id: str | None = None) -> dict[str, Any]:
    """Return a normalized v0.2 US/FDA-NLEA EditionRecord for Crispy Oat Cookies."""
    raw_ing = "Ingredients: Rolled oats, Wheat flour, Sugar, Palm oil, Soy lecithin, Baking soda."
    profile_id = "US/FDA-NLEA"
    core: dict[str, Any] = {
        "regulatory_profile": profile_id,
        "net_content": [{"value": "280", "unit": "g"}],
        "serving_size": {"value": "28", "unit": "g"},
        "nutrition_declared": {
            "basis": {"value": "28", "unit": "g"},
            "rows": [
                {"nutrient": "energy", "value": "140", "unit": "kcal", "nrv_pct": "7"},
                {"nutrient": "fat_total", "value": "6", "unit": "g", "nrv_pct": "8"},
                {"nutrient": "fat_saturated", "value": "2.5", "unit": "g", "nrv_pct": "13"},
                {"nutrient": "fat_trans", "value": "0", "unit": "g"},
                {"nutrient": "cholesterol", "value": "0", "unit": "mg", "nrv_pct": "0"},
                {"nutrient": "sodium", "value": "95", "unit": "mg", "nrv_pct": "4"},
                {"nutrient": "carbs_total", "value": "19", "unit": "g", "nrv_pct": "7"},
                {"nutrient": "dietary_fiber", "value": "2", "unit": "g", "nrv_pct": "7"},
                {"nutrient": "sugars_total", "value": "7", "unit": "g"},
                {"nutrient": "sugars_added", "value": "7", "unit": "g", "nrv_pct": "14"},
                {"nutrient": "protein", "value": "2", "unit": "g", "nrv_pct": "4"},
            ],
        },
        "ingredients_tree": [
            {
                "lang": "en",
                "nodes": parse_ingredients_semantic(raw_ing, lang="en", profile_id=profile_id),
            }
        ],
        "allergens_declared": {
            "contains": ["gluten_cereals", "soybeans"],
            "may_contain": ["milk", "tree_nuts"],
        },
    }
    attributes: dict[str, Any] = {
        "product_name": [{"lang": "en", "text": "Crispy Oat Cookies"}],
        "brand": "Test Bakery",
        "serving_size_label": "2 cookies (28g)",
        "ingredients_text": [{"lang": "en", "text": raw_ing}],
    }
    evidence = [
        {
            "evidence_id": "ev:01JTESTC00K1ES000000000001",
            "type": "official_registry_import",
            "registry": "US/USDA-FDC",
            "query": "FDC-TEST-001",
            "reported_at": "2026-01-15",
            "vintage_month": "2026-01",
        }
    ]
    return copy.deepcopy(
        _build_initial_edition(
            product_id="opf:test-bakery/crispy-oat-cookies/280g",
            edition_id=edition_id or "01JTESTC00K1ES000000000001",
            track="US/default",
            core=core,
            attributes=attributes,
            evidence=evidence,
        )
    )


def make_product_meta_from_edition(
    ed: dict[str, Any],
    *,
    aliases: list[str] | None = None,
    tracks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal valid product.json metadata document matching a fixture edition."""
    meta: dict[str, Any] = {
        "opf_schema": "0.2",
        "id": ed["id"],
    }
    if aliases:
        meta["aliases"] = list(aliases)
    if tracks:
        meta["tracks"] = copy.deepcopy(tracks)
    return meta
