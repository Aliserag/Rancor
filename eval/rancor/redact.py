"""Scrubbing identifiers out of diagnostic text before it is published.

Run directories are committed so a reviewer can check the audit trail, so
anything written into them is published. A provider exception is captured
verbatim, and the published judge_errors.jsonl carried an OpenRouter
account id inside one — three lines away from a DISCLOSURES claim that no
personal data is stored.

Error text is diagnostic, not evidence: the message matters, the account
it was raised against does not.
"""

from __future__ import annotations

import re

REDACTED = "[redacted]"

# Deliberately anchored on the value, not the field name -- "user_id" is
# useful diagnostic context and stays; the opaque id after it goes.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # provider account identifiers: user_ followed by a long opaque token
    re.compile(r"\buser_[A-Za-z0-9]{16,}\b"),
    # API keys of the shapes these providers issue
    re.compile(r"\bsk-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"\bor-v1-[A-Za-z0-9]{16,}\b"),
)


def scrub_identifiers(text: str) -> str:
    """Replace account identifiers and key-shaped tokens with a marker."""
    if not text:
        return text
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text
