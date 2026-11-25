"""Comprehensive JSON Schema (incl. oneOf), structural, patch-replay, and cross-edition validator for OPF v0.2."""

from __future__ import annotations

import copy
import json
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from opf.ids import (
    is_valid_ulid,
    product_dir_for_id,
    validate_product_id,
    validate_track_key,
)
from opf.ingredients import SPAN_KEYS, verify_ingredients_round_trip
from opf.normalize import (
    get_nutrients_registry,
    normalize_edition,
    nutrient_row_sort_key,
)
from opf.patches import (
    PatchError,
    _json_equal,
    apply_patch,
    extract_patchable_surface,
    invert_patch,
    parse_json_pointer,
)
from opf.registries import load_all_profiles
from opf.resources import get_resource_root

DECIMAL_RE = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$")
DATE_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}(-[0-9]{2})?$")
SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")
FINGERPRINT_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
OPF_MEDIA_RE = re.compile(r"^opf-media://sha256/([a-f0-9]{64})$")
VALID_PROVENANCES: tuple[str, ...] = (
    "maintainer",
    "external_contributor",
    "public_submission",
    "brand_owner",
    "partner",
)
AGREEMENT_REQUIRED_PROVENANCES: frozenset[str] = frozenset({"brand_owner", "partner"})


def public_image_sha(ev: dict[str, Any]) -> str:
    """Return the public (cropped, EXIF-stripped) image hash of an evidence item, if any."""
    return str(ev.get("cropped_sha256") or ev.get("sha256") or "")


FORBIDDEN_BATCH_KEYS = {
    "production_date",
    "expiry_date",
    "expiry_estimate",
    "purchase_date",
    "purchase_price",
    "lot_number",
    "batch_number",
}


@lru_cache(maxsize=8)
def load_json_schema(schema_name: str = "edition.v0.2.schema.json") -> dict[str, Any]:
    path = get_resource_root() / "spec" / "schema" / schema_name
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_ref(schema: dict[str, Any], root_schema: dict[str, Any]) -> dict[str, Any]:
    cur = schema
    while "$ref" in cur:
        ref = cur["$ref"]
        if not ref.startswith("#/$defs/"):
            raise ValueError(f"Unsupported $ref: {ref}")
        def_name = ref[len("#/$defs/") :]
        target = root_schema.get("$defs", {}).get(def_name)
        if not target:
            raise ValueError(f"Unresolved $ref: {ref}")
        cur = target
    return cur


def _branch_score(
    instance: Any,
    branch_schema: dict[str, Any],
    root_schema: dict[str, Any],
    errors: list[str],
) -> tuple[int, int, int]:
    """Rank failing oneOf branches so discriminator/const mismatches sort behind closest match."""
    resolved = _resolve_ref(branch_schema, root_schema)
    const_mismatches = 0
    missing_req = 0
    if isinstance(instance, dict) and resolved.get("type") == "object":
        props = resolved.get("properties", {})
        for k, prop_s in props.items():
            resolved_p = _resolve_ref(prop_s, root_schema)
            if "const" in resolved_p and k in instance:
                c = resolved_p["const"]
                if (type(instance[k]) is bool) != (type(c) is bool) or instance[k] != c:
                    const_mismatches += 1
        for rk in resolved.get("required", []):
            if rk not in instance:
                missing_req += 1
    elif resolved.get("type") == "null" and instance is not None:
        const_mismatches += 1
    return (const_mismatches, missing_req, len(errors))


