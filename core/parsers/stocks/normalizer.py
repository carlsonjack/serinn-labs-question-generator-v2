"""Normalize stock watchlist inputs."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from core.parsers.base import CategoryNormalizer
from core.parsers.contracts import (
    ContentEntity,
    DetectedFile,
    NormalizedBundle,
    SourceRole,
    ValidationIssue,
    ValidationSeverity,
)
from core.parsers.registry import register_category_normalizer

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def format_stock_display(company_name: str, ticker: str) -> str:
    """Return the client-required display label, e.g. ``Apple Inc. (AAPL)``."""

    return f"{company_name.strip()} ({ticker.strip().upper()})"


def _cell(row: Mapping[str, Any], *names: str) -> str:
    normalized = {_normalize_key(k): v for k, v in row.items()}
    for name in names:
        value = normalized.get(_normalize_key(name))
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _issue(
    code: str,
    message: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
    file_path: str | None = None,
    row_number: int | None = None,
) -> ValidationIssue:
    details = {"row_number": row_number} if row_number is not None else {}
    return ValidationIssue(
        code=code,
        message=message,
        severity=severity,
        file_path=file_path,
        source_role=SourceRole.ENTITY_SOURCE,
        details=details,
    )


@register_category_normalizer("stocks")
class StocksCategoryNormalizer(CategoryNormalizer):
    """Normalize a stock watchlist into generic content entities."""

    def normalize(
        self,
        detected_files: Sequence[DetectedFile],
        settings: Mapping[str, Any],
    ) -> NormalizedBundle:
        entity_file = next(
            (d for d in detected_files if d.source_role == SourceRole.ENTITY_SOURCE),
            None,
        )
        if entity_file is None:
            return NormalizedBundle(
                issues=[
                    _issue(
                        "missing_stock_watchlist",
                        "Stocks generation requires an entity_source/asset_source watchlist file.",
                    )
                ]
            )

        entities: list[ContentEntity] = []
        issues: list[ValidationIssue] = []
        seen_tickers: set[str] = set()
        expected_topic = str(
            settings.get("topic_import_id")
            or settings.get("topic_import_ids", {}).get("stocks")
            or ""
        ).strip()

        for offset, row in enumerate(entity_file.records, start=entity_file.header_row_index + 2):
            company = _cell(row, "Company Name", "company_name", "company", "asset")
            ticker = _cell(row, "Ticker", "ticker", "symbol").upper()
            topic_import_id = _cell(row, "Topic Import ID", "topic_import_id")
            topic_name = _cell(row, "topic_name", "Topic Name")

            if not company or not ticker:
                issues.append(
                    _issue(
                        "invalid_stock_row",
                        "Stock rows require Company Name and Ticker.",
                        file_path=str(entity_file.file_path),
                        row_number=offset,
                    )
                )
                continue
            if not _TICKER_RE.match(ticker):
                issues.append(
                    _issue(
                        "invalid_stock_ticker",
                        f"Invalid stock ticker {ticker!r}.",
                        file_path=str(entity_file.file_path),
                        row_number=offset,
                    )
                )
                continue
            if ticker in seen_tickers:
                issues.append(
                    _issue(
                        "duplicate_stock_ticker",
                        f"Duplicate stock ticker {ticker!r}; tickers must be unique.",
                        file_path=str(entity_file.file_path),
                        row_number=offset,
                    )
                )
                continue
            seen_tickers.add(ticker)

            if expected_topic and topic_import_id and topic_import_id != expected_topic:
                issues.append(
                    _issue(
                        "stock_topic_mismatch",
                        (
                            f"Watchlist topic_import_id {topic_import_id!r} does not match "
                            f"configured topic {expected_topic!r}; configured topic will be used."
                        ),
                        severity=ValidationSeverity.WARNING,
                        file_path=str(entity_file.file_path),
                        row_number=offset,
                    )
                )

            entities.append(
                ContentEntity(
                    entity_id=ticker,
                    display_name=format_stock_display(company, ticker),
                    entity_type="stock",
                    topic_import_id=topic_import_id or expected_topic or None,
                    metadata={
                        "company_name": company,
                        "ticker": ticker,
                        "topic_name": topic_name,
                        "row_number": offset,
                    },
                )
            )

        if not entities:
            issues.append(
                _issue(
                    "no_stocks_normalized",
                    "No valid stocks were normalized from the watchlist.",
                    file_path=str(entity_file.file_path),
                )
            )

        return NormalizedBundle(entities=entities, issues=issues)

