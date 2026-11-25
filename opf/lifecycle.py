"""Deterministic build-time evidence_level and temporal lifecycle derivation for OPF v0.3."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")
_OPF_MEDIA_RE = re.compile(r"^opf-media://sha256/([a-f0-9]{64})$")
_YEAR_4DIGIT_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def derive_evidence_level(edition: dict[str, Any]) -> str:
    """Deterministically derive build-time evidence_level from evidence[] per SPEC §8.6."""
    evidence = edition.get("evidence") or []
    photo_contributors: set[str] = set()
    has_official_import = False

    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        if etype == "label_photo":
            sha = str(ev.get("cropped_sha256") or "")
            mref = str(ev.get("media_ref") or "")
            contrib = str(ev.get("contributor") or "").strip()
            if _SHA256_HEX_RE.match(sha) and mref:
                m_media = _OPF_MEDIA_RE.match(mref)
                if mref.startswith("opf-media://") and (not m_media or m_media.group(1) != sha):
                    continue
                if contrib:
                    photo_contributors.add(contrib)
        elif etype in ("official_registry_import", "official_document"):
            has_official_import = True

    if len(photo_contributors) >= 2:
        return "corroborated"
    if len(photo_contributors) == 1:
        return "verified"
    if has_official_import:
        return "official_registry_imported"
    return "community_reported"


def compute_t_active_with_basis(edition: dict[str, Any]) -> tuple[str, str]:
    """Compute (YYYY-MM, basis) where basis is 'vintage_month' or 'earliest_reported_at'."""
    evidence = edition.get("evidence") or []
    vintage_months = [
        str(ev["vintage_month"])
        for ev in evidence
        if isinstance(ev, dict) and ev.get("vintage_month")
    ]
    if vintage_months:
        return max(vintage_months), "vintage_month"

    reported_months = [
        str(ev["reported_at"])[:7]
        for ev in evidence
        if isinstance(ev, dict) and ev.get("reported_at")
    ]
    if not reported_months:
        raise ValueError(
            f"Edition {edition.get('edition_id')!r} has no evidence reported_at or vintage_month"
        )
    return min(reported_months), "earliest_reported_at"


def compute_t_active(edition: dict[str, Any]) -> str:
    """Compute effective market presence month YYYY-MM (max vintage_month, else min reported_at[:7])."""
    ym, _basis = compute_t_active_with_basis(edition)
    return ym


def compute_stale_window_months(edition: dict[str, Any]) -> int:
    """Compute clamped stale window N(E) in [3, 18] months from attributes.shelf_life (default 12)."""
    attributes = edition.get("attributes") or {}
    shelf_life = attributes.get("shelf_life")
    if not isinstance(shelf_life, dict):
        return 12
    val = Decimal(str(shelf_life["value"]))
    unit = str(shelf_life["unit"]).strip().lower()
    if unit in ("month", "months", "mo"):
        months = math.ceil(val)
    elif unit in ("year", "years", "yr"):
        months = math.ceil(val * Decimal("12"))
    elif unit in ("day", "days", "d"):
        months = math.ceil(val / Decimal("30"))
    elif unit in ("week", "weeks", "wk"):
        months = math.ceil((val * Decimal("7")) / Decimal("30"))
    else:
        raise ValueError(f"Unsupported shelf_life unit: {shelf_life['unit']!r}")
    return max(3, min(18, int(months)))


def _months_between(older_ym: str, newer_ym: str) -> int:
    y1, m1 = map(int, older_ym.split("-"))
    y2, m2 = map(int, newer_ym.split("-"))
    return (y2 - y1) * 12 + (m2 - m1)


def _extract_standard_year(edition: dict[str, Any]) -> int:
    candidates: list[int] = []
    profile_id = str((edition.get("core") or {}).get("regulatory_profile") or "")
    for m in _YEAR_4DIGIT_RE.findall(profile_id):
        candidates.append(int(m))
    for std in (edition.get("attributes") or {}).get("product_standard") or []:
        for m in _YEAR_4DIGIT_RE.findall(str(std)):
            candidates.append(int(m))
    return max(candidates) if candidates else 0


def derive_editions_lifecycle(editions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Deterministically derive status, evidence_level, t_active, and superseded_by for all EditionRecords."""
    records: dict[str, dict[str, Any]] = {}
    for ed in editions:
        if isinstance(ed, dict) and "merged_into" not in ed and "edition_id" in ed:
            records[ed["edition_id"]] = ed

    superseded_by: dict[str, list[str]] = {eid: [] for eid in records}
    for eid, ed in records.items():
        state = (ed.get("lifecycle") or {}).get("state")
        if state == "retracted":
            continue
        for target_id in ed.get("supersedes") or []:
            if target_id in superseded_by:
                superseded_by[target_id].append(eid)
    for eid in superseded_by:
        superseded_by[eid] = sorted(set(superseded_by[eid]))

    t_active_pairs = {eid: compute_t_active_with_basis(ed) for eid, ed in records.items()}
    t_active_map: dict[str, str] = {eid: pair[0] for eid, pair in t_active_pairs.items()}
    t_active_basis_map: dict[str, str] = {eid: pair[1] for eid, pair in t_active_pairs.items()}
    ev_level_map: dict[str, str] = {eid: derive_evidence_level(ed) for eid, ed in records.items()}
    status_map: dict[str, str] = {}

    remaining_by_track: dict[str, list[dict[str, Any]]] = {}
    for eid, ed in records.items():
        state = (ed.get("lifecycle") or {}).get("state")
        if state == "retracted":
            status_map[eid] = "retracted"
        elif state == "discontinued":
            status_map[eid] = "discontinued"
        elif superseded_by[eid]:
            status_map[eid] = "superseded"
        else:
            track = str(ed.get("track") or "")
            remaining_by_track.setdefault(track, []).append(ed)

    for _track, candidates in remaining_by_track.items():
        head = max(
            candidates,
            key=lambda e: (
                t_active_map[e["edition_id"]],
                _extract_standard_year(e),
                str((e.get("attributes") or {}).get("packaging_code") or ""),
                e["edition_id"],
            ),
        )
        head_id = head["edition_id"]
        head_t = t_active_map[head_id]
        status_map[head_id] = "active"
        for ed in candidates:
            eid = ed["edition_id"]
            if eid == head_id:
                continue
            gap = _months_between(t_active_map[eid], head_t)
            window = compute_stale_window_months(ed)
            status_map[eid] = "stale" if gap >= window else "active"

    return {
        eid: {
            "status": status_map[eid],
            "evidence_level": ev_level_map[eid],
            "t_active": t_active_map[eid],
            "t_active_basis": t_active_basis_map[eid],
            "superseded_by": superseded_by[eid],
        }
        for eid in records
    }
