"""Zero-dependency Draft 2020-12 JSON Schema subset validator for OPF v0.3."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from opf.resources import get_resource_root


@lru_cache(maxsize=8)
def load_json_schema(schema_name: str = "edition.v0.3.schema.json") -> dict[str, Any]:
    path = get_resource_root() / "spec" / "schema" / schema_name
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_ref(schema: dict[str, Any], root_schema: dict[str, Any]) -> dict[str, Any]:
    cur = schema
    while "$ref" in cur:
        ref = cur["$ref"]
        if not ref.startswith("#/$defs/"):
            raise ValueError(f"Unsupported $ref: {ref}")
        def_name = ref[len("#/$defs/") :]
        target = root_schema.get("$defs", {}).get(def_name)
        if not target:
            raise ValueError(f"Unresolved $ref: {ref}")
        cur = target
    return cur


def _branch_score(
    instance: Any,
    branch_schema: dict[str, Any],
    root_schema: dict[str, Any],
    errors: list[str],
) -> tuple[int, int, int]:
    """Rank failing oneOf branches so discriminator/const mismatches sort behind closest match."""
    resolved = _resolve_ref(branch_schema, root_schema)
    const_mismatches = 0
    missing_req = 0
    if isinstance(instance, dict) and resolved.get("type") == "object":
        props = resolved.get("properties", {})
        for k, prop_s in props.items():
            resolved_p = _resolve_ref(prop_s, root_schema)
            if "const" in resolved_p and k in instance:
                c = resolved_p["const"]
                if (type(instance[k]) is bool) != (type(c) is bool) or instance[k] != c:
                    const_mismatches += 1
        for rk in resolved.get("required", []):
            if rk not in instance:
                missing_req += 1
    elif resolved.get("type") == "null" and instance is not None:
        const_mismatches += 1
    return (const_mismatches, missing_req, len(errors))


def validate_against_json_schema(
    instance: Any,
    schema: dict[str, Any],
    root_schema: dict[str, Any] | None = None,
    path: str = "$",
) -> list[str]:
    """Zero-dependency validator for OPF JSON Schemas (Draft 2020-12 subset incl. oneOf, not, if/then/else)."""
    if root_schema is None:
        root_schema = schema
    errors: list[str] = []

    if "$ref" in schema:
        target_schema = _resolve_ref(schema, root_schema)
        return validate_against_json_schema(instance, target_schema, root_schema, path)

    if "oneOf" in schema:
        branches = schema["oneOf"]
        branch_errors = [
            validate_against_json_schema(instance, branch, root_schema, path)
            for branch in branches
        ]
        matched_indices = [idx for idx, errs in enumerate(branch_errors) if not errs]
        if len(matched_indices) > 1:
            return [f"{path}: value matched {len(matched_indices)} schemas in oneOf (expected exactly 1)"]
        if len(matched_indices) == 0:
            best_idx = min(
                range(len(branches)),
                key=lambda idx: _branch_score(instance, branches[idx], root_schema, branch_errors[idx]),
            )
            return branch_errors[best_idx]

    expected_type = schema.get("type")
    if expected_type == "null":
        if instance is not None:
            return [f"{path}: expected null, got {type(instance).__name__}"]
    elif expected_type == "object":
        if not isinstance(instance, dict):
            return [f"{path}: expected object, got {type(instance).__name__}"]
        req = schema.get("required", [])
        for r_key in req:
            if r_key not in instance:
                errors.append(f"{path}: missing required property {r_key!r}")
        props = schema.get("properties", {})
        add_props = schema.get("additionalProperties", True)
        for k, v in instance.items():
            if k in props:
                errors.extend(
                    validate_against_json_schema(v, props[k], root_schema, f"{path}.{k}")
                )
            elif add_props is False:
                errors.append(f"{path}: additional property {k!r} is not allowed by schema")
            elif isinstance(add_props, dict):
                errors.extend(
                    validate_against_json_schema(v, add_props, root_schema, f"{path}.{k}")
                )
    elif expected_type == "array":
        if not isinstance(instance, list):
            return [f"{path}: expected array, got {type(instance).__name__}"]
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None and len(instance) < min_items:
            errors.append(f"{path}: array length {len(instance)} < minItems {min_items}")
        if max_items is not None and len(instance) > max_items:
            errors.append(f"{path}: array length {len(instance)} > maxItems {max_items}")
        if schema.get("uniqueItems"):
            seen_items = {
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in instance
            }
            if len(seen_items) != len(instance):
                errors.append(f"{path}: array items must be unique")
        prefix_items = schema.get("prefixItems")
        if prefix_items:
            for idx, item_schema in enumerate(prefix_items):
                if idx < len(instance):
                    errors.extend(
                        validate_against_json_schema(
                            instance[idx], item_schema, root_schema, f"{path}[{idx}]"
                        )
                    )
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for idx, item in enumerate(instance):
                errors.extend(
                    validate_against_json_schema(
                        item, items_schema, root_schema, f"{path}[{idx}]"
                    )
                )
    elif expected_type == "string":
        if not isinstance(instance, str):
            return [f"{path}: expected string, got {type(instance).__name__}"]
        min_len = schema.get("minLength")
        if min_len is not None and len(instance) < min_len:
            errors.append(f"{path}: string length {len(instance)} < minLength {min_len}")
        pattern = schema.get("pattern")
        if pattern and not re.search(pattern, instance):
            errors.append(f"{path}: value {instance!r} does not match pattern {pattern!r}")
    elif expected_type == "integer":
        if isinstance(instance, bool) or not isinstance(instance, int):
            return [f"{path}: expected integer, got {type(instance).__name__}"]
        minimum = schema.get("minimum")
        if minimum is not None and instance < minimum:
            errors.append(f"{path}: integer {instance} < minimum {minimum}")
    elif expected_type == "boolean":
        if not isinstance(instance, bool):
            return [f"{path}: expected boolean, got {type(instance).__name__}"]

    if "const" in schema:
        expected_const = schema["const"]
        if (type(instance) is bool) != (type(expected_const) is bool) or instance != expected_const:
            errors.append(f"{path}: expected const {expected_const!r}, got {instance!r}")
    if "enum" in schema:
        if not any(
            (type(instance) is bool) == (type(opt) is bool) and instance == opt
            for opt in schema["enum"]
        ):
            errors.append(f"{path}: value {instance!r} not in enum {schema['enum']}")

    for sub_schema in schema.get("allOf") or []:
        if isinstance(sub_schema, dict):
            errors.extend(
                validate_against_json_schema(instance, sub_schema, root_schema, path)
            )

    if "not" in schema and isinstance(schema["not"], dict):
        not_errs = validate_against_json_schema(instance, schema["not"], root_schema, path)
        if not not_errs:
            errors.append(f"{path}: value must not match disallowed schema ('not')")

    if "if" in schema and isinstance(schema["if"], dict):
        cond_errs = validate_against_json_schema(instance, schema["if"], root_schema, path)
        if not cond_errs:
            if isinstance(schema.get("then"), dict):
                errors.extend(
                    validate_against_json_schema(instance, schema["then"], root_schema, path)
                )
        elif isinstance(schema.get("else"), dict):
            errors.extend(
                validate_against_json_schema(instance, schema["else"], root_schema, path)
            )

    return errors
