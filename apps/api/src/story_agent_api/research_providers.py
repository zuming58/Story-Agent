from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


class ResearchProviderError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ResearchSourcePolicyError(ResearchProviderError):
    pass


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str = ""
    published_at: datetime | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    domain: str = ""
    source_type: str = "other"
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResponse:
    results: list[SearchResult]
    request_units: float = 0.0
    estimated_cost: float = 0.0
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchResponse:
    requested_url: str
    final_url: str
    title: str
    content: str
    summary: str = ""
    published_at: datetime | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    truncated: bool = False
    request_units: float = 0.0
    estimated_cost: float = 0.0
    provider_metadata: dict[str, Any] = field(default_factory=dict)


class SearchProvider(Protocol):
    name: str

    def search(
        self,
        query: str,
        domains: list[str],
        date_range: dict[str, str] | None,
        limit: int,
    ) -> SearchResponse:
        ...


class ContentFetchProvider(Protocol):
    name: str

    def fetch(self, url: str, max_chars: int) -> FetchResponse:
        ...


class ResearchSourcePolicy:
    def __init__(self, *, resolver: Any = socket.getaddrinfo):
        self._resolver = resolver

    @staticmethod
    def canonicalize_url(url: str) -> str:
        raw = (url or "").strip()
        parts = urlsplit(raw)
        scheme = parts.scheme.lower()
        if scheme not in {"http", "https"}:
            raise ResearchSourcePolicyError("SSRF_SCHEME_BLOCKED", "Only public HTTP(S) sources are allowed.")
        if not parts.hostname or parts.username or parts.password:
            raise ResearchSourcePolicyError("SSRF_HOST_BLOCKED", "The source URL has an invalid public host.")
        host = parts.hostname.lower().rstrip(".")
        try:
            port = parts.port
        except ValueError as exc:
            raise ResearchSourcePolicyError("SSRF_PORT_INVALID", "The source URL has an invalid port.") from exc
        default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
        netloc = host if port is None or default_port else f"{host}:{port}"
        path = parts.path or "/"
        return urlunsplit((scheme, netloc, path, parts.query, ""))

    def validate_url(self, url: str) -> str:
        canonical = self.canonicalize_url(url)
        host = urlsplit(canonical).hostname
        assert host
        if host == "localhost" or host.endswith(".localhost"):
            raise ResearchSourcePolicyError("SSRF_HOST_BLOCKED", "Localhost sources are not allowed.")
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            try:
                records = self._resolver(host, None, type=socket.SOCK_STREAM)
            except OSError as exc:
                raise ResearchSourcePolicyError("SOURCE_DNS_FAILED", "The source host could not be resolved.", retryable=True) from exc
            addresses = []
            for record in records:
                try:
                    addresses.append(ipaddress.ip_address(record[4][0]))
                except (IndexError, ValueError):
                    continue
            if not addresses:
                raise ResearchSourcePolicyError("SOURCE_DNS_FAILED", "The source host returned no usable address.", retryable=True)
        if any(not self._is_public(address) for address in addresses):
            raise ResearchSourcePolicyError("SSRF_ADDRESS_BLOCKED", "The source host resolves to a non-public address.")
        return canonical

    @staticmethod
    def _is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return bool(address.is_global) and not any(
            (
                address.is_private,
                address.is_loopback,
                address.is_link_local,
                address.is_multicast,
                address.is_reserved,
                address.is_unspecified,
            )
        )


class DeterministicSearchProvider:
    name = "deterministic-search"

    def __init__(self, fixtures: dict[str, list[SearchResult | dict[str, Any]]] | None = None):
        self.fixtures = fixtures or {}
        self.calls: list[dict[str, Any]] = []

    def search(self, query: str, domains: list[str], date_range: dict[str, str] | None, limit: int) -> SearchResponse:
        self.calls.append({"query": query, "domains": list(domains), "dateRange": date_range, "limit": limit})
        raw_items = self.fixtures.get(query, [])[:limit]
        results = [item if isinstance(item, SearchResult) else SearchResult(**item) for item in raw_items]
        return SearchResponse(results=results, request_units=1.0 if results else 0.0, provider_metadata={"fixture": True})


