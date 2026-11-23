from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.data.fees import CreateFeeData, FeeFilters, UpdateFeeData
from app.dependencies import (
    get_create_fee_handler,
    get_current_user,
    get_delete_fee_handler,
    get_list_fees_handler,
    get_my_fees_handler,
    get_pay_own_fee_handler,
    get_pending_members_handler,
    get_register_payment_handler,
    get_update_fee_handler,
    require_administrator,
)
from app.domain.entities import FeeStatus, PaymentMethod, User
from app.handlers.fees import (
    CreateFeeHandler,
    DeleteFeeHandler,
    ListFeesHandler,
    MyFeesHandler,
    PayOwnFeeHandler,
    PendingMembersHandler,
    RegisterPaymentHandler,
    UpdateFeeHandler,
)
from app.schemas.auth import AuthenticationErrorResponse, ValidationErrorResponse
from app.schemas.fees import (
    CreateFeeRequest,
    FeeEnvelope,
    FeeListResponse,
    FeeMemberResponse,
    FeeResponse,
    MyFeesResponse,
    MyFeesSummary,
    PayFeeRequest,
    PendingMemberResponse,
    PendingMembersResponse,
    RegisterPaymentRequest,
    UpdateFeeRequest,
)
from app.schemas.members import MemberErrorResponse as ErrorResponse
from app.schemas.members import PaginationMeta

router = APIRouter(
    prefix="/api/v1/fees",
    tags=["US19-US22 — Taxas e pagamentos"],
    responses={
        401: {
            "model": AuthenticationErrorResponse,
            "description": "Sessão ausente, inválida, expirada ou revogada",
            "headers": {"WWW-Authenticate": {"schema": {"type": "string"}, "example": "Bearer"}},
        },
        422: {"model": ValidationErrorResponse, "description": "Dados inválidos"},
    },
)
Admin = Annotated[User, Depends(require_administrator)]
CurrentUser = Annotated[User, Depends(get_current_user)]
FeeId = Annotated[int, Path(ge=1, le=9223372036854775807)]
forbidden = {"model": ErrorResponse, "description": "Conta sem permissão de administrador"}
not_found = {"model": ErrorResponse, "description": "Taxa não encontrada"}
paid = {"model": ErrorResponse, "description": "Taxa já paga"}


# ---------- Jogador (US20 e US22) ----------


@router.get(
    "/mine",
    response_model=MyFeesResponse,
    summary="Minhas taxas (pagas e pendentes)",
    description=(
        "Taxas do cadastro de membro com o mesmo e-mail da conta. Sem cadastro de membro, "
        "member é null e a lista vem vazia."
    ),
)
def my_fees(
    user: CurrentUser, handler: Annotated[MyFeesHandler, Depends(get_my_fees_handler)]
) -> MyFeesResponse:
    result = handler.handle(user)
    today = handler.today()
    fees = [FeeResponse.of(fee, today) for fee in result.fees]
    return MyFeesResponse(
        member=FeeMemberResponse.of(result.member) if result.member else None,
        data=fees,
        summary=MyFeesSummary(
            pending_total=result.pending_total,
            paid_total=result.paid_total,
            overdue_count=sum(fee.overdue for fee in fees),
        ),
    )


@router.post(
    "/mine/{fee_id}/pay",
    response_model=FeeEnvelope,
    summary="Pagar uma taxa própria",
    description=(
        "Paga uma taxa pendente do próprio jogador por Pix ou cartão. Sem gateway configurado, "
        "o pagamento é aprovado na hora (paid_via=online)."
    ),
    responses={404: not_found, 409: paid},
)
def pay_own_fee(
    fee_id: FeeId,
    payload: PayFeeRequest,
    user: CurrentUser,
    handler: Annotated[PayOwnFeeHandler, Depends(get_pay_own_fee_handler)],
) -> FeeEnvelope:
    fee = handler.handle(user, fee_id, PaymentMethod(payload.method))
    return FeeEnvelope(data=FeeResponse.of(fee, handler.today()))


# ---------- Administração (US19 e US21) ----------


