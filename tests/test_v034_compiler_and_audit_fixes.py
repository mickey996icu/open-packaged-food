"""Regression tests for v0.3.4 serving-basis normalization, ingredient grammar/INS subcodes, and audit rules."""

from __future__ import annotations

import copy
import unittest

from opf.audit import audit_edition_doc
from opf.cli_submit import _prepare_candidate_from_draft
from opf.ingredients import (
    annotate_ingredients_spans,
    parse_ingredients_semantic,
    verify_ingredients_round_trip,
)
from opf.normalize import normalize_edition
from opf.registries import lookup_additive_ins
from opf.validator import validate_edition_doc
from tests.fixtures import make_cn_patty_fixture


class TestV034CompilerAndAuditFixes(unittest.TestCase):
    def test_per_serving_basis_scales_via_serving_size_for_mass_and_volume(self) -> None:
        draft_mass = {
            "id": "gtin:00810179086053",
            "core": {
                "regulatory_profile": "US/FDA-NLEA",
                "net_content": [{"value": "170", "unit": "g"}],
                "serving_size": {"value": "50", "unit": "g"},
                "nutrition_declared": {
                    "basis": {"value": "1", "unit": "serving"},
                    "rows": [
                        {"nutrient": "energy", "value": "180", "unit": "kcal"},
                        {"nutrient": "protein", "value": "0", "unit": "g"},
                        {"nutrient": "fat_total", "value": "0", "unit": "g"},
                        {"nutrient": "fat_saturated", "value": "0", "unit": "g"},
                        {"nutrient": "fat_trans", "value": "0", "unit": "g"},
                        {"nutrient": "cholesterol", "value": "0", "unit": "mg"},
                        {"nutrient": "carbs_total", "value": "45", "unit": "g"},
                        {"nutrient": "dietary_fiber", "value": "0", "unit": "g"},
                        {"nutrient": "sugars_total", "value": "30", "unit": "g"},
                        {"nutrient": "sugars_added", "value": "30", "unit": "g"},
                        {"nutrient": "sodium", "value": "25", "unit": "mg"},
                    ],
                },
            },
            "attributes": {
                "product_name": [{"lang": "en", "text": "Blue Raspberry Gummy"}],
                "brand": "Demo Candy",
                "ingredients_text": [{"lang": "en", "text": "Ingredients: Glucose syrup, sugar, water."}],
            },
            "evidence": [
                {
                    "type": "label_photo",
                    "region": "nutrition_table",
                    "cropped_sha256": "a" * 64,
                    "media_ref": f"opf-media://sha256/{'a' * 64}",
                    "contributor": "github:tester",
                    "reported_at": "2026-11-28",
                }
            ],
        }
        ed, errs = _prepare_candidate_from_draft(draft_mass, track="US/default")
        self.assertEqual(errs, [])
        ed["revisions"] = [
            {
                "rev": 1,
                "kind": "initial",
                "author": "github:tester",
                "provenance": "external_contributor",
                "created_at": "2026-11-28T00:00:00Z",
                "evidence_refs": [f"sha256:{'a' * 64}"],
                "patch": [],
            }
        ]
        self.assertEqual(validate_edition_doc(ed), [])
        self.assertEqual(ed["normalized"]["basis"], "100g")
        # 180 kcal per 50g -> 360 kcal per 100g (NOT 18000!)
        self.assertEqual(ed["normalized"]["nutrients"]["energy_kcal"]["value"], "360")
        self.assertEqual(ed["normalized"]["nutrients"]["carbs_total"]["value"], "90")
        self.assertEqual(ed["normalized"]["nutrients"]["sodium"]["value"], "50")
        # 0g trans fat per 50g serving under US FDA (<0.5g/serving) -> <1 g/100g
        self.assertEqual(ed["normalized"]["nutrients"]["fat_trans"]["qualifier"], "<")
        self.assertEqual(ed["normalized"]["nutrients"]["fat_trans"]["value"], "1")
        self.assertEqual(ed["normalized"]["per_unit"]["nutrients"]["energy_kcal"]["value"], "180")

        # Liquid serving_size (250 ml) derives normalized.basis == '100ml'
        draft_liq = copy.deepcopy(draft_mass)
        draft_liq["core"]["net_content"] = [{"value": "500", "unit": "ml"}]
        draft_liq["core"]["serving_size"] = {"value": "250", "unit": "ml"}
        ed_liq, errs_liq = _prepare_candidate_from_draft(draft_liq, track="US/default")
        self.assertEqual(errs_liq, [])
        self.assertEqual(ed_liq["normalized"]["basis"], "100ml")
        self.assertEqual(ed_liq["normalized"]["nutrients"]["energy_kcal"]["value"], "72")

        # Missing serving_size when basis.unit == 'serving' is rejected cleanly
        bad = copy.deepcopy(ed)
        bad["core"].pop("serving_size", None)
        v_errs = validate_edition_doc(bad)
        self.assertTrue(any("requires core.serving_size" in e for e in v_errs))
        with self.assertRaises(ValueError):
            normalize_edition(bad)

        # Unsupported arbitrary basis.unit (e.g. 'piece') is rejected cleanly
        bad_unit = copy.deepcopy(ed)
        bad_unit["core"]["nutrition_declared"]["basis"] = {"value": "2", "unit": "piece"}
        v_errs_u = validate_edition_doc(bad_unit)
        self.assertTrue(any("basis.unit" in e for e in v_errs_u))

    def test_roman_subcode_ins_and_colourants_functional_class(self) -> None:
        nodes = parse_ingredients_semantic(
            "Ingredients: Water, Colourants (INS 160b(ii)), Emulsifiers (INS 481(i), INS 472c(ii)), Stabiliser (INS 340(ii)).",
            lang="en",
            profile_id="MY/MOH-R18B",
        )
        colour_node = nodes[1]
        self.assertEqual(colour_node["name"], "Colourants")
        self.assertTrue(colour_node.get("is_additive"))
        self.assertEqual(len(colour_node["children"]), 1)
        self.assertEqual(colour_node["children"][0]["name"], "INS 160b(ii)")
        self.assertEqual(colour_node["children"][0]["ins"], "160b(ii)")
        self.assertNotIn("children", colour_node["children"][0])

        emul_children = nodes[2]["children"]
        self.assertEqual(emul_children[0]["name"], "INS 481(i)")
        self.assertEqual(emul_children[0]["ins"], "481(i)")
        self.assertNotIn("children", emul_children[0])
        # Even an unregistered base code with Roman suffix stays atomic without garbage 'ii' child
        self.assertEqual(emul_children[1]["name"], "INS 472c(ii)")
        self.assertTrue(emul_children[1].get("is_additive"))
        self.assertNotIn("children", emul_children[1])

        stab_child = nodes[3]["children"][0]
        self.assertEqual(stab_child["ins"], "340(ii)")

        # Parent fallback in lookup_additive_ins preserves canonical Roman subdivision
        self.assertEqual(lookup_additive_ins("INS 471 (ii)"), "471(ii)")

    def test_interval_qualifiers_han_prefix_and_multi_bracket_qualifiers(self) -> None:
        raw = "配料：饮用水(20%-25%)、食用盐(18%~22%)、含焦糖色、含5'-呈味核苷酸二钠、含水柠檬酸、含气饮用水。"
        nodes = parse_ingredients_semantic(raw, lang="zh-Hans", profile_id="CN/GB28050-2025")
        self.assertEqual(verify_ingredients_round_trip(raw, nodes, profile_id="CN/GB28050-2025"), [])

        self.assertEqual(nodes[0]["name"], "饮用水")
        self.assertEqual(nodes[0]["qualifier"], "20%-25%")
        self.assertNotIn("children", nodes[0])

        self.assertEqual(nodes[1]["name"], "食用盐")
        self.assertEqual(nodes[1]["qualifier"], "18%~22%")
        self.assertNotIn("children", nodes[1])

        self.assertEqual(nodes[2]["functional_class"], "含")
        self.assertEqual(nodes[2]["name"], "焦糖色")
        self.assertEqual(nodes[2]["ins"], "150a")

        self.assertEqual(nodes[3]["functional_class"], "含")
        self.assertEqual(nodes[3]["name"], "5'-呈味核苷酸二钠")
        self.assertEqual(nodes[3]["ins"], "635")

        # '含水柠檬酸' and '含气饮用水' must NOT have '含' stripped off
        self.assertNotIn("functional_class", nodes[4])
        self.assertEqual(nodes[4]["name"], "含水柠檬酸")
        self.assertEqual(nodes[4]["ins"], "330")
        self.assertNotIn("functional_class", nodes[5])
        self.assertEqual(nodes[5]["name"], "含气饮用水")

        # Multi-bracket semantic qualifier joined with '；' aligns cleanly without ')( ' hacks
        plum_raw = "配料：李梅(嫁接)(添加量≥60%)、白砂糖。"
        plum_tree = [
            {"name": "李梅", "qualifier": "嫁接；添加量≥60%"},
            {"name": "白砂糖"},
        ]
        self.assertEqual(verify_ingredients_round_trip(plum_raw, plum_tree), [])
        spanned = annotate_ingredients_spans(plum_raw, plum_tree)
        self.assertEqual(spanned[0]["qualifier_span"], [6, 17])

    def test_multilingual_structural_connectors_and_malay_clauses(self) -> None:
        my_raw = (
            "Ramuan: Air, Gula, Mengandungi Pengawal Asid (INS 330) dan Perisa Yang Dibenarkan, "
            "Pengemulsi (INS 471) Sebagai Kondisioner Makanan Yang Dibenarkan."
        )
        auto_nodes = parse_ingredients_semantic(my_raw, lang="ms", profile_id="MY/MOH-R18B")
        self.assertEqual(verify_ingredients_round_trip(my_raw, auto_nodes, profile_id="MY/MOH-R18B"), [])
        names = [n["name"] for n in auto_nodes]
        self.assertEqual(names, ["Air", "Gula", "Pengawal Asid", "Perisa", "Pengemulsi"])
        self.assertTrue(auto_nodes[3].get("is_additive"))

        # Clean manual AST over English 'and' / 'Contains 2% or less of:' passes round-trip
        en_raw = "Ingredients: Wheat Flour, Sugar, Contains 2% or less of: Salt and Natural Flavors."
        en_tree = [
            {"name": "Wheat Flour"},
            {"name": "Sugar"},
            {"name": "Salt"},
            {"name": "Natural Flavors"},
        ]
        self.assertEqual(verify_ingredients_round_trip(en_raw, en_tree, profile_id="US/FDA-NLEA"), [])

        # Dropping an actual ingredient word ('Salt') must STILL fail round-trip verification
        incomplete_tree = [{"name": "Wheat Flour"}, {"name": "Sugar"}, {"name": "Natural Flavors"}]
        self.assertNotEqual(
            verify_ingredients_round_trip(en_raw, incomplete_tree, profile_id="US/FDA-NLEA"), []
        )

    def test_expanded_additive_dictionary_and_regional_no_ins_whitelist(self) -> None:
        expected_pairs = {
            "甜蜜素": "952",
            "糖精钠": "954",
            "乙基麦芽酚": "637",
            "双乙酸钠": "262(ii)",
            "胭脂虫红": "120",
            "E 124": "124",
            "E 1422": "1422",
            "E 1442": "1442",
            "INS 160b(ii)": "160b(ii)",
            "carnauba wax": "903",
        }
        for raw_term, expected_ins in expected_pairs.items():
            self.assertEqual(lookup_additive_ins(raw_term), expected_ins, msg=raw_term)

        # 红曲红 (no Codex INS) should not trigger UNMAPPED_ADDITIVE_CANDIDATES noise
        ed = make_cn_patty_fixture()
        ed["attributes"]["ingredients_text"] = [
            {"lang": "zh-Hans", "text": "配料：猪肉、水、食品添加剂（红曲红、双乙酸钠）。"}
        ]
        ed["core"]["ingredients_tree"] = [
            {
                "lang": "zh-Hans",
                "nodes": parse_ingredients_semantic(
                    "配料：猪肉、水、食品添加剂（红曲红、双乙酸钠）。",
                    lang="zh-Hans",
                    profile_id="CN/GB28050-2011",
                ),
            }
        ]
        normalize_edition(ed)
        codes = [f.code for f in audit_edition_doc(ed)]
        self.assertNotIn("UNMAPPED_ADDITIVE_CANDIDATES", codes)
        self.assertIn("262(ii)", ed["normalized"]["additives_ins"])

    def test_audit_sugar_sources_allergen_statement_and_foreign_license_checks(self) -> None:
        # 1. Pomegranate concentrate浆 & freeze-dried pineapple should NOT warn HIGH_SUGAR_NO_SUGAR_SOURCE
        ed = make_cn_patty_fixture()
        ed["core"]["regulatory_profile"] = "CN/GB28050-2025"
        ed["core"]["nutrition_declared"]["rows"] = [
            {"nutrient": "energy", "value": "280", "unit": "kJ", "nrv_pct": "3"},
            {"nutrient": "protein", "value": "0.5", "unit": "g", "nrv_pct": "1"},
            {"nutrient": "fat_total", "value": "0", "unit": "g", "nrv_pct": "0"},
            {"nutrient": "fat_saturated", "value": "0", "unit": "g", "nrv_pct": "0"},
            {"nutrient": "carbs_available", "value": "15", "unit": "g", "nrv_pct": "5"},
            {"nutrient": "sugars_total", "value": "12.5", "unit": "g"},
            {"nutrient": "sodium", "value": "10", "unit": "mg", "nrv_pct": "1"},
        ]
        ed["attributes"]["ingredients_text"] = [{"lang": "zh-Hans", "text": "配料：水、浓缩石榴浆。"}]
        ed["core"]["ingredients_tree"] = [
            {"lang": "zh-Hans", "nodes": [{"name": "水"}, {"name": "浓缩石榴浆"}]}
        ]
        ed["core"]["allergens_declared"] = {"contains": [], "may_contain": []}
        normalize_edition(ed)
        warn_codes = [f.code for f in audit_edition_doc(ed) if f.severity == "WARN"]
        self.assertNotIn("HIGH_SUGAR_NO_SUGAR_SOURCE", warn_codes)

        # 2. Brewed soy sauce + explicit allergens_raw_text -> INFO (not WARN), while precautionary-only -> WARN
        ed_soy = copy.deepcopy(ed)
        ed_soy["attributes"]["ingredients_text"] = [{"lang": "zh-Hans", "text": "配料：水、酿造酱油、白砂糖。"}]
        ed_soy["core"]["ingredients_tree"] = [
            {"lang": "zh-Hans", "nodes": [{"name": "水"}, {"name": "酿造酱油"}, {"name": "白砂糖"}]}
        ]
        ed_soy["attributes"]["allergens_raw_text"] = (
            "致敏物质提示：本产品含有大豆、小麦成分，此生产线也加工含蛋制品。"
        )
        ed_soy["core"]["allergens_declared"] = {
            "contains": ["gluten_cereals", "soybeans"],
            "may_contain": ["eggs"],
        }
        normalize_edition(ed_soy)
        soy_findings = audit_edition_doc(ed_soy)
        self.assertNotIn(
            "DECLARED_ALLERGEN_UNMATCHED_IN_INGREDIENTS",
            [f.code for f in soy_findings if f.severity == "WARN"],
        )
        self.assertIn(
            "DECLARED_ALLERGEN_VIA_STATEMENT_OR_COMPOUND",
            [f.code for f in soy_findings if f.severity == "INFO"],
        )

        # Misclassifying 'eggs' from precautionary clause into 'contains' MUST still trigger WARN
        ed_bad_alg = copy.deepcopy(ed_soy)
        ed_bad_alg["core"]["allergens_declared"]["contains"] = ["eggs", "gluten_cereals", "soybeans"]
        normalize_edition(ed_bad_alg)
        self.assertIn(
            "DECLARED_ALLERGEN_UNMATCHED_IN_INGREDIENTS",
            [f.code for f in audit_edition_doc(ed_bad_alg) if f.severity == "WARN"],
        )

        # 3. Malaysian SSM company registration number in parties[].license emits WARN
        ed_my = copy.deepcopy(ed)
        ed_my["core"]["regulatory_profile"] = "MY/MOH-R18B"
        ed_my["track"] = "MY/default"
        ed_my["attributes"]["origin"] = {"country": "MY"}
        ed_my["attributes"]["parties"] = [
            {"role": "manufacturer", "name": "Demo Food Sdn. Bhd.", "license": "1415058-W"}
        ]
        my_warns = [f.code for f in audit_edition_doc(ed_my) if f.severity == "WARN"]
        self.assertIn("COMPANY_REG_IN_FOOD_LICENSE", my_warns)

        # Legitimate foreign food report number emits INFO for human verification rather than WARN
        ed_kr = copy.deepcopy(ed_my)
        ed_kr["core"]["regulatory_profile"] = "KR/MFDS-2024"
        ed_kr["track"] = "KR/default"
        ed_kr["attributes"]["origin"] = {"country": "KR"}
        ed_kr["attributes"]["parties"] = [
            {"role": "manufacturer", "name": "Demo Korea Co.", "license": "19920415001-12"}
        ]
        kr_findings = audit_edition_doc(ed_kr)
        self.assertNotIn("COMPANY_REG_IN_FOOD_LICENSE", [f.code for f in kr_findings])
        self.assertIn("VERIFY_FOREIGN_LICENSE_SEMANTICS", [f.code for f in kr_findings if f.severity == "INFO"])


if __name__ == "__main__":
    unittest.main()
