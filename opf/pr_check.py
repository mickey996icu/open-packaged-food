"""Pull request metadata, cross-repo companion link, file-scope, and DCO validator for OPF repositories."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
CODE_SPAN_RE = re.compile(r"```.*?```|`[^`\n]+`", re.DOTALL)
CHECKBOX_ANY_RE = re.compile(r"^\s*[-*]\s*\[[ xX]\]\s+", re.MULTILINE)
CHECKBOX_CHECKED_RE = re.compile(r"^\s*[-*]\s*\[[xX]\]\s+", re.MULTILINE)
DCO_SIGNOFF_RE = re.compile(r"^Signed-off-by:\s+\S.*?<[^>\s]+@[^>\s]+>\s*$", re.MULTILINE)

UNRESOLVED_PLACEHOLDER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"<MEDIA_PR_URL>", re.IGNORECASE), "<MEDIA_PR_URL>"),
    (re.compile(r"<DATA_PR_URL>", re.IGNORECASE), "<DATA_PR_URL>"),
    (re.compile(r"填上[^\n]{0,30}(?:PR|链接)", re.IGNORECASE), "unfilled PR link prompt"),
    (re.compile(r"请填写[^\n]{0,30}(?:PR|链接)", re.IGNORECASE), "unfilled PR link prompt"),
    (re.compile(r"\bTODO\s*:\s*fill\b", re.IGNORECASE), "TODO placeholder"),
)

COMPANION_MEDIA_PR_RE = re.compile(
    r"https://github\.com/[A-Za-z0-9_.-]+/opf-media/pull/[1-9][0-9]*"
)
COMPANION_DATA_PR_RE = re.compile(
    r"https://github\.com/[A-Za-z0-9_.-]+/opf-data/pull/[1-9][0-9]*"
)
PRODUCT_IDENTIFIER_RE = re.compile(
    r"(?:\bgtin:[0-9]{8,14}\b|\bopf:[a-z0-9-]+/[a-z0-9-]+/[a-z0-9.-]+\b|\b[0-9]{8,14}\b)"
)

REPO_MAINTENANCE_PREFIXES = (".github/", "docs/", "LICENSES/")
REPO_MAINTENANCE_FILES = {
    ".gitignore",
    "LICENSE",
    "REUSE.toml",
    "LICENSE-DATA",
    "LICENSE-MEDIA",
}


def _norm_rel_path(rel_path: str) -> str:
    norm = rel_path.strip()
    while norm.startswith("./"):
        norm = norm[2:]
    return norm


def _is_maintenance_path(rel_path: str) -> bool:
    norm = _norm_rel_path(rel_path)
    if norm in REPO_MAINTENANCE_FILES:
        return True
    if norm.startswith(REPO_MAINTENANCE_PREFIXES):
        return True
    if norm.startswith(("README.", "CONTRIBUTING.", "GOVERNANCE.")) or norm in (
        "README.md",
        "CONTRIBUTING.md",
        "GOVERNANCE.md",
    ):
        return True
    return False


def strip_markdown_comments(text: str) -> str:
    return HTML_COMMENT_RE.sub("", text or "").strip()


def validate_pr_metadata(
    *,
    repo_kind: str,
    title: str,
    body: str,
    changed_files: list[str] | None = None,
    require_companion_media_pr: bool = False,
    commits: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Validate PR title, description, unresolved placeholders, repo file scope, and DCO sign-offs."""
    errors: list[str] = []
    clean_title = (title or "").strip()
    if len(clean_title) < 8:
        errors.append("PR title must be at least 8 characters and concisely describe the change.")

    clean_body = strip_markdown_comments(body or "")
    if len(clean_body) < 20:
        errors.append(
            "PR description must not be empty (at least 20 characters); summarize the change or complete the PR template."
        )
    else:
        prose_body = CODE_SPAN_RE.sub("", clean_body)
        for pat, label in UNRESOLVED_PLACEHOLDER_PATTERNS:
            if pat.search(prose_body):
                errors.append(f"PR description contains unresolved placeholder ({label}); replace it with the real value.")

        if CHECKBOX_ANY_RE.search(clean_body) and not CHECKBOX_CHECKED_RE.search(clean_body):
            errors.append(
                "PR description includes template checkboxes but none are checked ('- [x]')."
            )

    files = [_norm_rel_path(f) for f in (changed_files or []) if f.strip()]

    if repo_kind == "media":
        disallowed = [
            f for f in files if not f.startswith("media/") and not _is_maintenance_path(f)
        ]
        if disallowed:
            errors.append(
                "opf-media PR modifies unexpected paths outside media/: " + ", ".join(disallowed[:5])
            )
        touches_media = (not files) or any(f.startswith("media/") for f in files)
        if touches_media and clean_body:
            has_product_or_pr = bool(
                PRODUCT_IDENTIFIER_RE.search(clean_body)
                or COMPANION_DATA_PR_RE.search(clean_body)
            )
            if not has_product_or_pr:
                errors.append(
                    "opf-media label PR description must reference the target product ID/barcode (e.g. gtin:...) or companion opf-data PR URL."
                )

    elif repo_kind == "data":
        touches_data = (not files) or any(
            f.startswith(("products/", "overlays/")) for f in files
        )
        if touches_data and require_companion_media_pr:
            if not COMPANION_MEDIA_PR_RE.search(clean_body):
                errors.append(
                    "PR introduces opf-media:// references not yet on opf-media main, so the PR description must include the real companion opf-media PR URL (https://github.com/<org>/opf-media/pull/<N>)."
                )

    if commits:
        for sha, msg in commits:
            headline = (msg.strip().splitlines() or [""])[0]
            if headline.startswith("Merge "):
                continue
            if not DCO_SIGNOFF_RE.search(msg or ""):
                short_sha = sha[:8] if sha else "<commit>"
                errors.append(
                    f"Commit {short_sha} is missing a DCO 'Signed-off-by: Name <email>' trailer (use 'git commit -s')."
                )

    return errors


