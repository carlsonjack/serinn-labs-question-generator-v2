"""Base interfaces for file parsers and category normalizers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import DetectedFile, NormalizedBundle, ParserResult


class InputParser(ABC):
    """Two-step parser interface defined by the epic."""

    def __init__(self) -> None:
        self._loaded_path: Path | None = None

    @abstractmethod
    def load(self, filepath: str | Path) -> "InputParser":
        """Load a source file into parser state."""

    @abstractmethod
    def normalize(self) -> ParserResult:
        """Normalize the loaded file into typed records."""


class CategoryNormalizer(ABC):
    """Coordinates multiple detected files into one normalized bundle."""

    @abstractmethod
    def normalize(
        self,
        detected_files: Sequence[DetectedFile],
        settings: Mapping[str, Any],
    ) -> NormalizedBundle:
        """Produce a normalized bundle for one category."""

