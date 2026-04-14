"""
tests/test_bootstrap.py — Tests for Pelagic Bootstrap Agent

Unit tests for fleet_config.py, bootstrap.py, and cli.py using only stdlib
(unittest + tempfile).
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the project root is on sys.path so imports work
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fleet_config import (
    AgentRole,
    BackupSettings,
    FleetConfig,
    ModelTier,
    NetworkTopology,
)
from bootstrap import (
    AgentInfo,
    FleetStatus,
    PelagicBootstrap,
    _is_git_repo,
    _has_superinstance_marker,
)


class TestAgentRole(unittest.TestCase):
    """Tests for AgentRole data model."""

    def test_default_values(self) -> None:
        """AgentRole should have sensible defaults."""
        role = AgentRole(name="test-agent")
        self.assertEqual(role.name, "test-agent")
        self.assertEqual(role.role, "worker")
        self.assertFalse(role.captain)
        self.assertFalse(role.co_captain)
        self.assertEqual(role.model_tier, "standard")
        self.assertEqual(role.secret_scope, ["global"])

    def test_roundtrip_dict(self) -> None:
        """AgentRole should survive to_dict / from_dict roundtrip."""
        original = AgentRole(
            name="keeper",
            role="captain",
            captain=True,
            model_tier="premium",
            secret_scope=["global", "admin"],
            tags=["critical"],
            dependencies=["git-agent"],
        )
        restored = AgentRole.from_dict(original.to_dict())
        self.assertEqual(restored.name, "keeper")
        self.assertTrue(restored.captain)
        self.assertEqual(restored.model_tier, "premium")
        self.assertEqual(restored.secret_scope, ["global", "admin"])
        self.assertEqual(restored.tags, ["critical"])
        self.assertEqual(restored.dependencies, ["git-agent"])


class TestNetworkTopology(unittest.TestCase):
    """Tests for NetworkTopology data model."""

    def test_default_mesh(self) -> None:
        """Default topology should be mesh with no connections."""
        topo = NetworkTopology()
        self.assertEqual(topo.mode, "mesh")
        self.assertIsNone(topo.hub)
        self.assertEqual(topo.connections, [])

    def test_star_topology(self) -> None:
        """Star topology should accept a hub."""
        topo = NetworkTopology(mode="star", hub="keeper")
        self.assertEqual(topo.mode, "star")
        self.assertEqual(topo.hub, "keeper")

    def test_roundtrip_dict(self) -> None:
        """Topology should survive serialization roundtrip."""
        original = NetworkTopology(
            mode="star",
            hub="keeper",
            ports={"keeper": 8000, "git-agent": 8001},
        )
        restored = NetworkTopology.from_dict(original.to_dict())
        self.assertEqual(restored.mode, "star")
        self.assertEqual(restored.hub, "keeper")
        self.assertEqual(restored.ports["keeper"], 8000)


class TestBackupSettings(unittest.TestCase):
    """Tests for BackupSettings data model."""

    def test_defaults(self) -> None:
        """Backup settings should default to enabled with 24h interval."""
        backup = BackupSettings()
        self.assertTrue(backup.enabled)
        self.assertEqual(backup.interval_hours, 24)
        self.assertEqual(backup.retention_days, 30)
        self.assertEqual(backup.backend, "local")

    def test_roundtrip_dict(self) -> None:
        """BackupSettings should survive roundtrip."""
        original = BackupSettings(
            enabled=False,
            interval_hours=12,
            retention_days=7,
            backend="s3",
            remote_path="s3://backups/pelagic",
        )
        restored = BackupSettings.from_dict(original.to_dict())
        self.assertFalse(restored.enabled)
        self.assertEqual(restored.interval_hours, 12)
        self.assertEqual(restored.backend, "s3")


class TestModelTier(unittest.TestCase):
    """Tests for ModelTier data model."""

    def test_defaults(self) -> None:
        """Default model tier should use openai/gpt-4."""
        tier = ModelTier(name="standard")
        self.assertEqual(tier.provider, "openai")
        self.assertEqual(tier.model_id, "gpt-4")
        self.assertEqual(tier.context_window, 128_000)

    def test_roundtrip_dict(self) -> None:
        """ModelTier should survive roundtrip."""
        original = ModelTier(
            name="premium",
            provider="anthropic",
            model_id="claude-3-opus",
            context_window=200_000,
            rpm_limit=1000,
            priority=2,
        )
        restored = ModelTier.from_dict(original.to_dict())
        self.assertEqual(restored.provider, "anthropic")
        self.assertEqual(restored.model_id, "claude-3-opus")


class TestFleetConfig(unittest.TestCase):
    """Tests for FleetConfig YAML configuration manager."""

    def setUp(self) -> None:
        """Create a temporary directory for config files."""
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = Path(self.tmpdir) / "fleet.yaml"

    def tearDown(self) -> None:
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_new_config(self) -> None:
        """Creating a new config should produce a valid YAML file."""
        config = FleetConfig(self.config_path)
        config.fleet_name = "test-fleet"
        config.save()

        self.assertTrue(self.config_path.exists())
        config2 = FleetConfig(self.config_path)
        self.assertEqual(config2.fleet_name, "test-fleet")

    def test_add_and_remove_agent(self) -> None:
        """Adding and removing agents should update the config."""
        config = FleetConfig(self.config_path)
        agent = AgentRole(name="keeper", role="captain", captain=True)
        config.add_agent(agent)
        config.save()

        # Reload and verify
        config2 = FleetConfig(self.config_path)
        self.assertEqual(len(config2.agents), 1)
        self.assertEqual(config2.agents[0].name, "keeper")
        self.assertTrue(config2.agents[0].captain)

        # Remove
        config2.remove_agent("keeper")
        config2.save()

        config3 = FleetConfig(self.config_path)
        self.assertEqual(len(config3.agents), 0)

    def test_duplicate_agent_prevented(self) -> None:
        """Adding a duplicate agent should raise ValueError."""
        config = FleetConfig(self.config_path)
        config.add_agent(AgentRole(name="dup"))
        with self.assertRaises(ValueError):
            config.add_agent(AgentRole(name="dup"))

    def test_remove_nonexistent_agent(self) -> None:
        """Removing a nonexistent agent should raise KeyError."""
        config = FleetConfig(self.config_path)
        with self.assertRaises(KeyError):
            config.remove_agent("ghost")

    def test_set_captain(self) -> None:
        """Setting captain should update captain flags."""
        config = FleetConfig(self.config_path)
        config.add_agent(AgentRole(name="a", captain=True))
        config.add_agent(AgentRole(name="b"))

        config.set_captain("b")

        self.assertTrue(config.get_agent("b").captain)
        self.assertFalse(config.get_agent("a").captain)

    def test_validation_empty_fleet(self) -> None:
        """Empty fleet should produce a validation warning."""
        config = FleetConfig(self.config_path)
        issues = config.validate()
        self.assertTrue(any("no agents" in i.lower() for i in issues))

    def test_validation_duplicate_captains(self) -> None:
        """Multiple captains should be flagged."""
        config = FleetConfig(self.config_path)
        config.add_agent(AgentRole(name="a", captain=True))
        config.add_agent(AgentRole(name="b", captain=True))
        issues = config.validate()
        self.assertTrue(any("Multiple captains" in i for i in issues))

    def test_validation_unknown_dependency(self) -> None:
        """Unknown agent dependency should be flagged."""
        config = FleetConfig(self.config_path)
        config.add_agent(AgentRole(name="a", dependencies=["ghost"]))
        issues = config.validate()
        self.assertTrue(any("ghost" in i for i in issues))

    def test_star_topology_without_hub(self) -> None:
        """Star topology without hub should be flagged."""
        config = FleetConfig(self.config_path)
        config.topology.mode = "star"
        config.topology.hub = None
        issues = config.validate()
        self.assertTrue(any("hub" in i.lower() for i in issues))

    def test_port_auto_assignment(self) -> None:
        """Ports should be auto-assigned when adding agents."""
        config = FleetConfig(self.config_path)
        config.add_agent(AgentRole(name="a"))
        config.add_agent(AgentRole(name="b"))

        self.assertIn("a", config.topology.ports)
        self.assertIn("b", config.topology.ports)
        self.assertNotEqual(config.topology.ports["a"], config.topology.ports["b"])

    def test_to_dict(self) -> None:
        """to_dict should return a serialisable dictionary."""
        config = FleetConfig(self.config_path)
        config.add_agent(AgentRole(name="keeper", captain=True))
        d = config.to_dict()
        self.assertEqual(d["fleet_name"], "pelagic-default")
        self.assertEqual(len(d["agents"]), 1)

    def test_secret_scopes_persisted(self) -> None:
        """Secret scopes should survive save/load roundtrip."""
        config = FleetConfig(self.config_path)
        config.secret_scopes["custom"] = ["MY_SECRET"]
        config.save()

        config2 = FleetConfig(self.config_path)
        self.assertEqual(config2.secret_scopes["custom"], ["MY_SECRET"])

    def test_repr(self) -> None:
        """__repr__ should include fleet name and agent count."""
        config = FleetConfig(self.config_path)
        r = repr(config)
        self.assertIn("pelagic-default", r)
        self.assertIn("agents=0", r)


class TestHelperFunctions(unittest.TestCase):
    """Tests for bootstrap module helper functions."""

    def test_is_git_repo(self) -> None:
        """Should detect a .git directory."""
        with tempfile.TemporaryDirectory() as td:
            # Not a git repo
            self.assertFalse(_is_git_repo(Path(td)))
            # Make it a git repo
            (Path(td) / ".git").mkdir()
            self.assertTrue(_is_git_repo(Path(td)))

    def test_has_superinstance_marker(self) -> None:
        """Should detect SuperInstance marker files."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            self.assertFalse(_has_superinstance_marker(p))
            (p / "CLAUDE.md").write_text("# test")
            self.assertTrue(_has_superinstance_marker(p))


