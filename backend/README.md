# Atlas — Personal Productivity Agent

> MEST Tech Studio · March Program · Week 2 Assignment

A personal productivity agent that manages your calendar, email, web research, and notes through natural language. Built with PydanticAI, FastAPI, and Next.js.

---

## What it does

Tell the agent what you need in plain English. It reasons about the task, picks the right tools, chains them together, and returns a clear answer — pausing for your approval before any sensitive action like sending an email or creating a calendar event.

**Example:**

> _"Find a good restaurant near the office and add it to my calendar for Friday lunch"_

The agent calls `web_search`, picks a result, then calls `create_calendar_event` — and pauses to ask your approval before writing anything to your calendar.

---

## Architecture

```
Next.js (frontend)
  ├── Chat UI
  ├── Execution trace panel   ← shows every tool call + result live
  └── Approval gate UI        ← pauses for sensitive actions

FastAPI (backend)
  ├── POST /chat              ← SSE stream of agent events
  ├── POST /approve           ← resumes suspended agent runs
  └── PydanticAI Agent
        ├── Tool: Calendar    (Google Calendar API)
        ├── Tool: Gmail       (Gmail API)
        ├── Tool: Web Search  (Tavily API)
        └── Tool: Notes       (SQLite, exposed via MCP server)
              └── mcp_server.py  ← stdio MCP server
```

---

## Tools

| Tool                    | Description                                       |
| ----------------------- | ------------------------------------------------- |
| `get_calendar_events`   | Read events for a given date                      |
| `create_calendar_event` | Create a new calendar event _(requires approval)_ |
| `check_availability`    | Check if a time slot is free                      |
| `search_emails`         | Search Gmail inbox by query                       |
| `read_email`            | Read the full body of an email                    |
| `draft_email`           | Save a draft email _(requires approval)_          |
| `send_draft`            | Send a saved draft _(requires approval)_          |
| `web_search`            | Search the internet via Tavily                    |
| `save_note`             | Save a note to SQLite _(via MCP)_                 |
| `list_notes`            | List recent notes _(via MCP)_                     |
| `search_notes`          | Search notes by keyword _(via MCP)_               |
| `delete_note`           | Delete a note by ID _(via MCP)_                   |

---

## Tech Stack

| Layer           | Technology               |
| --------------- | ------------------------ |
| Language        | Python 3.12              |
| Package manager | uv                       |
| Agent framework | PydanticAI               |
| LLM             | OpenAI GPT-4o            |
| Backend         | FastAPI + uvicorn        |
| MCP server      | MCP Python SDK (stdio)   |
| Frontend        | Next.js 14 (App Router)  |
| Google APIs     | google-api-python-client |
| Web search      | Tavily API               |
| Notes storage   | SQLite                   |

---

## Prerequisites

- Python 3.12+
- Node.js 18+
- `uv` installed (`pip install uv`)
- A Google Cloud project with Calendar and Gmail APIs enabled
- An OpenAI API key
- A Tavily API key (free tier at app.tavily.com)

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-team/atlas-agent.git
cd atlas-agent
```

### 2. Backend setup

```bash
cd backend
uv sync
```

Copy the env template and fill in your values:

```bash
cp .env.example .env
```

```bash
# backend/.env
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
GOOGLE_CREDENTIALS_PATH=credentials.json
GOOGLE_TOKEN_PATH=token.json
NOTES_DB_PATH=notes.db
USER_TIMEZONE=Africa/Accra
```

### 3. Google credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project → enable **Google Calendar API** and **Gmail API**
3. Configure OAuth consent screen (External) → add your Gmail as a test user
4. Create credentials → **OAuth client ID** → **Desktop app** → download JSON
5. Rename the downloaded file to `credentials.json` and place it in `backend/`

### 4. Authenticate with Google (one-time)

Run this **before** starting the server. It opens a browser, you log in once, and writes `token.json`:

```bash
cd backend
uv run python setup_auth.py
```

### 5. Start the backend

```bash
uv run uvicorn main:app --reload --port 8000
```

Verify it's running:

```bash
curl http://localhost:8000/health
# {"status":"ok","agent":"Aria v1.0"}
```

### 6. Frontend setup

```bash
cd frontend
npm install
cp .env.local.example .env.local
```

```bash
# frontend/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
```

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## Usage

### Via the chat UI

Open the frontend and type any natural language request:

- _"What's on my calendar today?"_
- _"Show me unread emails from this week"_
- _"Search for Python async best practices and save a note"_
- _"Am I free tomorrow at 3pm?"_
- _"Draft a reply to Sarah's last email saying I'll be 10 minutes late"_

### Via Postman / curl

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is on my calendar today?",
    "history": [],
    "timezone": "Africa/Accra"
  }'
```

