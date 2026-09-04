from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Member(Base):
    __tablename__ = "members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(180), index=True)
    electorate: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    party: Mapped[str] = mapped_column(String(40), index=True)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    term_start: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    parliament_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    attendance_alias: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    attendance = relationship("Attendance", back_populates="member", cascade="all, delete-orphan")
    donations = relationship("Donation", back_populates="member")
    division_votes = relationship("DivisionVote", back_populates="member", cascade="all, delete-orphan")


class SittingDay(Base):
    __tablename__ = "sitting_days"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    evidence_url: Mapped[str] = mapped_column(Text)
    document_kind: Mapped[str] = mapped_column(String(30), default="Hansard")
    document_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attendance_count: Mapped[int] = mapped_column(Integer, default=0)
    scrape_status: Mapped[str] = mapped_column(String(30), default="ok")
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    attendance = relationship("Attendance", back_populates="sitting_day", cascade="all, delete-orphan")


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("sitting_day_id", "member_id", name="uq_attendance_day_member"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sitting_day_id: Mapped[int] = mapped_column(ForeignKey("sitting_days.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="present")
    source_token: Mapped[str | None] = mapped_column(String(100), nullable=True)

    sitting_day = relationship("SittingDay", back_populates="attendance")
    member = relationship("Member", back_populates="attendance")


class Division(Base):
    __tablename__ = "divisions"
    __table_args__ = (UniqueConstraint("sitting_date", "sequence", name="uq_division_date_sequence"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    sitting_date: Mapped[date] = mapped_column(Date, index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    evidence_url: Mapped[str] = mapped_column(Text)
    document_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ayes_count: Mapped[int] = mapped_column(Integer, default=0)
    noes_count: Mapped[int] = mapped_column(Integer, default=0)
    pair_count: Mapped[int] = mapped_column(Integer, default=0)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    votes = relationship("DivisionVote", back_populates="division", cascade="all, delete-orphan")


class DivisionVote(Base):
    __tablename__ = "division_votes"
    __table_args__ = (UniqueConstraint("division_id", "member_id", name="uq_division_member"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    division_id: Mapped[int] = mapped_column(ForeignKey("divisions.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    choice: Mapped[str] = mapped_column(String(20), index=True)  # aye, no, pair
    source_token: Mapped[str | None] = mapped_column(String(100), nullable=True)

    division = relationship("Division", back_populates="votes")
    member = relationship("Member", back_populates="division_votes")


class Donation(Base):
    __tablename__ = "donations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    donor: Mapped[str] = mapped_column(Text)
    recipient: Mapped[str] = mapped_column(Text, index=True)
    gift_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    election: Mapped[str | None] = mapped_column(Text, nullable=True)
    political_donation: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    reconciliation_status: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    electorate: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    recipient_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), nullable=True, index=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    member = relationship("Member", back_populates="donations")


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scraper: Mapped[str] = mapped_column(String(50), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_written: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
