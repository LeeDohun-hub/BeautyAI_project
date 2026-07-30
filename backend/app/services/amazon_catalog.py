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
import json
import re
from collections import Counter
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
    # ⚠ 삐아는 BBIA 다. 예전에 "peripera"(페리페라)로 잘못 매핑돼 있어 삐아 블러셔가
    #   'peripera cheek' 로 질의되고 매칭에 실패했다(KR 아마존 블러셔 컬럼이 0이던 원인 중 하나).
    "레브론": "revlon", "바비브라운": "bobbi brown", "삐아": "bbia",
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
    # 네일 브랜드(2026-07-29 보강). 맵에 없으면 amazon_search_query 가 한글 브랜드를 통째로
    # 떨어뜨려 질의가 'nail' 같은 일반어만 남고, match_amazon 은 브랜드 일치를 요구하므로
    # 무조건 실패한다 — 아마존 탭 네일 컬럼이 0이던 원인. 카탈로그 실재 확인 후 추가:
    # dashing diva(US 20건) · ohora(US 26건/JP 9건) · le ment(JP 4건).
    "데싱디바": "dashing diva", "오호라": "ohora", "르멘트": "le ment",
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
    # 네일·블러셔 라인어 보강(2026-07-29, 아마존 탭 블러셔·네일 0 건 조사).
    # 이 토큰들이 없으면 '삐아 레디 투 웨어 다우니 치크'가 'bbia cheek' 두 단어로 줄어,
    # 카탈로그에 **정확히 같은 상품**('BBIA Ready To Wear Downy Cheek Cream Blush 3.5g')이
    # 있는데도 라인 유사도가 문턱을 못 넘어 매칭에 실패했다.
    "레디": "ready", "투": "to", "웨어": "wear", "다우니": "downy", "블러": "blur",
    "샤벳": "sherbet", "러브": "love", "빔": "beam", "블렌딩": "blending",
    "매직": "magic", "프레스": "press", "매직프레스": "magic press", "스트립": "strip",
    "시럽": "syrup", "강화제": "strengthener", "하드너": "hardener", "영양제": "treatment",
    "탑코트": "top coat", "베이스코트": "base coat", "컬러": "color", "빌더": "builder",
    "리무버": "remover", "큐티클": "cuticle", "페디큐어": "pedicure", "페디": "pedi",
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
    # 바디·헤어 용어(2026-07-30). 이 토큰들이 없으면 바디 상품의 질의가 통째로 무너져
    # **카탈로그에 실재하는 상품도 매칭 자체가 불가능**했다(실측:
    #   '메디큐브 레드 바디워시' → query 'medicube red' (라인 토큰 1개 → 즉시 기각)
    #   '일리윤 세라미드 아토 바디로션' → query 'lotion' (브랜드마저 소실)
    # 카탈로그엔 'Medicube Red Body Wash …' 가 실제로 있다).
    # ⚠ '진정/보습/장벽' 같은 일반 수식어는 넣지 않는다 — 쿼리 라인 토큰만 늘려
    #   커버리지 분모를 키우고(cov=겹침/라인) 오히려 매칭을 떨어뜨린다.
    "바디": "body", "워시": "wash", "바디워시": "body wash", "샤워": "shower",
    "샴푸": "shampoo", "컨디셔너": "conditioner", "비누": "soap",
    "핸드": "hand", "풋": "foot", "스크럽": "scrub", "캡슐": "capsule",
    # 성분명(상품 정체성을 정하는 희귀어라 매칭 정확도에 직접 기여).
    "세라미드": "ceramide", "판테놀": "panthenol", "나이아신아마이드": "niacinamide",
    "니아신아마이드": "niacinamide", "센텔라": "centella", "어성초": "heartleaf",
    "쿼세티놀": "quercetinol", "석신산": "succinic", "히알루론산": "hyaluronic",
    "스쿠알란": "squalane", "알란토인": "allantoin", "시어버터": "shea butter",
    "쉐어버터": "shea butter", "오트밀": "oatmeal", "프로폴리스": "propolis",
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
    # 이 행이 '살아있는 ASIN 소스'인지. False면 개별 검증(_verified_alive_asins()) 없이는 쓰지 않는다.
    # HF(McAuley 2023) 카탈로그는 실측 사망률 48.5%(33/68)인데 전체 매칭의 80%를 차지해,
    # 게이트 없이 쓰면 아마존 버튼 10개 중 4개가 404로 열린다(사용자 리포트의 직접 원인).
    trusted: bool = True


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


