"""End-to-end CLI tests for OPF v0.2 (validate, normalize, parse-ingredients, submit, retrack, merge, lifecycle, pr)."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from opf.cli import main as cli_main
from opf.ids import product_dir_for_id
from opf.normalize import derive_editions_lifecycle, derive_evidence_level
from opf.validator import validate_products_root


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = cli_main(argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


def _make_draft(
    *,
    product_id: str = "gtin:00000000000109",
    sodium: str = "18",
    contributor: str = "github:alice",
    photo_seed: str = "photo-1",
    extra_photos: int = 0,
    extra_attrs: dict | None = None,
    track: str | None = None,
    track_definition: dict | None = None,
    aliases: list[str] | None = None,
) -> dict:
    sha1 = hashlib.sha256(photo_seed.encode("utf-8")).hexdigest()
    evidence: list[dict] = [
        {
            "type": "label_photo",
            "region": "nutrition_table",
            "cropped_sha256": sha1,
            "media_ref": f"opf-media://sha256/{sha1}",
            "contributor": contributor,
            "reported_at": "2026-02-14",
            "vintage_month": "2026-01",
        }
    ]
    for idx in range(extra_photos):
        sha_x = hashlib.sha256(f"{photo_seed}-extra-{idx}".encode("utf-8")).hexdigest()
        evidence.append(
            {
                "type": "label_photo",
                "region": "ingredients_box",
                "cropped_sha256": sha_x,
                "media_ref": f"opf-media://sha256/{sha_x}",
                "contributor": contributor,
                "reported_at": "2026-02-14",
                "vintage_month": "2026-01",
            }
        )

    attrs: dict = {
        "product_name": [{"lang": "zh-Hans", "text": "示例茉莉花茶"}],
        "brand": "示例茶饮",
        "ingredients_text": [
            {"lang": "zh-Hans", "text": "配料：水、茉莉花茶（绿茶茶坯）（≥4g/L）、维生素C、碳酸氢钠"}
        ],
    }
    if extra_attrs:
        attrs.update(copy.deepcopy(extra_attrs))

    draft: dict = {
        "id": product_id,
        "core": {
            "regulatory_profile": "CN/GB28050-2011",
            "net_content": [{"value": "900", "unit": "ml"}],
            "nutrition_declared": {
                "basis": {"value": "100", "unit": "ml"},
                "rows": [
                    {"nutrient": "energy", "value": "0", "unit": "kJ", "nrv_pct": "0"},
                    {"nutrient": "protein", "value": "0", "unit": "g", "nrv_pct": "0"},
                    {"nutrient": "fat_total", "value": "0", "unit": "g", "nrv_pct": "0"},
                    {"nutrient": "carbs_available", "value": "0", "unit": "g", "nrv_pct": "0"},
                    {"nutrient": "sodium", "value": sodium, "unit": "mg", "nrv_pct": "1"},
                ],
            },
            "allergens_declared": {"contains": [], "may_contain": []},
        },
        "attributes": attrs,
        "evidence": evidence,
    }
    if track is not None:
        draft["track"] = track
    if track_definition is not None:
        draft["track_definition"] = track_definition
    if aliases is not None:
        draft["aliases"] = aliases
    return draft


class TestCliV02Workflow(unittest.TestCase):
    def test_submit_enrichment_corroboration_and_conflict_abort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_root = tmp_path / "products"

            # 1. Initial submit: 2 photos without specimen_id/evidence_id + forbidden batch keys
            d1 = _make_draft(extra_photos=1, aliases=["示例大瓶茉莉花茶"])
            d1["attributes"]["production_date"] = "2026-01-15"
            d1["attributes"]["purchase_price"] = "5.5"
            p1 = tmp_path / "d1.json"
            p1.write_text(json.dumps(d1, ensure_ascii=False), encoding="utf-8")

            rc, out, err = _run_cli(["submit", "--input", str(p1), "--out-dir", str(products_root)])
            self.assertEqual(rc, 0, err)
            res1 = json.loads(out)
            self.assertEqual(res1["action"], "created_edition")
            self.assertEqual(res1["track"], "CN/default")
            self.assertEqual(res1["rev"], 1)
            self.assertEqual(
                sorted(res1["stripped_personal_batch_fields"]),
                ["production_date", "purchase_price"],
            )
            eid = res1["edition_id"]

            pdir = product_dir_for_id(products_root, d1["id"])
            ed_path = pdir / "editions" / f"{eid}.json"
            ed1 = json.loads(ed_path.read_text(encoding="utf-8"))
            self.assertEqual(len(ed1["evidence"]), 2)
            spec_ids = {ev.get("specimen_id") for ev in ed1["evidence"]}
            self.assertEqual(len(spec_ids), 1)
            self.assertIsNotNone(next(iter(spec_ids)))
            # Span-free semantic tree auto-parsed
            for node in ed1["core"]["ingredients_tree"][0]["nodes"]:
                self.assertNotIn("span", node)
            self.assertEqual(validate_products_root(products_root), [])

            # 2. Second submit: non-conflicting attribute enrichment -> rev 1 -> 2
            d2 = _make_draft(
                contributor="github:alice",
                photo_seed="photo-2",
                extra_attrs={
                    "product_name": [
                        {"lang": "zh-Hans", "text": "示例茉莉花茶"},
                        {"lang": "en", "text": "Sample Jasmine Tea"},
                    ],
                    "packaging_code": "SMP-900-A1",
                    "shelf_life": {"value": "9", "unit": "month"},
                    "parties": [
                        {
                            "role": "manufacturer",
                            "name": "示例饮品一厂",
                            "license": "SC10600000000001",
                        }
                    ],
                },
            )
            p2 = tmp_path / "d2.json"
            p2.write_text(json.dumps(d2, ensure_ascii=False), encoding="utf-8")
            rc2, out2, err2 = _run_cli(["submit", "--input", str(p2), "--out-dir", str(products_root)])
            self.assertEqual(rc2, 0, err2)
            res2 = json.loads(out2)
            self.assertEqual(res2["action"], "enriched_edition")
            self.assertEqual(res2["rev"], 2)
            ed2 = json.loads(ed_path.read_text(encoding="utf-8"))
            self.assertEqual(ed2["revisions"][-1]["kind"], "enrichment")
            self.assertEqual(validate_products_root(products_root), [])

            # 3. Third submit: Bob submits corroborating photo without changing attributes -> rev stays 2!
            d3 = _make_draft(contributor="github:bob", photo_seed="photo-bob")
            p3 = tmp_path / "d3.json"
            p3.write_text(json.dumps(d3, ensure_ascii=False), encoding="utf-8")
            rc3, out3, err3 = _run_cli(["submit", "--input", str(p3), "--out-dir", str(products_root)])
            self.assertEqual(rc3, 0, err3)
            res3 = json.loads(out3)
            self.assertEqual(res3["action"], "corroborated_edition")
            self.assertEqual(res3["rev"], 2)
            ed3 = json.loads(ed_path.read_text(encoding="utf-8"))
            self.assertEqual(len(ed3["revisions"]), 2)
            self.assertEqual(len(ed3["evidence"]), 4)
            self.assertEqual(derive_evidence_level(ed3), "corroborated")

            # 4. Fourth submit: identical photo & no new attrs -> unchanged, rev stays 2
            rc4, out4, err4 = _run_cli(["submit", "--input", str(p3), "--out-dir", str(products_root)])
            self.assertEqual(rc4, 0, err4)
            self.assertEqual(json.loads(out4)["action"], "unchanged")

            # 5. Conflicting SC license without intent flag -> exit 1 and disk untouched
            before_bytes = ed_path.read_bytes()
            d_conflict = _make_draft(
                contributor="github:carol",
                photo_seed="photo-carol",
                extra_attrs={
                    "packaging_code": "SMP-900-B2",
                    "parties": [
                        {
                            "role": "manufacturer",
                            "name": "示例饮品二厂",
                            "license": "SC10600000000002",
                        }
                    ],
                },
            )
            p_conf = tmp_path / "d_conf.json"
            p_conf.write_text(json.dumps(d_conflict, ensure_ascii=False), encoding="utf-8")
            rc_conf, _out_conf, err_conf = _run_cli(
                ["submit", "--input", str(p_conf), "--out-dir", str(products_root)]
            )
            self.assertEqual(rc_conf, 1)
            self.assertIn("--amend", err_conf)
            self.assertIn("--supersede", err_conf)
            self.assertIn("--new-variant", err_conf)
            self.assertEqual(ed_path.read_bytes(), before_bytes)

            # 6. Mutually exclusive intent flags -> exit 2
            rc_mut, _o, err_mut = _run_cli(
                [
                    "submit",
                    "--input",
                    str(p_conf),
                    "--out-dir",
                    str(products_root),
                    "--amend",
                    eid,
                    "--new-variant",
                ]
            )
            self.assertEqual(rc_mut, 2)
            self.assertIn("mutually exclusive", err_mut)

    def test_amend_errata_and_post_errata_collision_auto_merge_redirect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_root = tmp_path / "products"

            # Edition E1: sodium 18, packaging PKG-1
            d1 = _make_draft(sodium="18", photo_seed="e1", extra_attrs={"packaging_code": "PKG-1"})
            p1 = tmp_path / "d1.json"
            p1.write_text(json.dumps(d1, ensure_ascii=False), encoding="utf-8")
            rc1, out1, _ = _run_cli(["submit", "--input", str(p1), "--out-dir", str(products_root)])
            self.assertEqual(rc1, 0)
            e1_id = json.loads(out1)["edition_id"]

            # Edition E2: typo sodium 16, submitted concurrently as new variant
            d2 = _make_draft(sodium="16", contributor="github:bob", photo_seed="e2")
            p2 = tmp_path / "d2.json"
            p2.write_text(json.dumps(d2, ensure_ascii=False), encoding="utf-8")
            rc2, out2, _ = _run_cli(
                ["submit", "--new-variant", "--input", str(p2), "--out-dir", str(products_root)]
            )
            self.assertEqual(rc2, 0)
            e2_id = json.loads(out2)["edition_id"]

            # Standalone --amend on E2 changing 16 -> 17 (no collision) -> rev 2 errata
            d2_fix1 = _make_draft(sodium="17", contributor="github:bob", photo_seed="e2")
            p2_fix1 = tmp_path / "d2_fix1.json"
            p2_fix1.write_text(json.dumps(d2_fix1, ensure_ascii=False), encoding="utf-8")
            rc_f1, out_f1, err_f1 = _run_cli(
                [
                    "submit",
                    "--amend",
                    e2_id,
                    "--reason",
                    "Refine OCR reading 16->17",
                    "--input",
                    str(p2_fix1),
                    "--out-dir",
                    str(products_root),
                ]
            )
            self.assertEqual(rc_f1, 0, err_f1)
            res_f1 = json.loads(out_f1)
            self.assertEqual(res_f1["action"], "amended_edition")
            self.assertEqual(res_f1["rev"], 2)

            # Amending E2 to sodium=18 with conflicting packaging_code PKG-X must abort
            d2_bad_merge = _make_draft(
                sodium="18",
                contributor="github:bob",
                photo_seed="e2",
                extra_attrs={"packaging_code": "PKG-X"},
            )
            p2_bad = tmp_path / "d2_bad.json"
            p2_bad.write_text(json.dumps(d2_bad_merge, ensure_ascii=False), encoding="utf-8")
            rc_bm, _, err_bm = _run_cli(
                ["submit", "--amend", e2_id, "--input", str(p2_bad), "--out-dir", str(products_root)]
            )
            self.assertEqual(rc_bm, 1)
            self.assertIn("retrack", err_bm)

            # Amending E2 to sodium=18 without conflicting attrs auto-merges E2 -> E1 via EditionRedirect
            d2_fix2 = _make_draft(
                sodium="18",
                contributor="github:bob",
                photo_seed="e2",
                extra_attrs={"shelf_life": {"value": "9", "unit": "month"}},
            )
            p2_fix2 = tmp_path / "d2_fix2.json"
            p2_fix2.write_text(json.dumps(d2_fix2, ensure_ascii=False), encoding="utf-8")
            rc_m, out_m, err_m = _run_cli(
                [
                    "submit",
                    "--amend",
                    e2_id,
                    "--reason",
                    "Fix sodium typo 17->18 matching canonical edition",
                    "--input",
                    str(p2_fix2),
                    "--out-dir",
                    str(products_root),
                ]
            )
            self.assertEqual(rc_m, 0, err_m)
            res_m = json.loads(out_m)
            self.assertEqual(res_m["action"], "amended_and_merged")
            self.assertEqual(res_m["merged_into"], e1_id)

            pdir = product_dir_for_id(products_root, d1["id"])
            redir_doc = json.loads((pdir / "editions" / f"{e2_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(redir_doc["merged_into"], e1_id)
            e1_doc = json.loads((pdir / "editions" / f"{e1_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(derive_evidence_level(e1_doc), "corroborated")
            self.assertEqual(e1_doc["attributes"]["shelf_life"], {"value": "9", "unit": "month"})
            self.assertEqual(validate_products_root(products_root), [])

    def test_supersede_new_variant_and_retrack_split_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_root = tmp_path / "products"

            d1 = _make_draft(
                sodium="18",
                photo_seed="orig",
                extra_attrs={
                    "parties": [
                        {"role": "manufacturer", "name": "示例甲厂", "license": "SC111"}
                    ]
                },
            )
            p1 = tmp_path / "d1.json"
            p1.write_text(json.dumps(d1, ensure_ascii=False), encoding="utf-8")
            rc1, out1, _ = _run_cli(["submit", "--input", str(p1), "--out-dir", str(products_root)])
            self.assertEqual(rc1, 0)
            e1_id = json.loads(out1)["edition_id"]

            # Retrack E1 onto CN/plant:SC111 while registering discriminator in product.json
            pdir = product_dir_for_id(products_root, d1["id"])
            e1_doc = json.loads((pdir / "editions" / f"{e1_id}.json").read_text(encoding="utf-8"))
            ev_ref1 = e1_doc["evidence"][0]["evidence_id"]
            rc_rt, out_rt, err_rt = _run_cli(
                [
                    "retrack",
                    "--out-dir",
                    str(products_root),
                    "--id",
                    d1["id"],
                    "--edition",
                    e1_id,
                    "--track",
                    "CN/plant:SC111",
                    "--author",
                    "github:maintainer",
                    "--evidence-ref",
                    ev_ref1,
                    "--reason",
                    "Split East China single-plant print run",
                    "--discriminator-method",
                    "sc_license",
                    "--discriminator-field",
                    "attributes.parties[].license",
                    "--instruction",
                    "zh-Hans=生产商许可证为 SC111",
                    "--instruction",
                    "en=Manufacturer SC license is SC111",
                ]
            )
            self.assertEqual(rc_rt, 0, err_rt)
            self.assertEqual(json.loads(out_rt)["action"], "retracked")

            # Add concurrent South China plant variant on CN/plant:SC222 via --new-variant + track_definition
            d2 = _make_draft(
                sodium="22",
                contributor="github:bob",
                photo_seed="south",
                track="CN/plant:SC222",
                track_definition={
                    "discriminator": {
                        "method": "sc_license",
                        "field": "attributes.parties[].license",
                        "instructions": [{"lang": "zh-Hans", "text": "生产商许可证为 SC222"}],
                    }
                },
                extra_attrs={
                    "parties": [
                        {"role": "manufacturer", "name": "示例乙厂", "license": "SC222"}
                    ]
                },
            )
            p2 = tmp_path / "d2.json"
            p2.write_text(json.dumps(d2, ensure_ascii=False), encoding="utf-8")
            rc2, out2, err2 = _run_cli(
                ["submit", "--new-variant", "--input", str(p2), "--out-dir", str(products_root)]
            )
            self.assertEqual(rc2, 0, err2)
            e2_id = json.loads(out2)["edition_id"]

            # Supersede E1 on CN/plant:SC111 without passing --track (inherits E1 track)
            d3 = _make_draft(
                sodium="15",
                contributor="github:alice",
                photo_seed="e3",
                extra_attrs={
                    "parties": [
                        {"role": "manufacturer", "name": "示例甲厂", "license": "SC111"}
                    ]
                },
            )
            p3 = tmp_path / "d3.json"
            p3.write_text(json.dumps(d3, ensure_ascii=False), encoding="utf-8")
            rc3, out3, err3 = _run_cli(
                [
                    "submit",
                    "--supersede",
                    e1_id,
                    "--input",
                    str(p3),
                    "--out-dir",
                    str(products_root),
                ]
            )
            self.assertEqual(rc3, 0, err3)
            res3 = json.loads(out3)
            self.assertEqual(res3["action"], "superseded_edition")
            self.assertEqual(res3["track"], "CN/plant:SC111")
            e3_id = res3["edition_id"]

            editions = [
                json.loads(f.read_text(encoding="utf-8"))
                for f in sorted((pdir / "editions").glob("*.json"))
            ]
            derived = derive_editions_lifecycle(editions)
            self.assertEqual(derived[e1_id]["status"], "superseded")
            self.assertEqual(derived[e2_id]["status"], "active")
            self.assertEqual(derived[e3_id]["status"], "active")
            self.assertEqual(validate_products_root(products_root), [])

    def test_merge_lifecycle_validate_orphan_normalize_parse_and_pr_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_root = tmp_path / "products"

            # Allow empty on clean directory
            empty_dir = tmp_path / "empty_products"
            empty_dir.mkdir()
            rc_empty, _, _ = _run_cli(["validate", "--allow-empty", str(empty_dir)])
            self.assertEqual(rc_empty, 0)

            # Submit two concurrent editions with identical core on distinct tracks, then merge via `opf merge`
            d1 = _make_draft(photo_seed="m1")
            p1 = tmp_path / "m1.json"
            p1.write_text(json.dumps(d1, ensure_ascii=False), encoding="utf-8")
            rc1, out1, _ = _run_cli(["submit", "--input", str(p1), "--out-dir", str(products_root)])
            self.assertEqual(rc1, 0)
            e1_id = json.loads(out1)["edition_id"]

            d2 = _make_draft(
                contributor="github:bob",
                photo_seed="m2",
                track="CN/code:B",
                track_definition={
                    "discriminator": {
                        "method": "channel_mark",
                        "instructions": [{"lang": "zh-Hans", "text": "渠道标记 B"}],
                    }
                },
            )
            p2 = tmp_path / "m2.json"
            p2.write_text(json.dumps(d2, ensure_ascii=False), encoding="utf-8")
            rc2, out2, err2 = _run_cli(
                ["submit", "--new-variant", "--input", str(p2), "--out-dir", str(products_root)]
            )
            self.assertEqual(rc2, 0, err2)
            e2_id = json.loads(out2)["edition_id"]

            # `opf merge` absorbs e2 -> e1 without incrementing e1's rev (no new attributes)
            rc_mrg, out_mrg, err_mrg = _run_cli(
                [
                    "merge",
                    "--out-dir",
                    str(products_root),
                    "--id",
                    d1["id"],
                    "--source",
                    e2_id,
                    "--into",
                    e1_id,
                    "--reason",
                    "Duplicate concurrent PR",
                ]
            )
            self.assertEqual(rc_mrg, 0, err_mrg)
            self.assertEqual(json.loads(out_mrg)["rev"], 1)

            # `opf lifecycle --state discontinued`
            pdir = product_dir_for_id(products_root, d1["id"])
            e1_path = pdir / "editions" / f"{e1_id}.json"
            e1_doc = json.loads(e1_path.read_text(encoding="utf-8"))
            ev_ref = e1_doc["evidence"][0]["evidence_id"]
            rc_lc, out_lc, err_lc = _run_cli(
                [
                    "lifecycle",
                    "--out-dir",
                    str(products_root),
                    "--id",
                    d1["id"],
                    "--edition",
                    e1_id,
                    "--author",
                    "github:maintainer",
                    "--reason",
                    "Discontinued by manufacturer",
                    "--evidence-ref",
                    ev_ref,
                    "--state",
                    "discontinued",
                    "--effective-month",
                    "2026-10",
                ]
            )
            self.assertEqual(rc_lc, 0, err_lc)
            self.assertEqual(json.loads(out_lc)["rev"], 2)

            # `opf normalize --in-place --parse-ingredients`
            rc_norm, _, err_norm = _run_cli(
                ["normalize", "--in-place", "--parse-ingredients", str(e1_path)]
            )
            self.assertEqual(rc_norm, 0, err_norm)

            # `opf lifecycle --state retracted` on another variant clears supersedes and validates
            d_bad = _make_draft(sodium="88", contributor="github:carol", photo_seed="bad-ret")
            p_bad = tmp_path / "bad_ret.json"
            p_bad.write_text(json.dumps(d_bad, ensure_ascii=False), encoding="utf-8")
            rc_sb, out_sb, err_sb = _run_cli(
                ["submit", "--supersede", e1_id, "--input", str(p_bad), "--out-dir", str(products_root)]
            )
            self.assertEqual(rc_sb, 0, err_sb)
            e_ret_id = json.loads(out_sb)["edition_id"]
            e_ret_doc = json.loads((pdir / "editions" / f"{e_ret_id}.json").read_text(encoding="utf-8"))
            rc_ret_lc, out_ret_lc, err_ret_lc = _run_cli(
                [
                    "lifecycle",
                    "--out-dir",
                    str(products_root),
                    "--id",
                    d1["id"],
                    "--edition",
                    e_ret_id,
                    "--author",
                    "github:maintainer",
                    "--reason",
                    "Erroneous submission retracted",
                    "--evidence-ref",
                    e_ret_doc["evidence"][0]["evidence_id"],
                    "--state",
                    "retracted",
                ]
            )
            self.assertEqual(rc_ret_lc, 0, err_ret_lc)
            ret_lc_res = json.loads(out_ret_lc)
            self.assertEqual(ret_lc_res["lifecycle"]["state"], "retracted")
            self.assertEqual(ret_lc_res["supersedes"], [])

            # `opf validate` succeeds on valid product_dir and products_root
            rc_val_ok, out_val_ok, err_val_ok = _run_cli(["validate", "--json", str(products_root)])
            self.assertEqual(rc_val_ok, 0, err_val_ok)
            self.assertTrue(json.loads(out_val_ok)["valid"])

            # Orphan JSON inside products_root must be intercepted by `opf validate`
            stray = products_root / "gtin" / "000" / "000" / "00000000000109.json"
            stray.write_text("{}", encoding="utf-8")
            rc_orphan, _, err_orphan = _run_cli(["validate", str(products_root)])
            self.assertEqual(rc_orphan, 1)
            self.assertIn("orphan JSON", err_orphan)
            stray.unlink()

            # `opf parse-ingredients` default (span-free) vs --with-spans
            rc_pi, out_pi, _ = _run_cli(
                ["parse-ingredients", "配料：水、白砂糖"]
            )
            self.assertEqual(rc_pi, 0)
            self.assertNotIn("span", json.loads(out_pi)["nodes"][0])
            rc_pis, out_pis, _ = _run_cli(
                ["parse-ingredients", "--with-spans", "配料：水、白砂糖"]
            )
            self.assertEqual(rc_pis, 0)
            self.assertEqual(json.loads(out_pis)["nodes"][0]["span"], [3, 4])

            # `opf pr --dry-run` on a fresh temp git repo
            data_repo = tmp_path / "opf-data"
            data_repo.mkdir()
            subprocess.run(
                ["git", "-C", str(data_repo), "init", "-b", "main"],
                check=True,
                capture_output=True,
            )
            rc_pr, out_pr, err_pr = _run_cli(
                ["pr", "--input", str(p1), "--data-repo", str(data_repo), "--dry-run"]
            )
            self.assertEqual(rc_pr, 0, err_pr)
            pr_plan = json.loads(out_pr)
            self.assertEqual(pr_plan["action"], "created_edition")
            self.assertIn("gtin/000/000/00000000000109", pr_plan["product_dir"])
            self.assertTrue(
                (data_repo / "products" / "gtin" / "000" / "000" / "00000000000109" / "product.json").is_file()
            )
            self.assertEqual(validate_products_root(data_repo / "products"), [])


if __name__ == "__main__":
    unittest.main()
