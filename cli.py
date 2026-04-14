"""
cli.py — Pelagic Bootstrap CLI

Command-line interface for the Pelagic Bootstrap Agent. Provides subcommands
for initializing, discovering, cloning, configuring, onboarding, linking,
verifying, and diagnosing the SuperInstance fleet.

Usage:
    python cli.py init              # Interactive fleet initialization
    python cli.py discover          # Discover available agents
    python cli.py clone keeper git-agent  # Clone specific agents
    python cli.py setup-keeper      # Initialize keeper as captain
    python cli.py onboard-all       # Onboard every cloned agent
    python cli.py link-all          # Link agents to keeper
    python cli.py verify            # Verify fleet health
    python cli.py status            # Show fleet status
    python cli.py doctor            # Diagnose fleet issues
    python cli.py reset             # Reset fleet (with confirmation)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from bootstrap import (
    DEFAULT_AGENTS_DIR,
    DEFAULT_CONFIG_PATH,
    DEFAULT_FLEET_DIR,
    PelagicBootstrap,
)


def _setup_logging(verbose: bool = False) -> None:
    """Configure the root logger for the bootstrap CLI."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _banner() -> str:
    return r"""
    ╔══════════════════════════════════════════════════╗
    ║       PELAGIC BOOTSTRAP AGENT v1.0.0            ║
    ║   One command to rule them all.                  ║
    ╚══════════════════════════════════════════════════╝
    """


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a new fleet interactively."""
    print(_banner())
    fleet_dir = args.fleet_dir or DEFAULT_FLEET_DIR
    config_path = args.config or DEFAULT_CONFIG_PATH

    print(f"Fleet directory : {fleet_dir}")
    print(f"Config path     : {config_path}")
    print()

    fleet_dir = Path(fleet_dir)
    if fleet_dir.exists() and any(fleet_dir.iterdir()):
        confirm = input("Fleet directory is not empty. Continue? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return 1

    fleet_dir.mkdir(parents=True, exist_ok=True)
    print(f"Created fleet directory: {fleet_dir}")

    bs = PelagicBootstrap(fleet_dir=fleet_dir, config_path=config_path)

    org = input(f"GitHub org [{bs.github_org}]: ").strip()
    if org:
        bs.github_org = org
        bs.github_base = f"https://github.com/{org}"

    fleet_name = input(f"Fleet name [pelagic-default]: ").strip() or "pelagic-default"
    bs._ensure_config()
    bs.config.fleet_name = fleet_name
    bs.config.save()

    print(f"\nFleet '{fleet_name}' initialized at {fleet_dir}")
    print("Next steps:")
    print(f"  1. python cli.py discover          # Find available agents")
    print(f"  2. python cli.py clone --all       # Clone all agents")
    print(f"  3. python cli.py setup-keeper      # Initialize keeper")
    print(f"  4. python cli.py onboard-all       # Onboard agents")
    print(f"  5. python cli.py link-all          # Link to keeper")
    print(f"  6. python cli.py verify            # Verify fleet health")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    """Discover available agents from GitHub."""
    bs = PelagicBootstrap(
        fleet_dir=args.fleet_dir,
        config_path=args.config,
    )
    agents = bs.discover_agents()

    if not agents:
        print("No agents discovered.")
        return 1

    print(f"\nDiscovered {len(agents)} agent(s):\n")
    print(f"  {'NAME':<20} {'URL'}")
    print(f"  {'-'*20} {'-'*50}")
    for info in agents:
        cloned_marker = " ✓" if info.cloned else ""
        print(f"  {info.name:<20} {info.repo_url}{cloned_marker}")
    print()
    return 0


def cmd_clone(args: argparse.Namespace) -> int:
    """Clone specific agents or all discovered agents."""
    bs = PelagicBootstrap(
        fleet_dir=args.fleet_dir,
        config_path=args.config,
    )

    if args.all:
        bs.discover_agents()
        cloned = bs.clone_agents()
    elif args.agents:
        # Ensure agents are in the registry
        for name in args.agents:
            if name not in bs.agents:
                from bootstrap import AgentInfo
                bs.agents[name] = AgentInfo(
                    name=name,
                    repo_url=f"{bs.github_base}/{name}",
                )
        cloned = bs.clone_agents(args.agents)
    else:
        print("Specify agents to clone or use --all.")
        return 1

    if not cloned:
        print("No agents were cloned.")
        return 1

    print(f"\nCloned {len(cloned)} agent(s):")
    for info in cloned:
        print(f"  ✓ {info.name} → {info.local_path}")
    return 0


def cmd_setup_keeper(args: argparse.Namespace) -> int:
    """Set up the keeper agent as fleet captain."""
    bs = PelagicBootstrap(
        fleet_dir=args.fleet_dir,
        config_path=args.config,
    )
    try:
        keeper = bs.setup_keeper()
        print(f"\nKeeper agent '{keeper.name}' initialized at {keeper.local_path}")
        return 0
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_onboard_all(args: argparse.Namespace) -> int:
    """Onboard all cloned agents."""
    bs = PelagicBootstrap(
        fleet_dir=args.fleet_dir,
        config_path=args.config,
    )
    onboarded = bs.onboard_all()

    if not onboarded:
        print("No agents were onboarded.")
        return 1

    print(f"\nOnboarded {len(onboarded)} agent(s):")
    for info in onboarded:
        print(f"  ✓ {info.name}")
    return 0


def cmd_link_all(args: argparse.Namespace) -> int:
    """Link all agents to the keeper."""
    bs = PelagicBootstrap(
        fleet_dir=args.fleet_dir,
        config_path=args.config,
    )
    linked = bs.link_to_keeper()

    if not linked:
        print("No agents were linked. Is the keeper set up?")
        return 1

    print(f"\nLinked {len(linked)} agent(s) to keeper:")
    for info in linked:
        print(f"  ✓ {info.name}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify fleet health."""
    bs = PelagicBootstrap(
        fleet_dir=args.fleet_dir,
        config_path=args.config,
    )
    bs.discover_agents()
    status = bs.verify_fleet()

    print(bs.status_table())

    if status.issues:
        return 1
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show fleet status."""
    bs = PelagicBootstrap(
        fleet_dir=args.fleet_dir,
        config_path=args.config,
    )
    bs.discover_agents()
    print(bs.status_table())
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnose fleet issues."""
    bs = PelagicBootstrap(
        fleet_dir=args.fleet_dir,
        config_path=args.config,
    )
    bs.discover_agents()
    diagnostics = bs.doctor()

    if not diagnostics:
        print("✓ No issues found. Fleet is healthy.")
        return 0

    print(f"\nFound {len(diagnostics)} diagnostic(s):\n")
    for i, diag in enumerate(diagnostics, 1):
        print(f"  {i}. {diag}")
    print()
    return 1


