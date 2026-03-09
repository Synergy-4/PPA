"""
agent.py — PydanticAI agent for the Personal Productivity Assistant.

Responsibilities:
- Define the agent with a production-quality system prompt
- Register all tools (calendar, email, search, notes-via-MCP)
- Define structured output types
- Expose a run_agent() coroutine that streams events for FastAPI to consume
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPServerStdio
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------

class AgentResponse(BaseModel):
    """The agent always returns a structured response."""
    answer: str
    """Human-readable answer to show in the chat UI."""
    actions_taken: list[str] = []
    """Short summaries of each action the agent performed, e.g. 'Read 3 calendar events'."""
    requires_approval: bool = False
    """True when the agent has staged a sensitive action and is waiting for the user."""
    approval_payload: dict[str, Any] | None = None
    """The staged action details to show in the approval gate UI."""


# ---------------------------------------------------------------------------
# Agent dependencies (injected at runtime)
# ---------------------------------------------------------------------------

@dataclass
class AgentDeps:
    """Runtime dependencies injected into every tool call via RunContext."""
    user_timezone: str = "Africa/Accra"
    today: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    # OAuth credentials are read from env; these are passed for explicitness
    google_token_path: str = field(
        default_factory=lambda: os.getenv("GOOGLE_TOKEN_PATH", "token.json")
    )
    tavily_api_key: str = field(
        default_factory=lambda: os.getenv("TAVILY_API_KEY", "")
    )


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """
You are Aria, a sharp and reliable personal productivity assistant.
Your job is to help the user manage their calendar, emails, web research,
and personal notes — entirely through natural language.

## Your tools
You have exactly four tools. Use the right one every time:

| Tool                    | When to use it                                                          |
|-------------------------|-------------------------------------------------------------------------|
| get_calendar_events     | User asks what's on their schedule, upcoming meetings, free slots       |
| create_calendar_event   | User wants to add, schedule, or block time on their calendar            |
| search_emails           | User wants to find, read, or summarise recent emails                    |
| draft_email             | User wants to write or send a reply or new email                        |
| web_search              | User needs current information, research, recommendations, facts        |
| save_note               | User wants to remember something, jot down an idea, save a note        |
| list_notes              | User wants to see or search their saved notes                           |

Never call a tool you don't need. If the user's request can be answered
from context already in this conversation, answer directly.

## Multi-step reasoning
For tasks that require multiple steps, reason step by step:
1. State what information you need first.
2. Call the appropriate tool.
3. Use the result to decide your next step.
4. Repeat until you have everything you need.
5. Give a clear, concise final answer.

Always prefer chaining tools intelligently over asking the user for
information you can retrieve yourself.

## Output format
- Be concise. No padding, no filler phrases like "Certainly!" or "Of course!".
- When listing events or emails, use a short structured format (time – title).
- When you've completed a multi-step task, summarise what you did in 1–2 sentences.
- If a tool returns an error, tell the user plainly what failed and why, then
  suggest what they can do next.

## Sensitive actions — MANDATORY approval rules
The following actions MUST NEVER execute without explicit user approval:
  - Sending or drafting an outbound email (draft_email)
  - Creating a new calendar event (create_calendar_event)

When you are about to perform a sensitive action:
  1. Do NOT execute it immediately.
  2. Set requires_approval = true in your response.
  3. Populate approval_payload with the full details of what you intend to do.
  4. Ask the user clearly: "I'm about to [action]. Shall I go ahead?"
  5. Only proceed after the user explicitly approves.
  If the user rejects, acknowledge it and stop. Never retry a rejected action.

## Hard constraints
- Never invent calendar events or emails that don't exist in tool results.
- Never send an email without approval, even if the user says "just do it".
- Never store sensitive information (passwords, API keys) in notes.
- Never make up search results — if web_search fails, say so.
- If you are uncertain which tool to use, ask one clarifying question.
- Today's date is {today}. The user's timezone is {timezone}.
  Always use these when interpreting relative dates like "today", "tomorrow",
  "next Friday", etc.
""".strip()


# ---------------------------------------------------------------------------
# MCP server for Notes tool
# ---------------------------------------------------------------------------

notes_mcp_server = MCPServerStdio(
    command="python",
    args=["mcp_server.py"],
    env={**os.environ},
)


# ---------------------------------------------------------------------------
# Agent instantiation
# ---------------------------------------------------------------------------

agent: Agent[AgentDeps, AgentResponse] = Agent(
    model="openai:gpt-4o",
    deps_type=AgentDeps,
    output_type=AgentResponse,
    mcp_servers=[notes_mcp_server],
    system_prompt=SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# System prompt dynamic fields (injected at run time)
# ---------------------------------------------------------------------------

@agent.system_prompt
def inject_dynamic_context(ctx: RunContext[AgentDeps]) -> str:
    """Appends the user's current date and timezone into the system prompt."""
    return (
        f"\nToday's date: {ctx.deps.today}. "
        f"User timezone: {ctx.deps.user_timezone}."
    )


# ---------------------------------------------------------------------------
# Tool stubs — implementations live in tools/*.py and are registered here
# via @agent.tool decorators imported from each module.
# Importing the modules is enough; the decorators register themselves.
# ---------------------------------------------------------------------------

# These imports are intentionally deferred so this file stays readable.
# Each tools/ module calls @agent.tool internally.
def register_tools() -> None:
    """Call once at startup to register all tool modules with the agent."""
    from tools import calendar  # noqa: F401
    from tools import email     # noqa: F401
    from tools import search    # noqa: F401
    # Notes tools are served via MCP — no direct registration needed.


# ---------------------------------------------------------------------------
# Public run interface (used by FastAPI)
# ---------------------------------------------------------------------------

async def run_agent(
    user_message: str,
    message_history: list[dict] | None = None,
    deps: AgentDeps | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Run the agent and yield structured event dicts for SSE streaming.

    Event types:
      {"type": "tool_call",   "tool": str, "args": dict}
      {"type": "tool_result", "tool": str, "result": Any}
      {"type": "approval_required", "payload": dict}
      {"type": "message",     "content": str}
      {"type": "done",        "response": AgentResponse}
      {"type": "error",       "detail": str}
    """
    if deps is None:
        deps = AgentDeps()

    try:
        async with agent.run_stream(
            user_message,
            deps=deps,
            message_history=message_history or [],
        ) as result:
            async for event in result.stream_events():
                # Tool call started
                if event.type == "tool_call":
                    yield {
                        "type": "tool_call",
                        "tool": event.tool_name,
                        "args": event.args,
                    }
                # Tool result returned
                elif event.type == "tool_result":
                    yield {
                        "type": "tool_result",
                        "tool": event.tool_name,
                        "result": event.result,
                    }
                # Partial text delta
                elif event.type == "text_delta":
                    yield {"type": "message", "content": event.delta}

            # Final structured response
            final: AgentResponse = await result.get_output()
            if final.requires_approval:
                yield {"type": "approval_required", "payload": final.approval_payload}
            yield {"type": "done", "response": final.model_dump()}

    except Exception as exc:
        yield {"type": "error", "detail": str(exc)}


# Lazy import for type hint only
from typing import AsyncGenerator  # noqa: E402