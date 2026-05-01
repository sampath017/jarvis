from sqlalchemy import Column, String, Boolean, DateTime, Enum as SQLEnum
from database import Base
import enum

class CategoryEnum(str, enum.Enum):
    bike = "bike"
    work = "work"
    garden = "garden"
    health = "health"
    general = "general"

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, index=True)
    notes = Column(String, default="")
    dueDate = Column(DateTime, nullable=True)
    reminderTime = Column(DateTime, nullable=True)
    isCompleted = Column(Boolean, default=False)
    category = Column(SQLEnum(CategoryEnum), default=CategoryEnum.general)
