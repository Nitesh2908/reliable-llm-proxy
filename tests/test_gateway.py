import httpx
import pytest

from gateway.app import create_app
from gateway.config import Settings


def settings(**overrides: object) -> Settings:
    values = {
        "upstream_api_key": "upstream-secret",
        "inbound_api_keys": frozenset({"client-secret"}),
        "allowed_models": frozenset({"test-model"}),
        "upstream_base_url": "https://llm.example/v1",
        "max_retries": 0,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_proxies_valid_request_without_leaking_upstream_key() -> None:
    async def upstream(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer upstream-secret"
        assert request.url == "https://llm.example/v1/chat/completions"
        return httpx.Response(200, json={"id": "chat-1", "choices": []})

    app = create_app(settings(), httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer client-secret", "X-Request-ID": "req-123"},
                json={"model": "test-model", "messages": [{"role": "user", "content": "hello"}]},
            )

    assert response.status_code == 200
    assert response.json()["id"] == "chat-1"
    assert response.headers["x-request-id"] == "req-123"


@pytest.mark.asyncio
async def test_requires_authentication() -> None:
    app = create_app(settings(), httpx.MockTransport(lambda _: httpx.Response(500)))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                json={"model": "test-model", "messages": [{"role": "user", "content": "hello"}]},
            )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rejects_disallowed_model_before_calling_upstream() -> None:
    called = False

    async def upstream(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    app = create_app(settings(), httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer client-secret"},
                json={
                    "model": "expensive-model",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
    assert response.status_code == 403
    assert called is False


@pytest.mark.asyncio
async def test_maps_bad_upstream_response_to_safe_error() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(500, text="secret provider detail"))
    app = create_app(settings(), transport)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer client-secret"},
                json={"model": "test-model", "messages": [{"role": "user", "content": "hello"}]},
            )
    assert response.status_code == 502
    assert "secret provider detail" not in response.text
