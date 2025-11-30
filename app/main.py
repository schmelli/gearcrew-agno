"""
Main entry point for the GearCrew agent.
"""

import sys
from dotenv import load_dotenv

load_dotenv()

from app.agent import get_agent, extract_gear_info, run_agent_chat


def main():
    """Run the GearCrew agent in interactive mode."""
    print("GearCrew - Hiking/Backpacking Gear Knowledge Extractor")
    print("=" * 55)
    print("\nCommands:")
    print("  extract <url>  - Extract gear info from a URL")
    print("  chat           - Start interactive chat mode")
    print("  quit           - Exit the application")
    print()

    while True:
        try:
            user_input = input("GearCrew> ").strip()

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break

            if user_input.lower().startswith("extract "):
                url = user_input[8:].strip()
                if not url:
                    print("Please provide a URL to extract from.")
                    continue

                print(f"\nExtracting gear information from: {url}")
                print("This may take a moment...\n")

                result = extract_gear_info(url)

                print(f"Source: {result.source_url}")
                print(f"Type: {result.source_type}")
                print(f"\nGear Items Found: {len(result.gear_items)}")
                for item in result.gear_items:
                    print(f"  - {item.brand} {item.name}")
                    if item.weight_grams:
                        print(f"    Weight: {item.weight_grams}g")
                    if item.price_usd:
                        print(f"    Price: ${item.price_usd:.2f}")

                print(f"\nKnowledge Facts: {len(result.knowledge_facts)}")
                for fact in result.knowledge_facts[:5]:
                    print(f"  - [{fact.fact_type.value}] {fact.content[:100]}...")

                print()

            elif user_input.lower() == "chat":
                print("\nEntering chat mode. Type 'back' to return to main menu.\n")
                while True:
                    chat_input = input("You> ").strip()
                    if chat_input.lower() == "back":
                        print("Returning to main menu.\n")
                        break
                    if not chat_input:
                        continue

                    response = run_agent_chat(chat_input)
                    print(f"\nGearCrew: {response}\n")

            else:
                response = run_agent_chat(user_input)
                print(f"\n{response}\n")

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
