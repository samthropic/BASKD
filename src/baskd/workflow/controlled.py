"""Storage and issue-tracker implementations we control, for tests and the failure demo.

``BASKD_WORKFLOW_STORAGE=memory`` / ``BASKD_WORKFLOW_ISSUES=memory`` select the in-memory ones
(the default, so the service runs without other teams' accounts). ``failing`` selects ones
whose every call fails, which is how the HW3 failure demonstration runs on a deployed service
with nothing but a configuration change.

The in-memory classes keep the contract rules the workflow relies on: ``create`` never
overwrites (``ConflictError``), missing things are ``NotFoundError`` / ``not_found``, and
issues are listed newest first. Nothing is persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from cloud_storage_api import (
    ConflictError,
    DocumentStorage,
    FileInfo,
    InvalidOperationError,
    InvalidRequestError,
    NotFoundError,
    ProviderUnavailableError,
    StorageError,
)
from issue_tracker_contract import (
    MAX_TITLE_LENGTH,
    ErrorCode,
    Issue,
    IssueUpdate,
    ServiceError,
)

CONTROLLED_FAILURE = "Controlled failure (BASKD_WORKFLOW_{vertical}=failing)"


@dataclass
class _Stored:
    id: str
    content: bytes
    modified_at: str
    etag: str


class InMemoryDocumentStorage(DocumentStorage):
    """Files in a dict, keyed by absolute path. Folders exist while they contain a file."""

    def __init__(self) -> None:
        self._files: dict[str, _Stored] = {}

    def create(self, path: str, content: bytes) -> FileInfo:
        _check_path(path)
        if path in self._files or self._is_folder(path):
            raise ConflictError(f"Something already exists at {path}")
        if any(path.startswith(f"{file}/") for file in self._files):
            raise InvalidOperationError("A parent of the path is a file")
        self._files[path] = _Stored(uuid4().hex, content, _now(), uuid4().hex)
        return self._info(path)

    def replace(self, path: str, content: bytes) -> FileInfo:
        stored = self._file(path)
        stored.content, stored.modified_at, stored.etag = content, _now(), uuid4().hex
        return self._info(path)

    def download(self, path: str) -> bytes:
        return self._file(path).content

    def get_metadata(self, path: str) -> FileInfo:
        _check_path(path)
        if path in self._files:
            return self._info(path)
        if self._is_folder(path):
            return _folder(path)
        raise NotFoundError(f"Nothing exists at {path}")

    def list_files(self, path: str) -> list[FileInfo]:
        folder = "" if path == "/" else path
        if folder:
            _check_path(folder)
            if folder in self._files:
                raise InvalidOperationError("The path is a file, not a folder")
            if not self._is_folder(folder):
                raise NotFoundError(f"No folder exists at {path}")
        children: dict[str, FileInfo] = {}
        for file in self._files:
            if not file.startswith(f"{folder}/"):
                continue
            name = file[len(folder) + 1 :].split("/", 1)[0]
            child = f"{folder}/{name}"
            if child == file:
                children[child] = self._info(child, listed=True)
            else:
                children[child] = _folder(child, listed=True)
        return [children[child] for child in sorted(children)]

    def move(self, from_path: str, to_path: str) -> FileInfo:
        stored = self._file(from_path)
        _check_path(to_path)
        if to_path == from_path:
            raise InvalidOperationError("The source and destination are the same")
        if to_path in self._files or self._is_folder(to_path):
            raise ConflictError(f"Something already exists at {to_path}")
        del self._files[from_path]
        self._files[to_path] = stored
        return self._info(to_path)

    def delete(self, path: str) -> None:
        _check_path(path)
        if path in self._files:
            del self._files[path]
            return
        inside = [file for file in self._files if file.startswith(f"{path}/")]
        if not inside:
            raise NotFoundError(f"Nothing exists at {path}")
        for file in inside:
            del self._files[file]

    def check_health(self) -> None:
        return None

    def _file(self, path: str) -> _Stored:
        _check_path(path)
        if path in self._files:
            return self._files[path]
        if self._is_folder(path):
            raise InvalidOperationError("The path is a folder")
        raise NotFoundError(f"No file exists at {path}")

    def _is_folder(self, path: str) -> bool:
        return any(file.startswith(f"{path}/") for file in self._files)

    def _info(self, path: str, *, listed: bool = False) -> FileInfo:
        stored = self._files[path]
        return FileInfo(
            id=stored.id,
            name=path.rsplit("/", 1)[1],
            path=path,
            size=len(stored.content),
            modified_at=stored.modified_at,
            etag=stored.etag,
            type="file" if listed else None,
        )


class FailingDocumentStorage(DocumentStorage):
    """Every call raises ``error_type`` (by default ``ProviderUnavailableError``)."""

    def __init__(self, error_type: type[StorageError] = ProviderUnavailableError) -> None:
        self._error_type = error_type

    def _fail(self) -> StorageError:
        return self._error_type(CONTROLLED_FAILURE.format(vertical="STORAGE"))

    def create(self, path: str, content: bytes) -> FileInfo:
        raise self._fail()

    def replace(self, path: str, content: bytes) -> FileInfo:
        raise self._fail()

    def download(self, path: str) -> bytes:
        raise self._fail()

    def get_metadata(self, path: str) -> FileInfo:
        raise self._fail()

    def list_files(self, path: str) -> list[FileInfo]:
        raise self._fail()

    def move(self, from_path: str, to_path: str) -> FileInfo:
        raise self._fail()

    def delete(self, path: str) -> None:
        raise self._fail()

    def check_health(self) -> None:
        raise self._fail()


class InMemoryIssueProvider:
    """Issues in a dict. Satisfies :class:`issue_tracker_contract.IssueProvider`."""

    def __init__(self) -> None:
        self._issues: dict[str, Issue] = {}

    def create_issue(self, title: str) -> Issue:
        if not title.strip() or len(title) > MAX_TITLE_LENGTH:
            raise ServiceError(ErrorCode.INVALID_INPUT, "The issue title is not allowed")
        issue = Issue(id=uuid4().hex, title=title)
        self._issues[issue.id] = issue
        return issue

    def get_issue(self, issue_id: str, *, fresh: bool = False) -> Issue:
        return self._existing(issue_id)

    def update_issue(self, issue_id: str, changes: IssueUpdate) -> Issue:
        issue = self._existing(issue_id)
        if changes.title is not None:
            issue = Issue(id=issue.id, title=changes.title)
            self._issues[issue.id] = issue
        return issue

    def delete_issue(self, issue_id: str) -> None:
        self._existing(issue_id)
        del self._issues[issue_id]

    def list_issues(self, *, limit: int) -> list[Issue]:
        return list(reversed(self._issues.values()))[:limit]

    def _existing(self, issue_id: str) -> Issue:
        if issue_id not in self._issues:
            raise ServiceError(ErrorCode.NOT_FOUND, "Issue not found", provider_involved=True)
        return self._issues[issue_id]


class FailingIssueProvider:
    """Every call raises :class:`ServiceError` with ``code``.

    The default, ``provider_error`` with ``may_have_applied=False``, is a provider that could
    not be reached: nothing was written. ``may_have_applied=True`` is a write whose outcome is
    unknown (the request went out, the answer never came back).
    """

    def __init__(
        self,
        code: ErrorCode = ErrorCode.PROVIDER_ERROR,
        *,
        may_have_applied: bool = False,
    ) -> None:
        self._code = code
        self._may_have_applied = may_have_applied

    def _fail(self) -> ServiceError:
        return ServiceError(
            self._code,
            CONTROLLED_FAILURE.format(vertical="ISSUES"),
            provider_involved=True,
            may_have_applied=self._may_have_applied,
        )

    def create_issue(self, title: str) -> Issue:
        raise self._fail()

    def get_issue(self, issue_id: str, *, fresh: bool = False) -> Issue:
        raise self._fail()

    def update_issue(self, issue_id: str, changes: IssueUpdate) -> Issue:
        raise self._fail()

    def delete_issue(self, issue_id: str) -> None:
        raise self._fail()

    def list_issues(self, *, limit: int) -> list[Issue]:
        raise self._fail()


def _check_path(path: str) -> None:
    if not path.startswith("/") or path == "/" or path.endswith("/") or "//" in path:
        raise InvalidRequestError("A path must be absolute and name an entry below the root")


def _folder(path: str, *, listed: bool = False) -> FileInfo:
    return FileInfo(
        id=None,
        name=path.rsplit("/", 1)[1],
        path=path,
        size=None,
        modified_at=None,
        etag=None,
        type="folder" if listed else None,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