def _read_manifest(path: Path, items: list["_AmazonItem"], seen: set[str], trusted: bool = True) -> None:
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
                    trusted=trusted,
                )
            )


# 개별 검증 없이는 /dp 링크로 쓰지 않는 카탈로그(사망률이 높은 덤프). scripts/verify_amazon_asins.py
# 가 amazon_asin_status.json 에 "ok" 를 적은 ASIN만 살려 쓴다.
_UNTRUSTED_FILENAMES = frozenset({"amazon_beauty_hf.csv"})


@lru_cache(maxsize=2)
def _load_items(region: str = "us") -> tuple[_AmazonItem, ...]:
    items: list[_AmazonItem] = []
    seen: set[str] = set()
    for path in _region_files(region):
        _read_manifest(path, items, seen, trusted=path.name not in _UNTRUSTED_FILENAMES)
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


_ASIN_STATUS_FILENAME = "amazon_asin_status.json"
_alive_cache: tuple[float, frozenset[str]] | None = None


def _verified_alive_asins() -> frozenset[str]:
    """HTTP 검증으로 살아있음이 확인된 ASIN 집합(amazon_asin_status.json 의 "ok").

    _dead_asins 와 같은 이유로 mtime 감시 재로드한다 — 검증기가 백그라운드로 돌면서
    커버리지를 늘리는 동안, 서버 재시작 없이 새로 확인된 ASIN이 곧바로 버튼이 된다.
    """
    global _alive_cache
    path = _manifest_path().parent / _ASIN_STATUS_FILENAME
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _alive_cache = (0.0, frozenset())
        return _alive_cache[1]
    if _alive_cache is not None and _alive_cache[0] == mtime:
        return _alive_cache[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    _alive_cache = (mtime, frozenset(a for a, s in raw.items() if s == "ok"))
    return _alive_cache[1]


def clear_cache() -> None:
    global _dead_cache, _alive_cache
    _load_items.cache_clear()
    match_amazon.cache_clear()
    catalog_entries.cache_clear()
    _catalog_doc_freq.cache_clear()
    _dead_cache = None
    _alive_cache = None


def catalog_available(region: str = "us") -> bool:
    return bool(_load_items(region))


@dataclass(frozen=True)
class CatalogEntry:
    """카탈로그 상품을 호출부에 넘기는 읽기 전용 뷰(ASIN 직링크가 이미 확인된 행)."""

    asin: str
    title: str
    brand_key: str
    image_url: str
    reviews: int


@lru_cache(maxsize=8)
def catalog_entries(region: str = "us", pattern: str = "") -> tuple[CatalogEntry, ...]:
    """타이틀이 `pattern`(정규식, 대소문자 무시)에 걸리는 카탈로그 상품.

    카탈로그는 원래 '이 상품이 아마존에 있나'를 판정하는 **검증기**였다. 하지만 네일처럼
    후보 소스(네이버/라쿠텐 색상검색)와 아마존 취급 브랜드가 안 겹치는 카테고리는 검증만으로는
    컬럼이 영원히 빈다 — 그때 호출부가 카탈로그를 **후보 소스**로 쓸 수 있게 열어준다.
    """
    rx = re.compile(pattern, re.I) if pattern else None
    return tuple(
        CatalogEntry(
            asin=item.asin,
            title=item.title,
            brand_key=item.brand_key,
            image_url=item.image_url,
            reviews=item.reviews,
        )
        for item in _load_items(region)
        if item.asin and (rx is None or rx.search(item.title or ""))
    )


def amazon_com_url(asin: str) -> str:
    return _AMAZON_COM + asin


def amazon_jp_url(asin: str) -> str:
    return _AMAZON_JP + asin


def _en_brand(brand: str) -> str:
    return _KO_TO_EN_BRAND.get((brand or "").strip(), brand)


def _brand_ok(q_brand_key: str, q_brand_tokens: frozenset[str], item: "_AmazonItem") -> bool:
    """브랜드 일치. 키가 같거나 한쪽이 다른 쪽의 **접두**면 OK. 아니면 '구별력 있는'
    브랜드 토큰(len>=3, 불용어 제외)이 **전부** 타이틀에 있어야 한다.

    ⚠ 부분문자열(`in`) 포함은 쓰지 않는다. 길이 4 하한을 둬도 **단어 중간에 걸린다**:
    'anua'(아누아) ⊂ 'm-anua-l' 이라 브랜드 'Manual' 상품이 아누아로 매칭됐다(실측:
    아누아 클렌징폼 쿼리 → 'Manual Facial Cleansing Kabuki Brush'). 접미 허용도 안 된다 —
    'anessa' ⊂ 'd-anessa' 라 일본 아네사가 미국 Danessa 로 매칭되던 과거 버그가 되살아난다.
    그래서 접두(prefix)만 허용한다: 'holika'→'holikaholika', 'drjart'→'drjartplus',
    'roundlab'→'roundlabofficial' 같은 정당한 확장은 전부 접두다.

    브랜드 토큰 부분집합도 함께 본다 — 'bobbi brown' 이 카탈로그 'Bobbi Brown Cosmetics'
    처럼 접미어가 붙어도 매칭되게(접두 규칙만으론 공백 제거 후 접두가 되므로 대개 커버되나,
    토큰 순서가 다른 표기를 위해 남긴다)."""
    # 공백 제거 후 비교 — '정샘물'→'jung saem mool'(3토큰) 이 카탈로그 'jungsaemmool'(1토큰)과
    # 같은 브랜드인데 공백 유무로 안 맞던 버그 방지(실측: 정샘물 34개 취급인데 버튼 미출력).
    qk = q_brand_key.replace(" ", "")
    ik = item.brand_key.replace(" ", "")
    if qk and ik:
        if qk == ik:
            return True
        shorter, longer = (qk, ik) if len(qk) <= len(ik) else (ik, qk)
        if len(shorter) >= 4 and longer.startswith(shorter):
            return True
        q_tokens = {t for t in q_brand_tokens if len(t) >= 3 and t not in _BRAND_STOPWORDS}
        if q_tokens and q_tokens <= item.brand_tokens:
            return True
    distinctive = {t for t in q_brand_tokens if len(t) >= 3 and t not in _BRAND_STOPWORDS}
    return bool(distinctive) and distinctive <= item.name_tokens


# ── 제형(제품 종류) 게이트 ────────────────────────────────────────────────────────
# 라인 토큰이 2개만 겹치고 커버리지 0.5 를 넘기면 통과하던 구조라, **제품 종류가 아예 다른**
# 상품이 매칭됐다(실측: '아누아 어성초 실키 모이스처 선크림' → 'Anua Heartleaf 70% Soothing
# Cream'(선크림 아님), '아누아 … 클렌징폼' → 'Manual Facial Cleansing Kabuki Brush'(붓)).
# 그래서 쿼리와 후보의 '대표 제형'을 각각 하나로 확정해, 다르면 기각한다.
# 순서 = 우선순위(구체적 → 일반). tool 을 최상단에 둬 도구/부속품이 화장품 매칭을 못 하게 한다.
# 각 제형은 영문/일본어/한국어 표기를 함께 본다 — JP 카탈로그는 타이틀이 일본어라 영문 패턴만
# 두면 q_form 이 항상 ""가 되어 게이트가 JP 에서 통째로 무력화된다.
_FORM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("tool", re.compile(
        r"\bbrush(?:es)?\b|\bpuff\b|\bsponge\b|\bapplicator\b|\btweezer|\bclipper|\btrimmer"
        r"|\bmirror\b|\blamp\b|\bdryer\b|\bcontainer\b|\bstorage\b|\borganizer\b|\bholder\b"
        r"|\bcase\b|\bbag\b|\bstand\b|\bheadband\b|\bhair\s*clip|\bscissor"
        r"|ブラシ|パフ|スポンジ|ピンセット|毛抜き|鏡|ケース|ポーチ|容器|コンテナ|スタンド|ヘアクリップ"
        r"|브러시|브러쉬|퍼프|스펀지|핀셋|거울|파우치|손톱깎", re.I)),
    ("nail", re.compile(
        r"\bnail|\bpedi|\bpolish(?!ing)|\blacquer|\bmanicure|\bcuticle"
        r"|(?<!ス)ネイル|ペディ|マニキュア|(?<!스)네일|페디|매니큐어", re.I)),
    ("sunscreen", re.compile(
        r"\bsun\s*(?:screen|block|cream|stick|serum|milk|fluid)|\bsunscreen\b|\bspf\b|\bpa\+"
        r"|日焼け止め|サンスクリーン|サンクリーム|선크림|선스틱|자외선차단", re.I)),
    ("cleanser", re.compile(
        r"\bcleanser\b|\bcleansing\b|\bface\s*wash\b|\bfacial\s*wash\b|\bmicellar\b"
        r"|\bmakeup\s*remover\b|\bfoam(?:ing)?\s*wash\b"
        r"|クレンジング|洗顔|メイク落とし|클렌징|클렌저|세안|폼클렌징", re.I)),
    ("bodywash", re.compile(
        r"\bbody\s*(?:wash|cleanser|bar|soap)\b|\bshower\s*(?:gel|cream)\b|\bshampoo\b|\bconditioner\b"
        r"|ボディソープ|ボディウォッシュ|シャンプー|コンディショナー|바디워시|바디클렌저|샴푸|린스", re.I)),
    ("exfoliator", re.compile(r"\bscrub\b|\bpeel(?:ing)?\b|\bexfoliat|スクラブ|ピーリング|스크럽|피링|각질", re.I)),
    ("mask", re.compile(r"\bmask\b|\bsheet\s*mask\b|\bpatch(?:es)?\b|\bsleeping\s*pack\b|マスク|パック|마스크|팩|패치", re.I)),
    ("toner", re.compile(r"\btoner\b|\btoning\b|\bpad(?:s)?\b|\bmist\b|\bastringent\b|化粧水|トナー|ミスト|토너|스킨|미스트|패드", re.I)),
    ("serum", re.compile(
        r"\bserum\b|\bampoule\b|\bampule\b|\bessence\b|\bbooster\b|\bconcentrate\b"
        r"|美容液|セラム|エッセンス|アンプル|세럼|앰플|에센스|미용액", re.I)),
    ("lip", re.compile(
        r"\blip\b|\blipstick\b|\blip\s*(?:tint|gloss|balm|oil|mask)\b|\btint\b|\brouge\b"
        r"|リップ|ルージュ|ティント|口紅|립|틴트", re.I)),
    ("eye", re.compile(
        r"\beye\s*shadow\b|\beyeshadow\b|\bpalette\b|\bmascara\b|\beye\s*liner\b|\beyeliner\b"
        r"|\beyebrow\b|\bbrow\b|\bkajal\b"
        r"|アイシャドウ|アイライナー|マスカラ|アイブロウ|パレット|아이섀도|아이섀도우|섀도|쉐도|아이라이너|마스카라|아이브로우|팔레트", re.I)),
    ("blush", re.compile(r"\bblush(?:er)?\b|\bcheek\b|\bhighlighter\b|\bbronzer\b|チーク|ブラッシャー|블러셔|블러쉬|치크|볼터치|하이라이터", re.I)),
    ("base", re.compile(
        r"\bfoundation\b|\bcushion\b|\bconcealer\b|\bprimer\b|\bpowder\b|\bbb\s*cream\b|\bcc\s*cream\b"
        r"|ファンデーション|クッション|コンシーラー|プライマー|パウダー|파운데이션|쿠션|컨실러|프라이머|파우더", re.I)),
    ("moisturizer", re.compile(
        r"\bcream\b|\blotion\b|\bmoisturizer\b|\bmoisturiser\b|\bemulsion\b|\bbalm\b|\bbutter\b|\bgel\b|\boil\b"
        r"|クリーム|ローション|乳液|バーム|ジェル|オイル|크림|로션|밤|젤|오일|에멀전", re.I)),
)


