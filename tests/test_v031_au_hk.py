"""Tests for v0.3.1 AU/FSANZ-1.2.8 & HK/CFS-132W regulatory profiles, zh-Hant dictionaries, and primary-agri SC audit."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from opf.audit import audit_edition_doc
from opf.builder import build_compact_doc, build_static_api
from opf.ingredients import parse_ingredients_semantic, verify_ingredients_round_trip
from opf.normalize import derive_editions_lifecycle, normalize_edition
from opf.registries import lookup_additive_ins, match_allergens_in_name
from opf.validator import validate_edition_doc
from tests.fixtures import _build_initial_edition, make_product_meta_from_edition


class TestAuAndHkProfilesV031(unittest.TestCase):
    def test_au_fsanz_128_normalization_peal_allergens_and_nz_track_build(self) -> None:
        raw_ing = (
            "Ingredients: Rolled Oats (62%), Lupin Flour (10%), Roast Cashews, "
            "Calamari Powder, Food Acid (330), Mineral Salts (500(ii)), Vegetable Gum (415), "
            "Emulsifier (322), Preservative (223)."
        )
        nodes = parse_ingredients_semantic(raw_ing, lang="en", profile_id="AU/FSANZ-1.2.8")
        self.assertEqual(verify_ingredients_round_trip(raw_ing, nodes, profile_id="AU/FSANZ-1.2.8"), [])

        core = {
            "regulatory_profile": "AU/FSANZ-1.2.8",
            "net_content": [{"value": "350", "unit": "g"}],
            "serving_size": {"value": "35", "unit": "g"},
            "nutrition_declared": {
                "basis": {"value": "100", "unit": "g"},
                "rows": [
                    {"nutrient": "energy", "value": "1740", "unit": "kJ", "nrv_pct": "20"},
                    {"nutrient": "protein", "value": "12.5", "unit": "g", "nrv_pct": "25"},
                    {"nutrient": "fat_total", "value": "8.4", "unit": "g", "nrv_pct": "12"},
                    {"nutrient": "fat_saturated", "qualifier": "<", "value": "1", "unit": "g"},
                    {"nutrient": "carbs_available", "value": "62", "unit": "g", "nrv_pct": "20"},
                    {"nutrient": "sugars_total", "value": "0", "unit": "g"},
                    {"nutrient": "sodium", "value": "230", "unit": "mg", "nrv_pct": "10"},
                ],
            },
            "ingredients_tree": [{"lang": "en", "nodes": nodes}],
            "allergens_declared": {
                "contains": ["gluten_cereals", "lupin", "molluscs", "sulphites", "tree_nuts"],
                "may_contain": ["milk", "peanuts"],
            },
        }
        attrs = {
            "product_name": [{"lang": "en", "text": "Aussie Lupin & Oat Bites"}],
            "brand": "Southern Cross Pantry",
            "ingredients_text": [{"lang": "en", "text": raw_ing}],
            "origin": {"country": "AU"},
        }
        ev = [
            {
                "evidence_id": "ev:01JTESTAZFSANZ000000000001",
                "type": "community_report",
                "contributor": "github:au-tester",
                "reported_at": "2026-11-20",
                "vintage_month": "2026-10",
            }
        ]
        ed = _build_initial_edition(
            product_id="gtin:09300601000012",
            edition_id="01JTESTAZFSANZ000000000001",
            track="NZ/default",
            core=core,
            attributes=attrs,
            evidence=ev,
        )
        self.assertEqual(validate_edition_doc(ed), [])

        # Verify 8700 kJ DI reference gave 0 NRV_PCT_DECLARED_MISMATCH flags (1740 / 8700 = 20%)
        flag_codes = [f["code"] for f in ed["quality_flags"]]
        self.assertNotIn("NRV_PCT_DECLARED_MISMATCH", flag_codes)
        self.assertIn("REGULATORY_ZERO_ROUNDING_ARTIFACT", flag_codes)
        self.assertEqual(ed["normalized"]["nutrients"]["sugars_total"]["qualifier"], "<")
        self.assertEqual(ed["normalized"]["nutrients"]["sugars_total"]["value"], "0.5")

        # Verify numeric INS extraction (330, 500(ii), 415, 322, 223) and PEAL allergens (incl. lupin & molluscs)
        self.assertEqual(
            ed["normalized"]["additives_ins"],
            ["223", "322", "330", "415", "500(ii)"],
        )
        for alg in ("gluten_cereals", "lupin", "molluscs", "tree_nuts"):
            self.assertIn(alg, ed["normalized"]["allergens"]["inferred_from_ingredients"])

        # Audit should report 0 ERRORs (and 0 missing mandatory nutrient errors)
        findings = audit_edition_doc(ed)
        self.assertEqual([f for f in findings if f.severity == "ERROR"], [])

        # Missing saturated fat or sugars under AU/FSANZ-1.2.8 must trigger MISSING_MANDATORY_NUTRIENTS ERROR
        bad_ed = copy.deepcopy(ed)
        bad_ed["core"]["nutrition_declared"]["rows"] = [
            r for r in bad_ed["core"]["nutrition_declared"]["rows"] if r["nutrient"] != "sugars_total"
        ]
        normalize_edition(bad_ed)
        bad_errs = [f.code for f in audit_edition_doc(bad_ed) if f.severity == "ERROR"]
        self.assertIn("MISSING_MANDATORY_NUTRIENTS", bad_errs)

        # Static API build check with NZ/default track + AU/FSANZ-1.2.8 profile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "products"
            pdir = root / "gtin" / "930" / "060" / "09300601000012"
            (pdir / "editions").mkdir(parents=True)
            meta = make_product_meta_from_edition(ed)
            (pdir / "product.json").write_text(json.dumps(meta), encoding="utf-8")
            (pdir / "editions" / f"{ed['edition_id']}.json").write_text(
                json.dumps(ed, ensure_ascii=False), encoding="utf-8"
            )
            out_site = Path(tmp) / "site"
            site_meta = build_static_api(root, out_site, allow_empty=False)
            self.assertEqual(site_meta["counts_by_market"], {"NZ": 1})

    def test_hk_cfs_132w_1plus7_traditional_chinese_and_carbs_dual_mode(self) -> None:
        raw_ing_hant = (
            "成分：小麥粉、砂糖、無水牛油、淡忌廉、雞蛋、夏威夷果仁、"
            "乳化劑（大豆卵磷脂）、膨脹劑（碳酸氫鈉）、酸度調節劑（檸檬酸）、調味劑（621）。"
        )
        nodes = parse_ingredients_semantic(raw_ing_hant, lang="zh-Hant", profile_id="HK/CFS-132W")
        self.assertEqual(
            verify_ingredients_round_trip(raw_ing_hant, nodes, profile_id="HK/CFS-132W"), []
        )

        # Verify HK-specific zh-Hant allergen & additive lookups and false-positive exclusions
        self.assertIn("milk", match_allergens_in_name("無水牛油"))
        self.assertIn("milk", match_allergens_in_name("淡忌廉"))
        self.assertNotIn("milk", match_allergens_in_name("花生牛油"))
        self.assertIn("peanuts", match_allergens_in_name("花生牛油"))
        self.assertNotIn("gluten_cereals", match_allergens_in_name("蕎麥麵"))
        self.assertIn("buckwheat", match_allergens_in_name("蕎麥麵"))
        self.assertEqual(lookup_additive_ins("醋磺內酯鉀"), "950")
        self.assertEqual(lookup_additive_ins("玉米糖膠"), "415")

        core = {
            "regulatory_profile": "HK/CFS-132W",
            "net_content": [{"value": "180", "unit": "g"}],
            "nutrition_declared": {
                "basis": {"value": "100", "unit": "g"},
                "rows": [
                    {"nutrient": "energy", "value": "512", "unit": "kcal"},
                    {"nutrient": "protein", "value": "7.1", "unit": "g"},
                    {"nutrient": "fat_total", "value": "26.5", "unit": "g"},
                    {"nutrient": "fat_saturated", "value": "15.2", "unit": "g"},
                    {"nutrient": "fat_trans", "value": "0", "unit": "g"},
                    {"nutrient": "carbs_available", "value": "61.0", "unit": "g"},
                    {"nutrient": "sugars_total", "value": "24.5", "unit": "g"},
                    {"nutrient": "sodium", "value": "210", "unit": "mg"},
                ],
            },
            "ingredients_tree": [{"lang": "zh-Hant", "nodes": nodes}],
            "allergens_declared": {
                "contains": ["eggs", "gluten_cereals", "milk", "soybeans", "tree_nuts"],
                "may_contain": [],
            },
        }
        attrs = {
            "product_name": [
                {"lang": "zh-Hant", "text": "夏威夷果仁牛油曲奇"},
                {"lang": "en", "text": "Macadamia Butter Cookies"},
            ],
            "brand": "港式烘焙示例",
            "ingredients_text": [{"lang": "zh-Hant", "text": raw_ing_hant}],
            "origin": {"country": "HK"},
        }
        ev = [
            {
                "evidence_id": "ev:01JTESTHKCFS00000000000001",
                "type": "community_report",
                "contributor": "github:hk-tester",
                "reported_at": "2026-11-22",
                "vintage_month": "2026-11",
            }
        ]
        ed = _build_initial_edition(
            product_id="gtin:04891234567898",
            edition_id="01JTESTHKCFS00000000000001",
            track="HK/default",
            core=core,
            attributes=attrs,
            evidence=ev,
        )
        self.assertEqual(validate_edition_doc(ed), [])
        self.assertEqual(ed["normalized"]["nutrients"]["fat_trans"]["qualifier"], "<")
        self.assertEqual(ed["normalized"]["nutrients"]["fat_trans"]["value"], "0.3")
        self.assertEqual(
            ed["normalized"]["additives_ins"],
            ["322", "330", "500(ii)", "621"],
        )

        # Audit check: 0 ERRORs, 0 unmatched allergen warnings, 0 high-sugar false warnings
        findings = audit_edition_doc(ed)
        self.assertEqual([f for f in findings if f.severity == "ERROR"], [])
        warn_codes = {f.code for f in findings if f.severity == "WARN"}
        self.assertNotIn("DECLARED_ALLERGEN_UNMATCHED_IN_INGREDIENTS", warn_codes)
        self.assertNotIn("HIGH_SUGAR_NO_SUGAR_SOURCE", warn_codes)

        # HK Cap. 132W requires fat_trans unconditionally: omitting fat_trans must emit ERROR
        no_trans = copy.deepcopy(ed)
        no_trans["core"]["nutrition_declared"]["rows"] = [
            r for r in no_trans["core"]["nutrition_declared"]["rows"] if r["nutrient"] != "fat_trans"
        ]
        normalize_edition(no_trans)
        self.assertIn(
            "MISSING_MANDATORY_NUTRIENTS",
            [f.code for f in audit_edition_doc(no_trans) if f.severity == "ERROR"],
        )

        # HK Cap. 132W also accepts carbs_total in place of carbs_available when label states "Total Carbohydrates"
        total_carb_ed = copy.deepcopy(ed)
        for r in total_carb_ed["core"]["nutrition_declared"]["rows"]:
            if r["nutrient"] == "carbs_available":
                r["nutrient"] = "carbs_total"
        normalize_edition(total_carb_ed)
        self.assertEqual(validate_edition_doc(total_carb_ed), [])
        self.assertEqual([f for f in audit_edition_doc(total_carb_ed) if f.severity == "ERROR"], [])

        # Compact schema check for HK/CFS-132W
        lc = derive_editions_lifecycle([ed])
        compact = build_compact_doc(
            make_product_meta_from_edition(ed),
            [ed],
            {},
            lc,
            "v1/gtin/489/123/04891234567898.full.json",
        )
        self.assertEqual(compact["regulatory_profile"], "HK/CFS-132W")

    def test_primary_agricultural_egg_downgrades_missing_sc_from_warn_to_info(self) -> None:
        raw_ing = "鲜鸡蛋"
        nodes = parse_ingredients_semantic(raw_ing, lang="zh-Hans", profile_id="CN/GB28050-2011")
        core = {
            "regulatory_profile": "CN/GB28050-2011",
            "net_content": [{"value": "1.59", "unit": "kg"}],
            "nutrition_declared": None,
            "nutrition_exemption": {
                "category": "single_ingredient_unprocessed",
                "legal_basis": "GB 28050-2011 §7",
            },
            "ingredients_tree": [{"lang": "zh-Hans", "nodes": nodes}],
            "allergens_declared": {"contains": ["eggs"], "may_contain": []},
        }
        attrs = {
            "product_name": [{"lang": "zh-Hans", "text": "安心保洁蛋"}],
            "brand": "示例农场",
            "ingredients_text": [{"lang": "zh-Hans", "text": raw_ing}],
            "product_standard": ["GB 2749"],
            "parties": [
                {"role": "commissioner", "name": "示例禽蛋有限公司"},
                {
                    "role": "manufacturer",
                    "name": "示例生态农业发展有限公司",
                    "address": "安徽省宣城市郎溪县十字镇现代农业示范园1号",
                    "plant_code": "A",
                },
            ],
        }
        sha = "a" * 64
        ev = [
            {
                "evidence_id": f"sha256:{sha}",
                "type": "label_photo",
                "region": "full_back_label",
                "cropped_sha256": sha,
                "media_ref": f"opf-media://sha256/{sha}",
                "contributor": "github:tester",
                "reported_at": "2026-11-25",
                "vintage_month": "2026-11",
            }
        ]
        ed = _build_initial_edition(
            product_id="gtin:00000000000109",
            edition_id="01JTESTCNEGGS0000000000001",
            track="CN/default",
            core=core,
            attributes=attrs,
            evidence=ev,
        )
        findings = audit_edition_doc(ed)
        self.assertEqual([f for f in findings if f.severity in ("ERROR", "WARN")], [])
        info_codes = [f.code for f in findings if f.severity == "INFO"]
        self.assertIn("CN_AGRI_VERIFY_NO_SC", info_codes)


if __name__ == "__main__":
    unittest.main()
