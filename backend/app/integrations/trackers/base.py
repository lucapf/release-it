"""Common issue-tracker interface.

Every tracker fetches the issues belonging to a release from an external system
and returns them in a single normalized shape:

    {"key": str, "type": str, "summary": str, "status": str, "url": str}

``url`` is the human-facing page an operator opens in the tracker's own web UI,
not the REST endpoint. It is empty when the tracker cannot determine it.

A tracker also fetches a single issue in full, for the on-demand detail view:

    {"key", "type", "summary", "status", "url", "description", "assignee",
     "reporter", "priority", "labels": [str], "created_at", "updated_at"}

Concrete trackers live in their own modules (``jira.py``, ``github.py``) and
implement :class:`IssueTracker`. There are no in-process stubs: a tracker talks
to its real backing service, and returns an empty list when it is not
configured.
"""
from __future__ import annotations

from typing import Protocol

# Status used to mark an issue as completed/closed across trackers.
DONE = "Done"

# Every key a ``fetch_issue`` result carries, so callers can rely on their
# presence however sparse the tracker's own payload was.
DETAIL_FIELDS = (
    "key", "type", "summary", "status", "url",
    "description", "assignee", "reporter", "priority",
    "labels", "created_at", "updated_at",
)


def detail(**known) -> dict:
    """A full detail dict: every field present, ``known`` filled in."""
    out: dict = {f: "" for f in DETAIL_FIELDS}
    out["labels"] = []
    out.update(known)
    return out


class IssueTracker(Protocol):
    """Fetches the issues contained in a release from an external tracker.

    ``query`` is the resolved filter value (Jira: JQL; GitHub: a milestone
    title or label). ``filter_kind`` selects how ``query`` is interpreted for
    trackers that support more than one mode (GitHub: ``"milestone"`` or
    ``"label"``). ``repo`` is the product's repository slug when relevant
    (GitHub ``"owner/repo"``).
    """

    def fetch_issues(
        self, query: str, *, repo: str = "", filter_kind: str = ""
    ) -> list[dict]:
        ...

    def fetch_issue(self, key: str, *, repo: str = "") -> dict | None:
        """One issue in full, or None when it does not exist or the tracker is
        not configured. ``key`` is the normalized key ``fetch_issues`` stored
        (Jira: ``"REL-1"``; GitHub: ``"#12"``)."""
        ...
