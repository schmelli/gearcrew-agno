"""LighterPack gear list importer with research and ingestion."""

from typing import Optional
import re

from app.tools.lighterpack import parse_lighterpack_url
from app.tools.geargraph import (
    find_similar_gear,
    save_gear_to_graph,
)


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
        "researched": 0,
        "added": 0,
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
        elif result["status"] == "researched":
            stats["researched"] += 1
            stats["added"] += 1
        elif result["status"] == "skipped":
            stats["skipped"] += 1
        elif result["status"] == "error":
            stats["errors"] += 1

    print(f"\n📊 Import Summary:")
    print(f"  ✅ Found in database: {stats['found_in_db']}")
    print(f"  🔍 Researched & added: {stats['researched']}")
    print(f"  ⏭️  Skipped: {stats['skipped']}")
    print(f"  ❌ Errors: {stats['errors']}")

    return stats


async def _process_item(item: dict, auto_research: bool) -> dict:
    """Process a single gear item.

    Args:
        item: Item dict from LighterPack parser
        auto_research: Whether to auto-research missing items

    Returns:
        Dict with processing result
    """
    name = item["name"]
    print(f"\n📦 Processing: {name}")

    # Try to extract brand and model from name
    brand, model = _extract_brand_model(name)

    # Search in database using find_similar_gear
    search_query = f"{brand} {model or name}" if brand else name
    result = find_similar_gear(name=search_query, brand=brand)

    # Check if we got a match (find_similar_gear returns a formatted string)
    if result and ("Found" in result or "match" in result.lower()):
        print(f"  ✅ Found in DB")
        return {
            "item_name": name,
            "status": "found",
            "db_match": result[:200],
        }

    # Not found - research if enabled
    if not auto_research:
        print(f"  ⏭️  Skipped (auto-research disabled)")
        return {
            "item_name": name,
            "status": "skipped",
        }

    print(f"  🔍 Not found in DB - researching...")

    try:
        # Lazy import to avoid circular dependency
        from app.agent import run_agent_chat

        # Use agent to research the item
        research_prompt = f"""
Research this backpacking gear item and add it to GearGraph:

Item: {name}
Weight: {item.get('weight_grams')}g
Category: {item.get('category', 'unknown')}

Please search for this item online, find its specifications, and add it to the database
using the save_gear_to_graph tool. Include as much detail as possible:
brand, model, weight, price, materials, features, category, etc.
"""

        response = run_agent_chat(research_prompt)

        # Check if item was added
        if "added" in response.lower() or "success" in response.lower():
            print(f"  ✅ Researched and added")
            return {
                "item_name": name,
                "status": "researched",
                "agent_response": response[:200],
            }
        else:
            print(f"  ⚠️  Research completed but unclear if added")
            return {
                "item_name": name,
                "status": "researched",
                "agent_response": response[:200],
            }

    except Exception as e:
        print(f"  ❌ Error researching: {e}")
        return {
            "item_name": name,
            "status": "error",
            "error": str(e),
        }


def _extract_brand_model(name: str) -> tuple[Optional[str], Optional[str]]:
    """Try to extract brand and model from item name.

    Common patterns:
    - "Zpacks Nero 38L" -> brand: Zpacks, model: Nero 38L
    - "ThermaRest NeoAir XLite" -> brand: ThermaRest, model: NeoAir XLite
    - "GramXpert 200 Apex" -> brand: GramXpert, model: 200 Apex

    Args:
        name: Full item name

    Returns:
        Tuple of (brand, model) or (None, None)
    """
    # List of known brands (can be expanded)
    known_brands = [
        "Zpacks", "ThermaRest", "GramXpert", "Nordisk", "EOE", "Evernew",
        "Tarptent", "Big Agnes", "Nemo", "Sea to Summit", "MSR", "Osprey",
        "Hyperlite", "ULA", "Gossamer Gear", "Six Moon Designs", "Mountain Laurel Designs",
        "Western Mountaineering", "Enlightened Equipment", "Katabatic", "Nunatak",
        "Patagonia", "Arc'teryx", "Outdoor Research", "Black Diamond", "Petzl",
    ]

    # Check if name starts with a known brand
    for brand in known_brands:
        if name.lower().startswith(brand.lower()):
            model = name[len(brand):].strip()
            return brand, model

    # If no known brand, try to split on first space
    parts = name.split(maxsplit=1)
    if len(parts) == 2:
        # First word might be brand
        return parts[0], parts[1]

    return None, name


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
