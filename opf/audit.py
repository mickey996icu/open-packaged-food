"""Deep semantic, regulatory, label-quality, and cross-product audit engine for OPF v0.3."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from opf.ingredients import FUNCTIONAL_CLASS_TERMS, parse_ingredients_semantic
from opf.media import inspect_webp_bytes
from opf.normalize import (
    canonicalize_special_indicator,
    format_canonical_decimal,
    nutrient_row_sort_key,
)
from opf.registries import get_profile, match_allergens_in_name
from opf.validator import public_image_sha

SC_LICENSE_RE = re.compile(r"^SC[0-9]{14}$")
FOREIGN_REG_LICENSE_RE = re.compile(r"^C[A-Z]{3}[0-9]{14}$")

CN_PROVINCE_CODES: dict[str, str] = {
    "11": "北京", "12": "天津", "13": "河北", "14": "山西", "15": "内蒙古",
    "21": "辽宁", "22": "吉林", "23": "黑龙江", "31": "上海", "32": "江苏",
    "33": "浙江", "34": "安徽", "35": "福建", "36": "江西", "37": "山东",
    "41": "河南", "42": "湖北", "43": "湖南", "44": "广东", "45": "广西",
    "46": "海南", "50": "重庆", "51": "四川", "52": "贵州", "53": "云南",
    "54": "西藏", "61": "陕西", "62": "甘肃", "63": "青海", "64": "宁夏",
    "65": "新疆", "71": "台湾", "81": "香港", "82": "澳门",
}

_PROVINCE_NAMES_SORTED = sorted(CN_PROVINCE_CODES.values(), key=len, reverse=True)
_ADDR_PROVINCE_RE = re.compile(
    r"^(?:中国)?[\s（(]*(?P<prov>"
    + "|".join(re.escape(p) for p in _PROVINCE_NAMES_SORTED)
    + r")(?P<suffix>省|市|维吾尔自治区|壮族自治区|回族自治区|自治区|特别行政区)?"
)
_STREET_SUFFIX_RE = re.compile(r"^(?:东|西|南|北|中)?(?:路|街|道|巷|弄|大道)")
_TRUNCATED_SUFFIX_RE = re.compile(r"(?:省|市|县|旗|盟|自治州)$")
_NON_ADMIN_ZONE_SUFFIX_RE = re.compile(
    r"(?:开发区|工业区|产业区|园区|厂区|保税区|试验区|功能区|聚集区|集聚区|管理区|示范区|合作区|度假区|商务区|高新区|科技区|自贸区|新区|[A-Za-z0-9]区)$"
)

_SEASONING_HEAD_MASK_RE = re.compile(r"[\w\u4e00-\u9fff-]*味(?:复合)?调味(?:料|粉|酱|汁)")
_SUGAR_INTERFERENCE_MASK_RE = re.compile(
    r"(?:DL-苹果酸|L-苹果酸|苹果酸|柠檬酸钠|柠檬酸|乳酸|果胶|黄原胶|赤藓糖醇|木糖醇|麦芽糖醇|山梨糖醇|异麦芽酮糖醇|乳糖醇|三氯蔗糖|安赛蜜|阿斯巴甜|甜菊糖苷|罗汉果甜苷|纽甜|甜蜜素)",
    re.IGNORECASE,
)
_REAL_SUGAR_SOURCE_RE = re.compile(
    r"(?:白砂糖|砂糖|绵白糖|冰糖|红糖|黑糖|黄糖|蔗糖|果糖|葡萄糖|麦芽糖|乳糖|糖浆|蜂蜜|海藻糖|异麦芽酮糖|低聚果糖|低聚异麦芽糖|低聚半乳糖|浓缩[^\s，、（）()]*汁|果酱|果泥|果浆|果汁|生牛乳|牛乳|牛奶|乳粉|奶粉|炼乳|乳清|红枣|椰枣|葡萄干|蓝靛果|草莓|蓝莓|蔓越莓|黑莓|树莓|\bsugar\b|\bsucrose\b|\bfructose\b|\bglucose\b|\bsyrup\b|\bhoney\b|\blactose\b|\bmilk\b|\bwhey\b|\bjuice\b|\bdate\b)",
    re.IGNORECASE,
)
_WATER_FORBIDDEN_ING_RE = re.compile(
    r"(?:白砂糖|砂糖|绵白糖|冰糖|红糖|蔗糖|果糖|葡萄糖|糖浆|蜂蜜|赤藓糖醇|木糖醇|麦芽糖醇|三氯蔗糖|安赛蜜|阿斯巴甜|甜菊糖苷|罗汉果甜苷|食用香精|食品用香精|香精|浓缩[^\s，、（）()]*汁|果汁|生牛乳|牛乳|牛奶|乳粉|奶粉|茶粉|速溶茶|\bsugar\b|\bsyrup\b|\bsucralose\b|\berythritol\b|\bflavor\b|\bflavour\b|\bjuice\b|\bmilk\b)",
    re.IGNORECASE,
)
_TEA_COFFEE_FORBIDDEN_ING_RE = re.compile(
    r"(?:白砂糖|砂糖|绵白糖|冰糖|红糖|黑糖|蔗糖|果糖|葡萄糖|麦芽糖|糖浆|蜂蜜|生牛乳|牛乳|牛奶|乳粉|奶粉|炼乳|稀奶油|奶油|植脂末|\bsugar\b|\bsucrose\b|\bfructose\b|\bsyrup\b|\bhoney\b|\bmilk\b|\bcream\b|\bcreamer\b)",
    re.IGNORECASE,
)
_NUTRITION_CLAIM_RE = re.compile(
    r"(?:无糖|零糖|0糖|低糖|无蔗糖|零卡|0卡|低卡|零能量|0能量|低能量|零脂|0脂|无脂|低脂|脱脂|高钙|富含钙|低钠|无钠|高蛋白|富含蛋白|高膳食纤维|富含膳食纤维|高纤|\bsugar[- ]free\b|\bzero[- ]sugar\b|\blow[- ]sugar\b|\bfat[- ]free\b|\blow[- ]fat\b|\bhigh[- ]protein\b|\bhigh[- ]calcium\b|\blow[- ]sodium\b)",
    re.IGNORECASE,
)

INDICATOR_MODIFIERS: tuple[str, ...] = (
    "新西兰", "澳洲", "澳大利亚", "比利时", "法国", "日本", "北海道", "宇治",
    "进口", "有机", "NFC", "A2", "冷萃", "头道", "特级", "野生",
)
_NO_BARCODE_PROOF_RE = re.compile(
    r"(?:无条码|无零售条码|散装|店内码|未印条码|no[\s_-]*barcode|bulk|in-store)",
    re.IGNORECASE,
)
_PURE_ASCII_LATIN_RE = re.compile(r"^[A-Za-z0-9\s.,'&/+()_-]+$")
_NON_EXACT_LOWER_QUALIFIERS = frozenset({"<", "<=", "trace"})
_NON_EXACT_UPPER_QUALIFIERS = frozenset({">", ">="})

_SUBSET_NUTRIENT_RULES: tuple[tuple[str, str, str], ...] = (
    ("fat_saturated", "fat_total", "饱和脂肪"),
    ("fat_trans", "fat_total", "反式脂肪"),
    ("sugars_total", "carbs_available", "糖"),
    ("sugars_total", "carbs_total", "糖"),
    ("sugars_added", "sugars_total", "添加糖"),
    ("dietary_fiber", "carbs_total", "膳食纤维"),
)


@dataclass
class AuditFinding:
    """Structured diagnostic emitted by the OPF audit engine."""

    severity: str  # "ERROR" | "WARN" | "INFO"
    code: str
    product_id: str
    edition_id: str | None
    path: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def format_line(self) -> str:
        target = f"{self.product_id} ({self.edition_id})" if self.edition_id else self.product_id
        return f"[{self.severity}] {self.code} {target} [{self.path}]: {self.message}"


def _emit(
    findings: list[AuditFinding],
    severity: str,
    code: str,
    pid: str,
    eid: str | None,
    path: str,
    message: str,
) -> None:
    findings.append(AuditFinding(severity=severity, code=code, product_id=pid, edition_id=eid, path=path, message=message))


def _parse_dec(val: Any) -> Decimal | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        d = Decimal(str(val).strip())
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _extract_address_province(address: str) -> str | None:
    cleaned = address.strip()
    m = _ADDR_PROVINCE_RE.match(cleaned) if cleaned else None
    if not m:
        return None
    prov, suffix, tail = m.group("prov"), m.group("suffix"), cleaned[m.end() :]
    if not suffix and _STREET_SUFFIX_RE.match(tail):
        return None
    return prov


def _basis_to_100_factor(core: dict[str, Any]) -> Decimal | None:
    decl = core.get("nutrition_declared") or {}
    basis = decl.get("basis") or {}
    b_val = _parse_dec(basis.get("value"))
    b_unit = str(basis.get("unit") or "").strip().lower()
    if b_val is None or b_val <= 0:
        return None
    if b_unit in ("g", "ml"):
        return Decimal("100") / b_val
    if b_unit in ("kg", "l"):
        return Decimal("100") / (b_val * Decimal("1000"))
    if b_unit == "serving":
        serv = core.get("serving_size") or {}
        s_val = _parse_dec(serv.get("value"))
        s_unit = str(serv.get("unit") or "").strip().lower()
        if s_val and s_val > 0:
            if s_unit in ("g", "ml"):
                return Decimal("100") / (b_val * s_val)
            if s_unit in ("kg", "l"):
                return Decimal("100") / (b_val * s_val * Decimal("1000"))
    return None


def _is_lower_bounded_or_exact(row: dict[str, Any]) -> bool:
    return str(row.get("qualifier") or "") not in _NON_EXACT_LOWER_QUALIFIERS


def _is_upper_bounded_or_exact(row: dict[str, Any]) -> bool:
    return str(row.get("qualifier") or "") not in _NON_EXACT_UPPER_QUALIFIERS


def _check_nutrition(
    doc: dict[str, Any], *, pid: str, eid: str | None, path: str, findings: list[AuditFinding]
) -> None:
    core = doc.get("core") or {}
    if not isinstance(core, dict):
        return
    attrs = doc.get("attributes") or {}
    raw_ing = " ".join(
        str(it.get("text") or "")
        for it in (attrs.get("ingredients_text") or [])
        if isinstance(it, dict)
    )

    if core.get("nutrition_declared") is None:
        ex = core.get("nutrition_exemption")
        if not isinstance(ex, dict) or not str(ex.get("category") or "").strip():
            _emit(findings, "ERROR", "MISSING_NUTRITION_EXEMPTION", pid, eid, path,
                  "core.nutrition_declared 为 null 时必须提供包含有效 category 的 core.nutrition_exemption")
            return
        cat = str(ex["category"]).strip()
        if cat == "packaged_water" and raw_ing.strip():
            m_bad = _WATER_FORBIDDEN_ING_RE.search(raw_ing)
            if m_bad:
                _emit(findings, "ERROR", "INVALID_NUTRITION_EXEMPTION", pid, eid, path,
                      f"豁免类别 packaged_water 与配料 {m_bad.group(0)!r} 冲突：含糖/甜味剂/香精/乳/果茶成分的饮品不得按包装饮用水豁免营养成分表")
        elif cat == "tea_coffee_herbs" and raw_ing.strip():
            m_bad = _TEA_COFFEE_FORBIDDEN_ING_RE.search(raw_ing)
            if m_bad:
                _emit(findings, "ERROR", "INVALID_NUTRITION_EXEMPTION", pid, eid, path,
                      f"豁免类别 tea_coffee_herbs 与配料 {m_bad.group(0)!r} 冲突：含添加糖/乳制品/植脂末的产品不得按纯茶/咖啡豁免营养成分表")
        elif cat == "single_ingredient_unprocessed":
            max_top = max(
                (len(le.get("nodes") or []) for le in _effective_ingredients_tree(doc) if isinstance(le, dict)),
                default=0,
            )
            if max_top >= 2:
                _emit(findings, "WARN", "SUSPICIOUS_NUTRITION_EXEMPTION", pid, eid, path,
                      f"声明 single_ingredient_unprocessed 豁免，但配料树含 {max_top} 项顶层原料，请核实是否确属单一原料未加工豁免")
        elif cat in ("small_package_area", "small_daily_intake"):
            _emit(findings, "INFO", "VERIFY_EXEMPTION_EVIDENCE", pid, eid, path,
                  f"声明 {cat} 法定豁免，请对照原图确认外包装确未印刷营养成分表且符合面积/食用量条件")

        claims_joined = " ".join(str(c) for c in (attrs.get("claims_text") or []) if str(c).strip())
        m_claim = _NUTRITION_CLAIM_RE.search(claims_joined)
        if m_claim:
            _emit(findings, "WARN", "EXEMPT_WITH_NUTRITION_CLAIM", pid, eid, path,
                  f"豁免营养成分表记录同时含疑似营养声称 {m_claim.group(0)!r}；依 GB 28050 作营养声称通常丧失豁免资格，请看图核实")
        return

    profile_id = str(core.get("regulatory_profile") or "")
    rows = [r for r in ((core.get("nutrition_declared") or {}).get("rows") or []) if isinstance(r, dict)]
    by_nid: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if isinstance(row.get("nutrient"), str):
            by_nid.setdefault(row["nutrient"], []).append(row)

    if profile_id.startswith("CN/"):
        try:
            mandatory = get_profile(profile_id).get("mandatory_nutrients", [])
        except KeyError:
            mandatory = []
        missing = [nid for nid in mandatory if nid not in by_nid]
        if missing:
            _emit(findings, "ERROR", "MISSING_MANDATORY_NUTRIENTS", pid, eid, path,
                  f"{profile_id} 缺少必填营养素行: {', '.join(missing)}")

    def _first_g(nid: str) -> tuple[dict[str, Any], Decimal] | None:
        for r in by_nid.get(nid, []):
            if str(r.get("unit") or "") == "g":
                v = _parse_dec(r.get("value"))
                if v is not None:
                    return r, v
        return None

    g_rows = {k: _first_g(k) for k in (
        "protein", "fat_total", "fat_saturated", "fat_trans",
        "carbs_available", "carbs_total", "sugars_total", "sugars_added", "dietary_fiber",
    )}
    for sub_key, tot_key, label in _SUBSET_NUTRIENT_RULES:
        sub_item, tot_item = g_rows[sub_key], g_rows[tot_key]
        if (
            sub_item and tot_item
            and _is_lower_bounded_or_exact(sub_item[0])
            and _is_upper_bounded_or_exact(tot_item[0])
            and sub_item[1] > tot_item[1]
        ):
            _emit(findings, "ERROR", "NUTRIENT_SUBSET_EXCEEDS_TOTAL", pid, eid, path,
                  f"{label} ({sub_item[1]}g) 大于 {tot_key} ({tot_item[1]}g)")

    fat_tot, fat_sat, fat_trans = g_rows["fat_total"], g_rows["fat_saturated"], g_rows["fat_trans"]
    if (
        fat_tot and fat_sat and fat_trans
        and _is_lower_bounded_or_exact(fat_sat[0])
        and _is_lower_bounded_or_exact(fat_trans[0])
        and _is_upper_bounded_or_exact(fat_tot[0])
        and fat_sat[1] <= fat_tot[1] and fat_trans[1] <= fat_tot[1]
        and (fat_sat[1] + fat_trans[1]) > fat_tot[1]
    ):
        _emit(findings, "ERROR", "NUTRIENT_SUBSET_EXCEEDS_TOTAL", pid, eid, path,
              f"饱和脂肪+反式脂肪 ({fat_sat[1]}+{fat_trans[1]}g) 大于总脂肪 ({fat_tot[1]}g)")

    energy_rows = by_nid.get("energy", [])
    factor = _basis_to_100_factor(core)
    if energy_rows and factor is not None:
        all_zero = all((_parse_dec(r.get("value")) == Decimal("0")) and _is_upper_bounded_or_exact(r) for r in energy_rows)
        if all_zero:
            pr_val = g_rows["protein"][1] if (g_rows["protein"] and _is_lower_bounded_or_exact(g_rows["protein"][0])) else Decimal("0")
            ft_val = fat_tot[1] if (fat_tot and _is_lower_bounded_or_exact(fat_tot[0])) else Decimal("0")
            carb_item = g_rows["carbs_available"] or g_rows["carbs_total"]
            cb_val = carb_item[1] if (carb_item and _is_lower_bounded_or_exact(carb_item[0])) else Decimal("0")
            est_kj = (pr_val * Decimal("17") + ft_val * Decimal("37") + cb_val * Decimal("17")) * factor
            if est_kj > Decimal("25"):
                _emit(findings, "ERROR", "ZERO_ENERGY_WITH_MACROS", pid, eid, path,
                      f"标注能量为 0，但实报产能宏量折算每 100g/ml 约 {est_kj.quantize(Decimal('0.1'))} kJ")

    sugars = g_rows["sugars_total"]
    if sugars and factor is not None and _is_lower_bounded_or_exact(sugars[0]):
        sugars_per_100 = sugars[1] * factor
        if sugars_per_100 >= Decimal("5"):
            masked = _SUGAR_INTERFERENCE_MASK_RE.sub(" ", _SEASONING_HEAD_MASK_RE.sub(" ", raw_ing))
            if raw_ing.strip() and not _REAL_SUGAR_SOURCE_RE.search(masked):
                _emit(findings, "WARN", "HIGH_SUGAR_NO_SUGAR_SOURCE", pid, eid, path,
                      f"实报糖含量较高 ({sugars_per_100.quantize(Decimal('0.1'))}g/100)，但配料文本中未检索到明显糖源（已屏蔽调味料词头与酸味剂/糖醇干扰词），请核对是否漏抄配料")


def _check_parties_and_sc(
    doc: dict[str, Any], *, pid: str, eid: str | None, path: str, findings: list[AuditFinding]
) -> None:
    core = doc.get("core") or {}
    attrs = doc.get("attributes") or {}
    profile_id = str(core.get("regulatory_profile") or "")
    origin_country = str((attrs.get("origin") or {}).get("country") or "").strip().upper()
    parties = [p for p in (attrs.get("parties") or []) if isinstance(p, dict)]
    is_cn_domestic = profile_id.startswith("CN/") and origin_country in ("", "CN")

    for idx, party in enumerate(parties):
        role = str(party.get("role") or "")
        name = str(party.get("name") or "").strip()
        lic = str(party.get("license") or "").strip()
        addr = str(party.get("address") or "").strip()
        if not lic or FOREIGN_REG_LICENSE_RE.match(lic):
            continue
        if lic.upper().startswith(("SC", "QS")) or (is_cn_domestic and role == "manufacturer"):
            if not SC_LICENSE_RE.match(lic):
                _emit(findings, "ERROR", "INVALID_SC_FORMAT", pid, eid, path,
                      f"parties[{idx}] ({name or role}) 生产许可证格式非法 {lic!r}，须为 SC + 14 位数字")
                continue
            prov_code, city_code, county_code = lic[5:7], lic[7:9], lic[9:11]
            expected_prov = CN_PROVINCE_CODES.get(prov_code)
            if expected_prov is None:
                _emit(findings, "WARN", "SC_UNKNOWN_PROVINCE", pid, eid, path,
                      f"parties[{idx}] 许可证 {lic} 省码 {prov_code!r} 未在 GB/T 2260 省级代码表中")
            else:
                if city_code == "00" and prov_code not in {"11", "12", "31", "50"} and county_code != "90":
                    _emit(findings, "WARN", "SC_SUSPICIOUS_ADMIN_CODE", pid, eid, path,
                          f"parties[{idx}] 许可证 {lic} 市级区划码为 '00'，请核对是否错抄")
                addr_prov = _extract_address_province(addr) if addr else None
                if addr_prov and addr_prov != expected_prov:
                    _emit(findings, "ERROR", "SC_PROVINCE_MISMATCH", pid, eid, path,
                          f"parties[{idx}] 许可证 {lic} 省码 {prov_code}({expected_prov}) 与同条地址省份 {addr_prov!r} 矛盾")

    if not is_cn_domestic:
        return
    manufacturers = [p for p in parties if p.get("role") == "manufacturer"]
    importers = [p for p in parties if p.get("role") == "importer"]
    if not manufacturers and not importers:
        _emit(findings, "WARN", "CN_MISSING_MANUFACTURER", pid, eid, path,
              "CN 法规记录缺少 manufacturer（或 importer）主体信息")
        return
    for idx, mfg in enumerate(manufacturers):
        m_lic = str(mfg.get("license") or "").strip()
        if FOREIGN_REG_LICENSE_RE.match(m_lic):
            continue
        m_name = str(mfg.get("name") or f"manufacturer[{idx}]").strip()
        m_addr = str(mfg.get("address") or "").strip()
        if not m_addr:
            _emit(findings, "WARN", "CN_MANUFACTURER_MISSING_ADDRESS", pid, eid, path,
                  f"CN 生产商 {m_name!r} 缺少 address 厂址")
        elif _TRUNCATED_SUFFIX_RE.search(m_addr) or (m_addr.endswith("区") and not _NON_ADMIN_ZONE_SUFFIX_RE.search(m_addr)):
            _emit(findings, "WARN", "CN_MANUFACTURER_TRUNCATED_ADDRESS", pid, eid, path,
                  f"CN 生产商 {m_name!r} 地址疑似截断至行政区县层级: {m_addr!r}")
        if not m_lic:
            _emit(findings, "WARN", "CN_MANUFACTURER_MISSING_SC", pid, eid, path,
                  f"CN 生产商 {m_name!r} 缺少 SC 生产许可证编号")


def _walk_ingredient_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        collected.append(node)
        if isinstance(node.get("children"), list):
            collected.extend(_walk_ingredient_nodes(node["children"]))
    return collected


def _effective_ingredients_tree(doc: dict[str, Any]) -> list[dict[str, Any]]:
    core = doc.get("core") or {}
    tree = core.get("ingredients_tree")
    if isinstance(tree, list) and tree:
        return tree
    profile_id = str(core.get("regulatory_profile") or "CN/GB28050-2011")
    parsed: list[dict[str, Any]] = []
    for item in (doc.get("attributes") or {}).get("ingredients_text") or []:
        if isinstance(item, dict) and item.get("lang") and item.get("text"):
            try:
                nodes = parse_ingredients_semantic(str(item["text"]), lang=str(item["lang"]), profile_id=profile_id)
                parsed.append({"lang": str(item["lang"]), "nodes": nodes})
            except Exception:
                continue
    return parsed


def _check_ingredients_and_allergens(
    doc: dict[str, Any], *, pid: str, eid: str | None, path: str, findings: list[AuditFinding]
) -> None:
    core = doc.get("core") or {}
    all_nodes: list[dict[str, Any]] = []
    for lang_entry in _effective_ingredients_tree(doc):
        if isinstance(lang_entry, dict) and isinstance(lang_entry.get("nodes"), list):
            all_nodes.extend(_walk_ingredient_nodes(lang_entry["nodes"]))

    inferred: set[str] = set()
    candidates: list[str] = []
    seen: set[str] = set()
    for node in all_nodes:
        inferred.update(str(a) for a in (node.get("allergens") or []))
        name = str(node.get("name") or "").strip()
        if name:
            inferred.update(match_allergens_in_name(name))
        if (
            node.get("is_additive") is True and not node.get("ins") and not node.get("children")
            and name and name.lower() not in FUNCTIONAL_CLASS_TERMS and "添加剂" not in name and name not in seen
        ):
            seen.add(name)
            candidates.append(name)

    declared = ((core.get("allergens_declared") or {}).get("contains")) or []
    unmatched = [str(a) for a in declared if str(a) not in inferred]
    if unmatched:
        _emit(findings, "WARN", "DECLARED_ALLERGEN_UNMATCHED_IN_INGREDIENTS", pid, eid, path,
              f"core.allergens_declared.contains 声明致敏原在配料树（含子配料）中未匹配到: {', '.join(unmatched)}")
    if candidates:
        _emit(findings, "INFO", "UNMAPPED_ADDITIVE_CANDIDATES", pid, eid, path,
              f"未映射 INS 的候选添加剂词: {', '.join(candidates)}")


def _contains_modifier(haystack: str, modifier: str) -> bool:
    if modifier.isascii():
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(modifier)}(?![A-Za-z0-9])", haystack, re.IGNORECASE))
    return modifier in haystack


def _check_attributes_and_id(
    doc: dict[str, Any], *, pid: str, eid: str | None, path: str, findings: list[AuditFinding]
) -> None:
    core = doc.get("core") or {}
    attrs = doc.get("attributes") or {}
    claims = [str(c) for c in (attrs.get("claims_text") or []) if str(c).strip()]
    ing_texts = [str(it.get("text") or "") for it in (attrs.get("ingredients_text") or []) if isinstance(it, dict) and it.get("text")]
    prod_names = [str(it.get("text") or "") for it in (attrs.get("product_name") or []) if isinstance(it, dict) and it.get("text")]
    origin_raw = str((attrs.get("origin") or {}).get("raw_text") or "")
    pool = "\n".join([*ing_texts, *claims, *prod_names, origin_raw])

    if attrs.get("special_indicators") is not None:
        _emit(findings, "ERROR", "LEGACY_ATTRIBUTES_SPECIAL_INDICATORS", pid, eid, path,
              "v0.3 已将 special_indicators 从 attributes 升格至 core.special_indicators，请迁移字段位置")

    for idx, ind in enumerate(core.get("special_indicators") or []):
        if not isinstance(ind, dict):
            continue
        ind_name = str(ind.get("name") or "")
        for mod in INDICATOR_MODIFIERS:
            if _contains_modifier(ind_name, mod) and not _contains_modifier(pool, mod):
                _emit(findings, "WARN", "UNSUPPORTED_INDICATOR_MODIFIER", pid, eid, path,
                      f"core.special_indicators[{idx}].name ({ind_name!r}) 含限定修饰词 {mod!r}，未在配料/宣称/品名/产地文本中出现")

    if pid.startswith("opf:"):
        in_store = attrs.get("in_store_barcodes") or []
        evidence = [ev for ev in (doc.get("evidence") or []) if isinstance(ev, dict)]
        has_full_back = any(ev.get("type") == "label_photo" and ev.get("region") == "full_back_label" for ev in evidence)
        reasons = " ".join(str(r.get("reason") or "") for r in (doc.get("revisions") or []) if isinstance(r, dict))
        if not in_store and not has_full_back and not _NO_BARCODE_PROOF_RE.search("\n".join([*claims, reasons])):
            _emit(findings, "WARN", "SYNTHETIC_OPF_ID_WITHOUT_PROOF", pid, eid, path,
                  "使用合成 opf: ID，但缺少 in_store_barcodes、full_back_label 整背照或无条码说明")

    if claims:
        _emit(findings, "INFO", "VERIFY_CLAIMS_VERBATIM", pid, eid, path,
              f"请对照裁剪原图逐字核对 claims_text ({len(claims)} 条): " + " | ".join(claims))

    track = str(doc.get("track") or "")
    market = track.split("/", 1)[0] if "/" in track else ""
    origin_country = str((attrs.get("origin") or {}).get("country") or "").strip().upper()
    if market and market != "CN":
        ascii_names = [
            f"{it.get('lang')}:{it.get('text')}"
            for it in (attrs.get("product_name") or [])
            if isinstance(it, dict) and isinstance(it.get("text"), str) and _PURE_ASCII_LATIN_RE.match(it["text"].strip())
        ]
        if ascii_names or (origin_country and origin_country != market):
            extra = f"，含拉丁字母品名 {ascii_names}" if ascii_names else ""
            _emit(findings, "INFO", "FOREIGN_TRACK_MIXED_SCRIPT_CHECK", pid, eid, path,
                  f"非本土 track={track!r}（origin={origin_country or '未填'}）{extra}；请确认未混拼进口加贴纸或漏录贴纸配料/营养")


def _check_evidence_and_media(
    doc: dict[str, Any], *, pid: str, eid: str | None, path: str,
    media_root: Path | None, require_photo: bool, findings: list[AuditFinding],
) -> None:
    evidence = [ev for ev in (doc.get("evidence") or []) if isinstance(ev, dict)]
    photos = [ev for ev in evidence if ev.get("type") == "label_photo"]
    if not photos:
        _emit(findings, "ERROR" if require_photo else "WARN", "NO_LABEL_PHOTO", pid, eid, path,
              "缺少 label_photo 实拍裁剪图证据（仅含文字报告或无照片）")
        return

    region_notes: list[str] = []
    media_store = (media_root / "media") if media_root and (media_root / "media").is_dir() else media_root
    for ev in photos:
        region, sha = str(ev.get("region") or ""), public_image_sha(ev)
        if region in ("barcode_net_content", "other"):
            region_notes.append(f"{region}({sha[:12]})")
        if media_store is not None and len(sha) == 64:
            blob_path = media_store / sha[0:2] / sha[2:4] / f"{sha}.webp"
            if blob_path.is_file():
                try:
                    raw = blob_path.read_bytes()
                    info = inspect_webp_bytes(raw)
                except ValueError:
                    continue
                w, h = int(info["width"]), int(info["height"])
                size_bytes, bpp = len(raw), len(raw) / float(w * h)
                if 80 <= min(w, h) <= 185 and max(w, h) >= 400 and size_bytes < 8192 and bpp < 0.10:
                    _emit(findings, "WARN", "LOW_RES_BLURRY_CROP", pid, eid, path,
                          f"图片 {sha[:12]}.webp ({region}) 为低分辨率模糊窄长裁剪图 ({w}x{h}, {size_bytes}B, {bpp:.3f} B/px)，请看图核查关键字符是否可辨")

    if region_notes:
        _emit(findings, "INFO", "VERIFY_REGION_SEMANTICS", pid, eid, path,
              f"请看图核查特殊 region 语义及隐私合规: {', '.join(region_notes)}")


def canonical_nutrition_signature(doc: dict[str, Any]) -> str:
    """Return a canonical JSON string for packaging_code + nutrition cross-product deduplication."""
    core = doc.get("core") or {}
    raw_decl = core.get("nutrition_declared")
    if raw_decl is None:
        ex = core.get("nutrition_exemption") or {}
        inds = sorted(
            [
                canonicalize_special_indicator(it)
                for it in (core.get("special_indicators") or [])
                if isinstance(it, dict)
            ],
            key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        return json.dumps(
            {
                "nutrition_declared": None,
                "nutrition_exemption": {"category": str(ex.get("category") or "").strip()},
                "special_indicators": inds,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    decl = raw_decl if isinstance(raw_decl, dict) else {}
    basis = decl.get("basis") or {}
    rows_out: list[dict[str, Any]] = []
    for row in sorted((decl.get("rows") or []), key=nutrient_row_sort_key):
        if not isinstance(row, dict):
            continue
        item: dict[str, Any] = {
            "nutrient": str(row.get("nutrient") or ""),
            "value": format_canonical_decimal(row.get("value", "0")),
            "unit": str(row.get("unit") or ""),
        }
        if row.get("qualifier") and row.get("qualifier") != "=":
            item["qualifier"] = str(row["qualifier"])
        if row.get("nrv_pct") is not None:
            item["nrv_pct"] = format_canonical_decimal(row["nrv_pct"])
        rows_out.append(item)
    b_sig = {
        "value": format_canonical_decimal(basis.get("value", "0")) if basis.get("value") is not None else "",
        "unit": str(basis.get("unit") or ""),
    }
    return json.dumps({"basis": b_sig, "rows": rows_out}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def audit_edition_doc(
    doc: dict[str, Any], *, path: str = "<edition>", media_root: Path | None = None,
    require_photo: bool = False, product_meta: dict[str, Any] | None = None,
) -> list[AuditFinding]:
    """Audit a single v0.3 EditionRecord (or draft JSON) and return ERROR/WARN/INFO findings."""
    if not isinstance(doc, dict) or "merged_into" in doc:
        return []
    if (doc.get("lifecycle") or {}).get("state") == "retracted":
        return []
    pid = str(doc.get("id") or (product_meta or {}).get("id") or "<unknown>")
    eid = str(doc["edition_id"]) if doc.get("edition_id") else None
    findings: list[AuditFinding] = []
    _check_nutrition(doc, pid=pid, eid=eid, path=path, findings=findings)
    _check_parties_and_sc(doc, pid=pid, eid=eid, path=path, findings=findings)
    _check_ingredients_and_allergens(doc, pid=pid, eid=eid, path=path, findings=findings)
    _check_attributes_and_id(doc, pid=pid, eid=eid, path=path, findings=findings)
    _check_evidence_and_media(doc, pid=pid, eid=eid, path=path, media_root=media_root,
                              require_photo=require_photo, findings=findings)
    return findings


def _check_cross_product_duplicates(editions: list[tuple[str, dict[str, Any]]], findings: list[AuditFinding]) -> None:
    buckets: dict[tuple[str, str], list[tuple[str, str, str | None]]] = {}
    for path, doc in editions:
        pkg_code = str((doc.get("attributes") or {}).get("packaging_code") or "").strip()
        pid = str(doc.get("id") or "")
        if not pkg_code or not pid:
            continue
        try:
            nut_sig = canonical_nutrition_signature(doc)
        except Exception:
            continue
        eid = str(doc["edition_id"]) if doc.get("edition_id") else None
        buckets.setdefault((pkg_code, nut_sig), []).append((pid, path, eid))

    for (pkg_code, _nut_sig), entries in sorted(buckets.items()):
        unique_pids = sorted({pid for pid, _p, _e in entries})
        if len(unique_pids) < 2:
            continue
        peers = ", ".join(unique_pids)
        for pid, path, eid in entries:
            _emit(findings, "WARN", "DUPLICATE_PACKAGING_CODE_AND_NUTRITION", pid, eid, path,
                  f"包材码 {pkg_code!r} 与营养表在多个不同商品间完全相同: {peers}")


def _iter_edition_docs(target: Path) -> list[tuple[str, dict[str, Any], dict[str, Any] | None]]:
    if target.is_file():
        return [(str(target), json.loads(target.read_text(encoding="utf-8")), None)]
    docs: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
    pjsons = [target / "product.json"] if (target / "product.json").is_file() else sorted(target.rglob("product.json"))
    for pjson in pjsons:
        meta = json.loads(pjson.read_text(encoding="utf-8"))
        ed_dir = pjson.parent / "editions"
        if ed_dir.is_dir():
            for ef in sorted(ed_dir.glob("*.json")):
                docs.append((str(ef), json.loads(ef.read_text(encoding="utf-8")), meta))
    return docs


def audit_products_root(
    target: Path, *, media_root: Path | None = None, require_photo: bool = False
) -> list[AuditFinding]:
    """Audit a products root, product directory, edition file, or draft JSON file."""
    findings: list[AuditFinding] = []
    loaded: list[tuple[str, dict[str, Any]]] = []
    for path, doc, meta in _iter_edition_docs(Path(target)):
        if isinstance(doc, dict) and "merged_into" not in doc and (doc.get("lifecycle") or {}).get("state") != "retracted":
            loaded.append((path, doc))
        findings.extend(audit_edition_doc(doc, path=path, media_root=media_root,
                                          require_photo=require_photo, product_meta=meta))
    if len(loaded) > 1:
        _check_cross_product_duplicates(loaded, findings)
    return findings


def register_audit_subparser(sub: argparse._SubParsersAction[Any]) -> None:
    p = sub.add_parser(
        "audit",
        help="Run deep semantic, SC/address, nutrition, allergen, and media-quality audit (ERROR/WARN/INFO)",
    )
    p.add_argument("paths", nargs="+", help="Products root, product directory, edition JSON, or draft JSON")
    p.add_argument("--media-dir", help="Local opf-media repository root or media/ directory for WebP quality checks")
    p.add_argument("--strict", action="store_true", help="Exit non-zero on WARN findings as well as ERROR")
    p.add_argument("--require-photo", action="store_true", help="Promote NO_LABEL_PHOTO from WARN to ERROR")
    p.add_argument("--json", action="store_true", help="Output audit report as JSON")
    p.set_defaults(func=cmd_audit)


def cmd_audit(args: argparse.Namespace) -> int:
    media_root = Path(args.media_dir) if getattr(args, "media_dir", None) else None
    all_findings: list[AuditFinding] = []
    for raw in args.paths:
        p = Path(raw)
        if not p.exists():
            _emit(all_findings, "ERROR", "PATH_NOT_FOUND", "<unknown>", None, str(p), f"Path does not exist: {p}")
            continue
        try:
            all_findings.extend(audit_products_root(p, media_root=media_root,
                                                    require_photo=bool(getattr(args, "require_photo", False))))
        except Exception as exc:
            _emit(all_findings, "ERROR", "AUDIT_PARSE_ERROR", "<unknown>", None, str(p), f"Failed to audit {p}: {exc}")

    counts = {lvl: sum(1 for f in all_findings if f.severity == lvl) for lvl in ("ERROR", "WARN", "INFO")}
    strict = bool(getattr(args, "strict", False))
    failed = counts["ERROR"] > 0 or (strict and counts["WARN"] > 0)

    if getattr(args, "json", False):
        print(json.dumps({"ok": not failed, "strict": strict, "counts": counts,
                          "findings": [f.to_dict() for f in all_findings]}, ensure_ascii=False, indent=2))
    else:
        for f in all_findings:
            print(f.format_line(), file=sys.stderr if f.severity == "ERROR" else sys.stdout)
        print(f"AUDIT {'FAIL' if failed else 'OK'}: {counts['ERROR']} error(s), {counts['WARN']} warn(s), {counts['INFO']} info(s)",
              file=sys.stderr if failed else sys.stdout)
    return 1 if failed else 0