def cmd_reset(args: argparse.Namespace) -> int:
    """Reset the fleet to a clean state."""
    if not args.yes:
        confirm = input(
            "⚠  This will DELETE all cloned agents and fleet config. Continue? [y/N] "
        ).strip().lower()
        if confirm != "y":
            print("Aborted.")
            return 1

    bs = PelagicBootstrap(
        fleet_dir=args.fleet_dir,
        config_path=args.config,
    )
    success = bs.reset(confirm=True)

    if success:
        print("Fleet reset complete.")
        return 0
    else:
        print("Reset failed.", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="pelagic-bootstrap",
        description="Pelagic Bootstrap Agent — one-command fleet setup",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose (debug) logging",
    )

    # Global options for fleet dir / config path
    parser.add_argument(
        "--fleet-dir",
        default=str(DEFAULT_FLEET_DIR),
        help="Fleet root directory",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to fleet.yaml configuration",
    )

    sub = parser.add_subparsers(dest="command", help="Available subcommands")

    # init
    sub.add_parser("init", help="Initialize a new fleet (interactive)")

    # discover
    sub.add_parser("discover", help="Discover available agents from GitHub")

    # clone
    clone_p = sub.add_parser("clone", help="Clone agents")
    clone_p.add_argument("agents", nargs="*", help="Agent names to clone")
    clone_p.add_argument("--all", action="store_true", help="Clone all discovered agents")

    # setup-keeper
    sub.add_parser("setup-keeper", help="Set up the keeper agent")

    # onboard-all
    sub.add_parser("onboard-all", help="Onboard all cloned agents")

    # link-all
    sub.add_parser("link-all", help="Link all agents to keeper")

    # verify
    sub.add_parser("verify", help="Verify fleet health")

    # status
    sub.add_parser("status", help="Show fleet status")

    # doctor
    sub.add_parser("doctor", help="Diagnose fleet issues")

    # reset
    reset_p = sub.add_parser("reset", help="Reset fleet (with confirmation)")
    reset_p.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

COMMAND_MAP: dict[str, callable] = {  # type: ignore[type-arg]
    "init": cmd_init,
    "discover": cmd_discover,
    "clone": cmd_clone,
    "setup-keeper": cmd_setup_keeper,
    "onboard-all": cmd_onboard_all,
    "link-all": cmd_link_all,
    "verify": cmd_verify,
    "status": cmd_status,
    "doctor": cmd_doctor,
    "reset": cmd_reset,
}


def main(argv: Optional[list[str]] = None) -> int:
    """Main CLI entry point.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (0 = success, non-zero = failure).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    _setup_logging(getattr(args, "verbose", False))

    if not args.command:
        parser.print_help()
        return 0

    handler = COMMAND_MAP.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        logging.getLogger("pelagic.cli").error("Fatal: %s", exc, exc_info=True)
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
