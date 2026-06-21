# Amazon Beauty 데이터셋 분석 보고서

> **데이터셋**: Amazon Beauty Product Recommendation (Amazon India)
> **출처**: Kaggle — satrapankti/amazon-beauty-product-recommendation
> **규모**: 1,348,246건의 리뷰 · 23,838개 제품 · 883,753명의 사용자
> **분석 목적**: BIOHEAL BOH · WAKEMAKE의 글로벌 시장 입지 파악 및 뷰티 카테고리 인사이트 도출

---

## 1. BIOHEAL BOH · WAKEMAKE 브랜드 조회 결과

| 브랜드 | 검색 결과 | 리뷰 수 | 평균 평점 |
|--------|----------|---------|----------|
| BIOHEAL BOH | **미등록** | — | — |
| WAKEMAKE | **미등록** | — | — |

**Amazon India 데이터셋에서 두 브랜드 모두 검색되지 않습니다.**

비교를 위해 동일 데이터셋에서 K-Beauty 브랜드 전체를 탐색한 결과:

| 브랜드 | 제품명 | 카테고리 | 리뷰 수 | 평균 평점 |
|--------|--------|----------|---------|----------|
| Innisfree | Volcanic Blackhead 3 Step Program | Sheet Mask | 196 | 3.34 |
| COSRX | Acne Pimple Master Patch | Sheet Mask | 177 | 3.79 |

### 시사점

K-Beauty 브랜드의 Amazon India 내 점유율은 극히 미미한 수준입니다. Innisfree·COSRX와 같이 글로벌 인지도가 높은 브랜드조차 200건 미만의 리뷰에 그칩니다. **BIOHEAL BOH와 WAKEMAKE는 아직 Amazon 생태계에 진입하지 않은 상태**로, 이는 두 가지 의미를 갖습니다.

- **과제**: 브랜드 인지도가 사실상 제로에 가까워 론칭 단계부터 마케팅 전략 수립이 필요
- **기회**: 스킨케어·시트마스크·메이크업 카테고리 전반에서 K-Beauty 공백이 존재하며, 선점 시 강력한 포지셔닝 가능

---

## 2. 전체 판매량 Top-5 (리뷰 수 기준)

| 순위 | 제품명 | 카테고리 | 리뷰 수 | 평균 평점 |
|------|--------|----------|---------|----------|
| 1 | MyGlamm 2IN1 Nail Paint Poolside Soiree 2X5ml | Nail Polish | 9,942 | 4.19 |
| 2 | Faces Splash Enamel Floral Dream | Nail Polish | 9,836 | 4.17 |
| 3 | Revlon Nail Enamel Matt Coat | Nail Polish | 9,344 | 4.19 |
| 4 | Revlon Nail Enamel Red Fiesta | Nail Polish | 8,851 | 4.18 |
| 5 | ILLUMOR Crushed Diamond Polish Gilded | Nail Polish | 8,040 | 4.28 |

**전체 Top-5가 Nail Polish로 채워진 이유**: Amazon India 뷰티 시장에서 네일 제품은 저렴한 단가와 높은 충동 구매율을 바탕으로 리뷰 생성 속도가 압도적으로 빠릅니다. 단, 이는 Amazon India의 지역적 특성이 반영된 결과로, 일본 시장과의 직접 비교에는 주의가 필요합니다.

---

## 3. 카테고리별 Top-5 (스킨케어 집중 분석)

### Face Serum (얼굴 세럼)
| 순위 | 제품명 | 리뷰 수 | 평균 평점 |
|------|--------|---------|----------|
| 1 | Garnier Turbo Bright Super Serum | 2,883 | 4.26 |
| 2 | Biotique Dandelion Visibly Ageless Serum | 2,141 | 4.04 |
| 3 | Minimalist Tranexamic Acid Serum | 1,722 | 3.55 |
| 4 | Minimalist Niacinamide Serum | 1,668 | 4.04 |
| 5 | Plum Niacinamide Fermented Serum | 1,609 | 3.64 |

### Cream & Moisturizer (크림·보습)
상위 제품은 Nivea, Pond's, Himalaya 등 대형 글로벌·인도 로컬 브랜드가 독점. K-Beauty 고기능 크림 (BIOHEAL BOH 계열) 진입 여지 다수.

### Sunscreen (선크림)
| 순위 | 제품명 | 리뷰 수 | 평균 평점 |
|------|--------|---------|----------|
| 1 | Biotique Sandalwood Sunscreen | 4,641 | 4.06 |
| 2 | POND'S Bright Non-Oily Moisturizer | 4,557 | 4.20 |
| 3 | Dr. Sheth's Sunscreen Sensitive | 4,099 | 4.25 |
| 4 | Lotus Herbals Matte Daily Sunblock | 3,922 | 3.96 |
| 5 | Shield Pollution Protect Mineral Sunscreen | 3,058 | 4.15 |

**선크림 시장(133,427 리뷰)**은 스킨케어 카테고리 내 최대 볼륨을 자랑합니다. BIOHEAL BOH의 에이징케어·고기능 성분 포지셔닝으로 차별화 가능성 높음.

