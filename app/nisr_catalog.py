"""Client for NISR's own microdata catalogue MCP server (https://microdatabk.statistics.gov.rw/mcp).

Used when the loaded tables cannot answer: the agent asks NISR's catalogue which survey or document covers
the topic, so it can point the user to the right official source instead of guessing.
"""
import json
import os
import threading

import httpx

MCP_URL = os.getenv("NISR_MCP_URL", "https://microdatabk.statistics.gov.rw/mcp")
TIMEOUT = 15
PUBLIC_STUDY_PAGE = "https://microdata.statistics.gov.rw/index.php/catalog/study/"


class CatalogError(Exception):
    pass


def _parse(response):
    """The server answers with JSON or with server-sent events; return the JSON-RPC result."""
    if "text/event-stream" in response.headers.get("content-type", ""):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                if "result" in payload or "error" in payload:
                    break
        else:
            raise CatalogError("empty response from NISR catalogue")
    else:
        payload = response.json()
    if "error" in payload:
        raise CatalogError(str(payload["error"].get("message", "catalogue error")))
    return payload["result"]


def _call(method, params, client, session=None, request_id=1):
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    if session:
        headers["mcp-session-id"] = session
    body = {"jsonrpc": "2.0", "method": method, "params": params}
    if request_id is not None:
        body["id"] = request_id
    response = client.post(MCP_URL, headers=headers, json=body, timeout=TIMEOUT)
    response.raise_for_status()
    return response


_client = httpx.Client()
_session = {"id": None}
_session_lock = threading.Lock()


def _open_session():
    init = _call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                "clientInfo": {"name": "baza-nisr", "version": "1.0"}}, _client)
    session = init.headers.get("mcp-session-id")
    _call("notifications/initialized", {}, _client, session, request_id=None)
    return session


def call_tool(name, arguments):
    """Call a tool on NISR's MCP server, reusing one session (re-opened once if it expired)."""
    try:
        for attempt in range(2):
            with _session_lock:
                if _session["id"] is None or attempt:
                    _session["id"] = _open_session()
                session = _session["id"]
            try:
                result = _parse(_call("tools/call", {"name": name, "arguments": arguments}, _client, session, 2))
                break
            except (httpx.HTTPStatusError, CatalogError):
                if attempt:
                    raise
    except (httpx.HTTPError, ValueError, KeyError) as error:
        raise CatalogError(f"NISR catalogue unavailable: {type(error).__name__}") from error
    texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except ValueError:
        return {"text": joined[:4000]}


def list_tools():
    with httpx.Client() as client:
        init = _call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                    "clientInfo": {"name": "baza-nisr", "version": "1.0"}}, client)
        session = init.headers.get("mcp-session-id")
        _call("notifications/initialized", {}, client, session, request_id=None)
        return _parse(_call("tools/list", {}, client, session, 2))


def search(query, limit=5):
    """Search NISR's catalogue (surveys and documents) and return short pointers."""
    result = call_tool("nada_search_catalog", {"keywords": query, "type": "survey,document,table"})
    items = []
    for item in (result.get("items") or [])[:limit]:
        years = "-".join(sorted({y for y in [item.get("year_start"), item.get("year_end")] if y}))
        # Surveys have a public page on NISR's own catalogue; other items keep the link the server gave.
        url = PUBLIC_STUDY_PAGE + item["idno"] if item.get("type") == "survey" and item.get("idno") else item.get("url")
        items.append({"title": item.get("title"), "years": years, "type": item.get("type"),
                      "idno": item.get("idno"), "url": url,
                      "abstract": (item.get("abstract") or "")[:240]})
    return items
