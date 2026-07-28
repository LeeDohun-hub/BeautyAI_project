"""아마존 Beauty 카탈로그 매처 (product → ASIN 직링크).

Kaggle 'amazon-products-dataset-2023-1.4M'(amazon.com/US)에서 Beauty 상품만 뽑은 매니페스트를
인메모리로 올려, 상품(브랜드+상품명)을 ASIN으로 매칭한다. 매칭되면:
  - KR: https://www.amazon.com/dp/{asin}   (검증된 미국 아마존 직링크)
  - JP: https://www.amazon.co.jp/dp/{asin} (글로벌 브랜드는 ASIN 공유가 많음 → 일본 페이지로 연결)
매칭 안 되면 아마존 버튼을 붙이지 않는다(검색 링크 투기 방지 — 올리브영 직링크 기준으로 통일).

매칭 로직은 oliveyoung_catalog 의 score_line/_brands_match 를 재사용한다(브랜드 게이트 + 라인
토큰 유사도). 아마존 타이틀은 영문이라, 쿼리도 영문 정체성(영문 브랜드/영문 토큰)이 있어야
매칭된다. 한글 브랜드는 아래 별칭으로 영문화해 매칭률을 높인다.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.services.matsukiyo_matcher import normalize_key, tokens_for

_BRAND_STOPWORDS = {"of", "the", "and", "for", "by", "de", "la", "le"}

# 아마존 타이틀 노이즈(용량/수량/일반어) — 라인 매칭에서 제외해 커버리지 계산을 깨끗하게.
_NOISE_TOKENS = {
    "fl", "oz", "ml", "g", "kg", "lb", "pack", "count", "ct", "set", "pcs", "pc", "piece",
    "size", "value", "pack of", "new", "the", "for", "with", "and", "plus", "free",
    "face", "skin", "care", "beauty", "cosmetic", "cosmetics", "korean", "kbeauty",
}

_MANIFEST_FILENAME = "amazon_beauty_products.csv"
_AMAZON_COM = "https://www.amazon.com/dp/"
_AMAZON_JP = "https://www.amazon.co.jp/dp/"
_MIN_SCORE = 0.5

# 한글 브랜드 → 영문(아마존은 영문 검색이라야 조회됨: '자빈드서울' 0건, 'javin de seoul' 조회).
_KO_TO_EN_BRAND = {
    "롬앤": "romand", "페리페라": "peripera", "에스쁘아": "espoir", "클리오": "clio",
    "컬러그램": "colorgram", "웨이크메이크": "wakemake", "티르티르": "tirtir", "헤라": "hera",
    "라네즈": "laneige", "이니스프리": "innisfree", "에뛰드": "etude", "어뮤즈": "amuse",
    "무지개": "muzigae", "릴리바이레드": "lilybyred", "데이지크": "dasique", "퓌": "fwee",
    "클로브": "clove", "언리시아": "unleashia", "홀리카홀리카": "holika", "미샤": "missha",
    "메디힐": "mediheal", "코스알엑스": "cosrx", "라운드랩": "roundlab", "토리든": "torriden",
    "넘버즈인": "numbuzin", "아비브": "abib", "아누아": "anua", "조선미녀": "beauty of joseon",
    "스킨천사": "skin1004", "닥터자르트": "dr jart", "설화수": "sulwhasoo", "바닐라코": "banila",
    # 스크린샷/추가 브랜드(공식 영문명).
    "자빈드서울": "javin de seoul", "어바웃톤": "about tone", "정샘물": "jung saem mool",
    "무칸": "mukan", "아이소이": "isoi", "오브제": "obge", "다슈": "dashu", "그라펜": "grafen",
    "비올리코": "bioliko", "머지": "merzy", "멀지": "merzy", "멘소래담": "mentholatum",
    "레브론": "revlon", "바비브라운": "bobbi brown", "삐아": "peripera",
    "클럽클리오": "clio", "포멘트": "forment", "투쿨포스쿨": "too cool for school",
    "포니이펙트": "pony effect", "힌스": "hince", "아이디얼포맨": "ideal for men",
    "나인위시스": "ninewishes", "우르오스": "uruos", "블랙몬스터": "black monster",
    "낫포유": "notforyou", "미닉": "minique", "보웰": "bowell", "리우젤": "reuzel",
    # J-beauty(일본) + 추가 K-beauty 별칭(HF McAuley 카탈로그에 영문명으로 존재, 실측 미매칭 보강).
    "캔메이크": "canmake", "아네사": "anessa", "큐렐": "curel", "스킨푸드": "skinfood",
    "엘릭시르": "elixir", "시세이도": "shiseido", "코세": "kose", "비오레": "biore",
    "하다라보": "hada labo", "센카": "senka", "판클": "fancl", "무인양품": "muji",
    "도프로그램": "d program", "미논": "minon", "이프사": "ipsa", "카네보": "kanebo",
    "소피나": "sofina", "로토": "rohto", "멜라노씨씨": "melano cc", "나튜리에": "naturie",
    "트란시노": "transino", "굿달": "goodal", "메디큐브": "medicube", "달바": "dalba",
    "닥터지": "dr.g",
}

# 한국어 화장품 용어 → 영문(아마존 영문 검색용). 색상/제품종류 + 흔한 음차 형용사.
_KO_TO_EN_TERM = {
    # 색상
    "누드": "nude", "코랄": "coral", "로즈": "rose", "브라운": "brown", "베이지": "beige",
    "핑크": "pink", "레드": "red", "오렌지": "orange", "피치": "peach", "살구": "apricot",
    "모카": "mocha", "카멜": "camel", "버건디": "burgundy", "와인": "wine", "플럼": "plum",
    "자두": "plum", "베리": "berry", "체리": "cherry", "카키": "khaki", "올리브": "olive",
    "샌드": "sand", "아이보리": "ivory", "마룬": "maroon", "그레이": "gray", "실버": "silver",
    "골드": "gold", "블랙": "black", "화이트": "white", "라벤더": "lavender", "옐로우": "yellow",
    # 제품종류
    "립스틱": "lipstick", "틴트": "tint", "립글로스": "lip gloss", "립밤": "lip balm",
    "쿠션": "cushion", "파운데이션": "foundation", "컨실러": "concealer", "블러셔": "blush blusher",
    "블러쉬": "blush", "치크": "cheek", "아이섀도우": "eyeshadow", "섀도우": "shadow",
    "쉐도우": "shadow", "팔레트": "palette", "마스카라": "mascara", "아이라이너": "eyeliner",
    "라이너": "liner", "아이브로우": "eyebrow", "브로우": "brow", "펜슬": "pencil",
    "프라이머": "primer", "파우더": "powder", "선크림": "sunscreen", "선스틱": "sun stick",
    "네일": "nail", "젤네일": "gel nail", "폴리쉬": "polish", "매니큐어": "manicure",
    # 흔한 음차 형용사/라인어
    "퓨어": "pure", "소프트": "soft", "매트": "matte", "글로우": "glow", "벨벳": "velvet",
    "워터": "water", "워터리": "watery", "실키": "silky", "크리미": "creamy", "듀이": "dewy",
    "래스팅": "lasting", "커버": "cover", "킬": "kill", "잉크": "ink", "무드": "mood",
    "데일리": "daily", "내추럴": "natural", "톤업": "tone up", "비비": "bb", "씨씨": "cc",
    "스킨": "skin", "핏": "fit", "리퀴드": "liquid", "오일": "oil", "밤": "balm",
    "크림": "cream", "세럼": "serum", "에센스": "essence", "선샤인": "sunshine", "글로이": "glowy",
    "쥬시": "juicy", "글래스팅": "glasting", "누디": "nudie", "멜팅": "melting", "슈가": "sugar",
    # 제품 라인/타입어 보강(실측 미매칭: 미샤 타임레볼루션, 큐렐 인텐시브 모이스처, 홀리카 알로에 젤 등).
    "타임": "time", "리볼루션": "revolution", "타임레볼루션": "time revolution",
    "알로에": "aloe", "젤": "gel", "마스크": "mask", "시트마스크": "sheet mask",
    "인텐시브": "intensive", "모이스처": "moisture", "모이스처라이징": "moisturizing",
    "모이스트": "moist", "리프트": "lift", "로션": "lotion", "퍼펙트": "perfect",
    "선스크린": "sunscreen", "쉬어": "sheer", "립": "lip", "미네랄": "mineral",
    "노세범": "no sebum", "앰플": "ampoule", "리페어": "repair", "나이트": "night",
    "클렌징": "cleansing", "토너": "toner", "밀크": "milk", "수딩": "soothing",
    "하이드라": "hydra", "히알루론": "hyaluronic", "콜라겐": "collagen",
    "레티놀": "retinol", "비타민": "vitamin", "시카": "cica", "스네일": "snail", "뮤신": "mucin",
    "디파잉": "defying", "모이스춰": "moisture",
    # 흔한 라인/제품 수식어(실측 미매칭 보강: 정샘물 아티스트/마스터클래스 등). 주의: 브랜드의
    # 라인 접두사(예: 자빈드서울의 '윙크'=Wink Eye/Lip/Cushion 전부)는 오탐을 유발하므로 넣지 않는다.
    "아티스트": "artist", "마스터클래스": "masterclass", "래디언트": "radiant",
}
_JP_TO_EN_TERM = {
    # 색상
    "ローズブラウン": "rose brown", "ヌードコーラル": "nude coral", "ベージュコーラル": "beige coral",
    "カーキブラウン": "khaki brown", "ミュートブラウン": "muted brown", "オリーブベージュ": "olive beige",
    "ニュートラルウォームベージュ": "neutral warm beige", "サンドベージュ": "sand beige",
    "ヌードベージュ": "nude beige", "ローズ": "rose", "ブラウン": "brown", "ベージュ": "beige",
    "コーラル": "coral", "ヌード": "nude", "ピンク": "pink", "レッド": "red", "オレンジ": "orange",
    "ピーチ": "peach", "モカ": "mocha", "バーガンディ": "burgundy", "ワイン": "wine",
    "プラム": "plum", "ベリー": "berry", "チェリー": "cherry", "カーキ": "khaki",
    "オリーブ": "olive", "サンド": "sand", "アイボリー": "ivory", "グレー": "gray",
    "シルバー": "silver", "ゴールド": "gold", "ブラック": "black", "ホワイト": "white",
    "ラベンダー": "lavender", "イエロー": "yellow",
    # 제품종류
    "リップバーム": "lip balm", "リップグロス": "lip gloss", "リップスティック": "lipstick",
    "リップ": "lipstick", "ティント": "tint", "ファンデーション": "foundation", "クッション": "cushion",
    "コンシーラー": "concealer", "チーク": "cheek", "ブラッシャー": "blusher", "アイシャドウ": "eyeshadow",
    "シャドウ": "eyeshadow", "パレット": "palette", "マスカラ": "mascara", "アイライナー": "eyeliner",
    "ライナー": "liner", "アイブロウ": "eyebrow", "ブロウ": "brow", "ペンシル": "pencil",
    "プライマー": "primer", "パウダー": "powder", "日焼け止め": "sunscreen", "ネイル": "nail",
    "ジェルネイル": "gel nail", "ポリッシュ": "polish",
    # 흔한 상품/질감 단어
    "メンズ": "men", "ピュア": "pure", "ソフト": "soft", "マット": "matte", "グロウ": "glow",
    "ベルベット": "velvet", "ウォーター": "water", "シルキー": "silky", "クリーミー": "creamy",
    "ラスティング": "lasting", "カバー": "cover", "キル": "kill", "ムード": "mood",
    "デイリー": "daily", "ナチュラル": "natural", "トーンアップ": "tone up", "スキン": "skin",
    "フィット": "fit", "リキッド": "liquid", "バーム": "balm", "クリーム": "cream",
    "セラム": "serum", "エッセンス": "essence",
}
_LATIN_RE = re.compile(r"[a-zA-Z]")
# 순수 라틴 토큰만 영문 쿼리에 넣는다(일본어/한글 섞인 'メンズ…BBローション' 같은 잡토큰은 제외).
_PURE_LATIN_RE = re.compile(r"^[a-zA-Z0-9.&'+-]+$")
_SIZE_RE = re.compile(r"^\d+(\.\d+)?(ml|g|kg|oz|호|색|colors?|개|매|종|팩|세트|pcs?|ea)?$", re.I)


def amazon_search_query(brand: str, name: str) -> str:
    """아마존 영문 검색 쿼리. 한글 브랜드→영문 알리아스 + 한국어 용어→영문 변환 + 라틴 토큰.
    한국어 상품명을 아마존(영문 카탈로그/검색)에 맞게 영어로 바꾼다. 변환 불가한 순수 한글
    음차(예: '블러쉬드')는 버린다(브랜드+카테고리어만으로도 검색이 걸린다)."""
    en_brand = _en_brand(brand).strip()
    out: list[str] = []
    seen: set[str] = set()

    def add(tok: str) -> None:
        tok = tok.strip().lower()
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)

    if en_brand and _LATIN_RE.search(en_brand):
        for t in en_brand.split():
            if _PURE_LATIN_RE.match(t):
                add(t)
    # 일본어/복합 한글 토큰은 공백 분리가 안 되어도 의미 있는 색상/카테고리어를 뽑는다.
    for source in (brand or "", name or ""):
        for jp, en in sorted(_JP_TO_EN_TERM.items(), key=lambda item: len(item[0]), reverse=True):
            if jp in source:
                for t in en.split():
                    add(t)
        for ko, en in sorted(_KO_TO_EN_TERM.items(), key=lambda item: len(item[0]), reverse=True):
            if ko in source:
                for t in en.split():
                    add(t)
    for raw in (name or "").split():
        tok = raw.strip("[](){}/·,.")
        if not tok:
            continue
        if _SIZE_RE.match(tok):
            continue  # 용량/수량(15g, 23호, 2개) 제외
        if tok in _KO_TO_EN_TERM:
            for t in _KO_TO_EN_TERM[tok].split():
                add(t)
        elif _PURE_LATIN_RE.match(tok):
            add(tok)
        # 그 외(순수 한글 음차, 일본어/한글+라틴 혼합 토큰)는 스킵.
    return " ".join(out[:8])


@dataclass(frozen=True)
class AmazonMatch:
    asin: str
    title: str
    image_url: str
    score: float


@dataclass(frozen=True)
class _AmazonItem:
    asin: str
    title: str
    title_key: str
    brand_key: str
    brand_tokens: frozenset[str]
    name_tokens: frozenset[str]
    image_url: str
    reviews: int


# 지역별 카탈로그 파일(같은 디렉터리). US(amazon.com/영문 타이틀) vs JP(amazon.co.jp/일본어 타이틀).
# - US: Kaggle 베이스 + 크롤(amazon.com) + HF(McAuley). 라틴 쿼리로 매칭, KR 버튼은 amazon.com/dp.
# - JP: amazon.co.jp 크롤(실 JP ASIN, 일본어 타이틀). '일본어 상품명'으로 매칭, JP 버튼은
#   amazon.co.jp/dp — US ASIN 재활용의 404 위험을 없앤다(공유 안 되는 ASIN도 실 JP ASIN이라 유효).
_CRAWL_FILENAMES = ("amazon_beauty_us.csv", "amazon_beauty_hf.csv")
# ESCI(아마존 공개 Shopping Queries) JP 로케일에서 추린 바디케어 12,358건을 더한다.
# 기존 amazon_beauty_jp.csv(3,868건)는 한국 화장품 위주라, 라쿠텐·마츠키요에서 온 일본
# 드럭스토어 바디 상품과 겹치지 않아 JP+아마존 조합에서 보습·집중케어가 0건이었다.
# 생성: scripts/build_amazon_jp_catalog_from_esci.py
_JP_CRAWL_FILENAMES = ("amazon_beauty_jp.csv", "amazon_beauty_jp_esci.csv")
_KNOWN_BRAND_KEYS = frozenset(
    key
    for key in {normalize_key(value) for value in _KO_TO_EN_BRAND.values()} | {"2an"}
    if key and len(key) >= 3
)


def _manifest_path() -> Path:
    return get_settings().project_root / "data" / "manifests" / _MANIFEST_FILENAME


def _region_files(region: str) -> tuple[Path, ...]:
    base_dir = _manifest_path().parent
    if region == "jp":
        return tuple(base_dir / name for name in _JP_CRAWL_FILENAMES)
    return (_manifest_path(), *(base_dir / name for name in _CRAWL_FILENAMES))


def _read_manifest(path: Path, items: list["_AmazonItem"], seen: set[str]) -> None:
    if not path.exists():
        return
    with path.open(encoding="utf-8-sig", errors="ignore", newline="") as f:
        for row in csv.DictReader(f):
            asin = str(row.get("asin") or "").strip()
            title = str(row.get("title") or "").strip()
            if not asin or not title or asin in seen:
                continue
            seen.add(asin)
            brand = str(row.get("brand") or "").strip()
            try:
                reviews = int(float(row.get("reviews") or 0))
            except ValueError:
                reviews = 0
            items.append(
                _AmazonItem(
                    asin=asin,
                    title=title,
                    title_key=normalize_key(title),
                    brand_key=normalize_key(brand),
                    brand_tokens=tokens_for(brand),
                    name_tokens=tokens_for(title),
                    image_url=str(row.get("imageUrl") or "").strip(),
                    reviews=reviews,
                )
            )


@lru_cache(maxsize=2)
def _load_items(region: str = "us") -> tuple[_AmazonItem, ...]:
    items: list[_AmazonItem] = []
    seen: set[str] = set()
    for path in _region_files(region):
        _read_manifest(path, items, seen)
    return tuple(items)


# 죽은 ASIN 블록리스트. Kaggle/HF(McAuley 2023)에는 이미 폐기(delist)된 ASIN이 많아, 그 dp
# 링크는 amazon "Page Not Found"(404)로 열린다(실측: 매칭 표본의 ~45%가 죽은 링크). 오프라인
# 검증기(scripts/verify_amazon_asins.py)가 /dp 를 HTTP 확인해 404를 이 파일에 적고, 매칭은
# 여기 실린 ASIN을 건너뛴다(사용자 원칙: 에러페이지 열리는 버튼은 내지 않는다).
_DEAD_ASINS_FILENAME = "amazon_dead_asins.txt"
_dead_cache: tuple[float, frozenset[str]] | None = None


def _dead_asins() -> frozenset[str]:
    """죽은 ASIN 집합. 파일 mtime을 감시해 바뀌면 재로드한다 — 오프라인 검증기가 블록리스트를
    확장하는 동안, 서버(컨테이너)가 재시작 없이도 새로 발견된 죽은 링크를 반영하게 한다."""
    global _dead_cache
    path = _manifest_path().parent / _DEAD_ASINS_FILENAME
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _dead_cache = (0.0, frozenset())
        return _dead_cache[1]
    if _dead_cache is not None and _dead_cache[0] == mtime:
        return _dead_cache[1]
    out: set[str] = set()
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            asin = line.strip().split(",")[0].strip()  # 'ASIN' 또는 'ASIN,메모' 형식 허용
            if asin and not asin.startswith("#"):
                out.add(asin)
    _dead_cache = (mtime, frozenset(out))
    return _dead_cache[1]


def clear_cache() -> None:
    global _dead_cache
    _load_items.cache_clear()
    _dead_cache = None


def catalog_available(region: str = "us") -> bool:
    return bool(_load_items(region))


def amazon_com_url(asin: str) -> str:
    return _AMAZON_COM + asin


def amazon_jp_url(asin: str) -> str:
    return _AMAZON_JP + asin


def _en_brand(brand: str) -> str:
    return _KO_TO_EN_BRAND.get((brand or "").strip(), brand)


def _brand_ok(q_brand_key: str, q_brand_tokens: frozenset[str], item: "_AmazonItem") -> bool:
    """브랜드 일치. 키가 같거나 '충분히 긴' 쪽이 서로 포함되면 OK. 아니면 '구별력 있는'
    브랜드 토큰(len>=3, 불용어 제외)이 **전부** 타이틀에 있어야 한다.

    부분포함은 '짧은 쪽 키가 4자 이상'일 때만 허용한다. 카탈로그에는 브랜드 컬럼이 깨져
    1~2글자 쓰레기 키('i','in','g','by','oz' 등 428행)가 있는데, 이들이 부분문자열로 아무
    브랜드에나 걸리기 때문이다(실측 오탐: 브랜드키 'i'가 'espoir'의 부분문자열 → 'espoir'
    쿼리가 'i ENVY BY KISS Brow Stamp'에 매칭). 'of' 같은 공용어 하나로 새던 버그도 방지."""
    # 공백 제거 후 비교 — '정샘물'→'jung saem mool'(3토큰) 이 카탈로그 'jungsaemmool'(1토큰)과
    # 같은 브랜드인데 공백 유무로 안 맞던 버그 방지(실측: 정샘물 34개 취급인데 버튼 미출력).
    qk = q_brand_key.replace(" ", "")
    ik = item.brand_key.replace(" ", "")
    if qk and ik:
        if qk == ik:
            return True
        shorter = min(qk, ik, key=len)
        if len(shorter) >= 4 and (qk in ik or ik in qk):
            return True
    distinctive = {t for t in q_brand_tokens if len(t) >= 3 and t not in _BRAND_STOPWORDS}
    return bool(distinctive) and distinctive <= item.name_tokens


def _jp_title_has_other_brand(q_brand_key: str, item: "_AmazonItem") -> bool:
    if not q_brand_key or q_brand_key in item.title_key:
        return False
    return any(key != q_brand_key and key in item.title_key for key in _KNOWN_BRAND_KEYS)


def match_amazon(brand: str, name: str, min_score: float = _MIN_SCORE, region: str = "us") -> AmazonMatch | None:
    """상품을 아마존 Beauty 카탈로그와 조인해 최적 매칭(ASIN)을 반환한다. 없으면 None.

    브랜드가 실제로 일치하는 후보만 받는다(교차브랜드 오탐 차단). 동점이면 리뷰수가 많은 상품을
    고른다(대표 상품일 확률↑, 죽은 링크↓).

    region="jp"면 JP 카탈로그(일본어 타이틀)를 쓴다. 이때 name 은 **일본어 상품명**을 넘겨야
    라인 토큰(일본어)이 겹친다(라틴화한 amazon_search_query 결과 아님). 브랜드는 _en_brand 로
    라틴 정규화 — JP 카탈로그 brand 컬럼도 라틴 시드라 게이트가 라틴↔라틴으로 맞는다.
    """
    en_brand = _en_brand(brand)
    q_brand_key = normalize_key(en_brand)
    q_brand_tokens = tokens_for(en_brand)
    q_name_tokens = tokens_for(name)
    if not q_brand_key and not q_brand_tokens:
        return None  # 브랜드 없으면 매칭 신뢰 불가
    # 쿼리 '라인 토큰'(브랜드/노이즈 제외). 아마존 타이틀이 길어(용량/수량) Jaccard는 희석되므로,
    # '쿼리 라인이 타이틀에 얼마나 담겼나'(containment)로 채점한다.
    q_line = {t for t in (q_name_tokens - q_brand_tokens) if t not in _NOISE_TOKENS and not t.isdigit()}
    if len(q_line) < 2:
        return None  # 구별 토큰이 1개뿐이면 오탐 위험 → 기각

    dead = _dead_asins()
    best: _AmazonItem | None = None
    best_cov = 0.0
    best_reviews = -1
    for item in _load_items(region):
        if item.asin in dead:
            continue  # 죽은 링크(404)는 건너뛰고 살아있는 차선을 고른다
        if not _brand_ok(q_brand_key, q_brand_tokens, item):
            continue
        if region == "jp" and _jp_title_has_other_brand(q_brand_key, item):
            continue
        il = item.name_tokens - item.brand_tokens
        overlap = q_line & il
        if len(overlap) < 2:
            continue  # 라인 토큰 2개 이상 겹쳐야 인정(형제라인/generic 오탐 차단)
        cov = len(overlap) / len(q_line)  # 쿼리 커버리지
        if cov < min_score:
            continue
        # 커버리지 우선, 동률이면 리뷰 많은(대표) 상품.
        if cov > best_cov or (cov == best_cov and item.reviews > best_reviews):
            best, best_cov, best_reviews = item, cov, item.reviews
    if best is None:
        return None
    return AmazonMatch(asin=best.asin, title=best.title, image_url=best.image_url, score=round(min(1.0, best_cov), 3))
