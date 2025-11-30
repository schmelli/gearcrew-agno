Product Requirements Document (PRD): Outdoor Gear Insight Engine (OGIE)
Target Framework: Agno (formerly Phidata) Target Database: Memgraph (Graph DB) Language: Python

1. Executive Summary
The goal is to build an autonomous agentic system using Agno that ingests unstructured content (YouTube videos, blog posts, reviews) regarding outdoor/trekking equipment. The system must extract factual specifications (weight, material, etc.) and subjective experiences/sentiments. Crucially, extracted facts must be verified against trusted web sources via an autonomous research step. Validated data is presented in a Streamlit Dashboard for human review before being committed to a Memgraph database based on a strict pre-defined ontology.

2. Technical Stack & Architecture
2.1 Core Components

Orchestration Framework: Agno (Focus on Agent, Tools, and Pydantic structured outputs).

LLM: GPT-4o (OpenAI) or Gemini 1.5 Pro (Google) – Must support long-context and vision for video analysis.

Database: Memgraph (Cypher Query Language).

Frontend/Dashboard: Streamlit.

Data Validation: Pydantic.

Search/Verification: Exa.ai or Google Search (via Agno Tools).

Video Processing: YouTube Transcript API + LLM Vision capabilities (optional for visual-only specs).

2.2 Data Flow Architecture

Ingestion: User inputs a URL (YouTube/Web).

Extraction Agent (Agno): Analyzes content, extracts entities based on Pydantic Schema.

Verification Agent (Agno): Takes extracted "Facts", searches the web to verify them. Flags discrepancies.

Staging: Data is saved to a temporary JSON/State object.

Human-in-the-Loop (Streamlit): User reviews the extraction and verification status.

Commit: Confirmed data is transformed into Cypher queries and written to Memgraph.

3. Data Ontology & Modeling
The system must map unstructured data to the following conceptual graph structure (simplified):

Nodes:

Gear (Labels: Backpack, Tent, Jacket, etc.)

Brand

Material

Feature

Source (The YouTube video or Blog URL)

Edges:

(:Gear)-[:MANUFACTURED_BY]->(:Brand)

(:Gear)-[:HAS_SPEC]->(Property) (e.g., Weight, Volume)

(:Gear)-[:HAS_EXPERIENCE {sentiment: float, context: string}]->(:Experience)

(:Source)-[:MENTIONS]->(:Gear)

4. Agent Definitions (Agno Implementation)
The system requires a team of specialized agents.

4.1 Agent A: The "Extractor"

Role: Multimedia analyst.

Input: URL (YouTube or Text).

Capabilities:

Fetch YouTube transcript.

(Optional) Analyze video frames if transcript is ambiguous.

Output: A strict Pydantic Object RawExtraction containing:

gear_name

specs (List of key-value pairs).

experiences (List of quotes/summaries with sentiment).

Instructions: "You are an expert outdoor gear analyst. Extract technical specs and subjective user experiences separately. Do not hallucinate specs not mentioned in the source."

4.2 Agent B: The "Verifier"

Role: Fact-Checker.

Input: The RawExtraction object from Agent A.

Tools: Web Search (Google/Exa).

Logic:

Iterate through extracted specs.

Perform a search query (e.g., "Hilleberg Soulo weight official site").

Compare extracted_value vs found_value.

Output: VerifiedExtraction object. Each spec gets a status: VERIFIED, CONFLICT, or UNVERIFIED and a verification_source_url.

4.3 Agent C: The "Graph Mapper"

Role: Database Architect.

Input: The final approved data.

Task: Generate Cypher queries to insert/merge nodes and edges into Memgraph, ensuring no duplicates are created (use MERGE statements).

5. Functional Requirements
5.1 Transcription & Ingestion

The system must handle YouTube URLs natively.

If technical details are missing in audio but present in video text overlays, the system should attempt to retrieve them (Multimodal analysis).

5.2 Verification Logic

Strict Mode: If the extracted weight is 1.2kg, but the manufacturer site says 1.5kg, the system must flag this as a CONFLICT in the return object.

Source Provenance: Every verified fact must link to the URL where it was verified.

5.3 Experience Extraction

Subjective sentences ("The zipper feels flimsy in winter") must be separated from Facts.

These should be stored with a link to the Gear item, potentially with a 'Scenario' tag (e.g., "Winter", "Rain").

5.4 Dashboard (Streamlit)

Left Column: Source Video/Text summary.

Middle Column: Extracted Specs with color codes (Green = Verified, Red = Conflict).

Right Column: "Commit to DB" button.

Editable Fields: The user must be able to manually correct a value before committing.

6. Implementation Steps for Developer
Setup Environment: Initialize Agno, set up Memgraph Docker container.

Define Pydantic Schemas: Create robust Python classes for GearSpec, Experience, and VerificationResult.

Build Extraction Agent: Implement Agno agent with YoutubeTools.

Build Verification Agent: Implement Agno agent with SearchTools.

Build Streamlit UI: Create the interface to visualize the Pydantic objects.

Memgraph Connector: Implement the logic to take the Pydantic object and run Cypher queries.

7. Example Scenarios
Scenario 1: Conflict

Video says: "This backpack weighs 900g."

Verification Agent finds: Manufacturer site lists "1100g".

Dashboard shows: Weight: 900g (Detected) | 1100g (Official). Status: ⚠️ CONFLICT.

User Action: User accepts "1100g" and clicks Commit.

Scenario 2: Experience

Video says: "I froze in this sleeping bag at -5 degrees."

Extraction: Experience: "Cold at -5C" | Sentiment: Negative | Tag: "Temperature Rating".

Graph Write: (SleepingBag)-[:HAS_EXPERIENCE {rating: 'negative', context: '-5C'}]->(ExperienceNode)