class TestPelagicBootstrap(unittest.TestCase):
    """Tests for the PelagicBootstrap engine."""

    def setUp(self) -> None:
        """Create isolated temp fleet directory."""
        self.tmpdir = tempfile.mkdtemp()
        self.fleet_dir = Path(self.tmpdir) / "fleet"
        self.config_path = Path(self.tmpdir) / "fleet.yaml"
        self.bs = PelagicBootstrap(
            fleet_dir=self.fleet_dir,
            config_path=self.config_path,
        )

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_initialization_creates_dirs(self) -> None:
        """Bootstrap should create fleet and agents directories."""
        self.assertTrue(self.fleet_dir.exists())
        self.assertTrue(self.bs.agents_dir.exists())

    def test_fallback_discover(self) -> None:
        """Fallback discovery should return well-known agents."""
        agents = self.bs._fallback_discover()
        self.assertIn("keeper", agents)
        self.assertIn("git-agent", agents)

    def test_fallback_discover_with_cloned(self) -> None:
        """Fallback should include cloned agents with markers."""
        marker_dir = self.bs.agents_dir / "custom-agent"
        marker_dir.mkdir(parents=True)
        (marker_dir / "CLAUDE.md").write_text("# custom agent")

        agents = self.bs._fallback_discover()
        self.assertIn("custom-agent", agents)

    def test_status_empty_fleet(self) -> None:
        """Status of an empty fleet should show zero counts."""
        status = self.bs.status()
        self.assertEqual(status.total_agents, 0)
        self.assertEqual(status.cloned, 0)
        self.assertEqual(status.healthy, 0)

    def test_status_table_output(self) -> None:
        """status_table should return a formatted string."""
        table = self.bs.status_table()
        self.assertIn("PELAGIC FLEET STATUS", table)
        self.assertIn("Total agents", table)

    def test_doctor_checks(self) -> None:
        """Doctor should produce diagnostic messages for empty fleet."""
        diags = self.bs.doctor()
        self.assertTrue(len(diags) > 0)
        # Should mention missing config
        self.assertTrue(any("config" in d.lower() for d in diags))

    def test_reset(self) -> None:
        """Reset should clear agents and config."""
        self.bs.agents["test"] = AgentInfo(name="test", repo_url="http://example.com")
        self.bs.reset(confirm=True)
        self.assertEqual(len(self.bs.agents), 0)
        self.assertIsNone(self.bs.config)

    def test_reset_without_confirm(self) -> None:
        """Reset without confirm should be a no-op."""
        self.bs.agents["test"] = AgentInfo(name="test", repo_url="http://example.com")
        result = self.bs.reset(confirm=False)
        self.assertFalse(result)
        self.assertIn("test", self.bs.agents)

    def test_generate_fleet_config(self) -> None:
        """generate_fleet_config should create a YAML file."""
        self.bs.agents["keeper"] = AgentInfo(
            name="keeper", repo_url="http://example.com", cloned=True
        )
        path = self.bs.generate_fleet_config()
        self.assertTrue(path.exists())

        config = FleetConfig(path)
        self.assertEqual(len(config.agents), 1)

    def test_add_agent_to_config(self) -> None:
        """Adding agents to bootstrap should register in config."""
        self.bs._ensure_config()
        info = AgentInfo(name="worker", repo_url="http://example.com", cloned=True)
        self.bs.agents["worker"] = info
        self.bs.generate_fleet_config()

        config = FleetConfig(self.config_path)
        agent = config.get_agent("worker")
        self.assertIsNotNone(agent)
        self.assertEqual(agent.role, "worker")

    def test_check_agent_health_missing_config(self) -> None:
        """Agent without config should report unhealthy."""
        with tempfile.TemporaryDirectory() as td:
            info = AgentInfo(name="broken", repo_url="http://x", local_path=Path(td))
            healthy, issue = self.bs._check_agent_health(info)
            self.assertFalse(healthy)
            self.assertIsNotNone(issue)

    def test_check_agent_health_with_config(self) -> None:
        """Agent with config should report healthy."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "superinstance.yaml").write_text("name: test\n")
            info = AgentInfo(name="good", repo_url="http://x", local_path=p)
            healthy, issue = self.bs._check_agent_health(info)
            self.assertTrue(healthy)


class TestCLI(unittest.TestCase):
    """Tests for the CLI argument parser."""

    def test_build_parser(self) -> None:
        """Parser should accept all subcommands."""
        from cli import build_parser

        parser = build_parser()

        # Each known command should be a valid subcommand
        for cmd in ["init", "discover", "clone", "setup-keeper", "onboard-all",
                     "link-all", "verify", "status", "doctor", "reset"]:
            args = parser.parse_args([cmd])
            self.assertEqual(args.command, cmd)

    def test_clone_with_agents(self) -> None:
        """clone command should accept agent names."""
        from cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["clone", "keeper", "git-agent"])
        self.assertEqual(args.command, "clone")
        self.assertEqual(args.agents, ["keeper", "git-agent"])
        self.assertFalse(args.all)

    def test_clone_all_flag(self) -> None:
        """clone --all should set the all flag."""
        from cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["clone", "--all"])
        self.assertTrue(args.all)

    def test_reset_yes_flag(self) -> None:
        """reset -y should set the yes flag."""
        from cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["reset", "-y"])
        self.assertTrue(args.yes)

    def test_no_command_shows_help(self) -> None:
        """Running with no command should not raise."""
        from cli import build_parser

        parser = build_parser()
        args = parser.parse_args([])
        self.assertIsNone(args.command)

    def test_main_returns_zero_for_no_command(self) -> None:
        """main() with no args should return 0."""
        from cli import main

        result = main([])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
