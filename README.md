       COMPREHENSIVE GEARCREW-AGNO CODEBASE ANALYSIS

       Project Overview

       GearCrew Agno is a sophisticated Python/Streamlit application designed to extract structured
       information about hiking and backpacking gear from web sources (YouTube videos, gear review sites,
       blogs) and store it in the GearGraph database (Memgraph - a graph database). The system uses Agno as
       the AI framework with support for multiple LLM providers for cost optimization.

       ---
       1. PROJECT ARCHITECTURE & STRUCTURE

       Technology Stack

       - Framework: Streamlit (UI dashboard)
       - AI Framework: Agno (agentic AI)
       - LLM Providers:
         - DeepSeek (default, cost-effective ~$0.14/M input)
         - Anthropic Claude (higher quality, available in Haiku/Sonnet/Opus tiers)
       - Database: Memgraph (Neo4j-compatible graph database)
       - Web Scraping:
         - Playwright (primary)
         - Firecrawl (self-hosted + cloud fallback)
       - Other: Firebase (sync), LangWatch (observability), RDFlib (ontology), youtube-transcript-api

       Directory Structure

       app/
       ├── agent.py              # Main agent definition with LLM router
       ├── enrichment_agent.py   # Data enrichment agent
       ├── task_queue.py         # Background task processing
       ├── models/
       │   └── gear.py          # Pydantic models (GearItem, Manufacturer, KnowledgeFact)
       ├── db/
       │   └── memgraph.py      # Database connection & 1800+ lines of CYPHER queries
       ├── tools/
       │   ├── youtube.py       # YouTube transcript/playlist extraction
       │   ├── geargraph.py     # Graph database interface (1600+ lines)
       │   ├── web_scraper.py   # Web content extraction
       │   ├── smart_firecrawl.py # Self-hosted + cloud Firecrawl fallback
       │   ├── browser_scraper.py # Playwright-based scraping
       │   ├── product_family_detector.py # Product grouping logic
       │   ├── geargraph_sync_client.py   # Firebase sync
       │   └── firecrawl_scraper.py       # Firecrawl extraction tools
       ├── ui/
       │   ├── streamlit_app.py           # Main dashboard entry
       │   ├── graph_explorer.py          # Graph database UI (493 lines)
       │   ├── manufacturer_catalog.py    # Catalog discovery UI (602 lines)
       │   ├── website_extractor.py       # Website content extraction (301 lines)
       │   ├── playlist_manager.py        # YouTube playlist management (458 lines)
       │   ├── enrichment_view.py         # Data enrichment interface (363 lines)
       │   ├── firebase_sync_view.py      # Firebase sync UI (607 lines)
       │   ├── data_fixer.py              # Data quality tools (260 lines)
       │   ├── archive_view.py            # Video archive browser (188 lines)
       │   ├── graph_queries.py           # Pre-built CYPHER queries (275 lines)
       │   ├── fix_handlers.py            # Fix operation handlers (674 lines)
       │   └── family_fix_handler.py      # Product family management (219 lines)

       ---
       2. GRAPH DATABASE (MEMGRAPH/GEARGRAPH)

       Database Connection & Management

       File: /app/db/memgraph.py (1818 lines)

       Key Features:
       - Connection pooling with automatic reconnection on stale connections
       - Dual-mechanism error handling (connection detection + retry logic)
       - Remote host: geargraph.gearshack.app:7687

       Core Data Model (Node Types)

       GearItem
       ├── Properties: name, brand, category, weight_grams, price_usd
       ├── Optional: productUrl, imageUrl, materials[], features[]
       ├── Category-specific: volumeLiters, tempRatingF, rValue, capacityPersons
       ├── Extended: description, source_url, enrichedAt
       └── Relationships:
           ├── MANUFACTURED_BY -> OutdoorBrand
           ├── EXTRACTED_FROM -> VideoSource
           ├── HAS_TIP -> Insight
           ├── IS_VARIANT_OF -> ProductFamily
           ├── COMPARED_TO -> GearItem
           ├── HAS_ALTERNATIVE -> GearItem
           ├── HAS_OPINION -> Opinion
           └── SUITABLE_FOR -> UsageContext

       OutdoorBrand
       ├── Properties: name, country, website
       └── Relationships: MANUFACTURES_ITEM -> GearItem

       VideoSource
       ├── Properties: url, title, channel, thumbnailUrl, processedAt
       ├── Extended: gearItemsFound, insightsFound, extractionSummary
       └── Relationships: EXTRACTED_FROM <- GearItem

       Insight
       ├── Properties: summary, content, category
       └── Relationships: HAS_TIP <- GearItem

       ProductFamily
       ├── Properties: name, brand, description
       └── Relationships: IS_VARIANT_OF <- GearItem

       GlossaryTerm
       ├── Properties: name, definition, category, aliases[]
       └── Relationships: RELATES_TO <- GearItem

       Opinion, UsageContext, FieldSource, ProductComparison

       Key Memgraph Functions (1600+ lines)

       1. Core Operations: merge_gear_item(), merge_insight(), check_node_exists(), find_similar_nodes()
       2. Duplicate Detection: find_potential_duplicates(), scan_for_duplicates(), merge_gear_items()
       3. Video Source Tracking: save_video_source(), check_source_exists(), get_all_video_sources()
       4. Enrichment: get_items_needing_enrichment(), calculate_completeness_score(), mark_item_enriched()
       5. Provenance Tracking: add_field_provenance(), get_field_provenance(), set_gear_attribute()
       6. Relationships: save_gear_comparison(), save_gear_alternative(), save_gear_opinion(),
       save_usage_context()
       7. Glossary Management: merge_glossary_term(), get_glossary_term(), link_gear_to_glossary_term()

       Advanced Features

       - Fuzzy Matching: Uses RapidFuzz for typo/transcription error detection
       - Duplicate Detection Algorithm: Token-based matching with brand-aware weighting
       - Completeness Scoring: Weighted calculation based on core vs. category-specific fields
       - Dynamic Attributes: Flexible property storage for non-standard data
       - Field Provenance: Tracks source URL and confidence for every data field

       ---
       3. STREAMLIT DASHBOARD (8 Pages/Views)

       Page Structure

       Main Entry: /streamlit_app.py (361 lines)

       Page 1: Graph Explorer (493 lines)

       - Purpose: Interactive exploration of Memgraph database
       - Features:
         - Search nodes by name/brand
         - View recent items by label
         - Browse brands with product counts
         - Display insights and relationships
         - Preset CYPHER query builder
         - Data quality issue identification & fixing

       Page 2: Agent Chat (Integrated in main)

       - Purpose: Multi-turn conversation with background processing
       - Features:
         - YouTube video URL detection & preview (with thumbnail)
         - Background task execution (doesn't block UI)
         - Task progress tracking with activity logs
         - Model tier indicators (Haiku/Sonnet/Opus)
         - Task history with error reporting

       Page 3: Playlist Manager (458 lines)

       - Purpose: Batch YouTube video analysis
       - Features:
         - Playlist URL input & metadata fetch
         - Video listing with titles, durations, channels
         - Selective video processing
         - Batch extraction queue management
         - Individual video analysis in background

       Page 4: Website Extractor (301 lines)

       - Purpose: Scrape & extract gear info from specific URLs
       - Features:
         - URL input with validation
         - Content scraping (Playwright + Firecrawl)
         - Markdown/HTML conversion
         - Manual product extraction
         - Source tracking

       Page 5: Manufacturer Catalog (602 lines)

       - Purpose: Discover & bulk-extract entire product catalogs
       - Two-Phase Process:
         a. Discovery Phase:
             - Website mapping (up to 50 pages)
           - Category detection (filters non-product pages)
           - Product count per category
         b. Selection Phase:
             - Expandable category listings
           - Checkbox selection (products/categories/all)
           - Bulk extraction queue
           - Progress tracking

       Page 6: Data Enrichment (363 lines)

       - Purpose: Identify & enhance incomplete gear items
       - Features:
         - Completeness scoring algorithm
         - Priority-based sorting (tents, backpacks, etc.)
         - Category filtering
         - Missing field highlighting
         - Batch enrichment tools
         - Enrichment statistics

       Page 7: Video Archive (188 lines)

       - Purpose: Browse processed videos & extracted data
       - Features:
         - Video source listing (recent first)
         - Thumbnail display
         - Extraction summary viewing
         - Extracted gear item listing per video
         - Processing metadata

       Page 8: Firebase Sync (607 lines)

       - Purpose: Synchronize with Firebase/gearBase
       - Features:
         - Sync direction selection (upload/download/bidirectional)
         - Item selection & filtering
         - Conflict resolution UI
         - Sync history tracking
         - Change log viewing
         - Token management

       Task Queue System

       File: /app/task_queue.py (241 lines)

       - Architecture: Threaded background worker with Streamlit session state integration
       - Components:
         - TaskQueue: Thread-safe queue management
         - Task: Dataclass with progress tracking
         - TaskStatus: PENDING/RUNNING/COMPLETED/FAILED states
         - Streaming events for progress display

       ---
       4. AI AGENT SYSTEM

       Main Agent Definition

       File: /app/agent.py (1000+ lines)

       Dual LLM Provider Support:
       1. DeepSeek (Default): Cost-effective (~$0.14/M input tokens)
       2. Anthropic Claude: Higher quality with 3 tiers:
         - Haiku 4.5 (fast, cheap)
         - Sonnet 4.5 (balanced)
         - Opus 4.5 (advanced with extended thinking)

       Task Complexity Classifier:
       - Automatically selects model tier based on prompt analysis
       - Pattern matching for: verification tasks (→ Opus), simple lookups (→ Haiku)
       - Reduces costs by using cheaper models for simple tasks

       Available Tools (30+ functions):
       - YouTube: get_youtube_transcript(), get_playlist_videos()
       - Web: scrape_webpage(), search_web(), map_website()
       - Graph: find_similar_gear(), save_gear_to_graph(), check_video_already_processed()
       - Data Quality: audit_duplicates(), merge_duplicate_gear()
       - Glossary: save_glossary_term(), link_gear_to_term()
       - Enrichment: Track sources, opinions, comparisons, alternatives

       Enrichment Agent

       File: /app/enrichment_agent.py (345 lines)
       - Specialized agent for data completion
       - Multi-source lookup strategy
       - Validation workflow
       - Batch processing support

       ---
       5. WEB SCRAPING & CONTENT EXTRACTION

       Smart Firecrawl Client

       File: /app/tools/smart_firecrawl.py (350+ lines)

       Architecture:
       - Primary: Self-hosted Firecrawl (free, on-premises)
       - Fallback: Cloud Firecrawl API (paid, on-demand)
       - Auto-fallback: Transparent failure recovery

       Capabilities:
       - scrape(): Extract page content (markdown/HTML)
       - search(): Local search (self-hosted) or web search (cloud)
       - map(): Sitemap generation & link discovery
       - extract(): Structured data extraction (cloud only)

       Usage Statistics Tracking:
       - Counts self-hosted vs. cloud calls
       - Estimates cost ($0.005/credit)
       - Calculates self-hosted percentage for cost analysis

       Browser Scraper (Playwright)

       File: /app/tools/browser_scraper.py

       Features:
       - JavaScript rendering (unlike traditional scrapers)
       - Product URL detection
       - Website mapping & categorization
       - Product extraction with structured parsing
       - Headless browser automation

       YouTube Tools

       File: /app/tools/youtube.py (180 lines)

       Functions:
       - extract_video_id(): Parse various YouTube URL formats
       - get_youtube_transcript(): Fetch auto-generated or manual transcripts
       - extract_playlist_id(): Extract from playlist URLs
       - get_playlist_videos(): Batch fetch video metadata
       - get_playlist_info(): Get playlist title, channel, video count

       Product Family Detector

       File: /app/tools/product_family_detector.py

       Pattern Recognition:
       - Version numbers: "Lone Peak 8" → family: "Lone Peak", variant: "8"
       - Size numbers: "Exos 55" → family: "Exos", variant: "55"
       - Weight specs: "Nano Air 20g" → family: "Nano Air", variant: "20g"
       - Temperature: "Ultralight Bed 25°F" → family: "Ultralight Bed", variant: "25°F"
       - Fill power: "Muscovy Down 900 Fill"
       - Model suffixes: "X Ultra 4 GTX"

       Confidence Scoring: 0-1 confidence that products form a real family

       ---
       6. DATA MODELS

       File: /app/models/gear.py

       Enums

       GearCategory: backpack, tent, sleeping_bag, sleeping_pad, clothing,
                    footwear, cookware, water_filtration, navigation,
                    lighting, trekking_poles, accessories, first_aid, other

       FactType: review, tip, warning, comparison, specification, experience

       Core Models

       1. GearItem: Product information
         - Basic: name, brand, category, weight_grams, price_usd
         - Details: materials[], features[], use_cases[]
         - Metadata: model, source_url
       2. Manufacturer: Brand information
         - name, country, website
       3. KnowledgeFact: Extractable knowledge
         - content, source_url, fact_type, confidence (0-1)
         - Optional: linked gear_item_name
       4. ExtractionResult: Complete extraction output
         - source_url, source_type (youtube, blog, etc.)
         - gear_items[], manufacturers[], knowledge_facts[]
         - raw_content (for reference)

       ---
       7. GRAPH INTERACTION LAYER

       File: /app/tools/geargraph.py (1677 lines)

       Tool Categories

       Duplicate Detection:
       - find_similar_gear(): Fuzzy matching with 60%+ similarity threshold
       - check_gear_exists(): Exact matching
       - audit_duplicates(): Full database scan for duplicate groups

       Data Persistence:
       - save_gear_to_graph(): Create/update GearItem with any category-specific fields
       - update_existing_gear(): Selective field updates
       - save_insight_to_graph(): Knowledge fact storage
       - save_extraction_result(): Track processed sources

       Linking:
       - link_extracted_gear_to_source(): GearItem → VideoSource relationship
       - link_gear_to_term(): GearItem → GlossaryTerm relationship

       Advanced:
       - save_product_comparison(): Track competitive comparisons
       - save_product_opinion(): Store pro/con/tip/warning/experience
       - save_recommended_usage(): Use case contexts (terrain, weather, activity, skill_level, trip_type)
       - save_dynamic_attribute(): Custom field storage
       - track_field_source(): Provenance tracking with confidence scores

       Glossary Management:
       - save_glossary_term(): Create material/technology/technique terms
       - lookup_glossary_term(): Find by name or alias
       - import_glossary_from_json(): Bulk import from JSON array
       - find_gear_with_term(): Reverse lookup

       ---
       8. CONFIGURATION & SETUP

       Environment Variables (.env.example)

       # LLM Configuration
       LLM_PROVIDER=deepseek  # or "anthropic"
       ANTHROPIC_API_KEY=...
       DEEPSEEK_API_KEY=...

       # Database
       MEMGRAPH_HOST=geargraph.gearshack.app
       MEMGRAPH_PORT=7687
       MEMGRAPH_USER=memgraph
       MEMGRAPH_PASSWORD=...

       # Web Services
       SERPER_API_KEY=...  # Web search

       # Firecrawl Configuration
       FIRECRAWL_SELF_HOSTED_URL=https://geargraph.gearshack.app/firecrawl
       FIRECRAWL_SELF_HOSTED_KEY=local-dev-key
       FIRECRAWL_API_KEY=...  # Cloud fallback
       FIRECRAWL_TIMEOUT=30
       FIRECRAWL_MAX_RETRIES=2
       FIRECRAWL_ENABLE_FALLBACK=true

       # Observability
       LANGWATCH_API_KEY=...

       # Firebase Sync
       FIREBASE_SERVICE_ACCOUNT=firebase-service-account.json
       GEARGRAPH_API_KEY=...
       GEARGRAPH_SYNC_API_URL=https://geargraph.gearshack.app/api/sync/changes

       Dependencies

       - agno: AI framework
       - anthropic/deepseek: LLM clients
       - streamlit: Web UI
       - gqlalchemy: Memgraph ORM
       - firecrawl-py: Web scraping
       - playwright: Browser automation
       - youtube-transcript-api: Video transcripts
       - yt-dlp: YouTube metadata
       - firebase-admin: Firebase sync
       - langwatch: Observability
       - rdflib: Ontology parsing
       - rapidfuzz: Fuzzy matching
       - pydantic: Data validation

       ---
       9. KEY FEATURES & CAPABILITIES

       Data Extraction Capabilities

       1. YouTube Videos:
         - Transcript extraction (auto-generated or manual)
         - Playlist batch processing
         - Metadata capture (title, channel, duration)
       2. Web Content:
         - Intelligent HTML/Markdown parsing
         - Structured product data extraction
         - Website cataloging & category detection
       3. Structured Information:
         - Gear specifications (weight, price, materials, features)
         - Usage recommendations & contexts
         - Pros/cons and expert opinions
         - Product comparisons & alternatives

       Data Quality Features

       1. Duplicate Prevention:
         - Fuzzy name matching (typos, transcription errors)
         - Same-brand product matching
         - Substring matching for variants
         - Confidence scores for each match
       2. Completeness Tracking:
         - Scoring algorithm (0.0-1.0)
         - Category-specific field weighting
         - Enrichment prioritization
         - Batch completion tools
       3. Provenance Tracking:
         - Source URL for every data field
         - Confidence scoring per field
         - Multiple source support
         - Change history

       Advanced Graph Operations

       - Product Family Detection: Automatic grouping of variants
       - Relationship Mapping: Manufacturers → Products, Products → Insights
       - Semantic Queries: Find gear by material, technique, or usage context
       - Batch Operations: Bulk import, categorization, merging

       Automated Playlist Monitoring

       - Scheduled Monitoring: Checks playlists every 6 hours via GitHub Actions
       - Automatic Processing: New videos are automatically extracted and stored
       - Email Notifications: Detailed reports for each processed video
       - Progress Tracking: Maintains state to avoid reprocessing videos
       - Manual Control: Can be triggered on-demand or run locally
       - See: docs/PLAYLIST_MONITORING.md for setup instructions

       ---
       10. WORKFLOW EXAMPLES

       YouTube Video Extraction

       1. User provides YouTube URL
       2. Task Queue submits to background worker
       3. Agent:
          - Extracts transcript (youtube.py)
          - Processes with LLM (Haiku/Sonnet/Opus based on complexity)
          - Uses find_similar_gear() to check for duplicates
          - Calls save_gear_to_graph() for each item
          - Records extraction with save_extraction_result()
          - Links gear to source with link_extracted_gear_to_source()
       4. Streamlit displays progress in real-time
       5. User can switch views while processing continues

       Manufacturer Catalog Extraction

       1. Phase 1 (Discovery):
          - Browser scraper maps website (Playwright)
          - Extracts all product URLs
          - Groups by category
          - Filters out non-product pages

       2. Phase 2 (Selection):
          - User selects products/categories
          - Optional: Product-by-product verification with Firecrawl

       3. Extraction:
          - For each URL, extract product data
          - Detect product families
          - Save to graph with provenance

       Data Enrichment

       1. Query incomplete items:
          - Filter by completeness score threshold
          - Prioritize by category importance

       2. For each item:
          - Search web for specifications
          - Lookup manufacturer page
          - Extract missing fields
          - Track sources with confidence
          - Mark enrichedAt timestamp

       ---
       11. CYPHER QUERY EXAMPLES

       The system includes hundreds of pre-built CYPHER queries:

       Basic Lookups

       MATCH (g:GearItem {name: $name, brand: $brand})
       RETURN g, labels(g), id(g)

       MATCH (b:OutdoorBrand {name: $name})
       RETURN count(b)-[:MANUFACTURES_ITEM]->(g:GearItem)

       Duplicate Detection

       MATCH (g1:GearItem), (g2:GearItem)
       WHERE id(g1) < id(g2)
         AND toLower(g1.brand) = toLower(g2.brand)
         AND (toLower(g1.name) CONTAINS toLower(g2.name)
              OR toLower(g2.name) CONTAINS toLower(g1.name))
       RETURN g1, g2

       Enrichment Queries

       MATCH (g:GearItem)
       WITH g,
         CASE WHEN g.weight_grams IS NOT NULL THEN 1 ELSE 0 END as has_weight,
         CASE WHEN g.description IS NOT NULL THEN 1 ELSE 0 END as has_desc
       RETURN count(g), sum(has_weight), sum(has_desc)

       ---
       12. OBSERVABILITY & MONITORING

       LangWatch Integration

       - Prompt versioning & management
       - Agent execution tracing
       - Performance monitoring
       - Cost analysis

       Task Queue Monitoring

       - Real-time progress display
       - Activity logs per task
       - Tool usage tracking
       - Duration measurement
       - Error capture & reporting

       Database Monitoring

       - Graph statistics (node counts, relationship counts)
       - Data completeness metrics
       - Duplicate scan results
       - Enrichment statistics

       ---
       13. SECURITY & BEST PRACTICES

       - Connection Resilience: Auto-reconnect on stale connections
       - API Key Management: All sensitive data via environment variables
       - Fallback Systems: Firecrawl self-hosted → cloud auto-fallback
       - Duplicate Prevention: Pre-check before saving to prevent conflicts
       - Transaction Safety: MERGE operations for idempotency
       - Field Validation: Numeric field parsing with "N/A"/"unknown" handling
       - Rate Limiting: Timeout and retry configuration for Firecrawl

       ---
       14. DEPLOYMENT NOTES

       - Dashboard: streamlit run streamlit_app.py
       - Database: Remote Memgraph instance (requires VPN/network access)
       - Worker Threads: Background processing in separate threads
       - Session State: Streamlit session state management for state persistence
       - Dev Server: agno dev app/main.py for interactive development

       ---
       SUMMARY

       GearCrew Agno is a comprehensive, production-ready system for extracting and managing outdoor gear
       knowledge. It combines:
       - Intelligent Extraction: Multi-source AI-powered data extraction
       - Quality Assurance: Advanced duplicate detection and completeness scoring
       - Graph Intelligence: Rich semantic relationships in Memgraph
       - Cost Optimization: Dual LLM provider with task complexity routing
       - User Interface: 8-page Streamlit dashboard for complete workflow support
       - Background Processing: Threaded task queue for non-blocking operations
       - Data Integrity: Provenance tracking and source validation throughout

       The system is designed to scale to thousands of products while maintaining data quality and preventing
       duplicates through intelligent matching and verification workflows.
