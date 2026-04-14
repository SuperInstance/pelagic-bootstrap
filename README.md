# Pelagic Bootstrap Agent

> **One command to rule them all.**

The meta-agent that sets up an entire Pelagic SuperInstance fleet from scratch.
Oracle1, any human operator, or automation pipeline can run this to discover,
clone, configure, onboard, link, and verify a fleet of cooperative AI agents.

---

## Quick Start

### One-Command Fleet Setup

```bash
# From the pelagic-bootstrap directory:
python cli.py init                    # Interactive initialization
python cli.py discover                # Scan GitHub for available agents
python cli.py clone --all             # Clone every agent
python cli.py setup-keeper            # Promote keeper to fleet captain
python cli.py onboard-all             # Run first-run setup on each agent
python cli.py link-all                # Connect agents to the keeper
python cli.py verify                  # Confirm fleet health
python cli.py status                  # View fleet status table
```

Or use the Python API for programmatic control:

```python
from bootstrap import PelagicBootstrap

bs = PelagicBootstrap(fleet_dir="~/.pelagic/fleet")
status = bs.bootstrap_all()
print(bs.status_table())
```

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                 Pelagic Bootstrap Agent               │
│                  (cli.py / bootstrap.py)              │
├────────────┬──────────────┬──────────────────────────┤
│  Discovery │   Cloning    │   Configuration          │
│            │              │   (fleet_config.py)      │
│  GitHub    │  git clone   │   fleet.yaml             │
│  API/gh    │  --depth 1   │   ├ agents[]             │
│            │              │   ├ topology              │
├────────────┴──────────────┤   ├ model_tiers          │
│                           │   ├ secret_scopes        │
│   Keeper (Captain)        │   └ backup               │
│      │                    │                          │
│      ├── git-agent (Co)   │   Agent Registration     │
│      ├── coder            │   ├ role assignment      │
│      ├── researcher       │   ├ port allocation      │
│      └── reviewer         │   └ secret scoping       │
│                           │                          │
│         Star Topology     │   Health & Verification  │
│         with Keeper Hub   │   ├ config validation    │
└───────────────────────────┤   ├ git status check     │
                            │   └ endpoint reachability│
                            └──────────────────────────┘
```

### Key Components

| File | Purpose |
|------|---------|
| `bootstrap.py` | Core engine — discovery, cloning, onboarding, linking, verification |
| `fleet_config.py` | YAML-based fleet configuration with agent roles, topology, model tiers |
| `cli.py` | Full CLI with 10 subcommands for manual or scripted operation |

### Agent Roles

| Role | Description |
|------|-------------|
| **Captain** (keeper) | Fleet hub — coordinates all agents, stores shared state |
| **Co-captain** (git-agent) | Manages version control, code review, PR workflows |
| **Worker** | Domain-specific agents (coder, researcher, reviewer, etc.) |

---

## Example Workflows

### Bootstrap a Minimal Fleet

```bash
python cli.py init
python cli.py discover
python cli.py clone keeper git-agent
python cli.py setup-keeper
python cli.py onboard-all
python cli.py link-all
python cli.py verify
```

### Diagnose Problems

```bash
python cli.py doctor     # Check for missing deps, uncloned agents, etc.
python cli.py status     # View full fleet status table
```

### Reset and Start Fresh

```bash
python cli.py reset -y   # Remove all agents and config, start over
```

### Programmatic Usage

```python
from bootstrap import PelagicBootstrap
from fleet_config import FleetConfig, AgentRole

# Create fleet config
config = FleetConfig("my-fleet.yaml")
config.fleet_name = "production"
config.add_agent(AgentRole(name="keeper", role="captain", captain=True))
config.add_agent(AgentRole(name="coder", role="worker"))
config.save()

# Bootstrap
bs = PelagicBootstrap(config_path="my-fleet.yaml")
bs.discover_agents()
bs.clone_agents(["keeper", "coder"])
bs.setup_keeper()
bs.onboard_all()
print(bs.status_table())
```

---

## Configuration (fleet.yaml)

```yaml
version: "1.0.0"
fleet_name: pelagic-default
agents:
  - name: keeper
    role: captain
    captain: true
    model_tier: premium
  - name: git-agent
    role: co-captain
    co_captain: true
    secret_scope: [global, git]
topology:
  mode: star
  hub: keeper
  ports:
    keeper: 8000
    git-agent: 8001
model_tiers:
  standard:
    provider: openai
    model_id: gpt-4
  premium:
    provider: openai
    model_id: gpt-4-turbo
backup:
  enabled: true
  interval_hours: 24
  retention_days: 30
```

---

## Dependencies

- **Python 3.10+**
- **PyYAML** (`pip install pyyaml`)
- **Git** (for cloning)
- **GitHub CLI** (`gh`) — optional, enhances discovery

---

## License

MIT
