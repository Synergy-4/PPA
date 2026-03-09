"""
mcp_server.py — MCP server exposing the Notes tool.

Run this as a subprocess; the Aria agent connects to it via stdio
using PydanticAI's MCPServerStdio integration.

Usage (standalone test):
    python mcp_server.py

The agent in agent.py starts this automatically via:
    MCPServerStdio(command="python", args=["mcp_server.py"])
"""

from __future__ import annotations

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    TextContent,
    Tool,
)

from tools.notes import (
    delete_note,
    init_db,
    list_notes,
    save_note,
    search_notes,
)

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

server = Server("aria-notes")
init_db()


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """Advertise all available notes tools to any MCP client."""
    return [
        Tool(
            name="save_note",
            description=(
                "Save a new note with a title, content, and optional tags. "
                "Use this when the user wants to remember something, jot down an idea, "
                "or capture information for later."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short, descriptive title for the note.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full note body text.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional keyword tags to make the note easier to find later.",
                        "default": [],
                    },
                },
                "required": ["title", "content"],
            },
        ),
        Tool(
            name="list_notes",
            description=(
                "List the user's most recent saved notes, newest first. "
                "Use this when the user asks to see their notes or wants a summary of what they've saved."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of notes to return (default 20, max 50).",
                        "default": 20,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="search_notes",
            description=(
                "Search saved notes by keyword across titles, content, and tags. "
                "Use this when the user asks to find a specific note or remember something they saved."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword or phrase to search for.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 10).",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="delete_note",
            description=(
                "Delete a saved note by its ID. "
                "Only use this when the user explicitly asks to delete or remove a note."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "integer",
                        "description": "The integer ID of the note to delete.",
                    },
                },
                "required": ["note_id"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool call dispatcher
# ---------------------------------------------------------------------------

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> CallToolResult:
    """Dispatch incoming tool calls to the appropriate notes function."""
    try:
        if name == "save_note":
            result = save_note(
                title=arguments["title"],
                content=arguments["content"],
                tags=arguments.get("tags", []),
            )
            return CallToolResult(
                content=[TextContent(type="text", text=result.model_dump_json(indent=2))]
            )

        elif name == "list_notes":
            notes = list_notes(limit=arguments.get("limit", 20))
            payload = [n.model_dump() for n in notes]
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(payload, indent=2))]
            )

        elif name == "search_notes":
            result = search_notes(
                query=arguments["query"],
                limit=arguments.get("limit", 10),
            )
            return CallToolResult(
                content=[TextContent(type="text", text=result.model_dump_json(indent=2))]
            )

        elif name == "delete_note":
            result = delete_note(note_id=arguments["note_id"])
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))]
            )

        else:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Unknown tool: {name}")],
                isError=True,
            )

    except KeyError as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Missing required argument: {e}")],
            isError=True,
        )
    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Tool error: {str(e)}")],
            isError=True,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())