The response is a Server-Sent Events stream:

```
data: {"type": "tool_call", "tool": "get_calendar_events", "args": {"date": "2026-03-09"}}
data: {"type": "tool_result", "tool": "get_calendar_events", "result": {...}}
data: {"type": "done", "response": {"answer": "You have 2 events today..."}}
data: {"type": "stream_end"}
```

### Approving sensitive actions

When the agent is about to send an email or create a calendar event, it emits:

```
data: {"type": "approval_required", "approval_id": "abc-123", "payload": {...}}
```

Approve or reject via:

```bash
curl -X POST http://localhost:8000/approve \
  -H "Content-Type: application/json" \
  -d '{"approval_id": "abc-123", "decision": "approve"}'
```

---

## Project Structure

```
atlas-agent/
├── backend/
│   ├── main.py              # FastAPI app, SSE endpoint, approval gate
│   ├── agent.py             # PydanticAI agent, system prompt, run interface
│   ├── mcp_server.py        # MCP server exposing notes tools over stdio
│   ├── setup_auth.py        # One-time Google OAuth script
│   ├── pyproject.toml       # Dependencies (managed by uv)
│   ├── .env.example         # Environment variable template
│   └── tools/
│       ├── google_auth.py   # Shared async Google OAuth2 helper
│       ├── calendar.py      # Google Calendar tools
│       ├── gmail.py         # Gmail tools
│       ├── search.py        # Tavily web search tool
│       └── notes.py         # SQLite notes logic (used by MCP server)
│
└── frontend/
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx
    │   └── globals.css
    ├── components/
    │   ├── ChatPage.tsx      # Main chat orchestrator
    │   ├── TracePanel.tsx    # Live execution trace
    │   └── ApprovalGate.tsx  # Human-in-the-loop approval UI
    ├── lib/
    │   ├── types.ts          # Shared TypeScript types
    │   └── api.ts            # Backend API client (SSE + approval)
    └── next.config.js
```

---

## MCP Integration

The Notes tool is exposed as a standalone MCP server (`mcp_server.py`). The agent connects to it via the MCP protocol over stdio — it does not call the notes functions directly.

This means the notes tools can be used by any MCP-compatible client (Claude Desktop, Cursor, etc.) by pointing them at `mcp_server.py`.

To test the MCP server in isolation:

```bash
cd backend
uv run python mcp_server.py
```

Then send a JSON-RPC initialize message over stdin to verify the tools are advertised correctly.

---

## Human-in-the-Loop

The following actions always require explicit approval before executing:

- `create_calendar_event` — creating any calendar event
- `draft_email` — saving an email draft
- `send_draft` — sending an email

The agent stages the action, emits an `approval_required` SSE event with full details, and blocks until `POST /approve` is called with `decision: "approve"` or `"reject"`. Approvals time out after 5 minutes.

---

## Troubleshooting

**`credentials.json not found`** — Download your OAuth client JSON from Google Cloud Console and place it in `backend/`.

**`token.json not found`** — Run `uv run python setup_auth.py` from the `backend/` directory.

**`token.json is invalid or revoked`** — Delete `token.json` and re-run `setup_auth.py`.

**`Tavily API key not configured`** — Add `TAVILY_API_KEY=tvly-...` to `backend/.env`.

**Approval timeout** — Approvals expire after 5 minutes. Re-send the original chat request to trigger a new approval gate.

---

## Team

MEST Tech Studio — March Program, Week 2
