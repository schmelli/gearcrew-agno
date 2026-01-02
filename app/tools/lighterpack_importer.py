"""LighterPack gear list importer with research and ingestion."""

from typing import Optional
import re

from app.tools.lighterpack import parse_lighterpack_url
from app.tools.geargraph import (
    find_similar_gear,
    save_gear_to_graph,
    update_existing_gear,
)
from app.tools.web_scraper import search_web


async def import_lighterpack(url: str, auto_research: bool = True) -> dict:
    """Import gear list from LighterPack.

    Args:
        url: LighterPack list URL
        auto_research: If True, automatically research missing items

    Returns:
        Dict with import statistics and results
    """
    print(f"🔍 Parsing LighterPack: {url}")

    # Parse the pack list
    pack_data = await parse_lighterpack_url(url)

    print(f"📋 Pack: {pack_data['pack_name']}")
    print(f"📊 Items: {pack_data['total_items']}")
    print(f"⚖️  Base Weight: {pack_data['base_weight_grams']}g\n")

    stats = {
        "total_items": pack_data["total_items"],
        "found_in_db": 0,
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "items_processed": [],
    }

    for item in pack_data["items"]:
        result = await _process_item(
            item=item,
            auto_research=auto_research,
        )

        stats["items_processed"].append(result)

        if result["status"] == "found":
            stats["found_in_db"] += 1
        elif result["status"] == "added":
            stats["added"] += 1
        elif result["status"] == "updated":
            stats["updated"] += 1
        elif result["status"] == "skipped":
            stats["skipped"] += 1
        elif result["status"] == "error":
            stats["errors"] += 1

    print(f"\n📊 Import Summary:")
    print(f"  ✅ Found in database: {stats['found_in_db']}")
    print(f"  ➕ New items added: {stats['added']}")
    print(f"  🔄 Existing items updated: {stats['updated']}")
    print(f"  ⏭️  Skipped: {stats['skipped']}")
    print(f"  ❌ Errors: {stats['errors']}")

    return stats


async def _process_item(item: dict, auto_research: bool) -> dict:
    """Process a single gear item - research and save/update.

    Args:
        item: Item dict from LighterPack parser
        auto_research: Whether to auto-research missing items

    Returns:
        Dict with processing result
    """
    name = item["name"]
    weight_grams = item.get("weight_grams")

    print(f"\n📦 Processing: {name}")
    if weight_grams:
        print(f"   Weight from list: {weight_grams}g")

    # Try to extract brand and model from name
    brand, model = _extract_brand_model(name)
    print(f"   Parsed → Brand: {brand or 'unknown'}, Model: {model or name}")

    # Search in database using find_similar_gear
    search_query = f"{brand} {model or name}" if brand else name
    result = find_similar_gear(name=search_query, brand=brand)

    # Check if we got a match
    is_existing = result and ("Found" in result or "match" in result.lower())

    if not auto_research:
        if is_existing:
            print(f"  ✅ Found in DB (no enrichment - auto_research disabled)")
        else:
            print(f"  ⏭️  Skipped (auto-research disabled)")
        return {
            "item_name": name,
            "status": "skipped" if not is_existing else "found",
        }

    # Research the item to get detailed specs
    print(f"  🔍 Researching specs...")

    try:
        specs = await _research_item_specs(name, brand, model, weight_grams)

        if not specs:
            print(f"  ❌ Could not find specifications")
            return {
                "item_name": name,
                "status": "error",
                "error": "No specs found",
            }

        # Save or update in database
        if is_existing:
            print(f"  🔄 Updating existing item with new info...")
            result = update_existing_gear(
                name=specs.get("model", name),
                brand=specs.get("brand", brand or "Unknown"),
                weight_grams=specs.get("weight_grams") or weight_grams,
                price_usd=specs.get("price_usd"),
                category=specs.get("category"),
                materials=specs.get("materials"),
                features=specs.get("features"),
                product_url=specs.get("product_url"),
            )
            print(f"  ✅ Updated: {result[:100]}")
            return {
                "item_name": name,
                "status": "updated",
                "specs": specs,
            }
        else:
            print(f"  💾 Saving new item to database...")
            result = save_gear_to_graph(
                name=specs.get("model", name),
                brand=specs.get("brand", brand or "Unknown"),
                weight_grams=specs.get("weight_grams") or weight_grams,
                price_usd=specs.get("price_usd"),
                category=specs.get("category", "unknown"),
                materials=specs.get("materials"),
                features=specs.get("features"),
                product_url=specs.get("product_url"),
                source_url=specs.get("source_url"),
            )
            print(f"  ✅ Saved: {result[:100]}")
            return {
                "item_name": name,
                "status": "added",
                "specs": specs,
            }

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return {
            "item_name": name,
            "status": "error",
            "error": str(e),
        }


