"""Comprehensive v0.2 unit and integration domain tests for OpenPackagedFood (opf)."""

from __future__ import annotations

import copy
import hashlib
import json
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from opf.builder import build_compact_doc, build_static_api
from opf.cli import main as cli_main
from opf.ids import (
    compute_gs1_check_digit,
    edition_json_path,
    is_restricted_instore_gtin,
    normalize_gtin_to_14,
    product_json_path,
    validate_product_id,
)
from opf.ingredients import (
    parse_ingredients_semantic,
    parse_ingredients_text,
    verify_ingredients_round_trip,
)
from opf.media import resolve_media_ref, sanitize_and_hash_image, sanitize_image_bytes
from opf.normalize import (
    compute_label_fingerprint,
    derive_editions_lifecycle,
    derive_evidence_level,
    normalize_edition,
)
from opf.registries import lookup_additive_ins, match_allergens_in_name
from opf.validator import (
    load_json_schema,
    validate_against_json_schema,
    validate_edition_doc,
    validate_product_dir,
)
from tests.fixtures import (
    make_cn_patty_fixture,
    make_cn_tea_fixture,
    make_product_meta_from_edition,
    make_us_cookies_fixture,
)


def _png_chunk(ctype: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + ctype
        + payload
        + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)
    )


def _webp_chunk(fourcc: bytes, payload: bytes) -> bytes:
    pad = b"\x00" if (len(payload) & 1) else b""
    return fourcc + struct.pack("<I", len(payload)) + payload + pad


class TestIdentifiers(unittest.TestCase):
    def test_valid_gtin_check_digit(self) -> None:
        self.assertEqual(compute_gs1_check_digit("000000000010"), "9")
        self.assertEqual(normalize_gtin_to_14("0000000000109"), "00000000000109")
        self.assertEqual(validate_product_id("gtin:00000000000109"), [])

    def test_invalid_gtin_check_digit_rejected(self) -> None:
        errs = validate_product_id("gtin:00000000000100")
        self.assertTrue(any("check digit" in e for e in errs))

    def test_restricted_instore_barcodes_020_to_029_and_200_to_299_rejected(self) -> None:
        for prefix in ("020", "021", "029", "200", "250", "299"):
            body = f"0{prefix}000000000"
            chk = compute_gs1_check_digit(body)
            gtin14 = body + chk
            self.assertTrue(
                is_restricted_instore_gtin(gtin14),
                f"Expected prefix {prefix} in {gtin14} to be flagged restricted",
            )
            errs = validate_product_id(f"gtin:{gtin14}")
            self.assertTrue(
                any("Restricted in-store" in e for e in errs),
                f"Expected validate_product_id to reject {gtin14}",
            )

    def test_valid_and_invalid_opf_ids(self) -> None:
        self.assertEqual(
            validate_product_id("opf:demo-deli/black-pepper-patty/80g"), []
        )
        self.assertNotEqual(validate_product_id("opf:InvalidUpper/item/80g"), [])
        self.assertNotEqual(validate_product_id("opf:only-two-segments/80g"), [])


