"""Where the export lives, where actions are written, and what "now" means.

Ticket ages are measured against the moment the export was taken, not the wall
clock. Otherwise every ticket in a September export looks months overdue and the
priorities become meaningless. Override with SUPPORT_DESK_AS_OF when working on
a fresh export.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# From the export README: "Exported by the Customer Support team on 29 Sep 2026, 09:00 UTC."
EXPORT_TAKEN_AT = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    workspace_dir: Path
    as_of: datetime

    @classmethod
    def from_env(cls) -> "Settings":
        as_of = EXPORT_TAKEN_AT
        if raw := os.environ.get("SUPPORT_DESK_AS_OF"):
            as_of = datetime.fromisoformat(raw)
            as_of = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
        return cls(
            data_dir=Path(os.environ.get("SUPPORT_DESK_DATA", PROJECT_ROOT / "data")),
            workspace_dir=Path(os.environ.get("SUPPORT_DESK_WORKSPACE", PROJECT_ROOT / "workspace")),
            as_of=as_of,
        )
