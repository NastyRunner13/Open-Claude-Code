"""Web search tool using DuckDuckGo (free, no API key required)."""

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


async def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "Error: duckduckgo-search package not installed. Run: pip install duckduckgo-search"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        return f"Error performing web search: {e}"

    if not results:
        return f"No results found for: {query}"

    output_parts = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        url = r.get("href", r.get("link", ""))
        body = r.get("body", r.get("snippet", ""))
        output_parts.append(f"{i}. {title}\n   {url}\n   {body}")

    output = "\n\n".join(output_parts)
    if len(output) > MAX_OUTPUT:
        return output[:MAX_OUTPUT] + "\n[truncated]"
    return output
