"""Compatibility entrypoint for the versioned agent directory."""
from pathlib import Path
from .directory import AgentDirectory

AgentRoster = AgentDirectory
_ROSTER_PATH = Path(__file__).resolve().parents[2] / "data" / "execution_agents" / "roster.json"
_agent_roster = AgentRoster(_ROSTER_PATH)


def get_agent_roster():
    return _agent_roster
