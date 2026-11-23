"""Tests for OPF v0.2 Web Explorer locales, dictionary/enum coverage, JS hygiene, M3 tokens, and build asset copy."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from opf.builder import build_static_api
from opf.registries import REPO_ROOT


def _flatten(obj: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in obj.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, path))
        else:
            out[path] = str(v)
    return out


class TestWebV02(unittest.TestCase):
    def test_locales_parity_and_ui_key_coverage(self) -> None:
        locales_dir = REPO_ROOT / "web" / "locales"
        manifest = json.loads((locales_dir / "index.json").read_text(encoding="utf-8"))
        codes = [item["code"] for item in manifest["locales"]]
        expected_codes = {"zh-CN", "en", "ja", "de", "fr", "es", "it"}
        self.assertEqual(set(codes), expected_codes)

        flattened_by_code = {
            c: _flatten(json.loads((locales_dir / f"{c}.json").read_text(encoding="utf-8")))
            for c in codes
        }
        base_flat = flattened_by_code["en"]

        placeholder_re = re.compile(r"\{(\w+)\}")
        for code, flat in flattened_by_code.items():
            self.assertEqual(set(flat.keys()), set(base_flat.keys()), f"Key mismatch in {code}")
            for k, val in flat.items():
                self.assertEqual(
                    set(placeholder_re.findall(val)),
                    set(placeholder_re.findall(base_flat[k])),
                    f"Placeholder mismatch for key {k} in {code}",
                )

        html_text = (REPO_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="lang-select"', html_text)
        for attr_key in re.findall(r'data-i18n(?:-[a-z-]+)?="([^"]+)"', html_text):
            self.assertIn(attr_key, base_flat, f"Missing i18n key from index.html: {attr_key}")

        js_text = (REPO_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("detectPreferredLocale", js_text)
        for js_key in re.findall(r'\bt\(\s*"([^"$]+)"', js_text):
            self.assertIn(js_key, base_flat, f"Missing i18n key from app.js: {js_key}")

    def test_dictionary_and_v02_enum_coverage_in_locales(self) -> None:
        locales_dir = REPO_ROOT / "web" / "locales"
        manifest = json.loads((locales_dir / "index.json").read_text(encoding="utf-8"))
        codes = [item["code"] for item in manifest["locales"]]
        flats = {
            c: _flatten(json.loads((locales_dir / f"{c}.json").read_text(encoding="utf-8")))
            for c in codes
        }

        nutrients_dict = json.loads(
            (REPO_ROOT / "dictionaries" / "nutrients.json").read_text(encoding="utf-8")
        )["nutrients"]
        expected_nutrients = set()
        for nid, nmeta in nutrients_dict.items():
            for out_id in nmeta.get("normalized_outputs", [nid]):
                expected_nutrients.add(out_id)
        expected_nutrients.update({"fat_monounsaturated", "fat_polyunsaturated", "vitamin_a"})
        for out_id in sorted(expected_nutrients):
            for c, flat in flats.items():
                self.assertIn(f"nutrients.{out_id}", flat, f"Missing nutrients.{out_id} in {c}")

        allergens_dict = json.loads(
            (REPO_ROOT / "dictionaries" / "allergens.json").read_text(encoding="utf-8")
        )["allergens"]
        for aid in allergens_dict:
            for c, flat in flats.items():
                self.assertIn(f"allergens.{aid}", flat, f"Missing allergens.{aid} in {c}")

        edition_schema = json.loads(
            (REPO_ROOT / "spec" / "schema" / "edition.v0.2.schema.json").read_text(encoding="utf-8")
        )
        for role in edition_schema["$defs"]["Party"]["properties"]["role"]["enum"]:
            for c, flat in flats.items():
                self.assertIn(f"roles.{role}", flat, f"Missing roles.{role} in {c}")
        for rkind in edition_schema["$defs"]["RevisionEntry"]["properties"]["kind"]["enum"]:
            for c, flat in flats.items():
                self.assertIn(f"revisionKinds.{rkind}", flat, f"Missing revisionKinds.{rkind} in {c}")

        compact_schema = json.loads(
            (REPO_ROOT / "spec" / "schema" / "compact.v0.2.schema.json").read_text(encoding="utf-8")
        )
        for status in compact_schema["$defs"]["EditionStatus"]["enum"]:
            for c, flat in flats.items():
                self.assertIn(f"statuses.{status}", flat, f"Missing statuses.{status} in {c}")
        for res_mode in ("single", "uniform", "divergent", "inactive"):
            for c, flat in flats.items():
                self.assertIn(f"resolutions.{res_mode}.label", flat)
                self.assertIn(f"resolutions.{res_mode}.short", flat)

    def test_app_js_v02_clean_no_v01_leaks_and_syntax_ok(self) -> None:
        js_path = REPO_ROOT / "web" / "app.js"
        js_text = js_path.read_text(encoding="utf-8")
        forbidden_v01_patterns = (
            r"\.\bdeclared\b",
            r"\bnutrition_panel\b",
            r"\.\bobserved\b",
            r"\bobserved_at\b",
            r"\bformulation_fingerprint\b",
            r"\bsame_formulation_editions\b",
            r"\bhas_concurrent_variants\b",
            r"\bconcurrent_variants\b",
            r"\blatest_edition_id\b",
            r"\bv0\.1\b",
        )
        for pat in forbidden_v01_patterns:
            m = re.search(pat, js_text)
            self.assertIsNone(m, f"Found residual v0.1 pattern {pat!r} in web/app.js: {m}")

        node_bin = shutil.which("node")
        if node_bin:
            res = subprocess.run(
                [node_bin, "--check", str(js_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, f"node --check failed: {res.stderr}")

    def test_m3_palette_and_zero_external_fonts(self) -> None:
        css_text = (REPO_ROOT / "web" / "style.css").read_text(encoding="utf-8")
        marker = "/* --- END M3 TOKENS --- */"
        self.assertIn(marker, css_text)
        token_css, body_css = css_text.split(marker, 1)

        # Body CSS rules after the M3 token block must not hardcode raw hex/rgb/hsl colors
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}", body_css), [])
        self.assertEqual(re.findall(r"\brgba?\s*\(", body_css, flags=re.IGNORECASE), [])
        self.assertEqual(re.findall(r"\bhsla?\s*\(", body_css, flags=re.IGNORECASE), [])

        # Approved MD3E token hex allowlist only (Warm Stone / Dark Slate / Ink Blue / Slate Indigo / M3 Error; zero health traffic-light hues)
        approved_hex = {
            "#dfd9cc", "#f8f5ee", "#ffffff", "#f2eee4", "#ece6d9", "#e4ddce", "#dcd4c3",
            "#1b1f2a", "#4a4f5c", "#7a7f8c", "#cfcabd", "#2b4c7e", "#d6e3ff", "#001b3e",
            "#4c5d78", "#d8e3f8", "#0d1c32", "#b3261e",
            "#0f1116", "#13161d", "#0d0f14", "#1a1e27", "#202530", "#2a303d", "#353b4a",
            "#e4e6ee", "#b5bac8", "#8b90a0", "#3a3f4c", "#a9c4f5", "#0b2347", "#1f3a66",
            "#b4c6e4", "#33445e", "#f2b8b5",
        }
        found_hex = {h.lower() for h in re.findall(r"#[0-9a-fA-F]{3,8}", token_css)}
        self.assertEqual(found_hex - approved_hex, set(), f"Unapproved colors in M3 tokens: {found_hex - approved_hex}")

        # MD3E tokens, motion safety, responsive detail helpers, and complex workbench classes present
        for needle in (
            "--md-surface-lowest",
            "--md-surface-highest",
            "--md-secondary-container",
            "--ease-spring",
            "prefers-reduced-motion",
            ".table-wrap",
            ".rev-pill",
            ".section-card",
            ".filter-workbench",
            ".wb-grid",
            ".kpi-strip",
        ):
            self.assertIn(needle, css_text)

        html_text = (REPO_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for ctrl_id in (
            'id="filter-workbench"',
            'id="market-filters"',
            'id="wb-toggle"',
            'id="filter-panel"',
            'id="wb-col-facets"',
            'id="wb-col-ingredients"',
            'id="wb-col-nutrients"',
            'id="active-filters-strip"',
            'id="sort-select"',
            'id="q-clear"',
            'id="reset-filters-btn"',
        ):
            self.assertIn(ctrl_id, html_text)

        for rel_file in ("web/index.html", "web/style.css", "web/app.js"):
            txt = (REPO_ROOT / rel_file).read_text(encoding="utf-8")
            self.assertNotIn("fonts.googleapis.com", txt)
            self.assertNotIn("fonts.gstatic.com", txt)

    def test_build_copies_updated_web_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_dir = tmp_path / "products"
            products_dir.mkdir()
            site_dir = tmp_path / "site"

            build_static_api(products_dir, site_dir)
            self.assertEqual(
                (site_dir / "index.html").read_text(encoding="utf-8"),
                (REPO_ROOT / "web" / "index.html").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (site_dir / "assets" / "app.js").read_text(encoding="utf-8"),
                (REPO_ROOT / "web" / "app.js").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (site_dir / "assets" / "style.css").read_text(encoding="utf-8"),
                (REPO_ROOT / "web" / "style.css").read_text(encoding="utf-8"),
            )
            for loc in (
                "index.json",
                "zh-CN.json",
                "en.json",
                "ja.json",
                "de.json",
                "fr.json",
                "es.json",
                "it.json",
            ):
                self.assertEqual(
                    (site_dir / "locales" / loc).read_text(encoding="utf-8"),
                    (REPO_ROOT / "web" / "locales" / loc).read_text(encoding="utf-8"),
                )

    def test_open_source_sanitization_no_private_refs_or_owner_placeholders(self) -> None:
        """Guard open-source repos against local host paths, LAN IPs, and unresolved template placeholders."""
        forbidden_rules = [
            (re.compile(r"\b[O]WNER\b"), "unresolved org placeholder"),
            (re.compile(r"<[o]wner>", re.IGNORECASE), "unresolved owner tag"),
            (re.compile(r"example[.]github[.]io", re.IGNORECASE), "placeholder Pages domain"),
            (re.compile(r"\b192\.168\.[0-9]{1,3}\.[0-9]{1,3}\b"), "private LAN IPv4"),
            (re.compile(r"/(?:Users|Volumes|home)/[A-Za-z0-9._-]+/"), "local host directory path"),
        ]

        roots = [REPO_ROOT]
        data_repo = REPO_ROOT.parent / "opf-data"
        media_repo = REPO_ROOT.parent / "opf-media"
        if data_repo.is_dir():
            roots.append(data_repo)
        if media_repo.is_dir():
            roots.append(media_repo)

        skip_dirs = {".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist", "open_packaged_food.egg-info"}
        hits: list[str] = []
        for root in roots:
            for cur_root, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for fname in sorted(files):
                    fpath = Path(cur_root) / fname
                    try:
                        text = fpath.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        continue
                    rel = f"{root.name}/{fpath.relative_to(root)}"
                    for idx, line in enumerate(text.splitlines(), 1):
                        for pat, label in forbidden_rules:
                            if pat.search(line):
                                hits.append(f"{rel}:{idx} [{label}]: {line.strip()[:120]}")

        self.assertEqual(hits, [], "Disallowed private refs or placeholders found:\n" + "\n".join(hits))

        for rel_path in (
            "README.md",
            "README.zh-CN.md",
            "README.ja.md",
            "README.de.md",
            "README.fr.md",
            "README.es.md",
            "README.it.md",
            "skills/opf/SKILL.md",
            ".github/ISSUE_TEMPLATE/config.yml",
        ):
            self.assertIn("mickey996icu", (REPO_ROOT / rel_path).read_text(encoding="utf-8"))

        if data_repo.is_dir():
            for rel_path in (
                "README.md",
                "README.zh-CN.md",
                "README.ja.md",
                "README.de.md",
                "README.fr.md",
                "README.es.md",
                "README.it.md",
                ".github/ISSUE_TEMPLATE/config.yml",
            ):
                self.assertIn("mickey996icu", (data_repo / rel_path).read_text(encoding="utf-8"))

        if media_repo.is_dir():
            for rel_path in (
                "README.md",
                "README.zh-CN.md",
                "README.ja.md",
                "README.de.md",
                "README.fr.md",
                "README.es.md",
                "README.it.md",
            ):
                self.assertIn("mickey996icu", (media_repo / rel_path).read_text(encoding="utf-8"))

    def test_skill_minimal_draft_example_submits_and_validates(self) -> None:
        """Verify SKILL.md references examples/draft.minimal.json and the draft submits cleanly."""
        skill_text = (REPO_ROOT / "skills" / "opf" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("[examples/draft.minimal.json](./examples/draft.minimal.json)", skill_text)

        draft_path = REPO_ROOT / "skills" / "opf" / "examples" / "draft.minimal.json"
        self.assertTrue(draft_path.is_file(), f"Missing minimal skill draft template: {draft_path}")

        with tempfile.TemporaryDirectory() as tmp:
            products_dir = Path(tmp) / "products"
            products_dir.mkdir()
            submit_res = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "opf"),
                    "submit",
                    "--input",
                    str(draft_path),
                    "--out-dir",
                    str(products_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(submit_res.returncode, 0, submit_res.stderr)

            validate_res = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "opf"),
                    "validate",
                    str(products_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(validate_res.returncode, 0, validate_res.stderr)

    def test_scanner_ui_locales_empty_guide_and_node_parser(self) -> None:
        html_text = (REPO_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for needle in (
            'id="scan-btn"',
            'id="scan-modal"',
            'id="scan-video"',
            'id="scan-file"',
            'role="dialog"',
            'aria-modal="true"',
        ):
            self.assertIn(needle, html_text)

        js_text = (REPO_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        empty_fn_match = re.search(
            r"function renderEmptyCatalogCard\(\)\s*\{(.*?)\n\}",
            js_text,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(empty_fn_match)
        empty_fn_body = empty_fn_match.group(1)
        self.assertIn(
            "https://github.com/mickey996icu/open-packaged-food/blob/main/CONTRIBUTING.md",
            empty_fn_body,
        )
        forbidden_empty_terms = ("git clone", "opf submit", "uvx", "bin/opf", "submit_" + "product.yml")
        for term in forbidden_empty_terms:
            self.assertNotIn(term, empty_fn_body)

        locales_dir = REPO_ROOT / "web" / "locales"
        manifest = json.loads((locales_dir / "index.json").read_text(encoding="utf-8"))
        scanner_key_sets = {}
        for item in manifest["locales"]:
            code = item["code"]
            loc_data = json.loads((locales_dir / f"{code}.json").read_text(encoding="utf-8"))
            empty_text = json.dumps(loc_data.get("empty", {}), ensure_ascii=False)
            for term in forbidden_empty_terms:
                self.assertNotIn(term, empty_text, f"Forbidden CLI/form term {term!r} in {code} empty.*")
            self.assertIn("scanner", loc_data, f"Missing scanner section in {code}")
            scanner_key_sets[code] = set(loc_data["scanner"].keys())
            for req_key in ("openBtn", "startCameraBtn", "stopCameraBtn", "invalidCheckDigit", "notFoundTitle"):
                self.assertIn(req_key, scanner_key_sets[code], f"Missing scanner.{req_key} in {code}")

        base_scanner_keys = scanner_key_sets["en"]
        for code, keys in scanner_key_sets.items():
            self.assertEqual(keys, base_scanner_keys, f"scanner.* key mismatch in {code}")

        node_bin = shutil.which("node")
        self.assertIsNotNone(node_bin, "Node.js is required to verify web/app.js scanner logic")
        node_script = r"""
