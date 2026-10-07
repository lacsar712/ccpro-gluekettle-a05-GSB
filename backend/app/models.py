from datetime import datetime, timezone
from typing import ClassVar, Optional

from sqlalchemy import Index, text
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    role: str = "worker"


class Workshop(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    alley: str = ""
    kettles: list["Kettle"] = Relationship(back_populates="workshop")


class Kettle(SQLModel, table=True):
    STATUS_COLD: ClassVar[str] = "cold"
    STATUS_BOILING: ClassVar[str] = "boiling"
    STATUS_DRAWN: ClassVar[str] = "drawn"

    id: Optional[int] = Field(default=None, primary_key=True)
    workshop_id: int = Field(foreign_key="workshop.id")
    code: str
    status: str = STATUS_COLD
    bench: int = 0
    workshop: Optional[Workshop] = Relationship(back_populates="kettles")
    cooks: list["CookLog"] = Relationship(back_populates="kettle")
    certs: list["MeltCert"] = Relationship(back_populates="kettle")


class CookLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    taken_at: datetime = Field(default_factory=utcnow)
    peak_temp_c: float
    operator: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="cooks")


class MeltCert(SQLModel, table=True):
    """溶化证：一口锅一张现行（未核销）证，证号在本锅从 1 起顺序发放。"""

    __tablename__ = "meltcerts"
    __table_args__ = (
        # 一口锅至多一张现行证；竞态开证由数据库一锤定音。
        Index(
            "uq_meltcert_active_kettle",
            "kettle_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
        # 本锅现行证号禁止重复；核销后的旧证不再占位。
        # PostgreSQL 与 SQLite 各给一份局部唯一索引。
        Index(
            "uq_meltcert_active_cert_no",
            "kettle_id",
            "cert_no",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id", index=True)
    cert_no: int
    melt_temp_c: float
    issuer: str = ""
    issued_at: datetime = Field(default_factory=utcnow)
    revoked_at: Optional[datetime] = Field(default=None)
    revoker: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="certs")
