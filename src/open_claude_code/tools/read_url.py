"""Read URL tool — fetch and extract content from web pages."""

import re

from open_claude_code.tools.context import ToolContext, unbound_result
from open_claude_code.tools.result import ToolResult
from open_claude_code.tools.web_safety import fetch_public_url, load_cache, save_cache, untrusted_content

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


async def read_url(url: str, _context: ToolContext | None = None) -> ToolResult:
    """Fetch URL content and return as cleaned text."""
    if _context is None:
        return unbound_result("read_url")
    max_output = _context.max_output
    cached = load_cache(_context, "url", url)
    if cached:
        return ToolResult.ok(cached.get("content", ""), **cached.get("metadata", {}), cached=True)

    try:
        body, final_url, content_type, status_code, clipped = await fetch_public_url(url, _context)
        raw_text = body.decode("utf-8", errors="replace")
    except Exception as e:
        return ToolResult.fail(str(e), url=url)

    if "text/html" in content_type:
        text = _strip_html(raw_text)
    else:
        text = raw_text

    truncated = clipped or len(text) > max_output
    if truncated:
        text = text[:max_output] + "\n[truncated]"

    text = untrusted_content(final_url, text)

    metadata = {
        "url": final_url,
        "requested_url": url,
        "status_code": status_code,
        "content_type": content_type,
        "truncated": truncated,
        "untrusted": True,
    }
    save_cache(_context, "url", url, {"content": text, "metadata": metadata})
    return ToolResult.ok(
        text,
        **metadata,
    )


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
