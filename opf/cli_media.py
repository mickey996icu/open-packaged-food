"""Media repository validation, cross-repo media ref checks, and sanitization CLI commands for OPF v0.3."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from opf.media import (
    process_cropped_label_to_webp,
    sanitize_and_hash_image,
    validate_media_repo,
)


def _extract_media_sha_refs(doc: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for ev in doc.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        mref = str(ev.get("media_ref") or "").strip()
        m = re.match(r"^opf-media://sha256/([a-f0-9]{64})$", mref)
        if m:
            refs.append(m.group(1))
    return refs


def check_media_blob_http(media_base_url: str, sha256_hex: str) -> tuple[bool, str]:
    url = f"{media_base_url.rstrip('/')}/media/{sha256_hex[0:2]}/{sha256_hex[2:4]}/{sha256_hex}.webp"
    headers = {"User-Agent": "opf-ci-media-check/0.3"}
    last_err = ""
    for attempt in range(3):
        for method, extra_headers in (("HEAD", {}), ("GET", {"Range": "bytes=0-15"})):
            req = urllib.request.Request(url, method=method, headers={**headers, **extra_headers})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status = getattr(resp, "status", 200)
                    if status in (200, 206, 304):
                        return True, str(status)
                    last_err = f"HTTP {status}"
            except urllib.error.HTTPError as exc:
                last_err = f"HTTP {exc.code}"
                if method == "HEAD" and exc.code in (403, 405, 501):
                    continue
                if exc.code in (404, 410):
                    return False, last_err
                if exc.code >= 500:
                    break
                return False, last_err
            except Exception as exc:
                last_err = str(exc)
                break
        if attempt < 2:
            time.sleep(0.4 * (attempt + 1))
    return False, last_err or "request failed"


def check_media_refs(
    paths: list[Path],
    *,
    media_dir: Path | None = None,
    media_base_url: str = "",
    only_refs_from_git_diff: str | None = None,
    warn_only: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Verify referenced `opf-media://sha256/<hex>` blobs exist in media_dir or remote media_base_url."""
    refs_map: dict[str, list[str]] = {}

    if only_refs_from_git_diff:
        resolved_targets = [Path(p).resolve() for p in paths]
        anchor = resolved_targets[0] if resolved_targets[0].is_dir() else resolved_targets[0].parent
        top = subprocess.run(
            ["git", "-C", str(anchor), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if top.returncode != 0 or not top.stdout.strip():
            return 1, {"error": f"Failed to resolve git repository for diff base {only_refs_from_git_diff!r}"}
        git_root = Path(top.stdout.strip()).resolve()
        rel_filters: list[str] = []
        for t in resolved_targets:
            try:
                rel_p = t.relative_to(git_root).as_posix()
                rel_filters.append(rel_p or ".")
            except ValueError:
                pass
        diff_cmd = ["git", "-C", str(git_root), "diff", "--name-only", only_refs_from_git_diff]
        if rel_filters:
            diff_cmd.extend(["--", *rel_filters])
        diff_res = subprocess.run(diff_cmd, capture_output=True, text=True, check=False)
        if diff_res.returncode != 0:
            return 1, {"error": f"git diff failed: {diff_res.stderr.strip()}"}

        for rel_file in sorted(set(diff_res.stdout.splitlines())):
            if not rel_file.endswith(".json") or Path(rel_file).name == "product.json":
                continue
            fpath = git_root / rel_file
            if not fpath.is_file():
                continue
            try:
                doc = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(doc, dict) or "merged_into" in doc or "evidence" not in doc:
                continue
            old_refs: set[str] = set()
            show_res = subprocess.run(
                ["git", "-C", str(git_root), "show", f"{only_refs_from_git_diff}:{rel_file}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if show_res.returncode == 0 and show_res.stdout.strip():
                try:
                    old_doc = json.loads(show_res.stdout)
                    if isinstance(old_doc, dict):
                        old_refs = set(_extract_media_sha_refs(old_doc))
                except Exception:
                    pass
            for sha_hex in _extract_media_sha_refs(doc):
                if sha_hex not in old_refs:
                    refs_map.setdefault(sha_hex, []).append(rel_file)
    else:
        for raw_p in paths:
            p = Path(raw_p)
            cand_files: list[Path] = []
            if p.is_file():
                cand_files = [p]
            elif p.is_dir():
                cand_files = sorted(jf for jf in p.rglob("*.json") if jf.name != "product.json")
            for jf in cand_files:
                try:
                    doc = json.loads(jf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(doc, dict) or "merged_into" in doc or "evidence" not in doc:
                    continue
                for sha_hex in _extract_media_sha_refs(doc):
                    refs_map.setdefault(sha_hex, []).append(str(jf))

    if not refs_map:
        return 0, {"checked": 0, "missing": [], "status": "ok"}

    if media_dir is None and not media_base_url:
        return (0 if warn_only else 1), {
            "checked": len(refs_map),
            "missing": sorted(refs_map.keys()),
            "error": f"Specify --media-dir or --media-base-url to verify {len(refs_map)} opf-media reference(s).",
        }

    missing: list[dict[str, Any]] = []
    for sha_hex in sorted(refs_map.keys()):
        ed_files = sorted(dict.fromkeys(refs_map[sha_hex]))
        if media_dir is not None:
            blob_path = Path(media_dir) / "media" / sha_hex[0:2] / sha_hex[2:4] / f"{sha_hex}.webp"
            ok = blob_path.is_file() and hashlib.sha256(blob_path.read_bytes()).hexdigest() == sha_hex
            detail = "ok" if ok else "not_found_or_hash_mismatch"
        else:
            ok, detail = check_media_blob_http(media_base_url, sha_hex)
        if not ok:
            missing.append({"sha256": sha_hex, "editions": ed_files, "detail": detail})

    rc = 0 if (not missing or warn_only) else 1
    return rc, {
        "checked": len(refs_map),
        "missing": missing,
        "status": "ok" if not missing else ("warn" if warn_only else "missing"),
    }


def cmd_check_media_refs(args: argparse.Namespace) -> int:
    media_dir = Path(args.media_dir) if args.media_dir else None
    rc, report = check_media_refs(
        [Path(p) for p in args.paths],
        media_dir=media_dir,
        media_base_url=args.media_base_url,
        only_refs_from_git_diff=args.only_refs_from_git_diff,
        warn_only=args.warn_only,
    )
    if "error" in report:
        print(report["error"], file=sys.stderr)
        return rc
    if report["checked"] == 0:
        print("OK (0 opf-media references to verify)")
        return 0
    for item in report["missing"]:
        ed_label = ", ".join(item["editions"])
        print(
            f"MISSING_MEDIA: opf-media://sha256/{item['sha256']} ({ed_label}) not found on opf-media main. "
            "Merge the companion opf-media PR FIRST, then re-run this CI job.",
            file=sys.stderr,
        )
    if not report["missing"]:
        print(f"OK ({report['checked']} opf-media reference(s) verified)")
    return rc


def cmd_validate_media(args: argparse.Namespace) -> int:
    root = Path(args.media_root)
    store_dir = root / "media" if (root / "media").is_dir() else (root if root.name == "media" else root / "media")
    errs = validate_media_repo(root, max_edge=args.max_edge, max_bytes=args.max_bytes)
    webp_count = 0
    if store_dir.is_dir():
        webp_count = sum(
            1 for f in store_dir.rglob("*") if f.is_file() and f.name != ".gitkeep" and f.suffix == ".webp"
        )
    if not errs and webp_count == 0 and not args.allow_empty:
        errs.append(
            f"Media repository {root} contains 0 .webp files; pass --allow-empty if empty initialization is expected."
        )
    if getattr(args, "json", False):
        print(
            json.dumps(
                {"valid": len(errs) == 0, "media_root": str(root), "webp_count": webp_count, "errors": errs},
                ensure_ascii=False,
                indent=2,
            )
        )
    elif errs:
        print(f"FAIL {root}:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
    else:
        print(f"OK   {root} ({webp_count} WebP files)")
    return 0 if not errs else 1


def cmd_sanitize_media(args: argparse.Namespace) -> int:
    reports = []
    media_root = Path(args.media_root) if getattr(args, "media_root", None) else None
    out_dir = Path(args.out_dir) if getattr(args, "out_dir", None) else None
    lossless_only = bool(getattr(args, "lossless_only", False))
    max_edge = int(getattr(args, "max_edge", 1000))
    quality = int(getattr(args, "quality", 80))

    for raw in args.images:
        in_path = Path(raw)
        if not in_path.is_file():
            print(f"Image file not found: {in_path}", file=sys.stderr)
            return 1
        if lossless_only:
            out_path = (out_dir / in_path.name) if out_dir else None
            rep = sanitize_and_hash_image(in_path, out_path)
            reports.append(rep)
        else:
            if media_root is not None:
                rep = process_cropped_label_to_webp(
                    in_path, media_root=media_root, max_edge=max_edge, quality=quality
                )
                if out_dir is not None and rep["output"]:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    dest = out_dir / f"{rep['sha256']}.webp"
                    dest.write_bytes(Path(rep["output"]).read_bytes())
                    rep["out_dir_copy"] = str(dest)
            elif out_dir is not None:
                with tempfile.TemporaryDirectory(prefix="opf-webp-") as tmp:
                    rep = process_cropped_label_to_webp(
                        in_path, media_root=Path(tmp), max_edge=max_edge, quality=quality
                    )
                    out_dir.mkdir(parents=True, exist_ok=True)
                    dest = out_dir / f"{rep['sha256']}.webp"
                    dest.write_bytes(Path(rep["output"]).read_bytes())
                    rep["output"] = str(dest)
            else:
                rep = process_cropped_label_to_webp(
                    in_path, media_root=None, out_path=None, max_edge=max_edge, quality=quality
                )
            reports.append(rep)
    print(json.dumps({"sanitized": reports}, ensure_ascii=False, indent=2))
    return 0


def register_media_subparsers(sub: argparse._SubParsersAction) -> None:
    p_vmed = sub.add_parser(
        "validate-media",
        help="Validate content-addressed WebP label evidence store (zero Pillow dependency)",
    )
    p_vmed.add_argument("media_root", help="Path to opf-media repository root or media/ directory")
    p_vmed.add_argument("--allow-empty", action="store_true", help="Allow 0 .webp files")
    p_vmed.add_argument("--max-edge", type=int, default=1000, help="Maximum allowed pixel edge (default: 1000)")
    p_vmed.add_argument("--max-bytes", type=int, default=512_000, help="Maximum bytes per WebP (default: 512000)")
    p_vmed.add_argument("--json", action="store_true", help="Output validation report as JSON")
    p_vmed.set_defaults(func=cmd_validate_media)

    p_cmr = sub.add_parser(
        "check-media-refs",
        help="Verify opf-media://sha256/<hex> references exist on opf-media before merging opf-data PRs",
    )
    p_cmr.add_argument("paths", nargs="+", help="Products root directory, product dir, or edition JSON paths")
    p_cmr.add_argument("--media-dir", help="Local opf-media checkout directory")
    p_cmr.add_argument(
        "--media-base-url",
        default=os.environ.get("OPF_MEDIA_BASE_URL", ""),
        help="Remote media base URL (default env OPF_MEDIA_BASE_URL)",
    )
    p_cmr.add_argument(
        "--only-refs-from-git-diff",
        help="Only check opf-media refs newly added vs the given git base ref",
    )
    p_cmr.add_argument("--warn-only", action="store_true", help="Print warnings without failing exit code")
    p_cmr.set_defaults(func=cmd_check_media_refs)

    p_media = sub.add_parser(
        "sanitize-media",
        help="Transcode cropped label photos to <=1000px EXIF-free WebP (or strip losslessly with --lossless-only)",
    )
    p_media.add_argument("images", nargs="+", help="Image files (JPEG, PNG, WebP)")
    p_media.add_argument("--media-root", help="Write content-addressed <dir>/media/<h0:2>/<h2:4>/<sha256>.webp")
    p_media.add_argument("--out-dir", help="Optional directory to write sanitized images")
    p_media.add_argument("--max-edge", type=int, default=1000, help="Max pixel edge in WebP mode (default: 1000)")
    p_media.add_argument("--quality", type=int, default=80, help="WebP quality 1-100 (default: 80)")
    p_media.add_argument(
        "--lossless-only",
        action="store_true",
        help="Strip EXIF/XMP/IPTC metadata in original image format without WebP transcoding",
    )
    p_media.set_defaults(func=cmd_sanitize_media)