class TestIngredientsRoundTrip(unittest.TestCase):
    def test_cn_nested_and_qualifier_round_trip(self) -> None:
        raw = "水、茉莉花茶（绿茶茶坯）（≥4g/L）、维生素C、碳酸氢钠"
        nodes = parse_ingredients_semantic(raw, lang="zh-Hans", profile_id="CN/GB28050-2011")
        self.assertEqual(len(nodes), 4)
        self.assertEqual(nodes[1]["name"], "茉莉花茶")
        self.assertEqual(nodes[1]["qualifier"], "≥4g/L")
        self.assertEqual(nodes[1]["children"][0]["name"], "绿茶茶坯")
        self.assertEqual(nodes[2]["ins"], "300")
        self.assertEqual(nodes[3]["ins"], "500(ii)")
        self.assertEqual(
            verify_ingredients_round_trip(raw, nodes, profile_id="CN/GB28050-2011"), []
        )

    def test_cn_inline_percentage_round_trip(self) -> None:
        raw = "配料表：牛肉≥95%，食用盐≤3%，黑胡椒碎。"
        nodes = parse_ingredients_semantic(raw, lang="zh-Hans", profile_id="CN/GB28050-2011")
        self.assertEqual(nodes[0]["name"], "牛肉")
        self.assertEqual(nodes[0]["qualifier"], "≥95%")
        self.assertEqual(nodes[1]["name"], "食用盐")
        self.assertEqual(nodes[1]["qualifier"], "≤3%")
        self.assertEqual(
            verify_ingredients_round_trip(raw, nodes, profile_id="CN/GB28050-2011"), []
        )

    def test_cn_addition_prefix_and_qizhong_clause(self) -> None:
        raw = "水、浓缩苹果汁（添加量不少于10%）、植物油（其中棕榈油≥50%）、牛肉含量≥30%"
        nodes = parse_ingredients_semantic(raw, lang="zh-Hans", profile_id="CN/GB28050-2011")
        self.assertEqual(nodes[1]["name"], "浓缩苹果汁")
        self.assertEqual(nodes[1]["qualifier"], "添加量不少于10%")
        self.assertEqual(nodes[2]["name"], "植物油")
        self.assertEqual(nodes[2]["children"][0]["functional_class"], "其中")
        self.assertEqual(nodes[2]["children"][0]["name"], "棕榈油")
        self.assertEqual(nodes[2]["children"][0]["qualifier"], "≥50%")
        self.assertEqual(nodes[3]["name"], "牛肉")
        self.assertEqual(nodes[3]["qualifier"], "含量≥30%")
        self.assertEqual(
            verify_ingredients_round_trip(raw, nodes, profile_id="CN/GB28050-2011"), []
        )

    def test_eu_functional_class_and_multi_brackets(self) -> None:
        raw = "Ingredients: Wheat flour, Sugar, Emulsifier: Soy lecithin (E322), Raising agent (E500(ii))."
        nodes = parse_ingredients_semantic(raw, lang="en", profile_id="EU/1169-2011")
        self.assertEqual(nodes[2]["functional_class"], "Emulsifier")
        self.assertEqual(nodes[2]["name"], "Soy lecithin")
        self.assertEqual(nodes[2]["ins"], "322")
        self.assertEqual(nodes[2]["children"][0]["ins"], "322")
        self.assertTrue(nodes[3]["is_additive"])
        self.assertEqual(nodes[3]["children"][0]["ins"], "500(ii)")
        self.assertEqual(
            verify_ingredients_round_trip(raw, nodes, profile_id="EU/1169-2011"), []
        )

        # Multi-bracket nesting
        cn_multi = "小麦粉、复合调味料【白砂糖、酱油（水、大豆、小麦）、谷氨酸钠】"
        cn_nodes = parse_ingredients_semantic(cn_multi, lang="zh-Hans", profile_id="CN/GB28050-2011")
        self.assertEqual(cn_nodes[1]["children"][1]["name"], "酱油")
        self.assertEqual(cn_nodes[1]["children"][1]["children"][1]["name"], "大豆")
        self.assertEqual(cn_nodes[1]["children"][2]["ins"], "621")
        self.assertEqual(
            verify_ingredients_round_trip(cn_multi, cn_nodes, profile_id="CN/GB28050-2011"), []
        )

    def test_jp_slash_additive_rule(self) -> None:
        raw = "原材料名：緑茶（国産）、ジャスミン茶／ビタミンC、炭酸水素Na"
        nodes = parse_ingredients_semantic(raw, lang="ja", profile_id="JP/CAA-2015")
        self.assertEqual(len(nodes), 4)
        self.assertFalse(nodes[0].get("is_additive", False))
        self.assertFalse(nodes[1].get("is_additive", False))
        self.assertTrue(nodes[2].get("is_additive", False))
        self.assertEqual(nodes[2]["ins"], "300")
        self.assertTrue(nodes[3].get("is_additive", False))
        self.assertEqual(nodes[3]["ins"], "500(ii)")
        self.assertEqual(
            verify_ingredients_round_trip(raw, nodes, profile_id="JP/CAA-2015"), []
        )

    def test_round_trip_detects_dropped_ingredient(self) -> None:
        raw = "水、白砂糖、柠檬酸"
        nodes = parse_ingredients_text(raw, lang="zh-Hans", profile_id="CN/GB28050-2011")
        corrupted = [nodes[0], nodes[2]]
        errs = verify_ingredients_round_trip(raw, corrupted, profile_id="CN/GB28050-2011")
        self.assertTrue(any("uncaptured text" in e and "白砂糖" in e for e in errs))


