"""End-to-end static API v1 builder tests for OPF v0.2 (single, uniform, divergent, inactive, indices)."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from opf.builder import build_static_api
from opf.cli import main as cli_main
from opf.ids import product_dir_for_id
from opf.ingredients import parse_ingredients_semantic
from opf.normalize import normalize_edition
from opf.validator import load_json_schema, validate_against_json_schema


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_edition(
    *,
    pid: str,
    edition_id: str,
    track: str = "CN/default",
    brand: str = "示例茶饮",
    name: str = "示例茉莉花茶",
    raw_ing: str = "配料：水、茉莉花茶（绿茶茶坯）（≥4g/L）、维生素C、碳酸氢钠",
    energy_kj: str = "0",
    energy_kcal: str | None = None,
    sodium: str = "18",
    calcium: str | None = None,
    net_content: list[dict] | None = None,
    allergens_declared: dict | None = None,
    origin: dict | None = None,
    parties: list[dict] | None = None,
    product_standard: list[str] | None = None,
    packaging_code: str | None = None,
    vintage_month: str = "2026-01",
    contributors: list[str] | None = None,
    supersedes: list[str] | None = None,
    lifecycle: dict | None = None,
) -> dict:
    contribs = contributors if contributors is not None else ["github:alice"]
    evidence: list[dict] = []
    if contribs:
        for idx, contrib in enumerate(contribs):
            sha = hashlib.sha256(f"{edition_id}-{contrib}-{idx}".encode("utf-8")).hexdigest()
            evidence.append(
                {
                    "evidence_id": f"sha256:{sha}",
                    "type": "label_photo",
                    "provenance": "external_contributor",
                    "region": "nutrition_table",
                    "cropped_sha256": sha,
                    "media_ref": f"opf-media://sha256/{sha}",
                    "contributor": contrib,
                    "reported_at": "2026-02-14",
                    "vintage_month": vintage_month,
                }
            )
    else:
        evidence.append(
            {
                "evidence_id": f"ev:{edition_id}",
                "type": "community_report",
                "provenance": "external_contributor",
                "contributor": "github:anon",
                "reported_at": "2026-02-14",
                "vintage_month": vintage_month,
            }
        )

    rows: list[dict] = [{"nutrient": "energy", "value": energy_kj, "unit": "kJ"}]
    if energy_kcal is not None:
        rows.append({"nutrient": "energy", "value": energy_kcal, "unit": "kcal"})
    rows.extend(
        [
            {"nutrient": "protein", "value": "3.2", "unit": "g"},
            {"nutrient": "fat_total", "value": "3.8", "unit": "g"},
            {"nutrient": "carbs_available", "value": "4.8", "unit": "g"},
            {"nutrient": "sodium", "value": sodium, "unit": "mg"},
        ]
    )
    if calcium is not None:
        rows.append({"nutrient": "calcium", "value": calcium, "unit": "mg"})

    attrs: dict = {
        "product_name": [{"lang": "zh-Hans", "text": name}],
        "brand": brand,
        "ingredients_text": [{"lang": "zh-Hans", "text": raw_ing}],
    }
    if origin is not None:
        attrs["origin"] = origin
    if parties is not None:
        attrs["parties"] = parties
    if product_standard is not None:
        attrs["product_standard"] = product_standard
    if packaging_code is not None:
        attrs["packaging_code"] = packaging_code

    ed: dict = {
        "opf_schema": "0.2",
        "id": pid,
        "edition_id": edition_id,
        "rev": 1,
        "track": track,
        "supersedes": supersedes or [],
        "core": {
            "regulatory_profile": "CN/GB28050-2011",
            "net_content": net_content or [{"value": "250", "unit": "ml"}],
            "nutrition_declared": {
                "basis": {"value": "100", "unit": "ml"},
                "rows": rows,
            },
            "ingredients_tree": [
                {
                    "lang": "zh-Hans",
                    "nodes": parse_ingredients_semantic(
                        raw_ing, lang="zh-Hans", profile_id="CN/GB28050-2011"
                    ),
                }
            ],
            "allergens_declared": allergens_declared or {"contains": [], "may_contain": []},
        },
        "attributes": attrs,
        "evidence": evidence,
        "revisions": [
            {
                "rev": 1,
                "kind": "initial",
                "created_at": "2026-02-14T10:15:00Z",
                "author": contribs[0] if contribs else "github:anon",
                "provenance": "external_contributor",
                "evidence_refs": [evidence[0]["evidence_id"]],
                "patch": [],
            }
        ],
    }
    if lifecycle is not None:
        lc = copy.deepcopy(lifecycle)
        lc.setdefault("evidence_refs", [evidence[0]["evidence_id"]])
        ed["lifecycle"] = lc
    normalize_edition(ed)
    return ed


class TestBuilderV02(unittest.TestCase):
    def test_empty_directory_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_dir = tmp_path / "products"
            products_dir.mkdir()
            site_dir = tmp_path / "site"

            meta = build_static_api(products_dir, site_dir)
            self.assertEqual(meta["opf_schema"], "0.2")
            self.assertEqual(meta["total_products"], 0)
            self.assertEqual(meta["counts_by_resolution"], {})
            self.assertTrue((site_dir / "v1" / "meta.json").is_file())
            self.assertTrue((site_dir / "v1" / "index" / "brands.json").is_file())
            self.assertTrue((site_dir / "v1" / "index" / "catalog.jsonl").is_file())
            self.assertTrue((site_dir / "index.html").is_file())

    def test_all_four_resolutions_indices_and_cli_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_dir = tmp_path / "products"
            site_dir = tmp_path / "site"
            compact_schema = load_json_schema("compact.v0.2.schema.json")

            # ------------------------------------------------------------------
            # 1. `single` product: stale + superseded + active + EditionRedirect
            # ------------------------------------------------------------------
            pid_single = "gtin:00000000000109"
            pdir_single = product_dir_for_id(products_dir, pid_single)
            _write_json(pdir_single / "product.json", {"opf_schema": "0.2", "id": pid_single})

            e_stale = _make_edition(
                pid=pid_single,
                edition_id="01J8Z000000000000000000001",
                sodium="10",
                vintage_month="2024-01",
                net_content=[{"value": "900", "unit": "ml"}],
            )
            e_sup = _make_edition(
                pid=pid_single,
                edition_id="01J8Z000000000000000000002",
                sodium="16",
                vintage_month="2026-01",
                net_content=[{"value": "900", "unit": "ml"}],
            )
            e_act = _make_edition(
                pid=pid_single,
                edition_id="01J8Z000000000000000000003",
                sodium="18",
                vintage_month="2026-03",
                net_content=[{"value": "900", "unit": "ml"}],
                supersedes=[e_sup["edition_id"]],
                contributors=["github:alice", "github:bob"],
                origin={"country": "CN", "region": "华东示例区"},
                parties=[{"role": "manufacturer", "name": "示例饮品一厂", "license": "SC10600000000001"}],
                packaging_code="SMP-900-A1",
            )
            e_redir = {
                "opf_schema": "0.2",
                "id": pid_single,
                "edition_id": "01J8Z000000000000000000004",
                "merged_into": e_act["edition_id"],
                "merged_into_rev": 1,
                "merged_at": "2026-03-04",
                "reason": "Duplicate submission",
            }
            for doc in (e_stale, e_sup, e_act, e_redir):
                _write_json(pdir_single / "editions" / f"{doc['edition_id']}.json", doc)

            # ------------------------------------------------------------------
            # 2. `uniform` product: South + North single-plant tracks, identical core
            # ------------------------------------------------------------------
            pid_uniform = "opf:sample/uniform-tea/500ml"
            pdir_uniform = product_dir_for_id(products_dir, pid_uniform)
            _write_json(
                pdir_uniform / "product.json",
                {
                    "opf_schema": "0.2",
                    "id": pid_uniform,
                    "tracks": [
                        {
                            "track": "CN/plant:SC111",
                            "market": "CN",
                            "discriminator": {
                                "method": "sc_license",
                                "instructions": [{"lang": "zh-Hans", "text": "华南厂 SC111"}],
                            },
                        },
                        {
                            "track": "CN/plant:SC222",
                            "market": "CN",
                            "discriminator": {
                                "method": "sc_license",
                                "instructions": [{"lang": "zh-Hans", "text": "华北厂 SC222"}],
                            },
                        },
                    ],
                },
            )
            u_south = _make_edition(
                pid=pid_uniform,
                edition_id="01J8Z000000000000000000011",
                track="CN/plant:SC111",
                brand="示范茶坊",
                name="示例乌龙茶",
                net_content=[{"value": "500", "unit": "ml"}],
                origin={"country": "CN", "region": "华南示例区"},
                parties=[{"role": "manufacturer", "name": "华南一厂", "license": "SC111"}],
            )
            u_north = _make_edition(
                pid=pid_uniform,
                edition_id="01J8Z000000000000000000012",
                track="CN/plant:SC222",
                brand="示范茶坊",
                name="示例乌龙茶",
                net_content=[{"value": "500", "unit": "ml"}],
                origin={"country": "CN", "region": "华北示例区"},
                parties=[{"role": "manufacturer", "name": "华北一厂", "license": "SC222"}],
            )
            _write_json(pdir_uniform / "editions" / f"{u_south['edition_id']}.json", u_south)
            _write_json(pdir_uniform / "editions" / f"{u_north['edition_id']}.json", u_north)

            # ------------------------------------------------------------------
            # 3a. `divergent` product (mode == "by_track")
            # ------------------------------------------------------------------
            pid_div = "gtin:00000000000116"
            pdir_div = product_dir_for_id(products_dir, pid_div)
            _write_json(
                pdir_div / "product.json",
                {
                    "opf_schema": "0.2",
                    "id": pid_div,
                    "tracks": [
                        {
                            "track": "CN/plant:SC10500000000001",
                            "market": "CN",
                            "discriminator": {
                                "method": "sc_license",
                                "field": "attributes.parties[].license",
                                "instructions": [{"lang": "zh-Hans", "text": "示例乳业一厂 SC10500000000001"}],
                            },
                        },
                        {
                            "track": "CN/plant:SC10500000000002",
                            "market": "CN",
                            "discriminator": {
                                "method": "sc_license",
                                "field": "attributes.parties[].license",
                                "instructions": [{"lang": "zh-Hans", "text": "示例乳业二厂 SC10500000000002"}],
                            },
                        },
                    ],
                },
            )
            d_north = _make_edition(
                pid=pid_div,
                edition_id="01J8Z8AA11BB22CC33DD44EE55",
                track="CN/plant:SC10500000000001",
                brand="示例乳业",
                name="调制乳饮料",
                raw_ing="配料：生牛乳",
                energy_kj="302",
                sodium="55",
                calcium="125",
                allergens_declared={"contains": ["milk"], "may_contain": []},
                contributors=["github:alice", "github:bob"],
                vintage_month="2026-09",
                parties=[{"role": "manufacturer", "name": "示例乳业一厂", "license": "SC10500000000001"}],
            )
            d_south = _make_edition(
                pid=pid_div,
                edition_id="01J8Z9FF66GG77HH88JJ99KK00",
                track="CN/plant:SC10500000000002",
                brand="示例乳业",
                name="调制乳饮料",
                raw_ing="配料：生牛乳、卡拉胶",
                energy_kj="272",
                sodium="68",
                calcium=None,  # omitted in South variant -> partial: True
                allergens_declared={"contains": [], "may_contain": ["milk", "soy"]},
                contributors=[],  # community_reported -> must NOT demote highest_active!
                vintage_month="2026-10",
                parties=[{"role": "manufacturer", "name": "示例乳业二厂", "license": "SC10500000000002"}],
            )
            _write_json(pdir_div / "editions" / f"{d_north['edition_id']}.json", d_north)
            _write_json(pdir_div / "editions" / f"{d_south['edition_id']}.json", d_south)

            # ------------------------------------------------------------------
            # 3b. `divergent` product (mode == "unsplit_ambiguity")
            # ------------------------------------------------------------------
            pid_unsplit = "opf:sample/unsplit-snack/100g"
            pdir_unsplit = product_dir_for_id(products_dir, pid_unsplit)
            _write_json(pdir_unsplit / "product.json", {"opf_schema": "0.2", "id": pid_unsplit})
            u1 = _make_edition(
                pid=pid_unsplit,
                edition_id="01J8Z000000000000000000021",
                brand="无轨零食",
                name="香脆饼干",
                raw_ing="配料：小麦粉",
                energy_kj="1800",
                sodium="200",
            )
            u2 = _make_edition(
                pid=pid_unsplit,
                edition_id="01J8Z000000000000000000022",
                brand="无轨零食",
                name="香脆饼干",
                raw_ing="配料：小麦粉",
                energy_kj="2000",
                sodium="300",
            )
            _write_json(pdir_unsplit / "editions" / f"{u1['edition_id']}.json", u1)
            _write_json(pdir_unsplit / "editions" / f"{u2['edition_id']}.json", u2)

            # ------------------------------------------------------------------
            # 4. `inactive` product: sole track head marked discontinued
            # ------------------------------------------------------------------
            pid_inactive = "opf:sample/retired-soda/330ml"
            pdir_inact = product_dir_for_id(products_dir, pid_inactive)
            _write_json(pdir_inact / "product.json", {"opf_schema": "0.2", "id": pid_inactive})
            inact_ed = _make_edition(
                pid=pid_inactive,
                edition_id="01J8Z000000000000000000031",
                track="US/default",
                brand="Old Soda",
                name="Classic Cola",
                raw_ing="配料：水",
                lifecycle={"state": "discontinued", "effective_month": "2026-08", "reason": "Discontinued"},
            )
            _write_json(pdir_inact / "editions" / f"{inact_ed['edition_id']}.json", inact_ed)

            # Run build via CLI `opf build`
            out_buf = io.StringIO()
            err_buf = io.StringIO()
            with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                rc = cli_main(
                    [
                        "build",
                        "--data-dir",
                        str(products_dir),
                        "--out-dir",
                        str(site_dir),
                        "--media-base-url",
                        "https://media.example.org/",
                    ]
                )
            self.assertEqual(rc, 0, err_buf.getvalue())

            # Verify `single` compact & full outputs
            single_compact = json.loads((site_dir / "v1/gtin/000/000/00000000000109.json").read_text("utf-8"))
            self.assertEqual(validate_against_json_schema(single_compact, compact_schema), [])
            self.assertEqual(single_compact["resolution"], "single")
            self.assertEqual(single_compact["edition_redirects"], {e_redir["edition_id"]: e_act["edition_id"]})
            single_full = json.loads((site_dir / "v1/gtin/000/000/00000000000109.full.json").read_text("utf-8"))
            statuses = {e["edition_id"]: e["status"] for e in single_full["editions"]}
            self.assertEqual(
                statuses,
                {
                    e_stale["edition_id"]: "stale",
                    e_sup["edition_id"]: "superseded",
                    e_act["edition_id"]: "active",
                },
            )
            # core.ingredients_tree remains span-free while ingredients_tree_annotated has UI spans
            act_full = single_full["editions"][-1]
            self.assertNotIn("span", act_full["core"]["ingredients_tree"][0]["nodes"][0])
            self.assertEqual(act_full["ingredients_tree_annotated"][0]["nodes"][0]["span"], [3, 4])

            # Verify `uniform` compact output
            uniform_compact = json.loads((site_dir / "v1/opf/sample/uniform-tea/500ml.json").read_text("utf-8"))
            self.assertEqual(validate_against_json_schema(uniform_compact, compact_schema), [])
            self.assertEqual(uniform_compact["resolution"], "uniform")
            self.assertEqual(len(uniform_compact["origins_summary"]), 2)
            self.assertEqual(len(uniform_compact["parties_summary"]), 2)

            # Verify `divergent` (by_track)
            div_compact = json.loads((site_dir / "v1/gtin/000/000/00000000000116.json").read_text("utf-8"))
            self.assertEqual(validate_against_json_schema(div_compact, compact_schema), [])
            self.assertEqual(div_compact["resolution"], "divergent")
            self.assertNotIn("normalized", div_compact)
            self.assertNotIn("ingredients_text", div_compact)
            self.assertEqual(div_compact["disambiguation"]["mode"], "by_track")
            self.assertEqual(div_compact["evidence_summary"]["highest_active"], "corroborated")
            self.assertEqual(div_compact["evidence_summary"]["lowest_active"], "community_reported")
            ca_range = div_compact["common_summary"]["nutrient_ranges_not_for_logging"]["calcium"]
            self.assertTrue(ca_range["partial"])
            self.assertEqual(ca_range["declared_in_variants"], 1)
            self.assertEqual(ca_range["total_variants"], 2)
            # Allergens union separation: soy stays in may_contain, milk stays in contains (not duplicated in may_contain)
            self.assertEqual(div_compact["common_summary"]["allergens_union"]["contains"], ["milk"])
            self.assertEqual(div_compact["common_summary"]["allergens_union"]["may_contain"], ["soy"])

            # Verify `divergent` (unsplit_ambiguity)
            unsplit_compact = json.loads((site_dir / "v1/opf/sample/unsplit-snack/100g.json").read_text("utf-8"))
            self.assertEqual(validate_against_json_schema(unsplit_compact, compact_schema), [])
            self.assertEqual(unsplit_compact["disambiguation"]["mode"], "unsplit_ambiguity")

            # Verify `inactive`
            inact_compact = json.loads((site_dir / "v1/opf/sample/retired-soda/330ml.json").read_text("utf-8"))
            self.assertEqual(validate_against_json_schema(inact_compact, compact_schema), [])
            self.assertEqual(inact_compact["resolution"], "inactive")
            self.assertEqual(inact_compact["active_edition_ids"], [])
            self.assertIsNone(inact_compact["evidence_summary"]["highest_active"])
            self.assertNotIn("normalized", inact_compact)

            # Verify indices & meta.json
            meta = json.loads((site_dir / "v1" / "meta.json").read_text("utf-8"))
            self.assertEqual(meta["opf_schema"], "0.2")
            self.assertEqual(meta["media_base_url"], "https://media.example.org")
            self.assertEqual(meta["total_products"], 5)
            self.assertEqual(
                meta["counts_by_resolution"],
                {"single": 1, "uniform": 1, "divergent": 2, "inactive": 1},
            )
            # `US` track is inactive/discontinued so it must NOT be counted in counts_by_market
            self.assertEqual(meta["counts_by_market"], {"CN": 4})

            brands = json.loads((site_dir / "v1" / "index" / "brands.json").read_text("utf-8"))
            self.assertEqual(len(brands["brands"]), 5)

            catalog_lines = (site_dir / "v1" / "index" / "catalog.jsonl").read_text("utf-8").splitlines()
            self.assertEqual(len(catalog_lines), 5)
            by_id = {json.loads(line)["id"]: json.loads(line) for line in catalog_lines}
            self.assertIn("–", by_id[pid_div]["energy_kcal_100"])
            self.assertIsNone(by_id[pid_inactive]["energy_kcal_100"])
            self.assertEqual(by_id[pid_div]["lowest_active_evidence_level"], "community_reported")

            # Verify objective catalog filter & sort index fields (w06 + w07)
            for pid, row in by_id.items():
                for req_k in (
                    "namespace",
                    "profiles",
                    "markets",
                    "brand_slug",
                    "allergens_contains",
                    "allergens_may_contain",
                    "additives_ins",
                    "additives_count",
                    "ingredients_tokens",
                    "nutrients_100",
                    "energy_kcal_num",
                ):
                    self.assertIn(req_k, row, f"Missing {req_k!r} on {pid}")
                self.assertIsInstance(row["markets"], list)
                self.assertIsInstance(row["profiles"], list)
                self.assertIsInstance(row["additives_ins"], list)
                self.assertIsInstance(row["additives_count"], int)
                self.assertIsInstance(row["ingredients_tokens"], list)
                self.assertIsInstance(row["nutrients_100"], dict)

            self.assertEqual(by_id[pid_single]["namespace"], "gtin")
            self.assertEqual(by_id[pid_single]["profiles"], ["CN/GB28050-2011"])
            self.assertEqual(by_id[pid_single]["markets"], ["CN"])
            self.assertEqual(by_id[pid_single]["additives_ins"], ["300", "500(ii)"])
            self.assertEqual(by_id[pid_single]["additives_count"], 2)  # vitamin C + sodium bicarbonate
            self.assertIn("茉莉花茶", by_id[pid_single]["ingredients_tokens"])
            self.assertIn("energy_kj", by_id[pid_single]["nutrients_100"])
            self.assertTrue(by_id[pid_single]["nutrients_100"]["energy_kj"]["has_upper_bound"])
            self.assertFalse(by_id[pid_single]["nutrients_100"]["energy_kj"]["partial"])

            self.assertEqual(by_id[pid_div]["allergens_contains"], ["milk"])
            self.assertEqual(by_id[pid_div]["allergens_may_contain"], ["soy"])
            self.assertIsInstance(by_id[pid_div]["energy_kcal_num"], float)
            self.assertTrue(by_id[pid_div]["nutrients_100"]["calcium"]["partial"])
            self.assertFalse(by_id[pid_div]["nutrients_100"]["sodium"]["partial"])
            self.assertLess(by_id[pid_div]["nutrients_100"]["sodium"]["min"], by_id[pid_div]["nutrients_100"]["sodium"]["max"])

            self.assertEqual(by_id[pid_inactive]["namespace"], "opf")
            self.assertEqual(by_id[pid_inactive]["markets"], ["US"])
            self.assertIsNone(by_id[pid_inactive]["energy_kcal_num"])
            self.assertEqual(by_id[pid_inactive]["nutrients_100"], {})

            # Verify brand index shares enriched summary rows
            div_slug = by_id[pid_div]["brand_slug"]
            brand_doc = json.loads((site_dir / "v1" / "index" / "brand" / f"{div_slug}.json").read_text("utf-8"))
            self.assertEqual(brand_doc["products"][0]["allergens_contains"], ["milk"])
            self.assertEqual(brand_doc["products"][0]["allergens_may_contain"], ["soy"])


if __name__ == "__main__":
    unittest.main()
