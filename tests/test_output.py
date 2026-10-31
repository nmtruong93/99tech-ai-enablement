"""The committed output: the report regenerates from the committed workspace, and every draft in it
still passes the current checks."""

import json
import shutil

import pytest

from support_desk.checks import Severity, check_reply
from support_desk.cli import main, render_report
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
        findings = check_reply(draft.body, committed._reply_context(committed.triage(draft.ticket_id)))
        assert not [f for f in findings if f.severity is Severity.BLOCK], draft.draft_id


def test_every_open_ticket_has_a_draft_or_is_answered_elsewhere(committed):
    queue = committed.queue()
    drafted = {d.ticket_id for d in committed.workspace.drafts() if d.status is DraftStatus.PENDING_REVIEW}
    assert drafted == {t.ticket.ticket_id for t in queue if not t.duplicate_of}


def test_a_person_can_approve_and_decline_from_the_command_line(committed, monkeypatch, capsys):
    monkeypatch.setenv("SUPPORT_DESK_WORKSPACE", str(committed.workspace.root))
    assert main(["approve", "D-0001", "--by", "Mai"]) == 0  # the README's review example
    sent = (committed.workspace.root / "outbox.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(sent) == 1 and json.loads(sent[0])["body"].endswith("Mai, 99Tech Support")
    assert main(["refund", "R-9999", "--by", "Mai", "--decline"]) == 1
    assert "No refund request R-9999" in capsys.readouterr().err
    assert main(["approve", "D-9999", "--by", "Mai", "--body-file", "missing.txt"]) == 1
    assert "Can't read missing.txt" in capsys.readouterr().err
