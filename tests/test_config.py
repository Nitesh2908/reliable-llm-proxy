import pytest
from pydantic import ValidationError

from gateway.config import Settings


def test_csv_configuration_is_parsed() -> None:
    config = Settings(
        upstream_api_key="secret",
        inbound_api_keys="a,b",
        allowed_models="small,large",
    )
    assert config.inbound_api_keys == frozenset({"a", "b"})
    assert config.allowed_models == frozenset({"small", "large"})


def test_invalid_timeout_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(upstream_api_key="secret", inbound_api_keys="a", request_timeout_seconds=0)
