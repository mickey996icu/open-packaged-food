"""Unit and integration tests for OPF v0.3 statutory nutrition exemptions, core.special_indicators, and quality_grade."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from opf.audit import audit_edition_doc
from opf.builder import build_compact_doc, build_static_api
from opf.ids import product_dir_for_id
from opf.ingredients import parse_ingredients_semantic
from opf.normalize import derive_editions_lifecycle, normalize_edition
from opf.validator import (
    load_json_schema,
    validate_against_json_schema,
    validate_edition_doc,
)


def _make_exempt_water_edition(
    *,
    pid: str = "gtin:00000000000109",
    edition_id: str = "01J8Z000000000000000000501",
    track: str = "CN/default",
    calcium_min: str = "400",
    metasilicic_min: str = "180",
    ph_val: str = "7.3",
    ph_tol: str = "0.5",
    legal_basis: str | None = "GB 28050-2011 第7条",
    note: str | None = None,
    ing_text: str = "水（天然水）",
    plant_license: str = "SC10644160200149",
    plant_addr: str = "广东省河源市源城区站前路108号",
) -> dict[str, Any]:
    exemption: dict[str, Any] = {"category": "packaged_water"}
    if legal_basis:
        exemption["legal_basis"] = legal_basis
    if note:
        exemption["note"] = note

    doc: dict[str, Any] = {
        "opf_schema": "0.3",
        "id": pid,
        "edition_id": edition_id,
        "rev": 1,
        "track": track,
        "supersedes": [],
        "core": {
            "regulatory_profile": "CN/GB28050-2011",
            "net_content": [{"value": "550", "unit": "ml"}],
            "nutrition_declared": None,
            "nutrition_exemption": exemption,
            "ingredients_tree": [
                {
                    "lang": "zh-Hans",
                    "nodes": parse_ingredients_semantic(ing_text, lang="zh-Hans", profile_id="CN/GB28050-2011"),
                }
            ],
            "special_indicators": [
                {"name": "钙", "qualifier": ">=", "value": calcium_min, "unit": "μg/100ml"},
                {"name": "镁", "qualifier": ">=", "value": "50", "unit": "μg/100ml"},
                {"name": "钾", "qualifier": ">=", "value": "35", "unit": "μg/100ml"},
                {"name": "钠", "qualifier": ">=", "value": "80", "unit": "μg/100ml"},
                {"name": "偏硅酸", "qualifier": ">=", "value": metasilicic_min, "unit": "μg/100ml"},
                {"name": "pH值(25℃)", "value": ph_val, "tolerance": ph_tol},
            ],
        },
        "attributes": {
            "product_name": [{"lang": "zh-Hans", "text": "饮用天然水"}],
            "brand": "示例山泉",
            "declared_category": "饮用天然水",
            "ingredients_text": [{"lang": "zh-Hans", "text": ing_text}],
            "product_standard": ["Q/NFS 0001S"],
            "shelf_life": {"value": "24", "unit": "month"},
            "parties": [
                {
                    "role": "manufacturer",
                    "name": "示例山泉万绿湖厂",
                    "address": plant_addr,
                    "license": plant_license,
                }
            ],
        },
        "evidence": [
            {
                "evidence_id": f"sha256:{'a' * 64}",
                "type": "label_photo",
                "provenance": "external_contributor",
                "region": "full_back_label",
                "cropped_sha256": "a" * 64,
                "media_ref": f"opf-media://sha256/{'a' * 64}",
                "contributor": "github:tester-a",
                "reported_at": "2026-10-01",
                "vintage_month": "2026-09",
            }
        ],
        "revisions": [
            {
                "rev": 1,
                "kind": "initial",
                "created_at": "2026-10-01T00:00:00Z",
                "author": "github:tester-a",
                "provenance": "external_contributor",
                "evidence_refs": [f"sha256:{'a' * 64}"],
                "patch": [],
            }
        ],
    }
    normalize_edition(doc)
    return doc


def _make_exempt_tea_edition(
    *,
    pid: str = "gtin:00000000000116",
    edition_id: str = "01J8Z000000000000000000601",
    quality_grade: str = "特级",
    ing_text: str = "茶叶",
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "opf_schema": "0.3",
        "id": pid,
        "edition_id": edition_id,
        "rev": 1,
        "track": "CN/default",
        "supersedes": [],
        "core": {
            "regulatory_profile": "CN/GB28050-2011",
            "net_content": [{"value": "100", "unit": "g"}],
            "nutrition_declared": None,
            "nutrition_exemption": {
                "category": "tea_coffee_herbs",
                "legal_basis": "GB 28050-2011 第7条",
            },
            "ingredients_tree": [
                {
                    "lang": "zh-Hans",
                    "nodes": parse_ingredients_semantic(ing_text, lang="zh-Hans", profile_id="CN/GB28050-2011"),
                }
            ],
        },
        "attributes": {
            "product_name": [{"lang": "zh-Hans", "text": "花香高山乌龙茶"}],
            "brand": "示例茶庄",
            "quality_grade": quality_grade,
            "ingredients_text": [{"lang": "zh-Hans", "text": ing_text}],
            "product_standard": ["Q/ZPHD0001S"],
            "shelf_life": {"value": "36", "unit": "month"},
            "parties": [
                {
                    "role": "manufacturer",
                    "name": "福建示例农场有限公司",
                    "address": "福建省龙岩市漳平市永福镇李庄村1号",
                    "license": "SC11435088100235",
                }
            ],
        },
        "evidence": [
            {
                "evidence_id": f"sha256:{'b' * 64}",
                "type": "label_photo",
                "provenance": "external_contributor",
                "region": "full_back_label",
                "cropped_sha256": "b" * 64,
                "media_ref": f"opf-media://sha256/{'b' * 64}",
                "contributor": "github:tester-b",
                "reported_at": "2026-10-02",
                "vintage_month": "2026-02",
            }
        ],
        "revisions": [
            {
                "rev": 1,
                "kind": "initial",
                "created_at": "2026-10-02T00:00:00Z",
                "author": "github:tester-b",
                "provenance": "external_contributor",
                "evidence_refs": [f"sha256:{'b' * 64}"],
                "patch": [],
            }
        ],
    }
    normalize_edition(doc)
    return doc


class TestV03ExemptionAndSpecialIndicators(unittest.TestCase):
    def test_schema_mutex_and_special_indicator_validation(self) -> None:
        water = _make_exempt_water_edition()
        self.assertEqual(validate_edition_doc(water), [])

        # Range indicator with value_max >= value passes
        with_range = copy.deepcopy(water)
        with_range["core"]["special_indicators"].append(
            {"name": "总硬度", "value": "25.0", "value_max": "80.00", "unit": "mg/L"}
        )
        normalize_edition(with_range)
        self.assertEqual(with_range["core"]["special_indicators"][-1]["value"], "25")
        self.assertEqual(with_range["core"]["special_indicators"][-1]["value_max"], "80")
        self.assertEqual(validate_edition_doc(with_range), [])

        # 1. nutrition_declared == null without nutrition_exemption -> rejected
        missing_ex = copy.deepcopy(water)
        missing_ex["core"].pop("nutrition_exemption")
        self.assertNotEqual(validate_edition_doc(missing_ex), [])

        # 2. nutrition_declared non-null with nutrition_exemption -> rejected
        both_present = copy.deepcopy(water)
        both_present["core"]["nutrition_declared"] = {
            "basis": {"value": "100", "unit": "ml"},
            "rows": [
                {"nutrient": "energy", "value": "0", "unit": "kJ"},
                {"nutrient": "protein", "value": "0", "unit": "g"},
                {"nutrient": "fat_total", "value": "0", "unit": "g"},
                {"nutrient": "carbs_available", "value": "0", "unit": "g"},
                {"nutrient": "sodium", "value": "0", "unit": "mg"},
            ],
        }
        self.assertNotEqual(validate_edition_doc(both_present), [])

        # 3. SpecialIndicator mutex violations & invalid bounds -> rejected
        for bad_ind in (
            {"name": "pH", "qualifier": ">=", "value": "7.3", "tolerance": "0.5"},
            {"name": "pH", "value": "7", "value_max": "8", "tolerance": "0.5"},
            {"name": "钙", "qualifier": ">=", "value": "100", "value_max": "200", "unit": "ug/100ml"},
            {"name": "钙", "value": "300", "value_max": "200", "unit": "ug/100ml"},
            {"name": "pH", "value": "7.3", "tolerance": "0"},
        ):
            bad_doc = copy.deepcopy(water)
            bad_doc["core"]["special_indicators"] = [bad_ind]
            self.assertNotEqual(validate_edition_doc(bad_doc), [], f"Expected failure for {bad_ind}")

    def test_natural_water_multi_source_fingerprint_divergent_and_uniform(self) -> None:
        w1 = _make_exempt_water_edition(
            edition_id="01J8Z000000000000000000501",
            track="CN/plant:SC10644160200149",
            legal_basis="GB 28050-2011 第7条",
        )
        self.assertEqual(w1["normalized"]["basis"], "100ml")
        self.assertEqual(w1["normalized"]["nutrients"], {})
        self.assertNotIn("per_unit", w1["normalized"])
        self.assertEqual(w1["quality_flags"][0]["code"], "NUTRITION_LABEL_EXEMPT")

        # Changing free-text legal_basis/note or reordering special_indicators preserves core_fingerprint
        w1_reordered = _make_exempt_water_edition(
            edition_id="01J8Z000000000000000000502",
            track="CN/plant:SC10644169700012",
            legal_basis="GB 28050 §7 statutory exemption",
            note="万绿湖同水源二厂",
            plant_license="SC10644169700012",
            plant_addr="广东省河源市高新区兴工大道1号",
        )
        w1_reordered["core"]["special_indicators"] = list(reversed(w1_reordered["core"]["special_indicators"]))
        normalize_edition(w1_reordered)
        self.assertEqual(w1["core_fingerprint"], w1_reordered["core_fingerprint"])

        product_meta = {
            "opf_schema": "0.3",
            "id": w1["id"],
            "tracks": [
                {
                    "track": "CN/plant:SC10644160200149",
                    "market": "CN",
                    "discriminator": {
                        "method": "sc_license",
                        "instructions": [{"lang": "zh-Hans", "text": "河源源城厂"}],
                    },
                },
                {
                    "track": "CN/plant:SC10644169700012",
                    "market": "CN",
                    "discriminator": {
                        "method": "sc_license",
                        "instructions": [{"lang": "zh-Hans", "text": "河源高新厂"}],
                    },
                },
            ],
        }
        compact_schema = load_json_schema("compact.v0.3.schema.json")

        # Identical mineral indicators across 2 plants -> uniform, propagating exemption & indicators
        uniform_doc = build_compact_doc(
            product_meta,
            [w1, w1_reordered],
            {},
            derive_editions_lifecycle([w1, w1_reordered]),
            "v1/gtin/000/000/00000000000109.full.json",
        )
        self.assertEqual(uniform_doc["resolution"], "uniform")
        self.assertEqual(uniform_doc["nutrition_exemption"]["category"], "packaged_water")
        self.assertEqual(len(uniform_doc["special_indicators"]), 6)
        self.assertEqual(validate_against_json_schema(uniform_doc, compact_schema), [])

        # Different water source with different mineral profile -> core_fingerprint differs -> divergent
        w2_diff_source = _make_exempt_water_edition(
            edition_id="01J8Z000000000000000000503",
            track="CN/plant:SC10644169700012",
            calcium_min="200",
            metasilicic_min="270",
            plant_license="SC10644169700012",
            plant_addr="广东省河源市高新区兴工大道1号",
        )
        self.assertNotEqual(w1["core_fingerprint"], w2_diff_source["core_fingerprint"])

        div_doc = build_compact_doc(
            product_meta,
            [w1, w2_diff_source],
            {},
            derive_editions_lifecycle([w1, w2_diff_source]),
            "v1/gtin/000/000/00000000000109.full.json",
        )
        self.assertEqual(div_doc["resolution"], "divergent")
        self.assertEqual(div_doc["common_summary"]["nutrient_ranges_not_for_logging"], {})
        self.assertIn("special_indicators", div_doc["common_summary"]["differing_fields"])
        self.assertEqual(div_doc["variants"][0]["nutrition_exemption"]["category"], "packaged_water")
        self.assertEqual(validate_against_json_schema(div_doc, compact_schema), [])

    def test_oolong_tea_quality_grade_single_and_catalog_exempt_flag(self) -> None:
        tea = _make_exempt_tea_edition(quality_grade="特级")
        self.assertEqual(tea["normalized"]["basis"], "100g")
        self.assertEqual(tea["normalized"]["nutrients"], {})
        self.assertEqual(validate_edition_doc(tea), [])

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_dir = tmp_path / "products"
            site_dir = tmp_path / "site"
            pdir = product_dir_for_id(products_dir, tea["id"])
            (pdir / "editions").mkdir(parents=True)
            (pdir / "product.json").write_text(
                json.dumps({"opf_schema": "0.3", "id": tea["id"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (pdir / "editions" / f"{tea['edition_id']}.json").write_text(
                json.dumps(tea, ensure_ascii=False),
                encoding="utf-8",
            )

            meta = build_static_api(products_dir, site_dir)
            self.assertEqual(meta["opf_schema"], "0.3")

            compact = json.loads((site_dir / "v1/gtin/000/000/00000000000116.json").read_text("utf-8"))
            self.assertEqual(compact["resolution"], "single")
            self.assertEqual(compact["quality_grade"], "特级")
            self.assertEqual(compact["nutrition_exemption"]["category"], "tea_coffee_herbs")

            cat_row = json.loads(
                (site_dir / "v1/index/catalog.jsonl").read_text("utf-8").strip()
            )
            self.assertTrue(cat_row.get("nutrition_exempt"))
            self.assertIsNone(cat_row["energy_kcal_100"])
            self.assertIsNone(cat_row["energy_kcal_num"])
            self.assertEqual(cat_row["nutrients_100"], {})

    def test_audit_exemption_anti_abuse_rules(self) -> None:
        def _codes(doc: dict[str, Any], sev: str) -> list[str]:
            return [f.code for f in audit_edition_doc(doc) if f.severity == sev]

        # Valid natural water and plain oolong tea -> 0 ERROR
        self.assertEqual(_codes(_make_exempt_water_edition(), "ERROR"), [])
        self.assertEqual(_codes(_make_exempt_tea_edition(), "ERROR"), [])

        # Flavored/sweetened water claiming packaged_water exemption -> ERROR
        bad_water = _make_exempt_water_edition(ing_text="水、白砂糖、三氯蔗糖、食用香精")
        self.assertIn("INVALID_NUTRITION_EXEMPTION", _codes(bad_water, "ERROR"))

        # Milk tea / sweetened tea claiming tea_coffee_herbs exemption -> ERROR
        bad_tea = _make_exempt_tea_edition(ing_text="乌龙茶叶、白砂糖、全脂乳粉")
        self.assertIn("INVALID_NUTRITION_EXEMPTION", _codes(bad_tea, "ERROR"))

        # Multi-ingredient food claiming single_ingredient_unprocessed -> WARN
        multi_raw = _make_exempt_tea_edition(ing_text="大米、小米、食用盐")
        multi_raw["core"]["nutrition_exemption"] = {"category": "single_ingredient_unprocessed"}
        self.assertIn("SUSPICIOUS_NUTRITION_EXEMPTION", _codes(multi_raw, "WARN"))

        # Small package area -> INFO reminder
        small_pkg = _make_exempt_tea_edition()
        small_pkg["core"]["nutrition_exemption"] = {"category": "small_package_area"}
        self.assertIn("VERIFY_EXEMPTION_EVIDENCE", _codes(small_pkg, "INFO"))

        # Exempt item simultaneously making nutrition claim ("0糖") -> WARN
        claim_water = _make_exempt_water_edition()
        claim_water["attributes"]["claims_text"] = ["0糖0脂"]
        self.assertIn("EXEMPT_WITH_NUTRITION_CLAIM", _codes(claim_water, "WARN"))


if __name__ == "__main__":
    unittest.main()
