from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, HttpUrl, field_validator

class SourceProduct(BaseModel):
    id: str
    name: str
    description: str | None = None
    brand: str | None = None
    category: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

class Specification(BaseModel):
    group_name: str | None = None
    name: str
    value: str

class EnrichedProduct(BaseModel):
    name: str
    brand: str | None = None
    description: str | None = None
    category: str | None = None
    price: Decimal | None = None
    images: list[HttpUrl] = Field(default_factory=list)
    specifications: list[Specification] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    review_reason: str | None = None

    @field_validator("price")
    @classmethod
    def nonnegative(cls, value):
        if value is not None and value < 0:
            raise ValueError("price cannot be negative")
        return value

class ProductResult(BaseModel):
    source_id: str
    status: str
    detail: str = ""
