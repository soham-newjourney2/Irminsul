from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.app.core.deps import Db, require_role
from backend.app.core.idempotency import IdempotencyKey, run_idempotent
from backend.app.core.schemas import Envelope, parse_object_id
from backend.app.db.client import Doc
from backend.app.modules.procurement import service
from backend.app.modules.procurement.schemas import (
    CounterIn,
    NoteIn,
    OrderOut,
    OrderStatus,
    PurchaseRequestIn,
    PurchaseRequestOut,
    RequestStatus,
)

requests_router = APIRouter(prefix="/purchase-requests", tags=["purchase-requests"])
orders_router = APIRouter(prefix="/orders", tags=["orders"])

Distributor = Annotated[Doc, Depends(require_role("distributor"))]
Party = Annotated[Doc, Depends(require_role("farmer", "distributor"))]
OrderViewer = Annotated[Doc, Depends(require_role("farmer", "distributor", "admin"))]
Limit = Annotated[int, Query(ge=1, le=100)]
ReqOut = Envelope[PurchaseRequestOut]


@requests_router.post("", status_code=201, response_model=ReqOut)
async def create_request(
    body: PurchaseRequestIn, distributor: Distributor, db: Db, key: IdempotencyKey = None
) -> ReqOut:
    listing_id = parse_object_id(body.listing_id, "listing")
    out = await run_idempotent(
        db,
        user_id=distributor["_id"],
        key=key,
        scope="purchase_requests.create",
        model=PurchaseRequestOut,
        fn=lambda: service.create_request(db, distributor, body, listing_id),
    )
    return Envelope(data=out)


@requests_router.get("", response_model=Envelope[list[PurchaseRequestOut]])
async def list_requests(
    user: Party, db: Db, status: RequestStatus | None = None, limit: Limit = 50
) -> Envelope[list[PurchaseRequestOut]]:
    rows = await service.list_requests(db, user, status, limit)
    return Envelope(data=rows, meta={"count": len(rows), "limit": limit})


@requests_router.get("/{request_id}", response_model=ReqOut)
async def get_request(request_id: str, user: Party, db: Db) -> ReqOut:
    rid = parse_object_id(request_id, "purchase request")
    return Envelope(data=await service.get_request(db, user, rid))


@requests_router.post("/{request_id}/accept", response_model=Envelope[OrderOut])
async def accept_request(request_id: str, user: Party, db: Db) -> Envelope[OrderOut]:
    rid = parse_object_id(request_id, "purchase request")
    return Envelope(data=await service.accept(db, user, rid))


@requests_router.post("/{request_id}/counter", response_model=ReqOut)
async def counter_request(request_id: str, body: CounterIn, user: Party, db: Db) -> ReqOut:
    rid = parse_object_id(request_id, "purchase request")
    return Envelope(data=await service.counter(db, user, rid, body))


@requests_router.post("/{request_id}/reject", response_model=ReqOut)
async def reject_request(request_id: str, body: NoteIn, user: Party, db: Db) -> ReqOut:
    rid = parse_object_id(request_id, "purchase request")
    return Envelope(data=await service.reject(db, user, rid, body.note))


@requests_router.post("/{request_id}/withdraw", response_model=ReqOut)
async def withdraw_request(request_id: str, body: NoteIn, user: Party, db: Db) -> ReqOut:
    rid = parse_object_id(request_id, "purchase request")
    return Envelope(data=await service.withdraw(db, user, rid, body.note))


@orders_router.get("", response_model=Envelope[list[OrderOut]])
async def list_orders(
    user: OrderViewer, db: Db, status: OrderStatus | None = None, limit: Limit = 50
) -> Envelope[list[OrderOut]]:
    rows = await service.list_orders(db, user, status, limit)
    return Envelope(data=rows, meta={"count": len(rows), "limit": limit})


@orders_router.get("/{order_id}", response_model=Envelope[OrderOut])
async def get_order(order_id: str, user: OrderViewer, db: Db) -> Envelope[OrderOut]:
    return Envelope(data=await service.get_order(db, user, parse_object_id(order_id, "order")))


def _action_route(action: str) -> None:
    async def endpoint(
        order_id: str, body: NoteIn, user: OrderViewer, db: Db
    ) -> Envelope[OrderOut]:
        oid = parse_object_id(order_id, "order")
        return Envelope(data=await service.order_action(db, user, oid, action, body.note))

    orders_router.add_api_route(
        f"/{{order_id}}/{action}",
        endpoint,
        methods=["POST"],
        response_model=Envelope[OrderOut],
        name=f"order_{action}",
    )


for _action in service.ORDER_TRANSITIONS:
    _action_route(_action)
