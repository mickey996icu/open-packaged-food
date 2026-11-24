"""Unit and CLI tests for PR metadata/DCO gate, INS 160c mapping, and Explorer cache-busting."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from opf.ingredients import parse_ingredients_semantic
from opf.pr_check import validate_pr_metadata
from opf.registries import REPO_ROOT


class TestPrMetadataAndFixes(unittest.TestCase):
    def test_media_pr_rejects_empty_body_and_accepts_valid_or_maintenance(self) -> None:
        errs_empty = validate_pr_metadata(
            repo_kind="media",
            title="media(label): add complete unclipped label evidence",
            body="",
            changed_files=["media/91/9a/919a8247248a4d7b2ee3642d8336d114a4d4e05ca9e65956d3c3347c9fc3c208.webp"],
        )
        self.assertTrue(any("must not be empty" in e for e in errs_empty))

        errs_no_product = validate_pr_metadata(
            repo_kind="media",
            title="media(label): upload cropped WebP files",
            body="Uploaded cropped label images with stripped EXIF metadata only.",
            changed_files=["media/91/9a/919a8247248a4d7b2ee3642d8336d114a4d4e05ca9e65956d3c3347c9fc3c208.webp"],
        )
        self.assertTrue(any("must reference the target product ID" in e for e in errs_no_product))

        errs_ok = validate_pr_metadata(
            repo_kind="media",
            title="media(label): gtin:06974117080016 label WebP crops",
            body=(
                "## Label Evidence Media\n"
                "- **Companion Data PR**: https://github.com/mickey996icu/opf-data/pull/2\n"
                "- **Product**: `gtin:06974117080016`\n"
            ),
            changed_files=["media/91/9a/919a8247248a4d7b2ee3642d8336d114a4d4e05ca9e65956d3c3347c9fc3c208.webp"],
            commits=[("abc12345", "media(label): add crops\n\nSigned-off-by: Dev <dev@users.noreply.github.com>")],
        )
        self.assertEqual(errs_ok, [])

        errs_maint = validate_pr_metadata(
            repo_kind="media",
            title="ci: add PR template and metadata gate",
            body="Add pull request template and CI metadata validation workflow.",
            changed_files=[".github/PULL_REQUEST_TEMPLATE.md", ".github/workflows/ci.yml"],
            commits=[("def67890", "ci: add PR gate\n\nSigned-off-by: Dev <dev@users.noreply.github.com>")],
        )
        self.assertEqual(errs_maint, [])

    def test_data_pr_rejects_placeholders_unchecked_boxes_and_missing_companion_url(self) -> None:
        errs_placeholder = validate_pr_metadata(
            repo_kind="data",
            title="feat(product): add vegan steak record",
            body=(
                "- [x] 新增商品\n"
                "- **ID**: `gtin:06974117080016`\n"
                "- **Companion Media PR（先合入）**: 填上你刚开的 opf-media PR 链接\n"
            ),
            changed_files=["products/gtin/697/411/06974117080016/product.json"],
            require_companion_media_pr=True,
        )
        self.assertTrue(any("unresolved placeholder" in e for e in errs_placeholder))
        self.assertTrue(any("companion opf-media PR URL" in e for e in errs_placeholder))

        errs_unchecked = validate_pr_metadata(
            repo_kind="tooling",
            title="fix(cli): refine validation output",
            body="## Change Type\n- [ ] New product\n- [ ] Tooling update\nDetailed description of tooling changes.",
        )
        self.assertTrue(any("none are checked" in e for e in errs_unchecked))

        errs_dco = validate_pr_metadata(
            repo_kind="tooling",
            title="fix(cli): refine validation output",
            body="Detailed description of tooling changes without template checkboxes.",
            commits=[("11223344", "fix(cli): missing signoff line")],
        )
        self.assertTrue(any("Signed-off-by" in e for e in errs_dco))

    def test_cli_check_pr_meta_with_event_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ev_file = Path(tmp) / "event.json"
            ev_file.write_text(
                json.dumps(
                    {
                        "pull_request": {
                            "title": "feat(product): gtin:06974117080016 (rev1)",
                            "body": (
                                "## Product Submission (v0.2)\n"
                                "> **Companion Media PR (MERGE FIRST)**: https://github.com/mickey996icu/opf-media/pull/1\n"
                                "- **ID**: `gtin:06974117080016`\n"
                            ),
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            res = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "opf"),
                    "check-pr-meta",
                    "--repo-kind",
                    "data",
                    "--event-path",
                    str(ev_file),
                    "--require-companion-media-pr",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, res.stderr)

    def test_paprika_extract_ins_160c_and_web_cache_busting(self) -> None:
        nodes = parse_ingredients_semantic(
            "水、辣椒红、山梨酸钾", lang="zh-Hans", profile_id="CN/GB28050-2025"
        )
        by_name = {n["name"]: n for n in nodes}
        self.assertEqual(by_name["辣椒红"].get("ins"), "160c")
        self.assertTrue(by_name["辣椒红"].get("is_additive"))

        app_js = (REPO_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function withDataRev(", app_js)
        self.assertIn('{ cache: "no-cache" }', app_js)
        self.assertIn('withDataRev("v1/index/catalog.jsonl")', app_js)


if __name__ == "__main__":
    unittest.main()
