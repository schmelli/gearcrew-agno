"""Two-Pass Product Verification System.

Pass 1: Extract gear candidates from transcript (uncertain mentions)
Pass 2a: Verify products using Serper web search
Pass 2b: Enrich with specs using Firecrawl search for tricky cases

This system improves extraction for videos WITHOUT detailed descriptions.
"""

import os
import re
import logging
from typing import Optional
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


@dataclass
class GearCandidate:
    """A potential gear item extracted from transcript."""

    raw_mention: str  # Original text from transcript
    possible_brand: Optional[str] = None
    possible_product: Optional[str] = None
    context: str = ""  # Surrounding text for context
    confidence: float = 0.5  # 0.0 = very uncertain, 1.0 = certain

    # Filled after verification
    verified_brand: Optional[str] = None
    verified_product: Optional[str] = None
    verification_source: Optional[str] = None

    # Filled after enrichment
    weight_grams: Optional[int] = None
    price_usd: Optional[float] = None
    category: Optional[str] = None
    specs: dict = field(default_factory=dict)


def verify_product_with_serper(
    product_name: str,
    possible_brand: str = "",
    context: str = ""
) -> dict:
    """Verify a product mention using Serper web search.

    This is Pass 2a - quick verification to confirm product exists
    and get the correct brand/product name spelling.

    Args:
        product_name: The product name as heard/extracted
        possible_brand: Possible brand name (may be misspelled)
        context: Additional context from the transcript

    Returns:
        Dict with verified info:
        - verified: bool - whether product was found
        - brand: str - correct brand name
        - product: str - correct product name
        - url: str - product page URL
        - confidence: float - verification confidence
        - source: str - where info came from
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        logger.warning("SERPER_API_KEY not set")
        return {"verified": False, "error": "No API key"}

    # Build search query
    query_parts = []
    if possible_brand:
        query_parts.append(possible_brand)
    query_parts.append(product_name)
    query_parts.append("backpacking OR hiking OR ultralight gear")

    query = " ".join(query_parts)

    try:
        response = httpx.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 5},
            timeout=15.0
        )

        if response.status_code == 403:
            return {"verified": False, "error": "API credits exhausted"}

        response.raise_for_status()
        data = response.json()

        organic = data.get("organic", [])
        if not organic:
            return {"verified": False, "confidence": 0.0}

        # Analyze results to find product info
        result = _analyze_serper_results(organic, product_name, possible_brand)
        return result

    except Exception as e:
        logger.error(f"Serper verification failed: {e}")
        return {"verified": False, "error": str(e)}


def _analyze_serper_results(
    results: list[dict],
    product_name: str,
    possible_brand: str
) -> dict:
    """Analyze Serper results to extract verified product info."""

    # Known outdoor gear brands for matching
    KNOWN_BRANDS = {
        "zpacks", "gossamer gear", "ula", "granite gear", "osprey",
        "hyperlite mountain gear", "hmg", "tarptent", "big agnes",
        "msr", "enlightened equipment", "ee", "katabatic", "nunatak",
        "mountain laurel designs", "mld", "pa'lante", "palante",
        "atom packs", "waymark", "durston", "drop", "dan durston",
        "nemo", "thermarest", "sea to summit", "outdoor research", "or",
        "patagonia", "arc'teryx", "arcteryx", "rab", "montbell",
        "toaks", "evernew", "brs", "soto", "jetboil", "msr",
        "sawyer", "katadyn", "befree", "platypus", "cnoc",
        "farpointe", "outdoor vitals", "ov", "senchi", "melanzana",
        "skurka", "timmermade", "nunatak", "western mountaineering",
        "feathered friends", "katabatic gear", "locus gear",
        "six moon designs", "smd", "yama mountain gear", "borah gear",
        "enlightened equipment", "hammock gear", "underground quilts", "uq",
        "dutchware", "warbonnet", "hennessy", "eno",
        "altra", "hoka", "salomon", "la sportiva", "brooks",
        "injinji", "darn tough", "smartwool", "icebreaker",
        "black diamond", "petzl", "leki", "cascade mountain tech",
    }

    best_match = None
    best_confidence = 0.0

    for result in results:
        title = result.get("title", "").lower()
        snippet = result.get("snippet", "").lower()
        link = result.get("link", "")

        # Check for brand mentions
        found_brand = None
        for brand in KNOWN_BRANDS:
            if brand in title or brand in snippet:
                found_brand = brand.title()
                if brand in ["hmg"]:
                    found_brand = "Hyperlite Mountain Gear"
                elif brand in ["mld"]:
                    found_brand = "Mountain Laurel Designs"
                elif brand in ["ee"]:
                    found_brand = "Enlightened Equipment"
                elif brand in ["or"]:
                    found_brand = "Outdoor Research"
                elif brand in ["ov"]:
                    found_brand = "Outdoor Vitals"
                elif brand in ["smd"]:
                    found_brand = "Six Moon Designs"
                break

        # Calculate confidence
        confidence = 0.3  # Base confidence for finding results

        # Boost if product name appears in title
        if product_name.lower() in title:
            confidence += 0.3

        # Boost if brand matches
        if found_brand and possible_brand:
            if found_brand.lower() in possible_brand.lower() or possible_brand.lower() in found_brand.lower():
                confidence += 0.2

        # Boost for manufacturer/retailer sites
        trusted_domains = ["rei.com", "backcountry.com", "moosejaw.com",
                         "zpacks.com", "gossamergear.com", "ula-equipment.com",
                         "tarptent.com", "bigagnes.com", "enlightenedequipment.com"]
        if any(domain in link for domain in trusted_domains):
            confidence += 0.2

        if confidence > best_confidence:
            best_confidence = confidence
            best_match = {
                "verified": True,
                "brand": found_brand or possible_brand,
                "product": _extract_product_name(title, found_brand),
                "url": link,
                "confidence": min(confidence, 1.0),
                "source": "serper",
                "title": result.get("title", ""),
                "snippet": result.get("snippet", "")
            }

    if best_match:
        return best_match

    return {"verified": False, "confidence": 0.0}


def _extract_product_name(title: str, brand: str = None) -> str:
    """Extract clean product name from search result title."""
    # Remove common suffixes
    name = title
    for suffix in [" - ", " | ", " – ", " : "]:
        if suffix in name:
            name = name.split(suffix)[0]

    # Remove brand if present at start
    if brand:
        name = re.sub(rf"^{re.escape(brand)}\s+", "", name, flags=re.IGNORECASE)

    return name.strip()


def enrich_with_firecrawl(
    product_name: str,
    brand: str,
    product_url: str = None
) -> dict:
    """Enrich product data using Firecrawl search.

    This is Pass 2b - deep research for specs on tricky cases.
    Uses Firecrawl to search for and extract detailed specifications.

    Args:
        product_name: Verified product name
        brand: Verified brand name
        product_url: Optional URL to scrape directly

    Returns:
        Dict with enriched specs:
        - weight_grams: int
        - price_usd: float
        - materials: list[str]
        - features: list[str]
        - category: str
    """
    try:
        from app.tools.smart_firecrawl import get_smart_firecrawl
        firecrawl = get_smart_firecrawl()
    except Exception as e:
        logger.warning(f"Could not initialize Firecrawl: {e}")
        return {}

    # Build search query for specs
    query = f"{brand} {product_name} specifications weight oz grams"

    try:
        logger.info(f"[Firecrawl] Searching specs for: {brand} {product_name}")
        results = firecrawl.search(query, limit=3)

        if not results:
            return {}

        # Extract specs from search results
        specs = _extract_specs_from_results(results, product_name, brand)
        return specs

    except Exception as e:
        logger.error(f"Firecrawl enrichment failed: {e}")
        return {}


def _extract_specs_from_results(results: list, product_name: str, brand: str) -> dict:
    """Extract specifications from Firecrawl search results."""
    specs = {}

    # Weight patterns (oz and grams)
    weight_patterns = [
        r"(\d+(?:\.\d+)?)\s*(?:oz|ounces?)",
        r"(\d+(?:\.\d+)?)\s*(?:g|grams?)",
        r"weight[:\s]+(\d+(?:\.\d+)?)\s*(?:oz|g)",
    ]

    # Price patterns
    price_patterns = [
        r"\$(\d+(?:\.\d{2})?)",
        r"(\d+(?:\.\d{2})?)\s*(?:USD|dollars?)",
    ]

    for result in results:
        content = ""
        if isinstance(result, dict):
            content = result.get("markdown", "") or result.get("content", "") or result.get("snippet", "")
        elif hasattr(result, "markdown"):
            content = result.markdown or ""

        content_lower = content.lower()

        # Extract weight
        if "weight_grams" not in specs:
            for pattern in weight_patterns:
                match = re.search(pattern, content_lower)
                if match:
                    value = float(match.group(1))
                    # Convert oz to grams if needed
                    if "oz" in pattern or "ounces" in pattern:
                        value = int(value * 28.35)
                    else:
                        value = int(value)
                    specs["weight_grams"] = value
                    break

        # Extract price
        if "price_usd" not in specs:
            for pattern in price_patterns:
                match = re.search(pattern, content)
                if match:
                    specs["price_usd"] = float(match.group(1))
                    break

        # Extract materials (common outdoor gear materials)
        materials = []
        material_keywords = [
            "dyneema", "dcf", "cuben fiber", "silnylon", "silpoly",
            "ripstop", "cordura", "xpac", "ultra", "pertex",
            "gore-tex", "goretex", "polartec", "primaloft", "down",
            "titanium", "aluminum", "carbon fiber"
        ]
        for mat in material_keywords:
            if mat in content_lower:
                materials.append(mat.title())
        if materials:
            specs["materials"] = list(set(materials))

    return specs


def verify_and_enrich_candidate(candidate: GearCandidate) -> GearCandidate:
    """Full two-pass verification and enrichment for a gear candidate.

    Args:
        candidate: GearCandidate with initial extraction data

    Returns:
        Updated GearCandidate with verification and enrichment
    """
    # Pass 2a: Verify with Serper
    verification = verify_product_with_serper(
        product_name=candidate.possible_product or candidate.raw_mention,
        possible_brand=candidate.possible_brand or "",
        context=candidate.context
    )

    if verification.get("verified"):
        candidate.verified_brand = verification.get("brand")
        candidate.verified_product = verification.get("product")
        candidate.verification_source = verification.get("url")
        candidate.confidence = verification.get("confidence", 0.5)

        # Pass 2b: Enrich with Firecrawl if confidence is moderate
        # (high confidence = probably already have good data)
        # (low confidence = might be wrong product)
        if 0.4 <= candidate.confidence <= 0.8:
            enrichment = enrich_with_firecrawl(
                product_name=candidate.verified_product,
                brand=candidate.verified_brand,
                product_url=verification.get("url")
            )

            if enrichment:
                candidate.weight_grams = enrichment.get("weight_grams")
                candidate.price_usd = enrichment.get("price_usd")
                candidate.specs = enrichment

    return candidate


def batch_verify_candidates(candidates: list[GearCandidate]) -> list[GearCandidate]:
    """Verify and enrich a batch of gear candidates.

    Args:
        candidates: List of GearCandidate objects

    Returns:
        List of verified/enriched candidates
    """
    verified = []

    for candidate in candidates:
        try:
            result = verify_and_enrich_candidate(candidate)
            if result.verified_brand or result.confidence > 0.3:
                verified.append(result)
        except Exception as e:
            logger.error(f"Failed to verify candidate {candidate.raw_mention}: {e}")

    return verified


# Agent-callable wrapper functions

def verify_gear_mention(
    product_name: str,
    possible_brand: str = "",
    context: str = ""
) -> str:
    """Verify a gear mention from a video transcript using web search.

    Use this when you hear a product mentioned in a video but aren't sure
    about the exact brand name or spelling. Common with audio transcripts
    where brand names are often misheard.

    Examples:
        - "gossamer here" → Gossamer Gear
        - "u l a" → ULA (Ultra Light Adventure)
        - "enlightened equipment revelation" → Enlightened Equipment Revelation quilt

    Args:
        product_name: Product name as heard in video (may be misspelled)
        possible_brand: Possible brand name (may also be wrong)
        context: What was said around this mention (helps with verification)

    Returns:
        Verification result with correct brand/product names
    """
    result = verify_product_with_serper(product_name, possible_brand, context)

    if result.get("verified"):
        return f"""✅ **Product Verified**
