class DuplicateEmailError(Exception):
    """O endereço de e-mail já está cadastrado."""


class AuthenticationError(Exception):
    """Credenciais ou sessão inválidas."""


class InvalidCredentialsError(AuthenticationError):
    """Falha de login sem indicar se a conta existe."""


class ForbiddenError(Exception):
    """A conta autenticada não tem permissão para a operação."""


class MemberNotFoundError(Exception):
    """O membro solicitado não existe."""


class DuplicateMemberEmailError(Exception):
    """O e-mail já pertence a outro membro."""


class UserNotFoundError(Exception):
    """A conta de acesso solicitada não existe."""


class CourtNotFoundError(Exception):
    """A quadra solicitada não existe."""


class DuplicateCourtNameError(Exception):
    """Já existe uma quadra com este nome."""


class CourtInUseError(Exception):
    """A quadra tem reservas futuras ativas e não pode ser excluída."""


class BookingNotFoundError(Exception):
    """A reserva não existe ou não é visível para a conta autenticada."""


class SlotUnavailableError(Exception):
    """O horário já está reservado e o pedido não aceitou entrar na fila."""


class DuplicateBookingError(Exception):
    """A conta já tem um pedido ativo que se sobrepõe a este horário nesta quadra."""


class BookingNotEditableError(Exception):
    """A reserva foi cancelada ou já começou."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidBookingError(Exception):
    """Dados da reserva inválidos para as regras do negócio."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class BookingPermissionError(Exception):
    """Somente quem fez a reserva (ou um administrador) pode alterá-la."""


class CourtUnderMaintenanceError(Exception):
    """O horário pedido coincide com uma manutenção da quadra."""


class MaintenanceNotFoundError(Exception):
    """A janela de manutenção não existe nesta quadra."""


class MaintenanceConflictError(Exception):
    """Há reservas no período e o pedido não autorizou cancelá-las."""

    def __init__(self, count: int) -> None:
        super().__init__(count)
        self.count = count


class OrganizerAttendanceError(Exception):
    """Quem organiza a partida já está confirmado e não responde presença."""


class FeeNotFoundError(Exception):
    """Taxa inexistente (ou de outro membro, na área do jogador)."""


class FeeAlreadyPaidError(Exception):
    """Taxa já paga não pode ser alterada, excluída nem paga de novo."""