def validate_against_json_schema(
    instance: Any,
    schema: dict[str, Any],
    root_schema: dict[str, Any] | None = None,
    path: str = "$",
) -> list[str]:
    """Zero-dependency validator for OPF JSON Schemas (Draft 2020-12 subset incl. oneOf)."""
    if root_schema is None:
        root_schema = schema
    errors: list[str] = []

    if "$ref" in schema:
        target_schema = _resolve_ref(schema, root_schema)
        return validate_against_json_schema(instance, target_schema, root_schema, path)

    if "oneOf" in schema:
        branches = schema["oneOf"]
        branch_errors = [
            validate_against_json_schema(instance, branch, root_schema, path)
            for branch in branches
        ]
        matched_indices = [idx for idx, errs in enumerate(branch_errors) if not errs]
        if len(matched_indices) > 1:
            return [f"{path}: value matched {len(matched_indices)} schemas in oneOf (expected exactly 1)"]
        if len(matched_indices) == 0:
            best_idx = min(
                range(len(branches)),
                key=lambda idx: _branch_score(instance, branches[idx], root_schema, branch_errors[idx]),
            )
            return branch_errors[best_idx]

    expected_type = schema.get("type")
    if expected_type == "null":
        if instance is not None:
            return [f"{path}: expected null, got {type(instance).__name__}"]
    elif expected_type == "object":
        if not isinstance(instance, dict):
            return [f"{path}: expected object, got {type(instance).__name__}"]
        req = schema.get("required", [])
        for r_key in req:
            if r_key not in instance:
                errors.append(f"{path}: missing required property {r_key!r}")
        props = schema.get("properties", {})
        add_props = schema.get("additionalProperties", True)
        for k, v in instance.items():
            if k in props:
                errors.extend(
                    validate_against_json_schema(v, props[k], root_schema, f"{path}.{k}")
                )
            elif add_props is False:
                errors.append(f"{path}: additional property {k!r} is not allowed by schema")
            elif isinstance(add_props, dict):
                errors.extend(
                    validate_against_json_schema(v, add_props, root_schema, f"{path}.{k}")
                )
    elif expected_type == "array":
        if not isinstance(instance, list):
            return [f"{path}: expected array, got {type(instance).__name__}"]
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None and len(instance) < min_items:
            errors.append(f"{path}: array length {len(instance)} < minItems {min_items}")
        if max_items is not None and len(instance) > max_items:
            errors.append(f"{path}: array length {len(instance)} > maxItems {max_items}")
        if schema.get("uniqueItems"):
            seen_items = {
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in instance
            }
            if len(seen_items) != len(instance):
                errors.append(f"{path}: array items must be unique")
        prefix_items = schema.get("prefixItems")
        if prefix_items:
            for idx, item_schema in enumerate(prefix_items):
                if idx < len(instance):
                    errors.extend(
                        validate_against_json_schema(
                            instance[idx], item_schema, root_schema, f"{path}[{idx}]"
                        )
                    )
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for idx, item in enumerate(instance):
                errors.extend(
                    validate_against_json_schema(
                        item, items_schema, root_schema, f"{path}[{idx}]"
                    )
                )
    elif expected_type == "string":
        if not isinstance(instance, str):
            return [f"{path}: expected string, got {type(instance).__name__}"]
        min_len = schema.get("minLength")
        if min_len is not None and len(instance) < min_len:
            errors.append(f"{path}: string length {len(instance)} < minLength {min_len}")
        pattern = schema.get("pattern")
        if pattern and not re.search(pattern, instance):
            errors.append(f"{path}: value {instance!r} does not match pattern {pattern!r}")
    elif expected_type == "integer":
        if isinstance(instance, bool) or not isinstance(instance, int):
            return [f"{path}: expected integer, got {type(instance).__name__}"]
        minimum = schema.get("minimum")
        if minimum is not None and instance < minimum:
            errors.append(f"{path}: integer {instance} < minimum {minimum}")
    elif expected_type == "boolean":
        if not isinstance(instance, bool):
            return [f"{path}: expected boolean, got {type(instance).__name__}"]

    if "const" in schema:
        expected_const = schema["const"]
        if (type(instance) is bool) != (type(expected_const) is bool) or instance != expected_const:
            errors.append(f"{path}: expected const {expected_const!r}, got {instance!r}")
    if "enum" in schema:
        if not any(
            (type(instance) is bool) == (type(opt) is bool) and instance == opt
            for opt in schema["enum"]
        ):
            errors.append(f"{path}: value {instance!r} not in enum {schema['enum']}")

    for sub_schema in schema.get("allOf") or []:
        if isinstance(sub_schema, dict):
            errors.extend(
                validate_against_json_schema(instance, sub_schema, root_schema, path)
            )

    if "if" in schema and isinstance(schema["if"], dict):
        cond_errs = validate_against_json_schema(instance, schema["if"], root_schema, path)
        if not cond_errs:
            if isinstance(schema.get("then"), dict):
                errors.extend(
                    validate_against_json_schema(instance, schema["then"], root_schema, path)
                )
        elif isinstance(schema.get("else"), dict):
            errors.extend(
                validate_against_json_schema(instance, schema["else"], root_schema, path)
            )

    return errors


