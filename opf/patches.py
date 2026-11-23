"""RFC 6901 JSON Pointer, RFC 6902 JSON Patch, deterministic minimal inverse, and @rev replay."""

from __future__ import annotations

import copy
import re
from typing import Any

PATCHABLE_KEYS: tuple[str, ...] = ("core", "attributes", "track", "supersedes", "lifecycle")
_LIST_INDEX_RE = re.compile(r"^(0|[1-9][0-9]*)$")


class PatchError(ValueError):
    """Raised when a JSON Pointer or RFC 6902 patch operation is invalid or fails."""


def _json_equal(a: Any, b: Any) -> bool:
    """Exact JSON equality distinguishing bool from int (True != 1, False != 0)."""
    if type(a) is bool or type(b) is bool:
        return type(a) is type(b) and a is b
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return False
        return all(_json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def extract_patchable_surface(edition_doc: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of the patchable content projection {core, attributes, track, supersedes, lifecycle}."""
    return {k: copy.deepcopy(edition_doc[k]) for k in PATCHABLE_KEYS if k in edition_doc}


def escape_pointer_token(token: str) -> str:
    """Escape a reference token per RFC 6901 (~ -> ~0, / -> ~1)."""
    return token.replace("~", "~0").replace("/", "~1")


def unescape_pointer_token(token: str) -> str:
    """Unescape an RFC 6901 reference token, rejecting malformed tilde escapes."""
    out: list[str] = []
    i = 0
    n = len(token)
    while i < n:
        ch = token[i]
        if ch == "~":
            if i + 1 >= n or token[i + 1] not in ("0", "1"):
                raise PatchError(f"Invalid RFC 6901 escape sequence in token {token!r}")
            out.append("~" if token[i + 1] == "0" else "/")
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_json_pointer(pointer: str) -> list[str]:
    """Parse an RFC 6901 JSON Pointer string into unescaped reference tokens."""
    if not isinstance(pointer, str):
        raise PatchError(f"JSON Pointer must be a string, got {type(pointer).__name__}")
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise PatchError(f"JSON Pointer must start with '/' or be empty, got {pointer!r}")
    return [unescape_pointer_token(part) for part in pointer[1:].split("/")]


def format_json_pointer(tokens: list[str]) -> str:
    """Serialize reference tokens into an RFC 6901 JSON Pointer string."""
    if not tokens:
        return ""
    return "".join("/" + escape_pointer_token(t) for t in tokens)


def _parse_list_index(
    token: str,
    length: int,
    *,
    allow_dash: bool = False,
    allow_end: bool = False,
) -> int:
    if token == "-":
        if allow_dash:
            return length
        raise PatchError("JSON Pointer '-' is not allowed for this operation")
    if not _LIST_INDEX_RE.match(token):
        raise PatchError(f"Invalid JSON array index {token!r}")
    idx = int(token)
    max_idx = length if allow_end else length - 1
    if idx < 0 or idx > max_idx:
        raise PatchError(f"Array index {idx} out of bounds for array of length {length}")
    return idx


def _resolve_parent(root: Any, tokens: list[str], full_pointer: str) -> tuple[Any, str]:
    if not tokens:
        raise PatchError("Operation cannot target empty root pointer in this context")
    cur = root
    for token in tokens[:-1]:
        if isinstance(cur, dict):
            if token not in cur:
                raise PatchError(f"Missing intermediate key {token!r} for pointer {full_pointer!r}")
            cur = cur[token]
        elif isinstance(cur, list):
            idx = _parse_list_index(token, len(cur), allow_dash=False, allow_end=False)
            cur = cur[idx]
        else:
            raise PatchError(
                f"Cannot traverse non-container type {type(cur).__name__} at {full_pointer!r}"
            )
    if not isinstance(cur, (dict, list)):
        raise PatchError(
            f"Parent at {full_pointer!r} must be dict or list, got {type(cur).__name__}"
        )
    return cur, tokens[-1]


def _get_at_pointer(root: Any, pointer: str) -> Any:
    tokens = parse_json_pointer(pointer)
    cur = root
    for token in tokens:
        if isinstance(cur, dict):
            if token not in cur:
                raise PatchError(f"Key {token!r} not found at pointer {pointer!r}")
            cur = cur[token]
        elif isinstance(cur, list):
            idx = _parse_list_index(token, len(cur), allow_dash=False, allow_end=False)
            cur = cur[idx]
        else:
            raise PatchError(
                f"Cannot traverse non-container type {type(cur).__name__} at {pointer!r}"
            )
    return cur


def _add_at_pointer(root: Any, pointer: str, value: Any) -> Any:
    tokens = parse_json_pointer(pointer)
    if not tokens:
        return copy.deepcopy(value)
    parent, last = _resolve_parent(root, tokens, pointer)
    val = copy.deepcopy(value)
    if isinstance(parent, dict):
        parent[last] = val
    else:
        idx = _parse_list_index(last, len(parent), allow_dash=True, allow_end=True)
        parent.insert(idx, val)
    return root


def _replace_at_pointer(root: Any, pointer: str, value: Any) -> Any:
    tokens = parse_json_pointer(pointer)
    if not tokens:
        return copy.deepcopy(value)
    parent, last = _resolve_parent(root, tokens, pointer)
    val = copy.deepcopy(value)
    if isinstance(parent, dict):
        if last not in parent:
            raise PatchError(f"Cannot replace non-existent key {last!r} at {pointer!r}")
        parent[last] = val
    else:
        idx = _parse_list_index(last, len(parent), allow_dash=False, allow_end=False)
        parent[idx] = val
    return root


def _remove_at_pointer(root: Any, pointer: str) -> tuple[Any, Any]:
    tokens = parse_json_pointer(pointer)
    if not tokens:
        raise PatchError("Cannot remove root document")
    parent, last = _resolve_parent(root, tokens, pointer)
    if isinstance(parent, dict):
        if last not in parent:
            raise PatchError(f"Cannot remove non-existent key {last!r} at {pointer!r}")
        removed = parent.pop(last)
    else:
        idx = _parse_list_index(last, len(parent), allow_dash=False, allow_end=False)
        removed = parent.pop(idx)
    return root, removed


def _validate_move_paths(from_pointer: str, dest_pointer: str) -> None:
    from_tokens = parse_json_pointer(from_pointer)
    dest_tokens = parse_json_pointer(dest_pointer)
    if len(from_tokens) < len(dest_tokens) and dest_tokens[: len(from_tokens)] == from_tokens:
        raise PatchError(
            f"Invalid move: 'from' ({from_pointer!r}) cannot be a proper prefix of 'path' ({dest_pointer!r})"
        )


def apply_patch(doc: Any, ops: list[dict[str, Any]], in_place: bool = False) -> Any:
    """Apply an RFC 6902 JSON Patch operation list to doc and return the resulting value."""
    if not isinstance(ops, list):
        raise PatchError(f"Patch ops must be a list, got {type(ops).__name__}")
    state = doc if in_place else copy.deepcopy(doc)

    for idx, op_obj in enumerate(ops):
        if not isinstance(op_obj, dict):
            raise PatchError(f"Patch op[{idx}] must be an object, got {type(op_obj).__name__}")
        op = op_obj.get("op")
        path = op_obj.get("path")
        if not isinstance(path, str):
            raise PatchError(f"Patch op[{idx}] missing string 'path'")

        if op == "add":
            if "value" not in op_obj:
                raise PatchError(f"Patch op[{idx}] ('add') missing 'value'")
            state = _add_at_pointer(state, path, op_obj["value"])
        elif op == "replace":
            if "value" not in op_obj:
                raise PatchError(f"Patch op[{idx}] ('replace') missing 'value'")
            state = _replace_at_pointer(state, path, op_obj["value"])
        elif op == "remove":
            state, _removed = _remove_at_pointer(state, path)
        elif op == "move":
            from_path = op_obj.get("from")
            if not isinstance(from_path, str):
                raise PatchError(f"Patch op[{idx}] ('move') missing string 'from'")
            _validate_move_paths(from_path, path)
            if from_path == path:
                _get_at_pointer(state, from_path)
            else:
                state, moved_val = _remove_at_pointer(state, from_path)
                state = _add_at_pointer(state, path, moved_val)
        elif op == "copy":
            from_path = op_obj.get("from")
            if not isinstance(from_path, str):
                raise PatchError(f"Patch op[{idx}] ('copy') missing string 'from'")
            copied_val = copy.deepcopy(_get_at_pointer(state, from_path))
            state = _add_at_pointer(state, path, copied_val)
        elif op == "test":
            if "value" not in op_obj:
                raise PatchError(f"Patch op[{idx}] ('test') missing 'value'")
            actual = _get_at_pointer(state, path)
            if not _json_equal(actual, op_obj["value"]):
                raise PatchError(
                    f"Patch op[{idx}] ('test') failed at {path!r}: expected {op_obj['value']!r}, got {actual!r}"
                )
        else:
            raise PatchError(f"Unsupported RFC 6902 op {op!r} at op[{idx}]")
    return state


def _inverse_for_add(state: Any, path: str) -> list[dict[str, Any]]:
    tokens = parse_json_pointer(path)
    if not tokens:
        return [{"op": "replace", "path": "", "value": copy.deepcopy(state)}]
    parent, last = _resolve_parent(state, tokens, path)
    if isinstance(parent, dict):
        if last in parent:
            return [{"op": "replace", "path": path, "value": copy.deepcopy(parent[last])}]
        return [{"op": "remove", "path": path}]
    idx = _parse_list_index(last, len(parent), allow_dash=True, allow_end=True)
    concrete_path = format_json_pointer(tokens[:-1] + [str(idx)])
    return [{"op": "remove", "path": concrete_path}]


def invert_patch(state_before: dict[str, Any], forward_ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministically generate the exact minimal inverse RFC 6902 patch for forward_ops on state_before."""
    if not isinstance(forward_ops, list):
        raise PatchError(f"Patch ops must be a list, got {type(forward_ops).__name__}")
    state = copy.deepcopy(state_before)
    step_inverses: list[list[dict[str, Any]]] = []

    for idx, op_obj in enumerate(forward_ops):
        if not isinstance(op_obj, dict):
            raise PatchError(f"Patch op[{idx}] must be an object")
        op = op_obj.get("op")
        path = op_obj.get("path")
        if not isinstance(path, str):
            raise PatchError(f"Patch op[{idx}] missing string 'path'")

        if op == "add":
            if "value" not in op_obj:
                raise PatchError(f"Patch op[{idx}] ('add') missing 'value'")
            inv = _inverse_for_add(state, path)
            state = _add_at_pointer(state, path, op_obj["value"])
        elif op == "replace":
            if "value" not in op_obj:
                raise PatchError(f"Patch op[{idx}] ('replace') missing 'value'")
            old_val = copy.deepcopy(_get_at_pointer(state, path))
            inv = [{"op": "replace", "path": path, "value": old_val}]
            state = _replace_at_pointer(state, path, op_obj["value"])
        elif op == "remove":
            old_val = copy.deepcopy(_get_at_pointer(state, path))
            inv = [{"op": "add", "path": path, "value": old_val}]
            state, _ = _remove_at_pointer(state, path)
        elif op == "copy":
            from_path = op_obj.get("from")
            if not isinstance(from_path, str):
                raise PatchError(f"Patch op[{idx}] ('copy') missing string 'from'")
            copied_val = copy.deepcopy(_get_at_pointer(state, from_path))
            inv = _inverse_for_add(state, path)
            state = _add_at_pointer(state, path, copied_val)
        elif op == "move":
            from_path = op_obj.get("from")
            if not isinstance(from_path, str):
                raise PatchError(f"Patch op[{idx}] ('move') missing string 'from'")
            _validate_move_paths(from_path, path)
            if from_path == path:
                _get_at_pointer(state, from_path)
                inv = []
            else:
                state, moved_val = _remove_at_pointer(state, from_path)
                dest_tokens = parse_json_pointer(path)
                if not dest_tokens:
                    raise PatchError("Cannot move onto empty root path")
                dest_parent, dest_last = _resolve_parent(state, dest_tokens, path)
                if isinstance(dest_parent, dict):
                    if dest_last in dest_parent:
                        overwritten = copy.deepcopy(dest_parent[dest_last])
                        inv = [
                            {"op": "move", "from": path, "path": from_path},
                            {"op": "add", "path": path, "value": overwritten},
                        ]
                    else:
                        inv = [{"op": "move", "from": path, "path": from_path}]
                else:
                    dest_idx = _parse_list_index(
                        dest_last, len(dest_parent), allow_dash=True, allow_end=True
                    )
                    concrete_dest = format_json_pointer(dest_tokens[:-1] + [str(dest_idx)])
                    inv = [{"op": "move", "from": concrete_dest, "path": from_path}]
                state = _add_at_pointer(state, path, moved_val)
        elif op == "test":
            if "value" not in op_obj:
                raise PatchError(f"Patch op[{idx}] ('test') missing 'value'")
            actual = _get_at_pointer(state, path)
            if not _json_equal(actual, op_obj["value"]):
                raise PatchError(
                    f"Patch op[{idx}] ('test') failed at {path!r}: expected {op_obj['value']!r}, got {actual!r}"
                )
            inv = []
        else:
            raise PatchError(f"Unsupported RFC 6902 op {op!r} at op[{idx}]")

        step_inverses.append(inv)

    return [op for inv in reversed(step_inverses) for op in inv]


def _diff_values(old_val: Any, new_val: Any, tokens: list[str], ops: list[dict[str, Any]]) -> None:
    if _json_equal(old_val, new_val):
        return

    if isinstance(old_val, dict) and isinstance(new_val, dict):
        if not tokens:
            ordered_keys = [k for k in PATCHABLE_KEYS if k in old_val or k in new_val] + sorted(
                k for k in (set(old_val.keys()) | set(new_val.keys())) if k not in PATCHABLE_KEYS
            )
        else:
            ordered_keys = sorted(set(old_val.keys()) | set(new_val.keys()))
        for key in ordered_keys:
            child_tokens = tokens + [key]
            ptr = format_json_pointer(child_tokens)
            if key not in new_val:
                ops.append({"op": "remove", "path": ptr})
            elif key not in old_val:
                ops.append({"op": "add", "path": ptr, "value": copy.deepcopy(new_val[key])})
            else:
                _diff_values(old_val[key], new_val[key], child_tokens, ops)
        return

    if isinstance(old_val, list) and isinstance(new_val, list):
        ptr = format_json_pointer(tokens)
        if len(old_val) == len(new_val):
            # Avoid partial row replacement if canonical nutrient keys changed across positions
            if ptr == "/core/nutrition_declared/rows" and any(
                not isinstance(a, dict)
                or not isinstance(b, dict)
                or (a.get("nutrient"), a.get("unit")) != (b.get("nutrient"), b.get("unit"))
                for a, b in zip(old_val, new_val)
            ):
                ops.append({"op": "replace", "path": ptr, "value": copy.deepcopy(new_val)})
                return
            for i in range(len(old_val)):
                _diff_values(old_val[i], new_val[i], tokens + [str(i)], ops)
            return
        if len(new_val) > len(old_val) and all(
            _json_equal(old_val[i], new_val[i]) for i in range(len(old_val))
        ):
            for i in range(len(old_val), len(new_val)):
                ops.append(
                    {
                        "op": "add",
                        "path": format_json_pointer(tokens + [str(i)]),
                        "value": copy.deepcopy(new_val[i]),
                    }
                )
            return
        ops.append({"op": "replace", "path": ptr, "value": copy.deepcopy(new_val)})
        return

    ops.append({"op": "replace", "path": format_json_pointer(tokens), "value": copy.deepcopy(new_val)})


def diff_to_patch(
    old_surface: dict[str, Any], new_surface: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compute canonical (patch, reverse_patch) transforming old_surface into new_surface."""
    patch: list[dict[str, Any]] = []
    _diff_values(old_surface, new_surface, [], patch)
    reverse_patch = invert_patch(old_surface, patch)
    return patch, reverse_patch


def reconstruct_surface_at_rev(edition_doc: dict[str, Any], target_rev: int) -> dict[str, Any]:
    """Reconstruct the patchable content surface at target_rev (1 <= target_rev <= doc['rev'])."""
    current_rev = edition_doc.get("rev")
    if isinstance(current_rev, bool) or not isinstance(current_rev, int) or current_rev < 1:
        raise PatchError(f"Invalid current rev on edition_doc: {current_rev!r}")
    if isinstance(target_rev, bool) or not isinstance(target_rev, int) or not (1 <= target_rev <= current_rev):
        raise PatchError(f"target_rev must be in 1..{current_rev}, got {target_rev!r}")

    surface = extract_patchable_surface(edition_doc)
    revisions = edition_doc.get("revisions")
    if not isinstance(revisions, list):
        raise PatchError("edition_doc['revisions'] must be a list")
    by_rev: dict[int, dict[str, Any]] = {}
    for entry in revisions:
        if isinstance(entry, dict) and isinstance(entry.get("rev"), int):
            by_rev[entry["rev"]] = entry

    for r in range(current_rev, target_rev, -1):
        rev_entry = by_rev.get(r)
        if rev_entry is None:
            raise PatchError(f"Missing revision entry rev={r}")
        rev_patch = rev_entry.get("reverse_patch")
        if not isinstance(rev_patch, list) or not rev_patch:
            raise PatchError(f"Revision rev={r} missing non-empty reverse_patch")
        surface = apply_patch(surface, rev_patch)

    return surface
