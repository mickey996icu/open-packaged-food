"""Edition governance CLI commands (`retrack`, `merge`, `lifecycle`) for OPF v0.3."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from opf.cli_common import (
    commit_validated_product_dir,
    load_existing_product_dir,
    now_iso,
    resolve_agreement_ref,
    today_ymd,
)
from opf.cli_merge_ops import consolidate_duplicate_into
from opf.ids import validate_product_id, validate_track_key
from opf.patches import diff_to_patch, extract_patchable_surface, invert_patch
from opf.validator import AGREEMENT_REQUIRED_PROVENANCES, VALID_PROVENANCES


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
    product_meta, records, redirects, load_errs = load_existing_product_dir(out_root, pid)
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
        retrack_prov = getattr(args, "provenance", None) or "external_contributor"
        retrack_ref = resolve_agreement_ref(getattr(args, "agreement_ref", None))
        if retrack_prov in AGREEMENT_REQUIRED_PROVENANCES and not retrack_ref:
            print(f"Provenance {retrack_prov!r} requires --agreement-ref <id>.", file=sys.stderr)
            return 1
        rev_entry: dict[str, Any] = {
            "rev": ed["rev"],
            "kind": "retrack",
            "created_at": now_iso(),
            "author": args.author,
            "provenance": retrack_prov,
            "evidence_refs": list(dict.fromkeys(args.evidence_ref)),
            "patch": patch,
            "reverse_patch": rev_patch,
        }
        if retrack_ref:
            rev_entry["agreement_ref"] = retrack_ref
        if args.reason:
            rev_entry["reason"] = args.reason
        ed["revisions"].append(rev_entry)
        records[eid] = ed
        action = "retracked"

    commit_errs = commit_validated_product_dir(out_root, pid, product_meta, records, redirects)
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
    product_meta, records, redirects, load_errs = load_existing_product_dir(out_root, pid)
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

    merge_prov = getattr(args, "provenance", None) or "external_contributor"
    merge_ref = resolve_agreement_ref(getattr(args, "agreement_ref", None))
    if merge_prov in AGREEMENT_REQUIRED_PROVENANCES and not merge_ref:
        print(f"Provenance {merge_prov!r} requires --agreement-ref <id>.", file=sys.stderr)
        return 1

    merge_reason = args.reason or f"Merged duplicate edition {args.source} into {args.into}"
    updated_tgt, redir_stub, conflicts = consolidate_duplicate_into(
        src,
        tgt,
        redirects,
        author=args.author,
        provenance=merge_prov,
        agreement_ref=merge_ref,
        reason=merge_reason,
        created_at_iso=now_iso(),
        merged_at_ymd=today_ymd(),
    )
    if conflicts:
        print("Cannot merge due to attribute conflicts:", file=sys.stderr)
        for c in conflicts:
            print(f"  - {c}", file=sys.stderr)
        return 1

    records[args.into] = updated_tgt
    del records[args.source]
    redirects[args.source] = redir_stub

    commit_errs = commit_validated_product_dir(out_root, pid, product_meta, records, redirects)
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
    product_meta, records, redirects, load_errs = load_existing_product_dir(out_root, pid)
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
        lc_prov = getattr(args, "provenance", None) or "external_contributor"
        lc_ref = resolve_agreement_ref(getattr(args, "agreement_ref", None))
        if lc_prov in AGREEMENT_REQUIRED_PROVENANCES and not lc_ref:
            print(f"Provenance {lc_prov!r} requires --agreement-ref <id>.", file=sys.stderr)
            return 1
        if "lifecycle" in new_surface:
            ed["lifecycle"] = new_surface["lifecycle"]
        if "supersedes" in new_surface:
            ed["supersedes"] = new_surface["supersedes"]
        ed["rev"] += 1
        lc_rev_entry: dict[str, Any] = {
            "rev": ed["rev"],
            "kind": "lifecycle",
            "created_at": now_iso(),
            "author": args.author,
            "provenance": lc_prov,
            "reason": args.reason,
            "evidence_refs": ev_refs,
            "patch": patch,
            "reverse_patch": rev_patch,
        }
        if lc_ref:
            lc_rev_entry["agreement_ref"] = lc_ref
        ed["revisions"].append(lc_rev_entry)
        records[eid] = ed
        action = "lifecycle_updated"

    commit_errs = commit_validated_product_dir(out_root, pid, product_meta, records, redirects)
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


def register_lifecycle_subparsers(sub: argparse._SubParsersAction) -> None:
    p_ret = sub.add_parser("retrack", help="Move an edition onto a documented track (kind: retrack)")
    p_ret.add_argument("--out-dir", required=True, help="Products root directory")
    p_ret.add_argument("--id", required=True, help="Canonical product ID")
    p_ret.add_argument("--edition", required=True, help="Target edition ULID")
    p_ret.add_argument("--track", required=True, help="New track key")
    p_ret.add_argument("--author", required=True, help="Revision author")
    p_ret.add_argument(
        "--provenance",
        choices=VALID_PROVENANCES,
        default="external_contributor",
        help="Rights/origin provenance for the retrack revision (default: external_contributor)",
    )
    p_ret.add_argument(
        "--agreement-ref",
        help="Internal agreement reference ID (required for 'brand_owner' or 'partner')",
    )
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
    p_mrg.add_argument(
        "--provenance",
        choices=VALID_PROVENANCES,
        default="external_contributor",
        help="Rights/origin provenance for enrichment revision if attributes added (default: external_contributor)",
    )
    p_mrg.add_argument(
        "--agreement-ref",
        help="Internal agreement reference ID (required for 'brand_owner' or 'partner')",
    )
    p_mrg.add_argument("--reason", help="Reason for consolidation")
    p_mrg.add_argument("--force", action="store_true", help="Allow merge when core_fingerprints differ (if no attribute conflict)")
    p_mrg.add_argument("--quiet", action="store_true", help="Suppress JSON status output")
    p_mrg.set_defaults(func=cmd_merge)

    p_lc = sub.add_parser("lifecycle", help="Update lifecycle state or supersedes edges (kind: lifecycle)")
    p_lc.add_argument("--out-dir", required=True, help="Products root directory")
    p_lc.add_argument("--id", required=True, help="Canonical product ID")
    p_lc.add_argument("--edition", required=True, help="Target edition ULID")
    p_lc.add_argument("--author", required=True, help="Revision author")
    p_lc.add_argument(
        "--provenance",
        choices=VALID_PROVENANCES,
        default="external_contributor",
        help="Rights/origin provenance for lifecycle revision (default: external_contributor)",
    )
    p_lc.add_argument(
        "--agreement-ref",
        help="Internal agreement reference ID (required for 'brand_owner' or 'partner')",
    )
    p_lc.add_argument("--reason", required=True, help="Reason for lifecycle update")
    p_lc.add_argument("--evidence-ref", action="extend", nargs="+", required=True, help="Evidence ID(s)")
    p_lc.add_argument("--state", choices=["discontinued", "retracted"], help="Administrative lifecycle state")
    p_lc.add_argument("--effective-month", help="Optional YYYY-MM effective month")
    p_lc.add_argument("--add-supersedes", action="extend", nargs="+", help="Older edition ULID(s) to supersede")
    p_lc.add_argument("--quiet", action="store_true", help="Suppress JSON status output")
    p_lc.set_defaults(func=cmd_lifecycle)
