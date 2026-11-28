"""Deterministic ingredient list parser and strict span-free round-trip AST verifier."""

from __future__ import annotations

import copy
import re
from typing import Any

from opf.ingredients_lexicon import (
    ALLOWED_STRUCTURAL_CHARS,
    CLOSE_BRACKETS,
    COLON_CHARS,
    DEFAULT_DELIMITERS,
    FUNCTIONAL_CLASS_TERMS,
    HAN_PREFIX_SAFE_HEADS,
    HEADER_PREFIX_RE,
    INLINE_QUALIFIER_RE,
    KR_ORIGIN_HEAD_RE,
    OPEN_TO_CLOSE,
    QUALIFIER_ONLY_RE,
    SPAN_KEYS,
    STRUCTURAL_CONNECTOR_RE,
)
from opf.registries import (
    ATOMIC_ADDITIVE_CODE_RE,
    get_profile,
    lookup_additive_ins,
    match_allergens_in_name,
)

__all__ = [
    "FUNCTIONAL_CLASS_TERMS",
    "SPAN_KEYS",
    "annotate_ingredients_spans",
    "parse_ingredients_semantic",
    "parse_ingredients_text",
    "strip_ingredient_spans",
    "verify_ingredients_round_trip",
]


def _strip_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


_TRAILING_PERMISSION_CLAUSE_RE = re.compile(
    r"\s+(?:sebagai\s+kondisioner\s+makanan\s+yang\s+dibenarkan|as\s+permitted\s+food\s+conditioners?|yang\s+dibenarkan)$",
    re.IGNORECASE,
)
_LEADING_CONTAINS_WORD_RE = re.compile(
    r"^(?P<kw>mengandungi|contains|including|termasuk)\s+",
    re.IGNORECASE,
)
_CONJUNCTION_TOKEN_RE = re.compile(r"\s+(?:dan|and)\s+", re.IGNORECASE)


def _strip_permission_tail(s: str) -> str:
    m = _TRAILING_PERMISSION_CLAUSE_RE.search(s)
    return s[: m.start()].strip() if m else s.strip()


def _split_top_level(
    text: str, start: int, end: int, delimiters: set[str]
) -> list[tuple[int, int]]:
    """Split text[start:end] by delimiters at bracket depth 0, plus 'dan'/'and' before additive classes."""
    raw_segments: list[tuple[int, int]] = []
    depth = 0
    seg_start = start
    for i in range(start, end):
        ch = text[i]
        if ch in OPEN_TO_CLOSE:
            depth += 1
        elif ch in CLOSE_BRACKETS:
            depth = max(0, depth - 1)
        elif depth == 0 and ch in delimiters:
            s, e = _strip_span(text, seg_start, i)
            if s < e:
                raw_segments.append((s, e))
            seg_start = i + 1
    s, e = _strip_span(text, seg_start, end)
    if s < e:
        raw_segments.append((s, e))

    refined: list[tuple[int, int]] = []
    for seg_s, seg_e in raw_segments:
        cur_s = seg_s
        for m in _CONJUNCTION_TOKEN_RE.finditer(text, seg_s, seg_e):
            if m.start() <= cur_s:
                continue
            d_check = 0
            for k in range(cur_s, m.start()):
                if text[k] in OPEN_TO_CLOSE:
                    d_check += 1
                elif text[k] in CLOSE_BRACKETS:
                    d_check = max(0, d_check - 1)
            if d_check != 0:
                continue
            rhs_raw = _strip_permission_tail(text[m.end() : seg_e].rstrip("。. "))
            rhs_head = rhs_raw
            for idx, ch in enumerate(rhs_raw):
                if ch in OPEN_TO_CLOSE:
                    rhs_head = rhs_raw[:idx].strip()
                    break
            if rhs_head and (
                _is_functional_class_name(rhs_head) or lookup_additive_ins(rhs_head) is not None
            ):
                ls, le = _strip_span(text, cur_s, m.start())
                if ls < le:
                    refined.append((ls, le))
                cur_s = m.end()
        rs, re_end = _strip_span(text, cur_s, seg_e)
        if rs < re_end:
            refined.append((rs, re_end))
    return refined


