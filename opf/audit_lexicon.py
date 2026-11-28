"""Lexical patterns, province tables, and regulatory heuristics for the OPF v0.3 audit engine."""

from __future__ import annotations

import re

SC_LICENSE_RE = re.compile(r"^SC[0-9]{14}$")
FOREIGN_REG_LICENSE_RE = re.compile(r"^C[A-Z]{3}[0-9]{14}$")

# Corporate / business registration numbers (e.g. Malaysia SSM, Singapore UEN, Australia ABN/ACN)
# that belong in `parties[].name` verbatim rather than the food-safety `parties[].license` field.
COMPANY_REG_NO_RE = re.compile(
    r"^(?:"
    r"[0-9]{12}\s*(?:[（(]\s*[0-9]{5,7}-[A-Za-z]\s*[）)])?"
    r"|[0-9]{5,7}-[A-Za-z]"
    r"|LLP[0-9]{7}-[A-Za-z]{3}"
    r"|(?:19|20)[0-9]{7}[A-Z]"
    r"|[0-9]{8}[A-Z]"
    r"|T[0-9]{2}[A-Z]{2}[0-9]{4}[A-Z]"
    r"|(?:ABN|ACN|UEN|ROC)\b.*"
    r"|(?:co\.?\s*reg|company\s*reg|business\s*reg)\b.*"
    r")$",
    re.IGNORECASE,
)

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
ADDR_PROVINCE_RE = re.compile(
    r"^(?:中国)?[\s（(]*(?P<prov>"
    + "|".join(re.escape(p) for p in _PROVINCE_NAMES_SORTED)
    + r")(?P<suffix>省|市|维吾尔自治区|壮族自治区|回族自治区|自治区|特别行政区)?"
)
STREET_SUFFIX_RE = re.compile(r"^(?:东|西|南|北|中)?(?:路|街|道|巷|弄|大道)")
TRUNCATED_SUFFIX_RE = re.compile(r"(?:省|市|县|旗|盟|自治州)$")
NON_ADMIN_ZONE_SUFFIX_RE = re.compile(
    r"(?:开发区|工业区|产业区|园区|厂区|保税区|试验区|功能区|聚集区|集聚区|管理区|示范区|合作区|度假区|商务区|高新区|科技区|自贸区|新区|[A-Za-z0-9]区)$"
)