const assert = require("assert");
const mod = require(process.argv[1]);
assert.strictEqual(mod.isValidGs1CheckDigit("96385074"), true);
assert.strictEqual(mod.isValidGs1CheckDigit("036000291452"), true);
assert.strictEqual(mod.isValidGs1CheckDigit("4901234567894"), true);
assert.strictEqual(mod.isValidGs1CheckDigit("00000000000017"), true);
assert.strictEqual(mod.isValidGs1CheckDigit("4901234567895"), false);
assert.strictEqual(mod.isValidGs1CheckDigit("00000000000000"), false);
assert.strictEqual(mod.isValidGs1CheckDigit("123456789"), false);

const ean13 = mod.parseScannedCode("4901234567894");
assert.strictEqual(ean13.kind, "gtin");
assert.strictEqual(ean13.gtin14, "04901234567894");
assert.strictEqual(ean13.id, "gtin:04901234567894");
assert.strictEqual(ean13.apiPath, "v1/gtin/490/123/04901234567894.json");

const dl = mod.parseScannedCode("https://id.gs1.org/01/00000000000017/10/BATCH?17=260800");
assert.strictEqual(dl.kind, "gtin");
assert.strictEqual(dl.id, "gtin:00000000000017");
assert.strictEqual(dl.apiPath, "v1/gtin/000/000/00000000000017.json");

