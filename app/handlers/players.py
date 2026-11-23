"""Perfil de jogo e sugestão de parceiros (US23-US24)."""

from app.domain.entities import Availability, PartnerSuggestion, PlayerProfile, SkillLevel, User
from app.domain.exceptions import ProfileIncompleteError
from app.repositories.contracts import PlayerProfileRepository

MAX_SUGGESTIONS = 50


class GetPlayerProfileHandler:
    def __init__(self, profiles: PlayerProfileRepository) -> None:
        self.profiles = profiles

    def handle(self, user: User) -> PlayerProfile:
        return self.profiles.get(user.id)


class UpdatePlayerProfileHandler:
    """US23: o jogador informa o próprio nível e quando costuma jogar."""

    def __init__(self, profiles: PlayerProfileRepository) -> None:
        self.profiles = profiles

    def handle(
        self, user: User, skill_level: SkillLevel | None, availability: set[Availability]
    ) -> PlayerProfile:
        return self.profiles.save(user.id, skill_level, tuple(sorted(availability)))


class SuggestPartnersHandler:
    """US24: jogadores com nível igual ou vizinho e horários em comum.

    Com disponibilidade informada, só entram jogadores com ao menos um horário em comum, em
    ordem de mais horários em comum e depois de nível mais próximo. Sem disponibilidade, a lista
    considera só o nível.
    """

    def __init__(self, profiles: PlayerProfileRepository) -> None:
        self.profiles = profiles

    def handle(self, user: User) -> list[PartnerSuggestion]:
        me = self.profiles.get(user.id)
        if me.skill_level is None:
            raise ProfileIncompleteError
        rank = me.skill_level.rank
        levels = [level for level in SkillLevel if abs(level.rank - rank) <= 1]
        mine = set(me.availability)

        suggestions: list[tuple[int, int, PartnerSuggestion]] = []
        for other in self.profiles.candidates(user.id, levels):
            assert other.skill_level is not None
            shared = tuple(sorted(mine & set(other.availability)))
            if mine and not shared:
                continue
            distance = abs(other.skill_level.rank - rank)
            suggestion = PartnerSuggestion(other.user_id, other.name, other.skill_level, shared)
            suggestions.append((-len(shared), distance, suggestion))
        # sort estável: empates mantêm a ordem alfabética do repositório.
        suggestions.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in suggestions[:MAX_SUGGESTIONS]]