SEASONING_HEAD_MASK_RE = re.compile(r"[\w\u4e00-\u9fff-]*味(?:复合|複合)?(?:调味|調味)(?:料|粉|酱|醬|汁)")
SUGAR_INTERFERENCE_MASK_RE = re.compile(
    r"(?:DL-苹果酸|L-苹果酸|苹果酸|DL-蘋果酸|L-蘋果酸|蘋果酸|柠檬酸钠|柠檬酸|檸檬酸鈉|檸檬酸|乳酸|果胶|果膠|黄原胶|黃原膠|赤藓糖醇|赤蘚糖醇|木糖醇|麦芽糖醇|麥芽糖醇|山梨糖醇|异麦芽酮糖醇|異麥芽酮糖醇|乳糖醇|三氯蔗糖|蔗糖素|安赛蜜|安賽蜜|醋磺內酯鉀|阿斯巴甜|甜菊糖苷|罗汉果甜苷|羅漢果甜苷|纽甜|甜蜜素|糖精钠|구연산|사과산|젖산|펙틴|잔탄검|에리스리톨|자일리톨|말티톨|소비톨|수크랄로스|아세설팜칼륨|아스파탐|스테비올배당체|알룰로스|\basid\s+sitrik\b|\basid\s+malik\b|\basid\s+laktik\b|\bsukralosa\b|\beritritol\b|\bsorbitol\b|\bxilitol\b)",
    re.IGNORECASE,
)
REAL_SUGAR_SOURCE_RE = re.compile(
    r"(?:白砂糖|砂糖|绵白糖|綿白糖|冰糖|红糖|紅糖|黑糖|黄糖|黃糖|蔗糖|果糖|葡萄糖|麦芽糖|麥芽糖|乳糖|糖浆|糖漿|蜂蜜|海藻糖|异麦芽酮糖|異麥芽酮糖|低聚果糖|低聚异麦芽糖|低聚異麥芽糖|低聚半乳糖"
    r"|浓缩[^\s，、（）()]*?(?:汁|浆|原浆|泥)|濃縮[^\s，、（）()]*?(?:汁|漿|原漿|泥)"
    r"|果酱|果醬|果泥|果浆|果漿|原浆|原漿|果汁"
    r"|生牛乳|牛乳|牛奶|鲜奶|鮮奶|乳粉|奶粉|炼乳|煉乳|煉奶|乳清"
    r"|红枣|紅棗|椰枣|椰棗|葡萄干|葡萄乾|蓝靛果|草莓|蓝莓|藍莓|蔓越莓|黑莓|树莓|樹莓"
    r"|凤梨|鳳梨|菠萝|菠蘿|苹果|蘋果|芒果|水蜜桃|黄桃|黃桃|白桃|石榴|香蕉|百香果|西番莲|荔枝|龙眼|龍眼|桂圆|桂圓|猕猴桃|獼猴桃|奇异果|奇異果|山楂|无花果|無花果|桑葚|樱桃|櫻桃|西梅|乌梅|李梅|杨梅|楊梅|柑橘|蜜橘|沃柑|甜橙|脐橙|葡萄|哈密瓜|甜瓜|西瓜"
    r"|설탕|백설탕|흑설탕|황설탕|원당|사탕수수당|과당|액상과당|포도당|맥아당|유당|물엿|조청|시럽|올리고당|벌꿀|꿀|과즙|농축액|퓨레|우유|원유|분유|연유|유청"
    r"|\bsugar\b|\bsucrose\b|\bfructose\b|\bglucose\b|\bsyrup\b|\bhoney\b|\blactose\b|\bmilk\b|\bwhey\b|\bjuice\b|\bpuree\b|\bconcentrate\b|\bdate\b|\bpineapple\b|\bmango\b|\bapple\b|\bpomegranate\b|\bbanana\b|\bpeach\b|\bpear\b|\bgrape\b"
    r"|\bgula\b|\bsirap\b|\bmadu\b|\bglukosa\b|\bfruktosa\b|\blaktosa\b|\bsusu\b|\bdadih\b|\bjus\b|\bpuri\b|\bkurma\b|\bnanas\b|\bmangga\b|\bepal\b|\bdelima\b|\bpisang\b)",
    re.IGNORECASE,
)
WATER_FORBIDDEN_ING_RE = re.compile(
    r"(?:白砂糖|砂糖|绵白糖|綿白糖|冰糖|红糖|紅糖|蔗糖|果糖|葡萄糖|糖浆|糖漿|蜂蜜|赤藓糖醇|赤蘚糖醇|木糖醇|麦芽糖醇|麥芽糖醇|三氯蔗糖|蔗糖素|安赛蜜|安賽蜜|醋磺內酯鉀|阿斯巴甜|甜菊糖苷|罗汉果甜苷|羅漢果甜苷|食用香精|食品用香精|香精|香料|浓缩[^\s，、（）()]*?(?:汁|浆|泥)|濃縮[^\s，、（）()]*?(?:汁|漿|泥)|果汁|生牛乳|牛乳|牛奶|鮮奶|乳粉|奶粉|茶粉|速溶茶|설탕|과당|시럽|수크랄로스|에리스리톨|합성향료|천연향료|과즙|우유|\bsugar\b|\bsyrup\b|\bsucralose\b|\berythritol\b|\bflavor\b|\bflavour\b|\bjuice\b|\bmilk\b|\bgula\b|\bsirap\b|\bperisa\b|\bsusu\b|\bjus\b)",
    re.IGNORECASE,
)
TEA_COFFEE_FORBIDDEN_ING_RE = re.compile(
    r"(?:白砂糖|砂糖|绵白糖|綿白糖|冰糖|红糖|紅糖|黑糖|蔗糖|果糖|葡萄糖|麦芽糖|麥芽糖|糖浆|糖漿|蜂蜜|生牛乳|牛乳|牛奶|鮮奶|乳粉|奶粉|炼乳|煉乳|煉奶|稀奶油|忌廉|奶油|牛油|植脂末|奶精|설탕|원당|물엿|시럽|우유|분유|연유|유크림|식물성크림|프리마|\bsugar\b|\bsucrose\b|\bfructose\b|\bsyrup\b|\bhoney\b|\bmilk\b|\bcream\b|\bcreamer\b|\bgula\b|\bsirap\b|\bmadu\b|\bsusu\b|\bkrim\b|\bkrimer\b)",
    re.IGNORECASE,
)
NUTRITION_CLAIM_RE = re.compile(
    r"(?:无糖|無糖|零糖|0糖|低糖|无蔗糖|無蔗糖|零卡|0卡|低卡|零能量|0能量|低能量|零脂|0脂|无脂|無脂|低脂|脱脂|脫脂|高钙|高鈣|富含钙|富含鈣|低钠|低鈉|无钠|無鈉|高蛋白|富含蛋白|高膳食纤维|高膳食纖維|富含膳食纤维|富含膳食纖維|高纤|高纖|무설탕|무당|제로슈거|저당|제로칼로리|저칼로리|무지방|저지방|고단백|고칼슘|저나트륨|\bsugar[- ]free\b|\bzero[- ]sugar\b|\blow[- ]sugar\b|\bfat[- ]free\b|\blow[- ]fat\b|\bhigh[- ]protein\b|\bhigh[- ]calcium\b|\blow[- ]sodium\b|\btanpa\s+gula\b|\brendah\s+gula\b|\brendah\s+lemak\b|\btinggi\s+protein\b|\btinggi\s+kalsium\b|\brendah\s+natrium\b)",
    re.IGNORECASE,
)

