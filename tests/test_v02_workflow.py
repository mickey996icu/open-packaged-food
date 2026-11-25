"""Tests for v0.2 Phase 1 workflow: wheel resource bundling, WebP transcoding, validate-media, check-media-refs, and dual-PR planning."""

from __future__ import annotations

import contextlib
import functools
import hashlib
import http.server
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

HAS_PILLOW = importlib.util.find_spec("PIL") is not None

import opf.cli as opf_cli
from opf.builder import build_static_api
from opf.cli import check_media_refs, main as cli_main
from opf.media import (
    CANONICAL_EVIDENCE_REGIONS,
    FRONT_COVER_ERROR_MESSAGE,
    inspect_webp_bytes,
    normalize_evidence_region,
    process_cropped_label_to_webp,
    validate_media_repo,
)
from opf.normalize import normalize_edition
from opf.pr_check import validate_pr_metadata
from opf.resources import REPO_ROOT
from opf.validator import (
    load_json_schema,
    validate_against_json_schema,
    validate_products_root,
)


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = cli_main(argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


def _make_sample_draft() -> dict:
    return {
        "id": "gtin:00000000000017",
        "core": {
            "regulatory_profile": "CN/GB28050-2011",
            "net_content": [{"value": "500", "unit": "ml"}],
            "nutrition_declared": {
                "basis": {"value": "100", "unit": "ml"},
                "rows": [
                    {"nutrient": "energy", "value": "0", "unit": "kJ", "nrv_pct": "0"},
                    {"nutrient": "protein", "value": "0", "unit": "g", "nrv_pct": "0"},
                    {"nutrient": "fat_total", "value": "0", "unit": "g", "nrv_pct": "0"},
                    {"nutrient": "carbs_available", "value": "0", "unit": "g", "nrv_pct": "0"},
                    {"nutrient": "sodium", "value": "0", "unit": "mg", "nrv_pct": "0"},
                ],
            },
        },
        "attributes": {
            "product_name": [{"lang": "zh-Hans", "text": "无糖茉莉清茶"}],
            "brand": "示例茶坊",
            "ingredients_text": [
                {"lang": "zh-Hans", "text": "水、茉莉花茶（绿茶茶坯）、维生素C、碳酸氢钠"}
            ],
            "parties": [
                {"role": "commissioner", "name": "示例茶坊饮品有限公司"},
                {
                    "role": "manufacturer",
                    "name": "示例饮品测试厂",
                    "license": "SC10600000000001",
                },
            ],
            "translations": [
                {
                    "lang": "en",
                    "field": "brand",
                    "text": "Demo Tea Lab",
                    "source": "contributor_translated",
                    "contributor": "github:alice",
                }
            ],
        },
        "evidence": [],
    }


def _create_rotated_jpeg_with_exif(dest: Path, width: int = 1600, height: int = 1200) -> None:
    from PIL import Image

    img = Image.new("RGB", (width, height), (210, 220, 235))
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation = 6 (90 deg CW -> transposed portrait 1200x1600 -> 750x1000)
    exif[0x010F] = "SampleCamera"
    img.save(dest, format="JPEG", quality=92, exif=exif.tobytes())


class TestPhase1WorkflowV02(unittest.TestCase):
    def test_pure_stdlib_ci_paths_do_not_import_pillow(self) -> None:
        """Importing core validation/normalization/build/media-check modules never imports PIL."""
        code = (
            "import sys, opf.cli, opf.validator, opf.normalize, opf.builder, opf.media; "
            "assert 'PIL' not in sys.modules, f'Unexpected PIL import: {list(sys.modules.keys())}'"
        )
        res = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, res.stderr or res.stdout)

    def test_wheel_bundled_resources_outside_repo_checkout(self) -> None:
        """Packaged `_bundled` resources resolve cleanly when opf is imported outside source checkout."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            site_pkgs = tmp_path / "site_pkgs"
            pkg_dir = site_pkgs / "opf"
            shutil.copytree(
                REPO_ROOT / "opf",
                pkg_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "_bundled"),
            )
            bundled = pkg_dir / "_bundled"
            for rel in ("dictionaries", "profiles", "spec/schema", "web"):
                shutil.copytree(
                    REPO_ROOT / rel,
                    bundled / rel,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )

            draft_path = tmp_path / "draft.json"
            draft_path.write_text(
                json.dumps(
                    {
                        **_make_sample_draft(),
                        "evidence": [
                            {
                                "type": "community_report",
                                "contributor": "github:tester",
                                "reported_at": "2026-09-01",
                                "vintage_month": "2026-08",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            products_dir = tmp_path / "products"
            site_out = tmp_path / "site_out"

            env = {**os.environ, "PYTHONPATH": str(site_pkgs)}
            script = (
                "import pathlib; "
                "from opf.resources import get_resource_root; "
                "from opf.registries import load_nutrients_dict, load_all_profiles; "
                "from opf.validator import load_json_schema; "
                "from opf.cli import main; "
                "from opf.builder import build_static_api; "
                "r = get_resource_root(); "
                f"assert r == pathlib.Path({str(bundled.resolve())!r}), f'got {{r}}'; "
                "assert 'sodium' in load_nutrients_dict(); "
                "assert 'CN/GB28050-2011' in load_all_profiles(); "
                "assert load_json_schema('edition.v0.2.schema.json')['$id']; "
                f"assert main(['submit', '--quiet', '--input', {str(draft_path)!r}, '--out-dir', {str(products_dir)!r}]) == 0; "
                f"assert main(['validate', {str(products_dir)!r}]) == 0; "
                f"meta = build_static_api(pathlib.Path({str(products_dir)!r}), pathlib.Path({str(site_out)!r})); "
                "assert meta['total_products'] == 1"
            )
            res = subprocess.run(
                [sys.executable, "-c", script],
                cwd="/tmp",
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, res.stderr or res.stdout)
            self.assertTrue((site_out / "index.html").is_file())
            self.assertTrue((site_out / "v1" / "meta.json").is_file())
            for loc in ("index.json", "zh-CN.json", "en.json", "ja.json", "de.json", "fr.json", "es.json", "it.json"):
                self.assertTrue((site_out / "locales" / loc).is_file(), f"Missing bundled locale {loc}")

    @unittest.skipUnless(HAS_PILLOW, "Pillow not installed; skipping WebP/media transcoding test")
    def test_webp_transcode_orientation_strip_and_validate_media_repo(self) -> None:
        """Cropped JPEG with EXIF orientation is transposed, downscaled <=1000px, stripped to WebP, and validated."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_jpg = tmp_path / "crop_nutrition.jpg"
            _create_rotated_jpeg_with_exif(src_jpg, width=1600, height=1200)

            media_repo = tmp_path / "opf-media"
            rep = process_cropped_label_to_webp(src_jpg, media_root=media_repo, max_edge=1000, quality=80)

            out_webp = Path(rep["output"])
            self.assertTrue(out_webp.is_file())
            self.assertEqual(rep["width"], 750)
            self.assertEqual(rep["height"], 1000)
            self.assertTrue(rep["media_ref"].startswith("opf-media://sha256/"))
            h = rep["sha256"]
            self.assertEqual(rep["rel_path"], f"media/{h[0:2]}/{h[2:4]}/{h}.webp")

            raw = out_webp.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), h)
            info = inspect_webp_bytes(raw)
            self.assertEqual((info["width"], info["height"]), (750, 1000))
            self.assertEqual(info["metadata_chunks"], [])
            self.assertEqual(validate_media_repo(media_repo), [])

            rc_ok, out_ok, err_ok = _run_cli(["validate-media", str(media_repo)])
            self.assertEqual(rc_ok, 0, err_ok)
            self.assertIn("OK", out_ok)

            # Negative 1: stray non-content-addressed file
            stray = media_repo / "media" / "stray.png"
            stray.write_bytes(b"not-valid")
            self.assertTrue(any("Invalid media path" in e for e in validate_media_repo(media_repo)))
            stray.unlink()

            # Negative 2: corrupted SHA-256 bytes
            orig_bytes = out_webp.read_bytes()
            out_webp.write_bytes(orig_bytes + b"\x01\x02")
            self.assertTrue(any("SHA-256 mismatch" in e for e in validate_media_repo(media_repo)))
            out_webp.write_bytes(orig_bytes)

            # Negative 3: oversized WebP (>1000px) fails validate_media_repo
            from PIL import Image

            big_buf = io.BytesIO()
            Image.new("RGB", (1200, 1000), (10, 20, 30)).save(big_buf, format="WEBP", quality=75)
            big_bytes = big_buf.getvalue()
            big_sha = hashlib.sha256(big_bytes).hexdigest()
            big_path = media_repo / "media" / big_sha[0:2] / big_sha[2:4] / f"{big_sha}.webp"
            big_path.parent.mkdir(parents=True, exist_ok=True)
            big_path.write_bytes(big_bytes)
            errs_big = validate_media_repo(media_repo, max_edge=1000)
            self.assertTrue(any("exceed max edge 1000px" in e for e in errs_big), errs_big)

    @unittest.skipUnless(HAS_PILLOW, "Pillow not installed; skipping WebP/media transcoding test")
    def test_check_media_refs_ci_gate_local_and_http(self) -> None:
        """check-media-refs blocks missing opf-media:// refs and succeeds once present on opf-media."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_dir = tmp_path / "products"
            media_dir = tmp_path / "opf-media"
            (media_dir / "media").mkdir(parents=True)

            # 0 refs passes immediately
            rc_zero, out_zero, _ = _run_cli(["check-media-refs", str(products_dir)])
            self.assertEqual(rc_zero, 0)
            self.assertIn("0 opf-media references", out_zero)

            src_jpg = tmp_path / "crop.jpg"
            _create_rotated_jpeg_with_exif(src_jpg, width=800, height=600)
            draft_path = tmp_path / "draft.json"
            draft_path.write_text(json.dumps(_make_sample_draft(), ensure_ascii=False), encoding="utf-8")

            stage_dir = tmp_path / "staged_media"
            rc_sub, out_sub, err_sub = _run_cli(
                [
                    "submit",
                    "--input",
                    str(draft_path),
                    "--out-dir",
                    str(products_dir),
                    "--photo",
                    f"nutrition_table={src_jpg}",
                    "--media-out-dir",
                    str(stage_dir),
                    "--vintage-month",
                    "2026-08",
                ]
            )
            self.assertEqual(rc_sub, 0, err_sub)
            staged_info = json.loads(out_sub)["staged_media"][0]

            # Missing in media_dir -> exit 1 with merge-order error
            rc_miss, _, err_miss = _run_cli(
                ["check-media-refs", "--media-dir", str(media_dir), str(products_dir)]
            )
            self.assertEqual(rc_miss, 1)
            self.assertIn("MISSING_MEDIA:", err_miss)
            self.assertIn("Merge the companion opf-media PR FIRST", err_miss)

            # --warn-only still succeeds
            rc_warn, _, err_warn = _run_cli(
                ["check-media-refs", "--warn-only", "--media-dir", str(media_dir), str(products_dir)]
            )
            self.assertEqual(rc_warn, 0)
            self.assertIn("MISSING_MEDIA:", err_warn)

            # Start local HTTP server backed by media_dir -> HTTP 404 before copy
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(media_dir))
            httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                base_url = f"http://127.0.0.1:{port}"
                rc_http_404, _, _ = _run_cli(
                    ["check-media-refs", "--media-base-url", base_url, str(products_dir)]
                )
                self.assertEqual(rc_http_404, 1)

                # Populate blob into media_dir -> both --media-dir and HTTP check pass
                dest_blob = media_dir / staged_info["rel_path"]
                dest_blob.parent.mkdir(parents=True, exist_ok=True)
                dest_blob.write_bytes(Path(staged_info["abs_path"]).read_bytes())

                rc_local_ok, out_local_ok, err_local_ok = _run_cli(
                    ["check-media-refs", "--media-dir", str(media_dir), str(products_dir)]
                )
                self.assertEqual(rc_local_ok, 0, err_local_ok)
                self.assertIn("1 opf-media reference(s) verified", out_local_ok)

                rc_http_ok, out_http_ok, err_http_ok = _run_cli(
                    ["check-media-refs", "--media-base-url", base_url, str(products_dir)]
                )
                self.assertEqual(rc_http_ok, 0, err_http_ok)
                self.assertIn("1 opf-media reference(s) verified", out_http_ok)
            finally:
                httpd.shutdown()
                httpd.server_close()

            # Direct Python API smoke check
            rc_py, rep_py = check_media_refs([products_dir], media_dir=media_dir)
            self.assertEqual(rc_py, 0)
            self.assertEqual(rep_py["status"], "ok")

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
        """Remote Fork live mode runs _execute_submit strictly once, aligns ULIDs across PRs, and aborts before Media PR on conflict."""
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
            orig_execute_submit = opf_cli._execute_submit
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
                mock.patch.object(opf_cli, "_gh_authenticated_user", return_value=("alice", None)),
                mock.patch.object(opf_cli, "_sparse_clone_repo", side_effect=_fake_sparse_clone),
                mock.patch.object(opf_cli, "_gh_fork_clone_url", side_effect=_fake_fork_url),
                mock.patch.object(opf_cli, "_check_media_blob_http", return_value=(False, "HTTP 404")),
                mock.patch.object(opf_cli, "_execute_submit", side_effect=_wrapped_execute_submit),
                mock.patch.object(opf_cli.subprocess, "run", side_effect=_intercept_subprocess_run),
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
                self.assertEqual(len(submit_calls), 1, "Expected single _execute_submit call")
                res1 = json.loads(out1)
                ed_id = res1["edition_id"]
                self.assertEqual(ed_id, submit_calls[0]["edition_id"])
                self.assertEqual(res1["merge_order"], ["opf-media", "opf-data"])

                # Verify fork_data.git actually holds the identical ULID on the PR branch
                ls_data = orig_subprocess_run(
                    ["git", "--git-dir", str(fork_data_bare), "ls-tree", "-r", "--name-only", res1["branch"]],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                self.assertIn(f"/editions/{ed_id}.json", ls_data)

                # Verify both PR creations & cross-link edit share the exact same ed_id
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

                # Now promote the submitted product onto upstream_data main, and submit a conflicting attribute
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

    @unittest.skipUnless(HAS_PILLOW, "Pillow not installed; skipping WebP/media transcoding test")
    def test_check_media_refs_only_refs_from_git_diff(self) -> None:
        """`check-media-refs --only-refs-from-git-diff <base>` validates only newly added/changed refs."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "opf-data"
            products = repo / "products"
            products.mkdir(parents=True)
            media_dir = tmp_path / "opf-media"
            (media_dir / "media").mkdir(parents=True)

            subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "tester"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "tester@example.org"], check=True)

            # Commit 1: an older product referencing an intentionally unpopulated sha_old
            old_sha = "a" * 64
            d1 = _make_sample_draft()
            d1["evidence"] = [
                {
                    "type": "label_photo",
                    "region": "nutrition_table",
                    "cropped_sha256": old_sha,
                    "media_ref": f"opf-media://sha256/{old_sha}",
                    "contributor": "github:alice",
                    "reported_at": "2026-01-10",
                    "vintage_month": "2026-01",
                }
            ]
            p1 = tmp_path / "d1.json"
            p1.write_text(json.dumps(d1, ensure_ascii=False), encoding="utf-8")
            rc_s1, _, err_s1 = _run_cli(["submit", "--quiet", "--input", str(p1), "--out-dir", str(products)])
            self.assertEqual(rc_s1, 0, err_s1)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "add old product"], check=True, capture_output=True)

            # Commit 2: add second edition with sha_new from real WebP transcoding
            src_jpg = tmp_path / "new_crop.jpg"
            _create_rotated_jpeg_with_exif(src_jpg, width=600, height=500)
            stage_dir = tmp_path / "stage_media"
            d2 = _make_sample_draft()
            d2["id"] = "opf:sample/diff-test/100g"
            p2 = tmp_path / "d2.json"
            p2.write_text(json.dumps(d2, ensure_ascii=False), encoding="utf-8")
            rc_s2, out_s2, err_s2 = _run_cli(
                [
                    "submit",
                    "--input",
                    str(p2),
                    "--out-dir",
                    str(products),
                    "--photo",
                    f"nutrition_table={src_jpg}",
                    "--media-out-dir",
                    str(stage_dir),
                    "--vintage-month",
                    "2026-08",
                ]
            )
            self.assertEqual(rc_s2, 0, err_s2)
            new_blob = json.loads(out_s2)["staged_media"][0]
            new_sha = new_blob["sha256"]
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "add new product"], check=True, capture_output=True)

            # Diff-scoped check vs HEAD~1 checks ONLY new_sha (fails with MISSING_MEDIA for new_sha, ignoring old_sha)
            rc_diff_fail, _, err_diff_fail = _run_cli(
                [
                    "check-media-refs",
                    "--media-dir",
                    str(media_dir),
                    "--only-refs-from-git-diff",
                    "HEAD~1",
                    str(products),
                ]
            )
            self.assertEqual(rc_diff_fail, 1)
            self.assertIn(new_sha, err_diff_fail)
            self.assertNotIn(old_sha, err_diff_fail)

            # Place ONLY new_sha blob in media_dir -> diff-scoped check passes even while old_sha is absent
            dest_new = media_dir / new_blob["rel_path"]
            dest_new.parent.mkdir(parents=True, exist_ok=True)
            dest_new.write_bytes(Path(new_blob["abs_path"]).read_bytes())

            rc_diff_ok, out_diff_ok, err_diff_ok = _run_cli(
                [
                    "check-media-refs",
                    "--media-dir",
                    str(media_dir),
                    "--only-refs-from-git-diff",
                    "HEAD~1",
                    str(products),
                ]
            )
            self.assertEqual(rc_diff_ok, 0, err_diff_ok)
            self.assertIn("1 opf-media reference(s) verified", out_diff_ok)

    def test_synthetic_fixtures_products_validate_and_build_multilingual_brands(self) -> None:
        """Multi-market synthetic fixtures in tests/fixtures/products validate and compile multilingual brands cleanly."""
        fixtures_products = REPO_ROOT / "tests" / "fixtures" / "products"
        self.assertFalse(
            (REPO_ROOT / "tests" / "fixtures" / "__init__.py").exists(),
            "tests/fixtures/__init__.py must NOT exist (shadows tests/fixtures.py module)",
        )
        self.assertEqual(validate_products_root(fixtures_products, allow_empty=False), [])

        with tempfile.TemporaryDirectory() as tmp:
            site_dir = Path(tmp) / "site"
            meta = build_static_api(
                fixtures_products,
                site_dir,
                canonical_base="https://mickey996icu.github.io/opf-data",
                allow_empty=False,
                media_base_url="https://raw.githubusercontent.com/mickey996icu/opf-media/main",
            )
            self.assertEqual(meta["total_products"], 5)
            self.assertEqual(meta["counts_by_market"], {"CN": 2, "EU": 1, "JP": 1, "US": 1})

            # Verify uniform (CN), EditionRedirect (opf:), divergent+partial (EU), supersedes (US), and JP ／ additives
            c1 = json.loads((site_dir / "v1" / "gtin" / "000" / "000" / "00000000000017.json").read_text("utf-8"))
            self.assertEqual(c1["resolution"], "uniform")

            c2 = json.loads(
                (site_dir / "v1" / "opf" / "demo-deli" / "black-pepper-patty" / "80g.json").read_text("utf-8")
            )
            self.assertEqual(c2["resolution"], "single")
            self.assertTrue(c2.get("edition_redirects"))

            c3 = json.loads((site_dir / "v1" / "gtin" / "000" / "000" / "00000000000024.json").read_text("utf-8"))
            self.assertEqual(c3["resolution"], "divergent")
            self.assertTrue(c3["common_summary"]["nutrient_ranges_not_for_logging"]["dietary_fiber"]["partial"])
            self.assertEqual(c3["common_summary"]["allergens_union"]["may_contain"], ["peanuts"])

            c4 = json.loads((site_dir / "v1" / "gtin" / "000" / "000" / "00000000000031.json").read_text("utf-8"))
            self.assertEqual(c4["resolution"], "single")
            self.assertEqual(c4["normalized"]["nutrients"]["fat_trans"]["qualifier"], "<")
            statuses = {item["status"] for item in c4["editions_summary"]}
            self.assertEqual(statuses, {"active", "superseded"})

            c5 = json.loads((site_dir / "v1" / "gtin" / "000" / "000" / "00000000000048.json").read_text("utf-8"))
            self.assertEqual(c5["resolution"], "single")
            self.assertIn("300", c5["normalized"]["additives_ins"])

            # Verify multilingual brand_names propagation across brands.json, brand/{slug}.json, and catalog.jsonl
            brands_doc = json.loads((site_dir / "v1" / "index" / "brands.json").read_text("utf-8"))
            by_brand = {b["brand"]: b for b in brands_doc["brands"]}
            self.assertEqual(by_brand["示例茶坊"]["brand_names"].get("en"), "Demo Tea Lab")
            self.assertEqual(by_brand["鲜厨示例"]["brand_names"].get("en"), "Demo Deli")
            self.assertEqual(by_brand["ミドリ試作工房"]["brand_names"].get("en"), "Midori Demo Lab")

            brand_tea = json.loads((site_dir / by_brand["示例茶坊"]["index_url"].lstrip("/")).read_text("utf-8"))
            self.assertEqual(brand_tea["brand_names"].get("en"), "Demo Tea Lab")
            self.assertEqual(brand_tea["products"][0]["brand_names"].get("en"), "Demo Tea Lab")

            catalog_rows = [
                json.loads(line)
                for line in (site_dir / "v1" / "index" / "catalog.jsonl").read_text("utf-8").splitlines()
                if line.strip()
            ]
            by_id = {r["id"]: r for r in catalog_rows}
            for pid in by_id:
                if pid.startswith("gtin:"):
                    self.assertTrue(pid.startswith("gtin:0000000000"), f"Unexpected non-synthetic GTIN {pid}")
            self.assertEqual(by_id["gtin:00000000000017"]["brand_names"].get("en"), "Demo Tea Lab")
            self.assertEqual(by_id["gtin:00000000000048"]["brand_names"].get("en"), "Midori Demo Lab")

    def test_seven_region_schema_legacy_aliases_and_front_cover_rejection(self) -> None:
        """Schema enforces exact 7 functional regions, CLI/normalizer auto-maps legacy aliases, and rejects front cover photos."""
        ed_schema = load_json_schema("edition.v0.2.schema.json")
        schema_enum = ed_schema["$defs"]["EvidenceItem"]["properties"]["region"]["enum"]
        self.assertEqual(schema_enum, list(CANONICAL_EVIDENCE_REGIONS))
        self.assertEqual(len(schema_enum), 7)

        self.assertEqual(normalize_evidence_region("nutrition_panel"), "nutrition_table")
        self.assertEqual(normalize_evidence_region("ingredients_panel"), "ingredients_box")
        self.assertEqual(normalize_evidence_region("origin_manufacturer_panel"), "manufacturer_block")
        self.assertEqual(normalize_evidence_region("barcode_panel"), "barcode_net_content")
        self.assertEqual(normalize_evidence_region("full_back"), "full_back_label")
        for forbidden in ("front_of_pack", "front_thumb"):
            with self.assertRaises(ValueError) as ctx:
                normalize_evidence_region(forbidden)
            self.assertIn("prohibited", str(ctx.exception))

        # Raw schema rejects front_of_pack, front_thumb, and unnormalized nutrition_panel
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_dir = tmp_path / "products"
            products_dir.mkdir(parents=True)

            legacy_sha = "b" * 64
            legacy_draft = _make_sample_draft()
            legacy_draft["evidence"] = [
                {
                    "type": "label_photo",
                    "region": "nutrition_panel",
                    "cropped_sha256": legacy_sha,
                    "media_ref": f"opf-media://sha256/{legacy_sha}",
                    "contributor": "github:alice",
                    "reported_at": "2026-08-01",
                    "vintage_month": "2026-08",
                }
            ]
            d_path = tmp_path / "legacy_draft.json"
            d_path.write_text(json.dumps(legacy_draft, ensure_ascii=False), encoding="utf-8")

            rc_sub, out_sub, err_sub = _run_cli(
                ["submit", "--input", str(d_path), "--out-dir", str(products_dir)]
            )
            self.assertEqual(rc_sub, 0, err_sub)
            ed_id = json.loads(out_sub)["edition_id"]
            ed_path = products_dir / "gtin" / "000" / "000" / "00000000000017" / "editions" / f"{ed_id}.json"
            ed_doc = json.loads(ed_path.read_text("utf-8"))
            self.assertEqual(ed_doc["evidence"][0]["region"], "nutrition_table")

            for bad_region in ("front_of_pack", "front_thumb", "nutrition_panel"):
                bad_doc = json.loads(json.dumps(ed_doc))
                bad_doc["evidence"][0]["region"] = bad_region
                self.assertNotEqual(
                    validate_against_json_schema(bad_doc, ed_schema),
                    [],
                    f"Schema must reject unnormalized/forbidden region {bad_region!r}",
                )
            normalize_edition(bad_doc)
            self.assertEqual(bad_doc["evidence"][0]["region"], "nutrition_table")

            # CLI --photo front_of_pack=... & --photo front_thumb=... must abort with copyright notice
            jpg_path = tmp_path / "cover.jpg"
            jpg_path.write_bytes(b"\xff\xd8\xff\xd9")
            clean_draft = tmp_path / "clean_draft.json"
            clean_draft.write_text(json.dumps(_make_sample_draft(), ensure_ascii=False), encoding="utf-8")
            for bad_photo_region in ("front_of_pack", "front_thumb"):
                rc_bad, _, err_bad = _run_cli(
                    [
                        "submit",
                        "--input",
                        str(clean_draft),
                        "--out-dir",
                        str(products_dir),
                        "--photo",
                        f"{bad_photo_region}={jpg_path}",
                        "--vintage-month",
                        "2026-08",
                    ]
                )
                self.assertEqual(rc_bad, 1)
                self.assertIn("Front-of-pack cover photos", err_bad)
                self.assertIn(FRONT_COVER_ERROR_MESSAGE, err_bad)

                rc_pr_bad, _, err_pr_bad = _run_cli(
                    [
                        "pr",
                        "--input",
                        str(clean_draft),
                        "--photo",
                        f"{bad_photo_region}={jpg_path}",
                        "--vintage-month",
                        "2026-08",
                        "--dry-run",
                    ]
                )
                self.assertEqual(rc_pr_bad, 1)
                self.assertIn("Front-of-pack cover photos", err_pr_bad)

    def test_multilingual_allergen_additive_parsing_and_latin_word_boundaries(self) -> None:
        """All 7 languages support accurate allergen/additive parsing and Unicode Latin word boundaries."""
        from opf.ingredients import parse_ingredients_semantic, verify_ingredients_round_trip
        from opf.registries import lookup_additive_ins, match_allergens_in_name

        # Unicode Latin word-boundary precision & false-positive exclusions across DE / FR / ES / IT
        self.assertEqual(match_allergens_in_name("sablé"), [])
        for non_milk in (
            "laitue",
            "acide lactique",
            "Milchsäure",
            "Kokosmilch",
            "lechuga",
            "ácido láctico",
            "leche de coco",
            "lattuga",
            "acido lattico",
            "latte di cocco",
        ):
            self.assertNotIn("milk", match_allergens_in_name(non_milk), f"False positive milk on {non_milk!r}")

        for non_nut in (
            "Muskatnuss",
            "Kokosnuss",
            "noix de muscade",
            "noix de coco",
            "nuez moscada",
            "coco",
            "noce moscata",
            "noce di cocco",
        ):
            self.assertNotIn("tree_nuts", match_allergens_in_name(non_nut), f"False positive tree_nuts on {non_nut!r}")

        for non_gluten in (
            "Buchweizen",
            "Maltodextrin",
            "sarrasin",
            "blé noir",
            "maltodextrine",
            "trigo sarraceno",
            "alforfón",
            "maltodextrina",
            "grano saraceno",
            "maltodestrina",
        ):
            self.assertNotIn(
                "gluten_cereals",
                match_allergens_in_name(non_gluten),
                f"False positive gluten_cereals on {non_gluten!r}",
            )

        # True positives across European languages
        self.assertIn("gluten_cereals", match_allergens_in_name("Weizenmehl"))
        self.assertIn("gluten_cereals", match_allergens_in_name("Farine de blé"))
        self.assertIn("gluten_cereals", match_allergens_in_name("Harina de trigo"))
        self.assertIn("gluten_cereals", match_allergens_in_name("Farina di frumento"))
        self.assertIn("milk", match_allergens_in_name("Magermilchpulver"))
        self.assertIn("milk", match_allergens_in_name("Lait écrémé en poudre"))
        self.assertIn("milk", match_allergens_in_name("Leche desnatada"))
        self.assertIn("milk", match_allergens_in_name("Latte scremato"))
        self.assertIn("tree_nuts", match_allergens_in_name("geröstete Haselnüsse"))
        self.assertIn("tree_nuts", match_allergens_in_name("Noisettes grillées"))
        self.assertIn("tree_nuts", match_allergens_in_name("Avellanas tostadas"))
        self.assertIn("tree_nuts", match_allergens_in_name("Nocciole tostate"))
        self.assertIn("celery", match_allergens_in_name("Sellerie"))
        self.assertIn("celery", match_allergens_in_name("céleri"))
        self.assertIn("celery", match_allergens_in_name("apio"))
        self.assertIn("celery", match_allergens_in_name("sedano"))
        self.assertIn("mustard", match_allergens_in_name("Senf"))
        self.assertIn("mustard", match_allergens_in_name("moutarde"))
        self.assertIn("mustard", match_allergens_in_name("mostaza"))
        self.assertIn("mustard", match_allergens_in_name("senape"))
        self.assertIn("soybeans", match_allergens_in_name("Sojalecithin"))

        # Additive lookups across E-number variants and EU names
        self.assertEqual(lookup_additive_ins("E 300"), "300")
        self.assertEqual(lookup_additive_ins("E322(i)"), "322(i)")
        self.assertEqual(lookup_additive_ins("E 322(i)"), "322(i)")
        self.assertEqual(lookup_additive_ins("Sojalecithin"), "322")
        self.assertEqual(lookup_additive_ins("lécithines"), "322")
        self.assertEqual(lookup_additive_ins("lecitinas"), "322")
        self.assertEqual(lookup_additive_ins("lecitine"), "322")
        self.assertEqual(lookup_additive_ins("Natriumhydrogencarbonat"), "500(ii)")
        self.assertEqual(lookup_additive_ins("Bicarbonate de sodium"), "500(ii)")
        self.assertEqual(lookup_additive_ins("Bicarbonato sódico"), "500(ii)")
        self.assertEqual(lookup_additive_ins("Bicarbonato di sodio"), "500(ii)")

        # End-to-end functional-class + lossless round-trip across DE / FR / ES / IT / JA / ZH / EN
        samples = [
            ("de", "EU/1169-2011", "Zutaten: Weizenmehl, Buchweizenmehl, Emulgator: Lecithine (Soja), E 330."),
            ("fr", "EU/1169-2011", "Ingrédients : Farine de blé, sablé, Émulsifiant : lécithines (soja), correcteur d'acidité : acide citrique."),
            ("es", "EU/1169-2011", "Ingredientes: Harina de trigo, trigo sarraceno, Emulgente: lecitinas (soja), gasificante: E500(ii)."),
            ("it", "EU/1169-2011", "Ingredienti: Farina di grano tenero, latte, Emulsionante: lecitine (soia), antiossidante: acido ascorbico."),
            ("ja", "JP/CAA-2015", "原材料名：小麦粉、砂糖／乳化剤（大豆由来）、酸化防止剤（ビタミンC）"),
            ("zh-Hans", "CN/GB28050-2011", "配料：小麦粉、荞麦粉、乳化剂（大豆磷脂）、碳酸氢钠"),
            ("en", "EU/1169-2011", "Ingredients: Wheat flour, Emulsifier: Lecithins (Soy), Ascorbic acid."),
        ]
        for lang_tag, profile_id, raw_text in samples:
            nodes = parse_ingredients_semantic(raw_text, lang=lang_tag, profile_id=profile_id)
            self.assertEqual(
                verify_ingredients_round_trip(raw_text, nodes, profile_id=profile_id),
                [],
                f"Round-trip failed for {lang_tag}: {raw_text}",
            )


if __name__ == "__main__":
    unittest.main()