class TestAllergensAndAdditives(unittest.TestCase):
    def test_allergen_false_positives_excluded(self) -> None:
        # Should NOT match 'gluten_cereals'
        for term in ("荞麦", "苦荞", "甜荞", "麦芽糊精", "麦芽糖醇", "buckwheat", "maltodextrin"):
            self.assertNotIn(
                "gluten_cereals",
                match_allergens_in_name(term),
                f"False positive gluten_cereals on {term!r}",
            )
        self.assertIn("buckwheat", match_allergens_in_name("荞麦"))
        self.assertIn("gluten_cereals", match_allergens_in_name("小麦粉"))

        # Should NOT match 'eggs'
        for term in ("蛋白质", "植物蛋白", "豌豆蛋白", "胶原蛋白", "大豆蛋白", "eggplant"):
            self.assertNotIn("eggs", match_allergens_in_name(term), f"False positive eggs on {term!r}")
        self.assertEqual(match_allergens_in_name("大豆分离蛋白"), ["soybeans"])
        self.assertEqual(match_allergens_in_name("浓缩乳清蛋白"), ["milk"])

        # Should NOT match 'milk'
        for term in (
            "乳酸",
            "乳酸钠",
            "植物乳杆菌",
            "乳化剂",
            "可可脂",
            "代可可脂",
            "椰乳",
            "燕麦奶",
            "coconut milk",
            "cocoa butter",
            "lactic acid",
            "乳酸Ca",
            "乳化剤",
        ):
            self.assertNotIn("milk", match_allergens_in_name(term), f"False positive milk on {term!r}")

        # True positives still work even when combined with excluded terms
        self.assertIn("milk", match_allergens_in_name("生牛乳（含保加利亚乳杆菌）"))
        self.assertIn("eggs", match_allergens_in_name("巴氏杀菌全蛋液"))

    def test_expanded_additives_dictionary(self) -> None:
        self.assertEqual(lookup_additive_ins("六偏磷酸钠"), "452(i)")
        self.assertEqual(lookup_additive_ins("羧甲基纤维素钠"), "466")
        self.assertEqual(lookup_additive_ins("单，双甘油脂肪酸酯"), "471")
        self.assertEqual(lookup_additive_ins("E322"), "322")
        self.assertEqual(lookup_additive_ins("INS 500(ii)"), "500(ii)")


