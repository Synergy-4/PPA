"""
tools/email.py — Gmail tools for the Aria agent.

Tools registered:
  - search_emails(query, max_results)
  - read_email(email_id)
  - draft_email(to, subject, body, reply_to_id)
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from agent import agent, AgentDeps
from tools.google_auth import get_gmail_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_body(payload: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _decode_body(part)
        if text:
            return text

    return ""


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class EmailSummary(BaseModel):
    id: str
    thread_id: str
    from_address: str
    to_address: str
    subject: str
    date: str
    snippet: str


class EmailDetail(BaseModel):
    id: str
    thread_id: str
    from_address: str
    to_address: str
    subject: str
    date: str
    body: str


class DraftEmailInput(BaseModel):
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Full email body text")
    reply_to_id: Optional[str] = Field(
        default=None,
        description="Gmail message ID to reply to. Omit for new emails.",
    )


class DraftEmailResult(BaseModel):
    success: bool
    draft_id: Optional[str] = None
    message: str


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@agent.tool
async def search_emails(
    ctx: RunContext[AgentDeps],
    query: str,
    max_results: int = 5,
) -> list[EmailSummary]:
    """
    Search the user's Gmail inbox using a search query.

    Args:
        query:       Gmail search string, e.g. "from:sarah", "subject:report",
                     "is:unread", or a combination like "from:sarah is:unread".
        max_results: Maximum number of emails to return (default 5, max 20).

    Returns:
        A list of matching emails with sender, subject, date, and a short snippet.
        Use read_email to get the full body of a specific email.
    """
    try:
        service = await get_gmail_service()
        max_results = min(max_results, 20)

        response = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()

        messages = response.get("messages", [])
        if not messages:
            return []

        results = []
        for msg_ref in messages:
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()

            headers = msg.get("payload", {}).get("headers", [])
            results.append(EmailSummary(
                id=msg["id"],
                thread_id=msg["threadId"],
                from_address=_header(headers, "From"),
                to_address=_header(headers, "To"),
                subject=_header(headers, "Subject"),
                date=_header(headers, "Date"),
                snippet=msg.get("snippet", ""),
            ))

        return results

    except HttpError as e:
        raise ValueError(f"Gmail API error: {e.reason}") from e
    except Exception as e:
        raise ValueError(f"Failed to search emails: {str(e)}") from e


@agent.tool
async def read_email(
    ctx: RunContext[AgentDeps],
    email_id: str,
) -> EmailDetail:
    """
    Read the full content of a specific email by its ID.

    Args:
        email_id: The Gmail message ID from a previous search_emails call.

    Returns:
        Full email with sender, recipient, subject, date, and complete body text.
    """
    try:
        service = await get_gmail_service()

        msg = service.users().messages().get(
            userId="me",
            id=email_id,
            format="full",
        ).execute()

        headers = msg.get("payload", {}).get("headers", [])
        body = _decode_body(msg.get("payload", {}))

        return EmailDetail(
            id=msg["id"],
            thread_id=msg["threadId"],
            from_address=_header(headers, "From"),
            to_address=_header(headers, "To"),
            subject=_header(headers, "Subject"),
            date=_header(headers, "Date"),
            body=body or msg.get("snippet", "(No body found)"),
        )

    except HttpError as e:
        raise ValueError(f"Gmail API error: {e.reason}") from e
    except Exception as e:
        raise ValueError(f"Failed to read email: {str(e)}") from e


@agent.tool
async def draft_email(
    ctx: RunContext[AgentDeps],
    input: DraftEmailInput,
) -> DraftEmailResult:
    """
    Save a draft email in Gmail. Does NOT send — user must approve before sending.

    IMPORTANT: This is a sensitive action. Always show the user the full draft
    details (to, subject, body) and obtain explicit approval before calling this tool.

    Args:
        input: Recipient, subject, body, and optional reply thread ID.

    Returns:
        The draft ID if saved successfully.
    """
    try:
        service = await get_gmail_service()

        # Build MIME message
        mime = MIMEMultipart()
        mime["To"] = input.to
        mime["Subject"] = input.subject
        mime.attach(MIMEText(input.body, "plain"))

        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
        draft_body: dict = {"message": {"raw": raw}}

        # If replying, attach thread ID
        if input.reply_to_id:
            original = service.users().messages().get(
                userId="me", id=input.reply_to_id, format="metadata",
                metadataHeaders=["Subject"],
            ).execute()
            draft_body["message"]["threadId"] = original["threadId"]

        draft = service.users().drafts().create(
            userId="me",
            body=draft_body,
        ).execute()

        return DraftEmailResult(
            success=True,
            draft_id=draft["id"],
            message=f"Draft saved. Ready to send to {input.to}.",
        )

    except HttpError as e:
        return DraftEmailResult(
            success=False,
            message=f"Gmail API error: {e.reason}",
        )
    except Exception as e:
        return DraftEmailResult(
            success=False,
            message=f"Failed to draft email: {str(e)}",
        )


@agent.tool
async def send_draft(
    ctx: RunContext[AgentDeps],
    draft_id: str,
) -> dict:
    """
    Send a previously saved Gmail draft by its draft ID.

    IMPORTANT: Only call this after the user has explicitly approved sending.
    Never call this without prior human approval.

    Args:
        draft_id: The draft ID returned by draft_email.

    Returns:
        Confirmation with the sent message ID.
    """
    try:
        service = await get_gmail_service()
        sent = service.users().drafts().send(
            userId="me",
            body={"id": draft_id},
        ).execute()
        return {"success": True, "message_id": sent["id"], "message": "Email sent successfully."}
    except HttpError as e:
        return {"success": False, "message": f"Gmail API error: {e.reason}"}
    except Exception as e:
        return {"success": False, "message": f"Failed to send email: {str(e)}"}