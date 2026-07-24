from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.routine_steps import classify_routine_step, product_routine_step


# ── 명시 카테고리 → 단계 ─────────────────────────────────────────────
@pytest.mark.parametrize("category,expected", [
    ("cleanser", "cleanser"),
    ("Cleansers", "cleanser"),
    ("toner", "toner"),
    ("Pads", "toner"),
    ("serum", "serum"),
    ("essence", "serum"),
    ("ampoule", "serum"),
    ("treatment", "serum"),
    ("Blemish & Acne Treatments", "serum"),
    ("lotion", "lotion"),
    ("cream", "cream"),
    ("Moisturizers", "cream"),
    ("sunscreen", "sunscreen"),
    ("Sunscreen", "sunscreen"),
])
def test_explicit_category_maps(category, expected):
    assert classify_routine_step(category, "whatever name") == expected


# ── 명시 제외 카테고리 → None ────────────────────────────────────────
@pytest.mark.parametrize("category", [
    "mask", "Sheet Masks", "Facial Masks", "Patches", "Gift Set",
    "Body Moisturizers", "Face", "Nose Pack", "Hair Wash", "Eye",
    "Bath & Shower", "After Sun Care",
])
def test_excluded_categories(category):
    assert classify_routine_step(category, "Vitamin C Serum") is None


# ── skincare: 이름 추론 ──────────────────────────────────────────────
@pytest.mark.parametrize("name,expected", [
    ("Fresh Foaming Cleanser", "cleanser"),
    ("Deep Cleansing Oil", "cleanser"),
    ("Hydrating Toner", "toner"),
    ("Soothing Facial Mist", "toner"),
    ("Vitamin C Brightening Serum", "serum"),
    ("Retinol Night Ampoule", "serum"),
    ("2% BHA Liquid Exfoliator", "serum"),
    ("Dark Spot Correcting Essence", "serum"),
    ("Light Daily Emulsion", "lotion"),
    ("Rich Moisture Cream", "cream"),
    ("Ceramide Barrier Butter", "cream"),
    ("Daily Sun SPF50+ PA++++", "sunscreen"),
    ("Tone-up UV Protection Fluid", "sunscreen"),
])
def test_skincare_name_inference(name, expected):
    assert classify_routine_step("skincare", name) == expected


# ── skincare: 잡음/미해결 → None ─────────────────────────────────────
@pytest.mark.parametrize("name", [
    "CAVIAR Anti-Aging Working Hairspray",
    "Melonberry Hair Milk Leave-In Conditioner",
    "10 Day Results Kit",
    "3-Step Starter Set",
    "Nourishing Body Wash",
    "Rosewater Shower Gel",
    "Matte Lip Tint",
    "GENIUS Collagen Calming Relief",   # 단계 키워드 없음 → 미해결
])
def test_skincare_noise_excluded(name):
    assert classify_routine_step("skincare", name) is None


# ── 명시 카테고리라도 잡음 이름이면 제외(품질 게이트) ───────────────
@pytest.mark.parametrize("category,name", [
    ("lotion", "COCO MADEMOISELLE Moisturizing Body Lotion"),
    ("lotion", "Hairdresser's Invisible Oil Ultra Rich Treatment Lotion"),
    ("lotion", "Armani Code After Shave Lotion"),
    ("cream", "GENIUS Ultimate Anti-Aging Eye Cream"),
    ("cream", "Triple Algae Eye Renewal Balm Eye Cream"),
    ("sunscreen", "Hello Happy Flawless Brightening Foundation SPF 15"),
    ("skincare", "COMPLEXION RESCUE Tinted Moisturizer SPF 30"),
    ("serum", "Radiant Cushion Foundation SPF 40"),
])
def test_explicit_category_blocked_by_noise_name(category, name):
    assert classify_routine_step(category, name) is None


# ── balm / gel: 이름 재분류 ──────────────────────────────────────────
@pytest.mark.parametrize("category,name,expected", [
    ("balm", "Cleansing Balm Makeup Melt", "cleanser"),
    ("balm", "Overnight Repair Balm", "cream"),
    ("gel", "Foaming Gel Cleanser", "cleanser"),
    ("gel", "Aloe Soothing Gel", "cream"),
    ("gel", "Hydrating Water Gel", "cream"),
    ("balm", "Styling Hair Balm", None),   # 잡음 블록
])
def test_balm_gel_reclass(category, name, expected):
    assert classify_routine_step(category, name) == expected


# ── 우선순위/경계 ────────────────────────────────────────────────────
def test_priority_sunscreen_beats_cream():
    # 'SPF Moisturizer' 는 크림 키워드도 있지만 선크림이 우선
    assert classify_routine_step("skincare", "Daily Moisturizer SPF30") == "sunscreen"


def test_priority_toner_beats_cream():
    assert classify_routine_step("skincare", "Moisturizing Hydra Toner") == "toner"


@pytest.mark.parametrize("category,name,expected", [
    # 레티노이드/레티놀 = 트리트먼트 → 세럼칸 (emulsion/cream 라벨이라도)
    ("Moisturizers", "Granactive Retinoid 2% Emulsion", "serum"),
    ("skincare", "Advanced Retinol Night Emulsion", "serum"),
    # 잘못된 카테고리 라벨을 강한 이름이 override
    ("cream", "Vegan Rice Milk Moisturizing Toner", "toner"),
    ("Moisturizers", "Deep Cleansing Foam", "cleanser"),
    ("lotion", "Daily Sun SPF50 Fluid", "sunscreen"),
])
def test_strong_name_overrides_category(category, name, expected):
    assert classify_routine_step(category, name) == expected


@pytest.mark.parametrize("category,name", [
    ("skincare", "Renewing Scalp Leave-In Treatment with Hemp"),
    ("treatment", "Scalp Detox Serum"),
    ("serum", "Leave-in Hair Repair Serum"),
])
def test_scalp_hair_leavein_excluded(category, name):
    assert classify_routine_step(category, name) is None


def test_unknown_category_excluded():
    assert classify_routine_step("mystery-category", "Vitamin C Serum") is None


def test_case_insensitive_and_blank():
    assert classify_routine_step("SERUM", "x") == "serum"
    assert classify_routine_step(None, "Gentle Foaming Cleanser") == "cleanser"
    assert classify_routine_step("", "no keyword here") is None


# ── ORM 래퍼 ─────────────────────────────────────────────────────────
def test_product_wrapper():
    product = SimpleNamespace(category="skincare", name="Vitamin C Serum")
    assert product_routine_step(product) == "serum"
