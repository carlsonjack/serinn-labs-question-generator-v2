"""Question template schema and loading (EPIC 3)."""

from .loader import (
    default_templates_directory,
    index_template_json_paths_by_id,
    load_template_dir,
    load_template_file,
    resolve_templates_directory,
)
from .schema import QuestionTemplate, parse_template_dict

__all__ = [
    "QuestionTemplate",
    "default_templates_directory",
    "index_template_json_paths_by_id",
    "load_template_dir",
    "load_template_file",
    "parse_template_dict",
    "resolve_templates_directory",
]
