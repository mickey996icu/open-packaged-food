"""Tests for v0.3.2 SG/SFA-FR, MY/MOH-R18B, and KR/MFDS-2024 profiles, ko/ms dictionaries, and 20-class allergens."""

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


class TestSgMyKrProfilesV032(unittest.TestCase):
    def test_sg_sfa_fr_spice_exemption_and_hpb_panel_validation(self) -> None:
        raw_en = "Ingredients: White Pepper, Garlic, Spices."
        raw_zh = "配料：白胡椒、蒜头、香料。"
        nodes_en = parse_ingredients_semantic(raw_en, lang="en", profile_id="SG/SFA-FR")
        nodes_zh = parse_ingredients_semantic(raw_zh, lang="zh-Hans", profile_id="SG/SFA-FR")
        self.assertEqual(verify_ingredients_round_trip(raw_en, nodes_en, profile_id="SG/SFA-FR"), [])
        self.assertEqual(verify_ingredients_round_trip(raw_zh, nodes_zh, profile_id="SG/SFA-FR"), [])

        for ex_cat in ("salt_vinegar_spices", "general_unclaimed_exempt"):
            core = {
                "regulatory_profile": "SG/SFA-FR",
                "net_content": [{"value": "30", "unit": "g"}],
                "nutrition_declared": None,
                "nutrition_exemption": {
                    "category": ex_cat,
                    "legal_basis": "Singapore Sale of Food Act — Food Regulations",
                },
                "ingredients_tree": [
                    {"lang": "en", "nodes": nodes_en},
                    {"lang": "zh-Hans", "nodes": nodes_zh},
                ],
                "allergens_declared": {"contains": [], "may_contain": []},
            }
            attrs = {
                "product_name": [
                    {"lang": "en", "text": "Bak Kut Teh Spice"},
                    {"lang": "zh-Hans", "text": "潮州肉骨茶香料"},
                ],
                "brand": "SONG FA",
                "ingredients_text": [
                    {"lang": "en", "text": raw_en},
                    {"lang": "zh-Hans", "text": raw_zh},
                ],
                "origin": {"country": "SG"},
            }
            sha = "b" * 64
            ev = [
                {
                    "evidence_id": f"sha256:{sha}",
                    "type": "label_photo",
                    "region": "full_back_label",
                    "cropped_sha256": sha,
                    "media_ref": f"opf-media://sha256/{sha}",
                    "contributor": "github:sg-tester",
                    "reported_at": "2026-11-26",
                    "vintage_month": "2026-10",
                }
            ]
            ed = _build_initial_edition(
                product_id="gtin:08888123456780",
                edition_id="01JTESTSGSFAFR000000000001",
                track="SG/default",
                core=core,
                attributes=attrs,
                evidence=ev,
            )
            self.assertEqual(validate_edition_doc(ed), [])
            findings = audit_edition_doc(ed)
            self.assertEqual([f for f in findings if f.severity in ("ERROR", "WARN")], [])

        # SG printed 4-core NIP should also validate and audit cleanly
        nip_ed = copy.deepcopy(ed)
        nip_ed["core"].pop("nutrition_exemption", None)
        nip_ed["core"]["nutrition_declared"] = {
            "basis": {"value": "100", "unit": "g"},
            "rows": [
                {"nutrient": "energy", "value": "315", "unit": "kcal"},
                {"nutrient": "protein", "value": "11.2", "unit": "g"},
                {"nutrient": "fat_total", "value": "3.1", "unit": "g"},
                {"nutrient": "carbs_available", "value": "60.5", "unit": "g"},
                {"nutrient": "sodium", "value": "120", "unit": "mg"},
            ],
        }
        normalize_edition(nip_ed)
        self.assertEqual(validate_edition_doc(nip_ed), [])
        self.assertEqual([f for f in audit_edition_doc(nip_ed) if f.severity == "ERROR"], [])

    def test_my_moh_r18b_bahasa_malaysia_ingredients_and_1plus5_panel(self) -> None:
        raw_ms = (
            "Ramuan: Krimer Bukan Tenusu [Sirap Glukosa, Minyak Isirung Sawit, "
            "Natrium Kaseinat (Protein Susu), Penstabil (340), Pengemulsi (471), "
            "Agen Antipengerakan (551)], Gula, Kopi Segera."
        )
        nodes_ms = parse_ingredients_semantic(raw_ms, lang="ms", profile_id="MY/MOH-R18B")
        self.assertEqual(verify_ingredients_round_trip(raw_ms, nodes_ms, profile_id="MY/MOH-R18B"), [])

        # Bahasa Malaysia allergen & exclusion precision
        self.assertIn("milk", match_allergens_in_name("Natrium Kaseinat"))
        self.assertIn("milk", match_allergens_in_name("Protein Susu"))
        self.assertNotIn("milk", match_allergens_in_name("Krimer Bukan Tenusu"))
        self.assertNotIn("milk", match_allergens_in_name("Santan Kelapa"))
        self.assertNotIn("milk", match_allergens_in_name("Mentega Koko"))
        self.assertNotIn("tree_nuts", match_allergens_in_name("Buah Pala"))
        self.assertEqual(lookup_additive_ins("Asid Sitrik"), "330")

        core = {
            "regulatory_profile": "MY/MOH-R18B",
            "net_content": [{"value": "380", "unit": "g"}],
            "serving_size": {"value": "38", "unit": "g"},
            "nutrition_declared": {
                "basis": {"value": "100", "unit": "g"},
                "rows": [
                    {"nutrient": "energy", "value": "458", "unit": "kcal"},
                    {"nutrient": "protein", "value": "4.8", "unit": "g"},
                    {"nutrient": "fat_total", "value": "15.2", "unit": "g"},
                    {"nutrient": "fat_trans", "value": "0", "unit": "g"},
                    {"nutrient": "carbs_available", "value": "75.6", "unit": "g"},
                    {"nutrient": "sugars_total", "value": "36.4", "unit": "g"},
                    {"nutrient": "sodium", "value": "135", "unit": "mg"},
                ],
            },
            "ingredients_tree": [{"lang": "ms", "nodes": nodes_ms}],
            "allergens_declared": {"contains": ["milk"], "may_contain": []},
        }
        attrs = {
            "product_name": [
                {"lang": "ms", "text": "Kopi Putih Klasik"},
                {"lang": "zh-Hans", "text": "经典白咖啡"},
            ],
            "brand": "ORIENTAL KOPI",
            "ingredients_text": [{"lang": "ms", "text": raw_ms}],
            "origin": {"country": "MY"},
        }
        sha = "c" * 64
        ev = [
            {
                "evidence_id": f"sha256:{sha}",
                "type": "label_photo",
                "region": "full_back_label",
                "cropped_sha256": sha,
                "media_ref": f"opf-media://sha256/{sha}",
                "contributor": "github:my-tester",
                "reported_at": "2026-11-26",
                "vintage_month": "2026-11",
            }
        ]
        ed = _build_initial_edition(
            product_id="gtin:09555123456780",
            edition_id="01JTESTMYR18B0000000000001",
            track="MY/default",
            core=core,
            attributes=attrs,
            evidence=ev,
        )
        self.assertEqual(validate_edition_doc(ed), [])
        self.assertEqual(ed["normalized"]["additives_ins"], ["340", "471", "551"])
        self.assertEqual(ed["normalized"]["allergens"]["inferred_from_ingredients"], ["milk"])
        self.assertEqual(ed["normalized"]["per_unit"]["unit_amount"]["value"], "38")
        findings = audit_edition_doc(ed)
        self.assertEqual([f for f in findings if f.severity in ("ERROR", "WARN")], [])

        # Missing sugars_total under MY/MOH-R18B must raise MISSING_MANDATORY_NUTRIENTS
        no_sugar = copy.deepcopy(ed)
        no_sugar["core"]["nutrition_declared"]["rows"] = [
            r for r in no_sugar["core"]["nutrition_declared"]["rows"] if r["nutrient"] != "sugars_total"
        ]
        normalize_edition(no_sugar)
        self.assertIn(
            "MISSING_MANDATORY_NUTRIENTS",
            [f.code for f in audit_edition_doc(no_sugar) if f.severity == "ERROR"],
        )

    def test_kr_mfds_2024_9_nutrients_origin_colons_and_20_allergen_classes(self) -> None:
        raw_ko = (
            "원재료명 및 함량: 소맥분(밀:미국산, 호주산), 팜유(말레이시아산), 설탕, "
            "돈골추출물[돼지고기:국산, 대두유(대두:외국산(미국, 브라질))], "
            "쇠고기맛분말, 닭고기추출물, 복숭아농축액, 토마토페이스트, 오징어분말, "
            "산도조절제(탄산수소나트륨), 향미증진제(L-글루탐산나트륨), 비타민C."
        )
        nodes_ko = parse_ingredients_semantic(raw_ko, lang="ko", profile_id="KR/MFDS-2024")
        self.assertEqual(verify_ingredients_round_trip(raw_ko, nodes_ko, profile_id="KR/MFDS-2024"), [])

        # Ensure `밀:미국산` and `대두:외국산` were NOT misparsed into functional_class
        wheat_child = nodes_ko[0]["children"][0]
        self.assertEqual(wheat_child["name"], "밀:미국산")
        self.assertNotIn("functional_class", wheat_child)
        self.assertIn("gluten_cereals", wheat_child["allergens"])

        # False-positive guards across Chinese, Korean, and English for new meat/fruit allergens
        self.assertEqual(match_allergens_in_name("核桃仁"), ["tree_nuts"])
        self.assertNotIn("peach", match_allergens_in_name("猕猴桃汁"))
        self.assertNotIn("peach", match_allergens_in_name("杨桃"))
        self.assertNotIn("beef", match_allergens_in_name("牛油果泥"))
        self.assertNotIn("beef", match_allergens_in_name("牛磺酸"))
        self.assertNotIn("beef", match_allergens_in_name("生牛乳"))
        self.assertNotIn("chicken", match_allergens_in_name("鹰嘴豆"))
        self.assertNotIn("chicken", match_allergens_in_name("chickpea flour"))
        self.assertEqual(match_allergens_in_name("메밀가루"), ["buckwheat"])
        self.assertNotIn("gluten_cereals", match_allergens_in_name("당밀"))
        self.assertEqual(match_allergens_in_name("두유"), ["soybeans"])
        self.assertEqual(match_allergens_in_name("땅콩버터"), ["peanuts"])

        core = {
            "regulatory_profile": "KR/MFDS-2024",
            "net_content": [{"value": "120", "unit": "g"}],
            "nutrition_declared": {
                "basis": {"value": "100", "unit": "g"},
                "rows": [
                    {"nutrient": "energy", "value": "425", "unit": "kcal"},
                    {"nutrient": "protein", "value": "8.8", "unit": "g", "nrv_pct": "16"},
                    {"nutrient": "fat_total", "value": "13.5", "unit": "g", "nrv_pct": "25"},
                    {"nutrient": "fat_saturated", "value": "6", "unit": "g", "nrv_pct": "40"},
                    {"nutrient": "fat_trans", "value": "0", "unit": "g"},
                    {"nutrient": "cholesterol", "value": "15", "unit": "mg", "nrv_pct": "5"},
                    {"nutrient": "carbs_total", "value": "64.8", "unit": "g", "nrv_pct": "20"},
                    {"nutrient": "sugars_total", "value": "6", "unit": "g", "nrv_pct": "6"},
                    {"nutrient": "sodium", "value": "1400", "unit": "mg", "nrv_pct": "70"},
                ],
            },
            "ingredients_tree": [{"lang": "ko", "nodes": nodes_ko}],
            "allergens_declared": {
                "contains": [
                    "beef",
                    "chicken",
                    "gluten_cereals",
                    "molluscs",
                    "peach",
                    "pork",
                    "soybeans",
                    "tomato",
                ],
                "may_contain": ["buckwheat", "eggs", "milk"],
            },
        }
        attrs = {
            "product_name": [
                {"lang": "ko", "text": "얼큰 사골 라면"},
                {"lang": "en", "text": "Spicy Bone Broth Ramyun"},
            ],
            "brand": "K-Noodle Lab",
            "ingredients_text": [{"lang": "ko", "text": raw_ko}],
            "origin": {"country": "KR"},
        }
        sha = "d" * 64
        ev = [
            {
                "evidence_id": f"sha256:{sha}",
                "type": "label_photo",
                "region": "full_back_label",
                "cropped_sha256": sha,
                "media_ref": f"opf-media://sha256/{sha}",
                "contributor": "github:kr-tester",
                "reported_at": "2026-11-26",
                "vintage_month": "2026-11",
            }
        ]
        ed = _build_initial_edition(
            product_id="gtin:08801043014809",
            edition_id="01JTESTKRMFDS0000000000001",
            track="KR/default",
            core=core,
            attributes=attrs,
            evidence=ev,
        )
        self.assertEqual(validate_edition_doc(ed), [])
        # KR MFDS 0g trans fat -> < 0.2g regulatory upper bound; NRV% matches KR daily reference (324g carbs, 54g fat, 55g protein)
        self.assertEqual(ed["normalized"]["nutrients"]["fat_trans"]["qualifier"], "<")
        self.assertEqual(ed["normalized"]["nutrients"]["fat_trans"]["value"], "0.2")
        self.assertNotIn("NRV_PCT_DECLARED_MISMATCH", [f["code"] for f in ed["quality_flags"]])
        self.assertEqual(ed["normalized"]["additives_ins"], ["300", "500(ii)", "621"])
        self.assertEqual(
            ed["normalized"]["allergens"]["inferred_from_ingredients"],
            ["beef", "chicken", "gluten_cereals", "molluscs", "peach", "pork", "soybeans", "tomato"],
        )

        findings = audit_edition_doc(ed)
        self.assertEqual([f for f in findings if f.severity in ("ERROR", "WARN")], [])

        # Omitting cholesterol under KR/MFDS-2024 must emit MISSING_MANDATORY_NUTRIENTS ERROR
        no_chol = copy.deepcopy(ed)
        no_chol["core"]["nutrition_declared"]["rows"] = [
            r for r in no_chol["core"]["nutrition_declared"]["rows"] if r["nutrient"] != "cholesterol"
        ]
        normalize_edition(no_chol)
        self.assertIn(
            "MISSING_MANDATORY_NUTRIENTS",
            [f.code for f in audit_edition_doc(no_chol) if f.severity == "ERROR"],
        )

        # Verify static build & compact schema output for KR/MFDS-2024
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "products"
            pdir = root / "gtin" / "880" / "104" / "08801043014809"
            (pdir / "editions").mkdir(parents=True)
            meta = make_product_meta_from_edition(ed)
            (pdir / "product.json").write_text(json.dumps(meta), encoding="utf-8")
            (pdir / "editions" / f"{ed['edition_id']}.json").write_text(
                json.dumps(ed, ensure_ascii=False), encoding="utf-8"
            )
            out_site = Path(tmp) / "site"
            site_meta = build_static_api(root, out_site, allow_empty=False)
            self.assertEqual(site_meta["counts_by_market"], {"KR": 1})
            lc = derive_editions_lifecycle([ed])
            compact = build_compact_doc(meta, [ed], {}, lc, "v1/gtin/880/104/08801043014809.full.json")
            self.assertEqual(compact["regulatory_profile"], "KR/MFDS-2024")


if __name__ == "__main__":
    unittest.main()
