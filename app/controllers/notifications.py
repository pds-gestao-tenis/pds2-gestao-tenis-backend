import hmac
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.mailer import Mailer, send_all
from app.dependencies import get_mailer, get_reminders_handler
from app.handlers.notifications import SendRemindersHandler

router = APIRouter(prefix="/api/v1/internal", tags=["US18 — Lembretes"])


class RemindersResult(BaseModel):
    reminded_bookings: int
    emails: int


class RemindersEnvelope(BaseModel):
    data: RemindersResult


@router.post(
    "/reminders",
    response_model=RemindersEnvelope,
    summary="Enviar lembretes de reservas (agendador)",
    description=(
        "Rota interna, chamada periodicamente por um agendador com o cabeçalho X-Cron-Token. "
        "Envia um lembrete para cada reserva confirmada que começa dentro de "
        "REMINDER_HOURS_BEFORE horas e ainda não foi lembrada."
    ),
    responses={401: {"description": "Token ausente ou inválido"}},
)
def send_reminders(
    request: Request,
    handler: Annotated[SendRemindersHandler, Depends(get_reminders_handler)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
    background: BackgroundTasks,
    x_cron_token: Annotated[str | None, Header()] = None,
):
    expected = request.app.state.settings.cron_token
    if (
        expected is None
        or not x_cron_token
        or not hmac.compare_digest(x_cron_token, expected.get_secret_value())
    ):
        return JSONResponse(status_code=401, content={"message": "Token inválido."})
    run = handler.handle()
    background.add_task(send_all, mailer, run.emails)
    return RemindersEnvelope(
        data=RemindersResult(reminded_bookings=run.bookings, emails=len(run.emails))
    )
