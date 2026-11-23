from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.entities import (
    Availability,
    DayPeriod,
    PartnerSuggestion,
    PlayerProfile,
    SkillLevel,
)


class AvailabilityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday: int = Field(ge=0, le=6, description="0 = segunda-feira ... 6 = domingo")
    period: DayPeriod = Field(
        description="morning (7h-12h), afternoon (12h-18h), evening (18h-22h)"
    )

    @classmethod
    def of(cls, item: Availability) -> "AvailabilityItem":
        return cls(weekday=item.weekday, period=item.period)


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_level: SkillLevel | None = Field(
        description="beginner, intermediate, advanced, competitive; null para não informar"
    )
    availability: list[AvailabilityItem] = Field(default_factory=list, max_length=21)

    @field_validator("availability")
    @classmethod
    def unique(cls, value: list[AvailabilityItem]) -> list[AvailabilityItem]:
        if len({(item.weekday, item.period) for item in value}) != len(value):
            raise ValueError("Cada dia e período só pode aparecer uma vez.")
        return value


class ProfileResponse(BaseModel):
    skill_level: SkillLevel | None
    availability: list[AvailabilityItem]

    @classmethod
    def of(cls, profile: PlayerProfile) -> "ProfileResponse":
        return cls(
            skill_level=profile.skill_level,
            availability=[AvailabilityItem.of(item) for item in profile.availability],
        )


class ProfileEnvelope(BaseModel):
    data: ProfileResponse


class PartnerResponse(BaseModel):
    id: int
    name: str
    skill_level: SkillLevel
    shared_availability: list[AvailabilityItem]

    @classmethod
    def of(cls, item: PartnerSuggestion) -> "PartnerResponse":
        return cls(
            id=item.id,
            name=item.name,
            skill_level=item.skill_level,
            shared_availability=[AvailabilityItem.of(slot) for slot in item.shared_availability],
        )


class PartnerListResponse(BaseModel):
    data: list[PartnerResponse]
