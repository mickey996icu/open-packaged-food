"""Unit tests for OpenPackagedFood v0.2 schemas, IDs, span-free ingredients, patches, normalization, lifecycle, and validator."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from opf.ids import (
    edition_json_path,
    generate_ulid,
    is_valid_ulid,
    parse_edition_ref,
    product_dir_for_id,
    product_json_path,
    validate_track_key,
)
from opf.ingredients import (
    annotate_ingredients_spans,
    parse_ingredients_semantic,
    verify_ingredients_round_trip,
)
from opf.normalize import (
    compute_core_fingerprint,
    compute_stale_window_months,
    compute_t_active,
    derive_editions_lifecycle,
    derive_evidence_level,
    normalize_edition,
)
from opf.patches import (
    PatchError,
    apply_patch,
    diff_to_patch,
    extract_patchable_surface,
    invert_patch,
    parse_json_pointer,
    reconstruct_surface_at_rev,
)
from opf.registries import REPO_ROOT
from opf.validator import (
    load_json_schema,
    validate_against_json_schema,
    validate_edition_doc,
    validate_product_dir,
    validate_product_meta_doc,
    validate_products_root,
)


def _extract_spec_json_blocks() -> list[dict]:
    spec_text = (REPO_ROOT / "spec" / "SPEC.md").read_text(encoding="utf-8")
    blocks = re.findall(r"^[ \t]*```json\r?\n(.*?)\r?\n[ \t]*```", spec_text, flags=re.MULTILINE | re.DOTALL)
    return [json.loads(b) for b in blocks]


def _make_base_edition(
    *,
    product_id: str = "gtin:00000000000109",
    edition_id: str | None = None,
    track: str = "CN/default",
    sodium: str = "18",
    reported_at: str = "2026-02-14",
    vintage_month: str | None = "2026-01",
    contributor: str = "github:alice",
    shelf_life: dict | None = None,
    packaging_code: str | None = None,
    product_standard: list[str] | None = None,
    supersedes: list[str] | None = None,
    lifecycle: dict | None = None,
) -> dict:
    eid = edition_id or generate_ulid(1_770_000_000_000)
    raw_ing = "配料：水、茉莉花茶（绿茶茶坯）（≥4g/L）、维生素C、碳酸氢钠"
    photo_sha = hashlib.sha256(f"{eid}-{contributor}-{sodium}".encode("utf-8")).hexdigest()
    ev_item: dict = {
        "evidence_id": f"sha256:{photo_sha}",
        "type": "label_photo",
        "provenance": "external_contributor",
        "region": "nutrition_table",
        "cropped_sha256": photo_sha,
        "media_ref": f"opf-media://sha256/{photo_sha}",
        "contributor": contributor,
        "reported_at": reported_at,
    }
    if vintage_month is not None:
        ev_item["vintage_month"] = vintage_month

    attrs: dict = {
        "product_name": [{"lang": "zh-Hans", "text": "示例茉莉花茶"}],
        "brand": "示例茶饮",
        "ingredients_text": [{"lang": "zh-Hans", "text": raw_ing}],
    }
    if shelf_life is not None:
        attrs["shelf_life"] = shelf_life
    if packaging_code is not None:
        attrs["packaging_code"] = packaging_code
    if product_standard is not None:
        attrs["product_standard"] = product_standard

    doc: dict = {
        "opf_schema": "0.2",
        "id": product_id,
        "edition_id": eid,
        "rev": 1,
        "track": track,
        "supersedes": supersedes or [],
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
            "ingredients_tree": [
                {
                    "lang": "zh-Hans",
                    "nodes": parse_ingredients_semantic(
                        raw_ing, lang="zh-Hans", profile_id="CN/GB28050-2011"
                    ),
                }
            ],
            "allergens_declared": {"contains": [], "may_contain": []},
        },
        "attributes": attrs,
        "evidence": [ev_item],
        "revisions": [
            {
                "rev": 1,
                "kind": "initial",
                "created_at": "2026-02-14T10:15:00Z",
                "author": contributor,
                "provenance": "external_contributor",
                "evidence_refs": [ev_item["evidence_id"]],
                "patch": [],
            }
        ],
    }
    if lifecycle is not None:
        lifecycle_copy = copy.deepcopy(lifecycle)
        if not lifecycle_copy.get("evidence_refs"):
            lifecycle_copy["evidence_refs"] = [ev_item["evidence_id"]]
        doc["lifecycle"] = lifecycle_copy
    normalize_edition(doc)
    return doc


class TestSpecExamplesAndSchemas(unittest.TestCase):
    def test_deprecated_v01_schemas_deleted(self) -> None:
        schema_dir = REPO_ROOT / "spec" / "schema"
        self.assertFalse((schema_dir / "product.v0.1.schema.json").exists())
        self.assertFalse((schema_dir / "compact.v0.1.schema.json").exists())
        self.assertTrue((schema_dir / "compact.v0.2.schema.json").exists())

    def test_spec_examples_validate_against_v02_schemas_and_patch_replay(self) -> None:
        blocks = _extract_spec_json_blocks()
        self.assertEqual(len(blocks), 3)
        edition_example, redirect_example, compact_divergent_example = blocks

        # 1. SPEC §8.4 EditionRecord: normalize fills computed normalized/fingerprints, then full validation passes
        normalized_spec_ed = copy.deepcopy(edition_example)
        normalize_edition(normalized_spec_ed)
        self.assertEqual(
            validate_against_json_schema(normalized_spec_ed, load_json_schema("edition.v0.2.schema.json")),
            [],
        )
        self.assertEqual(validate_edition_doc(normalized_spec_ed), [])
        self.assertEqual(derive_evidence_level(normalized_spec_ed), "corroborated")
        self.assertEqual(compute_t_active(normalized_spec_ed), "2026-03")

        # Verify S1 <-> S4 backward and forward patch replay
        s1 = reconstruct_surface_at_rev(normalized_spec_ed, 1)
        self.assertEqual(s1["track"], "CN/default")
        self.assertNotIn("packaging_code", s1["attributes"])
        self.assertEqual(s1["core"]["nutrition_declared"]["rows"][4]["value"], "16")
        s3 = reconstruct_surface_at_rev(normalized_spec_ed, 3)
        self.assertEqual(s3["track"], "CN/plant:SC10600000000001")
        self.assertEqual(s3["core"]["nutrition_declared"]["rows"][4]["value"], "16")
        s4 = extract_patchable_surface(normalized_spec_ed)
        replayed = s1
        for r_entry in normalized_spec_ed["revisions"][1:]:
            replayed = apply_patch(replayed, r_entry["patch"])
        self.assertEqual(replayed, s4)

        # Reject tampered/hand-written reverse_patch (non-minimal or wrong op order)
        tampered = copy.deepcopy(normalized_spec_ed)
        tampered["revisions"][1]["reverse_patch"].reverse()
        errs_tampered = validate_edition_doc(tampered)
        self.assertTrue(any("reverse_patch" in e for e in errs_tampered))

        tampered2 = copy.deepcopy(normalized_spec_ed)
        tampered2["revisions"][3]["reverse_patch"] = [
            {"op": "remove", "path": "/core/nutrition_declared/rows/4/value"},
            {"op": "add", "path": "/core/nutrition_declared/rows/4/value", "value": "16"},
        ]
        errs_tampered2 = validate_edition_doc(tampered2)
        self.assertTrue(any("reverse_patch" in e for e in errs_tampered2))

        tampered3 = copy.deepcopy(normalized_spec_ed)
        tampered3["revisions"][2]["reverse_patch"][0]["path"] = "/attributes/brand"
        errs_tampered3 = validate_edition_doc(tampered3)
        self.assertTrue(any("reverse_patch" in e or "reproduce S_3" in e for e in errs_tampered3))

        # 2. SPEC §8.5 EditionRedirect verbatim
        self.assertEqual(
            validate_against_json_schema(redirect_example, load_json_schema("edition.v0.2.schema.json")),
            [],
        )
        self.assertEqual(validate_edition_doc(redirect_example), [])

        # 3. SPEC §8.7 Compact API divergent example verbatim
        self.assertEqual(
            validate_against_json_schema(
                compact_divergent_example, load_json_schema("compact.v0.2.schema.json")
            ),
            [],
        )

    def test_party_registry_check_removed_and_specimen_id_supported(self) -> None:
        ed = _make_base_edition()
        ed["evidence"][0]["specimen_id"] = "bottle-01_front"
        self.assertEqual(validate_edition_doc(ed), [])

        bad_spec = copy.deepcopy(ed)
        bad_spec["evidence"][0]["specimen_id"] = "bad specimen with spaces"
        self.assertNotEqual(validate_edition_doc(bad_spec), [])

        bad_party = copy.deepcopy(ed)
        bad_party["attributes"]["parties"] = [
            {
                "role": "manufacturer",
                "name": "测试工厂",
                "registry_check": {"registry": "CN/SAMR-SC", "result": "match", "checked_at": "2026-02-14"},
            }
        ]
        errs = validate_edition_doc(bad_party)
        self.assertTrue(any("registry_check" in e for e in errs))

    def test_compact_v02_oneof_modes_and_divergent_top_level_prohibition(self) -> None:
        blocks = _extract_spec_json_blocks()
        divergent = copy.deepcopy(blocks[2])
        compact_schema = load_json_schema("compact.v0.2.schema.json")

        bad_div = copy.deepcopy(divergent)
        bad_div["normalized"] = {"basis": "100ml", "nutrients": {}}
        self.assertNotEqual(validate_against_json_schema(bad_div, compact_schema), [])

        bad_div2 = copy.deepcopy(divergent)
        bad_div2["ingredients_text"] = [{"lang": "zh-Hans", "text": "配料：水"}]
        self.assertNotEqual(validate_against_json_schema(bad_div2, compact_schema), [])

        ed1 = _make_base_edition(edition_id="01J8Z8AA11BB22CC33DD44EE55")
        single_doc = {
            "opf_schema": "0.2",
            "id": ed1["id"],
            "resolution": "single",
            "active_edition_ids": [ed1["edition_id"]],
            "evidence_summary": {
                "highest_active": "verified",
                "lowest_active": "verified",
                "by_edition": {ed1["edition_id"]: "verified"},
            },
            "brand": ed1["attributes"]["brand"],
            "product_name": ed1["attributes"]["product_name"],
            "regulatory_profile": ed1["core"]["regulatory_profile"],
            "core_fingerprint": ed1["core_fingerprint"],
            "net_content": ed1["core"]["net_content"],
            "normalized": ed1["normalized"],
            "ingredients_text": ed1["attributes"]["ingredients_text"],
            "quality_flags": ed1["quality_flags"],
            "editions_summary": [
                {
                    "edition_id": ed1["edition_id"],
                    "rev": 1,
                    "track": "CN/default",
                    "status": "active",
                    "t_active": "2026-01",
                    "evidence_level": "verified",
                    "core_fingerprint": ed1["core_fingerprint"],
                }
            ],
            "full_url": "/v1/gtin/000/000/00000000000109.full.json",
        }
        self.assertEqual(validate_against_json_schema(single_doc, compact_schema), [])

        uniform_doc = copy.deepcopy(single_doc)
        uniform_doc["resolution"] = "uniform"
        uniform_doc["active_edition_ids"] = [
            "01J8Z8AA11BB22CC33DD44EE55",
            "01J8Z9FF66GG77HH88JJ99KK00",
        ]
        uniform_doc["active_tracks"] = ["CN/plant:SC111", "CN/plant:SC222"]
        uniform_doc["origins_summary"] = [{"country": "CN", "region": "浙江"}]
        uniform_doc["editions_summary"].append(
            {
                "edition_id": "01J8Z9FF66GG77HH88JJ99KK00",
                "rev": 1,
                "track": "CN/plant:SC222",
                "status": "active",
                "t_active": "2026-01",
                "evidence_level": "verified",
                "core_fingerprint": ed1["core_fingerprint"],
            }
        )
        self.assertEqual(validate_against_json_schema(uniform_doc, compact_schema), [])

        inactive_doc = {
            "opf_schema": "0.2",
            "id": ed1["id"],
            "resolution": "inactive",
            "active_edition_ids": [],
            "evidence_summary": {
                "highest_active": None,
                "lowest_active": None,
                "by_edition": {ed1["edition_id"]: "verified"},
            },
            "brand": ed1["attributes"]["brand"],
            "product_name": ed1["attributes"]["product_name"],
            "editions_summary": [
                {
                    "edition_id": ed1["edition_id"],
                    "rev": 1,
                    "track": "CN/default",
                    "status": "discontinued",
                    "t_active": "2026-01",
                    "evidence_level": "verified",
                    "core_fingerprint": ed1["core_fingerprint"],
                }
            ],
            "full_url": "/v1/gtin/000/000/00000000000109.full.json",
        }
        self.assertEqual(validate_against_json_schema(inactive_doc, compact_schema), [])


class TestIdsAndTracks(unittest.TestCase):
    def test_ulid_generation_and_validation(self) -> None:
        u1 = generate_ulid(1_700_000_000_000)
        u2 = generate_ulid(1_700_000_000_001)
        self.assertTrue(is_valid_ulid(u1))
        self.assertTrue(is_valid_ulid(u2))
        self.assertLess(u1[:10], u2[:10])
        self.assertFalse(is_valid_ulid("01J8Z8AA11BB22CC33DD44EE5I"))  # invalid I
        self.assertFalse(is_valid_ulid("81J8Z8AA11BB22CC33DD44EE55"))  # overflow leading digit
        self.assertFalse(is_valid_ulid("01j8z8aa11bb22cc33dd44ee55"))  # lowercase

    def test_track_keys_and_set_validation(self) -> None:
        self.assertEqual(validate_track_key("CN/default"), [])
        self.assertNotEqual(validate_track_key("CN/default", allow_default=False), [])
        self.assertEqual(validate_track_key("CN/plant:SC111"), [])
        self.assertEqual(validate_track_key("CN/plant:{SC111,SC222}"), [])
        self.assertEqual(validate_track_key("CN/origin:NZ+plant:{SC111,SC222}"), [])

        self.assertNotEqual(validate_track_key("CN/plant:{SC222,SC111}"), [])
        self.assertNotEqual(validate_track_key("CN/plant:{SC111}"), [])
        self.assertNotEqual(validate_track_key("CN/plant:{SC111,SC111}"), [])
        self.assertNotEqual(validate_track_key("CN/plant:SC111+origin:NZ"), [])
        self.assertNotEqual(validate_track_key("CN/plant:SC111+plant:SC222"), [])

    def test_v02_paths_and_edition_ref(self) -> None:
        root = Path("/tmp/opf-products")
        gid = "gtin:00000000000109"
        oid = "opf:demo-deli/black-pepper-patty/80g"
        ulid = "01J8Z4K9M2N3P4Q5R6S7T8V9W0"
        self.assertEqual(product_dir_for_id(root, gid), root / "gtin" / "000" / "000" / "00000000000109")
        self.assertEqual(product_json_path(root, oid), root / "opf" / "demo-deli" / "black-pepper-patty" / "80g" / "product.json")
        self.assertEqual(edition_json_path(root, gid, ulid), root / "gtin" / "000" / "000" / "00000000000109" / "editions" / f"{ulid}.json")
        self.assertEqual(parse_edition_ref(ulid), (ulid, None))
        self.assertEqual(parse_edition_ref(f"{ulid}@4"), (ulid, 4))
        with self.assertRaises(ValueError):
            parse_edition_ref(f"{ulid}@0")


class TestSpanFreeIngredients(unittest.TestCase):
    def test_punctuation_changes_keep_core_fingerprint_and_pass_round_trip(self) -> None:
        raw_full = "配料：水、茉莉花茶（绿茶茶坯）（≥4g/L）、维生素C、碳酸氢钠。"
        raw_half = "配料: 水, 茉莉花茶(绿茶茶坯)(≥4g/L), 维生素C, 碳酸氢钠"
        nodes = parse_ingredients_semantic(raw_full, lang="zh-Hans", profile_id="CN/GB28050-2011")
        for n in nodes:
            self.assertNotIn("span", n)
            self.assertNotIn("qualifier_span", n)
            self.assertNotIn("functional_class_span", n)
        self.assertEqual(verify_ingredients_round_trip(raw_full, nodes, "CN/GB28050-2011"), [])
        self.assertEqual(verify_ingredients_round_trip(raw_half, nodes, "CN/GB28050-2011"), [])

        ed_a = _make_base_edition()
        ed_b = copy.deepcopy(ed_a)
        ed_b["attributes"]["ingredients_text"][0]["text"] = raw_half
        normalize_edition(ed_b)
        self.assertEqual(ed_a["core_fingerprint"], ed_b["core_fingerprint"])

    def test_dropped_or_extra_ingredient_fails_monotonic_check(self) -> None:
        raw = "配料：水、白砂糖、柠檬酸"
        nodes = parse_ingredients_semantic(raw, lang="zh-Hans", profile_id="CN/GB28050-2011")
        self.assertEqual(verify_ingredients_round_trip(raw, nodes), [])

        dropped = [nodes[0], nodes[2]]
        errs_drop = verify_ingredients_round_trip(raw, dropped)
        self.assertTrue(any("白砂糖" in e for e in errs_drop))

        trailing_uncaptured = verify_ingredients_round_trip(raw + "、食用香精", nodes)
        self.assertTrue(any("食用香精" in e for e in trailing_uncaptured))

        extra_node = nodes + [{"name": "阿斯巴甜"}]
        errs_extra = verify_ingredients_round_trip(raw, extra_node)
        self.assertTrue(any("阿斯巴甜" in e for e in errs_extra))

    def test_qualifier_before_children_and_annotate_spans(self) -> None:
        raw = "配料：茉莉花茶（≥4g/L）（绿茶茶坯）、水"
        nodes = [
            {"name": "茉莉花茶", "qualifier": "≥4g/L", "children": [{"name": "绿茶茶坯"}]},
            {"name": "水"},
        ]
        self.assertEqual(verify_ingredients_round_trip(raw, nodes), [])
        spanned = annotate_ingredients_spans(raw, nodes)
        self.assertEqual(raw[spanned[0]["span"][0] : spanned[0]["span"][1]], "茉莉花茶")
        self.assertEqual(raw[spanned[0]["qualifier_span"][0] : spanned[0]["qualifier_span"][1]], "≥4g/L")
        self.assertEqual(
            raw[spanned[0]["children"][0]["span"][0] : spanned[0]["children"][0]["span"][1]],
            "绿茶茶坯",
        )


class TestPatchesAndRevisionValidation(unittest.TestCase):
    def test_json_pointer_tilde_and_all_rfc6902_ops_invert_cleanly(self) -> None:
        self.assertEqual(parse_json_pointer("/a~1b/m~0n/~01"), ["a/b", "m~n", "~1"])
        with self.assertRaises(PatchError):
            parse_json_pointer("/bad~2escape")

        s0 = {"core": {"a": 1, "arr": ["x", "y"]}, "attributes": {"k": "v"}}
        ops = [
            {"op": "test", "path": "/core/a", "value": 1},
            {"op": "add", "path": "/core/arr/-", "value": "z"},
            {"op": "move", "from": "/core/arr/0", "path": "/attributes/moved"},
            {"op": "copy", "from": "/attributes/k", "path": "/attributes/k2"},
            {"op": "replace", "path": "/core/a", "value": True},
            {"op": "remove", "path": "/attributes/k"},
        ]
        s1 = apply_patch(s0, ops)
        self.assertIs(s1["core"]["a"], True)
        inv = invert_patch(s0, ops)
        self.assertEqual(apply_patch(s1, inv), s0)

        with self.assertRaises(PatchError):
            apply_patch(s1, [{"op": "test", "path": "/core/a", "value": 1}])  # True != 1

    def test_disjoint_revision_kind_constraints_and_diff_to_patch(self) -> None:
        ed = _make_base_edition()
        s1 = extract_patchable_surface(ed)
        s2 = copy.deepcopy(s1)
        s2["attributes"]["packaging_code"] = "PKG-01"
        patch2, rev2 = diff_to_patch(s1, s2)
        ed["attributes"]["packaging_code"] = "PKG-01"
        ed["rev"] = 2
        ed["revisions"].append(
            {
                "rev": 2,
                "kind": "enrichment",
                "created_at": "2026-02-15T10:00:00Z",
                "author": "github:alice",
                "provenance": "external_contributor",
                "evidence_refs": [ed["evidence"][0]["evidence_id"]],
                "patch": patch2,
                "reverse_patch": rev2,
            }
        )
        normalize_edition(ed)
        self.assertEqual(validate_edition_doc(ed), [])

        # Enrichment attempting to touch /core or overwrite existing attribute must fail
        bad_enrich = copy.deepcopy(ed)
        bad_enrich["revisions"][1]["kind"] = "enrichment"
        bad_enrich["revisions"][1]["patch"] = [{"op": "replace", "path": "/attributes/packaging_code", "value": "X"}]
        self.assertNotEqual(validate_edition_doc(bad_enrich), [])

        # Errata cannot touch /track
        bad_errata = copy.deepcopy(ed)
        bad_errata["track"] = "CN/code:A"
        bad_errata["rev"] = 3
        p3, r3 = diff_to_patch(extract_patchable_surface(ed), extract_patchable_surface(bad_errata))
        bad_errata["revisions"].append(
            {
                "rev": 3,
                "kind": "errata",
                "created_at": "2026-02-16T10:00:00Z",
                "author": "github:alice",
                "provenance": "external_contributor",
                "evidence_refs": [ed["evidence"][0]["evidence_id"]],
                "patch": p3,
                "reverse_patch": r3,
            }
        )
        self.assertTrue(any("errata path" in e for e in validate_edition_doc(bad_errata)))


class TestLifecycleAndProductDir(unittest.TestCase):
    def test_canonical_row_order_enforced(self) -> None:
        ed = _make_base_edition()
        bad = copy.deepcopy(ed)
        bad["core"]["nutrition_declared"]["rows"].reverse()
        errs = validate_edition_doc(bad)
        self.assertTrue(any("canonical §3 order" in e for e in errs))

    def test_t_active_vintage_priority_and_no_reactivation_by_reported_at(self) -> None:
        # Without vintage_month: t_active = min(reported_at[:7]), so adding a later reported_at does NOT raise t_active
        e_old = _make_base_edition(
            edition_id="01J8Z000000000000000000001",
            reported_at="2024-01-10",
            vintage_month=None,
        )
        e_old["evidence"].append(
            {
                "evidence_id": "ev:01J8Z000000000000000000099",
                "type": "community_report",
                "provenance": "external_contributor",
                "contributor": "github:late",
                "reported_at": "2027-05-20",
            }
        )
        self.assertEqual(compute_t_active(e_old), "2024-01")

        # Newer edition on same track with vintage_month 2025-06 makes e_old stale (17 >= 12 months)
        e_new = _make_base_edition(
            edition_id="01J8Z000000000000000000002",
            sodium="20",
            reported_at="2025-07-01",
            vintage_month="2025-06",
        )
        derived = derive_editions_lifecycle([e_old, e_new])
        self.assertEqual(derived[e_old["edition_id"]]["status"], "stale")
        self.assertEqual(derived[e_new["edition_id"]]["status"], "active")

    def test_shelf_life_clamping_discontinued_head_and_retracted_isolation(self) -> None:
        self.assertEqual(compute_stale_window_months(_make_base_edition(shelf_life=None)), 12)
        self.assertEqual(
            compute_stale_window_months(_make_base_edition(shelf_life={"value": "45", "unit": "day"})), 3
        )
        self.assertEqual(
            compute_stale_window_months(_make_base_edition(shelf_life={"value": "24", "unit": "month"})), 18
        )

        # 4-month shelf life: e1 at 2026-01 vs head at 2026-05 -> gap 4 >= 4 -> stale
        e1 = _make_base_edition(
            edition_id="01J8Z000000000000000000011",
            vintage_month="2026-01",
            shelf_life={"value": "4", "unit": "month"},
        )
        e2 = _make_base_edition(
            edition_id="01J8Z000000000000000000012",
            sodium="22",
            vintage_month="2026-05",
            lifecycle={"state": "discontinued", "reason": "Product line retired", "evidence_refs": []},
        )
        e3_ret = _make_base_edition(
            edition_id="01J8Z000000000000000000013",
            sodium="99",
            vintage_month="2026-09",
            lifecycle={"state": "retracted", "reason": "OCR hallucination", "evidence_refs": []},
        )
        # e2 is discontinued so e1 is the remaining candidate track head and stays active; e3_ret is retracted
        derived = derive_editions_lifecycle([e1, e2, e3_ret])
        self.assertEqual(derived[e2["edition_id"]]["status"], "discontinued")
        self.assertEqual(derived[e3_ret["edition_id"]]["status"], "retracted")
        self.assertEqual(derived[e1["edition_id"]]["status"], "active")

        # If e2 were NOT discontinued, e1 would become stale against e2
        e2_live = copy.deepcopy(e2)
        e2_live.pop("lifecycle", None)
        derived2 = derive_editions_lifecycle([e1, e2_live])
        self.assertEqual(derived2[e1["edition_id"]]["status"], "stale")
        self.assertEqual(derived2[e2_live["edition_id"]]["status"], "active")

    def test_product_dir_duplicate_fingerprint_supersedes_and_redirect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            products_root = Path(tmp) / "products"
            pid = "gtin:00000000000109"
            pdir = product_dir_for_id(products_root, pid)
            (pdir / "editions").mkdir(parents=True)

            meta = {"opf_schema": "0.2", "id": pid}
            (pdir / "product.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

            e1 = _make_base_edition(edition_id="01J8Z000000000000000000101", packaging_code="V1")
            e2 = _make_base_edition(edition_id="01J8Z000000000000000000102", packaging_code="V2")
            (pdir / "editions" / f"{e1['edition_id']}.json").write_text(
                json.dumps(e1, ensure_ascii=False), encoding="utf-8"
            )
            (pdir / "editions" / f"{e2['edition_id']}.json").write_text(
                json.dumps(e2, ensure_ascii=False), encoding="utf-8"
            )

            # Same (id, track) and same core_fingerprint without supersedes -> blocked
            errs = validate_product_dir(pdir, products_root=products_root)
            self.assertTrue(any("duplicate core_fingerprint" in e for e in errs))

            # Linking e2 -> supersedes [e1] makes it valid
            e2_sup = _make_base_edition(
                edition_id="01J8Z000000000000000000102",
                packaging_code="V2",
                supersedes=[e1["edition_id"]],
            )
            (pdir / "editions" / f"{e2['edition_id']}.json").write_text(
                json.dumps(e2_sup, ensure_ascii=False), encoding="utf-8"
            )
            self.assertEqual(validate_products_root(products_root), [])

            # Replacing e2 with an EditionRedirect pointing to e1 also passes
            redir = {
                "opf_schema": "0.2",
                "id": pid,
                "edition_id": e2["edition_id"],
                "merged_into": e1["edition_id"],
                "merged_into_rev": 1,
                "merged_at": "2026-03-03",
                "reason": "Duplicate concurrent submission",
            }
            (pdir / "editions" / f"{e2['edition_id']}.json").write_text(
                json.dumps(redir, ensure_ascii=False), encoding="utf-8"
            )
            self.assertEqual(validate_products_root(products_root), [])

            # Redirect chain length > 1 must be rejected
            e3_id = "01J8Z000000000000000000103"
            redir_chain = {
                "opf_schema": "0.2",
                "id": pid,
                "edition_id": e3_id,
                "merged_into": e2["edition_id"],
                "merged_at": "2026-03-04",
            }
            (pdir / "editions" / f"{e3_id}.json").write_text(
                json.dumps(redir_chain, ensure_ascii=False), encoding="utf-8"
            )
            chain_errs = validate_product_dir(pdir, products_root=products_root)
            self.assertTrue(any("chain length must be 1" in e for e in chain_errs))
            (pdir / "editions" / f"{e3_id}.json").unlink()

            # Non-default track missing from product.json tracks[] must be rejected
            e_untracked = _make_base_edition(
                edition_id="01J8Z000000000000000000104",
                track="CN/plant:SC999",
                sodium="30",
            )
            (pdir / "editions" / f"{e_untracked['edition_id']}.json").write_text(
                json.dumps(e_untracked, ensure_ascii=False), encoding="utf-8"
            )
            track_errs = validate_product_dir(pdir, products_root=products_root)
            self.assertTrue(any("documented in product.json tracks[]" in e for e in track_errs))
            (pdir / "editions" / f"{e_untracked['edition_id']}.json").unlink()

            # Retracted edition referenced by supersedes[] must be rejected
            e_ret = _make_base_edition(
                edition_id="01J8Z000000000000000000105",
                sodium="40",
                lifecycle={"state": "retracted", "reason": "Bad upload", "evidence_refs": []},
            )
            e_sup_ret = _make_base_edition(
                edition_id="01J8Z000000000000000000106",
                sodium="41",
                supersedes=[e_ret["edition_id"]],
            )
            (pdir / "editions" / f"{e_ret['edition_id']}.json").write_text(
                json.dumps(e_ret, ensure_ascii=False), encoding="utf-8"
            )
            (pdir / "editions" / f"{e_sup_ret['edition_id']}.json").write_text(
                json.dumps(e_sup_ret, ensure_ascii=False), encoding="utf-8"
            )
            ret_errs = validate_product_dir(pdir, products_root=products_root)
            self.assertTrue(any("retracted edition" in e for e in ret_errs))


if __name__ == "__main__":
    unittest.main()
