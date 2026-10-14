"""Fixed Jin10 MCP endpoint; bounded responses and private connection diagnostics."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from jsonschema import validate
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from information_agent.config import settings

ENDPOINT = "https://mcp.jin10.com/mcp"
TOOLS = {"list_flash", "search_flash", "list_news", "search_news", "get_news"}
MAX_BYTES = 1_000_000


def configured() -> bool:
    return bool(settings.jin10_mcp_token.get_secret_value().strip())


class BoundedStream(httpx.AsyncByteStream):
    def __init__(self, inner):
        self.inner = inner

    async def __aiter__(self):
        size = 0
        async for chunk in self.inner:
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("jin10_response_limit")
            yield chunk

    async def aclose(self):
        await self.inner.aclose()


class BoundedTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request):
        if request.url.scheme != "https" or request.url.host != "mcp.jin10.com":
            raise ValueError("jin10_endpoint_boundary")
        response = await super().handle_async_request(request)
        response.stream = BoundedStream(response.stream)
        return response


def client_factory(headers=None, timeout=None, auth=None):
    return httpx.AsyncClient(headers=headers, timeout=timeout or httpx.Timeout(12), auth=auth,
                             follow_redirects=False, trust_env=False, transport=BoundedTransport(trust_env=False))


@asynccontextmanager
async def session():
    if not configured():
        raise ValueError("jin10_token_missing")
    async with streamablehttp_client(
        ENDPOINT, headers={"Authorization": "Bearer " + settings.jin10_mcp_token.get_secret_value().strip()},
        timeout=12, sse_read_timeout=15, httpx_client_factory=client_factory,
    ) as (read, write, _):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as active:
            await active.initialize()
            yield active


async def tool_catalog(active) -> dict:
    result = await active.list_tools()
    return {tool.name: tool.inputSchema for tool in result.tools[:100] if tool.name in TOOLS}


async def call_data(active, catalog: dict, name: str, arguments: dict) -> dict:
    if name not in TOOLS or name not in catalog:
        raise ValueError("jin10_tool_unavailable")
    validate(arguments, catalog[name])
    result = await active.call_tool(name, arguments)
    if result.isError:
        raise ValueError("jin10_tool_error")
    payload = result.structuredContent
    if payload is None:
        blocks = [block.text for block in result.content if block.type == "text"]
        if len(blocks) != 1:
            raise ValueError("jin10_result_format")
        payload = json.loads(blocks[0])
    if not isinstance(payload, dict) or payload.get("status") != 200 or not isinstance(payload.get("data"), dict):
        raise ValueError("jin10_result_format")
    return payload["data"]


def error_code(exc) -> str:
    # Do not return remote error messages, response bodies, headers or token values.
    if isinstance(exc, BaseExceptionGroup):
        codes = [error_code(child) for child in exc.exceptions]
        return next((code for code in codes if code.startswith("http_")), codes[0] if codes else "connection_error")
    if isinstance(exc, httpx.HTTPStatusError):
        return f"http_{exc.response.status_code}"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(exc, ValueError) and str(exc).startswith("jin10_") and len(str(exc)) < 50:
        return str(exc)
    return type(exc).__name__[:50]


async def probe() -> dict:
    if not configured():
        return {"status": "not_configured", "token_present": False, "tools": {}}

    async def connect():
        async with session() as active:
            return await tool_catalog(active)

    try:
        tools = await asyncio.wait_for(connect(), timeout=25)
        return {"status": "success", "token_present": True, "tools": tools}
    except Exception as exc:
        return {"status": "failure", "token_present": True, "error_type": error_code(exc), "tools": {}}
