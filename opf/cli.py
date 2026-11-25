"""Command-line interface dispatcher and core authoring subcommands for OpenPackagedFood (opf v0.3)."""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from opf import __version__
from opf.audit import register_audit_subparser
from opf.builder import build_static_api
from opf.cli_common import write_json
from opf.cli_lifecycle import register_lifecycle_subparsers
from opf.cli_media import check_media_refs, register_media_subparsers
from opf.cli_pr import register_pr_subparser
from opf.cli_submit import register_submit_subparser
from opf.ingredients import (
    annotate_ingredients_spans,
    parse_ingredients_semantic,
    verify_ingredients_round_trip,
)
from opf.normalize import normalize_edition
from opf.pr_check import register_pr_check_subparser
from opf.validator import (
    load_json_schema,
    validate_against_json_schema,
    validate_edition_doc,
    validate_product_dir,
    validate_product_doc,
    validate_products_root,
)

__all__ = ["check_media_refs", "main"]


def cmd_validate(args: argparse.Namespace) -> int:
    total_errors = 0
    results: list[dict[str, Any]] = []

    for raw in args.paths:
        p = Path(raw)
        if not p.exists():
            errs = [f"Path does not exist: {p}"]
            total_errors += 1
            results.append({"path": str(p), "kind": "missing", "valid": False, "errors": errs})
        elif p.is_dir() and (p / "product.json").is_file():
            errs = validate_product_dir(p)
            total_errors += len(errs)
            results.append({"path": str(p), "kind": "product_dir", "valid": not errs, "errors": errs})
        elif p.is_dir():
            errs = validate_products_root(p, allow_empty=bool(getattr(args, "allow_empty", False)))
            total_errors += len(errs)
            results.append({"path": str(p), "kind": "products_root", "valid": not errs, "errors": errs})
        else:
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                errs = [f"Failed to parse JSON: {exc}"]
                total_errors += 1
                results.append({"path": str(p), "kind": "file", "valid": False, "errors": errs})
                continue

            if isinstance(doc, dict) and "resolution" in doc and doc.get("opf_schema") == "0.3":
                errs = validate_against_json_schema(doc, load_json_schema("compact.v0.3.schema.json"))
            else:
                errs = validate_product_doc(doc)
            total_errors += len(errs)
            results.append(
                {
                    "path": str(p),
                    "id": doc.get("id") if isinstance(doc, dict) else None,
                    "kind": "file",
                    "valid": not errs,
                    "errors": errs,
                }
            )

    if args.json:
        print(json.dumps({"valid": total_errors == 0, "results": results}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            if r["valid"]:
                label = r.get("id") or r["kind"]
                print(f"OK   {r['path']} ({label})")
            else:
                print(f"FAIL {r['path']}:", file=sys.stderr)
                for e in r["errors"]:
                    print(f"  - {e}", file=sys.stderr)

    return 0 if total_errors == 0 else 1


def _collect_edition_files_for_normalize(paths: list[str]) -> list[Path]:
    result: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for jf in sorted(p.rglob("*.json")):
                if jf.name == "product.json":
                    continue
                result.append(jf)
        else:
            result.append(p)
    return result


def cmd_normalize(args: argparse.Namespace) -> int:
    files = _collect_edition_files_for_normalize(args.paths)
    if not files:
        print("No edition JSON files found to normalize.", file=sys.stderr)
        return 1

    processed = 0
    for fpath in files:
        try:
            doc = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Failed to parse {fpath}: {exc}", file=sys.stderr)
            return 1

        if not isinstance(doc, dict) or "merged_into" in doc or "core" not in doc:
            continue

        processed += 1
        core = doc["core"]
        attrs = doc.get("attributes") or {}
        profile_id = core["regulatory_profile"]
        if args.parse_ingredients or not core.get("ingredients_tree"):
            trees = []
            for item in attrs.get("ingredients_text", []):
                nodes = parse_ingredients_semantic(
                    item["text"], lang=item["lang"], profile_id=profile_id
                )
                trees.append({"lang": item["lang"], "nodes": nodes})
            core["ingredients_tree"] = sorted(trees, key=lambda x: str(x["lang"]))

        try:
            normalize_edition(doc)
        except ValueError as exc:
            print(f"Normalization error in {fpath}: {exc}", file=sys.stderr)
            return 1
        errs = validate_edition_doc(doc)
        if errs:
            print(f"Validation failed after normalizing {fpath}:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 1

        if args.in_place:
            write_json(fpath, doc)
            print(f"Normalized {fpath} ({doc['id']} @ {doc['edition_id']})")
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))

    if processed == 0:
        print("No live EditionRecord JSON files found to normalize.", file=sys.stderr)
        return 1
    return 0


def cmd_parse_ingredients(args: argparse.Namespace) -> int:
    nodes = parse_ingredients_semantic(args.text, lang=args.lang, profile_id=args.profile)
    errs = verify_ingredients_round_trip(args.text, nodes, profile_id=args.profile)
    out_nodes = (
        annotate_ingredients_spans(args.text, nodes, profile_id=args.profile)
        if getattr(args, "with_spans", False) and not errs
        else nodes
    )
    out = {
        "lang": args.lang,
        "profile": args.profile,
        "round_trip_valid": len(errs) == 0,
        "errors": errs,
        "nodes": out_nodes,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if errs:
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    try:
        meta = build_static_api(
            data_dir,
            out_dir,
            canonical_base=args.canonical_base,
            media_base_url=getattr(args, "media_base_url", ""),
        )
    except Exception as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Built static API v1 in {out_dir} ({meta['total_products']} products, "
        f"resolutions: {meta['counts_by_resolution']}, evidence: {meta['counts_by_evidence_level']})"
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    if args.data_dir:
        site_dir = Path(args.dir) if args.dir else Path(tempfile.mkdtemp(prefix="opf-site-"))
        build_static_api(
            Path(args.data_dir),
            site_dir,
            media_base_url=getattr(args, "media_base_url", ""),
        )
    elif args.dir:
        site_dir = Path(args.dir)
    else:
        print("Specify either --dir <built_site_dir> or --data-dir <products_dir>.", file=sys.stderr)
        return 1

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site_dir))
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        print(f"Serving OpenPackagedFood Catalog at http://{args.host}:{args.port}/ (from {site_dir})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opf",
        description="OpenPackagedFood CLI (v0.3): validate, validate-media, check-media-refs, audit, normalize, parse-ingredients, submit, retrack, merge, lifecycle, pr, build, sanitize-media, serve",
    )
    parser.add_argument("--version", action="version", version=f"opf {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="Validate OPF v0.3 products root, product directory, or JSON file")
    p_val.add_argument("paths", nargs="+", help="Product directory, products root, or JSON file")
    p_val.add_argument("--json", action="store_true", help="Output validation report as JSON")
    p_val.add_argument(
        "--allow-empty",
        action="store_true",
        help="Succeed if products root contains 0 product directories and 0 orphan JSON files",
    )
    p_val.set_defaults(func=cmd_validate)

    register_media_subparsers(sub)

    p_norm = sub.add_parser(
        "normalize",
        help="Canonicalize v0.3 core and compile normalized 100g/100ml layer + fingerprints",
    )
    p_norm.add_argument("paths", nargs="+", help="Edition JSON files or directories")
    p_norm.add_argument("--in-place", action="store_true", help="Write normalized output back to file")
    p_norm.add_argument(
        "--parse-ingredients",
        action="store_true",
        help="Re-parse span-free core.ingredients_tree from attributes.ingredients_text before normalizing",
    )
    p_norm.set_defaults(func=cmd_normalize)

    p_ing = sub.add_parser(
        "parse-ingredients",
        help="Parse raw ingredients text into span-free v0.3 AST and verify monotonic round-trip",
    )
    p_ing.add_argument("text", help="Raw ingredients text from label")
    p_ing.add_argument("--lang", default="zh-Hans", help="BCP-47 language code (default: zh-Hans)")
    p_ing.add_argument(
        "--profile",
        default="CN/GB28050-2011",
        help="Regulatory profile ID (default: CN/GB28050-2011)",
    )
    p_ing.add_argument(
        "--with-spans",
        action="store_true",
        help="Also compute and attach [start, end] spans for UI highlighting",
    )
    p_ing.set_defaults(func=cmd_parse_ingredients)

    p_build = sub.add_parser("build", help="Build static /v1/ API endpoints and indices")
    p_build.add_argument("--data-dir", required=True, help="Directory containing products tree")
    p_build.add_argument("--out-dir", required=True, help="Output directory for static API")
    p_build.add_argument("--canonical-base", default="", help="Optional canonical base URL")
    p_build.add_argument(
        "--media-base-url",
        default=os.environ.get("OPF_MEDIA_BASE_URL", ""),
        help="Base URL that opf-media://sha256/<hex> references resolve against (default env OPF_MEDIA_BASE_URL)",
    )
    p_build.set_defaults(func=cmd_build)

    register_submit_subparser(sub)
    register_lifecycle_subparsers(sub)
    register_pr_subparser(sub)

    p_serve = sub.add_parser("serve", help="Serve the static API and Catalog Card Explorer locally")
    p_serve.add_argument("--dir", help="Directory containing built static site")
    p_serve.add_argument("--data-dir", help="Build from products directory before serving")
    p_serve.add_argument(
        "--media-base-url",
        default=os.environ.get("OPF_MEDIA_BASE_URL", ""),
        help="Optional media base URL when building with --data-dir",
    )
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    p_serve.set_defaults(func=cmd_serve)

    register_pr_check_subparser(sub)
    register_audit_subparser(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