- Brand: {result.get('brand', 'Unknown')}
- Product: {result.get('product', product_name)}
- Confidence: {result.get('confidence', 0):.0%}
- Source: {result.get('url', 'N/A')}

Use these verified names when calling `save_gear_to_graph()`."""
    else:
        error = result.get("error", "Product not found in search results")
        return f"""❌ **Could Not Verify**
- Searched for: {possible_brand} {product_name}
- Reason: {error}

Consider:
1. Try different spelling variations
2. Search for the full product line (e.g., "Zpacks backpacks" instead of specific model)
3. Skip this item if confidence is too low"""


def research_gear_specs(
    product_name: str,
    brand: str
) -> str:
    """Research detailed specifications for a verified product.

    Use this AFTER verifying a product to get detailed specs like
    weight, price, and materials. Uses Firecrawl for deep web research.

    Args:
        product_name: Verified product name
        brand: Verified brand name

    Returns:
        Detailed specifications for the product
    """
    specs = enrich_with_firecrawl(product_name, brand)

    if specs:
        output = [f"📊 **Specs for {brand} {product_name}**"]

        if specs.get("weight_grams"):
            oz = specs["weight_grams"] / 28.35
            output.append(f"- Weight: {specs['weight_grams']}g ({oz:.1f}oz)")

        if specs.get("price_usd"):
            output.append(f"- Price: ${specs['price_usd']:.2f}")

        if specs.get("materials"):
            output.append(f"- Materials: {', '.join(specs['materials'])}")

        output.append("\nUse these specs when calling `save_gear_to_graph()`.")
        return "\n".join(output)
    else:
        return f"""⚠️ **Could not find detailed specs**
- Product: {brand} {product_name}

Try:
1. Searching the manufacturer's website directly
2. Using `search_gear_info()` for more general research
3. Saving with basic info and updating later"""
