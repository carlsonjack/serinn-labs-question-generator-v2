"""Central team alias registry for all sports packages."""

from .registry import get_flat_map, list_registered_packages, reload_team_aliases
from .resolve import normalize_team_name, resolve_stats_team_code

__all__ = [
    "get_flat_map",
    "list_registered_packages",
    "reload_team_aliases",
    "normalize_team_name",
    "resolve_stats_team_code",
]
