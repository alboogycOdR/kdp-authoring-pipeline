from __future__ import annotations

import re
import ipaddress
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProviderProfileSettings(BaseModel):
    """Non-secret provider configuration suitable for SQLite and future UI DTOs."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str
    provider_type: Literal["fake", "openai-compatible"]
    display_name: str
    enabled: bool = True
    base_url: str | None = None
    model: str = Field(min_length=1)
    api_key_env: str | None = None
    default_max_output_tokens: int = Field(default=1200, gt=0)
    default_temperature: float | None = Field(default=0.0, ge=0, le=2)
    priority: int | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
            raise ValueError("provider_id must use only letters, digits, underscore, or hyphen")
        return value

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_env(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("api_key_env must be an environment variable name")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("base_url must be an absolute HTTP(S) URL without credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain a query string or fragment")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("HTTP is allowed only for loopback provider endpoints")
        return value

    @model_validator(mode="after")
    def validate_type_fields(self) -> "ProviderProfileSettings":
        if self.provider_type == "openai-compatible" and not self.base_url:
            self.base_url = "https://api.openai.com/v1"
        if self.provider_type == "fake":
            if self.api_key_env or self.base_url:
                raise ValueError("fake providers do not use base_url or api_key_env")
        elif self.api_key_env is None:
            host = urlparse(self.base_url or "").hostname or ""
            loopback = host == "localhost"
            try:
                loopback = loopback or ipaddress.ip_address(host).is_loopback
            except ValueError:
                pass
            if not loopback:
                self.api_key_env = "OPENAI_API_KEY"
        return self


class ProviderProfileView(ProviderProfileSettings):
    api_key_configured: bool = False
    selected_for_projects: list[str] = Field(default_factory=list)


class ProviderCheckResult(BaseModel):
    provider_id: str
    ready: bool
    connected: bool = False
    message: str
