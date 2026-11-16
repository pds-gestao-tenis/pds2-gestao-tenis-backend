from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint("email = lower(btrim(email))", name="ck_users_email_normalized"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionModel(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemberModel(Base):
    __tablename__ = "members"
    __table_args__ = (
        UniqueConstraint("email", name="uq_members_email"),
        CheckConstraint("email = lower(btrim(email))", name="ck_members_email_normalized"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_members_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(8), default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CourtModel(Base):
    __tablename__ = "courts"
    __table_args__ = (
        CheckConstraint("size_m2 > 0", name="ck_courts_size_positive"),
        CheckConstraint(
            "surface IN ('clay', 'hard', 'grass', 'synthetic')", name="ck_courts_surface"
        ),
        CheckConstraint("max_players BETWEEN 1 AND 50", name="ck_courts_max_players"),
        CheckConstraint("hourly_price >= 0", name="ck_courts_hourly_price"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(255))
    size_m2: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    max_players: Mapped[int] = mapped_column(Integer)
    hourly_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    surface: Mapped[str] = mapped_column(String(10))
    covered: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BookingModel(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('confirmed', 'waitlisted', 'cancelled')", name="ck_bookings_status"
        ),
        CheckConstraint(
            "ends_at - starts_at IN (interval '60 minutes', interval '90 minutes')",
            name="ck_bookings_duration",
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)", name="ck_bookings_cancelled_at"
        ),
        # Duas reservas confirmadas nunca se sobrepõem na mesma quadra.
        ExcludeConstraint(
            ("court_id", "="),
            (text("tstzrange(starts_at, ends_at)"), "&&"),
            using="gist",
            where=text("status = 'confirmed'"),
            name="ex_bookings_confirmed_overlap",
        ),
        Index("ix_bookings_court_status_starts_at", "court_id", "status", "starts_at"),
        Index("ix_bookings_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BookingPlayerModel(Base):
    __tablename__ = "booking_players"
    __table_args__ = (
        CheckConstraint(
            "attendance IN ('pending', 'confirmed', 'declined')",
            name="ck_booking_players_attendance",
        ),
    )

    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    attendance: Mapped[str] = mapped_column(String(10), server_default="pending")


# Nome único sem diferenciar maiúsculas de minúsculas ("Quadra 1" = "quadra 1").
Index("uq_courts_name", func.lower(CourtModel.name), unique=True)


class CourtMaintenanceModel(Base):
    __tablename__ = "court_maintenance"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_court_maintenance_period"),
        Index("ix_court_maintenance_court_ends_at", "court_id", "ends_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id", ondelete="CASCADE"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
