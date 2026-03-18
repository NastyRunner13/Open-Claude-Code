"""Read URL tool — fetch and extract content from web pages."""

import re

MAX_OUTPUT = 10000

SCHEMA = {
    "name": "read_url",
    "description": (
        "Fetch the content of a URL and return it as text. "
        "Strips HTML tags for readability. "
        "Use this for reading documentation pages, README files, API docs, etc."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
        },
        "required": ["url"],
    },
}


async def read_url(url: str) -> str:
    """Fetch URL content and return as cleaned text."""
    try:
        import httpx
    except ImportError:
        return "Error: httpx package not installed. Run: pip install httpx"

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return f"Error: HTTP {e.response.status_code} for {url}"
    except httpx.RequestError as e:
        return f"Error fetching URL: {e}"
    except Exception as e:
        return f"Error: {e}"

    content_type = response.headers.get("content-type", "")

    if "text/html" in content_type:
        text = _strip_html(response.text)
    else:
        text = response.text

    if len(text) > MAX_OUTPUT:
        return text[:MAX_OUTPUT] + "\n[truncated]"
    return text


def _strip_html(html: str) -> str:
    """Simple HTML tag stripping — convert to readable text."""
    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Clean up whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Decode common HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return text
