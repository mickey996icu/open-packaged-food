"""Multilingual lexical tables and structural character sets for OPF ingredient parsing."""

from __future__ import annotations

import re

_QUAL_UNITS = r"(?:%|％|g/L|mg/kg|mg/L|g/kg|g/100g|ml/100ml|g|mg|ml)"
_QUAL_CMP = r"(?:[≥≤><~≈]|>=|<=|不少于|不低于|不超过|不少於|不低於|不超過|约|約)"
_QUAL_PREFIX = r"(?:添加量|含量|固形物|干物质|總固形物|乾物質)"
_QUAL_NUM_RANGE = (
    rf"[0-9]+(?:\.[0-9]+)?(?:\s*{_QUAL_UNITS})?(?:\s*[-~～—–]\s*[0-9]+(?:\.[0-9]+)?)?\s*{_QUAL_UNITS}"
)
_PCT_NUM_RANGE = (
    r"[0-9]+(?:\.[0-9]+)?(?:\s*(?:%|％))?(?:\s*[-~～—–]\s*[0-9]+(?:\.[0-9]+)?)?\s*(?:%|％)"
)

# Matches quantitative qualifiers including intervals, e.g. ">=4g/L", "≥95%", "20%-25%", "添加量18%~22%"
QUALIFIER_ONLY_RE = re.compile(
    rf"^(?:{_QUAL_PREFIX}\s*)?(?:{_QUAL_CMP}\s*)?{_QUAL_NUM_RANGE}$",
    re.IGNORECASE,
)

# Matches trailing inline qualifier attached to an ingredient name, e.g. "牛肉≥95%", "饮用水20%-25%"
INLINE_QUALIFIER_RE = re.compile(
    rf"^(?P<head>.+?)\s*(?<![0-9.\-~～—–])(?P<qual>(?:{_QUAL_PREFIX}\s*)(?:{_QUAL_CMP}\s*)?{_QUAL_NUM_RANGE}|{_QUAL_CMP}\s*{_QUAL_NUM_RANGE}|(?<![A-Za-z]){_PCT_NUM_RANGE})$",
    re.IGNORECASE,
)

HEADER_PREFIX_RE = re.compile(
    r"^(?:配料表|配料|成分|成份|原料与辅料|原料與輔料|原材料名|原材料|原料|원재료명\s*및\s*함량|원재료명|원재료|성분명|ramuan|bahan-bahan|kandungan|composition|ingredients|ingr[eé]dients|zutaten|ingredientes|ingredienti|made\s+from)\s*[：:]",
    re.IGNORECASE,
)

# Korean origin-country head after ':' inside ingredient parens, e.g. `밀:미국산`, `대두:외국산(미국, 브라질)`
KR_ORIGIN_HEAD_RE = re.compile(r"^[가-힣]+산$")

