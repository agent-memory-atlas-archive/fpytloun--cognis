"""Validated inference routing configuration and bounded recovery policy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecoveryPolicy(BaseModel):
    """One policy for direct and named inference; counts include adapter repairs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_retries_per_target: int = Field(default=3, ge=0, le=10)
    target_recovery_window_seconds: float = Field(default=30, gt=0, le=300)
    max_target_switches: int = Field(default=8, ge=0, le=15)
    request_timeout_seconds: float = Field(default=600, gt=0, le=3600)
    failure_threshold: int = Field(default=3, ge=1, le=100)
    failure_window_seconds: float = Field(default=60, ge=1, le=3600)
    cooldown_seconds: float = Field(default=30, ge=1, le=3600)


class RouteTarget(BaseModel):
    """A concrete candidate; provider credentials never belong to a route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=512)
    priority: int = Field(default=0, ge=0, le=1000)

    @property
    def reference(self) -> str:
        return f"{self.provider_id}/{self.model}"


class NamedRouteConfig(BaseModel):
    """Small route definition; equal priorities balance new sessions only."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
    targets: list[RouteTarget] = Field(min_length=1, max_length=16)
    recovery: RecoveryPolicy = Field(default_factory=RecoveryPolicy)

    @model_validator(mode="after")
    def unique_targets(self) -> NamedRouteConfig:
        keys = [(target.provider_id, target.model) for target in self.targets]
        if len(keys) != len(set(keys)):
            raise ValueError("A route cannot contain duplicate provider/model targets")
        if any(target.provider_id == "cognis" for target in self.targets):
            raise ValueError("Named routes can reference only concrete providers")
        return self
