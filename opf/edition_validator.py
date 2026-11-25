"""Document-level semantic, canonical order, round-trip, and revision patch-replay validators for OPF v0.3."""

from __future__ import annotations

import copy
import json
import re
from decimal import Decimal
from typing import Any

from opf.fingerprints import (
    canonicalize_special_indicator,
    get_nutrients_registry,
    nutrient_row_sort_key,
)
from opf.ids import is_valid_ulid, validate_product_id, validate_track_key
from opf.ingredients import SPAN_KEYS, verify_ingredients_round_trip
from opf.json_schema import load_json_schema, validate_against_json_schema
from opf.normalize import normalize_edition
from opf.patches import (
    PatchError,
    _json_equal,
    apply_patch,
    extract_patchable_surface,
    invert_patch,
    parse_json_pointer,
)
from opf.registries import load_all_profiles

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

FORBIDDEN_BATCH_KEYS = {
    "production_date",
    "expiry_date",
    "expiry_estimate",
    "purchase_date",
    "purchase_price",
    "lot_number",
    "batch_number",
}


def public_image_sha(ev: dict[str, Any]) -> str:
    """Return the public (cropped, EXIF-stripped) image hash of an evidence item, if any."""
    return str(ev.get("cropped_sha256") or ev.get("sha256") or "")


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

    inds = core.get("special_indicators")
    if isinstance(inds, list):
        seen_inds: set[str] = set()
        for idx, ind in enumerate(inds):
            if not isinstance(ind, dict):
                continue
            try:
                canon = canonicalize_special_indicator(ind)
                sig = json.dumps(canon, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if sig in seen_inds:
                    errs.append(f"{prefix}.special_indicators[{idx}]: duplicate indicator entry {canon!r}")
                seen_inds.add(sig)
            except Exception as exc:
                errs.append(f"{prefix}.special_indicators[{idx}]: {exc}")

    return errs


def validate_product_meta_doc(doc: dict[str, Any]) -> list[str]:
    """Validate a v0.3 product.json metadata document."""
    if not isinstance(doc, dict):
        return ["product.json root must be a JSON object"]

    errors: list[str] = []
    _check_no_forbidden_batch_keys(doc, "$", errors)
    errors.extend(validate_against_json_schema(doc, load_json_schema("product.v0.3.schema.json")))

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
    """Validate a single v0.3 EditionRecord or EditionRedirect JSON document."""
    if not isinstance(doc, dict):
        return ["Edition document root must be a JSON object"]

    errors: list[str] = []
    _check_no_forbidden_batch_keys(doc, "$", errors)
    errors.extend(validate_against_json_schema(doc, load_json_schema("edition.v0.3.schema.json")))

    product_id = doc.get("id")
    if isinstance(product_id, str):
        errors.extend(validate_product_id(product_id))

    edition_id = doc.get("edition_id")
    if isinstance(edition_id, str) and not is_valid_ulid(edition_id):
        errors.append(f"$.edition_id: invalid ULID {edition_id!r}")

    if "merged_into" in doc:
        if doc.get("merged_into") == edition_id:
            errors.append("$.merged_into: redirect cannot point to itself")
        return errors

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
        if decl is None:
            ex = core.get("nutrition_exemption")
            if not isinstance(ex, dict) or not str(ex.get("category") or "").strip():
                errors.append(
                    "$.core.nutrition_exemption: required with valid category when nutrition_declared is null"
                )
        elif isinstance(decl, dict):
            if core.get("nutrition_exemption") is not None:
                errors.append(
                    "$.core.nutrition_exemption: forbidden when nutrition_declared is non-null"
                )
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

        for s_idx, ind in enumerate(core.get("special_indicators") or []):
            if not isinstance(ind, dict):
                continue
            try:
                canon = canonicalize_special_indicator(ind)
                if not _json_equal(ind, canon):
                    errors.append(
                        f"$.core.special_indicators[{s_idx}]: not in canonical form (expected {canon}, got {ind})"
                    )
            except Exception as exc:
                errors.append(f"$.core.special_indicators[{s_idx}]: {exc}")

        errors.extend(_validate_core_canonical_order(core, "$.core"))

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