@lru_cache(maxsize=4096)
def product_form(text: str) -> str:
    """텍스트의 대표 제형(없으면 ""). 우선순위 순으로 첫 매칭을 쓴다."""
    for form, pattern in _FORM_PATTERNS:
        if pattern.search(text or ""):
            return form
    return ""


# 서로 '같은 제형으로 봐도 되는' 묶음. 바디워시는 정의상 세정제(cleanser)이고, 실제 타이틀이
# 두 표현을 섞어 쓴다 — 실측: 'Medicube Red **Body Wash** … Gentle and Hydrating **Cleansing**'
# 은 cleanser 로, 쿼리 '메디큐브 레드 바디워시'는 bodywash 로 잡혀 **같은 상품인데** 기각됐다.
_FORM_EQUIVALENT: tuple[frozenset[str], ...] = (
    frozenset({"cleanser", "bodywash"}),
)


def _forms_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    return any(a in group and b in group for group in _FORM_EQUIVALENT)


# ── 변별 토큰(희귀어) 게이트 ──────────────────────────────────────────────────────
# 제형이 같아도 **다른 상품**이 매칭되는 경우가 남는다(실측: '메디큐브 레드 석신산 …' →
# 'Medicube Zero Pore Pads', 'St.Tropez Gradual Tan **Watermelon** …' → '… Tinted …').
# 두 경우 모두 상품 정체성을 정하는 희귀어(succinic df=2, watermelon df=85)가 후보에서
# 빠져 있었다. 반대로 정상 매칭이 빠뜨리는 건 흔한 수식어다(홀리카 'magic' df=364).
# 그래서 '카탈로그에서 희귀한 쿼리 토큰'은 후보 타이틀에 반드시 있어야 한다고 요구한다.
# 문턱 150 은 실측 df 사이(watermelon 85 / magic 364)에서 잡았다 — 6.4만 타이틀 중 0.24%.
_RARE_DF_MAX = 150


