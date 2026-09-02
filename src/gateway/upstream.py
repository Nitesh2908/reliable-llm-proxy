import asyncio
import logging
import random

import httpx

from gateway.config import Settings
from gateway.observability import Metrics

logger = logging.getLogger(__name__)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class UpstreamError(Exception):
    def __init__(self, status_code: int, detail: str, retryable: bool = False) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.retryable = retryable


class LLMClient:
    def __init__(self, client: httpx.AsyncClient, settings: Settings, metrics: Metrics) -> None:
        self.client = client
        self.settings = settings
        self.metrics = metrics

    async def create_chat_completion(self, payload: dict[str, object]) -> dict[str, object]:
        url = f"{str(self.settings.upstream_base_url).rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.upstream_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

        for attempt in range(self.settings.max_retries + 1):
            try:
                response = await self.client.post(url, headers=headers, json=payload)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == self.settings.max_retries:
                    raise UpstreamError(503, "upstream temporarily unavailable", True) from exc
                await self._backoff(attempt)
                continue

            if response.status_code in RETRYABLE_STATUS and attempt < self.settings.max_retries:
                await self._backoff(attempt)
                continue
            if response.is_error:
                # Do not reflect upstream bodies: they may contain sensitive details.
                mapped = 429 if response.status_code == 429 else 502
                raise UpstreamError(mapped, "upstream rejected the request")
            try:
                return response.json()
            except ValueError as exc:
                raise UpstreamError(502, "upstream returned invalid JSON") from exc

        raise AssertionError("retry loop exhausted")

    async def _backoff(self, attempt: int) -> None:
        self.metrics.upstream_retries += 1
        delay = min(0.25 * (2**attempt) + random.uniform(0, 0.1), 2.0)
        logger.warning("retrying upstream request", extra={"attempt": attempt + 1})
        await asyncio.sleep(delay)

