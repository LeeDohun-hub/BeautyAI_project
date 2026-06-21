"""
Olive Young crawler + product recommender 실행 예시.

사용 예:
1. 상품 수집 및 저장
   python main.py --crawl

2. 이미 저장된 products.csv로 추천만 실행
   python main.py

포트폴리오/개인 학습용 프로젝트를 전제로 작성했으며,
실행 전 대상 사이트의 이용약관과 robots.txt를 확인하세요.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from crawler.oliveyoung_crawler import crawl_categories, save_products_csv, save_products_json
from recommender.product_recommender import load_products, recommend_products


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
CSV_PATH = DATA_DIR / "products.csv"
JSON_PATH = DATA_DIR / "products.json"


def run_crawler() -> None:
    """올리브영 랭킹 페이지에서 상품을 수집해 CSV/JSON으로 저장합니다."""
    products = crawl_categories(
        categories=["toner", "lotion", "serum", "cream", "spot_care"],
        limit_per_category=100,
        sleep_seconds=1.5,
    )
    save_products_csv(products, CSV_PATH)
    save_products_json(products, JSON_PATH)
    print(f"크롤링 완료: {len(products)}개 상품 저장")
    print(f"- CSV: {CSV_PATH}")
    print(f"- JSON: {JSON_PATH}")


def run_recommender() -> None:
    """요구사항의 예시 피부진단 결과로 TOP5 상품을 추천합니다."""
    if not CSV_PATH.exists():
        print("products.csv가 없어 먼저 크롤링을 실행합니다.")
        run_crawler()

    products = load_products(CSV_PATH)
    if not products:
        print("상품 데이터가 비어 있어 먼저 크롤링을 실행합니다.")
        run_crawler()
        products = load_products(CSV_PATH)

    # 사용자 피부진단 결과 예시입니다.
    skin_type = "oily"
    concerns = ["pore", "acne"]

    recommendations = recommend_products(
        products=products,
        skin_type=skin_type,
        concerns=concerns,
        top_k=5,
    )

    print("\n사용자 피부진단 결과:")
    print(f"- skin_type: {skin_type}")
    print(f"- concerns: {', '.join(concerns)}")

    print("\n추천 상품:")
    if not recommendations:
        print("조건에 맞는 상품을 찾지 못했습니다. 크롤링 selector 또는 태그 규칙을 확인해 주세요.")
        return

    for index, item in enumerate(recommendations, start=1):
        product = item.product
        print(
            f"{index}. {product.brand} / {product.product_name} / "
            f"{product.current_price:,}원 / {item.reason}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Olive Young ranking crawler and cosmetic recommender")
    parser.add_argument("--crawl", action="store_true", help="추천 실행 전에 상품 데이터를 새로 수집합니다.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.crawl:
        run_crawler()
    run_recommender()
