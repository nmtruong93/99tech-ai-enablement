"""The committed output: the report regenerates from the committed workspace, and every draft in it
still passes the current checks."""

import shutil

import pytest

from support_desk.checks import Severity, check_reply
from support_desk.cli import render_report
from support_desk.config import PROJECT_ROOT, Settings
from support_desk.desk import SupportDesk
from support_desk.models import DraftStatus

OUTPUT = PROJECT_ROOT / "output"


@pytest.fixture
def committed(tmp_path, settings):
    workspace = tmp_path / "committed"
    shutil.copytree(OUTPUT / "workspace", workspace)
    return SupportDesk(Settings(settings.data_dir, workspace, settings.as_of))


def test_report_matches_the_committed_run(committed):
    assert render_report(committed) == (OUTPUT / "open-tickets.md").read_text(encoding="utf-8")


def test_every_pending_draft_passes_the_current_checks(committed):
    pending = [d for d in committed.workspace.drafts() if d.status is DraftStatus.PENDING_REVIEW]
    assert pending
    for draft in pending:
        triage = committed.triage(draft.ticket_id)
        findings = check_reply(draft.body, committed._reply_context(triage.ticket, triage))
        assert not [f for f in findings if f.severity is Severity.BLOCK], draft.draft_id


def test_every_open_ticket_has_a_draft_or_is_answered_elsewhere(committed):
    queue = committed.queue()
    drafted = {d.ticket_id for d in committed.workspace.drafts() if d.status is DraftStatus.PENDING_REVIEW}
    assert drafted == {t.ticket.ticket_id for t in queue if not t.duplicate_of}
