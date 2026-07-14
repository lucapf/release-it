"""Mapping commits to tickets by the references they carry.

A commit belongs to a ticket only when it *says so* — a ticket id in the
message (``#123``, ``PROJ-123``) or in the branch name of a merge commit. A
commit that says nothing is unmapped, and stays unmapped: guessing would
silently misattribute code to work nobody did.
"""
from __future__ import annotations

from app.services.git_changes import extract_tickets


def test_github_style_reference_in_the_subject():
    assert extract_tickets("Fix login redirect (#123)", "") == ["#123"]


def test_jira_style_reference_in_the_body():
    assert extract_tickets("Fix login", "Implements PROJ-42 as discussed") == ["PROJ-42"]


def test_multiple_references_are_deduplicated_in_order():
    tickets = extract_tickets("Fix #12 and #34", "Also touches #12 and REL-7")
    assert tickets == ["#12", "#34", "REL-7"]


def test_merge_commit_branch_name_yields_a_ticket():
    assert extract_tickets("Merge branch 'feature/123-add-login'", "") == ["#123"]
    assert extract_tickets("Merge branch 'feature/PROJ-9-cleanup'", "") == ["PROJ-9"]
    assert extract_tickets("Merge branch '456-hotfix'", "") == ["#456"]


def test_merge_commit_of_a_ticketless_branch_is_unmapped():
    assert extract_tickets("Merge branch 'refactor-db-layer'", "") == []


def test_sha_fragments_and_lowercase_ids_are_not_tickets():
    # "abc#12" is not an issue reference; "proj-12" is not a Jira key.
    assert extract_tickets("Revert abc#12", "see proj-12") == []


def test_a_commit_with_no_reference_is_unmapped():
    assert extract_tickets("Improve error handling", "Better messages.") == []


def test_markdown_issue_links_still_count():
    assert extract_tickets("Fix crash", "Closes #99.") == ["#99"]
