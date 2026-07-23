from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DiseaseDict(Base):
    __tablename__ = "disease_dict"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    name_cn: Mapped[str] = mapped_column(String(100))
    name_en: Mapped[Optional[str]] = mapped_column(String(100))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    vaccine: Mapped[Optional[str]] = mapped_column(String(200))
