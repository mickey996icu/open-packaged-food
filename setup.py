"""Setuptools build hook that bundles dictionaries, profiles, schemas, and web assets into wheels."""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

_RESOURCE_DIRS = ("dictionaries", "profiles", "spec/schema", "web")


def _ignore_junk(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if n in ("__pycache__", ".DS_Store") or n.endswith((".pyc", ".pyo"))]


class BundleResourcesBuildPy(build_py):
    """Copy top-level repo resource trees into `opf/_bundled/` inside built distributions."""

    def run(self) -> None:
        super().run()
        repo_root = Path(__file__).resolve().parent
        bundled_root = Path(self.build_lib) / "opf" / "_bundled"
        for rel in _RESOURCE_DIRS:
            src = repo_root / rel
            if not src.is_dir():
                raise FileNotFoundError(f"Expected resource directory for wheel build: {src}")
            dst = bundled_root / rel
            if dst.exists():
                shutil.rmtree(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, ignore=_ignore_junk)

        if not (bundled_root / "dictionaries" / "nutrients.json").is_file():
            raise RuntimeError("Wheel resource bundle missing dictionaries/nutrients.json")
        if not (bundled_root / "spec" / "schema" / "edition.v0.2.schema.json").is_file():
            raise RuntimeError("Wheel resource bundle missing spec/schema/edition.v0.2.schema.json")
        if not (bundled_root / "web" / "scanner.js").is_file():
            raise RuntimeError("Wheel resource bundle missing web/scanner.js")
        if not (bundled_root / "web" / "vendor" / "zxing.min.js").is_file():
            raise RuntimeError("Wheel resource bundle missing web/vendor/zxing.min.js")
        if not (bundled_root / "web" / "vendor" / "sarasa-mono-regular.woff").is_file():
            raise RuntimeError("Wheel resource bundle missing web/vendor/sarasa-mono-regular.woff")


setup(cmdclass={"build_py": BundleResourcesBuildPy})