RESTRICTED_PROVENANCES: frozenset[str] = frozenset({"maintainer", "brand_owner", "partner"})
PROVENANCE_CORRECTION_TRAILER_RE = re.compile(r"^Provenance-Correction:\s+\S", re.MULTILINE)


def _edition_provenance_maps(
    doc: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]]]:
    if not isinstance(doc, dict) or "merged_into" in doc:
        return {}, {}
    ev_map: dict[str, dict[str, Any]] = {}
    for ev in doc.get("evidence") or []:
        if isinstance(ev, dict) and isinstance(ev.get("evidence_id"), str):
            ev_map[ev["evidence_id"]] = ev
    rev_map: dict[int, dict[str, Any]] = {}
    for r in doc.get("revisions") or []:
        if isinstance(r, dict) and isinstance(r.get("rev"), int):
            rev_map[r["rev"]] = r
    return ev_map, rev_map


def _has_provenance_correction_trailer(commits: list[tuple[str, str]] | None) -> bool:
    for _sha, msg in commits or []:
        if PROVENANCE_CORRECTION_TRAILER_RE.search(msg or ""):
            return True
    return False


def find_provenance_policy_errors(
    *,
    repo_dir: Path,
    base_ref: str,
    changed_files: list[str],
    pr_actor: str,
    maintainer_logins: set[str],
    relay_logins: set[str] | None = None,
    commits: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Enforce PR provenance creation rules and immutability of existing provenance tags."""
    actor_norm = (pr_actor or "").strip().lower()
    allowed_maintainers = {m.strip().lower() for m in maintainer_logins if m and m.strip()}
    allowed_relays = {r.strip().lower() for r in (relay_logins or set()) if r and r.strip()}
    is_maintainer = bool(actor_norm and actor_norm in allowed_maintainers)
    is_relay = bool(actor_norm and not is_maintainer and actor_norm in allowed_relays)
    has_correction_trailer = _has_provenance_correction_trailer(commits)

    errors: list[str] = []
    for raw_path in changed_files:
        rel_path = _norm_rel_path(raw_path)
        if not (
            rel_path.startswith("products/")
            and "/editions/" in rel_path
            and rel_path.endswith(".json")
        ):
            continue
        cur_file = repo_dir / rel_path
        show_res = subprocess.run(
            ["git", "-C", str(repo_dir), "show", f"{base_ref}:{rel_path}"],
            capture_output=True,
            text=True,
            check=False,
        )
        base_exists = show_res.returncode == 0 and bool(show_res.stdout.strip())
        if not cur_file.is_file():
            # Deleting an existing edition file would silently drop provenance-tagged entries.
            if base_exists and not is_maintainer:
                errors.append(
                    f"{rel_path}: non-maintainer PR author {pr_actor!r} cannot delete an existing edition file (use lifecycle 'retracted' instead)."
                )
            continue
        try:
            cur_doc = json.loads(cur_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(cur_doc, dict) and "merged_into" in cur_doc:
            # Merge redirect stubs are governed by validator merge rules; here we only
            # ensure a non-maintainer consolidation carried every existing evidence entry
            # into the target edition (evidence[] stays append-only across merges).
            if base_exists and not is_maintainer:
                try:
                    base_doc_m = json.loads(show_res.stdout)
                except Exception:
                    base_doc_m = None
                if isinstance(base_doc_m, dict) and "merged_into" not in base_doc_m:
                    base_ev_ids = set(_edition_provenance_maps(base_doc_m)[0])
                    target_file = cur_file.parent / f"{cur_doc.get('merged_into')}.json"
                    target_ev_ids: set[str] = set()
                    try:
                        target_doc = json.loads(target_file.read_text(encoding="utf-8"))
                        target_ev_ids = set(_edition_provenance_maps(target_doc)[0])
                    except Exception:
                        pass
                    for ev_id in sorted(base_ev_ids - target_ev_ids):
                        errors.append(
                            f"{rel_path}: merge into {cur_doc.get('merged_into')!r} drops existing evidence {ev_id!r} (evidence must be carried into the target edition)."
                        )
            continue
        cur_ev_map, cur_rev_map = _edition_provenance_maps(cur_doc)

        base_ev_map: dict[str, dict[str, Any]] = {}
        base_rev_map: dict[int, dict[str, Any]] = {}
        if base_exists:
            try:
                base_doc = json.loads(show_res.stdout)
                base_ev_map, base_rev_map = _edition_provenance_maps(base_doc)
            except Exception:
                pass

        if not is_maintainer:
            for ev_id in sorted(set(base_ev_map) - set(cur_ev_map)):
                errors.append(
                    f"{rel_path}: non-maintainer PR author {pr_actor!r} cannot remove existing evidence {ev_id!r} (evidence[] is append-only)."
                )
            for rev_num in sorted(set(base_rev_map) - set(cur_rev_map)):
                errors.append(
                    f"{rel_path}: non-maintainer PR author {pr_actor!r} cannot remove existing revision rev={rev_num} (revisions[] is append-only)."
                )

        for ev_id, cur_ev in cur_ev_map.items():
            cur_prov = cur_ev.get("provenance")
            base_ev = base_ev_map.get(ev_id)
            if base_ev is None:
                # Newly introduced evidence entry
                if is_relay:
                    if cur_prov != "public_submission":
                        errors.append(
                            f"{rel_path}: relay bot {pr_actor!r} may only set provenance='public_submission' on new evidence {ev_id!r}, got {cur_prov!r}."
                        )
                elif not is_maintainer:
                    if cur_prov != "external_contributor":
                        errors.append(
                            f"{rel_path}: external PR author {pr_actor!r} may only set provenance='external_contributor' on new evidence {ev_id!r}, got {cur_prov!r}."
                        )
                if not is_maintainer and cur_ev.get("transcription") == "independent_match":
                    errors.append(
                        f"{rel_path}: non-maintainer PR author {pr_actor!r} cannot set transcription='independent_match' on evidence {ev_id!r}."
                    )
            else:
                # Existing evidence entry: provenance is immutable unless maintainer + Provenance-Correction trailer
                base_prov = base_ev.get("provenance")
                if base_prov and cur_prov != base_prov:
                    if not is_maintainer or not has_correction_trailer:
                        errors.append(
                            f"{rel_path}: existing evidence {ev_id!r} provenance ({base_prov!r} -> {cur_prov!r}) cannot be modified without maintainer authorization and a 'Provenance-Correction: <reason>' commit trailer."
                        )
                if not is_maintainer and cur_ev.get("transcription") != base_ev.get("transcription"):
                    errors.append(
                        f"{rel_path}: non-maintainer PR author {pr_actor!r} cannot modify transcription attestation on existing evidence {ev_id!r}."
                    )

        for rev_num, cur_rev in cur_rev_map.items():
            cur_prov = cur_rev.get("provenance")
            base_rev = base_rev_map.get(rev_num)
            if base_rev is None:
                if is_relay:
                    if cur_prov != "public_submission":
                        errors.append(
                            f"{rel_path}: relay bot {pr_actor!r} may only set provenance='public_submission' on new revision rev={rev_num}, got {cur_prov!r}."
                        )
                elif not is_maintainer:
                    if cur_prov != "external_contributor":
                        errors.append(
                            f"{rel_path}: external PR author {pr_actor!r} may only set provenance='external_contributor' on new revision rev={rev_num}, got {cur_prov!r}."
                        )
            else:
                base_prov = base_rev.get("provenance")
                if base_prov and cur_prov != base_prov:
                    if not is_maintainer or not has_correction_trailer:
                        errors.append(
                            f"{rel_path}: existing revision rev={rev_num} provenance ({base_prov!r} -> {cur_prov!r}) cannot be modified without maintainer authorization and a 'Provenance-Correction: <reason>' commit trailer."
                        )
    return errors


def _git_changed_files_and_commits(
    repo_dir: Path, base_ref: str
) -> tuple[list[str], list[tuple[str, str]]]:
    diff_res = subprocess.run(
        ["git", "-C", str(repo_dir), "diff", "--name-only", f"{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    changed = [ln.strip() for ln in diff_res.stdout.splitlines() if ln.strip()]

    log_res = subprocess.run(
        ["git", "-C", str(repo_dir), "log", "--no-merges", "--format=%H%x00%B%x1e", f"{base_ref}..HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    commits: list[tuple[str, str]] = []
    for rec in log_res.stdout.split("\x1e"):
        rec = rec.strip()
        if not rec or "\x00" not in rec:
            continue
        sha, body = rec.split("\x00", 1)
        commits.append((sha.strip(), body.strip()))
    return changed, commits


def register_pr_check_subparser(sub: argparse._SubParsersAction[Any]) -> None:
    p = sub.add_parser(
        "check-pr-meta",
        help="Validate PR title, description, companion PR links, file scope, and DCO sign-off",
    )
    p.add_argument(
        "--repo-kind",
        choices=["tooling", "data", "media"],
        required=True,
        help="Target OPF repository role",
    )
    p.add_argument("--event-path", help="Path to GitHub Actions GITHUB_EVENT_PATH JSON")
    p.add_argument("--title", help="Explicit PR title (overrides --event-path)")
    p.add_argument("--body", help="Explicit PR body string (overrides --event-path)")
    p.add_argument("--body-file", help="Path to file containing PR body")
    p.add_argument("--repo-dir", help="Local git repository directory to inspect changed files and DCO commits")
    p.add_argument("--base-ref", help="Base git ref (e.g. origin/main) for diff and commit range")
    p.add_argument(
        "--require-companion-media-pr",
        action="store_true",
        help="Require a valid opf-media pull request URL in the PR description",
    )
    p.add_argument(
        "--maintainer-login",
        action="append",
        help="GitHub login allowed to submit maintainer/brand_owner/partner provenance entries (repeatable; defaults to base repo owner / OPF_MAINTAINER_LOGINS)",
    )
    p.add_argument(
        "--relay-login",
        action="append",
        help="GitHub login for Phase 2 submission relay bot (only allowed to create provenance='public_submission' entries; env OPF_RELAY_LOGINS)",
    )
    p.set_defaults(func=cmd_check_pr_meta)


def cmd_check_pr_meta(args: argparse.Namespace) -> int:
    title = args.title or ""
    body = args.body or ""
    pr_actor = ""
    maintainer_logins: set[str] = {
        m.strip() for m in (args.maintainer_login or []) if m and m.strip()
    }
    env_maintainers = os.environ.get("OPF_MAINTAINER_LOGINS", "")
    for item in env_maintainers.split(","):
        if item.strip():
            maintainer_logins.add(item.strip())

    relay_logins: set[str] = {
        r.strip() for r in (args.relay_login or []) if r and r.strip()
    }
    for item in os.environ.get("OPF_RELAY_LOGINS", "").split(","):
        if item.strip():
            relay_logins.add(item.strip())

    if args.event_path:
        ev_data = json.loads(Path(args.event_path).read_text(encoding="utf-8"))
        pr_obj = ev_data.get("pull_request") or {}
        if not title:
            title = str(pr_obj.get("title") or "")
        if not body and not args.body_file:
            body = str(pr_obj.get("body") or "")
        pr_actor = str((pr_obj.get("user") or {}).get("login") or "")
        owner_login = str((((pr_obj.get("base") or {}).get("repo") or {}).get("owner") or {}).get("login") or "")
        if owner_login and not args.maintainer_login and not env_maintainers:
            maintainer_logins.add(owner_login)

    if not maintainer_logins:
        gh_owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "").strip()
        if gh_owner:
            maintainer_logins.add(gh_owner)

    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")

    changed_files: list[str] | None = None
    commits: list[tuple[str, str]] | None = None
    if args.repo_dir and args.base_ref:
        changed_files, commits = _git_changed_files_and_commits(
            Path(args.repo_dir), args.base_ref
        )

    errs = validate_pr_metadata(
        repo_kind=args.repo_kind,
        title=title,
        body=body,
        changed_files=changed_files,
        require_companion_media_pr=bool(args.require_companion_media_pr),
        commits=commits,
    )
    if args.repo_kind == "data" and args.repo_dir and args.base_ref and changed_files is not None and pr_actor:
        errs.extend(
            find_provenance_policy_errors(
                repo_dir=Path(args.repo_dir),
                base_ref=args.base_ref,
                changed_files=changed_files,
                pr_actor=pr_actor,
                maintainer_logins=maintainer_logins,
                relay_logins=relay_logins,
                commits=commits,
            )
        )
    if errs:
        for e in errs:
            print(f"PR_META_ERROR: {e}", file=sys.stderr)
        return 1

    print(f"OK   PR metadata & DCO ({args.repo_kind})")
    return 0
