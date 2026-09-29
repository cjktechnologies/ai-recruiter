from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select

from app.api.deps import DB, IdempotencyKeyHeader, Paging, require, run_idempotent
from app.core.principal import Principal
from app.domain.enums import OfferStatus
from app.models.pipeline import Application
from app.models.selection import Offer
from app.schemas.common import DecisionIn, Page
from app.schemas.pipeline import CancelIn, OfferDraftIn, OfferOut, OfferResponseIn, OfferSendOut, OfferUpdate
from app.services import offers as svc
from app.services.common import get_scoped, paginate

router = APIRouter(tags=["Offers"])


@router.post(
    "/applications/{application_id}/offers",
    response_model=OfferOut,
    status_code=status.HTTP_201_CREATED,
    summary="Offer Agent drafts an offer within the approved compensation band",
)
def draft_offer(
    application_id: uuid.UUID, data: OfferDraftIn, db: DB, p: Annotated[Principal, Depends(require("offers:create"))]
) -> Offer:
    app = get_scoped(db, Application, application_id, p, label="Application")
    offer = svc.draft(db, app, data, p)
    db.commit()
    return offer


@router.get("/offers", response_model=Page[OfferOut])
def list_offers(
    db: DB,
    paging: Paging,
    p: Annotated[Principal, Depends(require("offers:read"))],
    status_: Annotated[OfferStatus | None, Query(alias="status")] = None,
    application_id: uuid.UUID | None = None,
) -> dict:
    stmt = select(Offer).where(Offer.organization_id == p.organization_id)
    if status_:
        stmt = stmt.where(Offer.status == status_)
    if application_id:
        stmt = stmt.where(Offer.application_id == application_id)
    items, total = paginate(
        db,
        stmt,
        model=Offer,
        page=paging.page,
        page_size=paging.page_size,
        sort=paging.sort,
        allowed_sorts={"created_at", "status", "sent_at"},
    )
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}


@router.get("/offers/{offer_id}", response_model=OfferOut)
def get_offer(offer_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("offers:read"))]) -> Offer:
    return get_scoped(db, Offer, offer_id, p)


@router.patch("/offers/{offer_id}", response_model=OfferOut)
def update_offer(
    offer_id: uuid.UUID, data: OfferUpdate, db: DB, p: Annotated[Principal, Depends(require("offers:update"))]
) -> Offer:
    offer = svc.update(db, get_scoped(db, Offer, offer_id, p), data, p)
    db.commit()
    return offer


@router.post("/offers/{offer_id}/submit", response_model=OfferOut, summary="Submit for the approval chain")
def submit_offer(offer_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("offers:update"))]) -> Offer:
    offer = svc.submit(db, get_scoped(db, Offer, offer_id, p), p)
    db.commit()
    return offer


@router.post("/offers/{offer_id}/decision", response_model=OfferOut, summary="Approve/reject the current step")
def decide_offer(
    offer_id: uuid.UUID,
    data: DecisionIn,
    db: DB,
    request: Request,
    key: IdempotencyKeyHeader,
    p: Annotated[Principal, Depends(require("offers:approve"))],
) -> dict:
    offer = get_scoped(db, Offer, offer_id, p)
    return run_idempotent(
        db,
        p,
        request,
        key,
        data.model_dump(),
        lambda: OfferOut.model_validate(svc.decide(db, offer, p, data.decision == "approve", data.comment)).model_dump(
            mode="json"
        ),
    )


@router.post(
    "/offers/{offer_id}/send",
    response_model=OfferSendOut,
    summary="Send the approved offer (idempotent with Idempotency-Key)",
)
def send_offer(
    offer_id: uuid.UUID,
    db: DB,
    request: Request,
    key: IdempotencyKeyHeader,
    p: Annotated[Principal, Depends(require("offers:send"))],
) -> dict:
    offer = get_scoped(db, Offer, offer_id, p)

    def _do() -> dict:
        o, link = svc.send(db, offer, p)
        return {"offer": OfferOut.model_validate(o).model_dump(mode="json"), "candidate_link": link}

    return run_idempotent(db, p, request, key, {"offer_id": str(offer_id)}, _do)


@router.post(
    "/offers/{offer_id}/record-response",
    response_model=OfferOut,
    summary="Record a candidate's response received outside the portal (e.g. signed PDF)",
)
def record_response(
    offer_id: uuid.UUID, data: OfferResponseIn, db: DB, p: Annotated[Principal, Depends(require("offers:send"))]
) -> Offer:
    offer = svc.respond(db, get_scoped(db, Offer, offer_id, p), data.accept, data.reason, p)
    db.commit()
    return offer


@router.post("/offers/{offer_id}/withdraw", response_model=OfferOut)
def withdraw_offer(
    offer_id: uuid.UUID, data: CancelIn, db: DB, p: Annotated[Principal, Depends(require("offers:update"))]
) -> Offer:
    offer = svc.withdraw(db, get_scoped(db, Offer, offer_id, p), p, data.reason)
    db.commit()
    return offer
