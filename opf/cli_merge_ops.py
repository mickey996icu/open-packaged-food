"""Attribute enrichment merge planning, evidence append helpers, and duplicate consolidation for OPF v0.3 CLI."""

from __future__ import annotations

import copy
import json
from typing import Any

from opf.fingerprints import format_canonical_decimal
from opf.normalize import normalize_edition
from opf.patches import apply_patch, extract_patchable_surface, invert_patch


def _canon_party_set(parties: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for p in parties:
        cleaned = {k: str(v).strip() for k, v in p.items() if v is not None and str(v).strip()}
        out.add(json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return out


def plan_attribute_merge(
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


def merge_evidence_append_only(
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


def merge_attributes_for_amend(
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


def consolidate_duplicate_into(
    source_ed: dict[str, Any],
    target_ed: dict[str, Any],
    redirects: dict[str, dict[str, Any]],
    *,
    author: str,
    provenance: str = "external_contributor",
    agreement_ref: str | None = None,
    reason: str,
    created_at_iso: str,
    merged_at_ymd: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Absorb source_ed evidence & missing attributes into target_ed and emit an EditionRedirect stub."""
    enrich_ops, conflicts = plan_attribute_merge(
        target_ed["attributes"],
        source_ed["attributes"],
        ignore_same_lang_ing_punct=True,
    )
    if conflicts:
        return {}, {}, conflicts

    updated_target = copy.deepcopy(target_ed)
    merge_evidence_append_only(updated_target, source_ed.get("evidence") or [])

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
        rev_entry: dict[str, Any] = {
            "rev": updated_target["rev"],
            "kind": "enrichment",
            "created_at": created_at_iso,
            "author": author,
            "provenance": provenance,
            "reason": reason,
            "evidence_refs": ev_refs,
            "patch": enrich_ops,
            "reverse_patch": rev_patch,
        }
        if agreement_ref:
            rev_entry["agreement_ref"] = agreement_ref
        updated_target["revisions"].append(rev_entry)
        normalize_edition(updated_target)

    source_id = source_ed["edition_id"]
    target_id = updated_target["edition_id"]
    for redir in redirects.values():
        if redir.get("merged_into") == source_id:
            redir["merged_into"] = target_id

    redirect_stub: dict[str, Any] = {
        "opf_schema": "0.3",
        "id": updated_target["id"],
        "edition_id": source_id,
        "merged_into": target_id,
        "merged_into_rev": updated_target["rev"],
        "merged_at": merged_at_ymd,
        "reason": reason,
    }
    return updated_target, redirect_stub, []
