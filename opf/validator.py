"""Product directory, supersedes DAG, and root catalog validator for OPF v0.3 (re-exports schema & doc APIs)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opf.edition_validator import (
    AGREEMENT_REQUIRED_PROVENANCES,
    DATE_MONTH_RE,
    DECIMAL_RE,
    FINGERPRINT_RE,
    FORBIDDEN_BATCH_KEYS,
    OPF_MEDIA_RE,
    SHA256_HEX_RE,
    VALID_PROVENANCES,
    public_image_sha,
    validate_edition_doc,
    validate_product_meta_doc,
)
from opf.ids import product_dir_for_id, validate_product_id
from opf.json_schema import load_json_schema, validate_against_json_schema

__all__ = [
    "AGREEMENT_REQUIRED_PROVENANCES",
    "DATE_MONTH_RE",
    "DECIMAL_RE",
    "FINGERPRINT_RE",
    "FORBIDDEN_BATCH_KEYS",
    "OPF_MEDIA_RE",
    "SHA256_HEX_RE",
    "VALID_PROVENANCES",
    "load_json_schema",
    "public_image_sha",
    "validate_against_json_schema",
    "validate_edition_doc",
    "validate_product_dir",
    "validate_product_doc",
    "validate_product_meta_doc",
    "validate_products_root",
]


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
    """Validate a v0.3 product directory (product.json + editions/*.json + cross-edition invariants)."""
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
    """Validate an entire v0.3 products/ tree, rejecting stray or orphan JSON files."""
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
    """Dispatch v0.3 document validation based on document shape (kept for transitional imports)."""
    if not isinstance(doc, dict):
        return ["Document root must be a JSON object"]
    if "edition_id" in doc:
        return validate_edition_doc(doc)
    if "opf_schema" in doc and doc.get("opf_schema") == "0.3":
        return validate_product_meta_doc(doc)
    return ["Unsupported document schema version (expected v0.3 product.json or editions/<ulid>.json)"]