@lru_cache(maxsize=2)
def _catalog_doc_freq(region: str = "us") -> dict[str, int]:
    """카탈로그 타이틀 토큰의 문서빈도. 희귀어(=상품 정체성) 판정용, 지역별 1회 계산."""
    df: Counter[str] = Counter()
    for item in _load_items(region):
        df.update(item.name_tokens - item.brand_tokens)
    return dict(df)


def _rare_tokens(q_line: frozenset[str], region: str) -> frozenset[str]:
    """쿼리 라인 토큰 중 '카탈로그에 있으나 희귀한' 것들(없으면 빈 집합 = 게이트 비활성).

    df=0(카탈로그 부재)은 제외한다 — 어떤 후보도 만족시킬 수 없어 요구하면 전부 기각된다.

    ⚠ '희귀 = 상품 정체성' 전제는 **쿼리와 카탈로그가 같은 어휘를 쓸 때만** 성립한다.
    JP 카탈로그(일본어 타이틀 1.6만)에 영문 쿼리를 넣으면 영문 토큰이 전부 df≤150 이라
    모든 토큰이 '희귀어'로 잡혀 사실상 완전일치를 요구하게 된다(실측: 이 게이트만으로
    amazon_jp 링크가 5→0). 그래서 쿼리 어휘가 그 카탈로그에 충분히 흔할 때만 게이트를 켠다:
    '카탈로그에 존재하는 쿼리 토큰들의 df 중앙값'이 희귀 문턱을 넘어야 한다.
    (US 영문 쿼리는 중앙값이 수백이라 켜지고, JP 교차언어 쿼리는 10~40이라 꺼진다.)
    """
    df = _catalog_doc_freq(region)
    present = sorted(v for v in (df.get(t, 0) for t in q_line) if v > 0)
    if not present:
        return frozenset()
    median = present[len(present) // 2] if len(present) % 2 else (present[len(present) // 2 - 1] + present[len(present) // 2]) / 2
    if median <= _RARE_DF_MAX:
        return frozenset()  # 교차언어/희소 어휘 카탈로그 → 희귀어 판정이 의미 없다
    return frozenset(t for t in q_line if 0 < df.get(t, 0) <= _RARE_DF_MAX)


def _jp_title_has_other_brand(q_brand_key: str, item: "_AmazonItem") -> bool:
    if not q_brand_key or q_brand_key in item.title_key:
        return False
    return any(key != q_brand_key and key in item.title_key for key in _KNOWN_BRAND_KEYS)


@lru_cache(maxsize=8192)
def match_amazon(brand: str, name: str, min_score: float = _MIN_SCORE, region: str = "us") -> AmazonMatch | None:
    """상품을 아마존 Beauty 카탈로그와 조인해 최적 매칭(ASIN)을 반환한다. 없으면 None.

    카탈로그 수만 건을 전수 스캔해 호출당 ~133ms 로 아이템매칭 전체에서 가장 비싼 구간이었다
    (후보 40개 기준 5.3s, `_brand_ok` 63만 회). 순수 함수라 메모이즈한다 — 반환 AmazonMatch 는
    읽기 전용으로만 쓸 것(호출부가 변형하면 캐시가 오염된다).

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
    q_line = frozenset(
        t for t in (q_name_tokens - q_brand_tokens) if t not in _NOISE_TOKENS and not t.isdigit()
    )
    if len(q_line) < 2:
        return None  # 구별 토큰이 1개뿐이면 오탐 위험 → 기각

    dead = _dead_asins()
    alive = _verified_alive_asins()
    q_form = product_form(name)
    required_rare = _rare_tokens(q_line, region)
    best: _AmazonItem | None = None
    best_cov = 0.0
    best_reviews = -1
    for item in _load_items(region):
        if item.asin in dead:
            continue  # 죽은 링크(404)는 건너뛰고 살아있는 차선을 고른다
        if not item.trusted and item.asin not in alive:
            continue  # 사망률 높은 덤프 행 → 개별 HTTP 검증된 것만 버튼으로 낸다
        if not _brand_ok(q_brand_key, q_brand_tokens, item):
            continue
        if region == "jp" and _jp_title_has_other_brand(q_brand_key, item):
            continue
        il = item.name_tokens - item.brand_tokens
        overlap = q_line & il
        if len(overlap) < 2:
            continue  # 라인 토큰 2개 이상 겹쳐야 인정(형제라인/generic 오탐 차단)
        if not required_rare <= il:
            continue  # 상품 정체성을 정하는 희귀어가 빠졌다 → 다른 상품/다른 쉐이드
        cov = len(overlap) / len(q_line)  # 쿼리 커버리지
        if cov < min_score:
            continue
        # 제형 게이트: 쿼리 제형을 알 때, 후보가 다른 제형이면 기각(도구/부속품 포함).
        # ⚠ 제형 판정은 CJK 대안이 많은 정규식 14개라 행당 비용이 크다. 그래서
        #   (1) 로드 시 6.4만 행에 미리 계산하지 않고(그렇게 했더니 `_load_items` 0.4s→20.6s),
        #   (2) 이 루프에서도 **가장 마지막에** 본다. 앞의 게이트들이 쿼리당 후보를 한 자릿수로
        #   줄여주므로, 순수 AND 조건인 이 검사를 뒤로 미루면 결과는 같고 비용만 사라진다
        #   (실측: 호출당 171ms → 133ms).
        item_form = product_form(item.title)
        if q_form:
            if item_form and not _forms_compatible(q_form, item_form):
                continue
        elif item_form == "tool":
            continue  # 쿼리 제형을 몰라도 도구/부속품은 화장품 매칭 대상이 아니다
        # 커버리지 우선, 동률이면 리뷰 많은(대표) 상품.
        if cov > best_cov or (cov == best_cov and item.reviews > best_reviews):
            best, best_cov, best_reviews = item, cov, item.reviews
    if best is None:
        return None
    return AmazonMatch(asin=best.asin, title=best.title, image_url=best.image_url, score=round(min(1.0, best_cov), 3))
