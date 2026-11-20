"""The storage and issue-tracker implementations we control keep the contract rules."""

from __future__ import annotations

import pytest
from cloud_storage_api import (
    ConflictError,
    DocumentStorage,
    InvalidOperationError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    ProviderUnavailableError,
)
from issue_tracker_contract import (
    MAX_TITLE_LENGTH,
    ErrorCode,
    IssueProvider,
    IssueUpdate,
    ServiceError,
)

from baskd.workflow.controlled import (
    FailingDocumentStorage,
    FailingIssueProvider,
    InMemoryDocumentStorage,
    InMemoryIssueProvider,
)


@pytest.fixture
def storage() -> InMemoryDocumentStorage:
    return InMemoryDocumentStorage()


@pytest.fixture
def issues() -> InMemoryIssueProvider:
    return InMemoryIssueProvider()


class TestInMemoryStorage:
    def test_create_then_read(self, storage: InMemoryDocumentStorage) -> None:
        info = storage.create("/notes/a.md", b"# A")
        assert (info.path, info.name, info.size, info.type) == ("/notes/a.md", "a.md", 3, None)
        assert info.id and info.etag and info.modified_at and info.modified_at.endswith("Z")
        assert storage.download("/notes/a.md") == b"# A"
        assert storage.get_metadata("/notes/a.md") == info

    def test_create_never_overwrites(self, storage: InMemoryDocumentStorage) -> None:
        storage.create("/notes/a.md", b"first")
        with pytest.raises(ConflictError):
            storage.create("/notes/a.md", b"second")
        with pytest.raises(ConflictError):
            storage.create("/notes", b"a folder is there")
        assert storage.download("/notes/a.md") == b"first"

    def test_create_below_a_file_is_invalid(self, storage: InMemoryDocumentStorage) -> None:
        storage.create("/a.md", b"")
        with pytest.raises(InvalidOperationError):
            storage.create("/a.md/b.md", b"")

    @pytest.mark.parametrize("path", ["relative.md", "/", "/folder/", "/a//b.md"])
    def test_rejects_malformed_paths(self, storage: InMemoryDocumentStorage, path: str) -> None:
        with pytest.raises(InvalidRequestError):
            storage.create(path, b"")

    def test_replace_changes_content_and_etag(self, storage: InMemoryDocumentStorage) -> None:
        before = storage.create("/a.md", b"one")
        after = storage.replace("/a.md", b"three")
        assert (after.id, after.size) == (before.id, 5)
        assert after.etag != before.etag

    def test_replace_never_creates(self, storage: InMemoryDocumentStorage) -> None:
        with pytest.raises(NotFoundError):
            storage.replace("/missing.md", b"")

    def test_files_and_folders_are_told_apart(self, storage: InMemoryDocumentStorage) -> None:
        storage.create("/notes/a.md", b"")
        folder = storage.get_metadata("/notes")
        assert (folder.id, folder.size, folder.name) == (None, None, "notes")
        with pytest.raises(InvalidOperationError):
            storage.download("/notes")
        with pytest.raises(NotFoundError):
            storage.get_metadata("/missing")

    def test_lists_direct_children_sorted(self, storage: InMemoryDocumentStorage) -> None:
        storage.create("/notes/b.md", b"")
        storage.create("/notes/a.md", b"")
        storage.create("/notes/deep/c.md", b"")
        storage.create("/other.md", b"")
        listed = storage.list_files("/notes")
        assert [(i.path, i.type) for i in listed] == [
            ("/notes/a.md", "file"),
            ("/notes/b.md", "file"),
            ("/notes/deep", "folder"),
        ]
        assert [i.path for i in storage.list_files("/")] == ["/notes", "/other.md"]

    def test_list_needs_an_existing_folder(self, storage: InMemoryDocumentStorage) -> None:
        storage.create("/a.md", b"")
        with pytest.raises(InvalidOperationError):
            storage.list_files("/a.md")
        with pytest.raises(NotFoundError):
            storage.list_files("/missing")

    def test_move(self, storage: InMemoryDocumentStorage) -> None:
        storage.create("/a.md", b"x")
        storage.create("/taken.md", b"")
        with pytest.raises(ConflictError):
            storage.move("/a.md", "/taken.md")
        with pytest.raises(InvalidOperationError):
            storage.move("/a.md", "/a.md")
        moved = storage.move("/a.md", "/b/a.md")
        assert moved.path == "/b/a.md"
        assert storage.download("/b/a.md") == b"x"
        with pytest.raises(NotFoundError):
            storage.get_metadata("/a.md")

    def test_delete_a_file_or_a_folder(self, storage: InMemoryDocumentStorage) -> None:
        storage.create("/a.md", b"")
        storage.create("/f/b.md", b"")
        storage.create("/f/g/c.md", b"")
        storage.delete("/a.md")
        storage.delete("/f")
        assert storage.list_files("/") == []
        with pytest.raises(NotFoundError):
            storage.delete("/f")

    def test_health(self, storage: InMemoryDocumentStorage) -> None:
        storage.check_health()