FUNCTIONAL_CLASS_TERMS = {
    # Simplified Chinese (zh-Hans)
    "食品添加剂",
    "添加剂",
    "酸度调节剂",
    "抗氧化剂",
    "防腐剂",
    "甜味剂",
    "增稠剂",
    "乳化剂",
    "着色剂",
    "膨松剂",
    "水分保持剂",
    "稳定剂",
    "凝固剂",
    "抗结剂",
    "增味剂",
    "护色剂",
    "漂白剂",
    "酶制剂",
    # Traditional Chinese / Hong Kong CFS (zh-Hant)
    "食品添加劑",
    "添加劑",
    "酸度調節劑",
    "抗氧化劑",
    "防腐劑",
    "甜味劑",
    "增稠劑",
    "乳化劑",
    "色素",
    "着色劑",
    "著色劑",
    "膨脹劑",
    "膨鬆劑",
    "水分保持劑",
    "濕潤劑",
    "穩定劑",
    "凝固劑",
    "抗結劑",
    "增味劑",
    "調味劑",
    "護色劑",
    "漂白劑",
    "酶製劑",
    "麵粉處理劑",
    "上光劑",
    "發泡劑",
    # English (US / EU / UK / AU / NZ / HK)
    "emulsifier",
    "emulsifiers",
    "acidity regulator",
    "acidity regulators",
    "food acid",
    "food acids",
    "acid",
    "acids",
    "antioxidant",
    "antioxidants",
    "preservative",
    "preservatives",
    "sweetener",
    "sweeteners",
    "thickener",
    "thickeners",
    "vegetable gum",
    "vegetable gums",
    "stabiliser",
    "stabilisers",
    "stabilizer",
    "stabilizers",
    "raising agent",
    "raising agents",
    "mineral salt",
    "mineral salts",
    "colour",
    "colours",
    "color",
    "colors",
    "colourant",
    "colourants",
    "colouring",
    "colourings",
    "coloring",
    "colorings",
    "food colour",
    "food colours",
    "food color",
    "food colors",
    "flavour enhancer",
    "flavour enhancers",
    "flavor enhancer",
    "flavor enhancers",
    "flavouring",
    "flavourings",
    "flavoring",
    "flavorings",
    "food conditioner",
    "food conditioners",
    "permitted food conditioner",
    "permitted food conditioners",
    "permitted flavouring",
    "permitted flavourings",
    "permitted flavoring",
    "permitted flavorings",
    "permitted colouring",
    "permitted colourings",
    "permitted coloring",
    "permitted colorings",
    "permitted preservative",
    "permitted preservatives",
    "sequestrant",
    "sequestrants",
    "bulking agent",
    "bulking agents",
    "foaming agent",
    "foaming agents",
    "modified starch",
    "modified food starch",
    "humectant",
    "humectants",
    "anticaking agent",
    "anti-caking agent",
    "anticaking agents",
    "anti-caking agents",
    "gelling agent",
    "gelling agents",
    "firming agent",
    "firming agents",
    "flour treatment agent",
    "flour treatment agents",
    "glazing agent",
    "glazing agents",
    "propellant",
    # German (de)
    "emulgator",
    "emulgatoren",
    "backtriebmittel",
    "säuerungsmittel",
    "säureregulator",
    "antioxidationsmittel",
    "konservierungsstoff",
    "konservierungsstoffe",
    "verdickungsmittel",
    "stabilisator",
    "stabilisatoren",
    "farbstoff",
    "farbstoffe",
    "süßungsmittel",
    "geschmacksverstärker",
    "feuchthaltemittel",
    "trennmittel",
    "geliermittel",
    # French (fr)
    "émulsifiant",
    "émulsifiants",
    "poudre à lever",
    "poudres à lever",
    "acidifiant",
    "acidifiants",
    "correcteur d'acidité",
    "antioxydant",
    "antioxydants",
    "conservateur",
    "conservateurs",
    "épaississant",
    "épaississants",
    "stabilisant",
    "stabilisants",
    "colorant",
    "colorants",
    "édulcorant",
    "édulcorants",
    "exhausteur de goût",
    "humectant",
    "antiagglomérant",
    "anti-agglomérant",
    "gélifiant",
    # Spanish (es)
    "emulgente",
    "emulgentes",
    "gasificante",
    "gasificantes",
    "acidulante",
    "acidulantes",
    "corrector de acidez",
    "antioxidante",
    "antioxidantes",
    "conservador",
    "conservadores",
    "espesante",
    "espesantes",
    "estabilizante",
    "estabilizantes",
    "edulcorante",
    "edulcorantes",
    "potenciador del sabor",
    "humectante",
    "antiaglomerante",
    "gelificante",
    # Italian (it)
    "emulsionante",
    "emulsionanti",
    "agente lievitante",
    "agenti lievitanti",
    "acidificante",
    "acidificanti",
    "correttore di acidità",
    "antiossidante",
    "antiossidanti",
    "conservante",
    "conservanti",
    "addensante",
    "addensanti",
    "stabilizzante",
    "stabilizzanti",
    "esaltatore di sapidità",
    "umidificante",
    "antiagglomerante",
    # Japanese (ja)
    "膨張剤",
    "乳化剤",
    "酸化防止剤",
    "酸味料",
    "保存料",
    "甘味料",
    "増粘剤",
    "安定剤",
    "着色料",
    "調味料",
    "ph調整剤",
    # Korean / MFDS (ko)
    "식품첨가물",
    "산도조절제",
    "유화제",
    "증점제",
    "안정제",
    "향미증진제",
    "합성향료",
    "천연향료",
    "향료",
    "착색료",
    "감미료",
    "보존료",
    "팽창제",
    "산화방지제",
    "응고제",
    "소포제",
    "습윤제",
    "고결방지제",
    "피막제",
    "효소제",
    "영양강화제",
    # Bahasa Malaysia / MOH (ms)
    "pengemulsi",
    "penstabil",
    "pengawal asid",
    "pengatur keasidan",
    "agen antipengerakan",
    "agen anti-pengerakan",
    "pemekat",
    "pengawet",
    "pengawet yang dibenarkan",
    "pewarna",
    "pewarna yang dibenarkan",
    "bahan pewarna",
    "bahan pewarna yang dibenarkan",
    "perisa",
    "perisa yang dibenarkan",
    "bahan perisa",
    "bahan perisa yang dibenarkan",
    "penambah perisa",
    "pemanis",
    "antioksidan",
    "agen penaik",
    "agen pengilat",
    "humektan",
    "kondisioner makanan",
    "kondisioner makanan yang dibenarkan",
}

HAN_PREFIX_SAFE_HEADS = {
    "食用香精",
    "食品用香精",
    "食用香料",
    "食用香精香料",
    "香精",
    "香料",
    "复合调味料",
}

# Word-boundary structural connectors and statutory permission clauses allowed between AST tokens
STRUCTURAL_CONNECTOR_RE = re.compile(
    r"(?:"
    r"sebagai\s+kondisioner\s+makanan\s+yang\s+dibenarkan"
    r"|as\s+permitted\s+food\s+conditioners?"
    r"|contains\s+(?:2%\s+or\s+less|less\s+than\s+2%)\s+of"
    r"|mengandungi\s+2%\s+atau\s+kurang\s+daripada"
    r"|yang\s+dibenarkan"
    r"|of\s+which"
    r"|and\s*/\s*or"
    r"|mengandungi|termasuk|contains|including|sebagai"
    r"|and|or|dan|atau|serta|und|oder|et|ou|dont|contiene"
    r")",
    re.IGNORECASE,
)

OPEN_TO_CLOSE = {"（": "）", "(": ")", "[": "]", "【": "】", "［": "］", "{": "}"}
CLOSE_BRACKETS = set(OPEN_TO_CLOSE.values())
DEFAULT_DELIMITERS = {"、", "，", ",", "；", ";"}
COLON_CHARS = {"：", ":"}
ALLOWED_STRUCTURAL_CHARS = (
    DEFAULT_DELIMITERS
    | set(OPEN_TO_CLOSE.keys())
    | CLOSE_BRACKETS
    | COLON_CHARS
    | {"／", "/", "。", ".", " ", "\t", "\r", "\n"}
)
SPAN_KEYS = ("span", "qualifier_span", "functional_class_span")
