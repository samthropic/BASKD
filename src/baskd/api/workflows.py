"""``/workflows/meeting-prep``: the HW3 workflow across calendar, storage and issue tracker.

The handler only converts between HTTP and :mod:`baskd.workflow.meeting_prep`. A failed
step reaches :mod:`baskd.api.errors`, which answers with the usual error envelope plus
``failed_step`` and ``completed``.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from pydantic import BaseModel

from baskd.api.errors import WorkflowErrorResponse
from baskd.models import MeetingPrepInput
from baskd.workflow.meeting_prep import MeetingPrep, MeetingPrepRequest, MeetingPrepResult

router = APIRouter(prefix="/workflows", tags=["workflows"])


class StepOut(BaseModel):
    step: str
    id: str
    reused: bool


class EventOut(BaseModel):
    id: str
    title: str
    start: str
    end: str


class DocumentOut(BaseModel):
    path: str
    id: str | None


class IssueOut(BaseModel):
    id: str
    title: str


class MeetingPrepResponse(BaseModel):
    event: EventOut
    document: DocumentOut
    issue: IssueOut
    steps: list[StepOut]


@router.post(
    "/meeting-prep",
    status_code=status.HTTP_201_CREATED,
    response_model=MeetingPrepResponse,
    summary="Prepare a meeting: event, agenda document and prep issue",
    description=(
        "Runs three fixed steps: `create_event` (our calendar), `save_agenda` (the configured "
        "Document Storage, at `/baskd/meeting-prep/<event id>.md`) and `create_issue` (the "
        "configured issue tracker, titled `Prep: <title> [evt:<event id>]`). Nothing is rolled "
        "back. A failure names `failed_step` and lists `completed`; resend the same body with "
        "`event_id` from `completed` to resume: finished steps are found and reused "
        "(`reused: true`), not repeated."
    ),
    responses={
        code: {"model": WorkflowErrorResponse}
        for code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            status.HTTP_502_BAD_GATEWAY,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    },
)
def meeting_prep(body: MeetingPrepInput, request: Request) -> MeetingPrepResponse:
    workflow: MeetingPrep = request.app.state.meeting_prep
    request.state.provider_called = True
    result = workflow.run(
        MeetingPrepRequest(
            title=body.title,
            start=body.start,
            end=body.end,
            agenda=body.agenda,
            event_id=body.event_id,
        )
    )
    return _response(result)


def _response(result: MeetingPrepResult) -> MeetingPrepResponse:
    event, document, issue = result.event, result.document, result.issue
    return MeetingPrepResponse(
        event=EventOut(id=event.id, title=event.title, start=event.start, end=event.end),
        document=DocumentOut(path=document.path, id=document.id),
        issue=IssueOut(id=issue.id, title=issue.title),
        steps=[StepOut(step=s.step, id=s.id, reused=s.reused) for s in result.steps],
    )