def _find_slash_outside_brackets(text: str, start: int, end: int, slashes: set[str]) -> int | None:
    depth = 0
    for i in range(start, end):
        ch = text[i]
        if ch in OPEN_TO_CLOSE:
            depth += 1
        elif ch in CLOSE_BRACKETS:
            depth = max(0, depth - 1)
        elif depth == 0 and ch in slashes:
            return i
    return None


def _is_functional_class_name(name: str) -> bool:
    low = name.strip().lower()
    return low in FUNCTIONAL_CLASS_TERMS or ("添加剂" in low) or ("添加劑" in low)


def _can_strip_han_prefix(rest: str) -> bool:
    """Return True only when text after '含'/'内含' is a known additive or functional term (avoids '含水柠檬酸'/'含气水')."""
    if not rest:
        return False
    if lookup_additive_ins(rest) is not None:
        return True
    head = rest
    for idx, ch in enumerate(rest):
        if ch in OPEN_TO_CLOSE:
            head = rest[:idx].strip()
            break
    m_in = INLINE_QUALIFIER_RE.match(head)
    if m_in:
        head = m_in.group("head").strip()
    return bool(
        head
        and (
            lookup_additive_ins(head) is not None
            or _is_functional_class_name(head)
            or head in HAN_PREFIX_SAFE_HEADS
        )
    )


def _merge_qualifier(
    cur_qual: str | None,
    cur_span: list[int] | None,
    new_qual: str,
    new_span: list[int],
) -> tuple[str, list[int]]:
    if cur_qual is None or cur_span is None:
        return new_qual, new_span
    sep = "；" if any("\u4e00" <= ch <= "\u9fff" for ch in (cur_qual + new_qual)) else "; "
    return f"{cur_qual}{sep}{new_qual}", [cur_span[0], new_span[1]]


