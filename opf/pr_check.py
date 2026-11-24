"""Pull request metadata, cross-repo companion link, file-scope, and DCO validator for OPF repositories."""

from __future__ import annotations

import argparse
import json
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

REPO_MAINTENANCE_PREFIXES = (".github/",)
REPO_MAINTENANCE_FILES = {
    ".gitignore",
    "LICENSE",
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
    if norm.startswith(("README.", "CONTRIBUTING.")) or norm in ("README.md", "CONTRIBUTING.md"):
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
    p.set_defaults(func=cmd_check_pr_meta)


def cmd_check_pr_meta(args: argparse.Namespace) -> int:
    title = args.title or ""
    body = args.body or ""

    if args.event_path:
        ev_data = json.loads(Path(args.event_path).read_text(encoding="utf-8"))
        pr_obj = ev_data.get("pull_request") or {}
        if not title:
            title = str(pr_obj.get("title") or "")
        if not body and not args.body_file:
            body = str(pr_obj.get("body") or "")

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
    if errs:
        for e in errs:
            print(f"PR_META_ERROR: {e}", file=sys.stderr)
        return 1

    print(f"OK   PR metadata & DCO ({args.repo_kind})")
    return 0
