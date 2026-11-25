"""Dual-repository sparse clone, auto-fork, and cross-linked PR orchestration (`opf pr`) for OPF v0.3."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from opf.audit import audit_products_root
from opf.cli_common import prepare_submission_inputs
from opf.cli_media import check_media_blob_http
from opf.cli_submit import execute_submit
from opf.ids import product_dir_for_id, validate_product_id
from opf.lifecycle import derive_evidence_level
from opf.media import validate_media_repo
from opf.validator import VALID_PROVENANCES


def _gh_authenticated_user() -> tuple[str | None, str | None]:
    if shutil.which("gh") is None:
        return None, "GitHub CLI (`gh`) is not installed in PATH."
    res = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True, check=False)
    if res.returncode != 0 or not res.stdout.strip():
        return None, "GitHub CLI is not authenticated. Run `gh auth login` first."
    return res.stdout.strip(), None


def _gh_fork_clone_url(target_repo: str, gh_user: str) -> str:
    owner, repo_name = target_repo.split("/", 1)
    if gh_user != owner:
        subprocess.run(["gh", "repo", "fork", target_repo, "--clone=false"], check=True, capture_output=True, text=True)
    proto_res = subprocess.run(["gh", "config", "get", "git_protocol"], capture_output=True, text=True, check=False)
    proto = (proto_res.stdout or "").strip().lower()
    fork_slug = f"{gh_user}/{repo_name}" if gh_user != owner else target_repo
    if proto == "ssh":
        return f"git@github.com:{fork_slug}.git"
    return f"https://github.com/{fork_slug}.git"


def _sparse_clone_repo(repo_slug: str, dest_dir: Path, sparse_paths: list[str]) -> None:
    clone_url = f"https://github.com/{repo_slug}.git"
    subprocess.run(
        ["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout", clone_url, str(dest_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "-C", str(dest_dir), "sparse-checkout", "init", "--no-cone"], check=True, capture_output=True)
    if sparse_paths:
        subprocess.run(
            ["git", "-C", str(dest_dir), "sparse-checkout", "set", *sparse_paths],
            check=True,
            capture_output=True,
        )
    subprocess.run(["git", "-C", str(dest_dir), "checkout"], check=True, capture_output=True)


def _fetch_upstream_product_if_reachable(target_data_repo: str, rel_pdir_sub: str, products_dir: Path) -> None:
    """Best-effort fast read-only fetch of an existing product directory for accurate --dry-run planning."""
    if os.environ.get("OPF_PR_DRY_RUN_OFFLINE") == "1":
        return
    api_base = f"https://api.github.com/repos/{target_data_repo}/contents/products/{rel_pdir_sub}"
    headers = {"User-Agent": "opf-cli-dry-run/0.3", "Accept": "application/vnd.github+json"}
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{api_base}?ref=main", headers=headers), timeout=1.5) as r:
            entries = json.loads(r.read().decode("utf-8"))
    except Exception:
        return
    if not isinstance(entries, list):
        return
    local_pdir = products_dir / rel_pdir_sub
    local_pdir.mkdir(parents=True, exist_ok=True)
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        if ent.get("type") == "file" and ent.get("name") == "product.json" and ent.get("download_url"):
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(ent["download_url"], headers=headers), timeout=1.5
                ) as rf:
                    (local_pdir / "product.json").write_bytes(rf.read())
            except Exception:
                pass
        elif ent.get("type") == "dir" and ent.get("name") == "editions":
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(f"{api_base}/editions?ref=main", headers=headers), timeout=1.5
                ) as re_resp:
                    ed_entries = json.loads(re_resp.read().decode("utf-8"))
                if isinstance(ed_entries, list):
                    (local_pdir / "editions").mkdir(parents=True, exist_ok=True)
                    for ed_ent in ed_entries:
                        if isinstance(ed_ent, dict) and ed_ent.get("download_url") and ed_ent.get("name", "").endswith(".json"):
                            with urllib.request.urlopen(
                                urllib.request.Request(ed_ent["download_url"], headers=headers), timeout=1.5
                            ) as ref_ed:
                                (local_pdir / "editions" / ed_ent["name"]).write_bytes(ref_ed.read())
            except Exception:
                pass


def _ensure_git_identity(repo_dir: Path, gh_user: str) -> None:
    """Ensure repo-local user.name and user.email exist before `git commit -s`."""
    email_res = subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.email"],
        capture_output=True,
        text=True,
        check=False,
    )
    if email_res.returncode != 0 or not email_res.stdout.strip():
        subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", gh_user], check=True)
        subprocess.run(
            ["git", "-C", str(repo_dir), "config", "user.email", f"{gh_user}@users.noreply.github.com"],
            check=True,
        )


def _set_git_remote(repo_dir: Path, remote_name: str, url: str) -> None:
    check_res = subprocess.run(
        ["git", "-C", str(repo_dir), "remote", "get-url", remote_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if check_res.returncode == 0:
        subprocess.run(["git", "-C", str(repo_dir), "remote", "set-url", remote_name, url], check=True)
    else:
        subprocess.run(["git", "-C", str(repo_dir), "remote", "add", remote_name, url], check=True)


def cmd_pr(args: argparse.Namespace) -> int:
    photo_specs = getattr(args, "photo", None) or []
    media_stage_raw = getattr(args, "media_stage_dir", None)
    media_repo_raw = getattr(args, "media_repo", None)
    data_repo_raw = getattr(args, "data_repo", None)
    vintage_month = getattr(args, "vintage_month", None)
    target_data_repo = getattr(args, "target_data_repo", None) or os.environ.get(
        "OPF_DATA_REPO", "mickey996icu/opf-data"
    )
    target_media_repo = getattr(args, "target_media_repo", None) or os.environ.get(
        "OPF_MEDIA_REPO", "mickey996icu/opf-media"
    )

    try:
        raw_draft = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to read input JSON {args.input}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(raw_draft, dict):
        print("Submission JSON root must be an object", file=sys.stderr)
        return 1

    pid_pre = str(raw_draft.get("id") or "")
    pid_errs = validate_product_id(pid_pre)
    if pid_errs:
        for e in pid_errs:
            print(f"ID error: {e}", file=sys.stderr)
        return 1
    rel_pdir_sub = product_dir_for_id(Path("."), pid_pre).as_posix().lstrip("./")
    sparse_prod_rel = f"products/{rel_pdir_sub}"

    with tempfile.TemporaryDirectory(prefix="opf-pr-") as tmp:
        tmp_path = Path(tmp)
        media_stage_root = (
            Path(media_repo_raw).resolve()
            if media_repo_raw
            else (tmp_path / "media-repo")
        )
        media_stage_root.mkdir(parents=True, exist_ok=True)
        (media_stage_root / "media").mkdir(parents=True, exist_ok=True)

        prep_path, staged_blobs, prep_errs = prepare_submission_inputs(
            Path(args.input),
            photo_specs=photo_specs,
            media_stage_root=media_stage_root,
            media_out_dir=None,
            media_stage_dir=Path(media_stage_raw) if media_stage_raw else None,
            vintage_month=vintage_month,
            contributor=getattr(args, "author", None),
            provenance=getattr(args, "provenance", None),
            agreement_ref=getattr(args, "agreement_ref", None),
            specimen_id=getattr(args, "specimen_id", None),
            temp_dir=tmp_path,
        )
        if prep_errs:
            for e in prep_errs:
                print(f"Media error: {e}", file=sys.stderr)
            return 1

        if staged_blobs:
            m_errs = validate_media_repo(media_stage_root)
            if m_errs:
                for e in m_errs:
                    print(f"Media validation failed: {e}", file=sys.stderr)
                return 1

        local_mode = bool(data_repo_raw)
        gh_user: str | None = None
        gh_err: str | None = None
        if not args.dry_run and not (local_mode and shutil.which("gh") is None):
            gh_user, gh_err = _gh_authenticated_user()

        if local_mode:
            data_repo = Path(data_repo_raw).resolve()
        else:
            data_repo = (tmp_path / "data-repo").resolve()
            if not args.dry_run and gh_user and not gh_err:
                _sparse_clone_repo(target_data_repo, data_repo, [f"/{sparse_prod_rel}"])
                (data_repo / "products").mkdir(parents=True, exist_ok=True)
            else:
                (data_repo / "products").mkdir(parents=True, exist_ok=True)
                _fetch_upstream_product_if_reachable(target_data_repo, rel_pdir_sub, data_repo / "products")

        products_dir = data_repo / "products"
        submit_ns = argparse.Namespace(
            input=str(prep_path),
            out_dir=str(products_dir),
            amend=getattr(args, "amend", None),
            supersede=getattr(args, "supersede", None),
            new_variant=getattr(args, "new_variant", False),
            track=getattr(args, "track", None),
            author=getattr(args, "author", None),
            provenance=getattr(args, "provenance", None),
            agreement_ref=getattr(args, "agreement_ref", None),
            reason=getattr(args, "reason", None),
            specimen_id=getattr(args, "specimen_id", None),
            quiet=True,
        )
        rc, summary = execute_submit(submit_ns)
        if rc != 0:
            return rc

        pid = summary["id"]
        ed_id = summary["edition_id"]
        pdir = Path(summary["product_dir"]).resolve()
        audit_findings = audit_products_root(
            pdir,
            media_root=media_stage_root if staged_blobs else None,
        )
        audit_errors = [f for f in audit_findings if f.severity == "ERROR"]
        audit_warns = [f for f in audit_findings if f.severity == "WARN"]
        if audit_errors:
            for f in audit_errors:
                print(f"Audit blocked PR: {f.format_line()}", file=sys.stderr)
            return 1
        if audit_warns and not getattr(args, "quiet", False):
            for f in audit_warns:
                print(f"Audit warning: {f.format_line()}", file=sys.stderr)
        ed_path = pdir / "editions" / f"{ed_id}.json"
        saved_ed = json.loads(ed_path.read_text(encoding="utf-8"))
        attrs = saved_ed["attributes"]
        brand = attrs["brand"]
        pname = attrs["product_name"][0]["text"]
        ev_level = derive_evidence_level(saved_ed)

        rel_pdir = pdir.relative_to(data_repo).as_posix()
        safe_slug = re.sub(r"[^a-z0-9]+", "-", f"{pid}-{ed_id}".lower()).strip("-")
        branch_name = f"contrib/{safe_slug}"
        commit_title = f"feat(product): {pid} ({ed_id}@rev{saved_ed['rev']}) - {brand} {pname}"
        media_commit_title = f"media(label): {pid} ({ed_id}) label WebP crops ({len(staged_blobs)} file(s))"

        def _build_data_body(media_url: str | None) -> str:
            callout = ""
            if staged_blobs:
                target_ref = media_url or "<MEDIA_PR_URL>"
                callout = (
                    "\n> [!IMPORTANT]\n"
                    f"> **Companion Media PR (MERGE FIRST)**: {target_ref}\n"
                    "> CI requires referenced label photos to exist on opf-media main before merging this PR.\n"
                )
            return (
                f"## Product Submission (v0.3)\n"
                f"{callout}\n"
                f"- **ID**: `{pid}`\n"
                f"- **Brand & Name**: {brand} — {pname}\n"
                f"- **Edition**: `{ed_id}` (`rev {saved_ed['rev']}`, track `{saved_ed['track']}`, `{ev_level}`)\n"
                f"- **Action**: `{summary['action']}`\n"
                f"- **Product Dir**: `{rel_pdir}`\n\n"
                f"Validated locally via `opf validate` (Schema v0.3 + GS1 + Span-Free Ingredient Round-Trip + Patch Replay).\n"
            )

        def _build_media_body(data_url: str | None, *, pending_text: str = "<DATA_PR_URL>") -> str:
            target_ref = data_url or pending_text
            blob_lines = "\n".join(f"  - `{b['rel_path']}` (`opf-media://sha256/{b['sha256']}`)" for b in staged_blobs)
            return (
                "## Label Evidence Media (WebP <= 1000px, EXIF-Free)\n\n"
                "> Merge this `opf-media` PR **FIRST** so `opf-data` CI `check-media-refs` passes.\n\n"
                f"- **Companion Data PR (merge second)**: {target_ref}\n"
                f"- **Product**: `{pid}` — {brand} {pname} (`{ed_id}`)\n"
                f"- **Media Blobs ({len(staged_blobs)})**:\n{blob_lines}\n\n"
                "Validated locally via `opf validate-media` (SHA-256 content-addressed paths, <=1000px, zero EXIF/XMP chunks).\n"
            )

        pr_body = _build_data_body(None)
        data_cmds = [
            f"git -C {data_repo} checkout -B {branch_name}",
            f"git -C {data_repo} add {rel_pdir}",
            f"git -C {data_repo} commit -s -m {json.dumps(commit_title, ensure_ascii=False)}",
            f"git -C {data_repo} push -u origin {branch_name}",
            f"gh pr create --repo {target_data_repo} --title {json.dumps(commit_title, ensure_ascii=False)} --body-file -",
        ]

        plan: dict[str, Any] = {
            "mode": "local" if local_mode else "remote_fork",
            "target_data_repo": target_data_repo,
            "target_media_repo": target_media_repo,
            "merge_order": ["opf-media", "opf-data"] if staged_blobs else ["opf-data"],
            "branch": branch_name,
            "data_repo": str(data_repo),
            "product_dir": rel_pdir,
            "action": summary["action"],
            "edition_id": ed_id,
            "rev": saved_ed["rev"],
            "commit_title": commit_title,
            "pr_body": pr_body,
            "staged_media": staged_blobs,
            "data_pr_plan": {
                "repo": target_data_repo,
                "branch": branch_name,
                "files": [rel_pdir],
                "commit_title": commit_title,
                "pr_body": pr_body,
                "commands": data_cmds,
            },
            "commands": data_cmds,
        }
        if staged_blobs:
            media_cmds = [
                f"git -C {media_stage_root} checkout -B {branch_name}",
                f"git -C {media_stage_root} add " + " ".join(b["rel_path"] for b in staged_blobs),
                f"git -C {media_stage_root} commit -s -m {json.dumps(media_commit_title, ensure_ascii=False)}",
                f"git -C {media_stage_root} push -u origin {branch_name}",
                f"gh pr create --repo {target_media_repo} --title {json.dumps(media_commit_title, ensure_ascii=False)} --body-file -",
            ]
            plan["media_pr_plan"] = {
                "repo": target_media_repo,
                "branch": branch_name,
                "files": [b["rel_path"] for b in staged_blobs],
                "commit_title": media_commit_title,
                "pr_body": _build_media_body(None),
                "commands": media_cmds,
            }

        if args.dry_run:
            if not getattr(args, "quiet", False):
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0

        if local_mode and shutil.which("gh") is None:
            plan["note"] = "gh CLI not found in PATH; outputting prepared git/gh commands."
            if not getattr(args, "quiet", False):
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0

        if gh_err or not gh_user:
            print(f"GitHub PR submission blocked: {gh_err}", file=sys.stderr)
            if not getattr(args, "quiet", False):
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 1

        if local_mode:
            media_pr_url: str | None = None
            if staged_blobs and media_repo_raw:
                m_repo = Path(media_repo_raw).resolve()
                _ensure_git_identity(m_repo, gh_user)
                subprocess.run(["git", "-C", str(m_repo), "checkout", "-B", branch_name], check=True)
                subprocess.run(
                    ["git", "-C", str(m_repo), "add", *[b["rel_path"] for b in staged_blobs]],
                    check=True,
                )
                subprocess.run(["git", "-C", str(m_repo), "commit", "-s", "-m", media_commit_title], check=True)
                subprocess.run(["git", "-C", str(m_repo), "push", "-u", "origin", branch_name], check=True)
                m_res = subprocess.run(
                    ["gh", "pr", "create", "--repo", target_media_repo, "--title", media_commit_title, "--body-file", "-"],
                    input=_build_media_body(
                        None,
                        pending_text="Linking companion opf-data PR automatically...",
                    ).encode("utf-8"),
                    cwd=str(m_repo),
                    capture_output=True,
                    check=True,
                )
                media_pr_url = m_res.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]

            _ensure_git_identity(data_repo, gh_user)
            final_data_body = _build_data_body(media_pr_url)
            subprocess.run(["git", "-C", str(data_repo), "checkout", "-B", branch_name], check=True)
            subprocess.run(["git", "-C", str(data_repo), "add", rel_pdir], check=True)
            subprocess.run(["git", "-C", str(data_repo), "commit", "-s", "-m", commit_title], check=True)
            subprocess.run(["git", "-C", str(data_repo), "push", "-u", "origin", branch_name], check=True)
            d_res = subprocess.run(
                ["gh", "pr", "create", "--title", commit_title, "--body-file", "-"],
                input=final_data_body.encode("utf-8"),
                cwd=str(data_repo),
                capture_output=True,
                check=True,
            )
            data_pr_url = d_res.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]
            if media_pr_url:
                subprocess.run(
                    ["gh", "pr", "edit", media_pr_url, "--body-file", "-"],
                    input=_build_media_body(data_pr_url).encode("utf-8"),
                    check=True,
                )
            if not getattr(args, "quiet", False):
                print(
                    json.dumps(
                        {
                            "status": "created",
                            "mode": "local",
                            "merge_order": ["opf-media", "opf-data"] if media_pr_url else ["opf-data"],
                            "media_pr_url": media_pr_url,
                            "data_pr_url": data_pr_url,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 0

        media_pr_url = None
        new_blobs: list[dict[str, Any]] = []
        if staged_blobs:
            raw_media_base = f"https://raw.githubusercontent.com/{target_media_repo}/main"
            for blob in staged_blobs:
                exists_remote, _ = check_media_blob_http(raw_media_base, blob["sha256"])
                if not exists_remote:
                    new_blobs.append(blob)

        if new_blobs:
            live_media_dir = Path(media_repo_raw).resolve() if media_repo_raw else (tmp_path / "live-media-repo")
            if not media_repo_raw:
                _sparse_clone_repo(
                    target_media_repo,
                    live_media_dir,
                    ["/LICENSE", "/media/.gitkeep", *(f"/{b['rel_path']}" for b in new_blobs)],
                )
                for blob in new_blobs:
                    dst_blob = live_media_dir / blob["rel_path"]
                    dst_blob.parent.mkdir(parents=True, exist_ok=True)
                    dst_blob.write_bytes(Path(blob["abs_path"]).read_bytes())
            m_live_errs = validate_media_repo(live_media_dir)
            if m_live_errs:
                for e in m_live_errs:
                    print(f"Media validation failed: {e}", file=sys.stderr)
                return 1
            m_owner = target_media_repo.split("/", 1)[0]
            m_push_url = _gh_fork_clone_url(target_media_repo, gh_user)
            m_head = f"{gh_user}:{branch_name}" if gh_user != m_owner else branch_name
            _ensure_git_identity(live_media_dir, gh_user)
            subprocess.run(["git", "-C", str(live_media_dir), "checkout", "-B", branch_name], check=True)
            subprocess.run(
                ["git", "-C", str(live_media_dir), "add", "--sparse", *[b["rel_path"] for b in new_blobs]],
                check=True,
            )
            subprocess.run(["git", "-C", str(live_media_dir), "commit", "-s", "-m", media_commit_title], check=True)
            _set_git_remote(live_media_dir, "fork", m_push_url)
            subprocess.run(
                ["git", "-C", str(live_media_dir), "push", "-f", "-u", "fork", branch_name],
                check=True,
            )
            m_res = subprocess.run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    target_media_repo,
                    "--head",
                    m_head,
                    "--title",
                    media_commit_title,
                    "--body-file",
                    "-",
                ],
                input=_build_media_body(
                    None,
                    pending_text="Linking companion opf-data PR automatically...",
                ).encode("utf-8"),
                cwd=str(live_media_dir),
                capture_output=True,
                check=True,
            )
            media_pr_url = m_res.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]

        d_owner = target_data_repo.split("/", 1)[0]
        d_push_url = _gh_fork_clone_url(target_data_repo, gh_user)
        d_head = f"{gh_user}:{branch_name}" if gh_user != d_owner else branch_name
        _ensure_git_identity(data_repo, gh_user)
        subprocess.run(["git", "-C", str(data_repo), "checkout", "-B", branch_name], check=True)
        subprocess.run(["git", "-C", str(data_repo), "add", "--sparse", sparse_prod_rel], check=True)
        subprocess.run(["git", "-C", str(data_repo), "commit", "-s", "-m", commit_title], check=True)
        _set_git_remote(data_repo, "fork", d_push_url)
        subprocess.run(["git", "-C", str(data_repo), "push", "-f", "-u", "fork", branch_name], check=True)
        d_res = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                target_data_repo,
                "--head",
                d_head,
                "--title",
                commit_title,
                "--body-file",
                "-",
            ],
            input=_build_data_body(media_pr_url).encode("utf-8"),
            cwd=str(data_repo),
            capture_output=True,
            check=True,
        )
        data_pr_url = d_res.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]
        if media_pr_url:
            subprocess.run(
                ["gh", "pr", "edit", media_pr_url, "--body-file", "-"],
                input=_build_media_body(data_pr_url).encode("utf-8"),
                check=True,
            )

        if not getattr(args, "quiet", False):
            print(
                json.dumps(
                    {
                        "status": "created",
                        "mode": "remote_fork",
                        "merge_order": ["opf-media", "opf-data"] if media_pr_url else ["opf-data"],
                        "media_pr_url": media_pr_url,
                        "data_pr_url": data_pr_url,
                        "edition_id": ed_id,
                        "rev": saved_ed["rev"],
                        "branch": branch_name,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0


def register_pr_subparser(sub: argparse._SubParsersAction) -> None:
    p_pr = sub.add_parser(
        "pr",
        help="Submit product + cropped label WebPs, auto-fork if needed, and open cross-linked opf-media/opf-data PRs",
    )
    p_pr.add_argument("--input", required=True, help="Path to draft JSON")
    p_pr.add_argument("--data-repo", help="Optional path to local opf-data git clone (omit for remote sparse/fork mode)")
    p_pr.add_argument("--media-repo", help="Optional path to local opf-media git clone")
    p_pr.add_argument(
        "--target-data-repo",
        default=os.environ.get("OPF_DATA_REPO", "mickey996icu/opf-data"),
        help="Target GitHub data repo '<namespace>/<repo>'",
    )
    p_pr.add_argument(
        "--target-media-repo",
        default=os.environ.get("OPF_MEDIA_REPO", "mickey996icu/opf-media"),
        help="Target GitHub media repo '<namespace>/<repo>'",
    )
    p_pr.add_argument("--amend", help="Forward --amend to submit")
    p_pr.add_argument("--supersede", action="extend", nargs="+", help="Forward --supersede to submit")
    p_pr.add_argument("--new-variant", action="store_true", help="Forward --new-variant to submit")
    p_pr.add_argument("--track", help="Forward --track to submit")
    p_pr.add_argument("--author", help="Forward --author to submit")
    p_pr.add_argument(
        "--provenance",
        choices=VALID_PROVENANCES,
        help="Forward --provenance to submit",
    )
    p_pr.add_argument(
        "--agreement-ref",
        help="Forward --agreement-ref to submit",
    )
    p_pr.add_argument("--reason", help="Forward --reason to submit")
    p_pr.add_argument("--specimen-id", help="Forward --specimen-id to submit")
    p_pr.add_argument("--vintage-month", help="Coarse YYYY-MM production month attached to label photos")
    p_pr.add_argument(
        "--photo",
        action="append",
        help="Cropped label photo '<region>=<path>' (repeatable; transcodes to <=1000px EXIF-free WebP)",
    )
    p_pr.add_argument("--media-stage-dir", help="Optional directory containing pre-sanitized WebP files")
    p_pr.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and stage locally without committing, pushing, or invoking gh",
    )
    p_pr.add_argument("--quiet", action="store_true", help="Suppress JSON status output")
    p_pr.set_defaults(func=cmd_pr)
