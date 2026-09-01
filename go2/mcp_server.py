# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""MCP server exposing retrieval to any MCP client.

Built against MCP SDK 2.x, where ``FastMCP`` was renamed ``MCPServer``.

Deliberately thin: each tool delegates straight to ``go2.tools`` and holds no
logic of its own. That is what lets the same four functions serve this server
today and an in-process agent loop later without a second implementation.

Run with ``go2 serve`` (stdio transport).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from go2.tools.search import fetch_document as _fetch_document
from go2.tools.search import list_documents as _list_documents
from go2.tools.search import search_documents as _search_documents

mcp = MCPServer(
    "go2assistant",
    instructions=(
        "Answers questions about the user's own documents from OneDrive, Google Drive, "
        "and local uploads.\n\n"
        "Use search_documents for anything about the CONTENT of documents. Prefer full "
        "natural-language questions over keywords -- half the retrieval is semantic. If "
        "the first search misses, rephrase and search again rather than giving up; "
        "several narrow searches beat one broad one.\n\n"
        "Use list_documents for questions about the FILES themselves -- which documents "
        "exist, what came from where, what failed to index. Vector search cannot answer "
        "those.\n\n"
        "Use fetch_document when a snippet is suggestive but incomplete and you need the "
        "surrounding text.\n\n"
        "Always cite the `citation` field of any passage you rely on, so the user can "
        "verify the answer against the original file.\n\n"
        "This index covers ingested files only. It is frequently one of several "
        "sources -- a project may also have a tracker, a wiki, or a chat history "
        "reachable through other tools. An empty result here means the answer is not "
        "in the indexed files; it does not mean the answer does not exist. Say which "
        "of the two you mean, and check the other sources available to you before "
        "concluding something was never recorded."
    ),
)


@mcp.tool()
def search_documents(
    query: str,
    limit: int = 8,
    source: str | None = None,
    title_contains: str | None = None,
) -> list[dict[str, Any]]:
    """Search the user's documents for passages answering a question.

    Args:
        query: A natural-language question. Full sentences retrieve better
            than keywords.
        limit: Maximum passages to return.
        source: Restrict to one connector: 'gdrive', 'onedrive', or 'upload'.
        title_contains: Restrict to documents whose title contains this text.
    """
    return _search_documents(query, limit=limit, source=source, title_contains=title_contains)


@mcp.tool()
def fetch_document(document_id: str, page: int | None = None) -> dict[str, Any]:
    """Read the full text of one document.

    Args:
        document_id: An id returned by search_documents.
        page: Restrict to a single page number, if the document has pages.
    """
    return _fetch_document(document_id, page=page)


@mcp.tool()
def list_documents(
    source: str | None = None,
    title_contains: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List indexed documents by metadata rather than by content.

    Use for questions about which files exist, where they came from, or which
    failed to index -- things no passage search can answer.

    Args:
        source: Restrict to one connector: 'gdrive', 'onedrive', or 'upload'.
        title_contains: Restrict to titles containing this text.
        status: Restrict to 'indexed', 'pending', 'failed', or 'skipped'.
        limit: Maximum documents to return.
    """
    return _list_documents(source=source, title_contains=title_contains, status=status, limit=limit)


def main() -> None:
    """Run the server on stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
