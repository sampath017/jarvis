from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum

class Category(str, Enum):
    bike = "bike"
    work = "work"
    garden = "garden"
    health = "health"
    general = "general"

class TaskBase(BaseModel):
    title: str
    notes: str = ""
    dueDate: Optional[datetime] = None
    reminderTime: Optional[datetime] = None
    isCompleted: bool = False
    category: Category = Category.general

class TaskCreate(TaskBase):
    id: str

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None
    dueDate: Optional[datetime] = None
    reminderTime: Optional[datetime] = None
    isCompleted: Optional[bool] = None
    category: Optional[Category] = None

class Task(TaskBase):
    id: str

    class Config:
        from_attributes = True
