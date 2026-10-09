from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..services import item_actions
from .runs import item_view
from .util import oid

router = APIRouter(prefix="/api/items", tags=["items"])


class ItemPatch(BaseModel):
    subject: str | None = None
    body: str | None = None
    greeting_text: str | None = None
    kind: str | None = None
    name: str | None = None
    company: str | None = None


@router.get("/{item_id}")
def get_item(item_id: str):
    return item_view(item_actions.get_item(oid(item_id)))


@router.patch("/{item_id}")
def patch_item(item_id: str, body: ItemPatch):
    item = item_actions.get_item(oid(item_id))
    return item_view(item_actions.edit_item(item, body.model_dump(exclude_unset=True)))
