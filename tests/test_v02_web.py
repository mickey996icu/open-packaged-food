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

from opf import __version__
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
        expected_codes = {"zh-CN", "en", "ja", "ko", "de", "fr", "es", "it"}
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

        for js_rel in ("app.js", "workbench.js", "detail.js", "scanner.js"):
            js_text = (REPO_ROOT / "web" / js_rel).read_text(encoding="utf-8")
            if js_rel == "app.js":
                self.assertIn("detectPreferredLocale", js_text)
            for js_key in re.findall(r'\bt\(\s*"([^"$]+)"', js_text):
                self.assertIn(js_key, base_flat, f"Missing i18n key from {js_rel}: {js_key}")

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
            (REPO_ROOT / "spec" / "schema" / "edition.v0.3.schema.json").read_text(encoding="utf-8")
        )
        for role in edition_schema["$defs"]["Party"]["properties"]["role"]["enum"]:
            for c, flat in flats.items():
                self.assertIn(f"roles.{role}", flat, f"Missing roles.{role} in {c}")
        for rkind in edition_schema["$defs"]["RevisionEntry"]["properties"]["kind"]["enum"]:
            for c, flat in flats.items():
                self.assertIn(f"revisionKinds.{rkind}", flat, f"Missing revisionKinds.{rkind} in {c}")
        for excat in edition_schema["$defs"]["NutritionExemption"]["properties"]["category"]["enum"]:
            for c, flat in flats.items():
                self.assertIn(
                    f"nutritionExemptions.{excat}",
                    flat,
                    f"Missing nutritionExemptions.{excat} in {c}",
                )

        compact_schema = json.loads(
            (REPO_ROOT / "spec" / "schema" / "compact.v0.3.schema.json").read_text(encoding="utf-8")
        )
        for status in compact_schema["$defs"]["EditionStatus"]["enum"]:
            for c, flat in flats.items():
                self.assertIn(f"statuses.{status}", flat, f"Missing statuses.{status} in {c}")
        for res_mode in ("single", "uniform", "divergent", "inactive"):
            for c, flat in flats.items():
                self.assertIn(f"resolutions.{res_mode}.label", flat)
                self.assertIn(f"resolutions.{res_mode}.short", flat)

    def test_app_js_v02_clean_no_v01_leaks_and_syntax_ok(self) -> None:
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
        node_bin = shutil.which("node")
        for js_name in ("app.js", "workbench.js", "detail.js", "scanner.js"):
            js_path = REPO_ROOT / "web" / js_name
            js_text = js_path.read_text(encoding="utf-8")
            for pat in forbidden_v01_patterns:
                m = re.search(pat, js_text)
                self.assertIsNone(m, f"Found residual v0.1 pattern {pat!r} in web/{js_name}: {m}")
            self.assertLessEqual(len(js_text.splitlines()), 800, f"web/{js_name} must stay <= 800 lines")
            if node_bin:
                res = subprocess.run(
                    [node_bin, "--check", str(js_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(res.returncode, 0, f"node --check failed for {js_name}: {res.stderr}")

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

        for extra_css in ("style-detail.css", "style-overlays.css"):
            extra_body = (REPO_ROOT / "web" / extra_css).read_text(encoding="utf-8")
            self.assertLessEqual(len(extra_body.splitlines()), 800)
            self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}", extra_body), [])
            self.assertEqual(re.findall(r"\brgba?\s*\(", extra_body, flags=re.IGNORECASE), [])
            self.assertEqual(re.findall(r"\bhsla?\s*\(", extra_body, flags=re.IGNORECASE), [])

        html_text = (REPO_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for perf_needle in ('id="opf-critical-css"', "__OPF_PREFETCH__", 'class="skel-card"'):
            self.assertIn(perf_needle, html_text)
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

        for rel_file in (
            "web/index.html",
            "web/style.css",
            "web/style-detail.css",
            "web/style-overlays.css",
            "web/workbench.js",
            "web/detail.js",
            "web/app.js",
            "web/scanner.js",
        ):
            txt = (REPO_ROOT / rel_file).read_text(encoding="utf-8")
            for forbidden_host in (
                "fonts.googleapis.com",
                "fonts.gstatic.com",
                "cdn.jsdelivr.net",
                "unpkg.com",
                "cdnjs.cloudflare.com",
            ):
                self.assertNotIn(forbidden_host, txt, f"External CDN {forbidden_host} found in {rel_file}")

    def test_build_copies_updated_web_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_dir = tmp_path / "products"
            products_dir.mkdir()
            site_dir = tmp_path / "site"

            build_static_api(products_dir, site_dir)
            meta = json.loads((site_dir / "v1" / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["opf_version"], __version__)
            bootstrap = json.loads((site_dir / "v1" / "bootstrap.json").read_text(encoding="utf-8"))
            self.assertEqual(bootstrap["meta"]["opf_version"], __version__)
            self.assertEqual(bootstrap["catalog"], [])
            self.assertEqual(
                (site_dir / "index.html").read_text(encoding="utf-8"),
                (REPO_ROOT / "web" / "index.html").read_text(encoding="utf-8"),
            )
            for asset_name in (
                "app.js",
                "workbench.js",
                "detail.js",
                "scanner.js",
                "style.css",
                "style-detail.css",
                "style-overlays.css",
            ):
                self.assertEqual(
                    (site_dir / "assets" / asset_name).read_text(encoding="utf-8"),
                    (REPO_ROOT / "web" / asset_name).read_text(encoding="utf-8"),
                )
            self.assertEqual(
                (site_dir / "assets" / "vendor" / "zxing.min.js").read_bytes(),
                (REPO_ROOT / "web" / "vendor" / "zxing.min.js").read_bytes(),
            )
            self.assertEqual(
                (site_dir / "assets" / "vendor" / "LICENSE-ZXING.txt").read_bytes(),
                (REPO_ROOT / "web" / "vendor" / "LICENSE-ZXING.txt").read_bytes(),
            )
            for loc in (
                "index.json",
                "zh-CN.json",
                "en.json",
                "ja.json",
                "ko.json",
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
            'src="assets/vendor/zxing.min.js"',
            'src="assets/scanner.js"',
            'src="assets/app.js"',
        ):
            self.assertIn(needle, html_text)
        self.assertLess(
            html_text.index('src="assets/vendor/zxing.min.js"'),
            html_text.index('src="assets/scanner.js"'),
        )
        self.assertLess(
            html_text.index('src="assets/scanner.js"'),
            html_text.index('src="assets/app.js"'),
        )

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

    def test_scanner_dual_engine_zxing_fallback_and_camera_cleanup(self) -> None:
        node_bin = shutil.which("node")
        self.assertIsNotNone(node_bin, "Node.js is required to verify web/scanner.js ZXing fallback")
        node_script = r"""
const assert = require("assert");
const ZXing = require(process.argv[1]);
globalThis.ZXing = ZXing;
const scanner = require(process.argv[2]);

function bitMatrixToRgba(matrix, scale = 4, margin = 16, inverted = false) {
  const mw = matrix.getWidth();
  const mh = matrix.getHeight();
  const width = mw * scale + margin * 2;
  const height = mh * scale + margin * 2;
  const data = new Uint8ClampedArray(width * height * 4);
  const bg = inverted ? 0 : 255;
  const fg = inverted ? 255 : 0;
  for (let i = 0; i < data.length; i += 4) {
    data[i] = bg; data[i + 1] = bg; data[i + 2] = bg; data[i + 3] = 255;
  }
  for (let y = 0; y < mh; y += 1) {
    for (let x = 0; x < mw; x += 1) {
      if (!matrix.get(x, y)) continue;
      for (let dy = 0; dy < scale; dy += 1) {
        for (let dx = 0; dx < scale; dx += 1) {
          const px = margin + x * scale + dx;
          const py = margin + y * scale + dy;
          const idx = (py * width + px) * 4;
          data[idx] = fg; data[idx + 1] = fg; data[idx + 2] = fg;
        }
      }
    }
  }
  return { data, width, height };
}

function buildEan13Rgba(digits, scale = 3, height = 120, rotate90 = false) {
  const L = ["0001101","0011001","0010011","0111101","0100011","0110001","0101111","0111011","0110111","0001011"];
  const G = ["0100111","0110011","0011011","0100001","0011101","0111001","0000101","0010001","0001001","0010111"];
  const R = ["1110010","1100110","1101100","1000010","1011100","1001110","1010000","1000100","1001000","1110100"];
  const PARITY = ["LLLLLL","LLGLGG","LLGGLG","LLGGGL","LGLLGG","LGGLLG","LGGGLL","LGLGLG","LGLGGL","LGGLGL"];
  const d = digits.split("").map(Number);
  const pat = PARITY[d[0]];
  let bits = "101";
  for (let i = 0; i < 6; i += 1) bits += (pat[i] === "L" ? L : G)[d[i + 1]];
  bits += "01010";
  for (let i = 7; i < 13; i += 1) bits += R[d[i]];
  bits += "101";
  const quiet = 12;
  const totalMods = bits.length + quiet * 2;
  const rawW = totalMods * scale;
  const rawH = height;
  const raw = new Uint8ClampedArray(rawW * rawH * 4).fill(255);
  for (let y = 16; y < rawH - 16; y += 1) {
    for (let m = 0; m < bits.length; m += 1) {
      if (bits[m] !== "1") continue;
      for (let sx = 0; sx < scale; sx += 1) {
        const x = (quiet + m) * scale + sx;
        const idx = (y * rawW + x) * 4;
        raw[idx] = 0; raw[idx + 1] = 0; raw[idx + 2] = 0;
      }
    }
  }
  if (!rotate90) return { data: raw, width: rawW, height: rawH };
  const rot = new Uint8ClampedArray(rawW * rawH * 4);
  for (let y = 0; y < rawH; y += 1) {
    for (let x = 0; x < rawW; x += 1) {
      const s = (y * rawW + x) * 4;
      const dx = y;
      const dy = rawW - 1 - x;
      const dIdx = (dy * rawH + dx) * 4;
      rot[dIdx] = raw[s]; rot[dIdx + 1] = raw[s + 1]; rot[dIdx + 2] = raw[s + 2]; rot[dIdx + 3] = 255;
    }
  }
  return { data: rot, width: rawH, height: rawW };
}

async function main() {
  // 1. No native window.BarcodeDetector -> ZXing fallback available & active
  assert.strictEqual(scanner.hasAvailableDetector({ window: {} }), true);
  assert.strictEqual(scanner.hasAvailableDetector({ window: {}, zxingLib: {} }), false);
  const zxingOnly = await scanner.createBarcodeDetector({ window: {} });
  assert.ok(zxingOnly);
  assert.strictEqual(zxingOnly.engine, "zxing");
  assert.strictEqual(zxingOnly.hasZXing, true);

  // 2. Decode QR code (GS1 Digital Link) + inverted QR code
  const writer = new ZXing.MultiFormatWriter();
  const qrPayload = "https://id.gs1.org/01/00000000000017";
  const qrMatrix = writer.encode(qrPayload, ZXing.BarcodeFormat.QR_CODE, 180, 180, new Map());
  const qrImg = bitMatrixToRgba(qrMatrix, 1, 20, false);
  const qrRes = await zxingOnly.detect(qrImg, { thorough: false });
  assert.strictEqual(qrRes.length, 1);
  assert.strictEqual(qrRes[0].rawValue, qrPayload);
  assert.strictEqual(scanner.parseScannedCode(qrRes[0].rawValue).id, "gtin:00000000000017");

  const qrInv = bitMatrixToRgba(qrMatrix, 1, 20, true);
  const qrInvRes = await zxingOnly.detect(qrInv, { thorough: true });
  assert.strictEqual(qrInvRes[0].rawValue, qrPayload);

  // 3. Decode synthetic GS1 EAN-13 horizontal and 90-degree rotated barcodes
  const eanImg = buildEan13Rgba("4901234567894", 3, 120, false);
  const eanRes = await zxingOnly.detect(eanImg, { thorough: false });
  assert.strictEqual(eanRes.length, 1);
  assert.strictEqual(eanRes[0].rawValue, "4901234567894");
  assert.strictEqual(eanRes[0].format, "ean_13");

  const eanRot = buildEan13Rgba("4901234567894", 3, 120, true);
  const eanRotRes = await zxingOnly.detect(eanRot, { thorough: true });
  assert.strictEqual(eanRotRes[0].rawValue, "4901234567894");

  // 4. Native BarcodeDetector reporting empty supported formats -> auto skip to ZXing
  class EmptyNativeDetector {
    static async getSupportedFormats() { return []; }
    async detect() { throw new Error("should not be called"); }
  }
  const skippedNative = await scanner.createBarcodeDetector({ window: { BarcodeDetector: EmptyNativeDetector } });
  assert.strictEqual(skippedNative.engine, "zxing");
  assert.strictEqual((await skippedNative.detect(eanImg))[0].rawValue, "4901234567894");

  // 5. Native BarcodeDetector failing at runtime -> seamless fallback to ZXing
  class FailingNativeDetector {
    static async getSupportedFormats() { return ["qr_code", "ean_13"]; }
    async detect() { throw new Error("NotSupportedError"); }
  }
  const runtimeFallback = await scanner.createBarcodeDetector({ window: { BarcodeDetector: FailingNativeDetector } });
  assert.strictEqual(runtimeFallback.engine, "native+zxing");
  assert.strictEqual(runtimeFallback.isNativeActive(), true);
  const fallbackHit = await runtimeFallback.detect(qrImg);
  assert.strictEqual(fallbackHit[0].rawValue, qrPayload);
  assert.strictEqual(runtimeFallback.isNativeActive(), false);

  // 6. Mock DOM controller: opening modal without BarcodeDetector must NOT warn unsupportedDetector, and camera tracks must stop on close
  const elements = {};
  const makeEl = (id) => {
    const el = {
      id,
      hidden: id === "scan-modal" || id === "scan-status" || id === "scan-result",
      dataset: {},
      textContent: "",
      innerHTML: "",
      srcObject: null,
      attributes: {},
      focused: false,
      addEventListener() {},
      setAttribute(k, v) { this.attributes[k] = v; },
      focus() { this.focused = true; },
      pause() {},
    };
    elements[id] = el;
    return el;
  };
  ["scan-modal","scan-status","scan-result","scan-camera-toggle","scan-manual-input","scan-video","scan-viewport"].forEach(makeEl);
  const mockDoc = {
    hidden: false,
    activeElement: null,
    querySelector(sel) { return elements[sel.replace(/^#/, "")] || null; },
    addEventListener() {},
  };
  let stoppedTracks = 0;
  const mockStream = {
    getTracks() {
      return [{ stop() { stoppedTracks += 1; } }, { stop() { stoppedTracks += 1; } }];
    },
  };
  const mockWin = { isSecureContext: true, addEventListener() {} };
  const mockNav = { mediaDevices: { async getUserMedia() { return mockStream; } } };
  const controller = scanner.createScannerController({
    document: mockDoc,
    window: mockWin,
    navigator: mockNav,
    t: (k) => k,
    getCatalog: () => [],
  });
  controller.openModal();
  assert.strictEqual(elements["scan-modal"].hidden, false);
  assert.strictEqual(elements["scan-status"].hidden, true);
  assert.strictEqual(elements["scan-status"].textContent, "");

  await controller.startCamera();
  assert.strictEqual(elements["scan-viewport"].dataset.active, "true");
  controller.closeModal();
  assert.strictEqual(stoppedTracks, 2);
  assert.strictEqual(elements["scan-video"].srcObject, null);
  assert.strictEqual(controller.getState().stream, null);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
"""
        res = subprocess.run(
            [
                node_bin,
                "-e",
                node_script,
                str(REPO_ROOT / "web" / "vendor" / "zxing.min.js"),
                str(REPO_ROOT / "web" / "scanner.js"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, f"Node ZXing fallback test failed: {res.stderr}\n{res.stdout}")

    def test_evidence_level_and_t_active_no_accuracy_misrepresentation_labels(self) -> None:
        locales_dir = REPO_ROOT / "web" / "locales"
        manifest = json.loads((locales_dir / "index.json").read_text(encoding="utf-8"))
        codes = [item["code"] for item in manifest["locales"]]
        forbidden_ui_patterns = (
            re.compile(r"已核验|已验证|已认证|多人印证|市场生效月|最近有效"),
            re.compile(r"\bverified\b|\bverifiziert\b|\bvérifié\b|\bverificado\b|\bverificato\b", re.IGNORECASE),
            re.compile(r"検証済|複数投稿印証|複数印証"),
        )
        for code in codes:
            loc = json.loads((locales_dir / f"{code}.json").read_text(encoding="utf-8"))
            self.assertNotIn("verified", loc["stats"], f"stats.verified must remain removed in {code}")
            self.assertNotIn("tActiveLabel", loc["detail"], f"Ambiguous detail.tActiveLabel should stay removed in {code}")
            for key in ("tActiveVintage", "tActiveReported", "tActiveVintageShort", "tActiveReportedShort"):
                self.assertIn(key, loc["detail"], f"Missing {key} in {code}")
            for key in ("footerDisclaimer", "limitationsLink", "reportErrataLink"):
                self.assertTrue(loc["app"].get(key), f"Missing app.{key} in {code}")

            checked_strings = [
                loc["header"]["legendToggle"],
                loc["header"]["legendAriaLabel"],
                loc["search"]["groupEvidence"],
                loc["search"]["tagEvidence"],
                loc["search"]["mixedEvidenceShort"],
                loc["search"]["mixedEvidenceTitle"],
                loc["detail"]["tActiveVintage"],
                loc["detail"]["tActiveReported"],
            ] + [entry["label"] for entry in loc["seals"].values()]
            for s in checked_strings:
                for pat in forbidden_ui_patterns:
                    self.assertIsNone(
                        pat.search(s),
                        f"Disallowed accuracy-claim wording {pat.pattern!r} in {code}: {s!r}",
                    )

        app_js = (REPO_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("formatTActiveText", app_js)
        self.assertNotIn("stats.verified", app_js)
        index_html = (REPO_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("docs/DATA-LIMITATIONS.md", index_html)
        self.assertIn("template=data_errata.yml", index_html)


if __name__ == "__main__":
    unittest.main()
