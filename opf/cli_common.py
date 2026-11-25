"""Shared CLI state helpers, provenance resolution, staging commits, and media draft preparation for OPF v0.3."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opf.ids import product_dir_for_id
from opf.media import (
    CANONICAL_EVIDENCE_REGIONS,
    FORBIDDEN_FRONT_REGIONS,
    LEGACY_REGION_ALIASES,
    normalize_evidence_region,
    process_cropped_label_to_webp,
)
from opf.validator import FORBIDDEN_BATCH_KEYS, VALID_PROVENANCES, validate_product_dir


def resolve_provenance(
    explicit: str | None,
    draft: dict[str, Any] | None = None,
    *,
    default: str = "external_contributor",
) -> str:
    if isinstance(explicit, str) and explicit in VALID_PROVENANCES:
        return explicit
    if isinstance(draft, dict):
        top_prov = draft.get("provenance")
        if isinstance(top_prov, str) and top_prov in VALID_PROVENANCES:
            return top_prov
        ev_provs = {
            str(ev["provenance"])
            for ev in (draft.get("evidence") or [])
            if isinstance(ev, dict) and isinstance(ev.get("provenance"), str) and ev["provenance"] in VALID_PROVENANCES
        }
        if len(ev_provs) == 1:
            return next(iter(ev_provs))
    return default


def resolve_agreement_ref(
    explicit: str | None,
    draft: dict[str, Any] | None = None,
) -> str | None:
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if isinstance(draft, dict):
        top_ref = draft.get("agreement_ref")
        if isinstance(top_ref, str) and top_ref.strip():
            return top_ref.strip()
        ev_refs = {
            str(ev["agreement_ref"]).strip()
            for ev in (draft.get("evidence") or [])
            if isinstance(ev, dict) and isinstance(ev.get("agreement_ref"), str) and ev["agreement_ref"].strip()
        }
        if len(ev_refs) == 1:
            return next(iter(ev_refs))
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_ymd() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def strip_forbidden_keys_in_place(obj: Any) -> list[str]:
    removed: list[str] = []
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            if k in FORBIDDEN_BATCH_KEYS:
                removed.append(k)
                del obj[k]
            else:
                removed.extend(strip_forbidden_keys_in_place(obj[k]))
    elif isinstance(obj, list):
        for item in obj:
            removed.extend(strip_forbidden_keys_in_place(item))
    return removed


def load_existing_product_dir(
    out_root: Path, product_id: str
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    """Load existing product.json + editions/*.json into memory, or return fresh empty state."""
    pdir = product_dir_for_id(out_root, product_id)
    if not pdir.exists():
        return {"opf_schema": "0.3", "id": product_id}, {}, {}, []

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


def commit_validated_product_dir(
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
        write_json(stage_pdir / "product.json", product_meta)
        for eid, rec in records.items():
            write_json(stage_editions / f"{eid}.json", rec)
        for eid, redir in redirects.items():
            write_json(stage_editions / f"{eid}.json", redir)

        errs = validate_product_dir(stage_pdir, products_root=stage_root)
        if errs:
            return errs

    target_pdir = out_root / rel_dir
    target_editions = target_pdir / "editions"
    target_editions.mkdir(parents=True, exist_ok=True)
    write_json(target_pdir / "product.json", product_meta)
    for eid, rec in records.items():
        write_json(target_editions / f"{eid}.json", rec)
    for eid, redir in redirects.items():
        write_json(target_editions / f"{eid}.json", redir)
    return []


def parse_photo_specs(raw_specs: list[str] | None) -> list[tuple[str, Path]]:
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


def prepare_submission_inputs(
    draft_path: Path,
    *,
    photo_specs: list[str] | None = None,
    media_stage_root: Path | None = None,
    media_out_dir: Path | None = None,
    media_stage_dir: Path | None = None,
    vintage_month: str | None = None,
    contributor: str | None = None,
    provenance: str | None = None,
    agreement_ref: str | None = None,
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
    inferred_provenance = resolve_provenance(provenance, draft_obj)
    inferred_agreement_ref = resolve_agreement_ref(agreement_ref, draft_obj)

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
        parsed_photos = parse_photo_specs(photo_specs)
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
                "provenance": inferred_provenance,
                "region": region,
                "cropped_sha256": rep["sha256"],
                "media_ref": rep["media_ref"],
                "contributor": inferred_contributor,
                "reported_at": today_ymd(),
            }
            if inferred_agreement_ref:
                ev_item["agreement_ref"] = inferred_agreement_ref
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
