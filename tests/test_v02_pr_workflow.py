"""Tests for dual-repository `opf pr` planning, remote sparse-clone/fork workflow, and conflict safety."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import opf.cli_pr as opf_cli_pr
from opf.cli import main as cli_main
from opf.pr_check import validate_pr_metadata
from tests.test_v02_workflow import _create_rotated_jpeg_with_exif, _make_sample_draft

HAS_PILLOW = importlib.util.find_spec("PIL") is not None


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = cli_main(argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


class TestDualRepoPrWorkflow(unittest.TestCase):
    @unittest.skipUnless(HAS_PILLOW, "Pillow not installed; skipping WebP/media transcoding test")
    def test_pr_dry_run_remote_fork_mode_with_photos_emits_cross_linked_dual_plans(self) -> None:
        """`opf pr --dry-run --photo ...` works without pre-existing --data-repo and links both PRs."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            p_nutri = tmp_path / "nutri.jpg"
            p_ing = tmp_path / "ing.jpg"
            _create_rotated_jpeg_with_exif(p_nutri, width=1400, height=1000)
            _create_rotated_jpeg_with_exif(p_ing, width=900, height=700)

            draft_path = tmp_path / "draft.json"
            draft_path.write_text(json.dumps(_make_sample_draft(), ensure_ascii=False), encoding="utf-8")

            old_flag = os.environ.get("OPF_PR_DRY_RUN_OFFLINE")
            os.environ["OPF_PR_DRY_RUN_OFFLINE"] = "1"
            try:
                rc, out, err = _run_cli(
                    [
                        "pr",
                        "--input",
                        str(draft_path),
                        "--photo",
                        f"nutrition_table={p_nutri}",
                        "--photo",
                        f"ingredients_box={p_ing}",
                        "--vintage-month",
                        "2026-08",
                        "--author",
                        "github:alice",
                        "--dry-run",
                    ]
                )
            finally:
                if old_flag is None:
                    os.environ.pop("OPF_PR_DRY_RUN_OFFLINE", None)
                else:
                    os.environ["OPF_PR_DRY_RUN_OFFLINE"] = old_flag

            self.assertEqual(rc, 0, err)
            plan = json.loads(out)
            self.assertEqual(plan["mode"], "remote_fork")
            self.assertEqual(plan["merge_order"], ["opf-media", "opf-data"])
            self.assertEqual(len(plan["staged_media"]), 2)
            self.assertIn("media_pr_plan", plan)
            self.assertIn("data_pr_plan", plan)
            self.assertIn("Companion Media PR (MERGE FIRST)", plan["data_pr_plan"]["pr_body"])
            self.assertIn("Companion Data PR (merge second)", plan["media_pr_plan"]["pr_body"])

    @unittest.skipUnless(HAS_PILLOW, "Pillow not installed; skipping WebP/media transcoding test")
    def test_pr_remote_fork_live_single_submit_ulid_consistency_and_conflict_abort(self) -> None:
        """Remote Fork live mode runs execute_submit strictly once, aligns ULIDs across PRs, and aborts before Media PR on conflict."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            def _init_seed_and_bare(name: str, files: dict[str, str]) -> tuple[Path, Path]:
                bare = (tmp_path / f"{name}.git").resolve()
                fork_bare = (tmp_path / f"fork_{name}.git").resolve()
                seed = (tmp_path / f"seed_{name}").resolve()
                subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
                subprocess.run(["git", "init", "--bare", "-b", "main", str(fork_bare)], check=True, capture_output=True)
                subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(seed), "config", "user.name", "tester"], check=True)
                subprocess.run(["git", "-C", str(seed), "config", "user.email", "tester@example.org"], check=True)
                for rel_p, content in files.items():
                    fp = seed / rel_p
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_text(content, encoding="utf-8")
                subprocess.run(["git", "-C", str(seed), "add", "-A"], check=True)
                subprocess.run(["git", "-C", str(seed), "commit", "-m", "init"], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(seed), "push", f"file://{bare}", "main"], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(seed), "push", f"file://{fork_bare}", "main"], check=True, capture_output=True)
                return bare, fork_bare

            up_data_bare, fork_data_bare = _init_seed_and_bare("opf-data", {"README.md": "# data\n"})
            up_media_bare, fork_media_bare = _init_seed_and_bare(
                "opf-media", {"LICENSE": "CC-BY-SA-4.0\n", "media/.gitkeep": ""}
            )

            src_jpg = tmp_path / "nutri.jpg"
            _create_rotated_jpeg_with_exif(src_jpg, width=1200, height=900)
            draft1 = _make_sample_draft()
            draft1["attributes"]["product_standard"] = ["GB/T 21733"]
            draft_path = tmp_path / "draft.json"
            draft_path.write_text(json.dumps(draft1, ensure_ascii=False), encoding="utf-8")

            submit_calls: list[dict] = []
            orig_execute_submit = opf_cli_pr.execute_submit
            orig_subprocess_run = subprocess.run
            gh_actions: list[dict] = []

            def _wrapped_execute_submit(ns):
                rc, summary = orig_execute_submit(ns)
                submit_calls.append({"rc": rc, "edition_id": summary.get("edition_id")})
                return rc, summary

            def _fake_sparse_clone(repo_slug: str, dest_dir: Path, sparse_paths: list[str]) -> None:
                upstream_bare = up_media_bare if "opf-media" in repo_slug else up_data_bare
                orig_subprocess_run(
                    [
                        "git",
                        "clone",
                        "--depth",
                        "1",
                        "--filter=blob:none",
                        "--no-checkout",
                        f"file://{upstream_bare}",
                        str(dest_dir),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                orig_subprocess_run(
                    ["git", "-C", str(dest_dir), "sparse-checkout", "init", "--no-cone"],
                    check=True,
                    capture_output=True,
                )
                if sparse_paths:
                    orig_subprocess_run(
                        ["git", "-C", str(dest_dir), "sparse-checkout", "set", *sparse_paths],
                        check=True,
                        capture_output=True,
                    )
                orig_subprocess_run(["git", "-C", str(dest_dir), "checkout"], check=True, capture_output=True)

            def _fake_fork_url(repo_slug: str, gh_user: str) -> str:
                fork_bare = fork_media_bare if "opf-media" in repo_slug else fork_data_bare
                return f"file://{fork_bare}"

            def _intercept_subprocess_run(cmd, *args, **kwargs):
                if isinstance(cmd, (list, tuple)) and len(cmd) >= 3 and cmd[0] == "gh" and cmd[1] == "pr":
                    body_bytes = kwargs.get("input") or b""
                    body_str = body_bytes.decode("utf-8", errors="replace") if isinstance(body_bytes, bytes) else str(body_bytes)
                    if cmd[2] == "create":
                        repo_arg = cmd[cmd.index("--repo") + 1]
                        title_arg = cmd[cmd.index("--title") + 1]
                        pr_num = 101 if "opf-media" in repo_arg else 202
                        url = f"https://github.com/{repo_arg}/pull/{pr_num}"
                        gh_actions.append({"op": "create", "repo": repo_arg, "title": title_arg, "body": body_str, "url": url})
                        return subprocess.CompletedProcess(cmd, 0, stdout=(url + "\n").encode("utf-8"), stderr=b"")
                    if cmd[2] == "edit":
                        pr_target = cmd[3]
                        gh_actions.append({"op": "edit", "target": pr_target, "body": body_str})
                        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
                return orig_subprocess_run(cmd, *args, **kwargs)

            with (
                mock.patch.object(opf_cli_pr, "_gh_authenticated_user", return_value=("alice", None)),
                mock.patch.object(opf_cli_pr, "_sparse_clone_repo", side_effect=_fake_sparse_clone),
                mock.patch.object(opf_cli_pr, "_gh_fork_clone_url", side_effect=_fake_fork_url),
                mock.patch.object(opf_cli_pr, "check_media_blob_http", return_value=(False, "HTTP 404")),
                mock.patch.object(opf_cli_pr, "execute_submit", side_effect=_wrapped_execute_submit),
                mock.patch.object(opf_cli_pr.subprocess, "run", side_effect=_intercept_subprocess_run),
            ):
                rc1, out1, err1 = _run_cli(
                    [
                        "pr",
                        "--input",
                        str(draft_path),
                        "--photo",
                        f"nutrition_table={src_jpg}",
                        "--vintage-month",
                        "2026-08",
                        "--author",
                        "github:alice",
                    ]
                )
                self.assertEqual(rc1, 0, err1)
                self.assertEqual(len(submit_calls), 1, "Expected single execute_submit call")
                res1 = json.loads(out1)
                ed_id = res1["edition_id"]
                self.assertEqual(ed_id, submit_calls[0]["edition_id"])
                self.assertEqual(res1["merge_order"], ["opf-media", "opf-data"])

                ls_data = orig_subprocess_run(
                    ["git", "--git-dir", str(fork_data_bare), "ls-tree", "-r", "--name-only", res1["branch"]],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                self.assertIn(f"/editions/{ed_id}.json", ls_data)

                self.assertEqual([a["op"] for a in gh_actions], ["create", "create", "edit"])
                media_create, data_create, media_edit = gh_actions
                self.assertIn(ed_id, media_create["title"])
                self.assertIn(ed_id, media_create["body"])
                self.assertIn(ed_id, data_create["title"])
                self.assertIn(ed_id, data_create["body"])
                self.assertIn("**Companion Media PR (MERGE FIRST)**: https://github.com/mickey996icu/opf-media/pull/101", data_create["body"])
                self.assertIn("**Companion Data PR (merge second)**: https://github.com/mickey996icu/opf-data/pull/202", media_edit["body"])
                self.assertEqual(
                    validate_pr_metadata(repo_kind="media", title=media_create["title"], body=media_create["body"]),
                    [],
                )
                self.assertEqual(
                    validate_pr_metadata(repo_kind="media", title=media_create["title"], body=media_edit["body"]),
                    [],
                )
                self.assertEqual(
                    validate_pr_metadata(
                        repo_kind="data",
                        title=data_create["title"],
                        body=data_create["body"],
                        require_companion_media_pr=True,
                    ),
                    [],
                )

                orig_subprocess_run(
                    ["git", "--git-dir", str(fork_data_bare), "push", f"file://{up_data_bare}", f"{res1['branch']}:main"],
                    check=True,
                    capture_output=True,
                )
                media_refs_before = orig_subprocess_run(
                    ["git", "--git-dir", str(fork_media_bare), "show-ref"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout

                conflict_draft = _make_sample_draft()
                conflict_draft["attributes"]["product_standard"] = ["GB/T 99999"]
                conflict_path = tmp_path / "conflict_draft.json"
                conflict_path.write_text(json.dumps(conflict_draft, ensure_ascii=False), encoding="utf-8")

                other_jpg = tmp_path / "nutri_conflict.jpg"
                _create_rotated_jpeg_with_exif(other_jpg, width=640, height=480)
                gh_actions.clear()

                rc2, _, err2 = _run_cli(
                    [
                        "pr",
                        "--input",
                        str(conflict_path),
                        "--photo",
                        f"nutrition_table={other_jpg}",
                        "--vintage-month",
                        "2026-08",
                    ]
                )
                self.assertEqual(rc2, 1)
                self.assertIn("Attribute conflict against existing edition", err2)
                self.assertEqual(gh_actions, [], "Conflict must abort before opening any PR")
                media_refs_after = orig_subprocess_run(
                    ["git", "--git-dir", str(fork_media_bare), "show-ref"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                self.assertEqual(media_refs_before, media_refs_after, "Conflict must not push orphan branch to opf-media")


if __name__ == "__main__":
    unittest.main()