class TestNormalizationAndValidation(unittest.TestCase):
    def test_fixtures_pass_schema_and_semantic_validation(self) -> None:
        for fn in (make_cn_tea_fixture, make_cn_patty_fixture, make_us_cookies_fixture):
            ed = fn()
            self.assertEqual(validate_edition_doc(ed), [])

    def test_kj_to_kcal_and_per_unit_calculation(self) -> None:
        ed = make_cn_patty_fixture()
        norm = ed["normalized"]
        self.assertEqual(norm["nutrients"]["protein"]["value"], "18.6")
        self.assertEqual(norm["nutrients"]["carbs_available"]["value"], "1")
        self.assertEqual(norm["nutrients"]["energy_kcal"]["value"], "260.8")
        self.assertEqual(norm["per_unit"]["nutrients"]["energy_kcal"]["value"], "208.6")

    def test_cn_zero_thresholds_per_100_preserved_as_upper_bound(self) -> None:
        ed = make_cn_tea_fixture()
        norm = ed["normalized"]["nutrients"]
        # Under CN/GB28050-2011: 0 kJ -> < 17 kJ, 0 g protein -> < 0.5 g, 0 mg sodium -> < 5 mg
        self.assertEqual(norm["energy_kj"]["qualifier"], "<")
        self.assertEqual(norm["energy_kj"]["value"], "17")
        self.assertEqual(norm["energy_kj"]["basis"], "regulatory_upper_bound")
        self.assertEqual(norm["protein"]["qualifier"], "<")
        self.assertEqual(norm["protein"]["value"], "0.5")
        self.assertEqual(norm["protein"]["basis"], "regulatory_upper_bound")
        self.assertEqual(norm["sodium"]["qualifier"], "<")
        self.assertEqual(norm["sodium"]["value"], "5")
        self.assertEqual(norm["sodium"]["basis"], "regulatory_upper_bound")
        codes = [qf["code"] for qf in ed["quality_flags"]]
        self.assertIn("REGULATORY_ZERO_ROUNDING_ARTIFACT", codes)

    def test_us_fda_zero_rounding_upper_bound_and_available_carbs_preserved(self) -> None:
        ed = make_us_cookies_fixture()
        trans = ed["normalized"]["nutrients"]["fat_trans"]
        self.assertEqual(trans["qualifier"], "<")
        self.assertEqual(trans["value"], "1.79")
        self.assertEqual(trans["basis"], "regulatory_upper_bound")
        # Available carbs = carbs_total (67.9) - dietary_fiber (7.1) = 60.8 g/100g
        avail = ed["normalized"]["nutrients"]["carbs_available"]
        self.assertEqual(avail["value"], "60.8")
        self.assertEqual(avail["unit"], "g")
        self.assertEqual(avail["basis"], "derived")
        codes = [qf["code"] for qf in ed["quality_flags"]]
        self.assertIn("REGULATORY_ZERO_ROUNDING_ARTIFACT", codes)
        self.assertIn("CARBS_TOTAL_INCLUDES_FIBER", codes)

    def test_eu_and_jp_salt_sodium_bidirectional_derivation_and_carbs(self) -> None:
        # 1. EU/1169-2011: salt_equivalent (1.0 g) -> sodium (400 mg) using ratio 2.5
        eu_ed = make_cn_patty_fixture()
        eu_ed["core"]["regulatory_profile"] = "EU/1169-2011"
        eu_ed["core"]["nutrition_declared"]["rows"] = [
            {"nutrient": "energy", "value": "1000", "unit": "kJ"},
            {"nutrient": "fat_total", "value": "5", "unit": "g"},
            {"nutrient": "fat_saturated", "value": "1", "unit": "g"},
            {"nutrient": "carbs_available", "value": "50", "unit": "g"},
            {"nutrient": "sugars_total", "value": "4", "unit": "g"},
            {"nutrient": "protein", "value": "10", "unit": "g"},
            {"nutrient": "salt_equivalent", "value": "1", "unit": "g"},
        ]
        normalize_edition(eu_ed)
        self.assertEqual(eu_ed["normalized"]["nutrients"]["sodium"]["value"], "400")
        self.assertEqual(eu_ed["normalized"]["nutrients"]["sodium"]["basis"], "derived")
        self.assertIn("SODIUM_DERIVED_FROM_SALT", [q["code"] for q in eu_ed["quality_flags"]])

        # Reverse direction under EU/1169-2011: sodium (400 mg) -> salt_equivalent (1 g)
        eu_rev = copy.deepcopy(eu_ed)
        eu_rev["core"]["nutrition_declared"]["rows"][-1] = {
            "nutrient": "sodium",
            "value": "400",
            "unit": "mg",
        }
        normalize_edition(eu_rev)
        self.assertEqual(eu_rev["normalized"]["nutrients"]["salt_equivalent"]["value"], "1")
        self.assertEqual(eu_rev["normalized"]["nutrients"]["salt_equivalent"]["basis"], "derived")
        self.assertIn("SALT_DERIVED_FROM_SODIUM", [q["code"] for q in eu_rev["quality_flags"]])

        # 2. JP/CAA-2015: salt_per_sodium_ratio 2.54 + carbs_available = carbs_total - dietary_fiber
        jp_ed = make_cn_patty_fixture()
        jp_ed["core"]["regulatory_profile"] = "JP/CAA-2015"
        jp_ed["core"]["nutrition_declared"]["rows"] = [
            {"nutrient": "energy", "value": "100", "unit": "kcal"},
            {"nutrient": "protein", "value": "4", "unit": "g"},
            {"nutrient": "fat_total", "value": "2", "unit": "g"},
            {"nutrient": "carbs_total", "value": "10", "unit": "g"},
            {"nutrient": "dietary_fiber", "value": "2.5", "unit": "g"},
            {"nutrient": "salt_equivalent", "value": "2.54", "unit": "g"},
        ]
        normalize_edition(jp_ed)
        self.assertEqual(jp_ed["normalized"]["nutrients"]["sodium"]["value"], "1000")
        self.assertEqual(jp_ed["normalized"]["nutrients"]["carbs_available"]["value"], "7.5")
        self.assertEqual(jp_ed["normalized"]["nutrients"]["carbs_available"]["basis"], "derived")
        jp_codes = [q["code"] for q in jp_ed["quality_flags"]]
        self.assertIn("SODIUM_DERIVED_FROM_SALT", jp_codes)
        self.assertIn("CARBS_TOTAL_INCLUDES_FIBER", jp_codes)

    def test_nrv_pct_mismatch_flagged(self) -> None:
        ed = make_cn_patty_fixture()
        # 1091 kJ is ~13% of 8400 kJ; set wrong 50% NRV
        ed["core"]["nutrition_declared"]["rows"][0]["nrv_pct"] = "50"
        normalize_edition(ed)
        codes = [qf["code"] for qf in ed["quality_flags"]]
        self.assertIn("NRV_PCT_DECLARED_MISMATCH", codes)
        self.assertEqual(validate_edition_doc(ed), [])

    def test_dual_kj_and_kcal_declared_mismatch_flagged(self) -> None:
        ed = make_cn_patty_fixture()
        # Add an inconsistent kcal row alongside 1091 kJ (expected ~261 kcal, declare 400 kcal)
        ed["core"]["nutrition_declared"]["rows"].append(
            {"nutrient": "energy", "value": "400", "unit": "kcal"}
        )
        normalize_edition(ed)
        self.assertEqual(ed["normalized"]["nutrients"]["energy_kj"]["basis"], "reported")
        self.assertEqual(ed["normalized"]["nutrients"]["energy_kcal"]["basis"], "reported")
        codes = [qf["code"] for qf in ed["quality_flags"]]
        self.assertIn("ENERGY_KJ_KCAL_DECLARED_MISMATCH", codes)

    def test_forbidden_personal_batch_fields_rejected(self) -> None:
        bad = make_cn_tea_fixture()
        bad["attributes"]["production_date"] = "2026-08-28"
        errs = validate_edition_doc(bad)
        self.assertTrue(any("production_date" in e and "forbidden" in e for e in errs))

        bad_price = make_cn_tea_fixture()
        bad_price["attributes"]["purchase_price"] = "5.00"
        errs_price = validate_edition_doc(bad_price)
        self.assertTrue(any("purchase_price" in e and "forbidden" in e for e in errs_price))