# Splits `allergens_raw_text` at precautionary cross-contact clauses so only explicit "contains" text is matched
PRECAUTIONARY_ALLERGEN_SPLIT_RE = re.compile(
    r"(?:可能含|或含|此生产线|本生产线|同生产线|共线|生产设备|车间也|工廠亦|此生產線|本生產線|可能含有"
    r"|\bmay\s+contain\b|\bproduced\s+in\s+a\s+facility\b|\bmanufactured\s+on\b|\bshared\s+equipment\b"
    r"|\bmungkin\s+mengandungi\b|\bdiproses\s+di\s+fasiliti\b"
    r"|이\s*제품은.*시설에서|혼입\s*가능)",
    re.IGNORECASE,
)

# Unexpanded compound ingredients that legitimately carry allergens declared in the allergen statement
COMPOUND_ALLERGEN_CARRIER_RE = re.compile(
    r"(?:酱油|醬油|豆瓣|黄豆酱|黃豆醬|酿造酱|釀造醬|甜面酱|甜麵醬|味噌|蚝油|蠔油|蚝汁|蠔汁|鸡精|雞精"
    r"|调味料|調味料|调味粉|調味粉|调味酱|調味醬|调味液|調味液|原汤|原湯|高汤|高湯"
    r"|香精|香料|麦芽糊精|麥芽糊精|磷脂|起酥油|人造黄油|人造奶油|玛琪琳|植脂末|奶精|明胶|明膠"
    r"|\bsoy\s+sauce\b|\boyster\s+sauce\b|\bseasoning\b|\bflavouring\b|\bflavoring\b|\bflavour\b|\bflavor\b"
    r"|\bbouillon\b|\bstock\b|\bshortening\b|\bmargarine\b|\bgelatin\b|\bgelatine\b|\blecithin\b"
    r"|\bkicap\b|\bsos\s+tiram\b|\bperencah\b|\bperisa\b|간장|된장|고추장|복합조미식품|향료)",
    re.IGNORECASE,
)

# Regionally permitted additives / generic flavouring terms that have no Codex INS number assigned
REGIONAL_NO_INS_ADDITIVES: frozenset[str] = frozenset(
    s.lower()
    for s in (
        "红曲红",
        "紅曲紅",
        "红曲黄色素",
        "紅曲黃色素",
        "红曲米",
        "ε-聚赖氨酸",
        "ε-聚赖氨酸盐酸盐",
        "纳他霉素",
        "茶多酚",
        "竹叶抗氧化物",
        "甘草抗氧化物",
        "迷迭香提取物",
        "食用香精",
        "食品用香精",
        "食用香料",
        "食用香精香料",
        "香精",
        "香料",
        "flavour",
        "flavours",
        "flavor",
        "flavors",
        "natural flavour",
        "natural flavor",
        "natural flavours",
        "natural flavors",
        "artificial flavor",
        "artificial flavour",
        "perisa",
        "bahan perisa",
    )
)

INDICATOR_MODIFIERS: tuple[str, ...] = (
    "新西兰", "澳洲", "澳大利亚", "比利时", "法国", "日本", "北海道", "宇治",
    "进口", "有机", "NFC", "A2", "冷萃", "头道", "特级", "野生",
)
NO_BARCODE_PROOF_RE = re.compile(
    r"(?:无条码|无零售条码|散装|店内码|未印条码|no[\s_-]*barcode|bulk|in-store)",
    re.IGNORECASE,
)
PURE_ASCII_LATIN_RE = re.compile(r"^[A-Za-z0-9\s.,'&/+()_-]+$")
NON_EXACT_LOWER_QUALIFIERS = frozenset({"<", "<=", "trace"})
NON_EXACT_UPPER_QUALIFIERS = frozenset({">", ">="})

SUBSET_NUTRIENT_RULES: tuple[tuple[str, str, str], ...] = (
    ("fat_saturated", "fat_total", "饱和脂肪"),
    ("fat_trans", "fat_total", "反式脂肪"),
    ("sugars_total", "carbs_available", "糖"),
    ("sugars_total", "carbs_total", "糖"),
    ("sugars_added", "sugars_total", "添加糖"),
    ("dietary_fiber", "carbs_total", "膳食纤维"),
)
