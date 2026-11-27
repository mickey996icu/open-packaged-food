"""Tests for v0.3.3 optional/empty core.net_content (omitted whole-pack per_unit without un-evidenced weight)."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from opf.audit import audit_edition_doc
from opf.builder import build_compact_doc, build_static_api
from opf.cli_submit import _prepare_candidate_from_draft, execute_submit
from opf.normalize import derive_editions_lifecycle
from opf.validator import validate_edition_doc
from tests.fixtures import make_cn_patty_fixture, make_product_meta_from_edition


class TestOptionalNetContentV033(unittest.TestCase):
    def test_existing_non_empty_net_content_preserves_exact_core_fingerprint(self) -> None:
        ed = make_cn_patty_fixture()
        self.assertEqual(validate_edition_doc(ed), [])
        self.assertTrue(ed["core"]["net_content"])
        self.assertIn("per_unit", ed["normalized"])

    def test_omitted_or_empty_net_content_normalizes_without_per_unit_and_builds_cleanly(self) -> None:
        raw_ing = "配料：小麦粉、白砂糖、植物油、食用盐。"
        draft = {
            "id": "gtin:06901234567892",
            "core": {
                "regulatory_profile": "CN/GB28050-2011",
                # Intentionally omit net_content (no front-panel weight crop taken)
                "nutrition_declared": {
                    "basis": {"value": "100", "unit": "g"},
                    "rows": [
                        {"nutrient": "energy", "value": "1950", "unit": "kJ", "nrv_pct": "23"},
                        {"nutrient": "protein", "value": "7.5", "unit": "g", "nrv_pct": "13"},
                        {"nutrient": "fat_total", "value": "18.2", "unit": "g", "nrv_pct": "30"},
                        {"nutrient": "carbs_available", "value": "66.0", "unit": "g", "nrv_pct": "22"},
                        {"nutrient": "sodium", "value": "310", "unit": "mg", "nrv_pct": "16"},
                    ],
                },
                "allergens_declared": {"contains": ["gluten_cereals"], "may_contain": []},
            },
            "attributes": {
                "product_name": [{"lang": "zh-Hans", "text": "袋装苏打饼干"}],
                "brand": "示例麦坊",
                "ingredients_text": [{"lang": "zh-Hans", "text": raw_ing}],
                "product_standard": ["GB/T 20980"],
                "shelf_life": {"value": "12", "unit": "month"},
                "storage_text": "置于阴凉干燥处保存",
                "parties": [
                    {
                        "role": "manufacturer",
                        "name": "示例食品厂",
                        "address": "浙江省杭州市示例路1号",
                        "license": "SC10833010000019",
                    }
                ],
            },
            "evidence": [
                {
                    "type": "label_photo",
                    "region": "full_back_label",
                    "cropped_sha256": "e" * 64,
                    "media_ref": f"opf-media://sha256/{'e' * 64}",
                    "contributor": "github:tester",
                    "reported_at": "2026-11-26",
                    "vintage_month": "2026-11",
                }
            ],
        }
        cand, errs = _prepare_candidate_from_draft(draft, track="CN/default")
        self.assertEqual(errs, [])
        self.assertEqual(cand["core"]["net_content"], [])
        self.assertNotIn("per_unit", cand["normalized"])

        # CLI execute_submit + validate + audit + Static API build & compact schema check with empty net_content
        with tempfile.TemporaryDirectory() as tmp:
            draft_path = Path(tmp) / "draft.json"
            draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
            root = Path(tmp) / "products"
            rc, summary = execute_submit(
                argparse.Namespace(
                    input=str(draft_path),
                    out_dir=str(root),
                    amend=None,
                    supersede=None,
                    new_variant=False,
                    track=None,
                    author="github:tester",
                    provenance="external_contributor",
                    agreement_ref=None,
                    reason=None,
                    specimen_id=None,
                )
            )
            self.assertEqual(rc, 0)
            self.assertEqual(summary["action"], "created_edition")
            ed_path = Path(summary["product_dir"]) / "editions" / f"{summary['edition_id']}.json"
            ed = json.loads(ed_path.read_text(encoding="utf-8"))
            self.assertEqual(ed["core"]["net_content"], [])
            self.assertNotIn("per_unit", ed["normalized"])
            self.assertEqual(validate_edition_doc(ed), [])
            self.assertEqual([f for f in audit_edition_doc(ed) if f.severity in ("ERROR", "WARN")], [])

            # Writing net_content_label while core.net_content is empty must raise an audit ERROR
            bad_ed = json.loads(json.dumps(ed))
            bad_ed["attributes"]["net_content_label"] = "净含量：120克"
            bad_codes = [f.code for f in audit_edition_doc(bad_ed) if f.severity == "ERROR"]
            self.assertIn("NET_CONTENT_LABEL_WITHOUT_QUANTITY", bad_codes)

            out_site = Path(tmp) / "site"
            site_meta = build_static_api(root, out_site, allow_empty=False)
            self.assertEqual(site_meta["total_products"], 1)
            lc = derive_editions_lifecycle([ed])
            meta = make_product_meta_from_edition(ed)
            compact = build_compact_doc(meta, [ed], {}, lc, "v1/gtin/690/123/06901234567892.full.json")
            self.assertEqual(compact["net_content"], [])


if __name__ == "__main__":
    unittest.main()
