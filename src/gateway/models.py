from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=32_000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=100)
    messages: list[Message]
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=16_384)

