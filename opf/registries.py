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


def _contains_keyword(text: str, kw: str) -> bool:
    kw_low = kw.strip().lower()
    if not kw_low:
        return False
    if LATIN_WORD_RE.match(kw_low):
        pattern = r"(?<![a-z\u00c0-\u024f0-9])" + re.escape(kw_low) + r"(?![a-z\u00c0-\u024f0-9])"
        return bool(re.search(pattern, text))
    return kw_low in text


def match_allergens_in_name(ingredient_name: str) -> list[str]:
    """Return sorted list of canonical allergen IDs matched in an ingredient name.

    Uses dictionary keywords + longest-first exclusion masking to prevent false positives
    such as '蛋白质' / '植物蛋白' -> eggs or '乳酸' / '乳化剂' -> milk.
    """
    base_lowered = ingredient_name.strip().lower()
    if not base_lowered:
        return []

    matched: set[str] = set()
    for allergen_id, spec in load_allergens_dict().items():
        # Mask out exclusion terms for this allergen (longest first)
        masked = base_lowered
        all_excludes: list[str] = []
        for _lang, ex_list in (spec.get("exclude_keywords") or {}).items():
            all_excludes.extend(ex_list)
        for ex in sorted(all_excludes, key=len, reverse=True):
            ex_low = ex.strip().lower()
            if ex_low and ex_low in masked:
                masked = masked.replace(ex_low, " ")

        found = False
        for _lang, keywords in spec.get("keywords", {}).items():
            for kw in keywords:
                if _contains_keyword(masked, kw):
                    matched.add(allergen_id)
                    found = True
                    break
            if found:
                break
    return sorted(matched)
