"""Command-line interface for OpenPackagedFood (opf v0.2)."""

from __future__ import annotations

import argparse
import copy
import functools
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opf import __version__
from opf.builder import build_static_api
from opf.ids import (
    generate_ulid,
    is_valid_ulid,
    product_dir_for_id,
    validate_product_id,
    validate_track_key,
)
from opf.ingredients import (
    annotate_ingredients_spans,
    parse_ingredients_semantic,
    verify_ingredients_round_trip,
)
from opf.media import (
    CANONICAL_EVIDENCE_REGIONS,
    FORBIDDEN_FRONT_REGIONS,
    LEGACY_REGION_ALIASES,
    normalize_evidence_region,
    process_cropped_label_to_webp,
    sanitize_and_hash_image,
    validate_media_repo,
)
from opf.normalize import (
    derive_evidence_level,
    format_canonical_decimal,
    normalize_edition,
)
from opf.patches import (
    apply_patch,
    diff_to_patch,
    extract_patchable_surface,
    invert_patch,
)
from opf.validator import (
    FORBIDDEN_BATCH_KEYS,
    load_json_schema,
    validate_against_json_schema,
    validate_edition_doc,
    validate_product_dir,
    validate_product_doc,
    validate_products_root,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_ymd() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _strip_forbidden_keys_in_place(obj: Any) -> list[str]:
    removed: list[str] = []
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            if k in FORBIDDEN_BATCH_KEYS:
                removed.append(k)
                del obj[k]
            else:
                removed.extend(_strip_forbidden_keys_in_place(obj[k]))
    elif isinstance(obj, list):
        for item in obj:
            removed.extend(_strip_forbidden_keys_in_place(item))
    return removed


def _load_existing_product_dir(
    out_root: Path, product_id: str
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    """Load existing product.json + editions/*.json into memory, or return fresh empty state."""
    pdir = product_dir_for_id(out_root, product_id)
    if not pdir.exists():
        return {"opf_schema": "0.2", "id": product_id}, {}, {}, []

    meta_path = pdir / "product.json"
    if not meta_path.is_file():
        return {}, {}, {}, [f"{pdir}: existing product directory is missing product.json"]

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, {}, {}, [f"{meta_path}: failed to parse JSON: {exc}"]

    records: dict[str, dict[str, Any]] = {}
    redirects: dict[str, dict[str, Any]] = {}
    editions_dir = pdir / "editions"
    if editions_dir.is_dir():
        for ef in sorted(editions_dir.glob("*.json")):
            try:
                edoc = json.loads(ef.read_text(encoding="utf-8"))
            except Exception as exc:
                return {}, {}, {}, [f"{ef}: failed to parse JSON: {exc}"]
            eid = edoc.get("edition_id") or ef.stem
            if "merged_into" in edoc:
                redirects[eid] = edoc
            else:
                records[eid] = edoc
    return meta, records, redirects, []


def _commit_validated_product_dir(
    out_root: Path,
    product_id: str,
    product_meta: dict[str, Any],
    records: dict[str, dict[str, Any]],
    redirects: dict[str, dict[str, Any]],
) -> list[str]:
    """Validate full product directory in an isolated temp dir before writing anything to out_root."""
    rel_dir = product_dir_for_id(Path("."), product_id)
    with tempfile.TemporaryDirectory(prefix="opf-stage-") as tmp:
        stage_root = Path(tmp)
        stage_pdir = stage_root / rel_dir
        stage_editions = stage_pdir / "editions"
        stage_editions.mkdir(parents=True, exist_ok=True)
        _write_json(stage_pdir / "product.json", product_meta)
        for eid, rec in records.items():
            _write_json(stage_editions / f"{eid}.json", rec)
        for eid, redir in redirects.items():
            _write_json(stage_editions / f"{eid}.json", redir)

        errs = validate_product_dir(stage_pdir, products_root=stage_root)
        if errs:
            return errs

    target_pdir = out_root / rel_dir
    target_editions = target_pdir / "editions"
    target_editions.mkdir(parents=True, exist_ok=True)
    _write_json(target_pdir / "product.json", product_meta)
    for eid, rec in records.items():
        _write_json(target_editions / f"{eid}.json", rec)
    for eid, redir in redirects.items():
        _write_json(target_editions / f"{eid}.json", redir)
    return []


def cmd_validate(args: argparse.Namespace) -> int:
    total_errors = 0
    results: list[dict[str, Any]] = []

    for raw in args.paths:
        p = Path(raw)
        if not p.exists():
            errs = [f"Path does not exist: {p}"]
            total_errors += 1
            results.append({"path": str(p), "kind": "missing", "valid": False, "errors": errs})
        elif p.is_dir() and (p / "product.json").is_file():
            errs = validate_product_dir(p)
            total_errors += len(errs)
            results.append({"path": str(p), "kind": "product_dir", "valid": not errs, "errors": errs})
        elif p.is_dir():
            errs = validate_products_root(p, allow_empty=bool(getattr(args, "allow_empty", False)))
            total_errors += len(errs)
            results.append({"path": str(p), "kind": "products_root", "valid": not errs, "errors": errs})
        else:
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                errs = [f"Failed to parse JSON: {exc}"]
                total_errors += 1
                results.append({"path": str(p), "kind": "file", "valid": False, "errors": errs})
                continue

            if isinstance(doc, dict) and "resolution" in doc and doc.get("opf_schema") == "0.2":
                errs = validate_against_json_schema(doc, load_json_schema("compact.v0.2.schema.json"))
            else:
                errs = validate_product_doc(doc)
            total_errors += len(errs)
            results.append(
                {
                    "path": str(p),
                    "id": doc.get("id") if isinstance(doc, dict) else None,
                    "kind": "file",
                    "valid": not errs,
                    "errors": errs,
                }
            )

    if args.json:
        print(json.dumps({"valid": total_errors == 0, "results": results}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            if r["valid"]:
                label = r.get("id") or r["kind"]
                print(f"OK   {r['path']} ({label})")
            else:
                print(f"FAIL {r['path']}:", file=sys.stderr)
                for e in r["errors"]:
                    print(f"  - {e}", file=sys.stderr)

    return 0 if total_errors == 0 else 1


def _collect_edition_files_for_normalize(paths: list[str]) -> list[Path]:
    result: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for jf in sorted(p.rglob("*.json")):
                if jf.name == "product.json":
                    continue
                result.append(jf)
        else:
            result.append(p)
    return result


def cmd_normalize(args: argparse.Namespace) -> int:
    files = _collect_edition_files_for_normalize(args.paths)
    if not files:
        print("No edition JSON files found to normalize.", file=sys.stderr)
        return 1

    processed = 0
    for fpath in files:
        try:
            doc = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Failed to parse {fpath}: {exc}", file=sys.stderr)
            return 1

        if not isinstance(doc, dict) or "merged_into" in doc or "core" not in doc:
            continue

        processed += 1
        core = doc["core"]
        attrs = doc.get("attributes") or {}
        profile_id = core["regulatory_profile"]
        if args.parse_ingredients or not core.get("ingredients_tree"):
            trees = []
            for item in attrs.get("ingredients_text", []):
                nodes = parse_ingredients_semantic(
                    item["text"], lang=item["lang"], profile_id=profile_id
                )
                trees.append({"lang": item["lang"], "nodes": nodes})
            core["ingredients_tree"] = sorted(trees, key=lambda x: str(x["lang"]))

        try:
            normalize_edition(doc)
        except ValueError as exc:
            print(f"Normalization error in {fpath}: {exc}", file=sys.stderr)
            return 1
        errs = validate_edition_doc(doc)
        if errs:
            print(f"Validation failed after normalizing {fpath}:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 1

        if args.in_place:
            _write_json(fpath, doc)
            print(f"Normalized {fpath} ({doc['id']} @ {doc['edition_id']})")
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))

    if processed == 0:
        print("No live EditionRecord JSON files found to normalize.", file=sys.stderr)
        return 1
    return 0


def cmd_parse_ingredients(args: argparse.Namespace) -> int:
    nodes = parse_ingredients_semantic(args.text, lang=args.lang, profile_id=args.profile)
    errs = verify_ingredients_round_trip(args.text, nodes, profile_id=args.profile)
    out_nodes = (
        annotate_ingredients_spans(args.text, nodes, profile_id=args.profile)
        if getattr(args, "with_spans", False) and not errs
        else nodes
    )
    out = {
        "lang": args.lang,
        "profile": args.profile,
        "round_trip_valid": len(errs) == 0,
        "errors": errs,
        "nodes": out_nodes,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if errs:
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    try:
        meta = build_static_api(
            data_dir,
            out_dir,
            canonical_base=args.canonical_base,
            media_base_url=getattr(args, "media_base_url", ""),
        )
    except Exception as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Built static API v1 in {out_dir} ({meta['total_products']} products, "
        f"resolutions: {meta['counts_by_resolution']}, evidence: {meta['counts_by_evidence_level']})"
    )
    return 0


def _canon_party_set(parties: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for p in parties:
        cleaned = {k: str(v).strip() for k, v in p.items() if v is not None and str(v).strip()}
        out.add(json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return out


def _canon_special_indicators_set(items: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for it in items:
        q = it.get("qualifier") or "="
        norm = {
            "name": str(it.get("name", "")).strip(),
            "qualifier": q,
            "value": format_canonical_decimal(it["value"]),
            "unit": str(it.get("unit", "")).strip(),
        }
        out.add(json.dumps(norm, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return out


def _plan_attribute_merge(
    existing_attrs: dict[str, Any],
    incoming_attrs: dict[str, Any],
    *,
    ignore_same_lang_ing_punct: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Compute enrichment-only RFC 6902 add ops and detect conflicting non-empty attributes."""
    ops: list[dict[str, Any]] = []
    conflicts: list[str] = []

    for key in sorted(incoming_attrs.keys()):
        inc_val = incoming_attrs[key]
        if inc_val is None or inc_val == "" or inc_val == [] or inc_val == {}:
            continue

        if key not in existing_attrs:
            ops.append({"op": "add", "path": f"/attributes/{key}", "value": copy.deepcopy(inc_val)})
            continue

        ex_val = existing_attrs[key]

        if key in ("product_name", "ingredients_text"):
            by_lang = {item["lang"]: item["text"] for item in ex_val if isinstance(item, dict)}
            next_idx = len(ex_val)
            for item in inc_val:
                lang = item["lang"]
                text = item["text"]
                if lang not in by_lang:
                    ops.append(
                        {
                            "op": "add",
                            "path": f"/attributes/{key}/{next_idx}",
                            "value": copy.deepcopy(item),
                        }
                    )
                    by_lang[lang] = text
                    next_idx += 1
                elif by_lang[lang].strip() != text.strip():
                    if key == "ingredients_text" and ignore_same_lang_ing_punct:
                        continue
                    conflicts.append(
                        f"attributes.{key}[{lang}] differs ({by_lang[lang]!r} vs {text!r})"
                    )
        elif key == "translations":
            by_kf = {
                (item["lang"], item["field"]): item["text"]
                for item in ex_val
                if isinstance(item, dict)
            }
            next_idx = len(ex_val)
            for item in inc_val:
                kf = (item["lang"], item["field"])
                if kf not in by_kf:
                    ops.append(
                        {
                            "op": "add",
                            "path": f"/attributes/translations/{next_idx}",
                            "value": copy.deepcopy(item),
                        }
                    )
                    by_kf[kf] = item["text"]
                    next_idx += 1
                elif by_kf[kf].strip() != item["text"].strip():
                    conflicts.append(
                        f"attributes.translations[{kf[0]}.{kf[1]}] differs"
                    )
        elif key == "in_store_barcodes":
            seen = {
                (item["retailer"].strip(), item["code"].strip())
                for item in ex_val
                if isinstance(item, dict)
            }
            next_idx = len(ex_val)
            for item in inc_val:
                pair = (item["retailer"].strip(), item["code"].strip())
                if pair not in seen:
                    ops.append(
                        {
                            "op": "add",
                            "path": f"/attributes/in_store_barcodes/{next_idx}",
                            "value": copy.deepcopy(item),
                        }
                    )
                    seen.add(pair)
                    next_idx += 1
        elif key == "parties":
            if _canon_party_set(ex_val) != _canon_party_set(inc_val):
                conflicts.append(
                    f"attributes.parties differs (existing={ex_val!r}, incoming={inc_val!r})"
                )
        elif key in ("product_standard", "claims_text"):
            ex_set = {str(s).strip() for s in ex_val}
            inc_set = {str(s).strip() for s in inc_val}
            if ex_set != inc_set:
                conflicts.append(
                    f"attributes.{key} differs (existing={sorted(ex_set)}, incoming={sorted(inc_set)})"
                )
        elif key == "special_indicators":
            if _canon_special_indicators_set(ex_val) != _canon_special_indicators_set(inc_val):
                conflicts.append(
                    f"attributes.special_indicators differs"
                )
        elif key == "origin":
            if not isinstance(ex_val, dict) or not isinstance(inc_val, dict):
                conflicts.append("attributes.origin type mismatch")
                continue
            for subk in sorted(inc_val.keys()):
                sv = inc_val[subk]
                if sv is None or str(sv).strip() == "":
                    continue
                if subk not in ex_val:
                    ops.append({"op": "add", "path": f"/attributes/origin/{subk}", "value": sv})
                elif str(ex_val[subk]).strip() != str(sv).strip():
                    conflicts.append(
                        f"attributes.origin.{subk} differs ({ex_val[subk]!r} vs {sv!r})"
                    )
        elif key == "shelf_life":
            if not isinstance(ex_val, dict) or not isinstance(inc_val, dict):
                conflicts.append("attributes.shelf_life type mismatch")
                continue
            ex_tup = (
                ex_val.get("qualifier") or "=",
                format_canonical_decimal(ex_val["value"]),
                str(ex_val["unit"]).strip().lower(),
            )
            inc_tup = (
                inc_val.get("qualifier") or "=",
                format_canonical_decimal(inc_val["value"]),
                str(inc_val["unit"]).strip().lower(),
            )
            if ex_tup != inc_tup:
                conflicts.append(
                    f"attributes.shelf_life differs ({ex_val!r} vs {inc_val!r})"
                )
            elif "label" in inc_val and str(inc_val["label"]).strip():
                if "label" not in ex_val:
                    ops.append(
                        {
                            "op": "add",
                            "path": "/attributes/shelf_life/label",
                            "value": inc_val["label"],
                        }
                    )
                elif str(ex_val["label"]).strip() != str(inc_val["label"]).strip():
                    conflicts.append(
                        f"attributes.shelf_life.label differs ({ex_val['label']!r} vs {inc_val['label']!r})"
                    )
        else:
            if str(ex_val).strip() != str(inc_val).strip():
                conflicts.append(
                    f"attributes.{key} differs ({ex_val!r} vs {inc_val!r})"
                )

    return ops, conflicts


def _merge_evidence_append_only(
    target_ed: dict[str, Any], incoming_evidence: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    existing_ids = {ev["evidence_id"] for ev in target_ed.get("evidence") or []}
    added: list[dict[str, Any]] = []
    for ev in incoming_evidence:
        ev_id = ev["evidence_id"]
        if ev_id not in existing_ids:
            ev_copy = copy.deepcopy(ev)
            target_ed["evidence"].append(ev_copy)
            existing_ids.add(ev_id)
            added.append(ev_copy)
    return added


def _consolidate_duplicate_into(
    source_ed: dict[str, Any],
    target_ed: dict[str, Any],
    redirects: dict[str, dict[str, Any]],
    *,
    author: str,
    reason: str,
    now_iso: str,
    today_ymd: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Absorb source_ed evidence & missing attributes into target_ed and emit an EditionRedirect stub."""
    enrich_ops, conflicts = _plan_attribute_merge(
        target_ed["attributes"],
        source_ed["attributes"],
        ignore_same_lang_ing_punct=True,
    )
    if conflicts:
        return {}, {}, conflicts

    updated_target = copy.deepcopy(target_ed)
    _merge_evidence_append_only(updated_target, source_ed.get("evidence") or [])

    if enrich_ops:
        s_before = extract_patchable_surface(updated_target)
        rev_patch = invert_patch(s_before, enrich_ops)
        s_after = apply_patch(s_before, enrich_ops)
        updated_target["attributes"] = s_after["attributes"]
        updated_target["rev"] += 1
        ev_refs = list(
            dict.fromkeys(
                [ev["evidence_id"] for ev in source_ed.get("evidence") or []]
                or [updated_target["evidence"][0]["evidence_id"]]
            )
        )
        updated_target["revisions"].append(
            {
                "rev": updated_target["rev"],
                "kind": "enrichment",
                "created_at": now_iso,
                "author": author,
                "reason": reason,
                "evidence_refs": ev_refs,
                "patch": enrich_ops,
                "reverse_patch": rev_patch,
            }
        )
        normalize_edition(updated_target)

    source_id = source_ed["edition_id"]
    target_id = updated_target["edition_id"]
    for redir in redirects.values():
        if redir.get("merged_into") == source_id:
            redir["merged_into"] = target_id

    redirect_stub: dict[str, Any] = {
        "opf_schema": "0.2",
        "id": updated_target["id"],
        "edition_id": source_id,
        "merged_into": target_id,
        "merged_into_rev": updated_target["rev"],
        "merged_at": today_ymd,
        "reason": reason,
    }
    return updated_target, redirect_stub, []


def _prepare_candidate_from_draft(
    draft: dict[str, Any],
    *,
    track: str,
    specimen_id_override: str | None,
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(draft, dict):
        return {}, ["Submission JSON root must be an object"]
    core = draft.get("core")
    attrs = draft.get("attributes")
    evidence = draft.get("evidence")
    if not isinstance(core, dict):
        return {}, ["Draft must include a 'core' object"]
    if not isinstance(attrs, dict):
        return {}, ["Draft must include an 'attributes' object"]
    if not isinstance(evidence, list) or not evidence:
        return {}, ["Draft must include a non-empty 'evidence' array"]

    ev_list = copy.deepcopy(evidence)
    photo_count = sum(1 for ev in ev_list if isinstance(ev, dict) and ev.get("type") == "label_photo")
    shared_specimen: str | None = None
    if specimen_id_override:
        shared_specimen = specimen_id_override
    elif photo_count >= 2:
        shared_specimen = f"sp-{generate_ulid()[:10].lower()}"

    for ev in ev_list:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "label_photo":
            if not ev.get("evidence_id") and ev.get("cropped_sha256"):
                ev["evidence_id"] = f"sha256:{ev['cropped_sha256']}"
            if shared_specimen is not None:
                if specimen_id_override or not ev.get("specimen_id"):
                    ev["specimen_id"] = shared_specimen
        else:
            if not ev.get("evidence_id"):
                if ev.get("snapshot_sha256"):
                    ev["evidence_id"] = f"sha256:{ev['snapshot_sha256']}"
                else:
                    ev["evidence_id"] = f"ev:{generate_ulid()}"

    core_copy = copy.deepcopy(core)
    attrs_copy = copy.deepcopy(attrs)
    profile_id = core_copy.get("regulatory_profile")
    if not core_copy.get("ingredients_tree"):
        if not isinstance(profile_id, str):
            return {}, ["core.regulatory_profile must be a valid string"]
        trees = []
        for item in attrs_copy.get("ingredients_text") or []:
            if isinstance(item, dict) and "lang" in item and "text" in item:
                nodes = parse_ingredients_semantic(
                    item["text"], lang=item["lang"], profile_id=profile_id
                )
                trees.append({"lang": item["lang"], "nodes": nodes})
        core_copy["ingredients_tree"] = sorted(trees, key=lambda x: str(x.get("lang", "")))

    candidate: dict[str, Any] = {
        "opf_schema": "0.2",
        "id": draft["id"],
        "edition_id": draft.get("edition_id") or generate_ulid(),
        "rev": 1,
        "track": track,
        "supersedes": list(draft.get("supersedes") or []),
        "core": core_copy,
        "attributes": attrs_copy,
        "evidence": ev_list,
        "revisions": [],
    }
    if "lifecycle" in draft and draft["lifecycle"] is not None:
        candidate["lifecycle"] = copy.deepcopy(draft["lifecycle"])

    try:
        normalize_edition(candidate)
    except Exception as exc:
        return {}, [f"Failed to normalize draft: {exc}"]

    return candidate, []


def _find_matching_head_on_track(
    records: dict[str, dict[str, Any]],
    track: str,
    core_fingerprint: str,
) -> dict[str, Any] | None:
    matches = [
        rec
        for rec in records.values()
        if rec.get("track") == track
        and rec.get("core_fingerprint") == core_fingerprint
        and (rec.get("lifecycle") or {}).get("state") != "retracted"
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    superseded_ids: set[str] = set()
    for rec in records.values():
        if (rec.get("lifecycle") or {}).get("state") == "retracted":
            continue
        superseded_ids.update(rec.get("supersedes") or [])
    heads = [m for m in matches if m["edition_id"] not in superseded_ids]
    pool = heads or matches
    return max(pool, key=lambda m: m["edition_id"])


def _merge_attributes_for_amend(
    existing_attrs: dict[str, Any], incoming_attrs: dict[str, Any]
) -> dict[str, Any]:
    merged = copy.deepcopy(existing_attrs)
    for key, val in incoming_attrs.items():
        if val is None or val == "" or val == [] or val == {}:
            continue
        if key in ("product_name", "ingredients_text") and isinstance(merged.get(key), list):
            cur_list = merged[key]
            idx_by_lang = {
                it["lang"]: i for i, it in enumerate(cur_list) if isinstance(it, dict) and "lang" in it
            }
            for item in val:
                lang = item["lang"]
                if lang in idx_by_lang:
                    cur_list[idx_by_lang[lang]] = copy.deepcopy(item)
                else:
                    idx_by_lang[lang] = len(cur_list)
                    cur_list.append(copy.deepcopy(item))
        elif key == "origin" and isinstance(val, dict) and isinstance(merged.get("origin"), dict):
            for sk, sv in val.items():
                if sv is not None and str(sv).strip():
                    merged["origin"][sk] = copy.deepcopy(sv)
        else:
            merged[key] = copy.deepcopy(val)
    return merged


def _execute_submit(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    amend_target = getattr(args, "amend", None)
    supersede_targets = getattr(args, "supersede", None)
    new_variant = bool(getattr(args, "new_variant", False))

    intent_count = sum([bool(amend_target), bool(supersede_targets), new_variant])
    if intent_count > 1:
        print(
            "Error: --amend, --supersede, and --new-variant are mutually exclusive.",
            file=sys.stderr,
        )
        return 2, {}

    in_path = Path(args.input)
    try:
        draft = json.loads(in_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to read input JSON {in_path}: {exc}", file=sys.stderr)
        return 1, {}

    if not isinstance(draft, dict):
        print("Submission JSON root must be an object", file=sys.stderr)
        return 1, {}

    removed_keys = _strip_forbidden_keys_in_place(draft)

    pid = str(draft.get("id") or "")
    id_errs = validate_product_id(pid)
    if id_errs:
        for e in id_errs:
            print(f"ID error: {e}", file=sys.stderr)
        return 1, {}

    out_root = Path(args.out_dir)
    product_meta, records, redirects, load_errs = _load_existing_product_dir(out_root, pid)
    if load_errs:
        for e in load_errs:
            print(f"Load error: {e}", file=sys.stderr)
        return 1, {}

    author = (
        getattr(args, "author", None)
        or draft.get("author")
        or next(
            (
                ev.get("contributor")
                for ev in (draft.get("evidence") or [])
                if isinstance(ev, dict) and ev.get("contributor")
            ),
            None,
        )
        or "opf:cli"
    )
    reason = getattr(args, "reason", None) or draft.get("reason")
    cli_track = getattr(args, "track", None)
    specimen_id_override = getattr(args, "specimen_id", None)

    # Resolve target track
    if amend_target:
        resolved_id = amend_target
        if resolved_id in redirects:
            resolved_id = redirects[resolved_id]["merged_into"]
        if resolved_id not in records:
            print(f"Cannot --amend unknown edition {amend_target!r} for {pid}", file=sys.stderr)
            return 1, {}
        target_rec = records[resolved_id]
        if (target_rec.get("lifecycle") or {}).get("state") == "retracted":
            print(f"Cannot --amend retracted edition {resolved_id!r}", file=sys.stderr)
            return 1, {}
        requested_track = cli_track or draft.get("track")
        if requested_track and requested_track != target_rec["track"]:
            print(
                f"--amend (errata) cannot change track from {target_rec['track']!r} to {requested_track!r}; "
                "use `opf retrack` instead.",
                file=sys.stderr,
            )
            return 1, {}
        track = target_rec["track"]
    elif supersede_targets:
        for old_id in supersede_targets:
            if old_id in redirects:
                print(
                    f"Cannot --supersede redirect stub {old_id!r}; target canonical edition {redirects[old_id]['merged_into']!r} instead.",
                    file=sys.stderr,
                )
                return 1, {}
            if old_id not in records:
                print(f"Cannot --supersede unknown edition {old_id!r} for {pid}", file=sys.stderr)
                return 1, {}
            if (records[old_id].get("lifecycle") or {}).get("state") == "retracted":
                print(f"Cannot --supersede retracted edition {old_id!r}", file=sys.stderr)
                return 1, {}
        track = cli_track or draft.get("track") or records[supersede_targets[0]]["track"]
    else:
        prof = str((draft.get("core") or {}).get("regulatory_profile") or "")
        default_track = f"{prof.split('/', 1)[0]}/default" if "/" in prof else ""
        track = cli_track or draft.get("track") or default_track

    track_errs = validate_track_key(track, allow_default=True)
    if track_errs:
        for e in track_errs:
            print(f"Track error: {e}", file=sys.stderr)
        return 1, {}

    # Update product_meta aliases and optional track_definition in memory
    if draft.get("aliases"):
        product_meta["aliases"] = list(
            dict.fromkeys((product_meta.get("aliases") or []) + list(draft["aliases"]))
        )
    if isinstance(draft.get("track_definition"), dict):
        tdef = copy.deepcopy(draft["track_definition"])
        tdef.setdefault("track", track)
        tdef.setdefault("market", tdef["track"].split("/", 1)[0])
        existing_tracks = product_meta.setdefault("tracks", [])
        if not any(t.get("track") == tdef["track"] for t in existing_tracks if isinstance(t, dict)):
            existing_tracks.append(tdef)

    if not track.endswith("/default"):
        defined_tracks = {
            t.get("track") for t in (product_meta.get("tracks") or []) if isinstance(t, dict)
        }
        if track not in defined_tracks:
            print(
                f"Non-default track {track!r} is not defined in product.json tracks[]; "
                "provide track_definition in draft or register via `opf retrack`.",
                file=sys.stderr,
            )
            return 1, {}

    candidate, prep_errs = _prepare_candidate_from_draft(
        draft, track=track, specimen_id_override=specimen_id_override
    )
    if prep_errs:
        for e in prep_errs:
            print(f"Draft error: {e}", file=sys.stderr)
        return 1, {}

    now_iso = _now_iso()
    today_ymd = _today_ymd()
    action = ""
    result_edition_id = candidate["edition_id"]
    merged_into_id: str | None = None

    if amend_target:
        target_id = amend_target if amend_target not in redirects else redirects[amend_target]["merged_into"]
        target_rec = records[target_id]
        old_surface = extract_patchable_surface(target_rec)
        amended = copy.deepcopy(target_rec)
        added_ev = _merge_evidence_append_only(amended, candidate["evidence"])
        amended["core"] = copy.deepcopy(candidate["core"])
        amended["attributes"] = _merge_attributes_for_amend(
            amended["attributes"], candidate["attributes"]
        )
        normalize_edition(amended)

        # Check for post-errata core_fingerprint collision on same (id, track)
        collision = next(
            (
                rec
                for eid, rec in sorted(records.items())
                if eid != target_id
                and rec.get("track") == amended["track"]
                and rec.get("core_fingerprint") == amended["core_fingerprint"]
                and (rec.get("lifecycle") or {}).get("state") != "retracted"
                and eid not in (amended.get("supersedes") or [])
                and target_id not in (rec.get("supersedes") or [])
            ),
            None,
        )
        if collision is not None:
            other_id = collision["edition_id"]
            merge_reason = reason or f"Consolidated duplicate {target_id} into {other_id} after errata"
            updated_other, redir_stub, conflicts = _consolidate_duplicate_into(
                amended,
                collision,
                redirects,
                author=author,
                reason=merge_reason,
                now_iso=now_iso,
                today_ymd=today_ymd,
            )
            if conflicts:
                print(
                    f"Post-errata core_fingerprint matches {other_id}, but attributes conflict: "
                    + "; ".join(conflicts)
                    + ". Run `opf retrack` or submit with `--supersede` instead.",
                    file=sys.stderr,
                )
                return 1, {}
            records[other_id] = updated_other
            del records[target_id]
            redirects[target_id] = redir_stub
            action = "amended_and_merged"
            result_edition_id = other_id
            merged_into_id = other_id
        else:
            new_surface = extract_patchable_surface(amended)
            patch, rev_patch = diff_to_patch(old_surface, new_surface)
            if patch:
                ev_refs = list(
                    dict.fromkeys(
                        [ev["evidence_id"] for ev in candidate["evidence"]]
                        or [amended["evidence"][0]["evidence_id"]]
                    )
                )
                amended["rev"] += 1
                rev_entry: dict[str, Any] = {
                    "rev": amended["rev"],
                    "kind": "errata",
                    "created_at": now_iso,
                    "author": author,
                    "evidence_refs": ev_refs,
                    "patch": patch,
                    "reverse_patch": rev_patch,
                }
                if reason:
                    rev_entry["reason"] = reason
                amended["revisions"].append(rev_entry)
                action = "amended_edition"
            else:
                action = "corroborated_edition" if added_ev else "unchanged"
            records[target_id] = amended
            result_edition_id = target_id

    elif supersede_targets:
        new_id = candidate["edition_id"]
        if new_id in records or new_id in redirects or not is_valid_ulid(new_id):
            new_id = generate_ulid()
        candidate["edition_id"] = new_id
        candidate["supersedes"] = sorted(set(supersede_targets))
        candidate["revisions"] = [
            {
                "rev": 1,
                "kind": "initial",
                "created_at": now_iso,
                "author": author,
                "evidence_refs": [ev["evidence_id"] for ev in candidate["evidence"]],
                "patch": [],
            }
        ]
        if reason:
            candidate["revisions"][0]["reason"] = reason
        normalize_edition(candidate)
        records[new_id] = candidate
        action = "superseded_edition"
        result_edition_id = new_id

    elif new_variant:
        new_id = candidate["edition_id"]
        if new_id in records or new_id in redirects or not is_valid_ulid(new_id):
            new_id = generate_ulid()
        candidate["edition_id"] = new_id
        candidate["revisions"] = [
            {
                "rev": 1,
                "kind": "initial",
                "created_at": now_iso,
                "author": author,
                "evidence_refs": [ev["evidence_id"] for ev in candidate["evidence"]],
                "patch": [],
            }
        ]
        if reason:
            candidate["revisions"][0]["reason"] = reason
        normalize_edition(candidate)
        records[new_id] = candidate
        action = "created_variant"
        result_edition_id = new_id

    else:
        existing_head = _find_matching_head_on_track(
            records, track, candidate["core_fingerprint"]
        )
        if existing_head is None:
            new_id = candidate["edition_id"]
            if new_id in records or new_id in redirects or not is_valid_ulid(new_id):
                new_id = generate_ulid()
            candidate["edition_id"] = new_id
            candidate["revisions"] = [
                {
                    "rev": 1,
                    "kind": "initial",
                    "created_at": now_iso,
                    "author": author,
                    "evidence_refs": [ev["evidence_id"] for ev in candidate["evidence"]],
                    "patch": [],
                }
            ]
            if reason:
                candidate["revisions"][0]["reason"] = reason
            normalize_edition(candidate)
            records[new_id] = candidate
            action = "created_edition"
            result_edition_id = new_id
        else:
            existing_id = existing_head["edition_id"]
            enrich_ops, conflicts = _plan_attribute_merge(
                existing_head["attributes"], candidate["attributes"]
            )
            if conflicts:
                print(
                    f"Attribute conflict against existing edition {existing_id!r} on track {track!r}:",
                    file=sys.stderr,
                )
                for c in conflicts:
                    print(f"  - {c}", file=sys.stderr)
                print(
                    f"Choose explicit intent:\n"
                    f"  --amend {existing_id}       (fix prior transcription error)\n"
                    f"  --supersede {existing_id}   (replace prior edition with a new version)\n"
                    f"  --new-variant [--track ...] (register concurrent variant / split print run)",
                    file=sys.stderr,
                )
                return 1, {}

            updated = copy.deepcopy(existing_head)
            added_ev = _merge_evidence_append_only(updated, candidate["evidence"])
            if enrich_ops:
                s_before = extract_patchable_surface(updated)
                rev_patch = invert_patch(s_before, enrich_ops)
                s_after = apply_patch(s_before, enrich_ops)
                updated["attributes"] = s_after["attributes"]
                updated["rev"] += 1
                ev_refs = list(
                    dict.fromkeys(
                        [ev["evidence_id"] for ev in candidate["evidence"]]
                        or [updated["evidence"][0]["evidence_id"]]
                    )
                )
                rev_entry = {
                    "rev": updated["rev"],
                    "kind": "enrichment",
                    "created_at": now_iso,
                    "author": author,
                    "evidence_refs": ev_refs,
                    "patch": enrich_ops,
                    "reverse_patch": rev_patch,
                }
                if reason:
                    rev_entry["reason"] = reason
                updated["revisions"].append(rev_entry)
                normalize_edition(updated)
                action = "enriched_edition"
            else:
                action = "corroborated_edition" if added_ev else "unchanged"

            records[existing_id] = updated
            result_edition_id = existing_id

    commit_errs = _commit_validated_product_dir(out_root, pid, product_meta, records, redirects)
    if commit_errs:
        print("Submission failed validation:", file=sys.stderr)
        for e in commit_errs:
            print(f"  - {e}", file=sys.stderr)
        return 1, {}

    pdir = product_dir_for_id(out_root, pid)
    summary: dict[str, Any] = {
        "status": "prepared",
        "action": action,
        "id": pid,
        "edition_id": result_edition_id,
        "track": track,
        "rev": records[result_edition_id]["rev"],
        "product_dir": str(pdir),
        "stripped_personal_batch_fields": removed_keys,
        "editions_count": len(records),
    }
    if merged_into_id is not None:
        summary["merged_into"] = merged_into_id
        summary["redirect_from"] = amend_target
    return 0, summary


def _parse_photo_specs(raw_specs: list[str] | None) -> list[tuple[str, Path]]:
    parsed: list[tuple[str, Path]] = []
    for raw in raw_specs or []:
        if "=" in raw:
            prefix, path_part = raw.split("=", 1)
            candidate_region = prefix.strip()
            if (
                candidate_region in CANONICAL_EVIDENCE_REGIONS
                or candidate_region in LEGACY_REGION_ALIASES
                or candidate_region in FORBIDDEN_FRONT_REGIONS
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", candidate_region)
            ):
                normalized_region = normalize_evidence_region(candidate_region)
                parsed.append((normalized_region, Path(path_part.strip())))
                continue
        parsed.append(("other", Path(raw.strip())))
    return parsed


def _prepare_submission_inputs(
    draft_path: Path,
    *,
    photo_specs: list[str] | None = None,
    media_stage_root: Path | None = None,
    media_out_dir: Path | None = None,
    media_stage_dir: Path | None = None,
    vintage_month: str | None = None,
    contributor: str | None = None,
    specimen_id: str | None = None,
    temp_dir: Path,
) -> tuple[Path, list[dict[str, Any]], list[str]]:
    """Process --photo crops / staged WebPs and return (prepared_draft_path, staged_blobs, errors)."""
    try:
        draft_obj = json.loads(draft_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return draft_path, [], [f"Failed to read draft JSON {draft_path}: {exc}"]
    if not isinstance(draft_obj, dict):
        return draft_path, [], ["Submission JSON root must be an object"]

    staged_blobs: list[dict[str, Any]] = []
    seen_sha: set[str] = set()
    ev_list = list(draft_obj.get("evidence") or [])
    if not isinstance(ev_list, list):
        return draft_path, [], ["Draft field 'evidence' must be a list"]

    inferred_vintage = vintage_month or next(
        (
            str(ev["vintage_month"]).strip()
            for ev in ev_list
            if isinstance(ev, dict) and ev.get("vintage_month")
        ),
        None,
    )
    inferred_contributor = contributor or draft_obj.get("author") or next(
        (
            str(ev["contributor"]).strip()
            for ev in ev_list
            if isinstance(ev, dict) and ev.get("contributor")
        ),
        None,
    ) or "github:contributor"

    if media_stage_dir is not None:
        sdir = Path(media_stage_dir)
        for ev in ev_list:
            if not isinstance(ev, dict):
                continue
            mref = str(ev.get("media_ref") or "")
            m = re.match(r"^opf-media://sha256/([a-f0-9]{64})$", mref)
            if not m:
                continue
            sha_hex = m.group(1)
            if sha_hex in seen_sha:
                continue
            rel_path = f"media/{sha_hex[0:2]}/{sha_hex[2:4]}/{sha_hex}.webp"
            cand1 = sdir / rel_path
            cand2 = sdir / f"{sha_hex}.webp"
            src_blob = cand1 if cand1.is_file() else (cand2 if cand2.is_file() else None)
            if src_blob is None:
                continue
            raw = src_blob.read_bytes()
            if hashlib.sha256(raw).hexdigest() != sha_hex:
                return draft_path, [], [f"Staged WebP hash mismatch for {src_blob} (expected {sha_hex})"]
            abs_out = src_blob
            if media_stage_root is not None:
                dest = media_stage_root / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
                abs_out = dest
            if media_out_dir is not None:
                dest_out = Path(media_out_dir) / rel_path
                dest_out.parent.mkdir(parents=True, exist_ok=True)
                dest_out.write_bytes(raw)
                abs_out = dest_out
            seen_sha.add(sha_hex)
            staged_blobs.append({"sha256": sha_hex, "rel_path": rel_path, "abs_path": str(abs_out)})

    try:
        parsed_photos = _parse_photo_specs(photo_specs)
    except ValueError as exc:
        return draft_path, [], [str(exc)]

    modified_draft = False
    if parsed_photos:
        target_stage = media_out_dir or media_stage_root or (temp_dir / "media_stage")
        for region, img_path in parsed_photos:
            if not img_path.is_file():
                return draft_path, [], [f"Photo file not found: {img_path}"]
            rep = process_cropped_label_to_webp(img_path, media_root=target_stage)
            if media_stage_root is not None and media_out_dir is not None and media_stage_root != media_out_dir:
                extra_dest = media_stage_root / rep["rel_path"]
                extra_dest.parent.mkdir(parents=True, exist_ok=True)
                extra_dest.write_bytes(Path(rep["output"]).read_bytes())
            ev_item: dict[str, Any] = {
                "type": "label_photo",
                "region": region,
                "cropped_sha256": rep["sha256"],
                "media_ref": rep["media_ref"],
                "contributor": inferred_contributor,
                "reported_at": _today_ymd(),
            }
            if inferred_vintage:
                ev_item["vintage_month"] = inferred_vintage
            if specimen_id:
                ev_item["specimen_id"] = specimen_id
            ev_list.append(ev_item)
            if rep["sha256"] not in seen_sha:
                seen_sha.add(rep["sha256"])
                staged_blobs.append(
                    {
                        "sha256": rep["sha256"],
                        "rel_path": rep["rel_path"],
                        "abs_path": rep["output"],
                        "width": rep["width"],
                        "height": rep["height"],
                        "webp_bytes": rep["webp_bytes"],
                    }
                )
            modified_draft = True

    if vintage_month:
        for ev in ev_list:
            if isinstance(ev, dict) and not ev.get("vintage_month"):
                ev["vintage_month"] = vintage_month
                modified_draft = True

    if modified_draft:
        draft_copy = copy.deepcopy(draft_obj)
        draft_copy["evidence"] = ev_list
        out_json = temp_dir / "prepared_draft.json"
        out_json.write_text(json.dumps(draft_copy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return out_json, staged_blobs, []

    return draft_path, staged_blobs, []


def cmd_submit(args: argparse.Namespace) -> int:
    photo_specs = getattr(args, "photo", None) or []
    media_out_raw = getattr(args, "media_out_dir", None)
    media_stage_raw = getattr(args, "media_stage_dir", None)
    vintage_month = getattr(args, "vintage_month", None)

    if photo_specs or media_out_raw or media_stage_raw or vintage_month:
        with tempfile.TemporaryDirectory(prefix="opf-submit-") as tmp:
            tmp_path = Path(tmp)
            prep_path, staged_blobs, errs = _prepare_submission_inputs(
                Path(args.input),
                photo_specs=photo_specs,
                media_stage_root=None,
                media_out_dir=Path(media_out_raw) if media_out_raw else None,
                media_stage_dir=Path(media_stage_raw) if media_stage_raw else None,
                vintage_month=vintage_month,
                contributor=getattr(args, "author", None),
                specimen_id=getattr(args, "specimen_id", None),
                temp_dir=tmp_path,
            )
            if errs:
                for e in errs:
                    print(f"Media preparation error: {e}", file=sys.stderr)
                return 1
            sub_ns = argparse.Namespace(**vars(args))
            sub_ns.input = str(prep_path)
            rc, summary = _execute_submit(sub_ns)
            if rc == 0 and staged_blobs:
                summary["staged_media"] = staged_blobs
    else:
        rc, summary = _execute_submit(args)

    if rc == 0 and not getattr(args, "quiet", False):
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return rc


def cmd_retrack(args: argparse.Namespace) -> int:
    pid = args.id
    id_errs = validate_product_id(pid)
    if id_errs:
        for e in id_errs:
            print(f"ID error: {e}", file=sys.stderr)
        return 1

    new_track = args.track
    track_errs = validate_track_key(new_track, allow_default=True)
    if track_errs:
        for e in track_errs:
            print(f"Track error: {e}", file=sys.stderr)
        return 1

    out_root = Path(args.out_dir)
    product_meta, records, redirects, load_errs = _load_existing_product_dir(out_root, pid)
    if load_errs:
        for e in load_errs:
            print(f"Load error: {e}", file=sys.stderr)
        return 1

    eid = args.edition
    if eid in redirects:
        print(
            f"Edition {eid!r} is a redirect stub pointing to {redirects[eid]['merged_into']!r}.",
            file=sys.stderr,
        )
        return 1
    if eid not in records:
        print(f"Edition {eid!r} not found in {pid}", file=sys.stderr)
        return 1

    ed = copy.deepcopy(records[eid])
    if (ed.get("lifecycle") or {}).get("state") == "retracted":
        print(f"Cannot retrack retracted edition {eid!r}", file=sys.stderr)
        return 1

    ev_ids = {ev["evidence_id"] for ev in ed.get("evidence") or []}
    for ref in args.evidence_ref:
        if ref not in ev_ids:
            print(f"Unknown evidence_ref {ref!r} on edition {eid!r}", file=sys.stderr)
            return 1

    if args.discriminator_method or args.instruction:
        if new_track.endswith("/default"):
            print("Default track cannot have a non-default TrackDefinition", file=sys.stderr)
            return 1
        instructions = []
        for raw_inst in args.instruction or []:
            if "=" not in raw_inst:
                print(f"Invalid --instruction {raw_inst!r}: expected '<lang>=<text>'", file=sys.stderr)
                return 1
            lang, text = raw_inst.split("=", 1)
            instructions.append({"lang": lang.strip(), "text": text.strip()})
        if not instructions:
            print(
                "Registering a track discriminator requires at least one --instruction '<lang>=<text>'",
                file=sys.stderr,
            )
            return 1
        disc: dict[str, Any] = {
            "method": args.discriminator_method or "other",
            "instructions": instructions,
        }
        if args.discriminator_field:
            disc["field"] = args.discriminator_field
        tdef = {
            "track": new_track,
            "market": new_track.split("/", 1)[0],
            "discriminator": disc,
        }
        tracks_list = product_meta.setdefault("tracks", [])
        replaced = False
        for i, existing in enumerate(tracks_list):
            if isinstance(existing, dict) and existing.get("track") == new_track:
                tracks_list[i] = tdef
                replaced = True
                break
        if not replaced:
            tracks_list.append(tdef)

    if not new_track.endswith("/default"):
        defined = {t.get("track") for t in (product_meta.get("tracks") or []) if isinstance(t, dict)}
        if new_track not in defined:
            print(
                f"Non-default track {new_track!r} is not registered in product.json tracks[]; "
                "pass --discriminator-method and --instruction '<lang>=<text>' to register it.",
                file=sys.stderr,
            )
            return 1

    action = "unchanged"
    if ed["track"] != new_track:
        s_before = extract_patchable_surface(ed)
        patch = [{"op": "replace", "path": "/track", "value": new_track}]
        rev_patch = invert_patch(s_before, patch)
        ed["track"] = new_track
        ed["rev"] += 1
        rev_entry: dict[str, Any] = {
            "rev": ed["rev"],
            "kind": "retrack",
            "created_at": _now_iso(),
            "author": args.author,
            "evidence_refs": list(dict.fromkeys(args.evidence_ref)),
            "patch": patch,
            "reverse_patch": rev_patch,
        }
        if args.reason:
            rev_entry["reason"] = args.reason
        ed["revisions"].append(rev_entry)
        records[eid] = ed
        action = "retracked"

    commit_errs = _commit_validated_product_dir(out_root, pid, product_meta, records, redirects)
    if commit_errs:
        print("Retrack failed validation:", file=sys.stderr)
        for e in commit_errs:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if not getattr(args, "quiet", False):
        print(
            json.dumps(
                {
                    "status": "ok",
                    "action": action,
                    "id": pid,
                    "edition_id": eid,
                    "track": new_track,
                    "rev": records[eid]["rev"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    pid = args.id
    id_errs = validate_product_id(pid)
    if id_errs:
        for e in id_errs:
            print(f"ID error: {e}", file=sys.stderr)
        return 1

    if args.source == args.into:
        print("--source and --into must be different edition ULIDs", file=sys.stderr)
        return 1

    out_root = Path(args.out_dir)
    product_meta, records, redirects, load_errs = _load_existing_product_dir(out_root, pid)
    if load_errs:
        for e in load_errs:
            print(f"Load error: {e}", file=sys.stderr)
        return 1

    if args.source not in records:
        print(f"Source edition {args.source!r} not found as live EditionRecord in {pid}", file=sys.stderr)
        return 1
    if args.into not in records:
        print(f"Target edition {args.into!r} not found as live EditionRecord in {pid}", file=sys.stderr)
        return 1

    src = records[args.source]
    tgt = records[args.into]
    if (src.get("lifecycle") or {}).get("state") == "retracted":
        print(f"Cannot merge retracted edition {args.source!r}", file=sys.stderr)
        return 1
    if (tgt.get("lifecycle") or {}).get("state") == "retracted":
        print(f"Cannot merge into retracted edition {args.into!r}", file=sys.stderr)
        return 1

    if src["core_fingerprint"] != tgt["core_fingerprint"] and not getattr(args, "force", False):
        print(
            f"core_fingerprint mismatch between {args.source} and {args.into}; pass --force to merge only if attributes do not conflict",
            file=sys.stderr,
        )
        return 1

    merge_reason = args.reason or f"Merged duplicate edition {args.source} into {args.into}"
    updated_tgt, redir_stub, conflicts = _consolidate_duplicate_into(
        src,
        tgt,
        redirects,
        author=args.author,
        reason=merge_reason,
        now_iso=_now_iso(),
        today_ymd=_today_ymd(),
    )
    if conflicts:
        print("Cannot merge due to attribute conflicts:", file=sys.stderr)
        for c in conflicts:
            print(f"  - {c}", file=sys.stderr)
        return 1

    records[args.into] = updated_tgt
    del records[args.source]
    redirects[args.source] = redir_stub

    commit_errs = _commit_validated_product_dir(out_root, pid, product_meta, records, redirects)
    if commit_errs:
        print("Merge failed validation:", file=sys.stderr)
        for e in commit_errs:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if not getattr(args, "quiet", False):
        print(
            json.dumps(
                {
                    "status": "ok",
                    "action": "merged",
                    "id": pid,
                    "source": args.source,
                    "merged_into": args.into,
                    "rev": records[args.into]["rev"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


def cmd_lifecycle(args: argparse.Namespace) -> int:
    if not args.state and not args.add_supersedes:
        print("Specify --state and/or --add-supersedes", file=sys.stderr)
        return 2
    if args.effective_month and not args.state:
        print("--effective-month requires --state", file=sys.stderr)
        return 2
    if args.state == "retracted" and args.add_supersedes:
        print("A retracted edition cannot carry supersedes edges", file=sys.stderr)
        return 1

    pid = args.id
    id_errs = validate_product_id(pid)
    if id_errs:
        for e in id_errs:
            print(f"ID error: {e}", file=sys.stderr)
        return 1

    out_root = Path(args.out_dir)
    product_meta, records, redirects, load_errs = _load_existing_product_dir(out_root, pid)
    if load_errs:
        for e in load_errs:
            print(f"Load error: {e}", file=sys.stderr)
        return 1

    eid = args.edition
    if eid not in records:
        print(f"Edition {eid!r} not found as live EditionRecord in {pid}", file=sys.stderr)
        return 1

    ed = copy.deepcopy(records[eid])
    ev_ids = {ev["evidence_id"] for ev in ed.get("evidence") or []}
    ev_refs = list(dict.fromkeys(args.evidence_ref))
    for ref in ev_refs:
        if ref not in ev_ids:
            print(f"Unknown evidence_ref {ref!r} on edition {eid!r}", file=sys.stderr)
            return 1

    old_surface = extract_patchable_surface(ed)
    new_surface = copy.deepcopy(old_surface)

    if args.state:
        lc_obj: dict[str, Any] = {
            "state": args.state,
            "reason": args.reason,
            "evidence_refs": ev_refs,
        }
        if args.effective_month:
            lc_obj["effective_month"] = args.effective_month
        new_surface["lifecycle"] = lc_obj
        if args.state == "retracted" and "supersedes" in new_surface:
            new_surface["supersedes"] = []

    if args.add_supersedes:
        if (new_surface.get("lifecycle") or {}).get("state") == "retracted":
            print(f"Cannot add supersedes to retracted edition {eid!r}", file=sys.stderr)
            return 1
        new_surface["supersedes"] = sorted(
            set(old_surface.get("supersedes") or []) | set(args.add_supersedes)
        )

    patch, rev_patch = diff_to_patch(old_surface, new_surface)
    action = "unchanged"
    if patch:
        if "lifecycle" in new_surface:
            ed["lifecycle"] = new_surface["lifecycle"]
        if "supersedes" in new_surface:
            ed["supersedes"] = new_surface["supersedes"]
        ed["rev"] += 1
        ed["revisions"].append(
            {
                "rev": ed["rev"],
                "kind": "lifecycle",
                "created_at": _now_iso(),
                "author": args.author,
                "reason": args.reason,
                "evidence_refs": ev_refs,
                "patch": patch,
                "reverse_patch": rev_patch,
            }
        )
        records[eid] = ed
        action = "lifecycle_updated"

    commit_errs = _commit_validated_product_dir(out_root, pid, product_meta, records, redirects)
    if commit_errs:
        print("Lifecycle update failed validation:", file=sys.stderr)
        for e in commit_errs:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if not getattr(args, "quiet", False):
        print(
            json.dumps(
                {
                    "status": "ok",
                    "action": action,
                    "id": pid,
                    "edition_id": eid,
                    "rev": records[eid]["rev"],
                    "lifecycle": records[eid].get("lifecycle"),
                    "supersedes": records[eid].get("supersedes", []),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


def _extract_media_sha_refs(doc: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for ev in doc.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        mref = str(ev.get("media_ref") or "").strip()
        m = re.match(r"^opf-media://sha256/([a-f0-9]{64})$", mref)
        if m:
            refs.append(m.group(1))
    return refs


def _check_media_blob_http(media_base_url: str, sha256_hex: str) -> tuple[bool, str]:
    url = f"{media_base_url.rstrip('/')}/media/{sha256_hex[0:2]}/{sha256_hex[2:4]}/{sha256_hex}.webp"
    headers = {"User-Agent": "opf-ci-media-check/0.2"}
    last_err = ""
    for attempt in range(3):
        for method, extra_headers in (("HEAD", {}), ("GET", {"Range": "bytes=0-15"})):
            req = urllib.request.Request(url, method=method, headers={**headers, **extra_headers})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status = getattr(resp, "status", 200)
                    if status in (200, 206, 304):
                        return True, str(status)
                    last_err = f"HTTP {status}"
            except urllib.error.HTTPError as exc:
                last_err = f"HTTP {exc.code}"
                if method == "HEAD" and exc.code in (403, 405, 501):
                    continue
                if exc.code in (404, 410):
                    return False, last_err
                if exc.code >= 500:
                    break
                return False, last_err
            except Exception as exc:
                last_err = str(exc)
                break
        if attempt < 2:
            time.sleep(0.4 * (attempt + 1))
    return False, last_err or "request failed"


def check_media_refs(
    paths: list[Path],
    *,
    media_dir: Path | None = None,
    media_base_url: str = "",
    only_refs_from_git_diff: str | None = None,
    warn_only: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Verify referenced `opf-media://sha256/<hex>` blobs exist in media_dir or remote media_base_url."""
    refs_map: dict[str, list[str]] = {}

    if only_refs_from_git_diff:
        resolved_targets = [Path(p).resolve() for p in paths]
        anchor = resolved_targets[0] if resolved_targets[0].is_dir() else resolved_targets[0].parent
        top = subprocess.run(
            ["git", "-C", str(anchor), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if top.returncode != 0 or not top.stdout.strip():
            return 1, {"error": f"Failed to resolve git repository for diff base {only_refs_from_git_diff!r}"}
        git_root = Path(top.stdout.strip()).resolve()
        rel_filters: list[str] = []
        for t in resolved_targets:
            try:
                rel_p = t.relative_to(git_root).as_posix()
                rel_filters.append(rel_p or ".")
            except ValueError:
                pass
        diff_cmd = ["git", "-C", str(git_root), "diff", "--name-only", only_refs_from_git_diff]
        if rel_filters:
            diff_cmd.extend(["--", *rel_filters])
        diff_res = subprocess.run(diff_cmd, capture_output=True, text=True, check=False)
        if diff_res.returncode != 0:
            return 1, {"error": f"git diff failed: {diff_res.stderr.strip()}"}

        for rel_file in sorted(set(diff_res.stdout.splitlines())):
            if not rel_file.endswith(".json") or Path(rel_file).name == "product.json":
                continue
            fpath = git_root / rel_file
            if not fpath.is_file():
                continue
            try:
                doc = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(doc, dict) or "merged_into" in doc or "evidence" not in doc:
                continue
            old_refs: set[str] = set()
            show_res = subprocess.run(
                ["git", "-C", str(git_root), "show", f"{only_refs_from_git_diff}:{rel_file}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if show_res.returncode == 0 and show_res.stdout.strip():
                try:
                    old_doc = json.loads(show_res.stdout)
                    if isinstance(old_doc, dict):
                        old_refs = set(_extract_media_sha_refs(old_doc))
                except Exception:
                    pass
            for sha_hex in _extract_media_sha_refs(doc):
                if sha_hex not in old_refs:
                    refs_map.setdefault(sha_hex, []).append(rel_file)
    else:
        for raw_p in paths:
            p = Path(raw_p)
            cand_files: list[Path] = []
            if p.is_file():
                cand_files = [p]
            elif p.is_dir():
                cand_files = sorted(jf for jf in p.rglob("*.json") if jf.name != "product.json")
            for jf in cand_files:
                try:
                    doc = json.loads(jf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(doc, dict) or "merged_into" in doc or "evidence" not in doc:
                    continue
                for sha_hex in _extract_media_sha_refs(doc):
                    refs_map.setdefault(sha_hex, []).append(str(jf))

    if not refs_map:
        return 0, {"checked": 0, "missing": [], "status": "ok"}

    if media_dir is None and not media_base_url:
        return (0 if warn_only else 1), {
            "checked": len(refs_map),
            "missing": sorted(refs_map.keys()),
            "error": f"Specify --media-dir or --media-base-url to verify {len(refs_map)} opf-media reference(s).",
        }

    missing: list[dict[str, Any]] = []
    for sha_hex in sorted(refs_map.keys()):
        ed_files = sorted(dict.fromkeys(refs_map[sha_hex]))
        if media_dir is not None:
            blob_path = Path(media_dir) / "media" / sha_hex[0:2] / sha_hex[2:4] / f"{sha_hex}.webp"
            ok = blob_path.is_file() and hashlib.sha256(blob_path.read_bytes()).hexdigest() == sha_hex
            detail = "ok" if ok else "not_found_or_hash_mismatch"
        else:
            ok, detail = _check_media_blob_http(media_base_url, sha_hex)
        if not ok:
            missing.append({"sha256": sha_hex, "editions": ed_files, "detail": detail})

    rc = 0 if (not missing or warn_only) else 1
    return rc, {
        "checked": len(refs_map),
        "missing": missing,
        "status": "ok" if not missing else ("warn" if warn_only else "missing"),
    }


def cmd_check_media_refs(args: argparse.Namespace) -> int:
    media_dir = Path(args.media_dir) if args.media_dir else None
    rc, report = check_media_refs(
        [Path(p) for p in args.paths],
        media_dir=media_dir,
        media_base_url=args.media_base_url,
        only_refs_from_git_diff=args.only_refs_from_git_diff,
        warn_only=args.warn_only,
    )
    if "error" in report:
        print(report["error"], file=sys.stderr)
        return rc
    if report["checked"] == 0:
        print("OK (0 opf-media references to verify)")
        return 0
    for item in report["missing"]:
        ed_label = ", ".join(item["editions"])
        print(
            f"MISSING_MEDIA: opf-media://sha256/{item['sha256']} ({ed_label}) not found on opf-media main. "
            "Merge the companion opf-media PR FIRST, then re-run this CI job.",
            file=sys.stderr,
        )
    if not report["missing"]:
        print(f"OK ({report['checked']} opf-media reference(s) verified)")
    return rc


def cmd_validate_media(args: argparse.Namespace) -> int:
    root = Path(args.media_root)
    store_dir = root / "media" if (root / "media").is_dir() else (root if root.name == "media" else root / "media")
    errs = validate_media_repo(root, max_edge=args.max_edge, max_bytes=args.max_bytes)
    webp_count = 0
    if store_dir.is_dir():
        webp_count = sum(
            1 for f in store_dir.rglob("*") if f.is_file() and f.name != ".gitkeep" and f.suffix == ".webp"
        )
    if not errs and webp_count == 0 and not args.allow_empty:
        errs.append(
            f"Media repository {root} contains 0 .webp files; pass --allow-empty if empty initialization is expected."
        )
    if getattr(args, "json", False):
        print(
            json.dumps(
                {"valid": len(errs) == 0, "media_root": str(root), "webp_count": webp_count, "errors": errs},
                ensure_ascii=False,
                indent=2,
            )
        )
    elif errs:
        print(f"FAIL {root}:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
    else:
        print(f"OK   {root} ({webp_count} WebP files)")
    return 0 if not errs else 1


def _gh_authenticated_user() -> tuple[str | None, str | None]:
    if shutil.which("gh") is None:
        return None, "GitHub CLI (`gh`) is not installed in PATH."
    res = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True, check=False)
    if res.returncode != 0 or not res.stdout.strip():
        return None, "GitHub CLI is not authenticated. Run `gh auth login` first."
    return res.stdout.strip(), None


def _gh_fork_clone_url(target_repo: str, gh_user: str) -> str:
    owner, repo_name = target_repo.split("/", 1)
    if gh_user != owner:
        subprocess.run(["gh", "repo", "fork", target_repo, "--clone=false"], check=True, capture_output=True, text=True)
    proto_res = subprocess.run(["gh", "config", "get", "git_protocol"], capture_output=True, text=True, check=False)
    proto = (proto_res.stdout or "").strip().lower()
    fork_slug = f"{gh_user}/{repo_name}" if gh_user != owner else target_repo
    if proto == "ssh":
        return f"git@github.com:{fork_slug}.git"
    return f"https://github.com/{fork_slug}.git"


def _sparse_clone_repo(repo_slug: str, dest_dir: Path, sparse_paths: list[str]) -> None:
    clone_url = f"https://github.com/{repo_slug}.git"
    subprocess.run(
        ["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout", clone_url, str(dest_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "-C", str(dest_dir), "sparse-checkout", "init", "--no-cone"], check=True, capture_output=True)
    if sparse_paths:
        subprocess.run(
            ["git", "-C", str(dest_dir), "sparse-checkout", "set", *sparse_paths],
            check=True,
            capture_output=True,
        )
    subprocess.run(["git", "-C", str(dest_dir), "checkout"], check=True, capture_output=True)


def _fetch_upstream_product_if_reachable(target_data_repo: str, rel_pdir_sub: str, products_dir: Path) -> None:
    """Best-effort fast read-only fetch of an existing product directory for accurate --dry-run planning."""
    if os.environ.get("OPF_PR_DRY_RUN_OFFLINE") == "1":
        return
    api_base = f"https://api.github.com/repos/{target_data_repo}/contents/products/{rel_pdir_sub}"
    headers = {"User-Agent": "opf-cli-dry-run/0.2", "Accept": "application/vnd.github+json"}
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{api_base}?ref=main", headers=headers), timeout=1.5) as r:
            entries = json.loads(r.read().decode("utf-8"))
    except Exception:
        return
    if not isinstance(entries, list):
        return
    local_pdir = products_dir / rel_pdir_sub
    local_pdir.mkdir(parents=True, exist_ok=True)
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        if ent.get("type") == "file" and ent.get("name") == "product.json" and ent.get("download_url"):
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(ent["download_url"], headers=headers), timeout=1.5
                ) as rf:
                    (local_pdir / "product.json").write_bytes(rf.read())
            except Exception:
                pass
        elif ent.get("type") == "dir" and ent.get("name") == "editions":
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(f"{api_base}/editions?ref=main", headers=headers), timeout=1.5
                ) as re_resp:
                    ed_entries = json.loads(re_resp.read().decode("utf-8"))
                if isinstance(ed_entries, list):
                    (local_pdir / "editions").mkdir(parents=True, exist_ok=True)
                    for ed_ent in ed_entries:
                        if isinstance(ed_ent, dict) and ed_ent.get("download_url") and ed_ent.get("name", "").endswith(".json"):
                            with urllib.request.urlopen(
                                urllib.request.Request(ed_ent["download_url"], headers=headers), timeout=1.5
                            ) as ref_ed:
                                (local_pdir / "editions" / ed_ent["name"]).write_bytes(ref_ed.read())
            except Exception:
                pass


def _ensure_git_identity(repo_dir: Path, gh_user: str) -> None:
    """Ensure repo-local user.name and user.email exist before `git commit -s`."""
    email_res = subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.email"],
        capture_output=True,
        text=True,
        check=False,
    )
    if email_res.returncode != 0 or not email_res.stdout.strip():
        subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", gh_user], check=True)
        subprocess.run(
            ["git", "-C", str(repo_dir), "config", "user.email", f"{gh_user}@users.noreply.github.com"],
            check=True,
        )


def _set_git_remote(repo_dir: Path, remote_name: str, url: str) -> None:
    check_res = subprocess.run(
        ["git", "-C", str(repo_dir), "remote", "get-url", remote_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if check_res.returncode == 0:
        subprocess.run(["git", "-C", str(repo_dir), "remote", "set-url", remote_name, url], check=True)
    else:
        subprocess.run(["git", "-C", str(repo_dir), "remote", "add", remote_name, url], check=True)


def cmd_pr(args: argparse.Namespace) -> int:
    photo_specs = getattr(args, "photo", None) or []
    media_stage_raw = getattr(args, "media_stage_dir", None)
    media_repo_raw = getattr(args, "media_repo", None)
    data_repo_raw = getattr(args, "data_repo", None)
    vintage_month = getattr(args, "vintage_month", None)
    target_data_repo = getattr(args, "target_data_repo", None) or os.environ.get(
        "OPF_DATA_REPO", "mickey996icu/opf-data"
    )
    target_media_repo = getattr(args, "target_media_repo", None) or os.environ.get(
        "OPF_MEDIA_REPO", "mickey996icu/opf-media"
    )

    try:
        raw_draft = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to read input JSON {args.input}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(raw_draft, dict):
        print("Submission JSON root must be an object", file=sys.stderr)
        return 1

    pid_pre = str(raw_draft.get("id") or "")
    pid_errs = validate_product_id(pid_pre)
    if pid_errs:
        for e in pid_errs:
            print(f"ID error: {e}", file=sys.stderr)
        return 1
    rel_pdir_sub = product_dir_for_id(Path("."), pid_pre).as_posix().lstrip("./")
    sparse_prod_rel = f"products/{rel_pdir_sub}"

    with tempfile.TemporaryDirectory(prefix="opf-pr-") as tmp:
        tmp_path = Path(tmp)
        media_stage_root = (
            Path(media_repo_raw).resolve()
            if media_repo_raw
            else (tmp_path / "media-repo")
        )
        media_stage_root.mkdir(parents=True, exist_ok=True)
        (media_stage_root / "media").mkdir(parents=True, exist_ok=True)

        prep_path, staged_blobs, prep_errs = _prepare_submission_inputs(
            Path(args.input),
            photo_specs=photo_specs,
            media_stage_root=media_stage_root,
            media_out_dir=None,
            media_stage_dir=Path(media_stage_raw) if media_stage_raw else None,
            vintage_month=vintage_month,
            contributor=getattr(args, "author", None),
            specimen_id=getattr(args, "specimen_id", None),
            temp_dir=tmp_path,
        )
        if prep_errs:
            for e in prep_errs:
                print(f"Media error: {e}", file=sys.stderr)
            return 1

        if staged_blobs:
            m_errs = validate_media_repo(media_stage_root)
            if m_errs:
                for e in m_errs:
                    print(f"Media validation failed: {e}", file=sys.stderr)
                return 1

        local_mode = bool(data_repo_raw)
        gh_user: str | None = None
        gh_err: str | None = None
        if not args.dry_run and not (local_mode and shutil.which("gh") is None):
            gh_user, gh_err = _gh_authenticated_user()

        if local_mode:
            data_repo = Path(data_repo_raw).resolve()
        else:
            data_repo = (tmp_path / "data-repo").resolve()
            if not args.dry_run and gh_user and not gh_err:
                # Sparse-clone upstream first so `_execute_submit` runs strictly ONCE against real upstream state
                _sparse_clone_repo(target_data_repo, data_repo, [f"/{sparse_prod_rel}"])
                (data_repo / "products").mkdir(parents=True, exist_ok=True)
            else:
                (data_repo / "products").mkdir(parents=True, exist_ok=True)
                _fetch_upstream_product_if_reachable(target_data_repo, rel_pdir_sub, data_repo / "products")

        products_dir = data_repo / "products"
        submit_ns = argparse.Namespace(
            input=str(prep_path),
            out_dir=str(products_dir),
            amend=getattr(args, "amend", None),
            supersede=getattr(args, "supersede", None),
            new_variant=getattr(args, "new_variant", False),
            track=getattr(args, "track", None),
            author=getattr(args, "author", None),
            reason=getattr(args, "reason", None),
            specimen_id=getattr(args, "specimen_id", None),
            quiet=True,
        )
        rc, summary = _execute_submit(submit_ns)
        if rc != 0:
            return rc

        pid = summary["id"]
        ed_id = summary["edition_id"]
        pdir = Path(summary["product_dir"]).resolve()
        ed_path = pdir / "editions" / f"{ed_id}.json"
        saved_ed = json.loads(ed_path.read_text(encoding="utf-8"))
        attrs = saved_ed["attributes"]
        brand = attrs["brand"]
        pname = attrs["product_name"][0]["text"]
        ev_level = derive_evidence_level(saved_ed)

        rel_pdir = pdir.relative_to(data_repo).as_posix()
        safe_slug = re.sub(r"[^a-z0-9]+", "-", f"{pid}-{ed_id}".lower()).strip("-")
        branch_name = f"contrib/{safe_slug}"
        commit_title = f"feat(product): {pid} ({ed_id}@rev{saved_ed['rev']}) - {brand} {pname}"
        media_commit_title = f"media(label): {pid} ({ed_id}) label WebP crops ({len(staged_blobs)} file(s))"

        def _build_data_body(media_url: str | None) -> str:
            callout = ""
            if staged_blobs:
                target_ref = media_url or "<MEDIA_PR_URL>"
                callout = (
                    "\n> [!IMPORTANT]\n"
                    f"> **Companion Media PR (MERGE FIRST)**: {target_ref}\n"
                    "> CI requires referenced label photos to exist on opf-media main before merging this PR.\n"
                )
            return (
                f"## Product Submission (v0.2)\n"
                f"{callout}\n"
                f"- **ID**: `{pid}`\n"
                f"- **Brand & Name**: {brand} — {pname}\n"
                f"- **Edition**: `{ed_id}` (`rev {saved_ed['rev']}`, track `{saved_ed['track']}`, `{ev_level}`)\n"
                f"- **Action**: `{summary['action']}`\n"
                f"- **Product Dir**: `{rel_pdir}`\n\n"
                f"Validated locally via `opf validate` (Schema v0.2 + GS1 + Span-Free Ingredient Round-Trip + Patch Replay).\n"
            )

        def _build_media_body(data_url: str | None) -> str:
            target_ref = data_url or "<DATA_PR_URL>"
            blob_lines = "\n".join(f"  - `{b['rel_path']}` (`opf-media://sha256/{b['sha256']}`)" for b in staged_blobs)
            return (
                "## Label Evidence Media (WebP <= 1000px, EXIF-Free)\n\n"
                "> Merge this `opf-media` PR **FIRST** so `opf-data` CI `check-media-refs` passes.\n\n"
                f"- **Companion Data PR (merge second)**: {target_ref}\n"
                f"- **Product**: `{pid}` — {brand} {pname} (`{ed_id}`)\n"
                f"- **Media Blobs ({len(staged_blobs)})**:\n{blob_lines}\n\n"
                "Validated locally via `opf validate-media` (SHA-256 content-addressed paths, <=1000px, zero EXIF/XMP chunks).\n"
            )

        pr_body = _build_data_body(None)
        data_cmds = [
            f"git -C {data_repo} checkout -B {branch_name}",
            f"git -C {data_repo} add {rel_pdir}",
            f"git -C {data_repo} commit -s -m {json.dumps(commit_title, ensure_ascii=False)}",
            f"git -C {data_repo} push -u origin {branch_name}",
            f"gh pr create --repo {target_data_repo} --title {json.dumps(commit_title, ensure_ascii=False)} --body-file -",
        ]

        plan: dict[str, Any] = {
            "mode": "local" if local_mode else "remote_fork",
            "target_data_repo": target_data_repo,
            "target_media_repo": target_media_repo,
            "merge_order": ["opf-media", "opf-data"] if staged_blobs else ["opf-data"],
            "branch": branch_name,
            "data_repo": str(data_repo),
            "product_dir": rel_pdir,
            "action": summary["action"],
            "edition_id": ed_id,
            "rev": saved_ed["rev"],
            "commit_title": commit_title,
            "pr_body": pr_body,
            "staged_media": staged_blobs,
            "data_pr_plan": {
                "repo": target_data_repo,
                "branch": branch_name,
                "files": [rel_pdir],
                "commit_title": commit_title,
                "pr_body": pr_body,
                "commands": data_cmds,
            },
            "commands": data_cmds,
        }
        if staged_blobs:
            media_cmds = [
                f"git -C {media_stage_root} checkout -B {branch_name}",
                f"git -C {media_stage_root} add " + " ".join(b["rel_path"] for b in staged_blobs),
                f"git -C {media_stage_root} commit -s -m {json.dumps(media_commit_title, ensure_ascii=False)}",
                f"git -C {media_stage_root} push -u origin {branch_name}",
                f"gh pr create --repo {target_media_repo} --title {json.dumps(media_commit_title, ensure_ascii=False)} --body-file -",
            ]
            plan["media_pr_plan"] = {
                "repo": target_media_repo,
                "branch": branch_name,
                "files": [b["rel_path"] for b in staged_blobs],
                "commit_title": media_commit_title,
                "pr_body": _build_media_body(None),
                "commands": media_cmds,
            }

        if args.dry_run:
            if not getattr(args, "quiet", False):
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0

        if local_mode and shutil.which("gh") is None:
            plan["note"] = "gh CLI not found in PATH; outputting prepared git/gh commands."
            if not getattr(args, "quiet", False):
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0

        if gh_err or not gh_user:
            print(f"GitHub PR submission blocked: {gh_err}", file=sys.stderr)
            if not getattr(args, "quiet", False):
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 1

        if local_mode:
            media_pr_url: str | None = None
            if staged_blobs and media_repo_raw:
                m_repo = Path(media_repo_raw).resolve()
                _ensure_git_identity(m_repo, gh_user)
                subprocess.run(["git", "-C", str(m_repo), "checkout", "-B", branch_name], check=True)
                subprocess.run(
                    ["git", "-C", str(m_repo), "add", *[b["rel_path"] for b in staged_blobs]],
                    check=True,
                )
                subprocess.run(["git", "-C", str(m_repo), "commit", "-s", "-m", media_commit_title], check=True)
                subprocess.run(["git", "-C", str(m_repo), "push", "-u", "origin", branch_name], check=True)
                m_res = subprocess.run(
                    ["gh", "pr", "create", "--repo", target_media_repo, "--title", media_commit_title, "--body-file", "-"],
                    input=_build_media_body(None).encode("utf-8"),
                    cwd=str(m_repo),
                    capture_output=True,
                    check=True,
                )
                media_pr_url = m_res.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]

            _ensure_git_identity(data_repo, gh_user)
            final_data_body = _build_data_body(media_pr_url)
            subprocess.run(["git", "-C", str(data_repo), "checkout", "-B", branch_name], check=True)
            subprocess.run(["git", "-C", str(data_repo), "add", rel_pdir], check=True)
            subprocess.run(["git", "-C", str(data_repo), "commit", "-s", "-m", commit_title], check=True)
            subprocess.run(["git", "-C", str(data_repo), "push", "-u", "origin", branch_name], check=True)
            d_res = subprocess.run(
                ["gh", "pr", "create", "--title", commit_title, "--body-file", "-"],
                input=final_data_body.encode("utf-8"),
                cwd=str(data_repo),
                capture_output=True,
                check=True,
            )
            data_pr_url = d_res.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]
            if media_pr_url:
                subprocess.run(
                    ["gh", "pr", "edit", media_pr_url, "--body-file", "-"],
                    input=_build_media_body(data_pr_url).encode("utf-8"),
                    check=True,
                )
            if not getattr(args, "quiet", False):
                print(
                    json.dumps(
                        {
                            "status": "created",
                            "mode": "local",
                            "merge_order": ["opf-media", "opf-data"] if media_pr_url else ["opf-data"],
                            "media_pr_url": media_pr_url,
                            "data_pr_url": data_pr_url,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 0

        # Remote Fork Mode: commit & push single-pass `data_repo` + new media blobs cleanly
        media_pr_url = None
        new_blobs: list[dict[str, Any]] = []
        if staged_blobs:
            raw_media_base = f"https://raw.githubusercontent.com/{target_media_repo}/main"
            for blob in staged_blobs:
                exists_remote, _ = _check_media_blob_http(raw_media_base, blob["sha256"])
                if not exists_remote:
                    new_blobs.append(blob)

        if new_blobs:
            live_media_dir = Path(media_repo_raw).resolve() if media_repo_raw else (tmp_path / "live-media-repo")
            if not media_repo_raw:
                _sparse_clone_repo(
                    target_media_repo,
                    live_media_dir,
                    ["/LICENSE", "/media/.gitkeep", *(f"/{b['rel_path']}" for b in new_blobs)],
                )
                for blob in new_blobs:
                    dst_blob = live_media_dir / blob["rel_path"]
                    dst_blob.parent.mkdir(parents=True, exist_ok=True)
                    dst_blob.write_bytes(Path(blob["abs_path"]).read_bytes())
            m_live_errs = validate_media_repo(live_media_dir)
            if m_live_errs:
                for e in m_live_errs:
                    print(f"Media validation failed: {e}", file=sys.stderr)
                return 1
            m_owner = target_media_repo.split("/", 1)[0]
            m_push_url = _gh_fork_clone_url(target_media_repo, gh_user)
            m_head = f"{gh_user}:{branch_name}" if gh_user != m_owner else branch_name
            _ensure_git_identity(live_media_dir, gh_user)
            subprocess.run(["git", "-C", str(live_media_dir), "checkout", "-B", branch_name], check=True)
            subprocess.run(
                ["git", "-C", str(live_media_dir), "add", "--sparse", *[b["rel_path"] for b in new_blobs]],
                check=True,
            )
            subprocess.run(["git", "-C", str(live_media_dir), "commit", "-s", "-m", media_commit_title], check=True)
            _set_git_remote(live_media_dir, "fork", m_push_url)
            subprocess.run(
                ["git", "-C", str(live_media_dir), "push", "-f", "-u", "fork", branch_name],
                check=True,
            )
            m_res = subprocess.run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    target_media_repo,
                    "--head",
                    m_head,
                    "--title",
                    media_commit_title,
                    "--body-file",
                    "-",
                ],
                input=_build_media_body(None).encode("utf-8"),
                cwd=str(live_media_dir),
                capture_output=True,
                check=True,
            )
            media_pr_url = m_res.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]

        d_owner = target_data_repo.split("/", 1)[0]
        d_push_url = _gh_fork_clone_url(target_data_repo, gh_user)
        d_head = f"{gh_user}:{branch_name}" if gh_user != d_owner else branch_name
        _ensure_git_identity(data_repo, gh_user)
        subprocess.run(["git", "-C", str(data_repo), "checkout", "-B", branch_name], check=True)
        subprocess.run(["git", "-C", str(data_repo), "add", "--sparse", sparse_prod_rel], check=True)
        subprocess.run(["git", "-C", str(data_repo), "commit", "-s", "-m", commit_title], check=True)
        _set_git_remote(data_repo, "fork", d_push_url)
        subprocess.run(["git", "-C", str(data_repo), "push", "-f", "-u", "fork", branch_name], check=True)
        d_res = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                target_data_repo,
                "--head",
                d_head,
                "--title",
                commit_title,
                "--body-file",
                "-",
            ],
            input=_build_data_body(media_pr_url).encode("utf-8"),
            cwd=str(data_repo),
            capture_output=True,
            check=True,
        )
        data_pr_url = d_res.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]
        if media_pr_url:
            subprocess.run(
                ["gh", "pr", "edit", media_pr_url, "--body-file", "-"],
                input=_build_media_body(data_pr_url).encode("utf-8"),
                check=True,
            )

        if not getattr(args, "quiet", False):
            print(
                json.dumps(
                    {
                        "status": "created",
                        "mode": "remote_fork",
                        "merge_order": ["opf-media", "opf-data"] if media_pr_url else ["opf-data"],
                        "media_pr_url": media_pr_url,
                        "data_pr_url": data_pr_url,
                        "edition_id": ed_id,
                        "rev": saved_ed["rev"],
                        "branch": branch_name,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0


def cmd_sanitize_media(args: argparse.Namespace) -> int:
    reports = []
    media_root = Path(args.media_root) if getattr(args, "media_root", None) else None
    out_dir = Path(args.out_dir) if getattr(args, "out_dir", None) else None
    lossless_only = bool(getattr(args, "lossless_only", False))
    max_edge = int(getattr(args, "max_edge", 1000))
    quality = int(getattr(args, "quality", 80))

    for raw in args.images:
        in_path = Path(raw)
        if not in_path.is_file():
            print(f"Image file not found: {in_path}", file=sys.stderr)
            return 1
        if lossless_only:
            out_path = (out_dir / in_path.name) if out_dir else None
            rep = sanitize_and_hash_image(in_path, out_path)
            reports.append(rep)
        else:
            if media_root is not None:
                rep = process_cropped_label_to_webp(
                    in_path, media_root=media_root, max_edge=max_edge, quality=quality
                )
                if out_dir is not None and rep["output"]:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    dest = out_dir / f"{rep['sha256']}.webp"
                    dest.write_bytes(Path(rep["output"]).read_bytes())
                    rep["out_dir_copy"] = str(dest)
            elif out_dir is not None:
                with tempfile.TemporaryDirectory(prefix="opf-webp-") as tmp:
                    rep = process_cropped_label_to_webp(
                        in_path, media_root=Path(tmp), max_edge=max_edge, quality=quality
                    )
                    out_dir.mkdir(parents=True, exist_ok=True)
                    dest = out_dir / f"{rep['sha256']}.webp"
                    dest.write_bytes(Path(rep["output"]).read_bytes())
                    rep["output"] = str(dest)
            else:
                rep = process_cropped_label_to_webp(
                    in_path, media_root=None, out_path=None, max_edge=max_edge, quality=quality
                )
            reports.append(rep)
    print(json.dumps({"sanitized": reports}, ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    if args.data_dir:
        site_dir = Path(args.dir) if args.dir else Path(tempfile.mkdtemp(prefix="opf-site-"))
        build_static_api(
            Path(args.data_dir),
            site_dir,
            media_base_url=getattr(args, "media_base_url", ""),
        )
    elif args.dir:
        site_dir = Path(args.dir)
    else:
        print("Specify either --dir <built_site_dir> or --data-dir <products_dir>.", file=sys.stderr)
        return 1

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site_dir))
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        print(f"Serving OpenPackagedFood Catalog at http://{args.host}:{args.port}/ (from {site_dir})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opf",
        description="OpenPackagedFood CLI (v0.2): validate, validate-media, check-media-refs, normalize, parse-ingredients, submit, retrack, merge, lifecycle, pr, build, sanitize-media, serve",
    )
    parser.add_argument("--version", action="version", version=f"opf {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="Validate OPF v0.2 products root, product directory, or JSON file")
    p_val.add_argument("paths", nargs="+", help="Product directory, products root, or JSON file")
    p_val.add_argument("--json", action="store_true", help="Output validation report as JSON")
    p_val.add_argument(
        "--allow-empty",
        action="store_true",
        help="Succeed if products root contains 0 product directories and 0 orphan JSON files",
    )
    p_val.set_defaults(func=cmd_validate)

    p_vmed = sub.add_parser(
        "validate-media",
        help="Validate content-addressed WebP label evidence store (zero Pillow dependency)",
    )
    p_vmed.add_argument("media_root", help="Path to opf-media repository root or media/ directory")
    p_vmed.add_argument("--allow-empty", action="store_true", help="Allow 0 .webp files")
    p_vmed.add_argument("--max-edge", type=int, default=1000, help="Maximum allowed pixel edge (default: 1000)")
    p_vmed.add_argument("--max-bytes", type=int, default=512_000, help="Maximum bytes per WebP (default: 512000)")
    p_vmed.add_argument("--json", action="store_true", help="Output validation report as JSON")
    p_vmed.set_defaults(func=cmd_validate_media)

    p_cmr = sub.add_parser(
        "check-media-refs",
        help="Verify opf-media://sha256/<hex> references exist on opf-media before merging opf-data PRs",
    )
    p_cmr.add_argument("paths", nargs="+", help="Products root directory, product dir, or edition JSON paths")
    p_cmr.add_argument("--media-dir", help="Local opf-media checkout directory")
    p_cmr.add_argument(
        "--media-base-url",
        default=os.environ.get("OPF_MEDIA_BASE_URL", ""),
        help="Remote media base URL (default env OPF_MEDIA_BASE_URL)",
    )
    p_cmr.add_argument(
        "--only-refs-from-git-diff",
        help="Only check opf-media refs newly added vs the given git base ref",
    )
    p_cmr.add_argument("--warn-only", action="store_true", help="Print warnings without failing exit code")
    p_cmr.set_defaults(func=cmd_check_media_refs)

    p_norm = sub.add_parser(
        "normalize",
        help="Canonicalize v0.2 core and compile normalized 100g/100ml layer + fingerprints",
    )
    p_norm.add_argument("paths", nargs="+", help="Edition JSON files or directories")
    p_norm.add_argument("--in-place", action="store_true", help="Write normalized output back to file")
    p_norm.add_argument(
        "--parse-ingredients",
        action="store_true",
        help="Re-parse span-free core.ingredients_tree from attributes.ingredients_text before normalizing",
    )
    p_norm.set_defaults(func=cmd_normalize)

    p_ing = sub.add_parser(
        "parse-ingredients",
        help="Parse raw ingredients text into span-free v0.2 AST and verify monotonic round-trip",
    )
    p_ing.add_argument("text", help="Raw ingredients text from label")
    p_ing.add_argument("--lang", default="zh-Hans", help="BCP-47 language code (default: zh-Hans)")
    p_ing.add_argument(
        "--profile",
        default="CN/GB28050-2011",
        help="Regulatory profile ID (default: CN/GB28050-2011)",
    )
    p_ing.add_argument(
        "--with-spans",
        action="store_true",
        help="Also compute and attach [start, end] spans for UI highlighting",
    )
    p_ing.set_defaults(func=cmd_parse_ingredients)

    p_build = sub.add_parser("build", help="Build static /v1/ API endpoints and indices")
    p_build.add_argument("--data-dir", required=True, help="Directory containing products tree")
    p_build.add_argument("--out-dir", required=True, help="Output directory for static API")
    p_build.add_argument("--canonical-base", default="", help="Optional canonical base URL")
    p_build.add_argument(
        "--media-base-url",
        default=os.environ.get("OPF_MEDIA_BASE_URL", ""),
        help="Base URL that opf-media://sha256/<hex> references resolve against (default env OPF_MEDIA_BASE_URL)",
    )
    p_build.set_defaults(func=cmd_build)

    p_sub = sub.add_parser(
        "submit",
        help="Sanitize, normalize, route conflicts, and submit an OPF v0.2 edition into products/",
    )
    p_sub.add_argument("--input", required=True, help="Path to draft JSON")
    p_sub.add_argument("--out-dir", required=True, help="Target products root directory")
    p_sub.add_argument("--amend", help="Amend an existing edition ULID (errata; auto-merges on collision)")
    p_sub.add_argument("--supersede", action="extend", nargs="+", help="Create a new edition superseding existing ULID(s)")
    p_sub.add_argument("--new-variant", action="store_true", help="Create a concurrent variant edition")
    p_sub.add_argument("--track", help="Target track key (e.g. CN/default or CN/plant:SC111)")
    p_sub.add_argument("--author", help="Revision author (e.g. github:alice)")
    p_sub.add_argument("--reason", help="Revision reason")
    p_sub.add_argument("--specimen-id", help="Specimen grouping identifier for submitted label photos")
    p_sub.add_argument("--vintage-month", help="Coarse YYYY-MM production month attached to label photos")
    p_sub.add_argument(
        "--photo",
        action="append",
        help="Cropped label photo '<region>=<path>' (repeatable; transcodes to <=1000px EXIF-free WebP)",
    )
    p_sub.add_argument("--media-out-dir", help="Optional content-addressed media root to write WebP crops")
    p_sub.add_argument("--media-stage-dir", help="Optional directory containing pre-sanitized WebP files")
    p_sub.add_argument("--quiet", action="store_true", help="Suppress JSON status output")
    p_sub.set_defaults(func=cmd_submit)

    p_ret = sub.add_parser("retrack", help="Move an edition onto a documented track (kind: retrack)")
    p_ret.add_argument("--out-dir", required=True, help="Products root directory")
    p_ret.add_argument("--id", required=True, help="Canonical product ID")
    p_ret.add_argument("--edition", required=True, help="Target edition ULID")
    p_ret.add_argument("--track", required=True, help="New track key")
    p_ret.add_argument("--author", required=True, help="Revision author")
    p_ret.add_argument("--evidence-ref", action="extend", nargs="+", required=True, help="Evidence ID(s)")
    p_ret.add_argument("--reason", help="Reason for track assignment")
    p_ret.add_argument("--discriminator-method", help="Track discriminator method for product.json")
    p_ret.add_argument("--discriminator-field", help="Optional edition field path for discriminator")
    p_ret.add_argument(
        "--instruction",
        action="append",
        help="Localized track disambiguation instruction as '<lang>=<text>' (repeatable)",
    )
    p_ret.add_argument("--quiet", action="store_true", help="Suppress JSON status output")
    p_ret.set_defaults(func=cmd_retrack)

    p_mrg = sub.add_parser("merge", help="Consolidate a duplicate edition into canonical ULID via EditionRedirect")
    p_mrg.add_argument("--out-dir", required=True, help="Products root directory")
    p_mrg.add_argument("--id", required=True, help="Canonical product ID")
    p_mrg.add_argument("--source", required=True, help="Duplicate edition ULID to absorb and redirect")
    p_mrg.add_argument("--into", required=True, help="Surviving canonical edition ULID")
    p_mrg.add_argument("--author", default="opf:maintainer", help="Author for enrichment if attributes added")
    p_mrg.add_argument("--reason", help="Reason for consolidation")
    p_mrg.add_argument("--force", action="store_true", help="Allow merge when core_fingerprints differ (if no attribute conflict)")
    p_mrg.add_argument("--quiet", action="store_true", help="Suppress JSON status output")
    p_mrg.set_defaults(func=cmd_merge)

    p_lc = sub.add_parser("lifecycle", help="Update lifecycle state or supersedes edges (kind: lifecycle)")
    p_lc.add_argument("--out-dir", required=True, help="Products root directory")
    p_lc.add_argument("--id", required=True, help="Canonical product ID")
    p_lc.add_argument("--edition", required=True, help="Target edition ULID")
    p_lc.add_argument("--author", required=True, help="Revision author")
    p_lc.add_argument("--reason", required=True, help="Reason for lifecycle update")
    p_lc.add_argument("--evidence-ref", action="extend", nargs="+", required=True, help="Evidence ID(s)")
    p_lc.add_argument("--state", choices=["discontinued", "retracted"], help="Administrative lifecycle state")
    p_lc.add_argument("--effective-month", help="Optional YYYY-MM effective month")
    p_lc.add_argument("--add-supersedes", action="extend", nargs="+", help="Older edition ULID(s) to supersede")
    p_lc.add_argument("--quiet", action="store_true", help="Suppress JSON status output")
    p_lc.set_defaults(func=cmd_lifecycle)

    p_pr = sub.add_parser(
        "pr",
        help="Submit product + cropped label WebPs, auto-fork if needed, and open cross-linked opf-media/opf-data PRs",
    )
    p_pr.add_argument("--input", required=True, help="Path to draft JSON")
    p_pr.add_argument("--data-repo", help="Optional path to local opf-data git clone (omit for remote sparse/fork mode)")
    p_pr.add_argument("--media-repo", help="Optional path to local opf-media git clone")
    p_pr.add_argument(
        "--target-data-repo",
        default=os.environ.get("OPF_DATA_REPO", "mickey996icu/opf-data"),
        help="Target GitHub data repo '<namespace>/<repo>'",
    )
    p_pr.add_argument(
        "--target-media-repo",
        default=os.environ.get("OPF_MEDIA_REPO", "mickey996icu/opf-media"),
        help="Target GitHub media repo '<namespace>/<repo>'",
    )
    p_pr.add_argument("--amend", help="Forward --amend to submit")
    p_pr.add_argument("--supersede", action="extend", nargs="+", help="Forward --supersede to submit")
    p_pr.add_argument("--new-variant", action="store_true", help="Forward --new-variant to submit")
    p_pr.add_argument("--track", help="Forward --track to submit")
    p_pr.add_argument("--author", help="Forward --author to submit")
    p_pr.add_argument("--reason", help="Forward --reason to submit")
    p_pr.add_argument("--specimen-id", help="Forward --specimen-id to submit")
    p_pr.add_argument("--vintage-month", help="Coarse YYYY-MM production month attached to label photos")
    p_pr.add_argument(
        "--photo",
        action="append",
        help="Cropped label photo '<region>=<path>' (repeatable; transcodes to <=1000px EXIF-free WebP)",
    )
    p_pr.add_argument("--media-stage-dir", help="Optional directory containing pre-sanitized WebP files")
    p_pr.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and stage locally without committing, pushing, or invoking gh",
    )
    p_pr.add_argument("--quiet", action="store_true", help="Suppress JSON status output")
    p_pr.set_defaults(func=cmd_pr)

    p_media = sub.add_parser(
        "sanitize-media",
        help="Transcode cropped label photos to <=1000px EXIF-free WebP (or strip losslessly with --lossless-only)",
    )
    p_media.add_argument("images", nargs="+", help="Image files (JPEG, PNG, WebP)")
    p_media.add_argument("--media-root", help="Write content-addressed <dir>/media/<h0:2>/<h2:4>/<sha256>.webp")
    p_media.add_argument("--out-dir", help="Optional directory to write sanitized images")
    p_media.add_argument("--max-edge", type=int, default=1000, help="Max pixel edge in WebP mode (default: 1000)")
    p_media.add_argument("--quality", type=int, default=80, help="WebP quality 1-100 (default: 80)")
    p_media.add_argument(
        "--lossless-only",
        action="store_true",
        help="Strip EXIF/XMP/IPTC metadata in original image format without WebP transcoding",
    )
    p_media.set_defaults(func=cmd_sanitize_media)

    p_serve = sub.add_parser("serve", help="Serve the static API and Catalog Card Explorer locally")
    p_serve.add_argument("--dir", help="Directory containing built static site")
    p_serve.add_argument("--data-dir", help="Build from products directory before serving")
    p_serve.add_argument(
        "--media-base-url",
        default=os.environ.get("OPF_MEDIA_BASE_URL", ""),
        help="Optional media base URL when building with --data-dir",
    )
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