### Sheet Mask (시트마스크)
| 순위 | 제품명 | 리뷰 수 | 평균 평점 |
|------|--------|---------|----------|
| 1 | Lakme Blush Glow Strawberry Sheet | 533 | **4.70** |
| 2 | Innisfree Volcanic Blackhead 3 Step | 196 | 3.34 |
| 3 | COSRX Acne Pimple Master Patch | 177 | 3.79 |

시트마스크 카테고리(11,189 리뷰)는 상대적으로 볼륨이 낮지만 **평점 1위 제품이 4.70점**으로 만족도가 매우 높습니다. K-Beauty 시트마스크의 품질 경쟁력을 잘 살리면 빠른 점유율 확보가 가능한 카테고리입니다.

---

## 4. 성별 Top-5

> **성별 판단 기준**: 제품 타입 및 제품명 키워드 기반 추정 (Nail Polish·Lipstick·Mascara → 여성, Trimmers·Shaving → 남성, Sunscreen·Cleanser·Shower Gel → 유니섹스)

### 성별 리뷰 분포

| 성별 | 리뷰 수 | 비중 |
|------|---------|------|
| Unisex (유니섹스) | 823,216 | 61.1% |
| Female (여성 타겟) | 432,759 | 32.1% |
| Male (남성 타겟) | 92,271 | 6.8% |

### 여성 타겟 Top-5
| 순위 | 제품명 | 카테고리 | 리뷰 수 | 평균 평점 |
|------|--------|----------|---------|----------|
| 1 | MyGlamm 2IN1 Nail Paint Poolside Soiree | Nail Polish | 9,942 | 4.19 |
| 2 | Faces Splash Enamel Floral Dream | Nail Polish | 9,836 | 4.17 |
| 3 | Revlon Nail Enamel Matt Coat | Nail Polish | 9,344 | 4.19 |
| 4 | Revlon Nail Enamel Red Fiesta | Nail Polish | 8,851 | 4.18 |
| 5 | ILLUMOR Crushed Diamond Polish Gilded | Nail Polish | 8,040 | 4.28 |

WAKEMAKE가 타겟으로 하는 **컬러 코스메틱** 영역에서 여성 소비자의 구매력이 집중되어 있음을 확인할 수 있습니다. 다만 현재 상위권은 네일 제품이 장악한 상태로, 립·아이·베이스 메이크업 영역은 진입 가능성이 열려 있습니다.

### 남성 타겟 Top-5
| 순위 | 제품명 | 카테고리 | 리뷰 수 | 평균 평점 |
|------|--------|----------|---------|----------|
| 1 | Himalaya Herbals Protein Shampoo Gentle | Shampoo | 5,506 | 4.19 |
| 2 | Biotique Protein Intensive Regrowth Treatment | Shampoo | 4,189 | 4.18 |
| 3 | Himalaya Herbals Purifying Neem Face Wash 100ml | Face Wash | 3,582 | 4.24 |
| 4 | Himalaya Herbals Purifying Neem Face Wash 150ml | Face Wash | 2,250 | 4.10 |
| 5 | Beardo Beard Color Men Natural | Hair Color | 2,214 | 3.99 |

### 유니섹스 Top-5
| 순위 | 제품명 | 카테고리 | 리뷰 수 | 평균 평점 |
|------|--------|----------|---------|----------|
| 1 | Nivea Pure Impact Shower 500ml | Shower Gel | 6,469 | 4.15 |
| 2 | Vivel Body Wash Lavender Almond | Shower Gel | 5,919 | 4.16 |
| 3 | mCaffeine Salicylic Exfoliates | Shower Gel | 5,036 | 4.04 |
| 4 | Pears Pure Gentle Body Extract | Shower Gel | 5,035 | 4.27 |
| 5 | Nivea Dark Spot Reduction 100ml | Face Wash | 4,825 | 4.14 |

---

## 5. 추가 분석 인사이트

### 5-1. 브랜드 점유율 Top-10 (전체 리뷰 수 합산)

| 순위 | 브랜드 | 총 리뷰 수 | 제품 수 | 평균 평점 |
|------|--------|-----------|--------|----------|
| 1 | Revlon | 39,995 | 9 | 4.17 |
| 2 | Lakme | 36,894 | 29 | 4.13 |
| 3 | Mamaearth | 35,706 | 30 | 4.14 |
| 4 | Biotique | 35,470 | 23 | 4.11 |
| 5 | Nivea | 33,788 | 20 | 4.22 |
| 6 | MyGlamm | 31,811 | 7 | 4.11 |
| 7 | L'Oréal | 31,142 | 25 | 4.04 |
| 8 | Minimalist | 24,437 | 25 | 4.05 |
| 9 | Garnier | 23,829 | 23 | 4.12 |
| 10 | Himalaya | 21,891 | 12 | 4.14 |

**K-Beauty 브랜드는 Top-10 어디에도 없습니다.** 이 공백이 곧 BIOHEAL BOH · WAKEMAKE의 진입 기회입니다.

### 5-2. 평점 분포 — 소비자 만족도 패턴

