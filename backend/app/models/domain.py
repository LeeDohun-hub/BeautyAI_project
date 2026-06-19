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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    surveys: Mapped[list["Survey"]] = relationship(back_populates="user")
    analyses: Mapped[list["SkinAnalysis"]] = relationship(back_populates="user")
    histories: Mapped[list["RecommendationHistory"]] = relationship(back_populates="user")


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

