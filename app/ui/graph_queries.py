"""Preset Cypher queries for the Graph Explorer.

This module contains the categorized preset queries used in the Custom Query tab.
"""

# Organize presets into categories for the dropdown
# Keys starting with "---" are category headers and map to None
PRESET_CATEGORIES = {
    "-- Select a preset --": None,
    "--- Data Quality ---": None,
    "Gear items without brand relation": "no_brand",
    "Gear items without images": "no_images",
    "Gear items missing weight data": "no_weight",
    "Gear items missing price": "no_price",
    "Gear items missing category": "no_category",
    "Duplicate gear items (same name)": "duplicates",
    "--- Product Families ---": None,
    "Product families without gear items": "orphan_families",
    "All product families with gear items": "families_with_items",
    "Product families by brand": "families_by_brand",
    "--- Insights & Knowledge ---": None,
    "Insights without gear item relations": "orphan_insights",
    "All insights by category": "insights_by_category",
    "All insights for a product": "insights_for_product",
    "--- Glossary ---": None,
    "All glossary entries": "all_glossary",
    "Glossary entries without relations": "orphan_glossary",
    "Glossary entries with related terms": "glossary_with_relations",
    "--- Brands ---": None,
    "All brands with product counts": "brands_with_counts",
    "Brands without products": "brands_no_products",
    "Top brands by gear items": "top_brands",
    "--- Sources ---": None,
    "All sources (videos/articles)": "all_sources",
    "Sources with most gear extractions": "top_sources",
    "Recent sources": "recent_sources",
    "--- Exploration ---": None,
    "Items with images": "with_images",
    "Heaviest gear items": "heaviest_items",
    "Lightest gear items": "lightest_items",
    "Most expensive gear": "most_expensive",
    "Gear by category": "gear_by_category",
}