const qp = mod.parseScannedCode("https://example.com/scan?ean=4901234567894");
assert.strictEqual(qp.kind, "gtin");
assert.strictEqual(qp.id, "gtin:04901234567894");

const opf = mod.parseScannedCode("opf:demo-tea/jasmine-tea/500ml");
assert.strictEqual(opf.kind, "opf");
assert.strictEqual(opf.id, "opf:demo-tea/jasmine-tea/500ml");
assert.strictEqual(opf.apiPath, "v1/opf/demo-tea/jasmine-tea/500ml.json");

const bad = mod.parseScannedCode("https://id.gs1.org/01/4901234567895");
assert.strictEqual(bad.kind, "invalid_gtin");
assert.strictEqual(bad.valid, false);

const badPref = mod.parseScannedCode("gtin:00000000000018");
assert.strictEqual(badPref.kind, "invalid_gtin");
assert.strictEqual(badPref.valid, false);

const plain = mod.parseScannedCode("https://example.com/about");
assert.strictEqual(plain.kind, "text");
assert.strictEqual(plain.valid, false);
"""
        res = subprocess.run(
            [node_bin, "-e", node_script, str(REPO_ROOT / "web" / "app.js")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, f"Node scanner test failed: {res.stderr}\n{res.stdout}")


if __name__ == "__main__":
    unittest.main()
