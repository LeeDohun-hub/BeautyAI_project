"""바디/핸드/풋 카테고리 분류 회귀 테스트.

여기 있는 케이스는 전부 실제 소스 CSV에서 오분류로 관측된 것들이다.
규칙을 손볼 때 같은 사고가 되살아나지 않게 고정한다.
"""
from app.services.body_categories import (
    BODY,
    BODY_CARE_CATEGORIES,
    CATEGORIES,
    FOOT,
    HAND,
    classify_by_keyword,
    classify_within_group,
    group_of,
    strip_bundle_extras,
)


def test_categories_are_namespaced_so_face_never_collides() -> None:
    # 바디 경로가 얼굴 크림을 추천하던 원인이 {"cream","lotion"} whitelist였다.
    # 모든 값이 group 접두사를 갖는 한 얼굴 카테고리와 문자열이 겹칠 수 없다.
    for category, meta in CATEGORIES.items():
        assert category.startswith(f"{meta['group']}."), category
    assert "cream" not in CATEGORIES
    assert "lotion" not in CATEGORIES


def test_body_care_categories_exclude_non_care_items() -> None:
    # 데오드란트·제모·미스트는 카탈로그로만 보유하고 질환 추천엔 올리지 않는다.
    assert "body.deodorant" not in BODY_CARE_CATEGORIES
    assert "body.hair_removal" not in BODY_CARE_CATEGORIES
    assert "body.mist" not in BODY_CARE_CATEGORIES
    # 핸드·풋은 그룹 자체가 달라 바디 추천에 섞이지 않는다.
    assert all(group_of(c) == BODY for c in BODY_CARE_CATEGORIES)


def test_official_category_wins_when_name_lacks_body_keyword() -> None:
    # 이름 키워드만 쓰면 올영 공식 Bath & Body 106건 중 55건을 놓친다.
    # 대표 케이스: ILLIYOON 세라마이드 아토로션/울트라 리페어 크림.
    assert classify_within_group(BODY, "body.lotion", "ILLIYOON Ceramide Ato Lotion 334ml") == "body.lotion"
    assert classify_within_group(BODY, "body.lotion", "ILLIYOON Ultra Repair Cream 200ml") == "body.cream"
    # 키워드로는 아무것도 안 잡혀도 공식 기본값은 유지돼야 한다.
    assert classify_within_group(BODY, "body.lotion", "Medi Heally Leg Fitting 6ea") == "body.lotion"


def test_bundle_freebie_does_not_decide_category() -> None:
    # 본품은 크림인데 괄호 안 증정 오일 때문에 body.oil로 잡히던 케이스.
    name = "ILLIYOON MD Red Itch Care Cream 330mL Set (+Red Itch Oil 20mL)"
    assert strip_bundle_extras(name) == "ILLIYOON MD Red Itch Care Cream 330mL Set"
    assert classify_within_group(BODY, "body.lotion", name) == "body.cream"


def test_earliest_form_wins_over_trailing_mention() -> None:
    # 'Body Lotion ... Body and Hand Lotion'이 hand.cream으로 잡히던 순서 버그.
    title = ("Ultra Healing Body Lotion, Moisturizer for Extra Dry Skin, "
             "Body and Hand Lotion with Advanced Ceramide Complex")
    assert classify_by_keyword(title) == "body.lotion"
    # 진짜 핸드크림은 그대로 핸드로 남아야 한다.
    assert classify_by_keyword("Dr.Jart+ Ceramidin Hand Cream 30ml") == "hand.cream"


def test_face_products_with_body_seo_tail_are_rejected() -> None:
    # 아마존 JP 타이틀은 SEO 키워드가 꼬리에 붙어 얼굴 크림이 바디로 잡혔다.
    face_cream = ("COSRX ザ・セラミド肌バリア保湿クリーム 80mL スキンケア "
                  "フェイスクリーム ボディローション ボディクリーム 韓国コスメ")
    assert classify_by_keyword(face_cream) is None
    # 겸용 표기가 있으면 바디로 인정한다.
    dual = "Cure by Toyo Aqua Gel Gentle Exfoliator Non-Abrasive Face and Body Cleanser"
    assert classify_by_keyword(dual) == "body.wash"


def test_suncare_routes_to_body_sun_or_is_rejected() -> None:
    # 얼굴 선크림이 body.lotion으로 잡히던 케이스. 전신 표기가 있으면 body.sun.
    zenshin = ("[d'Alba] トーンアップ UVエッセンス サンクリーム SPF50+/PA++++ "
               "化粧下地 日焼け止め 顔 全身用")
    assert classify_by_keyword(zenshin) == "body.sun"
    # 바디 언급이 전혀 없으면 얼굴 선크림이라 배제.
    assert classify_by_keyword("Some Brand UV Protection Sun Cream SPF50+ 화장품") is None


def test_non_body_products_are_excluded() -> None:
    # 실측 오탐: 립스크럽/헤어오일/속눈썹뷰러가 바디로 잡혔다.
    assert classify_by_keyword("レブロン キス シュガー スクラブ リップケア リップクリーム") is None
    assert classify_by_keyword("CURL KEEPER - Dry Oil Elixir hair serum") is None
    assert classify_by_keyword("Tweezer and Eyelash Curler by Revlon hair removal") is None


def test_body_products_never_enter_face_routine_steps() -> None:
    # classify_routine_step 은 _STRONG_NAME(이름 신호)을 카테고리보다 먼저 본다.
    # 네임스페이스를 먼저 끊지 않으면 아래 상품들이 얼굴 컬럼에 올라온다(실측 16건).
    from app.services.routine_steps import classify_routine_step

    leaky = [
        ("body.wash", "ILLIYOON Ceramide Ato 5.0 Gentle Skin Cleanser 400ml"),
        ("body.wash", "ILLIYOON Ultra Repair Moisture Cleanser 500ml"),
        ("body.lotion", "ILLIYOON Ceramide Ato Gentle Skin Toner 250ml"),
        ("body.sun", "キャンメイク マーメイドスキンジェルUV 日焼け止めジェル SPF50+"),
        ("hand.cream", "Dr.Jart+ Ceramidin Hand Cream 30ml"),
        ("foot.cream", "DASHU Daily Relax Foot Cream"),
    ]
    for category, name in leaky:
        assert classify_routine_step(category, name) is None, (category, name)

    # 얼굴 상품 분류는 그대로여야 한다.
    assert classify_routine_step("cleanser", "Foaming Facial Cleanser") == "cleanser"
    assert classify_routine_step("cream", "Barrier Repair Cream 50ml") == "cream"
    assert classify_routine_step("sunscreen", "UV Sun Cream SPF50") == "sunscreen"


def test_hand_and_foot_stay_in_their_own_groups() -> None:
    # 매니페디큐어 기능이 가져갈 그룹이라 바디와 섞이면 안 된다.
    assert group_of(classify_by_keyword("Mediheal Theraffin Hand Mask 10 Pairs")) == HAND
    assert group_of(classify_by_keyword("DASHU Daily Relax Foot Cream 2.36fl oz")) == FOOT
    assert group_of(classify_by_keyword("SKINFOOD Lemon Verbena Body Lotion 450mL")) == BODY