@router.get(
    "/pending-members",
    response_model=PendingMembersResponse,
    summary="Membros com pagamentos pendentes (admin)",
    description="Um item por membro com taxas pendentes; quem deve há mais tempo vem primeiro.",
    responses={403: forbidden},
)
def pending_members(
    _: Admin, handler: Annotated[PendingMembersHandler, Depends(get_pending_members_handler)]
) -> PendingMembersResponse:
    return PendingMembersResponse(
        data=[
            PendingMemberResponse(
                member=FeeMemberResponse.of(item.member),
                pending_count=item.pending_count,
                pending_total=item.pending_total,
                overdue_count=item.overdue_count,
                oldest_due_date=item.oldest_due_date,
            )
            for item in handler.handle()
        ]
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=FeeEnvelope,
    summary="Lançar taxa para um membro (admin)",
    responses={
        403: forbidden,
        404: {"model": ErrorResponse, "description": "Membro não encontrado"},
    },
)
def create_fee(
    payload: CreateFeeRequest,
    _: Admin,
    handler: Annotated[CreateFeeHandler, Depends(get_create_fee_handler)],
) -> FeeEnvelope:
    fee = handler.handle(
        CreateFeeData(payload.member_id, payload.description, payload.amount, payload.due_date)
    )
    return FeeEnvelope(data=FeeResponse.of(fee, handler.today()))


@router.get(
    "",
    response_model=FeeListResponse,
    summary="Listar taxas (admin)",
    description="Ordenadas por vencimento. overdue=true: só as pendentes já vencidas.",
    responses={403: forbidden},
)
def list_fees(
    _: Admin,
    handler: Annotated[ListFeesHandler, Depends(get_list_fees_handler)],
    page: Annotated[int, Query(ge=1, le=2147483647)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    member_id: Annotated[int | None, Query(ge=1, le=9223372036854775807)] = None,
    status_filter: Annotated[FeeStatus | None, Query(alias="status")] = None,
    overdue: bool = False,
) -> FeeListResponse:
    result = handler.handle(
        FeeFilters(member_id=member_id, status=status_filter),
        overdue=overdue,
        page=page,
        page_size=page_size,
    )
    today = handler.today()
    return FeeListResponse(
        data=[FeeResponse.of(fee, today) for fee in result.items],
        meta=PaginationMeta(
            page=result.page,
            page_size=result.page_size,
            total=result.total,
            total_pages=(result.total + result.page_size - 1) // result.page_size,
        ),
    )


@router.patch(
    "/{fee_id}",
    response_model=FeeEnvelope,
    summary="Corrigir taxa pendente (admin)",
    responses={403: forbidden, 404: not_found, 409: paid},
)
def update_fee(
    fee_id: FeeId,
    payload: UpdateFeeRequest,
    _: Admin,
    handler: Annotated[UpdateFeeHandler, Depends(get_update_fee_handler)],
) -> FeeEnvelope:
    fee = handler.handle(
        fee_id, UpdateFeeData(payload.description, payload.amount, payload.due_date)
    )
    return FeeEnvelope(data=FeeResponse.of(fee, handler.today()))


@router.post(
    "/{fee_id}/payment",
    response_model=FeeEnvelope,
    summary="Registrar pagamento recebido (admin)",
    responses={403: forbidden, 404: not_found, 409: paid},
)
def register_payment(
    fee_id: FeeId,
    payload: RegisterPaymentRequest,
    _: Admin,
    handler: Annotated[RegisterPaymentHandler, Depends(get_register_payment_handler)],
) -> FeeEnvelope:
    fee = handler.handle(fee_id, payload.method, payload.paid_at)
    return FeeEnvelope(data=FeeResponse.of(fee, handler.today()))


@router.delete(
    "/{fee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Excluir taxa pendente (admin)",
    responses={403: forbidden, 404: not_found, 409: paid},
)
def delete_fee(
    fee_id: FeeId,
    _: Admin,
    handler: Annotated[DeleteFeeHandler, Depends(get_delete_fee_handler)],
) -> Response:
    handler.handle(fee_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