class TestFailingStorage:
    def test_is_a_document_storage(self) -> None:
        assert isinstance(FailingDocumentStorage(), DocumentStorage)

    @pytest.mark.parametrize(
        "call",
        [
            lambda s: s.create("/a", b""),
            lambda s: s.replace("/a", b""),
            lambda s: s.download("/a"),
            lambda s: s.get_metadata("/a"),
            lambda s: s.list_files("/"),
            lambda s: s.move("/a", "/b"),
            lambda s: s.delete("/a"),
            lambda s: s.check_health(),
        ],
    )
    def test_every_call_fails_unavailable(self, call: object) -> None:
        with pytest.raises(ProviderUnavailableError, match="BASKD_WORKFLOW_STORAGE=failing"):
            call(FailingDocumentStorage())  # type: ignore[operator]

    def test_error_type_is_configurable(self) -> None:
        with pytest.raises(PermissionDeniedError):
            FailingDocumentStorage(PermissionDeniedError).create("/a", b"")


class TestInMemoryIssues:
    def test_satisfies_the_contract(self, issues: InMemoryIssueProvider) -> None:
        assert isinstance(issues, IssueProvider)

    def test_create_get_update_delete(self, issues: InMemoryIssueProvider) -> None:
        created = issues.create_issue("Prep: review")
        assert issues.get_issue(created.id, fresh=True) == created
        updated = issues.update_issue(created.id, IssueUpdate(title="Prep: renamed"))
        assert (updated.id, updated.title) == (created.id, "Prep: renamed")
        issues.delete_issue(created.id)
        with pytest.raises(ServiceError) as info:
            issues.get_issue(created.id)
        assert info.value.code is ErrorCode.NOT_FOUND
        with pytest.raises(ServiceError):
            issues.delete_issue(created.id)

    def test_lists_newest_first_up_to_limit(self, issues: InMemoryIssueProvider) -> None:
        titles = [issues.create_issue(f"issue {n}").title for n in range(3)]
        assert [i.title for i in issues.list_issues(limit=2)] == [titles[2], titles[1]]
        assert issues.list_issues(limit=10)[-1].title == titles[0]

    @pytest.mark.parametrize("title", ["   ", "x" * (MAX_TITLE_LENGTH + 1)])
    def test_rejects_titles_the_contract_forbids(
        self, issues: InMemoryIssueProvider, title: str
    ) -> None:
        with pytest.raises(ServiceError) as info:
            issues.create_issue(title)
        assert info.value.code is ErrorCode.INVALID_INPUT
        assert info.value.may_have_applied is False


class TestFailingIssues:
    def test_satisfies_the_contract(self) -> None:
        assert isinstance(FailingIssueProvider(), IssueProvider)

    @pytest.mark.parametrize(
        "call",
        [
            lambda p: p.create_issue("t"),
            lambda p: p.get_issue("1"),
            lambda p: p.update_issue("1", IssueUpdate(title="t")),
            lambda p: p.delete_issue("1"),
            lambda p: p.list_issues(limit=1),
        ],
    )
    def test_every_call_fails_without_writing(self, call: object) -> None:
        with pytest.raises(ServiceError) as info:
            call(FailingIssueProvider())  # type: ignore[operator]
        error = info.value
        assert (error.code, error.may_have_applied) == (ErrorCode.PROVIDER_ERROR, False)
        assert error.provider_involved is True
        assert "BASKD_WORKFLOW_ISSUES=failing" in error.message

    def test_can_fail_with_an_unknown_outcome(self) -> None:
        with pytest.raises(ServiceError) as info:
            FailingIssueProvider(may_have_applied=True).create_issue("t")
        assert info.value.may_have_applied is True
