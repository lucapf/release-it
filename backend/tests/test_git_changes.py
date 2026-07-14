"""Release change detection over the umbrella chart.

The umbrella Chart.yaml is the source of truth for what a release ships: its
dependencies are diffed between the previous release's tag and this one's, and
only the services it names are diffed further. Dependencies without a linked
repository are reported, never guessed; a component whose own diff fails
reports its error without sinking the rest; and a missing baseline is an
explicit reason, never an empty (clean-looking) change-set.

No database and no network: repositories and the git provider are faked.
"""
from __future__ import annotations

import pytest

from app.integrations.git import GitCommit, GitCompare, GitRefNotFound
from app.services import git_changes
from app.services.git_changes import (
    compute_release_changes,
    parse_chart_dependencies,
    render_tag,
)

REL = {"id": 2, "product_id": 1, "version": "0.2.0"}
PREV = {"id": 1, "product_id": 1, "version": "0.1.0", "state": "Approved"}

DEPLOYMENT = {
    "id": 10, "product_id": 1, "provider": "github", "repo": "acme/umbrella",
    "role": "deployment", "component_name": "", "tag_pattern": "v{version}",
    "web_url": "", "chart_path": "Chart.yaml",
}
LINK_A = {
    "id": 11, "product_id": 1, "provider": "github", "repo": "acme/moda",
    "role": "component", "component_name": "moda", "tag_pattern": "v{version}",
    "web_url": "https://github.com/acme/moda", "chart_path": "Chart.yaml",
}

CHART_OLD = """
apiVersion: v2
name: umbrella
dependencies:
  - name: moda
    version: 1.0.0
  - name: modb
    version: 2.0.0
  - name: modx
    version: 1.0.0
"""
CHART_NEW = """
apiVersion: v2
name: umbrella
dependencies:
  - name: moda
    version: 1.1.0
  - name: modb
    version: 2.0.0
  - name: modx
    version: 1.2.0
  - name: modc
    version: 0.1.0
"""


class FakeProvider:
    """Answers tag/file/compare questions from canned data."""

    def __init__(self):
        self.tags = {("acme/umbrella", "v0.1.0"), ("acme/umbrella", "v0.2.0")}
        self.files = {
            ("acme/umbrella", "Chart.yaml", "v0.1.0"): CHART_OLD,
            ("acme/umbrella", "Chart.yaml", "v0.2.0"): CHART_NEW,
        }
        self.compare_raises: Exception | None = None

    def resolve_tag(self, repo, tag):
        if (repo, tag) not in self.tags:
            raise GitRefNotFound(f'tag "{tag}" not found in {repo}')
        return "sha-" + tag

    def read_file_at_ref(self, repo, path, ref):
        return self.files[(repo, path, ref)]

    def compare(self, repo, base_ref, head_ref):
        if self.compare_raises:
            raise self.compare_raises
        return GitCompare(
            base_ref=base_ref, head_ref=head_ref,
            commits=[
                GitCommit(sha="a" * 40, short_sha="aaaaaaaa",
                          subject="Fix login (#12)", message="Fix login (#12)"),
                GitCommit(sha="b" * 40, short_sha="bbbbbbbb",
                          subject="Refactor internals", message="Refactor internals"),
            ],
            total_commits=2,
            web_url=f"https://github.com/{repo}/compare/{base_ref}...{head_ref}",
        )


