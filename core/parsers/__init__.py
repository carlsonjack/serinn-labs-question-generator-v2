"""Parser layer exports."""

from .base import CategoryNormalizer, InputParser
from .contracts import (
    ContentEntity,
    DetectedFile,
    InputProfile,
    NormalizedBundle,
    NormalizedEvent,
    ParserResult,
    PlayerStatRecord,
    SourceRole,
    ValidationIssue,
    ValidationSeverity,
)
from .registry import (
    get_category_normalizer,
    list_registered_categories,
    register_category_normalizer,
)
from .service import load_normalized_bundle

__all__ = [
    "CategoryNormalizer",
    "ContentEntity",
    "DetectedFile",
    "InputParser",
    "InputProfile",
    "NormalizedBundle",
    "NormalizedEvent",
    "ParserResult",
    "PlayerStatRecord",
    "SourceRole",
    "ValidationIssue",
    "ValidationSeverity",
    "get_category_normalizer",
    "list_registered_categories",
    "load_normalized_bundle",
    "register_category_normalizer",
]