async def _research_item_specs(
    name: str,
    brand: Optional[str],
    model: Optional[str],
    weight_grams: Optional[int]
) -> Optional[dict]:
    """Research gear item specifications online.

    Args:
        name: Full item name
        brand: Extracted brand
        model: Extracted model
        weight_grams: Weight from LighterPack (if available)

    Returns:
        Dict with specs or None
    """
    try:
        # Build search query
        search_query = f"{brand} {model or name} backpacking gear specs"

        # Search for product info
        search_results = search_web(search_query, num_results=3)

        if not search_results or "No results" in search_results:
            return None

        # Use direct Anthropic API call for simple extraction
        import os
        import anthropic

        extract_prompt = f"""Extract specifications for this gear item from the search results:

Item: {name}
Brand: {brand or 'unknown'}
Model: {model or name}
Weight from pack list: {weight_grams}g (if available)

Search Results:
{search_results[:2000]}

Extract and return ONLY these fields in this exact format:
- brand: [exact brand name]
- model: [exact model/product name]
- category: [tent/backpack/sleeping_bag/sleeping_pad/etc.]
- weight_grams: [number only, or use {weight_grams} if not found]
- price_usd: [number only if found]
- materials: [comma-separated if found]
- features: [comma-separated key features]
- product_url: [manufacturer URL if found]

Be concise and accurate. Return "NOT FOUND" if this doesn't appear to be a real product."""

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": extract_prompt}]
        )

        response = message.content[0].text

        # Parse the response
        specs = _parse_specs_response(response, brand, model, weight_grams)

        return specs

    except Exception as e:
        print(f"    Research error: {e}")
        return None


def _parse_specs_response(
    response: str,
    default_brand: Optional[str],
    default_model: Optional[str],
    default_weight: Optional[int]
) -> Optional[dict]:
    """Parse agent response into structured specs.

    Args:
        response: Agent response text
        default_brand: Fallback brand
        default_model: Fallback model
        default_weight: Fallback weight

    Returns:
        Specs dict or None
    """
    if "NOT FOUND" in response:
        return None

    specs = {
        "brand": default_brand or "Unknown",
        "model": default_model or "Unknown",
        "category": "unknown",
        "weight_grams": default_weight,
    }

    # Simple parsing - look for key: value patterns
    lines = response.split("\n")
    for line in lines:
        line = line.strip()
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower().replace("-", "_").replace(" ", "_")
            value = value.strip()

            if key in specs and value and value.lower() not in ["unknown", "not found", "n/a"]:
                # Try to extract clean value
                if key in ["weight_grams", "price_usd"]:
                    import re
                    match = re.search(r"(\d+\.?\d*)", value)
                    if match:
                        specs[key] = float(match.group(1)) if "." in match.group(1) else int(match.group(1))
                else:
                    specs[key] = value

    return specs if specs.get("brand") != "Unknown" else None


def _extract_brand_model(name: str) -> tuple[Optional[str], Optional[str]]:
    """Try to extract brand and model from item name.

    Common patterns:
    - "Zpacks Nero 38L" -> brand: Zpacks, model: Nero 38L
    - "ThermaRest NeoAir XLite" -> brand: ThermaRest, model: NeoAir XLite
    - "1x Nordisk V-Peg" -> brand: Nordisk, model: V-Peg (skip quantity prefix)

    Args:
        name: Full item name

    Returns:
        Tuple of (brand, model) or (None, None)
    """
    # Remove quantity prefixes like "1x", "2x", "3x Gear Swifts" etc.
    import re
    name_cleaned = re.sub(r'^\d+x\s+', '', name)

    # List of known brands (expanded)
    known_brands = [
        "Zpacks", "Therm-a-Rest", "ThermaRest", "GramXpert", "Nordisk", "EOE", "Evernew",
        "Tarptent", "Big Agnes", "Nemo", "Sea to Summit", "MSR", "Osprey",
        "Hyperlite", "ULA", "Gossamer Gear", "Six Moon Designs", "Mountain Laurel Designs",
        "Western Mountaineering", "Enlightened Equipment", "Katabatic", "Nunatak",
        "Patagonia", "Arc'teryx", "Outdoor Research", "Black Diamond", "Petzl",
        "Ruta Locura", "Gear Swifts", "Esbit", "BRS",
    ]

    # Check if name starts with a known brand (case-insensitive)
    for brand in known_brands:
        if name_cleaned.lower().startswith(brand.lower()):
            model = name_cleaned[len(brand):].strip()
            return brand, model

    # If no known brand, try to split on first space
    parts = name_cleaned.split(maxsplit=1)
    if len(parts) == 2:
        # First word might be brand - but skip if it looks like a quantity or generic word
        potential_brand = parts[0]
        if not re.match(r'^\d', potential_brand) and potential_brand.lower() not in ['the', 'a', 'an']:
            return parts[0], parts[1]

    return None, name_cleaned


def import_lighterpack_sync(url: str, auto_research: bool = True) -> dict:
    """Synchronous wrapper for import_lighterpack.

    Args:
        url: LighterPack list URL
        auto_research: If True, automatically research missing items

    Returns:
        Import statistics
    """
    import asyncio
    return asyncio.run(import_lighterpack(url, auto_research))
