"""Unit and CLI tests for PR metadata/DCO gate, INS 160c mapping, and Explorer cache-busting."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from opf.ingredients import parse_ingredients_semantic
from opf.pr_check import validate_pr_metadata
from opf.registries import REPO_ROOT


class TestPrMetadataAndFixes(unittest.TestCase):
    def test_media_pr_rejects_empty_body_and_accepts_valid_or_maintenance(self) -> None:
        errs_empty = validate_pr_metadata(
            repo_kind="media",
            title="media(label): add complete unclipped label evidence",
            body="",
            changed_files=["media/91/9a/919a8247248a4d7b2ee3642d8336d114a4d4e05ca9e65956d3c3347c9fc3c208.webp"],
        )
        self.assertTrue(any("must not be empty" in e for e in errs_empty))

        errs_no_product = validate_pr_metadata(
            repo_kind="media",
            title="media(label): upload cropped WebP files",
            body="Uploaded cropped label images with stripped EXIF metadata only.",
            changed_files=["media/91/9a/919a8247248a4d7b2ee3642d8336d114a4d4e05ca9e65956d3c3347c9fc3c208.webp"],
        )
        self.assertTrue(any("must reference the target product ID" in e for e in errs_no_product))

        errs_ok = validate_pr_metadata(
            repo_kind="media",
            title="media(label): gtin:06974117080016 label WebP crops",
            body=(
                "## Label Evidence Media\n"
                "- **Companion Data PR**: https://github.com/mickey996icu/opf-data/pull/2\n"
                "- **Product**: `gtin:06974117080016`\n"
            ),
            changed_files=["media/91/9a/919a8247248a4d7b2ee3642d8336d114a4d4e05ca9e65956d3c3347c9fc3c208.webp"],
            commits=[("abc12345", "media(label): add crops\n\nSigned-off-by: Dev <dev@users.noreply.github.com>")],
        )
        self.assertEqual(errs_ok, [])

        errs_maint = validate_pr_metadata(
            repo_kind="media",
            title="ci: add PR template and metadata gate",
            body="Add pull request template and CI metadata validation workflow.",
            changed_files=[".github/PULL_REQUEST_TEMPLATE.md", ".github/workflows/ci.yml"],
            commits=[("def67890", "ci: add PR gate\n\nSigned-off-by: Dev <dev@users.noreply.github.com>")],
        )
        self.assertEqual(errs_maint, [])

    def test_data_pr_rejects_placeholders_unchecked_boxes_and_missing_companion_url(self) -> None:
        errs_placeholder = validate_pr_metadata(
            repo_kind="data",
            title="feat(product): add vegan steak record",
            body=(
                "- [x] 新增商品\n"
                "- **ID**: `gtin:06974117080016`\n"
                "- **Companion Media PR（先合入）**: 填上你刚开的 opf-media PR 链接\n"
            ),
            changed_files=["products/gtin/697/411/06974117080016/product.json"],
            require_companion_media_pr=True,
        )
        self.assertTrue(any("unresolved placeholder" in e for e in errs_placeholder))
        self.assertTrue(any("companion opf-media PR URL" in e for e in errs_placeholder))

        errs_unchecked = validate_pr_metadata(
            repo_kind="tooling",
            title="fix(cli): refine validation output",
            body="## Change Type\n- [ ] New product\n- [ ] Tooling update\nDetailed description of tooling changes.",
        )
        self.assertTrue(any("none are checked" in e for e in errs_unchecked))

        errs_dco = validate_pr_metadata(
            repo_kind="tooling",
            title="fix(cli): refine validation output",
            body="Detailed description of tooling changes without template checkboxes.",
            commits=[("11223344", "fix(cli): missing signoff line")],
        )
        self.assertTrue(any("Signed-off-by" in e for e in errs_dco))

        errs_code_span = validate_pr_metadata(
            repo_kind="tooling",
            title="feat(ci): reject unresolved PR placeholders",
            body="- [x] Tooling update\nRejects literal `<MEDIA_PR_URL>` and `填上...链接` placeholders.",
        )
        self.assertEqual(errs_code_span, [])

    def test_cli_check_pr_meta_with_event_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ev_file = Path(tmp) / "event.json"
            ev_file.write_text(
                json.dumps(
                    {
                        "pull_request": {
                            "title": "feat(product): gtin:06974117080016 (rev1)",
                            "body": (
                                "## Product Submission (v0.2)\n"
                                "> **Companion Media PR (MERGE FIRST)**: https://github.com/mickey996icu/opf-media/pull/1\n"
                                "- **ID**: `gtin:06974117080016`\n"
                            ),
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            res = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "opf"),
                    "check-pr-meta",
                    "--repo-kind",
                    "data",
                    "--event-path",
                    str(ev_file),
                    "--require-companion-media-pr",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, res.stderr)

    def test_paprika_extract_ins_160c_and_web_cache_busting(self) -> None:
        nodes = parse_ingredients_semantic(
            "水、辣椒红、山梨酸钾", lang="zh-Hans", profile_id="CN/GB28050-2025"
        )
        by_name = {n["name"]: n for n in nodes}
        self.assertEqual(by_name["辣椒红"].get("ins"), "160c")
        self.assertTrue(by_name["辣椒红"].get("is_additive"))

        app_js = (REPO_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function withDataRev(", app_js)
        self.assertIn('{ cache: "no-cache" }', app_js)
        self.assertIn('withDataRev("v1/index/catalog.jsonl")', app_js)

    def test_pr_check_enforces_provenance_roles_and_immutability(self) -> None:
        rel_ed = "products/gtin/000/000/00000000000109/editions/01JTESTCNTEA00000000000001.json"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_repo = tmp_path / "opf-data"
            ed_file = data_repo / rel_ed
            ed_file.parent.mkdir(parents=True, exist_ok=True)
            base_doc = {
                "opf_schema": "0.2",
                "id": "gtin:00000000000109",
                "edition_id": "01JTESTCNTEA00000000000001",
                "evidence": [
                    {
                        "evidence_id": "ev:01JTESTCNTEA00000000000001",
                        "type": "community_report",
                        "provenance": "maintainer",
                    },
                    {
                        "evidence_id": "ev:01JTESTCNTEA00000000000010",
                        "type": "community_report",
                        "provenance": "external_contributor",
                    },
                ],
                "revisions": [
                    {"rev": 1, "kind": "initial", "provenance": "maintainer"},
                ],
            }
            ed_file.write_text(json.dumps(base_doc), encoding="utf-8")
            subprocess.run(["git", "-C", str(data_repo), "init", "-b", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(data_repo), "config", "user.email", "dev@example.org"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(data_repo), "config", "user.name", "Dev"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(data_repo), "add", "-A"], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(data_repo), "commit", "-s", "-m", "chore: initial baseline"],
                check=True,
                capture_output=True,
            )

            # 1. External contributor adds external_contributor evidence while keeping existing entries intact -> OK
            subprocess.run(["git", "-C", str(data_repo), "switch", "-c", "feat/ext-corrob"], check=True, capture_output=True)
            ok_doc = json.loads(ed_file.read_text(encoding="utf-8"))
            ok_doc["evidence"].append(
                {
                    "evidence_id": "ev:01JTESTCNTEA00000000000002",
                    "type": "community_report",
                    "provenance": "external_contributor",
                }
            )
            ed_file.write_text(json.dumps(ok_doc), encoding="utf-8")
            subprocess.run(["git", "-C", str(data_repo), "add", "-A"], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(data_repo), "commit", "-s", "-m", "feat(product): gtin:00000000000109 corroborate"],
                check=True,
                capture_output=True,
            )

            def _run_gate(actor: str, extra_args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
                ev_p = tmp_path / f"ev_{actor}.json"
                ev_p.write_text(
                    json.dumps(
                        {
                            "pull_request": {
                                "title": f"feat(product): gtin:00000000000109 update by {actor}",
                                "body": f"Submission for gtin:00000000000109 from {actor}.",
                                "user": {"login": actor},
                                "base": {"repo": {"owner": {"login": "mickey996icu"}}},
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.run(
                    [
                        sys.executable,
                        str(REPO_ROOT / "bin" / "opf"),
                        "check-pr-meta",
                        "--repo-kind",
                        "data",
                        "--event-path",
                        str(ev_p),
                        "--repo-dir",
                        str(data_repo),
                        "--base-ref",
                        "main",
                        *(extra_args or []),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )

            res_ext_ok = _run_gate("external-user")
            self.assertEqual(res_ext_ok.returncode, 0, res_ext_ok.stderr)

            # 2. External contributor cannot write public_submission, brand_owner, partner, or maintainer
            for forbidden in ("public_submission", "brand_owner", "partner", "maintainer"):
                subprocess.run(["git", "-C", str(data_repo), "switch", "main"], check=True, capture_output=True)
                bname = f"feat/ext-bad-{forbidden}"
                subprocess.run(["git", "-C", str(data_repo), "switch", "-c", bname], check=True, capture_output=True)
                d_bad = json.loads(ed_file.read_text(encoding="utf-8"))
                d_bad["evidence"].append(
                    {
                        "evidence_id": f"ev:01JTESTCNTEA0000000000099{forbidden[0].upper()}",
                        "type": "community_report",
                        "provenance": forbidden,
                    }
                )
                ed_file.write_text(json.dumps(d_bad), encoding="utf-8")
                subprocess.run(["git", "-C", str(data_repo), "add", "-A"], check=True, capture_output=True)
                subprocess.run(
                    ["git", "-C", str(data_repo), "commit", "-s", "-m", f"feat(product): spoof {forbidden}"],
                    check=True,
                    capture_output=True,
                )
                res_bad = _run_gate("external-user")
                self.assertEqual(res_bad.returncode, 1)
                self.assertIn("external_contributor", res_bad.stderr)

            # 3. Relay bot may only set provenance='public_submission'
            subprocess.run(["git", "-C", str(data_repo), "switch", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(data_repo), "switch", "-c", "feat/relay-ok"], check=True, capture_output=True)
            d_rel = json.loads(ed_file.read_text(encoding="utf-8"))
            d_rel["evidence"].append(
                {
                    "evidence_id": "ev:01JTESTCNTEA00000000000088",
                    "type": "community_report",
                    "provenance": "public_submission",
                }
            )
            ed_file.write_text(json.dumps(d_rel), encoding="utf-8")
            subprocess.run(["git", "-C", str(data_repo), "add", "-A"], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(data_repo), "commit", "-s", "-m", "feat(product): public submission"],
                check=True,
                capture_output=True,
            )
            self.assertEqual(_run_gate("opf-relay-bot", ["--relay-login", "opf-relay-bot"]).returncode, 0)
            # Relay bot spoofing external_contributor is rejected
            d_rel["evidence"].append(
                {
                    "evidence_id": "ev:01JTESTCNTEA00000000000089",
                    "type": "community_report",
                    "provenance": "external_contributor",
                }
            )
            ed_file.write_text(json.dumps(d_rel), encoding="utf-8")
            subprocess.run(["git", "-C", str(data_repo), "add", "-A"], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(data_repo), "commit", "-s", "-m", "feat(product): relay spoof ext"],
                check=True,
                capture_output=True,
            )
            res_rel_bad = _run_gate("opf-relay-bot", ["--relay-login", "opf-relay-bot"])
            self.assertEqual(res_rel_bad.returncode, 1)
            self.assertIn("public_submission", res_rel_bad.stderr)

            # 4. Existing provenance immutability: even maintainer cannot modify existing entry without Provenance-Correction trailer
            subprocess.run(["git", "-C", str(data_repo), "switch", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(data_repo), "switch", "-c", "feat/mutate-existing"], check=True, capture_output=True)
            d_mut = json.loads(ed_file.read_text(encoding="utf-8"))
            d_mut["evidence"][1]["provenance"] = "maintainer"
            ed_file.write_text(json.dumps(d_mut), encoding="utf-8")
            subprocess.run(["git", "-C", str(data_repo), "add", "-A"], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(data_repo), "commit", "-s", "-m", "chore: silently reclassify provenance"],
                check=True,
                capture_output=True,
            )
            res_mut_no_trailer = _run_gate("mickey996icu")
            self.assertEqual(res_mut_no_trailer.returncode, 1)
            self.assertIn("Provenance-Correction:", res_mut_no_trailer.stderr)

            # Adding explicit Provenance-Correction trailer allows maintainer correction, but NEVER external user
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(data_repo),
                    "commit",
                    "--amend",
                    "-s",
                    "-m",
                    "chore: correct mislabeled entry\n\nProvenance-Correction: Original entry captured by maintainer account",
                ],
                check=True,
                capture_output=True,
            )
            self.assertEqual(_run_gate("mickey996icu").returncode, 0)
            self.assertEqual(_run_gate("external-user").returncode, 1)

    def test_pr_check_blocks_non_maintainer_deletions(self) -> None:
        ed_dir = "products/gtin/000/000/00000000000109/editions"
        src_id = "01JTESTCNTEA00000000000001"
        tgt_id = "01JTESTCNTEA00000000000002"

        def _ed(edition_id: str, ev_ids: list[str]) -> dict:
            return {
                "opf_schema": "0.2",
                "id": "gtin:00000000000109",
                "edition_id": edition_id,
                "evidence": [
                    {"evidence_id": e, "type": "community_report", "provenance": "maintainer"} for e in ev_ids
                ],
                "revisions": [
                    {"rev": 1, "kind": "initial", "provenance": "maintainer"},
                    {"rev": 2, "kind": "errata", "provenance": "maintainer"},
                ],
            }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "opf-data"
            src = repo / ed_dir / f"{src_id}.json"
            tgt = repo / ed_dir / f"{tgt_id}.json"
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text(json.dumps(_ed(src_id, ["ev:A1", "ev:A2"])), encoding="utf-8")
            tgt.write_text(json.dumps(_ed(tgt_id, ["ev:B1"])), encoding="utf-8")

            def git(*args: str) -> None:
                subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

            git("init", "-b", "main")
            git("config", "user.email", "dev@example.org")
            git("config", "user.name", "Dev")
            git("add", "-A")
            git("commit", "-s", "-m", "chore: baseline")

            def gate(actor: str) -> subprocess.CompletedProcess[str]:
                ev_p = tmp_path / f"ev_{actor}.json"
                ev_p.write_text(
                    json.dumps(
                        {
                            "pull_request": {
                                "title": "feat(product): gtin:00000000000109 update",
                                "body": "Submission for gtin:00000000000109.",
                                "user": {"login": actor},
                                "base": {"repo": {"owner": {"login": "mickey996icu"}}},
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.run(
                    [
                        sys.executable,
                        str(REPO_ROOT / "bin" / "opf"),
                        "check-pr-meta",
                        "--repo-kind",
                        "data",
                        "--event-path",
                        str(ev_p),
                        "--repo-dir",
                        str(repo),
                        "--base-ref",
                        "main",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )

            def branch(name: str, mutate) -> None:
                git("switch", "main")
                git("switch", "-c", name)
                mutate()
                git("add", "-A")
                git("commit", "-s", "-m", f"chore: {name}")

            # 1. Deleting an existing edition file: rejected for external, allowed for maintainer
            branch("del-file", lambda: src.unlink())
            res = gate("external-user")
            self.assertEqual(res.returncode, 1)
            self.assertIn("cannot delete an existing edition file", res.stderr)
            self.assertEqual(gate("mickey996icu").returncode, 0, gate("mickey996icu").stderr)

            # 2. Removing an existing evidence entry / revision entry
            def _drop_entries() -> None:
                d = json.loads(src.read_text(encoding="utf-8"))
                d["evidence"] = d["evidence"][:1]
                d["revisions"] = d["revisions"][:1]
                src.write_text(json.dumps(d), encoding="utf-8")

            branch("drop-entries", _drop_entries)
            res = gate("external-user")
            self.assertEqual(res.returncode, 1)
            self.assertIn("evidence[] is append-only", res.stderr)
            self.assertIn("revisions[] is append-only", res.stderr)
            self.assertEqual(gate("mickey996icu").returncode, 0)

            # 3. Merge stub that drops evidence is rejected; carrying evidence into target passes
            stub = {
                "opf_schema": "0.2",
                "id": "gtin:00000000000109",
                "edition_id": src_id,
                "merged_into": tgt_id,
                "merged_into_rev": 2,
                "merged_at": "2026-11-01",
                "reason": "duplicate",
            }

            def _merge_lossy() -> None:
                src.write_text(json.dumps(stub), encoding="utf-8")

            branch("merge-lossy", _merge_lossy)
            res = gate("external-user")
            self.assertEqual(res.returncode, 1)
            self.assertIn("drops existing evidence", res.stderr)

            def _merge_ok() -> None:
                src.write_text(json.dumps(stub), encoding="utf-8")
                d = json.loads(tgt.read_text(encoding="utf-8"))
                d["evidence"] += [
                    {"evidence_id": e, "type": "community_report", "provenance": "maintainer"}
                    for e in ("ev:A1", "ev:A2")
                ]
                tgt.write_text(json.dumps(d), encoding="utf-8")

            branch("merge-ok", _merge_ok)
            res = gate("external-user")
            self.assertNotIn("drops existing evidence", res.stderr)
            self.assertNotIn("append-only", res.stderr)


if __name__ == "__main__":
    unittest.main()
