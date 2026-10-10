"""Replaceable provider adapter; no raw user questions or private account data."""

import json
from typing import Protocol

import httpx

from information_agent.config import settings


class SearchProvider(Protocol):
    cache_namespace: str

    async def search(self, query: str, domains: list[str], *, topic: str = "general") -> list[dict]: ...


class TavilyProvider:
    cache_namespace = "tavily-basic-v3-12-results"

    async def search(self, query: str, domains: list[str], *, topic: str = "general") -> list[dict]:
        if topic not in {"general", "news"}:
            raise ValueError("unsupported_search_topic")
        payload = {
            "query": query,
            "topic": topic,
            "search_depth": "basic",
            "auto_parameters": False,
            "max_results": 12,
            "chunks_per_source": 1,
            "time_range": "month",
            "include_domains": domains,
            "exclude_domains": ["quote.eastmoney.com", "egs.stcn.com"],
            "include_domains_mode": "restrict",
            "include_published_date": True,
            # Keep undated candidates for approved publisher metadata recovery.
            # normalize_result still requires a date inside the last 30 days.
            "filter_by_published_date": False,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_usage": True,
        }
        content = bytearray()
        async with httpx.AsyncClient(timeout=12, follow_redirects=False, trust_env=False) as client:
            async with client.stream(
                "POST",
                "https://api.tavily.com/search",
                json=payload,
                headers={"Authorization": "Bearer " + settings.tavily_api_key.get_secret_value()},
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > 128_000:
                        raise RuntimeError("search_response_limit")
                    content.extend(chunk)
        result = json.loads(content)
        if not isinstance(result, dict) or not isinstance(result.get("results"), list):
            raise RuntimeError("search_invalid_response")
        credits = result.get("usage", {}).get("credits", 1)
        if type(credits) is not int or credits != 1:
            # The fixed basic request must not silently change its cost contract.
            raise RuntimeError("search_credit_contract")
        return result["results"][:12]


def configured() -> bool:
    return settings.search_enabled and bool(settings.tavily_api_key.get_secret_value())


def provider() -> SearchProvider:
    # Add another implementation here without changing collection, memory or tools.
    return TavilyProvider()
