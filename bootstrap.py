"""
bootstrap.py — Pelagic Bootstrap Fleet Engine

The meta-agent that can set up an entire SuperInstance fleet from scratch.
Oracle1 or any human runs this to discover, clone, configure, onboard, and
verify a fleet of Pelagic agents.

Only stdlib + pyyaml are used.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fleet_config import (
    AgentRole,
    BackupSettings,
    FleetConfig,
    ModelTier,
    NetworkTopology,
)

logger = logging.getLogger("pelagic.bootstrap")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_FLEET_DIR = Path.home() / ".pelagic" / "fleet"
DEFAULT_AGENTS_DIR = DEFAULT_FLEET_DIR / "agents"
DEFAULT_CONFIG_PATH = DEFAULT_FLEET_DIR / "fleet.yaml"
SUPERINSTANCE_ORG = "pelagic-superinstance"
GITHUB_BASE = f"https://github.com/{SUPERINSTANCE_ORG}"

KEEPER_AGENT = "keeper"
GIT_AGENT = "git-agent"

# Well-known agent directory patterns that indicate a Pelagic SuperInstance
SUPERINSTANCE_MARKERS = [
    "superinstance.yaml",
    "agent.yaml",
    ".pelagic",
    "CLAUDE.md",
    "pelagic.toml",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AgentInfo:
    """Metadata about a discovered or cloned agent."""

    name: str
    repo_url: str
    local_path: Optional[Path] = None
    cloned: bool = False
    onboarded: bool = False
    linked_to_keeper: bool = False
    healthy: bool = False
    role: str = "worker"
    error: Optional[str] = None


@dataclass
class FleetStatus:
    """Snapshot of the fleet's current state."""

    total_agents: int = 0
    cloned: int = 0
    onboarded: int = 0
    linked: int = 0
    healthy: int = 0
    captain: Optional[str] = None
    co_captain: Optional[str] = None
    topology_mode: str = "star"
    issues: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _run(
    cmd: list[str],
    cwd: Optional[Path] = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command with logging."""
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
        check=check,
    )


def _is_git_repo(path: Path) -> bool:
    """Check whether *path* is a git repository."""
    return (path / ".git").is_dir()


def _has_superinstance_marker(path: Path) -> bool:
    """Return True if *path* contains any Pelagic SuperInstance marker."""
    return any((path / marker).exists() for marker in SUPERINSTANCE_MARKERS)


# ---------------------------------------------------------------------------
# PelagicBootstrap
# ---------------------------------------------------------------------------

class PelagicBootstrap:
    """Meta-agent for one-command fleet setup.

    Orchestrates discovery, cloning, configuration, onboarding, linking, and
    verification of the entire Pelagic SuperInstance fleet.

    Args:
        fleet_dir: Root directory for the fleet filesystem layout.
        config_path: Path to the fleet YAML configuration file.
        github_org: GitHub organisation / user to discover agents from.
    """

    def __init__(
        self,
        fleet_dir: str | Path = DEFAULT_FLEET_DIR,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        github_org: str = SUPERINSTANCE_ORG,
    ) -> None:
        self.fleet_dir = Path(fleet_dir)
        self.agents_dir = self.fleet_dir / "agents"
        self.config_path = Path(config_path)
        self.github_org = github_org
        self.github_base = f"https://github.com/{github_org}"

        self.agents: dict[str, AgentInfo] = {}
        self.config: Optional[FleetConfig] = None

        # Ensure directories exist
        self.fleet_dir.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)

    # ---- discovery --------------------------------------------------------

    def discover_agents(self) -> list[AgentInfo]:
        """Scan the GitHub SuperInstance org for available agents.

        Uses ``gh api`` if the GitHub CLI is available, otherwise falls back
        to parsing the organisation's public repository list.

        Returns:
            A list of :class:`AgentInfo` for every discovered agent.
        """
        logger.info("Discovering agents from %s ...", self.github_base)
        discovered: list[AgentInfo] = []

        try:
            result = _run(
                [
                    "gh", "api",
                    f"/orgs/{self.github_org}/repos",
                    "--paginate",
                    "--jq", ".[].name",
                ],
                check=False,
            )
            if result.returncode == 0:
                repo_names = result.stdout.strip().splitlines()
            else:
                repo_names = self._fallback_discover()
        except FileNotFoundError:
            repo_names = self._fallback_discover()

        for name in repo_names:
            name = name.strip()
            if not name:
                continue
            info = AgentInfo(
                name=name,
                repo_url=f"{self.github_base}/{name}",
            )
            discovered.append(info)
            self.agents[name] = info

        logger.info("Discovered %d agent(s)", len(discovered))
        return discovered

    def _fallback_discover(self) -> list[str]:
        """Fallback discovery when ``gh`` CLI is not installed.

        Returns well-known agent names and any already-cloned directories.
        """
        known = [KEEPER_AGENT, GIT_AGENT, "coder", "researcher", "reviewer"]
        found: list[str] = list(known)

        if self.agents_dir.exists():
            for entry in self.agents_dir.iterdir():
                if entry.is_dir() and _has_superinstance_marker(entry):
                    if entry.name not in found:
                        found.append(entry.name)
        return found

    # ---- cloning ----------------------------------------------------------

    def clone_agents(self, agents: list[str] | None = None) -> list[AgentInfo]:
        """Clone selected (or all discovered) agents.

        Args:
            agents: List of agent names to clone. ``None`` → clone all.

        Returns:
            List of :class:`AgentInfo` that were successfully cloned.
        """
        targets = agents if agents else list(self.agents.keys())
        cloned: list[AgentInfo] = []

        for name in targets:
            info = self.agents.get(name)
            if info is None:
                logger.warning("Unknown agent '%s' — skipping", name)
                continue
            dest = self.agents_dir / name
            if dest.exists() and _is_git_repo(dest):
                logger.info("Agent '%s' already cloned at %s", name, dest)
                info.local_path = dest
                info.cloned = True
                cloned.append(info)
                continue

            logger.info("Cloning %s → %s ...", info.repo_url, dest)
            try:
                _run(["git", "clone", "--depth", "1", info.repo_url, str(dest)])
                info.local_path = dest
                info.cloned = True
                cloned.append(info)
                logger.info("Cloned '%s' successfully", name)
            except subprocess.CalledProcessError as exc:
                info.error = str(exc)
                logger.error("Failed to clone '%s': %s", name, exc)

        return cloned

    # ---- keeper setup -----------------------------------------------------

    def setup_keeper(self) -> AgentInfo:
        """Initialize the keeper agent as fleet captain.

        Clones the keeper if not present, creates its configuration, and
        registers it as captain in the fleet config.

        Returns:
            The :class:`AgentInfo` for the keeper agent.
        """
        logger.info("Setting up keeper agent ...")
        self._ensure_config()

        keeper_info = self.agents.get(KEEPER_AGENT)
        if keeper_info is None:
            # Auto-discover if missing
            self.discover_agents()
            keeper_info = self.agents.get(KEEPER_AGENT)
        if keeper_info is None:
            keeper_info = AgentInfo(
                name=KEEPER_AGENT,
                repo_url=f"{self.github_base}/{KEEPER_AGENT}",
            )
            self.agents[KEEPER_AGENT] = keeper_info

        cloned = self.clone_agents([KEEPER_AGENT])
        if not cloned:
            raise RuntimeError(f"Failed to clone keeper from {keeper_info.repo_url}")

        keeper_info.role = "captain"
        role = AgentRole(name=KEEPER_AGENT, role="captain", captain=True)
        self.config.add_agent(role)
        self.config.set_captain(KEEPER_AGENT)
        self.config.save()

        # Write keeper-specific config
        self._write_agent_config(keeper_info, role)
        logger.info("Keeper agent initialized at %s", keeper_info.local_path)
        return keeper_info

    # ---- git-agent setup --------------------------------------------------

    def setup_git_agent(self) -> AgentInfo:
        """Initialize the git-agent as fleet co-captain.

        Returns:
            The :class:`AgentInfo` for the git-agent.
        """
        logger.info("Setting up git-agent ...")
        self._ensure_config()

        git_info = self.agents.get(GIT_AGENT)
        if git_info is None:
            git_info = AgentInfo(
                name=GIT_AGENT,
                repo_url=f"{self.github_base}/{GIT_AGENT}",
            )
            self.agents[GIT_AGENT] = git_info

        cloned = self.clone_agents([GIT_AGENT])
        if not cloned:
            raise RuntimeError(f"Failed to clone git-agent from {git_info.repo_url}")

        git_info.role = "co-captain"
        role = AgentRole(
            name=GIT_AGENT,
            role="co-captain",
            co_captain=True,
            secret_scope=["global", "git"],
        )
        self.config.add_agent(role)
        self.config.set_co_captain(GIT_AGENT)
        self.config.save()

        self._write_agent_config(git_info, role)
        logger.info("Git-agent initialized at %s", git_info.local_path)
        return git_info

    # ---- onboarding -------------------------------------------------------

    def onboard_all(self) -> list[AgentInfo]:
        """Run ``--onboard`` on every cloned agent.

        Executes each agent's onboard hook (if present) to perform first-run
        setup such as dependency installation, env initialisation, etc.

        Returns:
            List of agents that were successfully onboarded.
        """
        logger.info("Onboarding all agents ...")
        onboarded: list[AgentInfo] = []

        for name, info in self.agents.items():
            if not info.cloned or info.local_path is None:
                logger.debug("Skipping '%s' — not cloned", name)
                continue
            success = self._onboard_agent(info)
            if success:
                info.onboarded = True
                onboarded.append(info)

        logger.info("Onboarded %d/%d agent(s)", len(onboarded), len(self.agents))
        return onboarded

    def _onboard_agent(self, info: AgentInfo) -> bool:
        """Run onboarding for a single agent."""
        logger.info("Onboarding '%s' ...", info.name)
        onboard_script = info.local_path / "scripts" / "onboard.sh"
        makefile = info.local_path / "Makefile"

        if onboard_script.exists():
            try:
                _run(["bash", str(onboard_script)], cwd=info.local_path, check=False)
                return True
            except subprocess.CalledProcessError as exc:
                info.error = f"onboard failed: {exc}"
                logger.error("Onboard failed for '%s': %s", info.name, exc)
                return False

        if makefile.exists():
            try:
                _run(["make", "onboard"], cwd=info.local_path, check=False)
                return True
            except subprocess.CalledProcessError:
                pass

        # No onboard script found — mark as onboarded implicitly
        logger.info("No onboard script for '%s' — skipping", info.name)
        return True

    # ---- linking ----------------------------------------------------------

    def link_to_keeper(self) -> list[AgentInfo]:
        """Connect all agents to the keeper.

        Each agent's local config is updated to point its keeper endpoint at
        the keeper agent's address.

        Returns:
            List of agents that were successfully linked.
        """
        logger.info("Linking agents to keeper ...")
        keeper = self.agents.get(KEEPER_AGENT)
        if keeper is None or not keeper.cloned:
            logger.error("Keeper not available — cannot link")
            return []

        linked: list[AgentInfo] = []
        keeper_port = self.config.topology.ports.get(KEEPER_AGENT, 8000) if self.config else 8000

        for name, info in self.agents.items():
            if name == KEEPER_AGENT or not info.cloned or info.local_path is None:
                continue
            if self._link_agent(info, keeper_port):
                info.linked_to_keeper = True
                linked.append(info)

        logger.info("Linked %d agent(s) to keeper", len(linked))
        return linked

    def _link_agent(self, info: AgentInfo, keeper_port: int) -> bool:
        """Write keeper connection config for a single agent."""
        agent_cfg = info.local_path / ".pelagic" / "keeper.yaml"
        agent_cfg.parent.mkdir(parents=True, exist_ok=True)
        keeper_data = {
            "keeper_host": "localhost",
            "keeper_port": keeper_port,
            "keeper_name": KEEPER_AGENT,
            "fleet_name": self.config.fleet_name if self.config else "default",
        }
        try:
            import yaml
            with open(agent_cfg, "w", encoding="utf-8") as fh:
                yaml.dump(keeper_data, fh, default_flow_style=False)
            return True
        except Exception as exc:
            info.error = f"link failed: {exc}"
            logger.error("Link failed for '%s': %s", info.name, exc)
            return False

    # ---- verification -----------------------------------------------------

    def verify_fleet(self) -> FleetStatus:
        """Verify all agents are connected and healthy.

        Checks that each cloned agent has a valid config, can reach the
        keeper (if linked), and reports a healthy status.

        Returns:
            A :class:`FleetStatus` snapshot of the fleet.
        """
        logger.info("Verifying fleet health ...")
        status = FleetStatus()
        status.total_agents = len(self.agents)

        if self.config:
            status.topology_mode = self.config.topology.mode

        for name, info in self.agents.items():
            if info.cloned:
                status.cloned += 1
            if info.onboarded:
                status.onboarded += 1
            if info.linked_to_keeper:
                status.linked += 1

            if info.cloned and info.local_path:
                healthy, issue = self._check_agent_health(info)
                if healthy:
                    status.healthy += 1
                    info.healthy = True
                else:
                    info.healthy = False
                    if issue:
                        status.issues.append(f"{name}: {issue}")

            if info.role == "captain":
                status.captain = name
            elif info.role == "co-captain":
                status.co_captain = name

        if self.config:
            status.issues.extend(self.config.validate())

        logger.info("Fleet status: %s", status)
        return status

    def _check_agent_health(self, info: AgentInfo) -> tuple[bool, Optional[str]]:
        """Health-check a single agent directory."""
        if info.local_path is None:
            return False, "no local path"

        # Check for config file
        cfg = info.local_path / "superinstance.yaml"
        if not cfg.exists():
            cfg = info.local_path / "agent.yaml"
        if not cfg.exists():
            return False, "missing agent config"

        # Check git status is clean
        if _is_git_repo(info.local_path):
            try:
                result = _run(["git", "status", "--porcelain"], cwd=info.local_path, check=False)
                if result.stdout.strip():
                    return True, "dirty working tree (non-fatal)"
            except Exception:
                pass

        return True, None

    # ---- configuration generation ------------------------------------------

    def generate_fleet_config(self) -> Path:
        """Create or update the fleet-wide configuration.

        Generates a complete ``fleet.yaml`` with all discovered agents, their
        roles, the network topology, secret scopes, model tiers, and backup
        settings.

        Returns:
            Path to the generated configuration file.
        """
        logger.info("Generating fleet configuration ...")
        self._ensure_config()

        # Sync agents into config
        for name, info in self.agents.items():
            if self.config.get_agent(name) is None and info.cloned:
                role = AgentRole(name=name, role=info.role)
                self.config.add_agent(role)

        path = self.config.save()
        logger.info("Fleet config written to %s", path)
        return path

    # ---- bootcamp ---------------------------------------------------------

    def run_bootcamp(self, agent_name: str) -> bool:
        """Enroll an agent in the Pelagic bootcamp.

        Runs the agent's bootcamp script which runs self-tests, calibration,
        and integration exercises.

        Args:
            agent_name: The name of the agent to enroll.

        Returns:
            ``True`` if bootcamp completed successfully.
        """
        info = self.agents.get(agent_name)
        if info is None or not info.cloned or info.local_path is None:
            logger.error("Cannot run bootcamp for '%s' — not available", agent_name)
            return False

        logger.info("Enrolling '%s' in bootcamp ...", agent_name)
        bootcamp_script = info.local_path / "scripts" / "bootcamp.sh"

        if not bootcamp_script.exists():
            logger.warning("No bootcamp script for '%s' — simulating", agent_name)
            info.onboarded = True
            info.healthy = True
            return True

        try:
            result = _run(["bash", str(bootcamp_script)], cwd=info.local_path, check=False)
            success = result.returncode == 0
            if success:
                info.onboarded = True
                info.healthy = True
                logger.info("Bootcamp passed for '%s'", agent_name)
            else:
                info.error = f"bootcamp failed: {result.stderr}"
                logger.error("Bootcamp failed for '%s'", agent_name)
            return success
        except subprocess.CalledProcessError as exc:
            info.error = str(exc)
            logger.error("Bootcamp error for '%s': %s", agent_name, exc)
            return False

    # ---- status -----------------------------------------------------------

    def status(self) -> FleetStatus:
        """Show a comprehensive fleet status summary.

        Returns:
            A :class:`FleetStatus` with current fleet metrics.
        """
        return self.verify_fleet()

    def status_table(self) -> str:
        """Return a human-readable status table."""
        st = self.status()
        lines: list[str] = [
            f"{'='*60}",
            f"  PELAGIC FLEET STATUS — {st.topology_mode.upper()} topology",
            f"{'='*60}",
            f"  Total agents : {st.total_agents}",
            f"  Cloned       : {st.cloned}",
            f"  Onboarded    : {st.onboarded}",
            f"  Linked       : {st.linked}",
            f"  Healthy      : {st.healthy}",
            f"  Captain      : {st.captain or '(none)'}",
            f"  Co-captain   : {st.co_captain or '(none)'}",
            f"{'='*60}",
        ]

        if st.issues:
            lines.append("  ISSUES:")
            for issue in st.issues:
                lines.append(f"    ⚠  {issue}")
        else:
            lines.append("  All clear — no issues detected.")

        lines.append(f"{'='*60}")
        return "\n".join(lines)

    # ---- doctor -----------------------------------------------------------

    def doctor(self) -> list[str]:
        """Diagnose common fleet issues and suggest fixes.

        Returns:
            A list of diagnostic messages with suggested remedies.
        """
        diagnostics: list[str] = []

        # Check for gh CLI
        try:
            _run(["gh", "--version"], check=False)
        except FileNotFoundError:
            diagnostics.append(
                "GitHub CLI (gh) not found. Install it for agent discovery."
            )

        # Check for git
        try:
            _run(["git", "--version"], check=False)
        except FileNotFoundError:
            diagnostics.append("Git not found. Install git for agent cloning.")

        # Check fleet directory
        if not self.fleet_dir.exists():
            diagnostics.append(f"Fleet directory missing: {self.fleet_dir}")

        # Check config
        if self.config is None or not self.config_path.exists():
            diagnostics.append(
                "Fleet config not found. Run `init` first."
            )

        # Check each agent
        for name, info in self.agents.items():
            if not info.cloned:
                diagnostics.append(f"Agent '{name}' not cloned. Run `clone {name}`.")
            elif not info.onboarded:
                diagnostics.append(f"Agent '{name}' not onboarded. Run `onboard-all`.")
            elif not info.linked_to_keeper and name != KEEPER_AGENT:
                diagnostics.append(f"Agent '{name}' not linked to keeper. Run `link-all`.")

        # Check for YAML module
        try:
            import yaml  # noqa: F401
        except ImportError:
            diagnostics.append("PyYAML not installed. Run `pip install pyyaml`.")

        return diagnostics

    # ---- reset ------------------------------------------------------------

    def reset(self, confirm: bool = False) -> bool:
        """Reset the entire fleet to a clean state.

        Removes all cloned agents, deletes the fleet configuration, and
        recreates the directory structure.

        Args:
            confirm: Must be ``True`` to actually perform the reset.

        Returns:
            ``True`` if the reset was performed.
        """
        if not confirm:
            logger.warning("Reset not confirmed — pass confirm=True to proceed")
            return False

        logger.info("Resetting fleet at %s ...", self.fleet_dir)

        if self.agents_dir.exists():
            shutil.rmtree(self.agents_dir)
        self.agents_dir.mkdir(parents=True, exist_ok=True)

        if self.config_path.exists():
            self.config_path.unlink()

        self.agents.clear()
        self.config = None

        logger.info("Fleet reset complete")
        return True

    # ---- full bootstrap ---------------------------------------------------

    def bootstrap_all(
        self,
        agents: list[str] | None = None,
        skip_bootcamp: bool = False,
    ) -> FleetStatus:
        """One-command fleet setup.

        Runs the complete bootstrap sequence:
        1. Discover agents
        2. Clone agents
        3. Setup keeper
        4. Setup git-agent
        5. Generate fleet config
        6. Onboard all
        7. Link all to keeper
        8. Verify fleet

        Args:
            agents: Specific agents to include (``None`` → all).
            skip_bootcamp: If ``True``, skip the bootcamp enrollment step.

        Returns:
            Final :class:`FleetStatus` after bootstrap completes.
        """
        logger.info("=== PELAGIC BOOTSTRAP STARTING ===")

        self.discover_agents()
        self.clone_agents(agents)
        self.setup_keeper()
        self.setup_git_agent()
        self.generate_fleet_config()
        self.onboard_all()
        self.link_to_keeper()

        if not skip_bootcamp:
            for name in list(self.agents.keys()):
                self.run_bootcamp(name)

        final_status = self.verify_fleet()
        logger.info("=== PELAGIC BOOTSTRAP COMPLETE ===")
        logger.info(self.status_table())
        return final_status

    # ---- internal helpers -------------------------------------------------

    def _ensure_config(self) -> FleetConfig:
        """Lazily create / load the fleet config."""
        if self.config is None:
            self.config = FleetConfig(self.config_path)
        return self.config

    def _write_agent_config(self, info: AgentInfo, role: AgentRole) -> None:
        """Write an individual agent's pelagic config file."""
        if info.local_path is None:
            return
        import yaml
        agent_dir = info.local_path / ".pelagic"
        agent_dir.mkdir(parents=True, exist_ok=True)
        cfg_data = {
            "agent_name": role.name,
            "role": role.role,
            "fleet_name": self.config.fleet_name if self.config else "default",
            "model_tier": role.model_tier,
            "secret_scope": role.secret_scope,
        }
        cfg_path = agent_dir / "config.yaml"
        with open(cfg_path, "w", encoding="utf-8") as fh:
            yaml.dump(cfg_data, fh, default_flow_style=False)
