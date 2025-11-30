# Agent Development Guidelines

## Project Overview

**Goal:** Extract structured information about hiking and backpacking gear from web sources (YouTube videos, gear review sites, blog posts) and store it in the GearGraph database.

**Project Name:** GearCrew Agno - Gear Knowledge Extraction Agent

### What the Agent Does

The GearCrew agent performs the following tasks:

1. **Content Extraction**: Fetches content from various sources:
   - YouTube video transcripts (using youtube-transcript-api)
   - Gear review websites and blogs (using Firecrawl)
   - Manufacturer product pages

2. **Information Extraction**: Parses content to extract:
   - Gear item details (name, brand, model, category, weight, price)
   - Manufacturer information
   - Usage recommendations and experience-based knowledge
   - Pros/cons and performance characteristics

3. **Validation**: Cross-references extracted data using Firecrawl search to validate:
   - Product specifications
   - Manufacturer claims
   - User experiences

4. **Storage**: Saves validated data to the GearGraph database following a predefined ontology

### Data Ontology

The agent extracts data conforming to this structure:

```
GearItem:
  - name: str
  - brand: str
  - model: str
  - category: str (backpack, tent, sleeping_bag, clothing, cookware, etc.)
  - weight_grams: int
  - price_usd: float
  - materials: list[str]
  - features: list[str]
  - use_cases: list[str]

Manufacturer:
  - name: str
  - country: str
  - website: str

KnowledgeFact:
  - content: str
  - source_url: str
  - gear_item: GearItem (optional)
  - fact_type: str (review, tip, warning, comparison)
```

**Framework:** Agno
**Language:** Python

This project follows LangWatch best practices for building production-ready AI agents.

---

## Core Principles

### 1. Scenario Agent Testing

Scenario allows for end-to-end validation of multi-turn conversations and real-world scenarios, most agent functionality should be tested with scenarios

**CRITICAL**: Every new agent feature MUST be tested with Scenario tests before considering it complete.

- Write simulation tests for multi-turn conversations
- Validate edge cases
- Ensure business value is delivered
- Test different conversation paths

Best practices:
- NEVER check for regex or word matches in the agent's response, use judge criteria instead
- Use functions on the Scenario scripts for things that can be checked deterministically (tool calls, database entries, etc) instead of relying on the judge
- For the rest, use the judge criteria to check if agent is reaching the desired goal and
- When broken, run on single scenario at a time to debug and iterate faster, not the whole suite
- Write as few scenarios as possible, try to cover more ground with few scenarios, as they are heavy to run
- If user made 1 request, just 1 scenario might be enough, run it at the end of the implementation to check if it works
- ALWAYS consult the Scenario docs on how to write scenarios, do not assume the syntax

### 2. Prompt Management

**ALWAYS** use LangWatch Prompt CLI for managing prompts:

- Use the LangWatch MCP to learn about prompt management, search for Prompt CLI docs
- Never hardcode prompts in your application code
- Store all prompts in the `prompts/` directory as YAML files, use "langwatch prompt create <name>" to create a new prompt
- Run `langwatch prompt sync` after changing a prompt to update the registry

Example prompt structure:
```yaml
# prompts/my_prompt.yaml
model: gpt-4o
temperature: 0.7
messages:
  - role: system
    content: |
      Your system prompt here
  - role: user
    content: |
      {{ user_input }}
```

DO NOT use hardcoded prompts in your application code, example:

BAD:
```
Agent(prompt="You are a helpful assistant.")
```

GOOD:
```python
import langwatch

prompt = langwatch.prompts.get("my_prompt")
Agent(prompt=prompt.prompt)
```

```typescript
import { LangWatch } from "langwatch";

const langwatch = new LangWatch({
  apiKey: process.env.LANGWATCH_API_KEY
});

const prompt = await langwatch.prompts.get("my_prompt")
Agent(prompt=prompt!.prompt)
```

Prompt fetching is very reliable when using the prompts cli because the files are local (double check they were created with the CLI and are listed on the prompts.json file).
DO NOT add try/catch around it and DO NOT duplicate the prompt here as a fallback

Explore the prompt management get started and data model docs if you need more advanced usages such as compiled prompts with variables or messages list.

### 3. Evaluations for specific cases

Only write evaluations for specific cases:

