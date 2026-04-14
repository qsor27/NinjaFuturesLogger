from typing import Literal

from models.base import StrictModel
from models.position import Position

Outcome = Literal["winner", "loser", "scratch", "open"]


class LinkMember(StrictModel):
    account: str
    instrument: str
    entry_execution_id: str
    ordinal: int


class LinkGroup(StrictModel):
    link_group_id: int
    label: str | None
    created_at: int


class LinkGroupDetail(StrictModel):
    link_group_id: int
    label: str | None
    created_at: int
    members: list[LinkMember]


class PageMeta(StrictModel):
    page: int
    page_size: int
    total: int

    @property
    def total_pages(self) -> int:
        if self.total == 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1


class PositionListPage(StrictModel):
    positions: list[Position]
    page: PageMeta
