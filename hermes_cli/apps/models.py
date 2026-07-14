"""Strict domain models for the frozen App Manifest v1 contract."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SEMVER_PATTERN = (
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?"
    r"(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$"
)
APP_ID_PATTERN = r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*){2,}$"
ACTION_ID_PATTERN = r"^[a-z][a-z0-9._-]{0,63}$"
MCP_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
TOOL_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"
HANDLER_PATTERN = r"^[a-z][a-z0-9._-]*$"
ENTRY_PATTERN = r"^dist/[A-Za-z0-9._/-]+\.html$"
ICON_PATTERN = (
    r"^(icon\.(png|webp|jpg|jpeg)|"
    r"assets/[A-Za-z0-9._/-]+\.(png|webp|jpg|jpeg))$"
)
SOURCE_PATTERN = r"^source(/[A-Za-z0-9._/-]+)?$"
PROMPT_PATTERN = r"^prompts/[A-Za-z0-9._/-]+\.md$"
SCHEMA_PATH_PATTERN = r"^schemas/[A-Za-z0-9._/-]+\.json$"

Semver = Annotated[str, Field(pattern=SEMVER_PATTERN)]
SchemaPath = Annotated[str, Field(pattern=SCHEMA_PATH_PATTERN, max_length=512)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AppDisplay(StrictModel):
    theme: Literal["auto", "light", "dark"] = "auto"
    preferred_width: int | None = Field(default=None, ge=640, le=3840)
    preferred_height: int | None = Field(default=None, ge=480, le=2160)

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null_dimensions(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            for field in ("preferred_width", "preferred_height"):
                if field in value and value[field] is None:
                    raise ValueError(f"{field} cannot be null")
        return value


class StoragePermission(StrictModel):
    mode: Literal["none", "session", "persistent"]
    quota_mb: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_quota(self) -> "StoragePermission":
        if self.mode == "none" and self.quota_mb != 0:
            raise ValueError("quota_mb must be 0 when storage mode is none")
        if self.mode != "none" and self.quota_mb < 1:
            raise ValueError("quota_mb must be at least 1 when storage is enabled")
        return self


class AppPermissions(StrictModel):
    agent: bool
    mcp_servers: list[
        Annotated[str, Field(pattern=MCP_NAME_PATTERN, min_length=1, max_length=128)]
    ] = Field(max_length=32)
    storage: StoragePermission

    @field_validator("mcp_servers")
    @classmethod
    def validate_unique_servers(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("mcp_servers must not contain duplicates")
        return value


class AgentAction(StrictModel):
    kind: Literal["agent"]
    title: str = Field(min_length=1, max_length=80)
    prompt: str = Field(pattern=PROMPT_PATTERN, max_length=512)
    input_schema: SchemaPath
    output_schema: SchemaPath
    mode: Literal["stateless", "conversation"]
    toolsets: list[
        Annotated[str, Field(pattern=MCP_NAME_PATTERN, min_length=1, max_length=64)]
    ] = Field(max_length=16)
    timeout_seconds: int = Field(ge=5, le=300)
    max_iterations: int = Field(ge=1, le=30)
    max_concurrent_runs: int = Field(ge=1, le=4)
    cache_ttl_seconds: int = Field(ge=0, le=86400)

    @field_validator("toolsets")
    @classmethod
    def validate_unique_toolsets(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("toolsets must not contain duplicates")
        return value


class McpAction(StrictModel):
    kind: Literal["mcp"]
    title: str = Field(min_length=1, max_length=80)
    server: str = Field(
        pattern=MCP_NAME_PATTERN, min_length=1, max_length=128
    )
    tool: str = Field(pattern=TOOL_NAME_PATTERN, min_length=1, max_length=128)
    arguments_template: dict[str, Any]
    input_schema: SchemaPath
    output_schema: SchemaPath
    timeout_seconds: int = Field(ge=5, le=300)
    max_concurrent_runs: int = Field(ge=1, le=4)
    cache_ttl_seconds: int = Field(ge=0, le=86400)


class ServiceAction(StrictModel):
    kind: Literal["service"]
    title: str = Field(min_length=1, max_length=80)
    handler: str = Field(
        pattern=HANDLER_PATTERN, min_length=1, max_length=128
    )
    input_schema: SchemaPath
    output_schema: SchemaPath
    timeout_seconds: int = Field(ge=5, le=300)
    max_concurrent_runs: int = Field(ge=1, le=4)
    cache_ttl_seconds: int = Field(ge=0, le=86400)


AppAction = Annotated[
    AgentAction | McpAction | ServiceAction,
    Field(discriminator="kind"),
]


class AppManifest(StrictModel):
    schema_version: Literal[1]
    id: str = Field(pattern=APP_ID_PATTERN, min_length=5, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    version: Semver
    description: str = Field(min_length=1, max_length=500)
    entry: str = Field(pattern=ENTRY_PATTERN, max_length=512)
    icon: str = Field(pattern=ICON_PATTERN, max_length=512)
    source: str | None = Field(default=None, pattern=SOURCE_PATTERN, max_length=512)
    sdk_version: Semver
    min_runtime_version: Semver
    display: AppDisplay | None = None
    permissions: AppPermissions
    actions: dict[str, AppAction] = Field(min_length=1, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null_optionals(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            for field in ("source", "display"):
                if field in value and value[field] is None:
                    raise ValueError(f"{field} cannot be null")
        return value

    @field_validator("actions")
    @classmethod
    def validate_action_ids(cls, value: dict[str, AppAction]) -> dict[str, AppAction]:
        invalid = [
            action_id
            for action_id in value
            if not re.fullmatch(ACTION_ID_PATTERN, action_id)
        ]
        if invalid:
            raise ValueError(f"invalid action id: {invalid[0]}")
        return value

    def contract_dict(self) -> dict[str, Any]:
        """Return the JSON value represented by Manifest Schema v1."""
        return self.model_dump(mode="json", exclude_none=True)


AppLineage = Literal["user", "imported", "builtin"]


__all__ = [
    "AgentAction",
    "AppAction",
    "AppDisplay",
    "AppLineage",
    "AppManifest",
    "AppPermissions",
    "McpAction",
    "ServiceAction",
    "StoragePermission",
]
