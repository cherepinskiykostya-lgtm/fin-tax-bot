from __future__ import annotations

from typing import Optional

__all__ = ["initial_summary_candidate"]


def initial_summary_candidate(
    domain: str,
    summary_source_kind: str,
    provided_summary: Optional[str],
) -> Optional[str]:
    """Return the initial summary candidate based on source domain."""

    if domain.endswith("tax.gov.ua") and summary_source_kind == "print":
        # For DPS we always prefer extracting the article body from the print
        # version, so ignore any teaser pulled from the listing page.
        return None

    return provided_summary
