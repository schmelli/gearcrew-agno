"""LighterPack gear list parser and importer."""

import re
from typing import Optional
from playwright.async_api import Page

from app.tools.browser_scraper import BrowserScraper


async def parse_lighterpack_url(url: str) -> dict:
    """Parse a LighterPack gear list URL.

    Args:
        url: LighterPack list URL (e.g., https://lighterpack.com/r/abc123)

    Returns:
        Dict with pack_name, base_weight, total_weight, items list

    Raises:
        ValueError: If URL is invalid or parsing fails
    """
    if "lighterpack.com" not in url:
        raise ValueError(f"Not a valid LighterPack URL: {url}")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        await page.goto(url)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(3000)  # Wait for JS to render

        # Extract pack metadata
        pack_name = await page.title()

        # Extract all gear items using working selector
        item_elements = await page.query_selector_all(".lpItem")
        items = []

        for item_elem in item_elements:
            try:
                item_data = await _extract_item(item_elem, page)
                if item_data:
                    items.append(item_data)
            except Exception as e:
                print(f"Error extracting item: {e}")
                continue

        # Get totals
        base_weight = await _extract_total_weight(page, "lpTotalValue")

        await browser.close()

        return {
            "pack_name": pack_name,
            "source_url": url,
            "base_weight_grams": base_weight,
            "items": items,
            "total_items": len(items),
        }


async def _extract_item(item_elem, page) -> Optional[dict]:
    """Extract data from a single item element.

    Args:
        item_elem: Playwright element handle
        page: Page context

    Returns:
        Dict with item data or None
    """
    try:
        # Get item name - try multiple selectors
        desc_elem = await item_elem.query_selector(".lpDescription")
        if not desc_elem:
            desc_elem = await item_elem.query_selector("input[type='text']")

        if not desc_elem:
            return None

        name = await desc_elem.get_attribute("value")
        if not name:
            name = await desc_elem.inner_text()

        if not name or name.strip() == "":
            return None

        # Get weight and price from number inputs
        weight_inputs = await item_elem.query_selector_all("input.lpNumber")
        weight_str = ""
        price_str = ""

        if weight_inputs:
            weight_str = await weight_inputs[0].get_attribute("value") or ""
        if len(weight_inputs) > 1:
            price_str = await weight_inputs[1].get_attribute("value") or ""

        # Parse weight to grams
        weight_grams = _parse_weight(weight_str)

        # Check if worn/consumable
        is_worn = await item_elem.query_selector(".lpWorn.lpActive")
        is_consumable = await item_elem.query_selector(".lpConsumable.lpActive")

        return {
            "name": name.strip(),
            "weight_grams": weight_grams,
            "quantity": 1,  # Default
            "price": price_str.strip() if price_str else None,
            "is_worn": bool(is_worn),
            "is_consumable": bool(is_consumable),
        }

    except Exception as e:
        print(f"Error in _extract_item: {e}")
        return None


def _parse_weight(weight_str: str) -> Optional[int]:
    """Parse weight string to grams.

    Handles formats like:
    - "123" (grams)
    - "123g"
    - "1.5kg"
    - "2lb"
    - "8oz"

    Args:
        weight_str: Weight string

    Returns:
        Weight in grams or None
    """
    if not weight_str:
        return None

    weight_str = weight_str.strip().lower()

    # Remove commas
    weight_str = weight_str.replace(",", "")

    # Extract number
    match = re.search(r"([\d.]+)", weight_str)
    if not match:
        return None

    try:
        value = float(match.group(1))
    except ValueError:
        return None

    # Determine unit
    if "kg" in weight_str:
        return int(value * 1000)
    elif "lb" in weight_str:
        return int(value * 453.592)
    elif "oz" in weight_str:
        return int(value * 28.3495)
    else:
        # Assume grams
        return int(value)


async def _extract_total_weight(page: Page, class_name: str) -> Optional[int]:
    """Extract total weight from pack.

    Args:
        page: Playwright page
        class_name: CSS class to search for

    Returns:
        Total weight in grams
    """
    try:
        total_elem = await page.query_selector(f".{class_name}")
        if not total_elem:
            return None

        total_str = await total_elem.inner_text()
        return _parse_weight(total_str)
    except:
        return None
