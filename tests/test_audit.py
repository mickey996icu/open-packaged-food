"""Tests for OPF deep audit engine (`opf audit`), PR blocking, and path hygiene."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from opf.audit import audit_edition_doc, audit_products_root
from opf.cli import main as cli_main
from opf.ingredients import parse_ingredients_semantic
from opf.normalize import normalize_edition
from opf.resources import REPO_ROOT


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = cli_main(argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


def _make_minimal_webp(width: int, height: int, pad_bytes: int = 100) -> tuple[bytes, str]:
    payload = b"\x2f" + struct.pack("<I", (width - 1) | ((height - 1) << 14)) + (b"\x00" * pad_bytes)
    chunk_body = payload + (b"\x00" if (len(payload) & 1) else b"")
    vp8l = b"VP8L" + struct.pack("<I", len(payload)) + chunk_body
    raw = b"RIFF" + struct.pack("<I", 4 + len(vp8l)) + b"WEBP" + vp8l
    return raw, hashlib.sha256(raw).hexdigest()


def _write_webp(media_root: Path, raw: bytes, sha: str) -> Path:
    dest = media_root / "media" / sha[0:2] / sha[2:4] / f"{sha}.webp"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return dest


def _sample_edition(
    *,
    pid: str = "gtin:06970674931280",
    eid: str = "01M88Q1J2ZNAZ49Q7G0HWWRPFD",
    profile: str = "CN/GB28050-2011",
    track: str = "CN/default",
    rows: list[dict[str, Any]] | None = None,
    ing_text: str = "水、白砂糖、食用盐",
    parties: list[dict[str, Any]] | None = None,
    with_photo: bool = True,
    photo_sha: str = "a" * 64,
    photo_region: str = "full_back_label",
) -> dict[str, Any]:
    if rows is None:
        rows = [
            {"nutrient": "energy", "value": "120", "unit": "kJ", "nrv_pct": "1"},
            {"nutrient": "protein", "value": "0", "unit": "g", "nrv_pct": "0"},
            {"nutrient": "fat_total", "value": "0", "unit": "g", "nrv_pct": "0"},
            {"nutrient": "carbs_available", "value": "7", "unit": "g", "nrv_pct": "2"},
            {"nutrient": "sodium", "value": "10", "unit": "mg", "nrv_pct": "1"},
        ]
    if parties is None:
        parties = [
            {
                "role": "manufacturer",
                "name": "示例食品有限公司",
                "address": "广东省广州市南沙区榄核镇榄北路110号",
                "license": "SC11144011500492",
            }
        ]
    ev: list[dict[str, Any]] = []
    if with_photo:
        ev.append(
            {
                "evidence_id": f"sha256:{photo_sha}",
                "type": "label_photo",
                "provenance": "external_contributor",
                "region": photo_region,
                "cropped_sha256": photo_sha,
                "media_ref": f"opf-media://sha256/{photo_sha}",
                "contributor": "github:tester",
                "reported_at": "2026-11-01",
                "vintage_month": "2026-10",
            }
        )
    else:
        ev.append(
            {
                "evidence_id": "ev:01JTEST0000000000000000001",
                "type": "community_report",
                "provenance": "external_contributor",
                "contributor": "github:tester",
                "reported_at": "2026-11-01",
            }
        )
    return {
        "opf_schema": "0.3",
        "id": pid,
        "edition_id": eid,
        "rev": 1,
        "track": track,
        "supersedes": [],
        "core": {
            "regulatory_profile": profile,
            "net_content": [{"value": "500", "unit": "ml"}],
            "nutrition_declared": {"basis": {"value": "100", "unit": "ml"}, "rows": rows},
            "ingredients_tree": [
                {"lang": "zh-Hans", "nodes": parse_ingredients_semantic(ing_text, lang="zh-Hans", profile_id=profile)}
            ],
        },
        "attributes": {
            "product_name": [{"lang": "zh-Hans", "text": "测试饮品"}],
            "brand": "测试品牌",
            "ingredients_text": [{"lang": "zh-Hans", "text": ing_text}],
            "parties": parties,
        },
        "evidence": ev,
        "revisions": [
            {
                "rev": 1,
                "kind": "initial",
                "created_at": "2026-11-01T00:00:00Z",
                "author": "github:tester",
                "provenance": "external_contributor",
                "evidence_refs": [ev[0]["evidence_id"]],
                "patch": [],
            }
        ],
    }


def _codes(findings: list[Any], severity: str | None = None) -> list[str]:
    return [f.code for f in findings if severity is None or f.severity == severity]


class TestAuditEngine(unittest.TestCase):
    def test_pure_stdlib_audit_modules_never_import_pillow(self) -> None:
        code = (
            "import sys, opf.audit; "
            "assert 'PIL' not in sys.modules, f'Unexpected PIL import: {list(sys.modules)}'"
        )
        res = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15)
        self.assertEqual(res.returncode, 0, res.stderr or res.stdout)

    def test_error_sc_format_province_mismatch_and_import_exemption(self) -> None:
        # Foreign import registry number CJPN... is exempted
        imp_doc = _sample_edition(
            parties=[{"role": "manufacturer", "name": "Japan Co", "address": "東京都", "license": "CJPN24052202230043"}],
        )
        imp_doc["attributes"]["origin"] = {"country": "JP", "raw_text": "日本"}
        self.assertEqual(_codes(audit_edition_doc(imp_doc), "ERROR"), [])

        # Bad SC format -> ERROR
        bad_sc = _sample_edition(
            parties=[{"role": "manufacturer", "name": "厂", "address": "广东省广州市天河区1号", "license": "SC1114401"}]
        )
        self.assertIn("INVALID_SC_FORMAT", _codes(audit_edition_doc(bad_sc), "ERROR"))

        # Province mismatch: SC11144... (广东) with 江苏省... -> ERROR
        mismatch = _sample_edition(
            parties=[{"role": "manufacturer", "name": "厂", "address": "江苏省南京市鼓楼区1号", "license": "SC11144011500492"}]
        )
        self.assertIn("SC_PROVINCE_MISMATCH", _codes(audit_edition_doc(mismatch), "ERROR"))

        # Street name "北京东路" must NOT trigger false province mismatch against 44 (广东)
        street_ok = _sample_edition(
            parties=[{"role": "manufacturer", "name": "厂", "address": "北京东路18号", "license": "SC11144011500492"}]
        )
        self.assertNotIn("SC_PROVINCE_MISMATCH", _codes(audit_edition_doc(street_ok), "ERROR"))

    def test_error_mandatory_nutrients_subsets_and_zero_energy(self) -> None:
        # 2011 missing sodium -> ERROR
        miss_2011 = _sample_edition(
            profile="CN/GB28050-2011",
            rows=[
                {"nutrient": "energy", "value": "100", "unit": "kJ"},
                {"nutrient": "protein", "value": "1", "unit": "g"},
                {"nutrient": "fat_total", "value": "1", "unit": "g"},
                {"nutrient": "carbs_available", "value": "3", "unit": "g"},
            ],
        )
        self.assertIn("MISSING_MANDATORY_NUTRIENTS", _codes(audit_edition_doc(miss_2011), "ERROR"))

        # 2025 missing fat_saturated and sugars_total -> ERROR
        miss_2025 = _sample_edition(profile="CN/GB28050-2025")
        self.assertIn("MISSING_MANDATORY_NUTRIENTS", _codes(audit_edition_doc(miss_2025), "ERROR"))

        # Subset > total -> ERROR
        bad_subset = _sample_edition(
            profile="CN/GB28050-2025",
            rows=[
                {"nutrient": "energy", "value": "500", "unit": "kJ"},
                {"nutrient": "protein", "value": "2", "unit": "g"},
                {"nutrient": "fat_total", "value": "1", "unit": "g"},
                {"nutrient": "fat_saturated", "value": "2", "unit": "g"},
                {"nutrient": "carbs_available", "value": "3", "unit": "g"},
                {"nutrient": "sugars_total", "value": "5", "unit": "g"},
                {"nutrient": "sodium", "value": "50", "unit": "mg"},
            ],
            ing_text="白砂糖、水",
        )
        errs = _codes(audit_edition_doc(bad_subset), "ERROR")
        self.assertEqual(errs.count("NUTRIENT_SUBSET_EXCEEDS_TOTAL"), 2)

        # Regulatory upper bound `< 0.5` when total is `0` must NOT trigger false positive
        upper_bound_ok = _sample_edition(
            profile="CN/GB28050-2025",
            rows=[
                {"nutrient": "energy", "value": "0", "unit": "kJ"},
                {"nutrient": "protein", "value": "0", "unit": "g"},
                {"nutrient": "fat_total", "value": "0", "unit": "g"},
                {"nutrient": "fat_saturated", "qualifier": "<", "value": "0.5", "unit": "g"},
                {"nutrient": "carbs_available", "value": "0", "unit": "g"},
                {"nutrient": "sugars_total", "qualifier": "<", "value": "0.5", "unit": "g"},
                {"nutrient": "sodium", "value": "0", "unit": "mg"},
            ],
        )
        self.assertEqual(_codes(audit_edition_doc(upper_bound_ok), "ERROR"), [])

        # Zero energy with real macros -> ERROR
        zero_e = _sample_edition(
            rows=[
                {"nutrient": "energy", "value": "0", "unit": "kJ"},
                {"nutrient": "protein", "value": "3", "unit": "g"},
                {"nutrient": "fat_total", "value": "2", "unit": "g"},
                {"nutrient": "carbs_available", "value": "10", "unit": "g"},
                {"nutrient": "sodium", "value": "20", "unit": "mg"},
            ],
        )
        self.assertIn("ZERO_ENERGY_WITH_MACROS", _codes(audit_edition_doc(zero_e), "ERROR"))

    def test_warn_no_photo_require_photo_strict_and_sc_unknown_province(self) -> None:
        # SC10600... (unknown province 00) + no photo -> WARN (not ERROR)
        doc = _sample_edition(
            parties=[{"role": "manufacturer", "name": "示例厂", "license": "SC10600000000001"}],
            with_photo=False,
        )
        findings = audit_edition_doc(doc, require_photo=False)
        self.assertEqual(_codes(findings, "ERROR"), [])
        warns = _codes(findings, "WARN")
        self.assertIn("SC_UNKNOWN_PROVINCE", warns)
        self.assertIn("NO_LABEL_PHOTO", warns)
        self.assertIn("CN_MANUFACTURER_MISSING_ADDRESS", warns)

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "draft.json"
            p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            rc_default, _, _ = _run_cli(["audit", str(p)])
            self.assertEqual(rc_default, 0)
            rc_strict, _, _ = _run_cli(["audit", "--strict", str(p)])
            self.assertEqual(rc_strict, 1)
            rc_req_photo, _, err_rp = _run_cli(["audit", "--require-photo", str(p)])
            self.assertEqual(rc_req_photo, 1)
            self.assertIn("NO_LABEL_PHOTO", err_rp)

    def test_warn_truncated_address_and_zone_exemptions(self) -> None:
        trunc = _sample_edition(
            parties=[{"role": "manufacturer", "name": "厂", "address": "江苏省射阳县", "license": "SC11132092400001"}]
        )
        self.assertIn("CN_MANUFACTURER_TRUNCATED_ADDRESS", _codes(audit_edition_doc(trunc), "WARN"))

        dev_zone = _sample_edition(
            parties=[{"role": "manufacturer", "name": "厂", "address": "湖南省长沙市望城经济开发区", "license": "SC10543011200116"}]
        )
        self.assertNotIn("CN_MANUFACTURER_TRUNCATED_ADDRESS", _codes(audit_edition_doc(dev_zone), "WARN"))

    def test_warn_high_sugar_masking_allergens_modifiers_and_opf_id(self) -> None:
        # High sugar masked against '番茄味调味料' and 'DL-苹果酸' -> triggers WARN
        no_sugar = _sample_edition(
            profile="CN/GB28050-2025",
            rows=[
                {"nutrient": "energy", "value": "1900", "unit": "kJ"},
                {"nutrient": "protein", "value": "6", "unit": "g"},
                {"nutrient": "fat_total", "value": "20", "unit": "g"},
                {"nutrient": "fat_saturated", "value": "8", "unit": "g"},
                {"nutrient": "carbs_available", "value": "60", "unit": "g"},
                {"nutrient": "sugars_total", "value": "8.3", "unit": "g"},
                {"nutrient": "sodium", "value": "400", "unit": "mg"},
            ],
            ing_text="马铃薯粉、植物油、番茄味调味料(食用盐、DL-苹果酸、辣椒红)",
        )
        self.assertIn("HIGH_SUGAR_NO_SUGAR_SOURCE", _codes(audit_edition_doc(no_sugar), "WARN"))

        # Compound seasoning containing real sugar inside parentheses -> NO WARN
        has_sugar = copy.deepcopy(no_sugar)
        has_sugar["attributes"]["ingredients_text"][0]["text"] = "马铃薯粉、番茄味调味料(食用盐、白砂糖、DL-苹果酸)"
        self.assertNotIn("HIGH_SUGAR_NO_SUGAR_SOURCE", _codes(audit_edition_doc(has_sugar), "WARN"))

        # Allergen declared in core but missing in ingredients_tree
        alg_doc = _sample_edition(ing_text="大米、食用盐")
        alg_doc["core"]["allergens_declared"] = {"contains": ["milk"]}
        self.assertIn("DECLARED_ALLERGEN_UNMATCHED_IN_INGREDIENTS", _codes(audit_edition_doc(alg_doc), "WARN"))

        # Nested allergen inside compound ingredient parentheses -> NO WARN
        alg_ok = _sample_edition(ing_text="小麦粉、调味料（乳粉）")
        alg_ok["core"]["ingredients_tree"] = [
            {"lang": "zh-Hans", "nodes": [{"name": "小麦粉", "allergens": ["gluten_cereals"]},
                                          {"name": "调味料", "children": [{"name": "乳粉", "allergens": ["milk"]}]}]}
        ]
        alg_ok["core"]["allergens_declared"] = {"contains": ["milk"]}
        self.assertNotIn("DECLARED_ALLERGEN_UNMATCHED_IN_INGREDIENTS", _codes(audit_edition_doc(alg_ok), "WARN"))

        # Special indicator modifiers (in core.special_indicators) + legacy attributes placement error
        ind_bad = _sample_edition()
        ind_bad["core"]["special_indicators"] = [{"name": "新西兰进口乳粉含量", "value": "30", "unit": "%"}]
        self.assertIn("UNSUPPORTED_INDICATOR_MODIFIER", _codes(audit_edition_doc(ind_bad), "WARN"))
        ind_ok = _sample_edition(ing_text="新西兰进口生牛乳、白砂糖")
        ind_ok["core"]["special_indicators"] = [{"name": "新西兰进口生牛乳含量", "value": "80", "unit": "%"}]
        self.assertNotIn("UNSUPPORTED_INDICATOR_MODIFIER", _codes(audit_edition_doc(ind_ok), "WARN"))
        ind_legacy = _sample_edition()
        ind_legacy["attributes"]["special_indicators"] = [{"name": "茶多酚", "qualifier": ">=", "value": "180", "unit": "mg/kg"}]
        self.assertIn("LEGACY_ATTRIBUTES_SPECIAL_INDICATORS", _codes(audit_edition_doc(ind_legacy), "ERROR"))

        # Synthetic opf: ID without proof -> WARN
        opf_doc = _sample_edition(pid="opf:demo/cake/100g", photo_region="nutrition_table")
        self.assertIn("SYNTHETIC_OPF_ID_WITHOUT_PROOF", _codes(audit_edition_doc(opf_doc), "WARN"))

    def test_warn_low_res_blurry_crop_and_duplicate_pkg_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            media_root = tmp_path / "opf-media"
            blur_raw, blur_sha = _make_minimal_webp(172, 461, pad_bytes=3000)
            strip_raw, strip_sha = _make_minimal_webp(307, 31, pad_bytes=1500)
            tall_raw, tall_sha = _make_minimal_webp(140, 280, pad_bytes=1500)
            _write_webp(media_root, blur_raw, blur_sha)
            _write_webp(media_root, strip_raw, strip_sha)
            _write_webp(media_root, tall_raw, tall_sha)

            self.assertIn("LOW_RES_BLURRY_CROP", _codes(audit_edition_doc(_sample_edition(photo_sha=blur_sha), media_root=media_root), "WARN"))
            self.assertNotIn("LOW_RES_BLURRY_CROP", _codes(audit_edition_doc(_sample_edition(photo_sha=strip_sha), media_root=media_root), "WARN"))
            self.assertNotIn("LOW_RES_BLURRY_CROP", _codes(audit_edition_doc(_sample_edition(photo_sha=tall_sha), media_root=media_root), "WARN"))

            # Cross-product duplicate packaging_code + nutrition
            products_dir = tmp_path / "products"
            for gt in ("gtin:06970674931280", "gtin:06970674931297"):
                p14 = gt[5:]
                pdir = products_dir / "gtin" / p14[1:4] / p14[4:7] / p14
                (pdir / "editions").mkdir(parents=True)
                (pdir / "product.json").write_text(json.dumps({"opf_schema": "0.3", "id": gt}), encoding="utf-8")
                ed = _sample_edition(pid=gt)
                ed["attributes"]["packaging_code"] = "S-D-002"
                (pdir / "editions" / f"{ed['edition_id']}.json").write_text(json.dumps(ed), encoding="utf-8")

            dup_findings = audit_products_root(products_dir)
            self.assertEqual(_codes(dup_findings, "WARN").count("DUPLICATE_PACKAGING_CODE_AND_NUTRITION"), 2)

    def test_info_diagnostics_and_opf_pr_audit_blocking(self) -> None:
        doc = _sample_edition(track="JP/default", photo_region="barcode_net_content")
        doc["attributes"]["claims_text"] = ["0糖"]
        doc["attributes"]["origin"] = {"country": "JP", "raw_text": "日本"}
        doc["attributes"]["product_name"] = [{"lang": "en", "text": "Shizouka Soda"}]
        doc["core"]["ingredients_tree"] = [
            {"lang": "zh-Hans", "nodes": [{"name": "神秘增稠剂X", "is_additive": True}]}
        ]
        infos = _codes(audit_edition_doc(doc), "INFO")
        for expected in ("VERIFY_CLAIMS_VERBATIM", "VERIFY_REGION_SEMANTICS", "FOREIGN_TRACK_MIXED_SCRIPT_CHECK", "UNMAPPED_ADDITIVE_CANDIDATES"):
            self.assertIn(expected, infos)

        # `opf pr --dry-run` blocks on audit ERROR (e.g. SC province mismatch)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_repo = tmp_path / "opf-data"
            (data_repo / "products").mkdir(parents=True)
            draft_path = tmp_path / "bad_draft.json"
            bad_draft = {
                "id": "gtin:00000000000017",
                "core": {
                    "regulatory_profile": "CN/GB28050-2011",
                    "net_content": [{"value": "500", "unit": "ml"}],
                    "nutrition_declared": {
                        "basis": {"value": "100", "unit": "ml"},
                        "rows": [
                            {"nutrient": "energy", "value": "0", "unit": "kJ"},
                            {"nutrient": "protein", "value": "0", "unit": "g"},
                            {"nutrient": "fat_total", "value": "0", "unit": "g"},
                            {"nutrient": "carbs_available", "value": "0", "unit": "g"},
                            {"nutrient": "sodium", "value": "0", "unit": "mg"},
                        ],
                    },
                },
                "attributes": {
                    "product_name": [{"lang": "zh-Hans", "text": "错误SC饮品"}],
                    "brand": "测试",
                    "ingredients_text": [{"lang": "zh-Hans", "text": "水"}],
                    "parties": [{"role": "manufacturer", "name": "江苏厂", "address": "江苏省南京市A路1号", "license": "SC11144011500492"}],
                },
                "evidence": [{"type": "community_report", "contributor": "github:t", "reported_at": "2026-11-01"}],
            }
            draft_path.write_text(json.dumps(bad_draft, ensure_ascii=False), encoding="utf-8")
            rc_pr, _, err_pr = _run_cli(["pr", "--input", str(draft_path), "--data-repo", str(data_repo), "--dry-run"])
            self.assertEqual(rc_pr, 1)
            self.assertIn("SC_PROVINCE_MISMATCH", err_pr)

    def test_repo_contains_no_private_host_paths_or_ips(self) -> None:
        forbidden = (
            "/" + "Users/",
            "/" + "home/" + "antigravity",
            "192." + "168.",
        )
        scan_exts = {".py", ".md", ".json", ".js", ".html", ".css", ".yml", ".yaml", ".toml"}
        leaks: list[str] = []
        for path in sorted(REPO_ROOT.rglob("*")):
            if not path.is_file() or any(part in {".git", "__pycache__", ".DS_Store"} for part in path.parts):
                continue
            if path.suffix.lower() not in scan_exts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pat in forbidden:
                if pat in text:
                    leaks.append(f"{path.relative_to(REPO_ROOT)} contains {pat!r}")
        self.assertEqual(leaks, [])


if __name__ == "__main__":
    unittest.main()