| 평점 | 리뷰 수 | 비중 |
|------|---------|------|
| ★ 1점 | 120,305 | 8.9% |
| ★ 2점 | 75,480 | 5.6% |
| ★ 3점 | 114,825 | 8.5% |
| ★ 4점 | 214,453 | 15.9% |
| ★ 5점 | 823,183 | **61.1%** |

전체 리뷰의 **61.1%가 5점**으로, 뷰티 카테고리 전반에서 소비자 만족도가 양극화되어 있습니다. 4~5점 합산 시 77%가 긍정 리뷰입니다. 이는 **품질 기반의 신뢰 구축**이 빠른 재구매와 직결되는 시장임을 시사합니다.

### 5-3. 스킨케어 카테고리 시장 규모 비교

| 카테고리 | 리뷰 수 | 평균 평점 | 비고 |
|----------|---------|----------|------|
| Sunscreen | 133,427 | 4.12 | 최대 볼륨, 필수재화 |
| Face Wash & Cleansers | 112,020 | 4.14 | 일상 루틴 상품 |
| Face Serum | 54,001 | 4.05 | 프리미엄 가격대 가능 |
| Cream & Moisturizer | 34,109 | 4.05 | BIOHEAL BOH 주력 |
| Sheet Mask | 11,189 | 4.16 | K-Beauty 강점 카테고리 |

BIOHEAL BOH가 강점을 갖는 **Cream & Moisturizer(34,109 리뷰)**와 **Sheet Mask(11,189 리뷰)** 모두 평균 평점이 높게 형성되어 있어, 품질 중심 포지셔닝이 유효한 카테고리입니다.

### 5-4. 고평점 제품 Top-5 (리뷰 500건 이상 기준)

| 순위 | 제품명 | 카테고리 | 리뷰 수 | 평균 평점 |
|------|--------|----------|---------|----------|
| 1 | Lakme Blush Glow Strawberry Sheet | Sheet Mask | 533 | **4.70** |
| 2 | Wet N Wild Megalast Catsuit Lipstick | Lipstick | 735 | **4.61** |
| 3 | Dance Eyeshadow Palette Multicolor EP12 02 | Eye Shadow | 565 | **4.60** |
| 4 | Blue Heaven Twist Mascara Black | Eye Shadow & Mascara | 970 | **4.55** |
| 5 | Plum BodyLovin Fragrance Body Lotion | Deo & Perfume | 898 | **4.53** |

메이크업 제품(립, 아이섀도, 마스카라)과 시트마스크가 **소비자 만족도 최상위권**을 형성하고 있습니다. WAKEMAKE의 트렌드 컬러 코스메틱 및 BIOHEAL BOH의 시트마스크 라인은 이 고만족도 세그먼트에 직접 경쟁할 수 있는 제품군입니다.

### 5-5. K-Beauty 시장 공백 — 전략적 기회 맵

```
리뷰 수 (시장 규모)
  ↑
133K ┤ Sunscreen ← 대형 인도·글로벌 브랜드 독점 / K-Beauty 침투율 <0.1%
112K ┤ Face Wash
 54K ┤ Face Serum ← K-Beauty 기능성 세럼 경쟁력 ★★★
 34K ┤ Cream & Moisturizer ← BIOHEAL BOH 에이징케어 적합 ★★★★
 11K ┤ Sheet Mask ← K-Beauty 원조 카테고리, 점유율 확보 시작 가능 ★★★★★
     └──────────────────────────────────────────────
                                K-Beauty 점유율 (현재 거의 0)
```

---

## 6. 종합 결론 및 마케팅 방향성 제언

### 현황 요약
- BIOHEAL BOH · WAKEMAKE는 Amazon Beauty 데이터셋(약 24,000 제품)에 **미등록** 상태
- K-Beauty 전체 입지: 데이터셋 내 2개 제품(Innisfree, COSRX) 합산 373건 리뷰 — 시장 점유율 **0.03%**
- 경쟁 브랜드(Revlon, Lakme, Mamaearth 등)는 수만 건의 리뷰를 보유

### 기회 포인트
1. **K-Beauty 공백**: 기능성 스킨케어(세럼, 보습크림, 시트마스크) 카테고리에서 K-Beauty 경쟁자가 없음
2. **메이크업 만족도 상위권 공백**: 4.5점+ 고평점 메이크업 제품군에서 WAKEMAKE 포지셔닝 가능
3. **5점 리뷰 61% 시장**: 초기 충성 리뷰어 확보 → 입소문 마케팅 연결 고리가 강한 시장

### 리스크 요인
- 현재 Amazon India 기반 데이터로, 일본 시장과 소비자 특성 차이 존재
- 기존 상위 브랜드(Himalaya, Biotique 등)는 현지 허브·성분 중심 포지셔닝으로 강력한 로컬 신뢰 형성
- K-Beauty에 대한 별도 마케팅 없이는 브랜드 인지도 자연 유입 기대 불가

---

*분석 기준일: 2026-06-21 | 데이터 기간: 2010–2014 (Amazon India 리뷰 타임스탬프 기준)*
