"""Loader and lookup utilities for OPF dictionaries and regulatory profiles."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from opf.resources import REPO_ROOT, get_resource_root

LATIN_WORD_RE = re.compile(r"^[a-z\u00c0-\u024f0-9\s\-\']+$")
ASCII_WORD_RE = LATIN_WORD_RE


@lru_cache(maxsize=1)
def load_nutrients_dict() -> dict[str, Any]:
    path = get_resource_root() / "dictionaries" / "nutrients.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)["nutrients"]


@lru_cache(maxsize=1)
def load_additives_dict() -> dict[str, Any]:
    path = get_resource_root() / "dictionaries" / "additives_ins.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)["additives"]


@lru_cache(maxsize=1)
def load_allergens_dict() -> dict[str, Any]:
    path = get_resource_root() / "dictionaries" / "allergens.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)["allergens"]


@lru_cache(maxsize=1)
def load_all_profiles() -> dict[str, dict[str, Any]]:
    profiles_dir = get_resource_root() / "profiles"
    merged: dict[str, dict[str, Any]] = {}
    for pfile in sorted(profiles_dir.glob("*/profile.json")):
        with pfile.open("r", encoding="utf-8") as f:
            data = json.load(f)
            for pid, pspec in data.get("profiles", {}).items():
                merged[pid] = pspec
    return merged


def get_profile(profile_id: str) -> dict[str, Any]:
    profiles = load_all_profiles()
    if profile_id not in profiles:
        raise KeyError(f"Unknown regulatory_profile {profile_id!r}. Available: {sorted(profiles)}")
    return profiles[profile_id]


@lru_cache(maxsize=1)
def _build_additive_lookup() -> dict[str, str]:
    """Build case-insensitive name/code -> canonical INS code map."""
    lookup: dict[str, str] = {}
    for ins_code, entry in load_additives_dict().items():
        lookup[ins_code.lower()] = ins_code
        e_num = entry.get("e_number")
        if e_num:
            lookup[e_num.lower()] = ins_code
            lookup[e_num.lower().replace("e", "e ")] = ins_code
        for _lang, names in entry.get("names", {}).items():
            for name in names:
                lookup[name.strip().lower()] = ins_code
    return lookup


def lookup_additive_ins(name_or_code: str) -> str | None:
    """Return canonical Codex INS code if name_or_code matches known additive, else None."""
    key = re.sub(r"\s+", " ", name_or_code.strip().lower())
    m_ins = re.match(r"^ins[\s\-]+(.+)$", key)
    if m_ins:
        key = m_ins.group(1).strip()
    elif key.startswith("ins"):
        key = key[3:].strip()
    m_e = re.match(r"^e[\s\-]+([0-9].*)$", key)
    if m_e:
        key = "e" + m_e.group(1).strip()
    return _build_additive_lookup().get(key)


@lru_cache(maxsize=1)
def _build_allergen_matchers() -> list[tuple[str, tuple[str, ...], tuple[tuple[str, re.Pattern[str] | None], ...]]]:
    """Precompile sorted lowercase exclusions and optional word-boundary regexes per allergen."""
    compiled: list[tuple[str, tuple[str, ...], tuple[tuple[str, re.Pattern[str] | None], ...]]] = []
    for allergen_id, spec in load_allergens_dict().items():
        raw_excludes = {
            ex.strip().lower()
            for ex_list in (spec.get("exclude_keywords") or {}).values()
            for ex in ex_list
            if ex and ex.strip()
        }
        sorted_excludes = tuple(sorted(raw_excludes, key=len, reverse=True))

        kw_entries: list[tuple[str, re.Pattern[str] | None]] = []
        seen_kw: set[str] = set()
        for keywords in (spec.get("keywords") or {}).values():
            for kw in keywords:
                kw_low = kw.strip().lower()
                if not kw_low or kw_low in seen_kw:
                    continue
                seen_kw.add(kw_low)
                if LATIN_WORD_RE.match(kw_low):
                    pat = re.compile(
                        r"(?<![a-z\u00c0-\u024f0-9])" + re.escape(kw_low) + r"(?![a-z\u00c0-\u024f0-9])"
                    )
                    kw_entries.append((kw_low, pat))
                else:
                    kw_entries.append((kw_low, None))
        compiled.append((allergen_id, sorted_excludes, tuple(kw_entries)))
    return compiled


def match_allergens_in_name(ingredient_name: str) -> list[str]:
    """Return sorted list of canonical allergen IDs matched in an ingredient name.

    Uses dictionary keywords + longest-first exclusion masking to prevent false positives
    such as '蛋白质' / '植物蛋白' -> eggs or '乳酸' / '乳化剂' -> milk.
    """
    base_lowered = ingredient_name.strip().lower()
    if not base_lowered:
        return []

    matched: list[str] = []
    for allergen_id, sorted_excludes, kw_entries in _build_allergen_matchers():
        masked = base_lowered
        for ex_low in sorted_excludes:
            if ex_low in masked:
                masked = masked.replace(ex_low, " ")

        for kw_low, pat in kw_entries:
            if kw_low in masked and (pat is None or pat.search(masked)):
                matched.append(allergen_id)
                break
    return sorted(matched)