def _check_no_forbidden_batch_keys(obj: Any, path: str, errors: list[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_BATCH_KEYS:
                errors.append(
                    f"{path}.{k}: Personal or batch-specific field {k!r} is forbidden in OPF public records"
                )
            _check_no_forbidden_batch_keys(v, f"{path}.{k}", errors)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _check_no_forbidden_batch_keys(item, f"{path}[{idx}]", errors)


def _check_no_spans_in_nodes(nodes: Any, path: str, errors: list[str]) -> None:
    if not isinstance(nodes, list):
        return
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        for sk in SPAN_KEYS:
            if sk in node:
                errors.append(f"{path}[{idx}].{sk}: core.ingredients_tree must be span-free")
        if "allergens" in node and isinstance(node["allergens"], list):
            algs = node["allergens"]
            if algs != sorted(set(algs)):
                errors.append(f"{path}[{idx}].allergens: must be sorted and unique")
        if "children" in node:
            _check_no_spans_in_nodes(node["children"], f"{path}[{idx}].children", errors)


def _validate_core_canonical_order(core: Any, prefix: str) -> list[str]:
    errs: list[str] = []
    if not isinstance(core, dict):
        return [f"{prefix}: core must be an object"]

    decl = core.get("nutrition_declared")
    if isinstance(decl, dict):
        rows = decl.get("rows")
        if isinstance(rows, list):
            seen_pairs: set[tuple[str, str]] = set()
            for r_idx, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                pair = (str(row.get("nutrient", "")), str(row.get("unit", "")))
                if pair in seen_pairs:
                    errs.append(f"{prefix}.nutrition_declared.rows[{r_idx}]: duplicate (nutrient, unit) {pair!r}")
                seen_pairs.add(pair)
            expected_rows = sorted(
                [r for r in rows if isinstance(r, dict)],
                key=nutrient_row_sort_key,
            )
            actual_pairs = [(r.get("nutrient"), r.get("unit")) for r in rows if isinstance(r, dict)]
            expected_pairs = [(r.get("nutrient"), r.get("unit")) for r in expected_rows]
            if actual_pairs != expected_pairs:
                errs.append(
                    f"{prefix}.nutrition_declared.rows: rows must be persisted in strict canonical §3 order "
                    f"(expected {expected_pairs}, got {actual_pairs})"
                )

    trees = core.get("ingredients_tree")
    if isinstance(trees, list):
        langs = [str(item.get("lang", "")) for item in trees if isinstance(item, dict)]
        if len(langs) != len(set(langs)):
            errs.append(f"{prefix}.ingredients_tree: duplicate language entries {langs!r}")
        elif langs != sorted(langs):
            errs.append(
                f"{prefix}.ingredients_tree: must be sorted lexicographically by lang (got {langs!r})"
            )

    ad = core.get("allergens_declared")
    if isinstance(ad, dict):
        for field in ("contains", "may_contain"):
            vals = ad.get(field)
            if isinstance(vals, list) and vals != sorted(set(vals)):
                errs.append(f"{prefix}.allergens_declared.{field}: must be sorted and unique")

    return errs


def validate_product_meta_doc(doc: dict[str, Any]) -> list[str]:
    """Validate a v0.2 product.json metadata document."""
    if not isinstance(doc, dict):
        return ["product.json root must be a JSON object"]

    errors: list[str] = []
    _check_no_forbidden_batch_keys(doc, "$", errors)
    errors.extend(validate_against_json_schema(doc, load_json_schema("product.v0.2.schema.json")))

    product_id = doc.get("id")
    if isinstance(product_id, str):
        errors.extend(validate_product_id(product_id))

    tracks = doc.get("tracks")
    if isinstance(tracks, list):
        seen_tracks: set[str] = set()
        for idx, tdef in enumerate(tracks):
            if not isinstance(tdef, dict):
                continue
            track_key = tdef.get("track")
            market = tdef.get("market")
            if isinstance(track_key, str):
                if track_key in seen_tracks:
                    errors.append(f"$.tracks[{idx}].track: duplicate track definition {track_key!r}")
                seen_tracks.add(track_key)
                for te in validate_track_key(track_key, allow_default=False):
                    errors.append(f"$.tracks[{idx}].track: {te}")
                if isinstance(market, str) and "/" in track_key:
                    expected_market = track_key.split("/", 1)[0]
                    if market != expected_market:
                        errors.append(
                            f"$.tracks[{idx}].market: expected {expected_market!r} matching track prefix, got {market!r}"
                        )
    return errors


def _validate_enrichment_op_on_state(state: dict[str, Any], op_obj: dict[str, Any], rev_num: int) -> list[str]:
    errs: list[str] = []
    if op_obj.get("op") != "add":
        return [
            f"revisions[rev={rev_num}]: enrichment revision only allows 'add' ops, got {op_obj.get('op')!r}"
        ]
    path = str(op_obj.get("path") or "")
    if not path.startswith("/attributes/"):
        return [
            f"revisions[rev={rev_num}]: enrichment op path {path!r} must target '/attributes/...'"
        ]
    tokens = parse_json_pointer(path)
    cur: Any = state
    for tok in tokens[:-1]:
        if isinstance(cur, dict) and tok in cur:
            cur = cur[tok]
        elif isinstance(cur, list) and tok.isdigit() and int(tok) < len(cur):
            cur = cur[int(tok)]
        else:
            return [f"revisions[rev={rev_num}]: missing parent path for {path!r}"]
    last = tokens[-1]
    if isinstance(cur, dict):
        if last in cur:
            errs.append(
                f"revisions[rev={rev_num}]: enrichment cannot overwrite existing attribute {path!r} (use errata)"
            )
    elif isinstance(cur, list):
        if last != "-" and last != str(len(cur)):
            errs.append(
                f"revisions[rev={rev_num}]: enrichment list op on {path!r} may only append at tail ('-' or index {len(cur)})"
            )
    else:
        errs.append(f"revisions[rev={rev_num}]: invalid parent container for enrichment path {path!r}")
    return errs


def _validate_revision_kind_paths(rev_entry: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    rev_num = rev_entry.get("rev")
    kind = rev_entry.get("kind")
    patch = rev_entry.get("patch") or []

    for op_idx, op_obj in enumerate(patch):
        if not isinstance(op_obj, dict):
            continue
        paths = [str(op_obj.get("path") or "")]
        if "from" in op_obj:
            paths.append(str(op_obj.get("from") or ""))

        for p in paths:
            if kind == "enrichment":
                if op_obj.get("op") != "add":
                    errs.append(
                        f"revisions[rev={rev_num}].patch[{op_idx}]: enrichment only permits 'add', got {op_obj.get('op')!r}"
                    )
                if not p.startswith("/attributes/"):
                    errs.append(
                        f"revisions[rev={rev_num}].patch[{op_idx}]: enrichment path {p!r} must be under '/attributes/...'"
                    )
            elif kind == "errata":
                if not (p == "/core" or p.startswith("/core/") or p == "/attributes" or p.startswith("/attributes/")):
                    errs.append(
                        f"revisions[rev={rev_num}].patch[{op_idx}]: errata path {p!r} may only target /core/... or /attributes/..."
                    )
            elif kind == "retrack":
                if p != "/track":
                    errs.append(
                        f"revisions[rev={rev_num}].patch[{op_idx}]: retrack path {p!r} may only target '/track'"
                    )
            elif kind == "lifecycle":
                if not (
                    p == "/supersedes"
                    or p.startswith("/supersedes/")
                    or p == "/lifecycle"
                    or p.startswith("/lifecycle/")
                ):
                    errs.append(
                        f"revisions[rev={rev_num}].patch[{op_idx}]: lifecycle path {p!r} may only target /supersedes or /lifecycle"
                    )
    return errs


def validate_edition_doc(doc: dict[str, Any]) -> list[str]:
    """Validate a single v0.2 EditionRecord or EditionRedirect JSON document."""
    if not isinstance(doc, dict):
        return ["Edition document root must be a JSON object"]

    errors: list[str] = []
    _check_no_forbidden_batch_keys(doc, "$", errors)
    errors.extend(validate_against_json_schema(doc, load_json_schema("edition.v0.2.schema.json")))

    product_id = doc.get("id")
    if isinstance(product_id, str):
        errors.extend(validate_product_id(product_id))

    edition_id = doc.get("edition_id")
    if isinstance(edition_id, str) and not is_valid_ulid(edition_id):
        errors.append(f"$.edition_id: invalid ULID {edition_id!r}")

    # EditionRedirect stub
    if "merged_into" in doc:
        if doc.get("merged_into") == edition_id:
            errors.append("$.merged_into: redirect cannot point to itself")
        return errors

    # EditionRecord checks
    track = doc.get("track")
    if isinstance(track, str):
        for te in validate_track_key(track, allow_default=True):
            errors.append(f"$.track: {te}")

    supersedes = doc.get("supersedes")
    if isinstance(supersedes, list):
        if edition_id in supersedes:
            errors.append("$.supersedes: an edition cannot supersede itself")
        if supersedes != sorted(set(supersedes)):
            errors.append("$.supersedes: must be sorted and unique")
        if (doc.get("lifecycle") or {}).get("state") == "retracted" and supersedes:
            errors.append("$.supersedes: a retracted edition must not have non-empty supersedes")

    profiles = load_all_profiles()
    nutrients_dict = get_nutrients_registry()

    core = doc.get("core")
    attributes = doc.get("attributes")
    profile_id = core.get("regulatory_profile") if isinstance(core, dict) else None
    can_normalize = False

    if isinstance(core, dict):
        if profile_id not in profiles:
            errors.append(f"$.core.regulatory_profile: unknown profile {profile_id!r}")
        else:
            can_normalize = True

        for nc_idx, nc in enumerate(core.get("net_content") or []):
            if isinstance(nc, dict) and "value" in nc:
                try:
                    if Decimal(str(nc["value"])) <= Decimal("0"):
                        errors.append(f"$.core.net_content[{nc_idx}].value: must be positive")
                except Exception:
                    errors.append(f"$.core.net_content[{nc_idx}].value: invalid decimal {nc['value']!r}")

        serving_size = core.get("serving_size")
        if isinstance(serving_size, dict) and "value" in serving_size:
            try:
                if Decimal(str(serving_size["value"])) <= Decimal("0"):
                    errors.append("$.core.serving_size.value: must be positive")
            except Exception:
                errors.append(f"$.core.serving_size.value: invalid decimal {serving_size['value']!r}")

        decl = core.get("nutrition_declared")
        if isinstance(decl, dict):
            basis = decl.get("basis")
            if isinstance(basis, dict) and "value" in basis:
                try:
                    if Decimal(str(basis["value"])) <= Decimal("0"):
                        errors.append("$.core.nutrition_declared.basis.value: must be positive")
                except Exception:
                    errors.append("$.core.nutrition_declared.basis.value: invalid decimal")

            rows = decl.get("rows")
            if isinstance(rows, list):
                for r_idx, row in enumerate(rows):
                    if not isinstance(row, dict):
                        continue
                    nid = row.get("nutrient")
                    unit = row.get("unit")
                    if nid not in nutrients_dict:
                        errors.append(
                            f"$.core.nutrition_declared.rows[{r_idx}]: unknown nutrient ID {nid!r}"
                        )
                        can_normalize = False
                    else:
                        allowed_u = nutrients_dict[nid]["allowed_units"]
                        if unit not in allowed_u:
                            errors.append(
                                f"$.core.nutrition_declared.rows[{r_idx}]: unit {unit!r} not in {allowed_u} for {nid}"
                            )
                            can_normalize = False

        errors.extend(_validate_core_canonical_order(core, "$.core"))

        # Check span-free AST + language parity + lossless round-trip
        trees = core.get("ingredients_tree") or []
        ing_texts = (attributes.get("ingredients_text") or []) if isinstance(attributes, dict) else []
        tree_by_lang: dict[str, Any] = {}
        text_by_lang: dict[str, Any] = {}

        for item in trees:
            if isinstance(item, dict) and "lang" in item:
                lang = item["lang"]
                tree_by_lang[lang] = item.get("nodes")
                _check_no_spans_in_nodes(item.get("nodes"), f"$.core.ingredients_tree[{lang}]", errors)

        for item in ing_texts:
            if isinstance(item, dict) and "lang" in item:
                lang = item["lang"]
                if lang in text_by_lang:
                    errors.append(f"$.attributes.ingredients_text: duplicate language {lang!r}")
                text_by_lang[lang] = item.get("text")

        if set(tree_by_lang.keys()) != set(text_by_lang.keys()):
            missing_in_tree = sorted(set(text_by_lang.keys()) - set(tree_by_lang.keys()))
            missing_in_text = sorted(set(tree_by_lang.keys()) - set(text_by_lang.keys()))
            if missing_in_tree:
                errors.append(
                    f"$.core.ingredients_tree: missing language(s) declared in attributes.ingredients_text: {missing_in_tree}"
                )
            if missing_in_text:
                errors.append(
                    f"$.attributes.ingredients_text: missing raw text for language(s) in core.ingredients_tree: {missing_in_text}"
                )
        elif profile_id in profiles:
            for lang, raw_text in text_by_lang.items():
                if isinstance(raw_text, str):
                    for rte in verify_ingredients_round_trip(
                        raw_text, tree_by_lang[lang], profile_id=profile_id
                    ):
                        errors.append(f"$.core.ingredients_tree[{lang}]: {rte}")

    # Evidence checks
    evidence_list = doc.get("evidence")
    evidence_ids: set[str] = set()
    if isinstance(evidence_list, list):
        for e_idx, ev in enumerate(evidence_list):
            if not isinstance(ev, dict):
                continue
            if "provenance" not in ev:
                errors.append(
                    f"$.evidence[{e_idx}].provenance: migration required — set 'provenance' to one of {list(VALID_PROVENANCES)} (use updated `opf` tooling)."
                )
            elif ev.get("provenance") in AGREEMENT_REQUIRED_PROVENANCES and not str(ev.get("agreement_ref") or "").strip():
                errors.append(
                    f"$.evidence[{e_idx}].agreement_ref: provenance={ev.get('provenance')!r} requires a non-empty internal agreement_ref identifier"
                )
            if ev.get("transcription") == "independent_match" and ev.get("provenance") != "maintainer":
                errors.append(
                    f"$.evidence[{e_idx}].transcription: 'independent_match' requires provenance='maintainer'"
                )
            ev_id = ev.get("evidence_id")
            if isinstance(ev_id, str):
                if ev_id in evidence_ids:
                    errors.append(f"$.evidence[{e_idx}].evidence_id: duplicate evidence_id {ev_id!r}")
                evidence_ids.add(ev_id)

            etype = ev.get("type")
            if etype == "label_photo":
                sha = str(ev.get("cropped_sha256") or "")
                mref = str(ev.get("media_ref") or "")
                if not SHA256_HEX_RE.match(sha) or not mref:
                    errors.append(
                        f"$.evidence[{e_idx}]: label_photo requires 64-char hex cropped_sha256 and non-empty media_ref"
                    )
                else:
                    expected_id = f"sha256:{sha}"
                    if ev_id != expected_id:
                        errors.append(
                            f"$.evidence[{e_idx}].evidence_id: label_photo evidence_id must equal {expected_id!r}, got {ev_id!r}"
                        )
                    m_media = OPF_MEDIA_RE.match(mref)
                    if mref.startswith("opf-media://"):
                        if not m_media:
                            errors.append(
                                f"$.evidence[{e_idx}].media_ref: malformed {mref!r}; expected opf-media://sha256/<64 hex>"
                            )
                        elif m_media.group(1) != sha:
                            errors.append(
                                f"$.evidence[{e_idx}].media_ref: {mref!r} does not match cropped_sha256 {sha!r}"
                            )
            else:
                snap = ev.get("snapshot_sha256")
                if snap and isinstance(ev_id, str) and ev_id.startswith("sha256:"):
                    if ev_id != f"sha256:{snap}":
                        errors.append(
                            f"$.evidence[{e_idx}].evidence_id: sha256 evidence_id {ev_id!r} must match snapshot_sha256 {snap!r}"
                        )

    lifecycle = doc.get("lifecycle")
    if isinstance(lifecycle, dict):
        for ref in lifecycle.get("evidence_refs") or []:
            if ref not in evidence_ids:
                errors.append(f"$.lifecycle.evidence_refs: unknown evidence_id {ref!r}")

    # Revisions & deterministic patch/reverse_patch replay checks
    top_rev = doc.get("rev")
    revisions = doc.get("revisions")
    if isinstance(top_rev, int) and not isinstance(top_rev, bool) and isinstance(revisions, list):
        if len(revisions) != top_rev:
            errors.append(
                f"$.revisions: expected {top_rev} revision entries matching top-level rev, got {len(revisions)}"
            )
        else:
            rev_ok = True
            for idx, r_entry in enumerate(revisions):
                expected_rev = idx + 1
                if not isinstance(r_entry, dict):
                    errors.append(f"$.revisions[{idx}]: must be an object")
                    rev_ok = False
                    continue
                if "provenance" not in r_entry:
                    errors.append(
                        f"$.revisions[{idx}].provenance: migration required — set 'provenance' to one of {list(VALID_PROVENANCES)} (use updated `opf` tooling)."
                    )
                elif r_entry.get("provenance") in AGREEMENT_REQUIRED_PROVENANCES and not str(r_entry.get("agreement_ref") or "").strip():
                    errors.append(
                        f"$.revisions[{idx}].agreement_ref: provenance={r_entry.get('provenance')!r} requires a non-empty internal agreement_ref identifier"
                    )
                if r_entry.get("rev") != expected_rev:
                    errors.append(
                        f"$.revisions[{idx}].rev: expected sequential rev {expected_rev}, got {r_entry.get('rev')!r}"
                    )
                    rev_ok = False
                for ev_ref in r_entry.get("evidence_refs") or []:
                    if ev_ref not in evidence_ids:
                        errors.append(
                            f"$.revisions[{idx}].evidence_refs: unknown evidence_id {ev_ref!r}"
                        )
                kind = r_entry.get("kind")
                patch = r_entry.get("patch")
                rev_patch = r_entry.get("reverse_patch")
                if expected_rev == 1:
                    if kind != "initial":
                        errors.append("$.revisions[0].kind: rev 1 must have kind 'initial'")
                    if patch != []:
                        errors.append("$.revisions[0].patch: rev 1 must have empty patch []")
                    if "reverse_patch" in r_entry:
                        errors.append("$.revisions[0].reverse_patch: rev 1 must not have reverse_patch")
                else:
                    if kind == "initial":
                        errors.append(f"$.revisions[{idx}].kind: 'initial' only allowed at rev 1")
                    if not isinstance(patch, list) or not patch:
                        errors.append(f"$.revisions[{idx}].patch: rev {expected_rev} requires non-empty patch")
                        rev_ok = False
                    if not isinstance(rev_patch, list) or not rev_patch:
                        errors.append(
                            f"$.revisions[{idx}].reverse_patch: rev {expected_rev} requires non-empty reverse_patch"
                        )
                        rev_ok = False
                    errors.extend(_validate_revision_kind_paths(r_entry))

            if rev_ok and top_rev >= 2:
                states: dict[int, dict[str, Any]] = {top_rev: extract_patchable_surface(doc)}
                backward_ok = True
                for r in range(top_rev, 1, -1):
                    r_entry = revisions[r - 1]
                    try:
                        prev_state = apply_patch(states[r], r_entry["reverse_patch"])
                    except PatchError as exc:
                        errors.append(
                            f"$.revisions[{r - 1}].reverse_patch: failed applying reverse_patch at rev {r}: {exc}"
                        )
                        backward_ok = False
                        break
                    if not isinstance(prev_state, dict):
                        errors.append(f"$.revisions[{r - 1}]: reconstructed state S_{r - 1} is not an object")
                        backward_ok = False
                        break
                    states[r - 1] = prev_state
                    # Every intermediate state S_k must preserve §3/§8.2 canonical order
                    if "core" in prev_state:
                        errors.extend(
                            _validate_core_canonical_order(prev_state["core"], f"S_{r - 1}.core")
                        )
                    if "supersedes" in prev_state and isinstance(prev_state["supersedes"], list):
                        sups = prev_state["supersedes"]
                        if sups != sorted(set(sups)):
                            errors.append(f"S_{r - 1}.supersedes: must remain sorted and unique")

                if backward_ok:
                    for r in range(2, top_rev + 1):
                        r_entry = revisions[r - 1]
                        s_before = states[r - 1]
                        # Validate enrichment op preconditions step-by-step against S_{r-1}
                        if r_entry.get("kind") == "enrichment":
                            sim = copy.deepcopy(s_before)
                            for op_obj in r_entry["patch"]:
                                e_errs = _validate_enrichment_op_on_state(sim, op_obj, r)
                                errors.extend(e_errs)
                                if not e_errs:
                                    try:
                                        sim = apply_patch(sim, [op_obj], in_place=True)
                                    except PatchError:
                                        break
                        try:
                            s_after_fwd = apply_patch(s_before, r_entry["patch"])
                        except PatchError as exc:
                            errors.append(
                                f"$.revisions[{r - 1}].patch: forward patch failed from S_{r - 1}: {exc}"
                            )
                            continue
                        if not _json_equal(s_after_fwd, states[r]):
                            errors.append(
                                f"$.revisions[{r - 1}]: forward patch from S_{r - 1} does not reproduce S_{r}"
                            )
                            continue
                        try:
                            expected_inv = invert_patch(s_before, r_entry["patch"])
                        except PatchError as exc:
                            errors.append(
                                f"$.revisions[{r - 1}].patch: cannot invert patch on S_{r - 1}: {exc}"
                            )
                            continue
                        if not _json_equal(r_entry["reverse_patch"], expected_inv):
                            errors.append(
                                f"$.revisions[{r - 1}].reverse_patch: non-canonical or hand-written reverse_patch rejected "
                                f"(expected {expected_inv}, got {r_entry['reverse_patch']})"
                            )

    # Deterministic normalized / quality_flags / fingerprints consistency check
    if can_normalize and not _validate_core_canonical_order(core, "$.core"):
        try:
            recomputed = copy.deepcopy(doc)
            normalize_edition(recomputed)
            if not _json_equal(doc.get("normalized"), recomputed["normalized"]):
                errors.append(
                    f"$.normalized: does not match deterministic output of `opf normalize` "
                    f"(expected {recomputed['normalized']}, got {doc.get('normalized')})"
                )
            if not _json_equal(doc.get("quality_flags"), recomputed["quality_flags"]):
                errors.append(
                    f"$.quality_flags: does not match deterministic output of `opf normalize` "
                    f"(expected {recomputed['quality_flags']}, got {doc.get('quality_flags')})"
                )
            if doc.get("core_fingerprint") != recomputed["core_fingerprint"]:
                errors.append(
                    f"$.core_fingerprint: expected {recomputed['core_fingerprint']!r}, got {doc.get('core_fingerprint')!r}"
                )
            if doc.get("label_fingerprint") != recomputed["label_fingerprint"]:
                errors.append(
                    f"$.label_fingerprint: expected {recomputed['label_fingerprint']!r}, got {doc.get('label_fingerprint')!r}"
                )
        except Exception as exc:
            errors.append(f"Normalization failed: {exc}")

    return errors


def _has_supersedes_cycle(records: dict[str, dict[str, Any]]) -> bool:
    state: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=done

    def _dfs(node: str) -> bool:
        state[node] = 1
        for nxt in records[node].get("supersedes") or []:
            if nxt not in records:
                continue
            st = state.get(nxt, 0)
            if st == 1:
                return True
            if st == 0 and _dfs(nxt):
                return True
        state[node] = 2
        return False

    return any(state.get(eid, 0) == 0 and _dfs(eid) for eid in records)


def _reachable_ancestors(records: dict[str, dict[str, Any]], start: str) -> set[str]:
    visited: set[str] = set()
    stack = list(records[start].get("supersedes") or [])
    while stack:
        cur = stack.pop()
        if cur in visited or cur not in records:
            continue
        visited.add(cur)
        stack.extend(records[cur].get("supersedes") or [])
    return visited


def validate_product_dir(product_dir: Path, products_root: Path | None = None) -> list[str]:
    """Validate a v0.2 product directory (product.json + editions/*.json + cross-edition invariants)."""
    pdir = Path(product_dir)
    errors: list[str] = []
    meta_path = pdir / "product.json"
    if not meta_path.is_file():
        return [f"{pdir}: missing product.json"]

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"{meta_path}: failed to parse JSON: {exc}"]

    for err in validate_product_meta_doc(meta):
        errors.append(f"{meta_path}: {err}")

    product_id = meta.get("id")
    if products_root is not None and isinstance(product_id, str) and not validate_product_id(product_id):
        expected_dir = product_dir_for_id(Path(products_root), product_id).resolve()
        if pdir.resolve() != expected_dir:
            errors.append(
                f"{pdir}: directory path does not match canonical location {expected_dir} for {product_id!r}"
            )

    editions_dir = pdir / "editions"
    if not editions_dir.is_dir():
        errors.append(f"{pdir}: missing editions/ directory")
        return errors

    edition_files = sorted(editions_dir.glob("*.json"))
    if not edition_files:
        errors.append(f"{editions_dir}: must contain at least one edition JSON file")
        return errors

    records: dict[str, dict[str, Any]] = {}
    redirects: dict[str, dict[str, Any]] = {}

    for ef in edition_files:
        try:
            edoc = json.loads(ef.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{ef}: failed to parse JSON: {exc}")
            continue

        for err in validate_edition_doc(edoc):
            errors.append(f"{ef}: {err}")

        eid = edoc.get("edition_id")
        if eid != ef.stem:
            errors.append(f"{ef}: filename stem {ef.stem!r} must match edition_id {eid!r}")
        if product_id is not None and edoc.get("id") != product_id:
            errors.append(
                f"{ef}: edition id {edoc.get('id')!r} does not match product.json id {product_id!r}"
            )
        if isinstance(eid, str):
            if "merged_into" in edoc:
                redirects[eid] = edoc
            else:
                records[eid] = edoc

    if not records:
        errors.append(f"{editions_dir}: must contain at least one non-redirect EditionRecord")
        return errors

    defined_tracks = {
        t["track"]
        for t in (meta.get("tracks") or [])
        if isinstance(t, dict) and isinstance(t.get("track"), str)
    }
    for eid, rec in records.items():
        track = rec.get("track")
        if isinstance(track, str) and not track.endswith("/default") and track not in defined_tracks:
            errors.append(
                f"{editions_dir / f'{eid}.json'}: non-default track {track!r} must be documented in product.json tracks[]"
            )

    # Validate EditionRedirects (chain length == 1, pointing directly to live EditionRecord)
    for eid, redir in redirects.items():
        target = redir.get("merged_into")
        ef_path = editions_dir / f"{eid}.json"
        if target in redirects:
            errors.append(
                f"{ef_path}: merged_into {target!r} points to another EditionRedirect (chain length must be 1, no cycles)"
            )
        elif target not in records:
            errors.append(
                f"{ef_path}: merged_into target {target!r} does not exist as a live EditionRecord in {editions_dir}"
            )
        else:
            m_rev = redir.get("merged_into_rev")
            if isinstance(m_rev, int) and m_rev > records[target].get("rev", 0):
                errors.append(
                    f"{ef_path}: merged_into_rev {m_rev} exceeds target {target!r} current rev {records[target].get('rev')}"
                )

    # Validate supersedes graph (DAG, targets exist, retracted isolation)
    for eid, rec in records.items():
        ef_path = editions_dir / f"{eid}.json"
        for target in rec.get("supersedes") or []:
            if target in redirects:
                errors.append(
                    f"{ef_path}: supersedes target {target!r} is an EditionRedirect; point to canonical EditionRecord instead"
                )
            elif target not in records:
                errors.append(
                    f"{ef_path}: supersedes target {target!r} not found in {editions_dir}"
                )
            elif (records[target].get("lifecycle") or {}).get("state") == "retracted":
                errors.append(
                    f"{ef_path}: retracted edition {target!r} cannot appear in supersedes[]"
                )

    has_cycle = _has_supersedes_cycle(records)
    if has_cycle:
        errors.append(f"{pdir}: cycle detected in supersedes graph")

    # Check duplicate core_fingerprint on same (id, track) among non-retracted EditionRecords
    if not has_cycle:
        by_track_fp: dict[tuple[str, str], list[str]] = {}
        ancestors_cache: dict[str, set[str]] = {}
        for eid, rec in records.items():
            if (rec.get("lifecycle") or {}).get("state") == "retracted":
                continue
            key = (str(rec.get("track") or ""), str(rec.get("core_fingerprint") or ""))
            by_track_fp.setdefault(key, []).append(eid)

        for (track, fp), group in sorted(by_track_fp.items()):
            if len(group) < 2:
                continue
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    e1, e2 = group[i], group[j]
                    anc1 = ancestors_cache.setdefault(e1, _reachable_ancestors(records, e1))
                    anc2 = ancestors_cache.setdefault(e2, _reachable_ancestors(records, e2))
                    if e2 not in anc1 and e1 not in anc2:
                        errors.append(
                            f"{pdir}: duplicate core_fingerprint {fp} on track {track!r} between {e1} and {e2} "
                            "without supersedes relation; consolidate via EditionRedirect (merged_into)"
                        )

    return errors


def validate_products_root(products_root: Path, allow_empty: bool = False) -> list[str]:
    """Validate an entire v0.2 products/ tree, rejecting stray or orphan JSON files."""
    root = Path(products_root)
    if not root.exists():
        return [f"Products directory does not exist: {root}"]
    if not root.is_dir():
        return [f"Products path is not a directory: {root}"]

    product_jsons = sorted(root.rglob("product.json"))
    all_jsons = sorted(root.rglob("*.json"))
    if not product_jsons and not all_jsons:
        return [] if allow_empty else [f"{root}: no product.json files found"]

    errors: list[str] = []
    seen_ids: dict[str, Path] = {}
    accounted_files: set[Path] = set()
    for pjson in product_jsons:
        pdir = pjson.parent
        accounted_files.add(pjson.resolve())
        editions_dir = pdir / "editions"
        if editions_dir.is_dir():
            for ef in editions_dir.glob("*.json"):
                accounted_files.add(ef.resolve())
        errors.extend(validate_product_dir(pdir, products_root=root))
        try:
            meta = json.loads(pjson.read_text(encoding="utf-8"))
            pid = meta.get("id")
            if isinstance(pid, str):
                if pid in seen_ids:
                    errors.append(
                        f"{pjson}: duplicate product id {pid!r} (already seen at {seen_ids[pid]})"
                    )
                else:
                    seen_ids[pid] = pjson
        except Exception:
            pass

    for jf in all_jsons:
        if jf.resolve() not in accounted_files:
            errors.append(
                f"{jf}: orphan JSON file does not belong to any valid product directory "
                "(expected <product_dir>/product.json or <product_dir>/editions/<edition_id>.json)"
            )
    return errors


def validate_product_doc(doc: dict[str, Any]) -> list[str]:
    """Dispatch v0.2 document validation based on document shape (kept for transitional imports)."""
    if not isinstance(doc, dict):
        return ["Document root must be a JSON object"]
    if "edition_id" in doc:
        return validate_edition_doc(doc)
    if "opf_schema" in doc and doc.get("opf_schema") == "0.2":
        return validate_product_meta_doc(doc)
    return ["Unsupported document schema version (expected v0.2 product.json or editions/<ulid>.json)"]
