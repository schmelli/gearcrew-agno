"""Site pattern definitions for LLM-driven website analysis.

Contains dataclasses and JSON schema for representing site structure patterns
discovered by the LLM analyzer.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional


# JSON Schema for DeepSeek response validation
SITE_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string", "description": "The domain analyzed"},
        "platform": {
            "type": "string",
            "enum": ["shopify", "woocommerce", "magento", "prestashop", "custom", "unknown"],
            "description": "Detected e-commerce platform",
        },
        "platform_confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence in platform detection (0-1)",
        },
        "product_patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "regex": {"type": "string", "description": "Regex pattern for product URLs"},
                    "description": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "example_matches": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["regex", "confidence"],
            },
        },
        "category_patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "regex": {"type": "string", "description": "Regex pattern for category URLs"},
                    "description": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "example_matches": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["regex", "confidence"],
            },
        },
        "skip_patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "regex": {"type": "string"},
                    "reason": {"type": "string", "description": "Why to skip these URLs"},
                },
                "required": ["regex", "reason"],
            },
        },
        "overall_confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Overall confidence in the analysis",
        },
        "analysis_notes": {"type": "string", "description": "Notes about patterns or limitations"},
    },
    "required": ["domain", "platform", "product_patterns", "category_patterns", "overall_confidence"],
}


@dataclass
class PatternDef:
    """A URL pattern definition from LLM analysis."""

    regex: str
    confidence: float
    description: str = ""
    example_matches: list[str] = field(default_factory=list)
    _compiled: Optional[re.Pattern] = field(default=None, repr=False, compare=False)

    def matches(self, path: str) -> bool:
        """Check if a URL path matches this pattern."""
        if self._compiled is None:
            try:
                self._compiled = re.compile(self.regex, re.IGNORECASE)
            except re.error:
                return False
        return bool(self._compiled.search(path))

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "regex": self.regex,
            "confidence": self.confidence,
            "description": self.description,
            "example_matches": self.example_matches,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PatternDef":
        """Create from dictionary."""
        return cls(
            regex=data["regex"],
            confidence=data.get("confidence", 0.5),
            description=data.get("description", ""),
            example_matches=data.get("example_matches", []),
        )


@dataclass
class SitePatterns:
    """Complete site analysis result from LLM."""

    domain: str
    platform: str
    platform_confidence: float
    product_patterns: list[PatternDef]
    category_patterns: list[PatternDef]
    skip_patterns: list[PatternDef]
    overall_confidence: float
    analysis_notes: str = ""
    created_at: float = field(default_factory=time.time)

    def is_valid(self) -> bool:
        """Check if analysis is reliable enough to use."""
        return (
            self.overall_confidence >= 0.6
            and len(self.product_patterns) > 0
            and any(p.confidence >= 0.7 for p in self.product_patterns)
        )

    def is_expired(self, max_age_hours: int = 24) -> bool:
        """Check if cached analysis is too old."""
        age_hours = (time.time() - self.created_at) / 3600
        return age_hours > max_age_hours

    def get_best_product_pattern(self) -> Optional[PatternDef]:
        """Get the highest confidence product pattern."""
        if not self.product_patterns:
            return None
        return max(self.product_patterns, key=lambda p: p.confidence)

    def get_best_category_pattern(self) -> Optional[PatternDef]:
        """Get the highest confidence category pattern."""
        if not self.category_patterns:
            return None
        return max(self.category_patterns, key=lambda p: p.confidence)

    def matches_product(self, path: str) -> bool:
        """Check if path matches any product pattern."""
        return any(p.matches(path) for p in self.product_patterns)

    def matches_category(self, path: str) -> bool:
        """Check if path matches any category pattern."""
        return any(p.matches(path) for p in self.category_patterns)

    def should_skip(self, path: str) -> bool:
        """Check if path should be skipped."""
        return any(p.matches(path) for p in self.skip_patterns)

    def to_dict(self) -> dict:
        """Serialize for caching."""
        return {
            "domain": self.domain,
            "platform": self.platform,
            "platform_confidence": self.platform_confidence,
            "product_patterns": [p.to_dict() for p in self.product_patterns],
            "category_patterns": [p.to_dict() for p in self.category_patterns],
            "skip_patterns": [{"regex": p.regex, "reason": p.description} for p in self.skip_patterns],
            "overall_confidence": self.overall_confidence,
            "analysis_notes": self.analysis_notes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SitePatterns":
        """Create from dictionary (cached data)."""
        product_patterns = [PatternDef.from_dict(p) for p in data.get("product_patterns", [])]
        category_patterns = [PatternDef.from_dict(p) for p in data.get("category_patterns", [])]
        skip_patterns = [
            PatternDef(regex=p["regex"], confidence=1.0, description=p.get("reason", ""))
            for p in data.get("skip_patterns", [])
        ]

        return cls(
            domain=data["domain"],
            platform=data.get("platform", "unknown"),
            platform_confidence=data.get("platform_confidence", 0.5),
            product_patterns=product_patterns,
            category_patterns=category_patterns,
            skip_patterns=skip_patterns,
            overall_confidence=data.get("overall_confidence", 0.5),
            analysis_notes=data.get("analysis_notes", ""),
            created_at=data.get("created_at", time.time()),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "SitePatterns":
        """Parse LLM JSON response into SitePatterns."""
        data = json.loads(json_str)

        product_patterns = [
            PatternDef(
                regex=p["regex"],
                confidence=p.get("confidence", 0.5),
                description=p.get("description", ""),
                example_matches=p.get("example_matches", []),
            )
            for p in data.get("product_patterns", [])
        ]

        category_patterns = [
            PatternDef(
                regex=p["regex"],
                confidence=p.get("confidence", 0.5),
                description=p.get("description", ""),
                example_matches=p.get("example_matches", []),
            )
            for p in data.get("category_patterns", [])
        ]

        skip_patterns = [
            PatternDef(regex=p["regex"], confidence=1.0, description=p.get("reason", ""))
            for p in data.get("skip_patterns", [])
        ]

        return cls(
            domain=data.get("domain", "unknown"),
            platform=data.get("platform", "unknown"),
            platform_confidence=data.get("platform_confidence", 0.5),
            product_patterns=product_patterns,
            category_patterns=category_patterns,
            skip_patterns=skip_patterns,
            overall_confidence=data.get("overall_confidence", 0.5),
            analysis_notes=data.get("analysis_notes", ""),
        )


@dataclass
class ExtractionResult:
    """Result from smart site extraction."""

    products: list[dict]
    source: str  # "smart_extraction", "cloud_crawl_fallback", "legacy_fallback"
    patterns: Optional[SitePatterns] = None
    from_cache: bool = False
    estimated_cost: float = 0.0
    stats: dict = field(default_factory=dict)
