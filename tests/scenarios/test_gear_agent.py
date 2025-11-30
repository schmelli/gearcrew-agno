"""
Scenario tests for the GearCrew gear extraction agent.
Tests end-to-end agent behavior using simulated user interactions.
"""

import os
import pytest
import scenario
from dotenv import load_dotenv

load_dotenv()

# Configure scenario defaults
scenario.configure(
    default_model="anthropic/claude-sonnet-4-20250514",
    max_turns=5,
    verbose=True,
)


class GearCrewAgent(scenario.AgentAdapter):
    """Adapter wrapping the GearCrew agent for scenario testing."""

    def __init__(self):
        super().__init__()
        from app.agent import get_agent
        self._agent = get_agent()

    @scenario.cache(ignore=["self"])
    async def call(self, input: scenario.AgentInput) -> str:
        """Process messages through the GearCrew agent with full context."""
        messages = input.messages
        if not messages:
            return "I need more information to help you."

        formatted_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                formatted_messages.append(f"User: {content}")
            elif role == "assistant":
                formatted_messages.append(f"Assistant: {content}")

        context = "\n".join(formatted_messages)
        user_message = input.last_new_user_message_str()

        if len(formatted_messages) > 1:
            prompt = f"""Previous conversation context:
{context}

Please continue the conversation by responding to the latest user message.
Remember to maintain context from the previous messages."""
        else:
            prompt = user_message or ""

        response = self._agent.run(prompt)
        return str(response.content) if response.content else ""


@pytest.mark.asyncio
async def test_gear_knowledge_question():
    """Test that the agent can answer basic gear questions."""
    result = await scenario.run(
        name="gear_knowledge_question",
        description="A hiker asks about lightweight backpacks for thru-hiking",
        agents=[
            GearCrewAgent(),
            scenario.UserSimulatorAgent(),
            scenario.JudgeAgent(
                criteria=[
                    "Agent should respond with information about backpacks",
                    "Agent should mention weight considerations for thru-hiking",
                    "Agent should be helpful and knowledgeable about hiking gear",
                ]
            ),
        ],
        script=[
            scenario.user(
                "What are some good lightweight backpacks for thru-hiking the PCT?"
            ),
            scenario.agent(),
            scenario.judge(),
        ],
    )

    assert result.success, f"Scenario failed: {result.reasoning}"


@pytest.mark.asyncio
async def test_gear_category_identification():
    """Test that the agent correctly identifies gear categories."""
    result = await scenario.run(
        name="gear_category_identification",
        description="User asks about different types of sleeping pads",
        agents=[
            GearCrewAgent(),
            scenario.UserSimulatorAgent(),
            scenario.JudgeAgent(
                criteria=[
                    "Agent should explain different types of sleeping pads",
                    "Agent should mention at least foam and inflatable options",
                    "Agent should discuss R-value or insulation characteristics",
                ]
            ),
        ],
        script=[
            scenario.user("What's the difference between foam and inflatable sleeping pads?"),
            scenario.agent(),
            scenario.judge(),
        ],
    )

    assert result.success, f"Scenario failed: {result.reasoning}"


@pytest.mark.asyncio
async def test_multi_turn_gear_conversation():
    """Test a multi-turn conversation about gear selection."""
    result = await scenario.run(
        name="multi_turn_gear_conversation",
        description="User has a back-and-forth about tent selection",
        agents=[
            GearCrewAgent(),
            scenario.UserSimulatorAgent(),
            scenario.JudgeAgent(
                criteria=[
                    "Agent should maintain context across conversation turns",
                    "Agent should provide increasingly specific recommendations",
                    "Agent should not contradict previous responses",
                ]
            ),
        ],
        script=[
            scenario.user("I'm looking for a tent for backpacking. What should I consider?"),
            scenario.agent(),
            scenario.user("I mostly camp in the summer in California. What capacity do you recommend?"),
            scenario.agent(),
            scenario.judge(),
        ],
    )

    assert result.success, f"Scenario failed: {result.reasoning}"