def _parse_segment(
    text: str,
    seg_start: int,
    seg_end: int,
    delimiters: set[str],
    force_additive: bool = False,
) -> dict[str, Any]:
    """Parse a single ingredient segment text[seg_start:seg_end] into an IngredientNode."""
    while seg_end > seg_start and text[seg_end - 1] in {"。", "."}:
        seg_end -= 1
    seg_start, seg_end = _strip_span(text, seg_start, seg_end)
    m_perm = _TRAILING_PERMISSION_CLAUSE_RE.search(text[seg_start:seg_end])
    if m_perm and m_perm.start() > 0:
        cand_s, cand_e = _strip_span(text, seg_start, seg_start + m_perm.start())
        if cand_s < cand_e:
            seg_start, seg_end = cand_s, cand_e

    func_class: str | None = None
    func_span: list[int] | None = None
    depth = 0
    for i in range(seg_start, seg_end):
        ch = text[i]
        if ch in OPEN_TO_CLOSE:
            depth += 1
        elif ch in CLOSE_BRACKETS:
            depth = max(0, depth - 1)
        elif depth == 0 and ch in COLON_CHARS:
            fc_s, fc_e = _strip_span(text, seg_start, i)
            if fc_s < fc_e:
                cand_fc = text[fc_s:fc_e]
                rest_s, rest_e = _strip_span(text, i + 1, seg_end)
                rhs = text[rest_s:rest_e]
                rhs_head = rhs
                for k, rch in enumerate(rhs):
                    if rch in OPEN_TO_CLOSE or rch.isspace():
                        rhs_head = rhs[:k]
                        break
                if not _is_functional_class_name(cand_fc) and KR_ORIGIN_HEAD_RE.match(rhs_head):
                    break
                func_class = cand_fc
                func_span = [fc_s, fc_e]
                seg_start, seg_end = rest_s, rest_e
            break

    if func_class is None and text[seg_start:seg_end].startswith("其中") and (seg_end - seg_start) > 2:
        fc_s = seg_start
        fc_e = seg_start + 2
        rest_s, rest_e = _strip_span(text, fc_e, seg_end)
        if rest_s < rest_e:
            func_class = text[fc_s:fc_e]
            func_span = [fc_s, fc_e]
            seg_start, seg_end = rest_s, rest_e
    elif func_class is None:
        seg_slice = text[seg_start:seg_end]
        m_lead = _LEADING_CONTAINS_WORD_RE.match(seg_slice)
        if m_lead:
            fc_s = seg_start
            fc_e = seg_start + len(m_lead.group("kw"))
            rest_s, rest_e = _strip_span(text, seg_start + m_lead.end(), seg_end)
            if rest_s < rest_e:
                func_class = text[fc_s:fc_e]
                func_span = [fc_s, fc_e]
                seg_start, seg_end = rest_s, rest_e
        else:
            for han_pfx in ("内含", "含"):
                if seg_slice.startswith(han_pfx) and len(seg_slice) > len(han_pfx):
                    fc_s = seg_start
                    fc_e = seg_start + len(han_pfx)
                    rest_s, rest_e = _strip_span(text, fc_e, seg_end)
                    if rest_s < rest_e and (
                        text[fc_e].isspace() or _can_strip_han_prefix(text[rest_s:rest_e])
                    ):
                        func_class = text[fc_s:fc_e]
                        func_span = [fc_s, fc_e]
                        seg_start, seg_end = rest_s, rest_e
                    break

    seg_body = text[seg_start:seg_end]
    whole_seg_ins = lookup_additive_ins(seg_body)
    is_atomic_code = bool(whole_seg_ins or ATOMIC_ADDITIVE_CODE_RE.match(seg_body))
    paren_groups: list[tuple[int, int, int, int]] = []
    depth = 0
    open_idx = -1
    head_end: int | None = None
    if not is_atomic_code:
        for i in range(seg_start, seg_end):
            ch = text[i]
            if ch in OPEN_TO_CLOSE:
                if depth == 0:
                    open_idx = i
                    if head_end is None:
                        head_end = i
                depth += 1
            elif ch in CLOSE_BRACKETS:
                if depth > 0:
                    depth -= 1
                    if depth == 0 and open_idx != -1:
                        in_s, in_e = _strip_span(text, open_idx + 1, i)
                        paren_groups.append((open_idx, in_s, in_e, i))
                        open_idx = -1

    if head_end is None:
        head_end = seg_end

    name_s, name_e = _strip_span(text, seg_start, head_end)
    raw_head = text[name_s:name_e]

    qualifier: str | None = None
    qualifier_span: list[int] | None = None

    m_inline = INLINE_QUALIFIER_RE.match(raw_head)
    if m_inline:
        head_part = m_inline.group("head")
        qual_part = m_inline.group("qual")
        q_start = name_s + m_inline.start("qual")
        q_end = name_s + m_inline.end("qual")
        name_e = name_s + len(head_part.rstrip())
        qualifier = qual_part
        qualifier_span = [q_start, q_end]

    head_name = text[name_s:name_e]
    is_head_func_class = _is_functional_class_name(head_name) or (
        func_class is not None and _is_functional_class_name(func_class)
    )

    children: list[dict[str, Any]] = []
    for _open_i, in_s, in_e, _close_i in paren_groups:
        inner_str = text[in_s:in_e]
        if QUALIFIER_ONLY_RE.match(inner_str):
            qualifier, qualifier_span = _merge_qualifier(
                qualifier, qualifier_span, inner_str, [in_s, in_e]
            )
        else:
            ins_match = lookup_additive_ins(inner_str)
            is_inner_atomic = bool(ins_match or ATOMIC_ADDITIVE_CODE_RE.match(inner_str))
            if is_inner_atomic and len(_split_top_level(text, in_s, in_e, delimiters)) == 1:
                child_node = _parse_segment(text, in_s, in_e, delimiters, force_additive=True)
                children.append(child_node)
            else:
                sub_segs = _split_top_level(text, in_s, in_e, delimiters)
                is_sub_additive = force_additive or is_head_func_class
                for sub_s, sub_e in sub_segs:
                    children.append(
                        _parse_segment(text, sub_s, sub_e, delimiters, force_additive=is_sub_additive)
                    )

    if paren_groups:
        last_close = paren_groups[-1][3]
        tail_s, tail_e = _strip_span(text, last_close + 1, seg_end)
        if tail_s < tail_e:
            tail_str = text[tail_s:tail_e]
            if QUALIFIER_ONLY_RE.match(tail_str):
                qualifier, qualifier_span = _merge_qualifier(
                    qualifier, qualifier_span, tail_str, [tail_s, tail_e]
                )

    node_name = text[name_s:name_e]
    node: dict[str, Any] = {
        "name": node_name,
        "span": [name_s, name_e],
    }
    if func_class is not None and func_span is not None:
        node["functional_class"] = func_class
        node["functional_class_span"] = func_span
    if qualifier is not None and qualifier_span is not None:
        node["qualifier"] = qualifier
        node["qualifier_span"] = qualifier_span

    ins_code = lookup_additive_ins(node_name)
    if ins_code:
        node["ins"] = ins_code
        node["is_additive"] = True
    elif force_additive or is_head_func_class or is_atomic_code:
        node["is_additive"] = True

    allergens = match_allergens_in_name(node_name)
    if allergens:
        node["allergens"] = allergens

    if children:
        node["children"] = children

    return node


