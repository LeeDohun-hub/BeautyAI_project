from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(100), default="Guest")
    role: Mapped[str] = mapped_column(String(30), default="customer")
    # BeautyWEB members.id. 핸드오프 티켓으로 들어온 계정을 여기에 붙여 같은 사람의
    # 분석·추천 이력이 이어지게 한다. 웹을 안 거친 사용자는 None 이다.
    web_member_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    login_id: Mapped[str | None] = mapped_column(String(100))
    # 웹 마이페이지에서 받아온 프로필. 설문 프리필과 퍼스널컬러 바로쓰기에 쓴다.
    gender: Mapped[str | None] = mapped_column(String(20))
    age_group: Mapped[str | None] = mapped_column(String(20))
    skin_type: Mapped[str | None] = mapped_column(String(40))
    personal_color: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    surveys: Mapped[list["Survey"]] = relationship(back_populates="user")
    analyses: Mapped[list["SkinAnalysis"]] = relationship(back_populates="user")
    histories: Mapped[list["RecommendationHistory"]] = relationship(back_populates="user")


class CartHandoff(Base):
    """결과지 QR → 웹 장바구니 담기용 1회용 핸드오프.

    QR 에 상품 목록을 통째로 싣지 않는 이유: 상품 5개(이름·브랜드·구매URL)를 base64 로
    실으면 1KB 를 넘겨 QR 이 아주 조밀해진다(키오스크 출력물에서 인식 실패). 짧은 코드만
    싣고(`<WEB>/cart?ai=<code>`) 실제 목록은 여기서 서버끼리 주고받는다.

    web_member_id 를 함께 들고 있어서 **폰이 로그인 안 돼 있어도** 본인 계정 장바구니에
    담긴다. 대신 코드 자체가 베어러 자격증명이므로 짧은 수명 + 1회용으로 태운다.
    """

    __tablename__ = "cart_handoffs"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    web_member_id: Mapped[int] = mapped_column(Integer, index=True)
    # [{name, brand, url, image_url, price, source, external_id}] 직렬화.
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)


class UsedTicket(Base):
    """소각한 핸드오프 티켓의 jti.

    티켓은 URL 프래그먼트에 실려 오므로 브라우저 히스토리에는 남는다. 수명이 120초로
    짧지만 그 안에 재사용되는 것까지 막으려고 1회용으로 태운다. Redis 를 쓸까 했지만
    이 프로젝트는 redis 패키지를 실제로 안 쓰고 있어(설정값만 있다) 의존성을 늘리는 대신
    DB 유니크 제약으로 막는다 — 교환은 사용자당 세션에 한 번뿐이라 비용이 문제되지 않는다.
    """

    __tablename__ = "used_tickets"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    used_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Survey(Base):
    __tablename__ = "surveys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    skin_type: Mapped[str] = mapped_column(String(40))
    concerns: Mapped[str] = mapped_column(Text, default="")
    sensitivity: Mapped[int] = mapped_column(Integer, default=2)
    routine_level: Mapped[str] = mapped_column(String(40), default="basic")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User | None] = relationship(back_populates="surveys")


class SkinAnalysis(Base):
    __tablename__ = "skin_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    acne: Mapped[float] = mapped_column(Float)
    pore: Mapped[float] = mapped_column(Float)
    wrinkle: Mapped[float] = mapped_column(Float)
    redness: Mapped[float] = mapped_column(Float)
    pigmentation: Mapped[float] = mapped_column(Float)
    oiliness: Mapped[float] = mapped_column(Float)
    image_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User | None] = relationship(back_populates="analyses")


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")

    products: Mapped[list["Product"]] = relationship(back_populates="brand")


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    benefit: Mapped[str] = mapped_column(Text)
    targets: Mapped[str] = mapped_column(String(255))

    products: Mapped[list["ProductIngredient"]] = relationship(back_populates="ingredient")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"))
    name: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(80))
    skin_types: Mapped[str] = mapped_column(String(255), default="all")
    price: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    product_url: Mapped[str] = mapped_column(String(500), default="")
    image_url: Mapped[str] = mapped_column(String(500), default="")
    avg_rating: Mapped[float] = mapped_column(Float, default=0.0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)

    brand: Mapped[Brand] = relationship(back_populates="products")
    ingredients: Mapped[list["ProductIngredient"]] = relationship(back_populates="product")


class ProductIngredient(Base):
    __tablename__ = "product_ingredients"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    product: Mapped[Product] = relationship(back_populates="ingredients")
    ingredient: Mapped[Ingredient] = relationship(back_populates="products")


class RecommendationHistory(Base):
    __tablename__ = "recommendation_histories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("skin_analyses.id"))
    recommended_ingredients: Mapped[str] = mapped_column(Text)
    recommended_products: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User | None] = relationship(back_populates="histories")


class ChatHistory(Base):
    __tablename__ = "chat_histories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

