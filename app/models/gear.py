"""Data models for hiking/backpacking gear information."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class GearCategory(str, Enum):
    """Categories for hiking/backpacking gear."""

    BACKPACK = "backpack"
    TENT = "tent"
    SLEEPING_BAG = "sleeping_bag"
    SLEEPING_PAD = "sleeping_pad"
    CLOTHING = "clothing"
    FOOTWEAR = "footwear"
    COOKWARE = "cookware"
    WATER_FILTRATION = "water_filtration"
    NAVIGATION = "navigation"
    LIGHTING = "lighting"
    TREKKING_POLES = "trekking_poles"
    ACCESSORIES = "accessories"
    FIRST_AID = "first_aid"
    OTHER = "other"


class FactType(str, Enum):
    """Types of knowledge facts that can be extracted."""

    REVIEW = "review"
    TIP = "tip"
    WARNING = "warning"
    COMPARISON = "comparison"
    SPECIFICATION = "specification"
    EXPERIENCE = "experience"


class Manufacturer(BaseModel):
    """Information about a gear manufacturer."""

    name: str = Field(..., description="Company/brand name")
    country: Optional[str] = Field(None, description="Country of origin")
    website: Optional[str] = Field(None, description="Official website URL")


class GearItem(BaseModel):
    """Structured information about a piece of hiking/backpacking gear."""

    name: str = Field(..., description="Full product name")
    brand: str = Field(..., description="Manufacturer/brand name")
    model: Optional[str] = Field(None, description="Model identifier or number")
    category: GearCategory = Field(..., description="Gear category")
    weight_grams: Optional[int] = Field(None, description="Weight in grams")
    price_usd: Optional[float] = Field(None, description="Price in USD")
    materials: list[str] = Field(default_factory=list, description="Materials used")
    features: list[str] = Field(default_factory=list, description="Key features")
    use_cases: list[str] = Field(
        default_factory=list, description="Recommended use cases"
    )
    source_url: Optional[str] = Field(None, description="Source URL of information")


class KnowledgeFact(BaseModel):
    """A piece of knowledge or experience about gear usage."""

    content: str = Field(..., description="The factual content or insight")
    source_url: str = Field(..., description="URL where fact was found")
    gear_item_name: Optional[str] = Field(
        None, description="Associated gear item name"
    )
    fact_type: FactType = Field(..., description="Type of fact")
    confidence: float = Field(
        default=0.8, ge=0.0, le=1.0, description="Confidence score (0-1)"
    )


class ExtractionResult(BaseModel):
    """Result of extracting gear information from a source."""

    source_url: str = Field(..., description="URL of the source")
    source_type: str = Field(..., description="Type of source (youtube, blog, etc)")
    gear_items: list[GearItem] = Field(
        default_factory=list, description="Extracted gear items"
    )
    manufacturers: list[Manufacturer] = Field(
        default_factory=list, description="Extracted manufacturers"
    )
    knowledge_facts: list[KnowledgeFact] = Field(
        default_factory=list, description="Extracted knowledge facts"
    )
    raw_content: Optional[str] = Field(
        None, description="Raw extracted content for reference"
    )
