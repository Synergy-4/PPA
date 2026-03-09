"""
tools/search.py — Web search tool for the Aria agent using Tavily.

Tools registered:
  - web_search(query, max_results)
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from agent import agent, AgentDeps

TAVILY_API_URL = "https://api.tavily.com/search"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    score: Optional[float] = None


class WebSearchResult(BaseModel):
    query: str
    results: list[SearchResult]
    total: int


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@agent.tool
async def web_search(
    ctx: RunContext[AgentDeps],
    query: str,
    max_results: int = 5,
) -> WebSearchResult:
    """
    Search the internet for current information, facts, recommendations, or research.

    Use this tool when the user asks about:
    - Current events or news
    - Recommendations (restaurants, products, services)
    - Facts you're not certain about
    - Anything that requires up-to-date information

    Args:
        query:       A clear, specific search query. Be precise — good queries
                     return better results (e.g. "best sushi restaurant Accra Ghana"
                     not just "sushi").
        max_results: Number of results to return (default 5, max 10).

    Returns:
        A ranked list of search results with titles, URLs, and snippets.
    """
    api_key = ctx.deps.tavily_api_key or os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        raise ValueError(
            "Tavily API key not configured. Set the TAVILY_API_KEY environment variable."
        )

    max_results = min(max_results, 10)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                TAVILY_API_URL,
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                    "include_answer": False,
                    "include_raw_content": False,
                },
            )
            response.raise_for_status()
            data = response.json()

        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
                score=r.get("score"),
            )
            for r in data.get("results", [])
        ]

        return WebSearchResult(
            query=query,
            results=results,
            total=len(results),
        )

    except httpx.HTTPStatusError as e:
        raise ValueError(f"Tavily search failed ({e.response.status_code}): {e.response.text}") from e
    except httpx.RequestError as e:
        raise ValueError(f"Network error during web search: {str(e)}") from e
    except Exception as e:
        raise ValueError(f"Web search failed: {str(e)}") from e