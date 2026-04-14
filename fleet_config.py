"""
fleet_config.py — Fleet-wide Configuration Management

Manages YAML-based fleet configuration including agent roles, network topology,
secret scopes, model tiers, and backup/recovery settings for the Pelagic
SuperInstance fleet.
"""

from __future__ import annotations

import os
import copy
from dataclasses import dataclass, field
from typing import Any, Optional
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class AgentRole:
    """Role assignment for a single fleet agent."""

    name: str
    role: str = "worker"
    captain: bool = False
    co_captain: bool = False
    model_tier: str = "standard"
    secret_scope: list[str] = field(default_factory=lambda: ["global"])
    env_vars: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to plain dict for YAML dumping."""
        return {
            "name": self.name,
            "role": self.role,
            "captain": self.captain,
            "co_captain": self.co_captain,
            "model_tier": self.model_tier,
            "secret_scope": self.secret_scope,
            "env_vars": self.env_vars,
            "tags": self.tags,
            "dependencies": self.dependencies,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentRole:
        """Deserialize from a plain dict."""
        return cls(
            name=data.get("name", "unnamed"),
            role=data.get("role", "worker"),
            captain=data.get("captain", False),
            co_captain=data.get("co_captain", False),
            model_tier=data.get("model_tier", "standard"),
            secret_scope=data.get("secret_scope", ["global"]),
            env_vars=data.get("env_vars", {}),
            tags=data.get("tags", []),
            dependencies=data.get("dependencies", []),
        )


@dataclass
class NetworkTopology:
    """Describes the inter-agent communication topology."""

    mode: str = "mesh"  # mesh | star | ring | custom
    hub: Optional[str] = None  # agent name for star topology
    connections: list[dict[str, str]] = field(default_factory=list)
    ports: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "hub": self.hub,
            "connections": self.connections,
            "ports": self.ports,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NetworkTopology:
        return cls(
            mode=data.get("mode", "mesh"),
            hub=data.get("hub"),
            connections=data.get("connections", []),
            ports=data.get("ports", {}),
        )


@dataclass
class BackupSettings:
    """Backup and recovery configuration."""

    enabled: bool = True
    interval_hours: int = 24
    retention_days: int = 30
    backend: str = "local"
    remote_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "interval_hours": self.interval_hours,
            "retention_days": self.retention_days,
            "backend": self.backend,
            "remote_path": self.remote_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackupSettings:
        return cls(
            enabled=data.get("enabled", True),
            interval_hours=data.get("interval_hours", 24),
            retention_days=data.get("retention_days", 30),
            backend=data.get("backend", "local"),
            remote_path=data.get("remote_path"),
        )


@dataclass
class ModelTier:
    """Model tier definition."""

    name: str
    provider: str = "openai"
    model_id: str = "gpt-4"
    context_window: int = 128_000
    rpm_limit: int = 500
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "model_id": self.model_id,
            "context_window": self.context_window,
            "rpm_limit": self.rpm_limit,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelTier:
        return cls(
            name=data.get("name", "standard"),
            provider=data.get("provider", "openai"),
            model_id=data.get("model_id", "gpt-4"),
            context_window=data.get("context_window", 128_000),
            rpm_limit=data.get("rpm_limit", 500),
            priority=data.get("priority", 0),
        )


# ---------------------------------------------------------------------------
# FleetConfig
# ---------------------------------------------------------------------------

DEFAULT_FLEET_CONFIG: dict[str, Any] = {
    "version": "1.0.0",
    "fleet_name": "pelagic-default",
    "agents": [],
    "topology": {
        "mode": "star",
        "hub": "keeper",
        "connections": [],
        "ports": {},
    },
    "model_tiers": {
        "standard": {
            "provider": "openai",
            "model_id": "gpt-4",
            "context_window": 128000,
            "rpm_limit": 500,
            "priority": 0,
        },
        "premium": {
            "provider": "openai",
            "model_id": "gpt-4-turbo",
            "context_window": 128000,
            "rpm_limit": 1000,
            "priority": 1,
        },
    },
    "backup": {
        "enabled": True,
        "interval_hours": 24,
        "retention_days": 30,
        "backend": "local",
        "remote_path": None,
    },
    "secret_scopes": {
        "global": [],
        "captain": ["ADMIN_TOKEN", "FLEET_KEY"],
        "git": ["GITHUB_TOKEN", "GIT_SSH_KEY"],
    },
}


class FleetConfig:
    """YAML-based fleet configuration manager.

    Handles serialization, deserialization, validation, and manipulation of the
    fleet-wide configuration that governs all Pelagic SuperInstance agents.

    Attributes:
        path: Filesystem path to the YAML config file.
        data: Raw configuration dictionary.
        fleet_name: Human-readable fleet identifier.
        agents: List of :class:`AgentRole` entries.
        topology: Network topology descriptor.
        model_tiers: Mapping of tier name → :class:`ModelTier`.
        backup: Backup/recovery settings.
        secret_scopes: Mapping of scope name → list of secret keys.
    """

    def __init__(self, path: str | Path = "fleet.yaml") -> None:
        """Initialise FleetConfig, loading from *path* if it exists."""
        self.path = Path(path)
        self.data: dict[str, Any] = copy.deepcopy(DEFAULT_FLEET_CONFIG)
        self.fleet_name: str = self.data["fleet_name"]
        self.agents: list[AgentRole] = []
        self.topology: NetworkTopology = NetworkTopology.from_dict(self.data["topology"])
        self.model_tiers: dict[str, ModelTier] = {}
        self.backup: BackupSettings = BackupSettings.from_dict(self.data["backup"])
        self.secret_scopes: dict[str, list[str]] = dict(self.data.get("secret_scopes", {}))

        if self.path.exists():
            self.load()

    # ---- persistence ------------------------------------------------------

    def load(self) -> None:
        """Load configuration from the YAML file on disk."""
        with open(self.path, "r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}

        # Merge with defaults so new keys are always present
        merged = copy.deepcopy(DEFAULT_FLEET_CONFIG)
        merged.update(raw)
        self.data = merged

        self.fleet_name = self.data.get("fleet_name", "pelagic-default")
        self._parse_agents()
        self.topology = NetworkTopology.from_dict(self.data.get("topology", {}))
        self._parse_model_tiers()
        self.backup = BackupSettings.from_dict(self.data.get("backup", {}))
        self.secret_scopes = dict(self.data.get("secret_scopes", {}))

    def save(self) -> Path:
        """Persist the current configuration to disk.

        Returns:
            The path that was written to.
        """
        self._sync_to_data()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            yaml.dump(self.data, fh, default_flow_style=False, sort_keys=False)
        return self.path

    # ---- agent management -------------------------------------------------

    def add_agent(self, agent: AgentRole) -> None:
        """Register a new agent in the fleet configuration."""
        existing_names = {a.name for a in self.agents}
        if agent.name in existing_names:
            raise ValueError(f"Agent '{agent.name}' already exists in fleet config")
        self.agents.append(agent)
        self._assign_port(agent)
        self._sync_topology()

    def remove_agent(self, name: str) -> None:
        """Remove an agent by name."""
        before = len(self.agents)
        self.agents = [a for a in self.agents if a.name != name]
        if len(self.agents) == before:
            raise KeyError(f"Agent '{name}' not found in fleet config")
        self.topology.ports.pop(name, None)
        self._sync_topology()

    def get_agent(self, name: str) -> Optional[AgentRole]:
        """Look up an agent by name, or ``None`` if not found."""
        for agent in self.agents:
            if agent.name == name:
                return agent
        return None

    def set_captain(self, name: str) -> None:
        """Designate *name* as fleet captain, clearing prior captain."""
        for agent in self.agents:
            agent.captain = agent.name == name
        self.topology.hub = name

    def set_co_captain(self, name: str) -> None:
        """Designate *name* as fleet co-captain."""
        for agent in self.agents:
            agent.co_captain = agent.name == name

    # ---- validation -------------------------------------------------------

    def validate(self) -> list[str]:
        """Return a list of validation warnings/errors (empty ⇒ valid)."""
        issues: list[str] = []

        if not self.agents:
            issues.append("Fleet has no agents configured")

        captains = [a for a in self.agents if a.captain]
        if len(captains) > 1:
            issues.append(
                f"Multiple captains: {[a.name for a in captains]}"
            )

        names = [a.name for a in self.agents]
        dupes = [n for n in names if names.count(n) > 1]
        if dupes:
            issues.append(f"Duplicate agent names: {set(dupes)}")

        for agent in self.agents:
            for dep in agent.dependencies:
                if dep not in names:
                    issues.append(
                        f"Agent '{agent.name}' depends on unknown agent '{dep}'"
                    )

        for scope_name, keys in self.secret_scopes.items():
            if not isinstance(keys, list):
                issues.append(f"Secret scope '{scope_name}' is not a list")

        if self.topology.mode == "star" and not self.topology.hub:
            issues.append("Star topology requires a hub agent")

        return issues

    # ---- serialisation helpers --------------------------------------------

    def _parse_agents(self) -> None:
        self.agents = [
            AgentRole.from_dict(a) for a in self.data.get("agents", [])
        ]

    def _parse_model_tiers(self) -> None:
        self.model_tiers = {
            name: ModelTier.from_dict(cfg)
            for name, cfg in self.data.get("model_tiers", {}).items()
        }

    def _sync_to_data(self) -> None:
        """Push in-memory objects back into ``self.data`` for serialisation."""
        self.data["fleet_name"] = self.fleet_name
        self.data["agents"] = [a.to_dict() for a in self.agents]
        self.data["topology"] = self.topology.to_dict()
        self.data["model_tiers"] = {
            name: tier.to_dict() for name, tier in self.model_tiers.items()
        }
        self.data["backup"] = self.backup.to_dict()
        self.data["secret_scopes"] = self.secret_scopes

    def _sync_topology(self) -> None:
        """Rebuild topology connections based on current agent list."""
        names = [a.name for a in self.agents]
        connections: list[dict[str, str]] = []
        for i, src in enumerate(names):
            for j, dst in enumerate(names):
                if i < j:
                    connections.append({"from": src, "to": dst})
        self.topology.connections = connections

    def _assign_port(self, agent: AgentRole) -> None:
        """Auto-assign a port for the agent if not already assigned."""
        if agent.name not in self.topology.ports:
            base = 8000
            existing_ports = set(self.topology.ports.values())
            port = base + len(self.agents)
            while port in existing_ports:
                port += 1
            self.topology.ports[agent.name] = port

    # ---- dict / repr ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the full configuration as a plain dict."""
        self._sync_to_data()
        return copy.deepcopy(self.data)

    def __repr__(self) -> str:
        return (
            f"FleetConfig(fleet_name={self.fleet_name!r}, "
            f"agents={len(self.agents)}, topology={self.topology.mode!r})"
        )
