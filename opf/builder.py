"""Static API v1 catalog, brand shard index, and web asset builder for OPF v0.3."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from opf import __version__
from opf.doc_compiler import (
    EVIDENCE_LEVEL_RANK,
    build_compact_doc,
    build_full_doc,
    select_representative,
    sort_editions,
)
from opf.ids import api_paths_for_id
from opf.lifecycle import derive_editions_lifecycle
from opf.resources import get_resource_root
from opf.validator import validate_products_root

__all__ = [
    "EVIDENCE_LEVEL_RANK",
    "build_compact_doc",
    "build_full_doc",
    "build_static_api",
]


def _detect_git_commit(repo_dir: Path) -> str | None:
    if not any((cand / ".git").exists() for cand in (repo_dir, repo_dir.parent)):
        return None
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def _brand_slug(brand: str) -> str:
    ascii_part = re.sub(r"[^a-z0-9]+", "-", brand.strip().lower()).strip("-")
    if ascii_part and len(ascii_part) >= 2:
        return ascii_part
    short_hash = hashlib.sha256(brand.strip().encode("utf-8")).hexdigest()[:10]
    return f"b-{short_hash}"


def _format_net_content_str(items: list[dict[str, Any]]) -> str:
    return " / ".join(
        f"{item.get('qualifier', '') if item.get('qualifier') not in (None, '=') else ''}{item['value']}{item['unit']}"
        for item in items
    )


def _compute_energy_kcal_100_summary(
    compact_doc: dict[str, Any], resolution: str
) -> str | None:
    if resolution in ("single", "uniform"):
        nutrients = compact_doc["normalized"].get("nutrients") or {}
        kcal = nutrients.get("energy_kcal")
        if not kcal:
            return None
        q = kcal.get("qualifier") or ""
        return f"{'' if q == '=' else q}{kcal['value']}"
    if resolution == "divergent":
        common = compact_doc["common_summary"]
        if common["basis"] == "mixed":
            return None
        rng = common["nutrient_ranges_not_for_logging"].get("energy_kcal")
        if not rng:
            return None
        lo = f"{rng.get('min_qualifier', '')}{rng['min']}"
        hi = f"{rng.get('max_qualifier', '')}{rng['max']}"
        return lo if lo == hi else f"{lo}–{hi}"
    return None


def _compute_energy_kcal_num(
    compact_doc: dict[str, Any], resolution: str
) -> float | None:
    """Return numeric per-100 kcal estimate strictly for catalog sorting (None when inactive/mixed)."""
    if resolution in ("single", "uniform"):
        kcal = (compact_doc["normalized"].get("nutrients") or {}).get("energy_kcal")
        if not kcal:
            return None
        return round(float(Decimal(kcal["value"])), 2)
    if resolution == "divergent":
        common = compact_doc["common_summary"]
        if common["basis"] == "mixed":
            return None
        rng = common["nutrient_ranges_not_for_logging"].get("energy_kcal")
        if not rng:
            return None
        mid = (Decimal(rng["min"]) + Decimal(rng["max"])) / Decimal("2")
        return round(float(mid), 2)
    return None


def _collect_ingredients_tokens(editions: list[dict[str, Any]]) -> list[str]:
    """Collect NFKC-normalized lowercase ingredient texts, node names, and INS tags for client search."""
    tokens: set[str] = set()

    def _add_norm(raw: Any) -> None:
        if isinstance(raw, str):
            norm = unicodedata.normalize("NFKC", raw).strip().lower()
            if norm:
                tokens.add(norm)

    def _walk_nodes(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            _add_norm(node.get("name"))
            _add_norm(node.get("functional_class"))
            ins = node.get("ins")
            if isinstance(ins, str) and ins.strip():
                _add_norm(ins)
                _add_norm(f"ins {ins}")
            if isinstance(node.get("children"), list):
                _walk_nodes(node["children"])

    for ed in editions:
        attrs = ed.get("attributes") or {}
        for item in attrs.get("ingredients_text") or []:
            if isinstance(item, dict):
                _add_norm(item.get("text"))
        core = ed.get("core") or {}
        for lang_entry in core.get("ingredients_tree") or []:
            if isinstance(lang_entry, dict) and isinstance(lang_entry.get("nodes"), list):
                _walk_nodes(lang_entry["nodes"])

    return sorted(tokens)


def _compute_nutrients_100(
    compact_doc: dict[str, Any],
    active_editions: list[dict[str, Any]],
    resolution: str,
) -> dict[str, dict[str, Any]]:
    """Build per-100g/100ml min/max/upper-bound/partial nutrient index for strict rule filtering."""
    out: dict[str, dict[str, Any]] = {}
    if resolution in ("single", "uniform"):
        norm = compact_doc["normalized"]
        if norm.get("basis") not in ("100g", "100ml"):
            return out
        for k, entry in (norm.get("nutrients") or {}).items():
            val_f = round(float(Decimal(entry["value"])), 4)
            out[k] = {
                "min": val_f,
                "max": val_f,
                "unit": entry["unit"],
                "has_upper_bound": entry.get("qualifier") in ("<", "<="),
                "partial": False,
            }
        return out

    if resolution == "divergent":
        common = compact_doc["common_summary"]
        if common.get("basis") not in ("100g", "100ml"):
            return out
        ranges = common.get("nutrient_ranges_not_for_logging") or {}
        for k, rng in ranges.items():
            entries_k = [
                e["normalized"]["nutrients"][k]
                for e in active_editions
                if k in ((e.get("normalized") or {}).get("nutrients") or {})
            ]
            has_ub = any(en.get("qualifier") in ("<", "<=") for en in entries_k)
            out[k] = {
                "min": round(float(Decimal(rng["min"])), 4),
                "max": round(float(Decimal(rng["max"])), 4),
                "unit": rng["unit"],
                "has_upper_bound": has_ub,
                "partial": bool(rng.get("partial", False)),
            }
        return out

    return out


def build_static_api(
    data_dir: Path,
    out_dir: Path,
    canonical_base: str = "",
    allow_empty: bool = True,
    media_base_url: str = "",
) -> dict[str, Any]:
    """Validate v0.3 split product directories under data_dir and generate static /v1/ API."""
    root = Path(data_dir)
    val_errors = validate_products_root(root, allow_empty=allow_empty)
    if val_errors:
        raise ValueError("Validation failed during build:\n" + "\n".join(val_errors))

    product_items: list[tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]] = []
    for pjson in sorted(root.rglob("product.json")):
        pdir = pjson.parent
        meta = json.loads(pjson.read_text(encoding="utf-8"))
        editions_dir = pdir / "editions"
        records: list[dict[str, Any]] = []
        redirects: dict[str, str] = {}
        for ef in sorted(editions_dir.glob("*.json")):
            edoc = json.loads(ef.read_text(encoding="utf-8"))
            if "merged_into" in edoc:
                redirects[edoc["edition_id"]] = edoc["merged_into"]
            else:
                records.append(edoc)
        product_items.append((meta, records, redirects))

    product_items.sort(key=lambda item: item[0]["id"])

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    brands_map: dict[str, dict[str, Any]] = {}
    catalog_rows: list[dict[str, Any]] = []
    counts_by_resolution: dict[str, int] = {}
    counts_by_evidence: dict[str, int] = {}
    counts_by_market: dict[str, int] = {}

    for product_meta, records, redirects in product_items:
        pid = product_meta["id"]
        lifecycle_map = derive_editions_lifecycle(records)
        compact_rel, full_rel = api_paths_for_id(pid)

        full_doc = build_full_doc(product_meta, records, redirects, lifecycle_map)
        compact_doc = build_compact_doc(product_meta, records, redirects, lifecycle_map, full_rel)

        compact_out = out_path / compact_rel
        full_out = out_path / full_rel
        compact_out.parent.mkdir(parents=True, exist_ok=True)
        with compact_out.open("w", encoding="utf-8") as f:
            json.dump(compact_doc, f, ensure_ascii=False, separators=(",", ":"))
        with full_out.open("w", encoding="utf-8") as f:
            json.dump(full_doc, f, ensure_ascii=False, indent=2)
            f.write("\n")

        resolution = compact_doc["resolution"]
        counts_by_resolution[resolution] = counts_by_resolution.get(resolution, 0) + 1

        ev_summary = compact_doc["evidence_summary"]
        if ev_summary["highest_active"] is not None:
            top_ev_level = ev_summary["highest_active"]
        elif ev_summary["by_edition"]:
            top_ev_level = max(
                ev_summary["by_edition"].values(),
                key=lambda lv: EVIDENCE_LEVEL_RANK[lv],
            )
        else:
            top_ev_level = "community_reported"
        counts_by_evidence[top_ev_level] = counts_by_evidence.get(top_ev_level, 0) + 1

        sorted_records = sort_editions(records, lifecycle_map)
        active_editions = [
            e for e in sorted_records if lifecycle_map[e["edition_id"]]["status"] == "active"
        ]
        for mkt in sorted({e["track"].split("/", 1)[0] for e in active_editions}):
            counts_by_market[mkt] = counts_by_market.get(mkt, 0) + 1

        rep = select_representative(sorted_records, active_editions, lifecycle_map)
        rep_attrs = rep.get("attributes") or {}
        names_i18n = {
            item["lang"]: item["text"]
            for item in compact_doc["product_name"]
            if isinstance(item, dict) and "lang" in item and "text" in item
        }
        brand_names_i18n: dict[str, str] = {}
        for ed_src in [rep, *sorted_records]:
            ed_attrs = ed_src.get("attributes") or {}
            for tr in ed_attrs.get("translations") or []:
                if not isinstance(tr, dict) or not tr.get("lang") or not tr.get("text"):
                    continue
                if tr.get("field") == "product_name":
                    names_i18n.setdefault(tr["lang"], tr["text"])
                elif tr.get("field") == "brand":
                    brand_names_i18n.setdefault(tr["lang"], tr["text"])

        if resolution in ("single", "uniform"):
            net_str = _format_net_content_str(compact_doc["net_content"])
            basis_str = compact_doc["normalized"]["basis"]
        elif resolution == "divergent":
            net_str = _format_net_content_str(compact_doc["common_summary"]["net_content_values"])
            basis_str = compact_doc["common_summary"]["basis"]
        else:
            net_str = _format_net_content_str(rep["core"]["net_content"])
            basis_str = rep["normalized"]["basis"]

        brand_name = compact_doc["brand"]
        if compact_doc["product_name"]:
            first_lang = compact_doc["product_name"][0].get("lang")
            if first_lang and first_lang not in brand_names_i18n:
                brand_names_i18n[first_lang] = brand_name
        b_slug = _brand_slug(brand_name)
        namespace = pid.split(":", 1)[0]
        markets = sorted({e["track"].split("/", 1)[0] for e in (active_editions or sorted_records)})
        filter_editions = active_editions or [rep]
        profiles_list = sorted(
            {
                e["core"]["regulatory_profile"]
                for e in filter_editions
                if (e.get("core") or {}).get("regulatory_profile")
            }
        )
        category_val = compact_doc.get("category") or rep_attrs.get("category") or None
        allergens_contains = sorted(
            {
                alg
                for e in filter_editions
                for alg in ((e["normalized"].get("allergens") or {}).get("contains") or [])
            }
        )
        allergens_may_contain = sorted(
            {
                alg
                for e in filter_editions
                for alg in ((e["normalized"].get("allergens") or {}).get("may_contain") or [])
            }
            - set(allergens_contains)
        )
        additives_ins_list = sorted(
            {ins for e in filter_editions for ins in (e["normalized"].get("additives_ins") or [])}
        )
        additives_count = len(additives_ins_list)
        ingredients_tokens = _collect_ingredients_tokens(filter_editions)
        nutrients_100 = _compute_nutrients_100(compact_doc, active_editions, resolution)
        all_exempt = bool(filter_editions) and all(
            (e.get("core") or {}).get("nutrition_declared") is None for e in filter_editions
        )

        summary_row: dict[str, Any] = {
            "id": pid,
            "namespace": namespace,
            "name": compact_doc["product_name"][0]["text"],
            "names": names_i18n,
            "brand": brand_name,
            "brand_names": dict(sorted(brand_names_i18n.items())),
            "brand_slug": b_slug,
            "markets": markets,
            "profiles": profiles_list,
            "resolution": resolution,
            "active_edition_ids": compact_doc["active_edition_ids"],
            "evidence_level": top_ev_level,
            "lowest_active_evidence_level": ev_summary["lowest_active"],
            "net_content": net_str,
            "basis": basis_str,
            "energy_kcal_100": _compute_energy_kcal_100_summary(compact_doc, resolution),
            "energy_kcal_num": _compute_energy_kcal_num(compact_doc, resolution),
            "allergens_contains": allergens_contains,
            "allergens_may_contain": allergens_may_contain,
            "additives_ins": additives_ins_list,
            "additives_count": additives_count,
            "ingredients_tokens": ingredients_tokens,
            "nutrients_100": nutrients_100,
            "compact_url": f"/{compact_rel}",
            "full_url": f"/{full_rel}",
        }
        if all_exempt:
            summary_row["nutrition_exempt"] = True
        if category_val:
            summary_row["category"] = category_val
        if product_meta.get("aliases"):
            summary_row["aliases"] = list(product_meta["aliases"])

        if b_slug not in brands_map:
            brands_map[b_slug] = {
                "brand_slug": b_slug,
                "brand": brand_name,
                "brand_names": {},
                "count": 0,
                "index_url": f"/v1/index/brand/{b_slug}.json",
                "items": [],
            }
        for lang_k, txt_v in brand_names_i18n.items():
            brands_map[b_slug]["brand_names"].setdefault(lang_k, txt_v)
        brands_map[b_slug]["count"] += 1
        brands_map[b_slug]["items"].append(summary_row)
        catalog_rows.append(summary_row)

    index_dir = out_path / "v1" / "index"
    brand_index_dir = index_dir / "brand"
    brand_index_dir.mkdir(parents=True, exist_ok=True)

    brands_directory = []
    for b_slug, b_info in sorted(brands_map.items()):
        sorted_brand_names = dict(sorted(b_info["brand_names"].items()))
        b_file = brand_index_dir / f"{b_slug}.json"
        with b_file.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "brand_slug": b_slug,
                    "brand": b_info["brand"],
                    "brand_names": sorted_brand_names,
                    "count": b_info["count"],
                    "products": b_info["items"],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.write("\n")
        brands_directory.append(
            {
                "brand_slug": b_slug,
                "brand": b_info["brand"],
                "brand_names": sorted_brand_names,
                "count": b_info["count"],
                "index_url": b_info["index_url"],
            }
        )

    with (index_dir / "brands.json").open("w", encoding="utf-8") as f:
        json.dump({"brands": brands_directory}, f, ensure_ascii=False, indent=2)
        f.write("\n")

    with (index_dir / "catalog.jsonl").open("w", encoding="utf-8") as f:
        for row in catalog_rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    tool_commit = _detect_git_commit(Path(__file__).resolve().parent.parent)
    data_commit = _detect_git_commit(root)

    meta_out: dict[str, Any] = {
        "opf_schema": "0.3",
        "opf_version": __version__,
        "canonical_base": canonical_base,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_products": len(product_items),
        "counts_by_resolution": counts_by_resolution,
        "counts_by_evidence_level": counts_by_evidence,
        "counts_by_market": counts_by_market,
        "endpoints": {
            "gtin_compact": "/v1/gtin/{p1}/{p2}/{gtin14}.json",
            "gtin_full": "/v1/gtin/{p1}/{p2}/{gtin14}.full.json",
            "opf_compact": "/v1/opf/{brand}/{product}/{spec}.json",
            "opf_full": "/v1/opf/{brand}/{product}/{spec}.full.json",
            "brands_index": "/v1/index/brands.json",
            "brand_products": "/v1/index/brand/{brand_slug}.json",
            "catalog_jsonl": "/v1/index/catalog.jsonl",
        },
    }
    if media_base_url:
        meta_out["media_base_url"] = media_base_url.rstrip("/")
    if tool_commit:
        meta_out["opf_tool_commit"] = tool_commit
    if data_commit:
        meta_out["opf_data_commit"] = data_commit

    with (out_path / "v1" / "meta.json").open("w", encoding="utf-8") as f:
        json.dump(meta_out, f, ensure_ascii=False, indent=2)
        f.write("\n")

    _copy_web_assets(out_path)
    return meta_out


def _copy_web_assets(out_dir: Path) -> None:
    """Copy the static explorer (web/) and locale files into the site root."""
    web_dir = get_resource_root() / "web"
    if not web_dir.is_dir():
        return
    assets = out_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(web_dir / "index.html", out_dir / "index.html")
    for name in ("style.css", "app.js", "scanner.js"):
        shutil.copyfile(web_dir / name, assets / name)
    vendor_src = web_dir / "vendor"
    if vendor_src.is_dir():
        vendor_dst = assets / "vendor"
        vendor_dst.mkdir(parents=True, exist_ok=True)
        for vfile in sorted(vendor_src.iterdir()):
            if vfile.is_file() and not vfile.name.startswith("."):
                shutil.copyfile(vfile, vendor_dst / vfile.name)
    locales_src = web_dir / "locales"
    if locales_src.is_dir():
        locales_dst = out_dir / "locales"
        locales_dst.mkdir(parents=True, exist_ok=True)
        for lfile in sorted(locales_src.glob("*.json")):
            shutil.copyfile(lfile, locales_dst / lfile.name)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
