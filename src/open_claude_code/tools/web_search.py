"""Web search tool using DuckDuckGo (free, no API key required)."""

from open_claude_code.tools.result import ToolResult

MAX_OUTPUT = 10000

SCHEMA = {
    "name": "web_search",
    "description": (
        "Search the web using DuckDuckGo. "
        "Returns relevant results with titles, URLs, and snippets. "
        "Use this to find documentation, solutions, or current information."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return. Defaults to 5.",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}


async def web_search(query: str, max_results: int = 5) -> ToolResult:
    """Search the web using DuckDuckGo."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return ToolResult.fail(
            "duckduckgo-search package not installed. Run: pip install duckduckgo-search",
            query=query,
        )

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        return ToolResult.fail(f"Error performing web search: {e}", query=query)

    if not results:
        return ToolResult.ok(f"No results found for: {query}", query=query, result_count=0)

    output_parts = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        url = r.get("href", r.get("link", ""))
        body = r.get("body", r.get("snippet", ""))
        output_parts.append(f"{i}. {title}\n   {url}\n   {body}")

    output = "\n\n".join(output_parts)
    truncated = len(output) > MAX_OUTPUT
    if truncated:
        output = output[:MAX_OUTPUT] + "\n[truncated]"

    return ToolResult.ok(output, query=query, result_count=len(results), truncated=truncated)