- When a RAG is implemented, so we can evaluate the accuracy given many sample queries (using an LLM to compare expected with generated outputs)
- For classification tasks, e.g. categorization, routing, simple true/false detection, etc
- When the user asks and you are sure an agent scenario wouldn't test the behaviour better

This is because evaluations are good for things when you have a lot of examples, with avery clear
definition of what is correct and what is not (that is, you can just compare expected with generated)
and you are looking for single input/output pairs. This is not the case for multi-turn agent flows.

Create evaluations in Jupyter notebooks under `tests/evaluations/`:

- Generate csv example datasets yourself to be read by pandas with plenty of examples
- Use LangWatch Evaluations API to create evaluation notebooks and track the evaluation results
- Use either a simple == comparison or a direct (e.g. openai) LLM call to compare expected with generated if possible and not requested otherwise

### 4. General good practices

- ALWAYS use the package manager cli commands to init, add and install new dependencies, DO NOT guess package versions, DO NOT add them to the dependencies file by hand.
- When setting up, remember to load dotenv for the tests so env vars are available
- Double check the guidelines on AGENTS.md after the end of the implementation.

---

## Framework-Specific Guidelines

### Agno Framework

**Always follow Agno best practices:**

- Refer to the `.cursorrules` file for Agno-specific coding standards
- Consult `llms.txt` for comprehensive Agno documentation
- Use Agno's agent building patterns and conventions
- Follow Agno's recommended project structure

**Key Agno Resources:**
- Documentation: https://docs.agno.com/
- GitHub: https://github.com/agno-agi/agno
- Local files: `.cursorrules` and `llms.txt`

**When implementing agent features:**
1. Review Agno documentation for best practices
2. Use Agno's built-in tools and utilities
3. Follow Agno's patterns for agent state management
4. Leverage Agno's testing utilities

---

## Project Structure

This project follows a standardized structure for production-ready agents:

```
|__ app/           # Main application code
|__ prompts/          # Versioned prompt files (YAML)
|_____ *.yaml
|__ tests/
|_____ evaluations/   # Jupyter notebooks for component evaluation
|________ *.ipynb
|_____ scenarios/     # End-to-end scenario tests
|________ *.test.py
|__ prompts.json      # Prompt registry
|__ .env              # Environment variables (never commit!)
```

---

## Development Workflow

### When Starting a New Feature:

1. **Understand Requirements**: Clarify what the agent should do
2. **Design the Approach**: Plan which components you'll need
3. **Implement with Prompts**: Use LangWatch Prompt CLI to create/manage prompts
4. **Write Unit Tests**: Test deterministic components
5. **Create Evaluations**: Build evaluation notebooks for probabilistic components
6. **Write Scenario Tests**: Create end-to-end tests using Scenario
7. **Run Tests**: Verify everything works before moving on

### Always:

- ✅ Version control your prompts
- ✅ Write tests for new features
- ✅ Use LangWatch MCP to learn best practices
- ✅ Follow the Agent Testing Pyramid
- ✅ Document your agent's capabilities

### Never:

- ❌ Hardcode prompts in application code
- ❌ Skip testing new features
- ❌ Commit API keys or sensitive data
- ❌ Optimize without measuring (use evaluations first)

---

## Using LangWatch MCP

The LangWatch MCP server provides expert guidance on:

- Prompt management with Prompt CLI
- Writing Scenario tests
- Creating evaluations
- Best practices for agent development

**How to use it:**
Simply ask your coding assistant questions like:
- "How do I use the LangWatch Prompt CLI?"
- "Show me how to write a Scenario test"
- "How do I create an evaluation for my RAG system?"

The MCP will provide up-to-date documentation and examples.

---

## Getting Started

1. **Set up your environment**: Copy `.env.example` to `.env` and fill in your API keys
2. **Learn the tools**: Ask the LangWatch MCP about prompt management and testing
3. **Start building**: Implement your agent in the `app/` directory
4. **Write tests**: Create scenario tests for your agent's capabilities
5. **Iterate**: Use evaluations to improve your agent's performance

---

## Resources

- **Scenario Documentation**: https://scenario.langwatch.ai/
- **Agent Testing Pyramid**: https://scenario.langwatch.ai/best-practices/the-agent-testing-pyramid
- **LangWatch Dashboard**: https://app.langwatch.ai/
- **Agno Documentation**: https://docs.agno.com/

---

Remember: Building production-ready agents means combining great AI capabilities with solid software engineering practices. Follow these guidelines to create agents that are reliable, testable, and maintainable.
