"""Submission draft preparation, conflict routing, and `opf submit` command for OPF v0.3."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from opf.cli_common import (
    commit_validated_product_dir,
    load_existing_product_dir,
    now_iso,
    prepare_submission_inputs,
    resolve_agreement_ref,
    resolve_provenance,
    strip_forbidden_keys_in_place,
    today_ymd,
)
from opf.cli_merge_ops import (
    consolidate_duplicate_into,
    merge_attributes_for_amend,
    merge_evidence_append_only,
    plan_attribute_merge,
)
from opf.ids import (
    generate_ulid,
    is_valid_ulid,
    product_dir_for_id,
    validate_product_id,
    validate_track_key,
)
from opf.ingredients import parse_ingredients_semantic
from opf.normalize import normalize_edition
from opf.patches import (
    apply_patch,
    diff_to_patch,
    extract_patchable_surface,
    invert_patch,
)
from opf.validator import AGREEMENT_REQUIRED_PROVENANCES, VALID_PROVENANCES


def _prepare_candidate_from_draft(
    draft: dict[str, Any],
    *,
    track: str,
    specimen_id_override: str | None = None,
    default_provenance: str = "external_contributor",
    default_agreement_ref: str | None = None,
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
        if not ev.get("provenance"):
            ev["provenance"] = default_provenance
        if ev.get("provenance") in AGREEMENT_REQUIRED_PROVENANCES and not ev.get("agreement_ref") and default_agreement_ref:
            ev["agreement_ref"] = default_agreement_ref
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
    if core_copy.get("net_content") is None:
        core_copy["net_content"] = []
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
        "opf_schema": "0.3",
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


def execute_submit(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
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

    removed_keys = strip_forbidden_keys_in_place(draft)

    pid = str(draft.get("id") or "")
    id_errs = validate_product_id(pid)
    if id_errs:
        for e in id_errs:
            print(f"ID error: {e}", file=sys.stderr)
        return 1, {}

    out_root = Path(args.out_dir)
    product_meta, records, redirects, load_errs = load_existing_product_dir(out_root, pid)
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
    provenance = resolve_provenance(getattr(args, "provenance", None), draft)
    agreement_ref = resolve_agreement_ref(getattr(args, "agreement_ref", None), draft)
    if provenance in AGREEMENT_REQUIRED_PROVENANCES and not agreement_ref:
        print(
            f"Provenance {provenance!r} requires --agreement-ref <id> (or agreement_ref in draft).",
            file=sys.stderr,
        )
        return 1, {}
    cli_track = getattr(args, "track", None)
    specimen_id_override = getattr(args, "specimen_id", None)

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
        draft,
        track=track,
        specimen_id_override=specimen_id_override,
        default_provenance=provenance,
        default_agreement_ref=agreement_ref,
    )
    if prep_errs:
        for e in prep_errs:
            print(f"Draft error: {e}", file=sys.stderr)
        return 1, {}

    cur_iso = now_iso()
    cur_ymd = today_ymd()
    action = ""
    result_edition_id = candidate["edition_id"]
    merged_into_id: str | None = None

    if amend_target:
        target_id = amend_target if amend_target not in redirects else redirects[amend_target]["merged_into"]
        target_rec = records[target_id]
        old_surface = extract_patchable_surface(target_rec)
        amended = copy.deepcopy(target_rec)
        added_ev = merge_evidence_append_only(amended, candidate["evidence"])
        amended["core"] = copy.deepcopy(candidate["core"])
        amended["attributes"] = merge_attributes_for_amend(
            amended["attributes"], candidate["attributes"]
        )
        normalize_edition(amended)

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
            updated_other, redir_stub, conflicts = consolidate_duplicate_into(
                amended,
                collision,
                redirects,
                author=author,
                provenance=provenance,
                agreement_ref=agreement_ref,
                reason=merge_reason,
                created_at_iso=cur_iso,
                merged_at_ymd=cur_ymd,
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
                    "created_at": cur_iso,
                    "author": author,
                    "provenance": provenance,
                    "evidence_refs": ev_refs,
                    "patch": patch,
                    "reverse_patch": rev_patch,
                }
                if agreement_ref:
                    rev_entry["agreement_ref"] = agreement_ref
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
        init_rev: dict[str, Any] = {
            "rev": 1,
            "kind": "initial",
            "created_at": cur_iso,
            "author": author,
            "provenance": provenance,
            "evidence_refs": [ev["evidence_id"] for ev in candidate["evidence"]],
            "patch": [],
        }
        if agreement_ref:
            init_rev["agreement_ref"] = agreement_ref
        if reason:
            init_rev["reason"] = reason
        candidate["revisions"] = [init_rev]
        normalize_edition(candidate)
        records[new_id] = candidate
        action = "superseded_edition"
        result_edition_id = new_id

    elif new_variant:
        new_id = candidate["edition_id"]
        if new_id in records or new_id in redirects or not is_valid_ulid(new_id):
            new_id = generate_ulid()
        candidate["edition_id"] = new_id
        init_rev = {
            "rev": 1,
            "kind": "initial",
            "created_at": cur_iso,
            "author": author,
            "provenance": provenance,
            "evidence_refs": [ev["evidence_id"] for ev in candidate["evidence"]],
            "patch": [],
        }
        if agreement_ref:
            init_rev["agreement_ref"] = agreement_ref
        if reason:
            init_rev["reason"] = reason
        candidate["revisions"] = [init_rev]
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
            init_rev = {
                "rev": 1,
                "kind": "initial",
                "created_at": cur_iso,
                "author": author,
                "provenance": provenance,
                "evidence_refs": [ev["evidence_id"] for ev in candidate["evidence"]],
                "patch": [],
            }
            if agreement_ref:
                init_rev["agreement_ref"] = agreement_ref
            if reason:
                init_rev["reason"] = reason
            candidate["revisions"] = [init_rev]
            normalize_edition(candidate)
            records[new_id] = candidate
            action = "created_edition"
            result_edition_id = new_id
        else:
            existing_id = existing_head["edition_id"]
            enrich_ops, conflicts = plan_attribute_merge(
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
            added_ev = merge_evidence_append_only(updated, candidate["evidence"])
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
                    "created_at": cur_iso,
                    "author": author,
                    "provenance": provenance,
                    "evidence_refs": ev_refs,
                    "patch": enrich_ops,
                    "reverse_patch": rev_patch,
                }
                if agreement_ref:
                    rev_entry["agreement_ref"] = agreement_ref
                if reason:
                    rev_entry["reason"] = reason
                updated["revisions"].append(rev_entry)
                normalize_edition(updated)
                action = "enriched_edition"
            else:
                action = "corroborated_edition" if added_ev else "unchanged"

            records[existing_id] = updated
            result_edition_id = existing_id

    commit_errs = commit_validated_product_dir(out_root, pid, product_meta, records, redirects)
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


def cmd_submit(args: argparse.Namespace) -> int:
    photo_specs = getattr(args, "photo", None) or []
    media_out_raw = getattr(args, "media_out_dir", None)
    media_stage_raw = getattr(args, "media_stage_dir", None)
    vintage_month = getattr(args, "vintage_month", None)

    if photo_specs or media_out_raw or media_stage_raw or vintage_month:
        with tempfile.TemporaryDirectory(prefix="opf-submit-") as tmp:
            tmp_path = Path(tmp)
            prep_path, staged_blobs, errs = prepare_submission_inputs(
                Path(args.input),
                photo_specs=photo_specs,
                media_stage_root=None,
                media_out_dir=Path(media_out_raw) if media_out_raw else None,
                media_stage_dir=Path(media_stage_raw) if media_stage_raw else None,
                vintage_month=vintage_month,
                contributor=getattr(args, "author", None),
                provenance=getattr(args, "provenance", None),
                agreement_ref=getattr(args, "agreement_ref", None),
                specimen_id=getattr(args, "specimen_id", None),
                temp_dir=tmp_path,
            )
            if errs:
                for e in errs:
                    print(f"Media preparation error: {e}", file=sys.stderr)
                return 1
            sub_ns = argparse.Namespace(**vars(args))
            sub_ns.input = str(prep_path)
            rc, summary = execute_submit(sub_ns)
            if rc == 0 and staged_blobs:
                summary["staged_media"] = staged_blobs
    else:
        rc, summary = execute_submit(args)

    if rc == 0 and not getattr(args, "quiet", False):
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return rc


def register_submit_subparser(sub: argparse._SubParsersAction) -> None:
    p_sub = sub.add_parser(
        "submit",
        help="Sanitize, normalize, route conflicts, and submit an OPF v0.3 edition into products/",
    )
    p_sub.add_argument("--input", required=True, help="Path to draft JSON")
    p_sub.add_argument("--out-dir", required=True, help="Target products root directory")
    p_sub.add_argument("--amend", help="Amend an existing edition ULID (errata; auto-merges on collision)")
    p_sub.add_argument("--supersede", action="extend", nargs="+", help="Create a new edition superseding existing ULID(s)")
    p_sub.add_argument("--new-variant", action="store_true", help="Create a concurrent variant edition")
    p_sub.add_argument("--track", help="Target track key (e.g. CN/default or CN/plant:SC111)")
    p_sub.add_argument("--author", help="Revision author (e.g. github:alice)")
    p_sub.add_argument(
        "--provenance",
        choices=VALID_PROVENANCES,
        help="Rights/origin provenance for new evidence/revision entries (default: inferred or 'external_contributor')",
    )
    p_sub.add_argument(
        "--agreement-ref",
        help="Internal agreement reference ID (required when provenance is 'brand_owner' or 'partner')",
    )
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
