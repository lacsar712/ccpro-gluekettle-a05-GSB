from datetime import datetime, timezone
from typing import ClassVar, Optional

from sqlalchemy import Index
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
    melt_certs: list["MeltCert"] = Relationship(back_populates="kettle")


class CookLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    taken_at: datetime = Field(default_factory=utcnow)
    peak_temp_c: float
    operator: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="cooks")


class MeltCert(SQLModel, table=True):
    """溶化证：一炉一张，证号本锅内不得与现行（未核销）证重复。"""

    __tablename__ = "meltcert"
    __table_args__ = (
        # 本锅现行证号唯一：仅约束未核销的证，核销后同号可再开。
        Index(
            "uq_meltcert_kettle_certno_active",
            "kettle_id",
            "cert_no",
            unique=True,
            postgresql_where="used_at IS NULL",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    cert_no: int = Field(index=True)
    melt_temp_c: float
    issued_by: str = ""
    issued_at: datetime = Field(default_factory=utcnow)
    used_at: Optional[datetime] = Field(default=None, index=True)
    used_by: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="melt_certs")