def strip_ingredient_spans(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a deep copy of ingredient nodes without character-offset span keys."""
    cleaned: list[dict[str, Any]] = []
    for node in nodes:
        out = {k: copy.deepcopy(v) for k, v in node.items() if k not in SPAN_KEYS}
        if "children" in out and isinstance(out["children"], list):
            out["children"] = strip_ingredient_spans(out["children"])
        cleaned.append(out)
    return cleaned


def parse_ingredients_text(
    raw_text: str,
    lang: str = "zh-Hans",
    profile_id: str = "CN/GB28050-2011",
) -> list[dict[str, Any]]:
    """Deterministically parse raw ingredients text into a list of spanned IngredientNode dicts."""
    profile = get_profile(profile_id)
    grammar = profile.get("ingredients_grammar", {})
    prefixes: list[str] = grammar.get("prefixes", [])
    delimiters = set(grammar.get("top_level_delimiters", DEFAULT_DELIMITERS))
    slashes = set(grammar.get("additive_slash_split") or [])

    start = 0
    end = len(raw_text)
    start, end = _strip_span(raw_text, start, end)

    lowered_rest = raw_text[start:end].lower()
    matched_prefix = False
    for prefix in sorted(prefixes, key=len, reverse=True):
        if raw_text[start:end].startswith(prefix) or lowered_rest.startswith(prefix.lower()):
            start += len(prefix)
            start, end = _strip_span(raw_text, start, end)
            matched_prefix = True
            break
    if not matched_prefix:
        m_hdr = HEADER_PREFIX_RE.match(raw_text[start:end])
        if m_hdr:
            start += m_hdr.end()
            start, end = _strip_span(raw_text, start, end)

    while end > start and raw_text[end - 1] in {"。", "."}:
        end -= 1
    start, end = _strip_span(raw_text, start, end)

    nodes: list[dict[str, Any]] = []
    if slashes:
        slash_idx = _find_slash_outside_brackets(raw_text, start, end, slashes)
        if slash_idx is not None:
            before_segs = _split_top_level(raw_text, start, slash_idx, delimiters)
            after_segs = _split_top_level(raw_text, slash_idx + 1, end, delimiters)
            for s, e in before_segs:
                nodes.append(_parse_segment(raw_text, s, e, delimiters, force_additive=False))
            for s, e in after_segs:
                nodes.append(_parse_segment(raw_text, s, e, delimiters, force_additive=True))
            return nodes

    for s, e in _split_top_level(raw_text, start, end, delimiters):
        nodes.append(_parse_segment(raw_text, s, e, delimiters, force_additive=False))
    return nodes


def parse_ingredients_semantic(
    text: str,
    lang: str = "zh-Hans",
    profile_id: str = "CN/GB28050-2011",
) -> list[dict[str, Any]]:
    """Parse raw ingredients text into span-free v0.3 SemanticIngredientNode dictionaries."""
    return strip_ingredient_spans(parse_ingredients_text(text, lang=lang, profile_id=profile_id))


def _context_snippet(text: str, pos: int, radius: int = 12) -> str:
    s = max(0, pos - radius)
    e = min(len(text), pos + radius)
    return f"...{text[s:pos]}👉{text[pos:e]}..."


def _build_allowed_structural_chars(profile: dict[str, Any]) -> set[str]:
    grammar = profile.get("ingredients_grammar", {})
    allowed = set(ALLOWED_STRUCTURAL_CHARS)
    for key in (
        "top_level_delimiters",
        "open_brackets",
        "close_brackets",
        "trailing_punctuation",
        "additive_slash_split",
    ):
        for item in grammar.get(key) or []:
            allowed.update(str(item))
    return allowed


def _skip_header_prefix(raw_text: str, prefixes: list[str]) -> int:
    pos = 0
    n_chars = len(raw_text)
    while pos < n_chars and raw_text[pos].isspace():
        pos += 1
    lowered_rest = raw_text[pos:].lower()
    for prefix in sorted(prefixes, key=len, reverse=True):
        if raw_text.startswith(prefix, pos) or lowered_rest.startswith(prefix.lower()):
            return pos + len(prefix)
    m = HEADER_PREFIX_RE.match(raw_text[pos:])
    if m:
        return pos + m.end()
    return pos


def _check_balanced_brackets(raw_text: str) -> list[str]:
    errors: list[str] = []
    stack: list[tuple[str, int]] = []
    for idx, ch in enumerate(raw_text):
        if ch in OPEN_TO_CLOSE:
            stack.append((OPEN_TO_CLOSE[ch], idx))
        elif ch in CLOSE_BRACKETS:
            if not stack or stack[-1][0] != ch:
                errors.append(
                    f"Unbalanced closing bracket {ch!r} at index {idx} ({_context_snippet(raw_text, idx)}) in ingredients_text"
                )
                break
            stack.pop()
    if stack:
        errors.append(
            f"Unclosed bracket at index {stack[-1][1]} ({_context_snippet(raw_text, stack[-1][1])}) in ingredients_text"
        )
    return errors


def _align_semantic_tree(
    raw_text: str,
    nodes: list[dict[str, Any]],
    profile_id: str = "CN/GB28050-2011",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Monotonically align a span-free (or spanned) ingredient AST against raw_text left-to-right."""
    errors: list[str] = []
    if not isinstance(raw_text, str) or not raw_text.strip():
        return [], ["ingredients_text raw text cannot be empty"]
    if not isinstance(nodes, list) or not nodes:
        return [], ["ingredients_tree nodes list cannot be empty"]

    profile = get_profile(profile_id)
    grammar = profile.get("ingredients_grammar", {})
    prefixes: list[str] = grammar.get("prefixes", [])
    allowed_chars = _build_allowed_structural_chars(profile)

    n_chars = len(raw_text)
    cursor = _skip_header_prefix(raw_text, prefixes)

    def _skip_chars(pos: int) -> int:
        while pos < n_chars and raw_text[pos] in allowed_chars:
            pos += 1
        return pos

    def _skip_structural(pos: int) -> int:
        while pos < n_chars:
            if raw_text[pos] in allowed_chars:
                pos += 1
                continue
            if pos == 0 or raw_text[pos - 1] in allowed_chars:
                m_conn = STRUCTURAL_CONNECTOR_RE.match(raw_text, pos)
                if m_conn:
                    end_pos = m_conn.end()
                    if end_pos == n_chars or raw_text[end_pos] in allowed_chars:
                        pos = end_pos
                        continue
            break
        return pos

    def _match_token(expected: Any, label: str, explicit_span: Any = None) -> list[int] | None:
        nonlocal cursor
        if not isinstance(expected, str) or not expected:
            errors.append(f"Invalid empty token for {label}")
            return None
        cursor = _skip_chars(cursor)
        if not raw_text.startswith(expected, cursor):
            cursor = _skip_structural(cursor)
        if raw_text.startswith(expected, cursor):
            span = [cursor, cursor + len(expected)]
            if explicit_span is not None and explicit_span != span:
                errors.append(
                    f"Explicit span {explicit_span!r} for {label} disagrees with monotonic span {span!r}"
                )
                return None
            cursor += len(expected)
            return span

        later = raw_text.find(expected, cursor)
        if later != -1:
            bad_runs: list[str] = []
            i = _skip_structural(cursor)
            while i < later:
                j = i + 1
                while j < later and raw_text[j] not in allowed_chars:
                    j += 1
                bad_runs.append(f"{raw_text[i:j]!r} at [{i}:{j}]")
                i = _skip_structural(j)
            if bad_runs:
                errors.append(
                    "Ingredient round-trip check failed: uncaptured text in ingredients_text: "
                    + ", ".join(bad_runs)
                    + f" ({_context_snippet(raw_text, cursor)})"
                )
            else:
                errors.append(
                    f"Ingredient round-trip alignment error before {label} at index {cursor} "
                    f"({_context_snippet(raw_text, cursor)})"
                )
        else:
            errors.append(
                f"Ingredient round-trip mismatch for {label} at index {cursor}: "
                f"expected {expected!r}, found {raw_text[cursor:cursor + len(expected)]!r} "
                f"({_context_snippet(raw_text, cursor)})"
            )
        return None

    def _qualifier_starts_at(qual_val: Any, pos: int) -> bool:
        if not isinstance(qual_val, str) or not qual_val:
            return False
        if raw_text.startswith(qual_val, pos):
            return True
        if "；" in qual_val or ";" in qual_val:
            parts = [p.strip() for p in re.split(r"[；;]", qual_val) if p.strip()]
            if len(parts) >= 2 and raw_text.startswith(parts[0], pos):
                return True
        return False

    def _match_qualifier(qual_val: Any, explicit_span: Any = None) -> list[int] | None:
        nonlocal cursor
        if not isinstance(qual_val, str) or not qual_val:
            errors.append(f"Invalid empty token for qualifier({qual_val})")
            return None
        peek = _skip_structural(cursor)
        if raw_text.startswith(qual_val, peek):
            return _match_token(qual_val, f"qualifier({qual_val})", explicit_span=explicit_span)
        if "；" in qual_val or ";" in qual_val:
            parts = [p.strip() for p in re.split(r"[；;]", qual_val) if p.strip()]
            if len(parts) >= 2:
                first_span: list[int] | None = None
                last_span: list[int] | None = None
                for idx, part in enumerate(parts):
                    sp = _match_token(part, f"qualifier_part[{idx}]({part})", explicit_span=None)
                    if sp is None:
                        return None
                    if first_span is None:
                        first_span = sp
                    last_span = sp
                assert first_span is not None and last_span is not None
                combined = [first_span[0], last_span[1]]
                if explicit_span is not None and explicit_span != combined:
                    errors.append(
                        f"Explicit span {explicit_span!r} for qualifier({qual_val}) disagrees with monotonic span {combined!r}"
                    )
                    return None
                return combined
        return _match_token(qual_val, f"qualifier({qual_val})", explicit_span=explicit_span)

    def _walk(node: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(node, dict):
            errors.append(f"Ingredient node must be an object, got {type(node).__name__}")
            return None

        out = {k: copy.deepcopy(v) for k, v in node.items() if k not in SPAN_KEYS}

        if "functional_class" in node:
            fc_span = _match_token(
                node["functional_class"],
                f"functional_class({node['functional_class']})",
                explicit_span=node.get("functional_class_span"),
            )
            if fc_span is None:
                return None
            out["functional_class_span"] = fc_span

        name = node.get("name")
        name_span = _match_token(
            name,
            f"ingredient({name})",
            explicit_span=node.get("span"),
        )
        if name_span is None:
            return None
        out["span"] = name_span

        children = node.get("children") or []
        has_qual = "qualifier" in node and node["qualifier"] is not None

        if has_qual and children:
            peek = _skip_structural(cursor)
            if _qualifier_starts_at(node["qualifier"], peek):
                q_span = _match_qualifier(
                    node["qualifier"],
                    explicit_span=node.get("qualifier_span"),
                )
                if q_span is None:
                    return None
                out["qualifier_span"] = q_span
                annotated_children: list[dict[str, Any]] = []
                for child in children:
                    c_out = _walk(child)
                    if c_out is None:
                        return None
                    annotated_children.append(c_out)
                out["children"] = annotated_children
            else:
                annotated_children = []
                for child in children:
                    c_out = _walk(child)
                    if c_out is None:
                        return None
                    annotated_children.append(c_out)
                out["children"] = annotated_children
                q_span = _match_qualifier(
                    node["qualifier"],
                    explicit_span=node.get("qualifier_span"),
                )
                if q_span is None:
                    return None
                out["qualifier_span"] = q_span
        else:
            if children:
                annotated_children = []
                for child in children:
                    c_out = _walk(child)
                    if c_out is None:
                        return None
                    annotated_children.append(c_out)
                out["children"] = annotated_children
            if has_qual:
                q_span = _match_qualifier(
                    node["qualifier"],
                    explicit_span=node.get("qualifier_span"),
                )
                if q_span is None:
                    return None
                out["qualifier_span"] = q_span

        return out

    annotated: list[dict[str, Any]] = []
    for top_node in nodes:
        res = _walk(top_node)
        if res is None:
            break
        annotated.append(res)

    if not errors:
        uncaptured_ranges: list[tuple[int, int, str]] = []
        i = _skip_structural(cursor)
        while i < n_chars:
            j = i + 1
            while j < n_chars and raw_text[j] not in allowed_chars:
                j += 1
            uncaptured_ranges.append((i, j, raw_text[i:j]))
            i = _skip_structural(j)
        if uncaptured_ranges:
            formatted = ", ".join(
                f"{sub!r} at [{s}:{e}] ({_context_snippet(raw_text, s)})"
                for s, e, sub in uncaptured_ranges
            )
            errors.append(
                f"Ingredient round-trip check failed: uncaptured text in ingredients_text: {formatted}"
            )

    errors.extend(_check_balanced_brackets(raw_text))
    return annotated, errors


def verify_ingredients_round_trip(
    raw_text: str,
    nodes: list[dict[str, Any]],
    profile_id: str = "CN/GB28050-2011",
) -> list[str]:
    """Verify that a semantic (or spanned) ingredients_tree losslessly and monotonically maps to raw_text."""
    _annotated, errors = _align_semantic_tree(raw_text, nodes, profile_id=profile_id)
    return errors


def annotate_ingredients_spans(
    raw_text: str,
    nodes: list[dict[str, Any]],
    profile_id: str = "CN/GB28050-2011",
) -> list[dict[str, Any]]:
    """Compute and attach [start, end] spans onto a semantic ingredient AST for .full.json build output."""
    annotated, errors = _align_semantic_tree(raw_text, nodes, profile_id=profile_id)
    if errors:
        raise ValueError("; ".join(errors))
    return annotated
