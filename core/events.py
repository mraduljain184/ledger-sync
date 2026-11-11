import uuid
from dataclasses import dataclass
from typing import Optional

from core.hlc import HLC

CREATE = "create"
EDIT_AMOUNT = "edit_amount"
EDIT_NOTE = "edit_note"
DELETE = "delete"


@dataclass(frozen=True)
class Event:
    id: str
    device: str
    hlc: HLC
    entry: str
    op: str
    party: str = ""
    amount: int = 0          # paise; positive = customer owes, negative = payment received
    note: str = ""
    base: Optional[str] = None   # latest event the author had seen (see below)


def new_id():
    return str(uuid.uuid4())