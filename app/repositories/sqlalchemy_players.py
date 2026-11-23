from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from app.db.models import PlayerAvailabilityModel, UserModel
from app.domain.entities import Availability, DayPeriod, PlayerProfile, SkillLevel


class SqlAlchemyPlayerProfileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _availability(self, user_ids: list[int]) -> dict[int, tuple[Availability, ...]]:
        found: dict[int, list[Availability]] = defaultdict(list)
        if user_ids:
            rows = self.session.execute(
                select(PlayerAvailabilityModel).where(PlayerAvailabilityModel.user_id.in_(user_ids))
            ).scalars()
            for row in rows:
                found[row.user_id].append(Availability(row.weekday, DayPeriod(row.period)))
        return {user_id: tuple(sorted(found[user_id])) for user_id in user_ids}

    @staticmethod
    def _profile(user: UserModel, availability: tuple[Availability, ...]) -> PlayerProfile:
        level = SkillLevel(user.skill_level) if user.skill_level else None
        return PlayerProfile(user.id, user.name, level, availability)

    def get(self, user_id: int) -> PlayerProfile:
        user = self.session.get(UserModel, user_id)
        assert user is not None
        return self._profile(user, self._availability([user_id])[user_id])

    def save(
        self, user_id: int, skill_level: SkillLevel | None, availability: tuple[Availability, ...]
    ) -> PlayerProfile:
        try:
            self.session.execute(
                update(UserModel)
                .where(UserModel.id == user_id)
                .values(skill_level=skill_level.value if skill_level else None)
            )
            self.session.execute(
                delete(PlayerAvailabilityModel).where(PlayerAvailabilityModel.user_id == user_id)
            )
            if availability:
                self.session.execute(
                    insert(PlayerAvailabilityModel),
                    [
                        {"user_id": user_id, "weekday": item.weekday, "period": item.period.value}
                        for item in availability
                    ],
                )
            self.session.commit()
        except BaseException:
            self.session.rollback()
            raise
        self.session.expire_all()
        return self.get(user_id)

    def candidates(self, user_id: int, levels: Sequence[SkillLevel]) -> Sequence[PlayerProfile]:
        users = self.session.scalars(
            select(UserModel)
            .where(
                UserModel.id != user_id,
                UserModel.skill_level.in_([level.value for level in levels]),
            )
            .order_by(UserModel.name, UserModel.id)
        ).all()
        availability = self._availability([user.id for user in users])
        return [self._profile(user, availability[user.id]) for user in users]