class DeterministicContentFetchProvider:
    name = "deterministic-fetch"

    def __init__(self, fixtures: dict[str, FetchResponse | dict[str, Any]] | None = None):
        self.fixtures = fixtures or {}
        self.calls: list[dict[str, Any]] = []

    def fetch(self, url: str, max_chars: int) -> FetchResponse:
        self.calls.append({"url": url, "maxChars": max_chars})
        if url not in self.fixtures:
            raise ResearchProviderError("SOURCE_NOT_IN_FIXTURE", "No deterministic source fixture exists for this URL.")
        raw = self.fixtures[url]
        response = raw if isinstance(raw, FetchResponse) else FetchResponse(**raw)
        content = response.content[:max_chars]
        return FetchResponse(
            requested_url=response.requested_url,
            final_url=response.final_url,
            title=response.title,
            content=content,
            summary=response.summary[:2000],
            published_at=response.published_at,
            fetched_at=response.fetched_at,
            truncated=response.truncated or len(response.content) > max_chars,
            request_units=response.request_units,
            estimated_cost=response.estimated_cost,
            provider_metadata={**response.provider_metadata, "fixture": True},
        )


class TavilySearchProvider:
    name = "tavily"

    def __init__(self, api_key: str, *, timeout_seconds: int = 20, endpoint: str = "https://api.tavily.com/search", policy: ResearchSourcePolicy | None = None):
        if not api_key:
            raise ResearchProviderError("SEARCH_API_KEY_MISSING", "Tavily is not configured.")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._endpoint = endpoint
        self._policy = policy or ResearchSourcePolicy()

    def search(self, query: str, domains: list[str], date_range: dict[str, str] | None, limit: int) -> SearchResponse:
        payload: dict[str, Any] = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max(1, min(limit, 20)),
            "include_raw_content": False,
        }
        if domains:
            payload["include_domains"] = domains
        if date_range:
            payload.update({key: value for key, value in date_range.items() if key in {"start_date", "end_date"}})
        try:
            response = httpx.post(self._endpoint, json=payload, timeout=self._timeout_seconds)
            response.raise_for_status()
            body = response.json()
        except httpx.TimeoutException as exc:
            raise ResearchProviderError("SEARCH_TIMEOUT", "The search provider timed out.", retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                code, message = "SEARCH_AUTH_FAILED", "The search provider rejected the API key."
            elif status == 429:
                code, message = "SEARCH_RATE_LIMITED", "The search provider rate limited the request."
            else:
                code, message = "SEARCH_PROVIDER_FAILED", f"The search provider returned HTTP {status}."
            raise ResearchProviderError(code, message, retryable=status in {429, 500, 502, 503, 504}) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ResearchProviderError("SEARCH_PROVIDER_FAILED", "The search provider returned an invalid response.", retryable=True) from exc
        results: list[SearchResult] = []
        for raw in body.get("results", []) if isinstance(body, dict) else []:
            if not isinstance(raw, dict) or not raw.get("url"):
                continue
            try:
                url = self._policy.validate_url(str(raw["url"]))
            except ResearchSourcePolicyError:
                continue
            published_at = _parse_datetime(raw.get("published_date"))
            results.append(SearchResult(
                url=url,
                title=str(raw.get("title") or "")[:1000],
                snippet=str(raw.get("content") or "")[:2000],
                published_at=published_at,
                domain=urlsplit(url).hostname or "",
                provider_metadata={"score": raw.get("score")},
            ))
        return SearchResponse(results=results, request_units=1.0, provider_metadata={"responseTime": body.get("response_time") if isinstance(body, dict) else None})


class PublicHttpContentFetchProvider:
    name = "public-http"

    def __init__(self, *, timeout_seconds: int = 20, policy: ResearchSourcePolicy | None = None, max_redirects: int = 5):
        self._timeout_seconds = timeout_seconds
        self._policy = policy or ResearchSourcePolicy()
        self._max_redirects = max_redirects

    def fetch(self, url: str, max_chars: int) -> FetchResponse:
        current = self._policy.validate_url(url)
        try:
            with httpx.Client(timeout=self._timeout_seconds, follow_redirects=False, headers={"User-Agent": "StoryAgentResearch/1.0"}) as client:
                for _ in range(self._max_redirects + 1):
                    response = client.get(current)
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ResearchProviderError("SOURCE_REDIRECT_INVALID", "The source returned a redirect without a location.")
                        current = self._policy.validate_url(urljoin(current, location))
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if not any(kind in content_type for kind in ("text/", "application/json", "application/xhtml+xml")):
                        raise ResearchProviderError("SOURCE_CONTENT_TYPE_BLOCKED", "The source is not a supported public text page.")
                    text = response.text
                    bounded = text[:max_chars]
                    return FetchResponse(
                        requested_url=self._policy.canonicalize_url(url),
                        final_url=current,
                        title="",
                        content=bounded,
                        truncated=len(text) > max_chars,
                        request_units=1.0,
                        provider_metadata={"contentType": content_type[:160], "statusCode": response.status_code},
                    )
                raise ResearchProviderError("SOURCE_REDIRECT_LIMIT", "The source exceeded the redirect limit.")
        except httpx.TimeoutException as exc:
            raise ResearchProviderError("SOURCE_TIMEOUT", "The source fetch timed out.", retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            code = "SOURCE_RATE_LIMITED" if exc.response.status_code == 429 else "SOURCE_FETCH_FAILED"
            raise ResearchProviderError(code, "The public source could not be fetched.", retryable=exc.response.status_code in {429, 500, 502, 503, 504}) from exc
        except httpx.HTTPError as exc:
            raise ResearchProviderError("SOURCE_FETCH_FAILED", "The public source could not be fetched.", retryable=True) from exc


class FirecrawlContentFetchProvider:
    name = "firecrawl"

    def __init__(self, api_key: str, *, timeout_seconds: int = 30, endpoint: str = "https://api.firecrawl.dev/v1/scrape", policy: ResearchSourcePolicy | None = None):
        if not api_key:
            raise ResearchProviderError("FETCH_API_KEY_MISSING", "Firecrawl is not configured.")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._endpoint = endpoint
        self._policy = policy or ResearchSourcePolicy()

    def fetch(self, url: str, max_chars: int) -> FetchResponse:
        requested_url = self._policy.validate_url(url)
        try:
            response = httpx.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"url": requested_url, "formats": ["markdown"], "onlyMainContent": True},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.TimeoutException as exc:
            raise ResearchProviderError("SOURCE_TIMEOUT", "The extraction provider timed out.", retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            code = "SOURCE_RATE_LIMITED" if exc.response.status_code == 429 else "SOURCE_FETCH_FAILED"
            raise ResearchProviderError(code, "The extraction provider rejected the request.", retryable=exc.response.status_code in {429, 500, 502, 503, 504}) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ResearchProviderError("SOURCE_FETCH_FAILED", "The extraction provider returned an invalid response.", retryable=True) from exc
        data = body.get("data", body) if isinstance(body, dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
        final_url = self._policy.validate_url(str(metadata.get("sourceURL") or metadata.get("url") or requested_url))
        content = str(data.get("markdown") or "") if isinstance(data, dict) else ""
        return FetchResponse(
            requested_url=requested_url,
            final_url=final_url,
            title=str(metadata.get("title") or "")[:1000],
            content=content[:max_chars],
            summary=str(metadata.get("description") or "")[:2000],
            published_at=_parse_datetime(metadata.get("publishedTime")),
            truncated=len(content) > max_chars,
            request_units=1.0,
            provider_metadata={"statusCode": metadata.get("statusCode")},
        )


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