class TestBuildSubmitPrAndMediaV02(unittest.TestCase):
    def test_empty_catalog_validate_and_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            empty_products = tmp_path / "products"
            empty_products.mkdir()
            out_site = tmp_path / "site"

            rc_val = cli_main(["validate", "--allow-empty", str(empty_products)])
            self.assertEqual(rc_val, 0)

            meta = build_static_api(empty_products, out_site)
            self.assertEqual(meta["total_products"], 0)
            self.assertTrue((out_site / "v1" / "meta.json").exists())
            self.assertTrue((out_site / "v1" / "index" / "brands.json").exists())
            self.assertTrue((out_site / "v1" / "index" / "catalog.jsonl").exists())
            self.assertTrue((out_site / "index.html").exists())

    def test_submit_corroboration_and_conflict_routing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_dir = tmp_path / "products"

            ed1 = make_cn_patty_fixture()
            sha_a = hashlib.sha256(b"photo-a").hexdigest()
            draft1 = {
                "id": ed1["id"],
                "core": copy.deepcopy(ed1["core"]),
                "attributes": copy.deepcopy(ed1["attributes"]),
                "evidence": [
                    {
                        "type": "label_photo",
                        "region": "nutrition_table",
                        "cropped_sha256": sha_a,
                        "media_ref": f"opf-media://sha256/{sha_a}",
                        "contributor": "github:user-a",
                        "reported_at": "2026-01-10",
                        "vintage_month": "2026-01",
                    }
                ],
            }
            p1 = tmp_path / "draft1.json"
            p1.write_text(json.dumps(draft1, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(cli_main(["submit", "--quiet", "--input", str(p1), "--out-dir", str(products_dir)]), 0)

            # Second contributor submits identical core + attributes with a new photo -> rev stays 1, evidence_level becomes corroborated
            sha_b = hashlib.sha256(b"photo-b").hexdigest()
            draft2 = copy.deepcopy(draft1)
            draft2["evidence"] = [
                {
                    "type": "label_photo",
                    "region": "nutrition_table",
                    "cropped_sha256": sha_b,
                    "media_ref": f"opf-media://sha256/{sha_b}",
                    "contributor": "github:user-b",
                    "reported_at": "2026-03-05",
                    "vintage_month": "2026-03",
                }
            ]
            p2 = tmp_path / "draft2.json"
            p2.write_text(json.dumps(draft2, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(cli_main(["submit", "--quiet", "--input", str(p2), "--out-dir", str(products_dir)]), 0)

            pdir = products_dir / "opf" / "demo-deli" / "black-pepper-patty" / "80g"
            ed_files = list((pdir / "editions").glob("*.json"))
            self.assertEqual(len(ed_files), 1)
            saved_ed = json.loads(ed_files[0].read_text(encoding="utf-8"))
            self.assertEqual(saved_ed["rev"], 1)
            self.assertEqual(derive_evidence_level(saved_ed), "corroborated")
            self.assertEqual(validate_product_dir(pdir, products_root=products_dir), [])

            # Attribute conflict against same (id, track, core_fingerprint) without --amend/--supersede/--new-variant must fail
            draft3 = copy.deepcopy(draft1)
            draft3["attributes"]["product_standard"] = ["GB/T 99999"]
            p3 = tmp_path / "draft3.json"
            p3.write_text(json.dumps(draft3, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(cli_main(["submit", "--quiet", "--input", str(p3), "--out-dir", str(products_dir)]), 1)

    def test_pr_dry_run_in_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_repo = tmp_path / "opf-data"
            data_repo.mkdir()
            subprocess.run(["git", "-C", str(data_repo), "init", "-b", "main"], check=True, capture_output=True)

            ed = make_cn_tea_fixture()
            draft = {
                "id": ed["id"],
                "aliases": ["示例大瓶茉莉花茶"],
                "core": ed["core"],
                "attributes": ed["attributes"],
                "evidence": ed["evidence"],
            }
            draft_path = tmp_path / "draft.json"
            draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
            rc = cli_main(
                ["pr", "--quiet", "--input", str(draft_path), "--data-repo", str(data_repo), "--dry-run"]
            )
            self.assertEqual(rc, 0)
            pjson = product_json_path(data_repo / "products", "gtin:00000000000109")
            self.assertTrue(pjson.exists())
            ed_files = list((pjson.parent / "editions").glob("*.json"))
            self.assertEqual(len(ed_files), 1)
            self.assertEqual(validate_product_dir(pjson.parent, products_root=data_repo / "products"), [])

    def test_media_metadata_stripping_jpeg_png_webp(self) -> None:
        # 1. JPEG: APP1 (EXIF) + APP13 (IPTC) + COM + DQT + SOS + EOI
        app1_seg = b"\xff\xe1" + struct.pack(">H", len(b"Exif\x00\x00SecretGPSData") + 2) + b"Exif\x00\x00SecretGPSData"
        app13_seg = b"\xff\xed" + struct.pack(">H", len(b"PhotoshopIPTC") + 2) + b"PhotoshopIPTC"
        com_seg = b"\xff\xfe" + struct.pack(">H", len(b"CameraComment") + 2) + b"CameraComment"
        dqt_seg = b"\xff\xdb" + struct.pack(">H", 6) + b"\x00" * 4
        sos_seg = b"\xff\xda\x00\x04\x00\x00\x11\x22\x33\xff\xd9"
        raw_jpeg = b"\xff\xd8" + app1_seg + app13_seg + com_seg + dqt_seg + sos_seg

        cleaned_jpg, removed_jpg = sanitize_image_bytes(raw_jpeg)
        self.assertEqual(set(removed_jpg), {"JPEG:0xFFE1", "JPEG:0xFFED", "JPEG:0xFFFE"})
        self.assertEqual(cleaned_jpg, b"\xff\xd8" + dqt_seg + sos_seg)

        # 2. PNG: IHDR + eXIf + tEXt + iTXt + tIME + IDAT + IEND
        ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        exif_png = _png_chunk(b"eXIf", b"II*\x00SecretGPS")
        text_png = _png_chunk(b"tEXt", b"Software\x00SecretCam")
        itxt_png = _png_chunk(b"iTXt", b"XML:com.adobe.xmp\x00\x00\x00\x00\x00<xmp/>")
        time_png = _png_chunk(b"tIME", struct.pack(">HBBBBB", 2026, 5, 1, 12, 0, 0))
        idat = _png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        iend = _png_chunk(b"IEND", b"")
        raw_png = b"\x89PNG\r\n\x1a\n" + ihdr + exif_png + text_png + itxt_png + time_png + idat + iend

        cleaned_png, removed_png = sanitize_image_bytes(raw_png)
        self.assertEqual(removed_png, ["PNG:eXIf", "PNG:tEXt", "PNG:iTXt", "PNG:tIME"])
        self.assertEqual(cleaned_png, b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend)

        # 3. WebP: RIFF + WEBP + VP8 + EXIF + XMP
        vp8_chunk = _webp_chunk(b"VP8 ", b"\x00\x01\x02\x03")
        exif_webp = _webp_chunk(b"EXIF", b"Exif\x00\x00GPS")
        xmp_webp = _webp_chunk(b"XMP ", b"<x:xmpmeta/>")
        chunks_raw = vp8_chunk + exif_webp + xmp_webp
        raw_webp = b"RIFF" + struct.pack("<I", 4 + len(chunks_raw)) + b"WEBP" + chunks_raw

        cleaned_webp, removed_webp = sanitize_image_bytes(raw_webp)
        self.assertEqual(removed_webp, ["WEBP:EXIF", "WEBP:XMP"])
        self.assertEqual(cleaned_webp, b"RIFF" + struct.pack("<I", 4 + len(vp8_chunk)) + b"WEBP" + vp8_chunk)

        # SHA-256 hash stability across sanitize_and_hash_image invocations
        with tempfile.TemporaryDirectory() as tmp:
            for ext, blob in (("jpg", raw_jpeg), ("png", raw_png), ("webp", raw_webp)):
                p = Path(tmp) / f"sample.{ext}"
                p.write_bytes(blob)
                rep1 = sanitize_and_hash_image(p)
                rep2 = sanitize_and_hash_image(p)
                self.assertGreater(len(rep1["removed_metadata"]), 0)
                self.assertEqual(rep2["removed_metadata"], [])
                self.assertEqual(rep1["sha256"], rep2["sha256"])
                self.assertEqual(len(str(rep1["sha256"])), 64)

    def test_label_fingerprint_tracks_parties_order_independently(self) -> None:
        a = make_cn_patty_fixture()
        b = make_cn_patty_fixture()
        a["attributes"]["parties"] = [
            {"role": "manufacturer", "name": "华南厂", "plant_code": "A", "license": "SC111"}
        ]
        b["attributes"]["parties"] = [
            {"role": "manufacturer", "name": "华北厂", "plant_code": "B", "license": "SC222"}
        ]
        normalize_edition(a)
        normalize_edition(b)
        self.assertEqual(a["core_fingerprint"], b["core_fingerprint"])
        self.assertNotEqual(a["label_fingerprint"], b["label_fingerprint"])

        two = copy.deepcopy(a)
        two["attributes"]["parties"] = [a["attributes"]["parties"][0], b["attributes"]["parties"][0]]
        normalize_edition(two)
        rev = copy.deepcopy(two)
        rev["attributes"]["parties"].reverse()
        normalize_edition(rev)
        self.assertEqual(two["label_fingerprint"], rev["label_fingerprint"])

    def test_uniform_and_divergent_compact_resolutions(self) -> None:
        # 1. Two plants sharing exact core_fingerprint -> uniform
        south = make_cn_patty_fixture("01JTESTCNPATY0000000000001")
        south["track"] = "CN/plant:SC111"
        south["attributes"]["parties"] = [
            {"role": "manufacturer", "name": "华南厂", "plant_code": "A", "license": "SC111"}
        ]
        normalize_edition(south)

        north = make_cn_patty_fixture("01JTESTCNPATY0000000000002")
        north["track"] = "CN/plant:SC222"
        north["attributes"]["parties"] = [
            {"role": "manufacturer", "name": "华北厂", "plant_code": "B", "license": "SC222"}
        ]
        normalize_edition(north)

        meta = make_product_meta_from_edition(
            south,
            tracks=[
                {
                    "track": "CN/plant:SC111",
                    "market": "CN",
                    "discriminator": {
                        "method": "sc_license",
                        "field": "attributes.parties[].license",
                        "instructions": [{"lang": "zh-Hans", "text": "SC111"}],
                    },
                },
                {
                    "track": "CN/plant:SC222",
                    "market": "CN",
                    "discriminator": {
                        "method": "sc_license",
                        "field": "attributes.parties[].license",
                        "instructions": [{"lang": "zh-Hans", "text": "SC222"}],
                    },
                },
            ],
        )
        records = [south, north]
        lc_map = derive_editions_lifecycle(records)
        compact_uniform = build_compact_doc(meta, records, {}, lc_map, "v1/opf/x/y/z.full.json")
        self.assertEqual(compact_uniform["resolution"], "uniform")
        self.assertEqual(
            sorted(p["plant_code"] for p in compact_uniform["parties_summary"]), ["A", "B"]
        )
        self.assertEqual(
            validate_against_json_schema(compact_uniform, load_json_schema("compact.v0.2.schema.json")),
            [],
        )

        # 2. Divergent core_fingerprint across tracks -> divergent
        north_div = copy.deepcopy(north)
        north_div["core"]["nutrition_declared"]["rows"][4]["value"] = "650"
        normalize_edition(north_div)
        records_div = [south, north_div]
        compact_div = build_compact_doc(
            meta, records_div, {}, derive_editions_lifecycle(records_div), "v1/opf/x/y/z.full.json"
        )
        self.assertEqual(compact_div["resolution"], "divergent")
        sodium = {
            v["edition_id"]: v["normalized"]["nutrients"]["sodium"]["value"]
            for v in compact_div["variants"]
        }
        self.assertEqual(
            sodium,
            {"01JTESTCNPATY0000000000001": "510", "01JTESTCNPATY0000000000002": "650"},
        )
        self.assertEqual(
            validate_against_json_schema(compact_div, load_json_schema("compact.v0.2.schema.json")),
            [],
        )

    def test_vault_hashes_and_opf_media_refs(self) -> None:
        ed = make_cn_patty_fixture()
        sha = hashlib.sha256(b"cropped").hexdigest()
        raw = hashlib.sha256(b"raw-original").hexdigest()
        ed["evidence"] = [
            {
                "evidence_id": f"sha256:{sha}",
                "type": "label_photo",
                "region": "nutrition_table",
                "cropped_sha256": sha,
                "vault_raw_sha256": raw,
                "media_ref": f"opf-media://sha256/{sha}",
                "artwork_note": "Spring Festival limited pack",
                "contributor": "github:user-a",
                "reported_at": "2026-01-10",
                "vintage_month": "2026-01",
            }
        ]
        ed["revisions"][0]["evidence_refs"] = [f"sha256:{sha}"]
        self.assertEqual(validate_edition_doc(ed), [])
        self.assertEqual(derive_evidence_level(ed), "verified")

        bad = copy.deepcopy(ed)
        bad["evidence"][0]["media_ref"] = "opf-media://sha256/" + "0" * 64
        self.assertTrue(any("does not match cropped_sha256" in e for e in validate_edition_doc(bad)))

        url = resolve_media_ref(f"opf-media://sha256/{sha}", "https://m.example.org/")
        self.assertEqual(url, f"https://m.example.org/media/{sha[:2]}/{sha[2:4]}/{sha}.webp")
        self.assertIsNone(resolve_media_ref(f"opf-media://sha256/{sha}", ""))


if __name__ == "__main__":
    unittest.main()