@pytest.fixture
def world(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(git_changes.git, "get_git_provider", lambda cfg, p: provider)
    monkeypatch.setattr(
        git_changes.git_repos_repo, "anchor_for", lambda conn, pid: DEPLOYMENT
    )
    monkeypatch.setattr(
        git_changes.git_repos_repo, "components_for",
        lambda conn, pid: {"moda": LINK_A},
    )
    monkeypatch.setattr(
        git_changes.git_repos_repo, "list_for_product", lambda conn, pid: [DEPLOYMENT, LINK_A]
    )
    monkeypatch.setattr(
        git_changes.releases_repo, "previous_release", lambda conn, rid: PREV
    )
    return provider


def test_chart_dependency_parsing():
    deps = parse_chart_dependencies(CHART_NEW)
    assert deps == {"moda": "1.1.0", "modb": "2.0.0", "modx": "1.2.0", "modc": "0.1.0"}


def test_malformed_chart_is_an_error_not_an_empty_answer():
    with pytest.raises(ValueError):
        parse_chart_dependencies("dependencies: {not: [a, list")
    with pytest.raises(ValueError):
        parse_chart_dependencies("- just\n- a list\n")


def test_render_tag_falls_back_on_a_broken_pattern():
    assert render_tag("v{version}", "1.2.0") == "v1.2.0"
    assert render_tag("release-{version}", "1.2.0") == "release-1.2.0"
    assert render_tag("{versoin}", "1.2.0") == "v1.2.0"  # typo'd placeholder


def test_changed_added_and_unchanged_components_are_classified(world):
    cs = compute_release_changes(None, None, REL)
    by_name = {c.name: c for c in cs.components}
    assert cs.baseline_missing == ""
    assert by_name["moda"].status == "changed"
    assert (by_name["moda"].old_version, by_name["moda"].new_version) == ("1.0.0", "1.1.0")
    # modb/modc have no linked repo? modb is unmatched too — only moda is linked.
    assert "moda" in by_name and len(by_name) == 1


def test_commits_are_mapped_to_tickets_and_unmapped_ones_counted(world):
    cs = compute_release_changes(None, None, REL)
    moda = next(c for c in cs.components if c.name == "moda")
    assert moda.mapped_count == 1 and moda.unmapped_count == 1
    assert moda.commits[0].tickets == ["#12"]
    assert moda.commits[1].tickets == []


def test_dependencies_without_a_linked_repo_are_reported_not_guessed(world):
    cs = compute_release_changes(None, None, REL)
    unmatched = {d["name"]: d for d in cs.unmatched_dependencies}
    # modx changed but has no link; modb (unchanged) and modc (added) too.
    assert set(unmatched) == {"modb", "modc", "modx"}
    assert unmatched["modx"] == {
        "name": "modx", "old_version": "1.0.0", "new_version": "1.2.0"
    }
    assert unmatched["modc"]["old_version"] is None  # added in this release


def test_a_component_diff_failure_does_not_sink_the_report(world):
    world.compare_raises = GitRefNotFound('tag "v1.0.0" not found in acme/moda')
    cs = compute_release_changes(None, None, REL)
    moda = next(c for c in cs.components if c.name == "moda")
    assert moda.status == "error"
    assert "v1.0.0" in moda.error
    # The rest of the change-set is intact.
    assert cs.baseline_missing == ""
    assert cs.unmatched_dependencies


def test_first_release_has_an_explicit_missing_baseline(world, monkeypatch):
    monkeypatch.setattr(
        git_changes.releases_repo, "previous_release", lambda conn, rid: None
    )
    cs = compute_release_changes(None, None, REL)
    assert "first release" in cs.baseline_missing
    # Current versions are still reported (as unchanged), nothing is diffed.
    assert all(c.status == "unchanged" for c in cs.components)


def test_untagged_release_has_an_explicit_reason(world):
    world.tags.discard(("acme/umbrella", "v0.2.0"))
    cs = compute_release_changes(None, None, REL)
    assert "has not been tagged" in cs.baseline_missing
    assert cs.new_tag is None and cs.components == []


def test_missing_previous_tag_has_an_explicit_reason(world):
    world.tags.discard(("acme/umbrella", "v0.1.0"))
    cs = compute_release_changes(None, None, REL)
    assert 'previous release\'s tag "v0.1.0"' in cs.baseline_missing


def test_no_anchor_repo_is_an_error_not_an_empty_change_set(world, monkeypatch):
    monkeypatch.setattr(
        git_changes.git_repos_repo, "anchor_for", lambda conn, pid: None
    )
    with pytest.raises(git_changes.ChangesUnavailable):
        compute_release_changes(None, None, REL)


# --- Simple products: the whole codebase in one repo -------------------------
CODEBASE = {
    "id": 20, "product_id": 1, "provider": "github", "repo": "acme/simple",
    "role": "codebase", "component_name": "", "tag_pattern": "v{version}",
    "web_url": "https://github.com/acme/simple", "chart_path": "Chart.yaml",
}


@pytest.fixture
def simple_world(world, monkeypatch):
    """Same fakes, but the product's anchor is a single codebase repo tagged
    with the product version — no umbrella chart, no components."""
    world.tags = {("acme/simple", "v0.1.0"), ("acme/simple", "v0.2.0")}
    monkeypatch.setattr(
        git_changes.git_repos_repo, "anchor_for", lambda conn, pid: CODEBASE
    )
    monkeypatch.setattr(git_changes.git_repos_repo, "components_for", lambda conn, pid: {})
    monkeypatch.setattr(
        git_changes.git_repos_repo, "list_for_product", lambda conn, pid: [CODEBASE]
    )
    return world


def test_single_repo_product_diffs_the_codebase_between_release_tags(simple_world):
    cs = compute_release_changes(None, None, REL)
    assert cs.mode == "single-repo"
    assert cs.baseline_missing == ""
    assert (cs.old_tag, cs.new_tag) == ("v0.1.0", "v0.2.0")
    assert len(cs.components) == 1
    repo = cs.components[0]
    assert repo.name == "simple"  # falls back to the repository name
    assert (repo.old_version, repo.new_version) == ("0.1.0", "0.2.0")
    assert repo.status == "changed"
    assert repo.mapped_count == 1 and repo.unmapped_count == 1
    assert cs.unmatched_dependencies == []  # no Chart.yaml in this mode


def test_single_repo_first_release_has_an_explicit_missing_baseline(
    simple_world, monkeypatch
):
    monkeypatch.setattr(
        git_changes.releases_repo, "previous_release", lambda conn, rid: None
    )
    cs = compute_release_changes(None, None, REL)
    assert "first release" in cs.baseline_missing
    assert cs.components[0].status == "unchanged"
    assert cs.components[0].new_version == "0.2.0"


def test_single_repo_untagged_release_has_an_explicit_reason(simple_world):
    simple_world.tags.discard(("acme/simple", "v0.2.0"))
    cs = compute_release_changes(None, None, REL)
    assert "has not been tagged" in cs.baseline_missing
    assert cs.new_tag is None


def test_single_repo_missing_previous_tag_has_an_explicit_reason(simple_world):
    simple_world.tags.discard(("acme/simple", "v0.1.0"))
    cs = compute_release_changes(None, None, REL)
    assert 'previous release\'s tag "v0.1.0"' in cs.baseline_missing
    assert cs.components[0].status == "unchanged"  # versions shown, nothing diffed