# The actual Cypher queries, keyed by the query_key from PRESET_CATEGORIES
PRESET_QUERIES = {
    # Data Quality
    "no_brand": """
MATCH (g:GearItem)
WHERE NOT (g)-[:PRODUCED_BY]->(:OutdoorBrand)
  AND NOT (g)<-[:MANUFACTURES_ITEM]-(:OutdoorBrand)
RETURN g.name as name, g.brand as brand_text, g.category as category
ORDER BY g.name
LIMIT 50
""",
    "no_images": """
MATCH (g:GearItem)
WHERE g.imageUrl IS NULL OR g.imageUrl = ''
RETURN g.name as name, g.brand as brand, g.category as category
ORDER BY g.name
LIMIT 50
""",
    "no_weight": """
MATCH (g:GearItem)
WHERE g.weight_grams IS NULL
RETURN g.name as name, g.brand as brand, g.category as category
ORDER BY g.name
LIMIT 50
""",
    "no_price": """
MATCH (g:GearItem)
WHERE g.price_usd IS NULL
RETURN g.name as name, g.brand as brand, g.category as category
ORDER BY g.name
LIMIT 50
""",
    "no_category": """
MATCH (g:GearItem)
WHERE g.category IS NULL OR g.category = '' OR g.category = 'unknown'
RETURN g.name as name, g.brand as brand
ORDER BY g.name
LIMIT 50
""",
    "duplicates": """
MATCH (g:GearItem)
WITH g.name as name, collect(g) as items, count(g) as cnt
WHERE cnt > 1
RETURN name, cnt as duplicate_count,
       [i IN items | i.brand][0..3] as brands
ORDER BY cnt DESC
LIMIT 30
""",
    # Product Families
    "orphan_families": """
MATCH (pf:ProductFamily)
WHERE NOT (pf)-[:HAS_VARIANT]->(:GearItem)
  AND NOT (pf)<-[:VARIANT_OF]-(:GearItem)
RETURN pf.name as family_name, pf.brand as brand, pf.description as description
ORDER BY pf.name
LIMIT 50
""",
    "families_with_items": """
MATCH (pf:ProductFamily)
OPTIONAL MATCH (pf)-[:HAS_VARIANT]->(g:GearItem)
OPTIONAL MATCH (g2:GearItem)-[:VARIANT_OF]->(pf)
WITH pf, collect(DISTINCT g) + collect(DISTINCT g2) as items
RETURN pf.name as family, pf.brand as brand, size(items) as item_count,
       [i IN items | i.name][0..5] as sample_items
ORDER BY size(items) DESC
LIMIT 50
""",
    "families_by_brand": """
MATCH (pf:ProductFamily)
OPTIONAL MATCH (pf)-[:PRODUCED_BY]->(b:OutdoorBrand)
RETURN pf.name as family, coalesce(b.name, pf.brand) as brand,
       pf.category as category
ORDER BY brand, family
LIMIT 100
""",
    # Insights
    "orphan_insights": """
MATCH (i:Insight)
WHERE NOT ()-[:HAS_TIP]->(i)
  AND NOT (i)-[:RELATES_TO]->()
RETURN i.summary as summary, i.category as category, i.content as content
ORDER BY i.category, i.summary
LIMIT 50
""",
    "insights_by_category": """
MATCH (i:Insight)
RETURN i.category as category, count(i) as count,
       collect(i.summary)[0..3] as sample_insights
ORDER BY count DESC
""",
    "insights_for_product": """
MATCH (p)-[:HAS_TIP]->(i:Insight)
RETURN p.name as product, i.summary as insight, i.category as category
ORDER BY p.name
LIMIT 50
""",
    # Glossary
    "all_glossary": """
MATCH (g:GlossaryEntry)
RETURN g.term as term, g.definition as definition, g.category as category
ORDER BY g.term
LIMIT 100
""",
    "orphan_glossary": """
MATCH (g:GlossaryEntry)
WHERE NOT (g)-[:RELATED_TO]-()
  AND NOT ()-[:USES_TERM]->(g)
RETURN g.term as term, g.definition as definition
ORDER BY g.term
LIMIT 50
""",
    "glossary_with_relations": """
MATCH (g:GlossaryEntry)-[r]-(related)
RETURN g.term as term, type(r) as relation, labels(related)[0] as related_type,
       coalesce(related.name, related.term) as related_name
ORDER BY g.term
LIMIT 100
""",
    # Brands
    "brands_with_counts": """
MATCH (b:OutdoorBrand)
OPTIONAL MATCH (b)-[:MANUFACTURES_ITEM]->(g:GearItem)
OPTIONAL MATCH (b)-[:MANUFACTURES]->(pf:ProductFamily)
RETURN b.name as brand, count(DISTINCT g) as gear_items,
       count(DISTINCT pf) as product_families
ORDER BY gear_items DESC
LIMIT 50
""",
    "brands_no_products": """
MATCH (b:OutdoorBrand)
WHERE NOT (b)-[:MANUFACTURES_ITEM]->(:GearItem)
  AND NOT (b)-[:MANUFACTURES]->(:ProductFamily)
RETURN b.name as brand, b.website as website, b.country as country
ORDER BY b.name
LIMIT 50
""",
    "top_brands": """
MATCH (b:OutdoorBrand)-[:MANUFACTURES_ITEM]->(g:GearItem)
RETURN b.name as brand, count(g) as product_count
ORDER BY product_count DESC
LIMIT 20
""",
    # Sources
    "all_sources": """
MATCH (s:Source)
RETURN s.title as title, s.url as url, s.source_type as type,
       s.processed_at as processed
ORDER BY s.processed_at DESC
LIMIT 50
""",
    "top_sources": """
MATCH (s:Source)-[:EXTRACTED_FROM]->(g:GearItem)
RETURN s.title as source, s.source_type as type, count(g) as gear_extracted
ORDER BY gear_extracted DESC
LIMIT 20
""",
    "recent_sources": """
MATCH (s:Source)
RETURN s.title as title, s.url as url, s.source_type as type,
       s.processed_at as processed
ORDER BY s.processed_at DESC
LIMIT 20
""",
    # Exploration
    "with_images": """
MATCH (g:GearItem)
WHERE g.imageUrl IS NOT NULL AND g.imageUrl <> ''
RETURN g.name as name, g.brand as brand, g.imageUrl as image
ORDER BY g.name
LIMIT 30
""",
    "heaviest_items": """
MATCH (g:GearItem)
WHERE g.weight_grams IS NOT NULL
RETURN g.name as name, g.brand as brand, g.weight_grams as weight_g,
       g.category as category
ORDER BY g.weight_grams DESC
LIMIT 30
""",
    "lightest_items": """
MATCH (g:GearItem)
WHERE g.weight_grams IS NOT NULL AND g.weight_grams > 0
RETURN g.name as name, g.brand as brand, g.weight_grams as weight_g,
       g.category as category
ORDER BY g.weight_grams ASC
LIMIT 30
""",
    "most_expensive": """
MATCH (g:GearItem)
WHERE g.price_usd IS NOT NULL
RETURN g.name as name, g.brand as brand, g.price_usd as price,
       g.category as category
ORDER BY g.price_usd DESC
LIMIT 30
""",
    "gear_by_category": """
MATCH (g:GearItem)
WHERE g.category IS NOT NULL AND g.category <> ''
RETURN g.category as category, count(g) as count,
       collect(g.name)[0..5] as sample_items
ORDER BY count DESC
""",
}
