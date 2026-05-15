"""Registries for parser-layer extension points."""

from __future__ import annotations

from typing import Callable

from .base import CategoryNormalizer

_CATEGORY_NORMALIZERS: dict[str, type[CategoryNormalizer]] = {}


def register_category_normalizer(
    category_key: str,
) -> Callable[[type[CategoryNormalizer]], type[CategoryNormalizer]]:
    """Register a category normalizer class by key."""

    def decorator(
        normalizer_cls: type[CategoryNormalizer],
    ) -> type[CategoryNormalizer]:
        _CATEGORY_NORMALIZERS[category_key] = normalizer_cls
        return normalizer_cls

    return decorator


def get_category_normalizer(category_key: str) -> type[CategoryNormalizer]:
    """Resolve a previously registered category normalizer."""

    try:
        return _CATEGORY_NORMALIZERS[category_key]
    except KeyError as exc:
        known = ", ".join(sorted(_CATEGORY_NORMALIZERS)) or "<none>"
        raise KeyError(
            f"Unknown category normalizer '{category_key}'. Known: {known}"
        ) from exc


def list_registered_categories() -> list[str]:
    """Return registered category keys in stable order."""

    return sorted(_CATEGORY_NORMALIZERS)

