"""
main.py — FastAPI application for the Aria productivity agent.

Endpoints:
  POST /chat          → streams agent events via SSE
  POST /approve       → resumes a suspended agent run (human-in-the-loop)
  GET  /health        → health check
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncGenerator

import logfire
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import AgentDeps, register_tools, run_agent

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logfire — configure once at startup.
# Reads LOGFIRE_TOKEN from the environment automatically.
# instrument_pydantic_ai() traces every agent run, tool call, and LLM request.
# ---------------------------------------------------------------------------

logfire.configure()
logfire.instrument_pydantic_ai()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Aria Productivity Agent", version="1.0.0")

# Instrument all FastAPI routes — adds request/response spans to every endpoint.
logfire.instrument_fastapi(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all tool modules on startup
register_tools()


# ---------------------------------------------------------------------------
# In-memory session store
# Holds pending approval states keyed by approval_id.
# In production, replace with Redis.
# ---------------------------------------------------------------------------

# approval_id -> {"payload": dict, "queue": asyncio.Queue}
_pending_approvals: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str          # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    session_id: str = ""
    timezone: str = "Africa/Accra"


class ApprovalRequest(BaseModel):
    approval_id: str
    decision: str      # "approve" | "reject"
    edited_payload: dict | None = None  # if user edited the action details


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _serialize(obj: any) -> any:
    """Recursively convert Pydantic models and other non-serializable types to dicts."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    return obj


def _sse(event_type: str, data: dict) -> str:
    """Format a single SSE frame, safely serializing Pydantic models."""
    payload = json.dumps({"type": event_type, **_serialize(data)})
    return f"data: {payload}\n\n"


async def _stream_agent(
    request: ChatRequest,
) -> AsyncGenerator[str, None]:
    """
    Core streaming generator.
    Runs the agent and forwards each event as an SSE frame.
    When the agent signals approval_required, we pause and hand off
    to the approval flow.
    """
    deps = AgentDeps(user_timezone=request.timezone)
    history = [
        {"role": m.role, "content": m.content} for m in request.history
    ]

    async for event in run_agent(
        user_message=request.message,
        message_history=history,
        deps=deps,
    ):
        event_type = event.pop("type")

        if event_type == "approval_required":
            # Generate an approval ID and park it
            approval_id = str(uuid.uuid4())
            queue: asyncio.Queue[dict] = asyncio.Queue()
            _pending_approvals[approval_id] = {
                "payload": event.get("payload", {}),
                "queue": queue,
            }

            # Tell the frontend to show the approval gate
            yield _sse("approval_required", {
                "approval_id": approval_id,
                "payload": event.get("payload", {}),
            })

            # Block until the user approves or rejects (timeout: 5 min)
            try:
                decision = await asyncio.wait_for(queue.get(), timeout=300)
            except asyncio.TimeoutError:
                yield _sse("error", {"detail": "Approval timed out after 5 minutes."})
                return
            finally:
                _pending_approvals.pop(approval_id, None)

            yield _sse("approval_resolved", {
                "decision": decision["decision"],
                "approval_id": approval_id,
            })

            if decision["decision"] == "reject":
                yield _sse("message", {"content": "Understood — action cancelled."})
                yield _sse("done", {"response": {"answer": "Action cancelled by user.", "actions_taken": []}})
                return

            # If approved, the agent continues naturally (the tool was already
            # staged; PydanticAI will execute it now that approval is granted).

        elif event_type == "tool_call":
            yield _sse("tool_call", event)

        elif event_type == "tool_result":
            yield _sse("tool_result", event)

        elif event_type == "message":
            yield _sse("message", event)

        elif event_type == "done":
            yield _sse("done", event)

        elif event_type == "error":
            yield _sse("error", event)

    yield _sse("stream_end", {})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """
    Main chat endpoint. Returns a Server-Sent Events stream.

    The frontend should open an EventSource / fetch with SSE parsing.
    Each event has the shape: { type: string, ...fields }

    Event types emitted:
      tool_call         — { tool: string, args: object }
      tool_result       — { tool: string, result: any }
      message           — { content: string }  (partial text delta)
      approval_required — { approval_id: string, payload: object }
      approval_resolved — { decision: "approve"|"reject", approval_id: string }
      done              — { response: AgentResponse }
      error             — { detail: string }
      stream_end        — {}
    """
    return StreamingResponse(
        _stream_agent(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )


@app.post("/approve")
async def approve(request: ApprovalRequest) -> dict:
    """
    Resume a suspended agent run after human approval or rejection.

    Called by the frontend when the user clicks Approve / Reject in the UI.
    """
    pending = _pending_approvals.get(request.approval_id)
    if not pending:
        raise HTTPException(
            status_code=404,
            detail=f"No pending approval found for ID {request.approval_id}. It may have timed out.",
        )

    await pending["queue"].put({
        "decision": request.decision,
        "edited_payload": request.edited_payload,
    })

    return {"status": "ok", "decision": request.decision}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "agent": "Aria v1.0"}