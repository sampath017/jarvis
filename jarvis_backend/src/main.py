import sys

# Force stdout and stderr to use UTF-8 to prevent UnicodeEncodeError in Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

import models
import schemas
from database import engine, Base, get_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(lifespan=lifespan)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/tasks", response_model=List[schemas.Task])
async def get_tasks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Task))
    tasks = result.scalars().all()
    return tasks

@app.post("/tasks", response_model=schemas.Task)
async def create_task(task: schemas.TaskCreate, db: AsyncSession = Depends(get_db)):
    # Check if task already exists just in case
    result = await db.execute(select(models.Task).where(models.Task.id == task.id))
    existing_task = result.scalars().first()
    if existing_task:
        raise HTTPException(status_code=400, detail="Task already exists")
    
    db_task = models.Task(**task.model_dump())
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)
    return db_task

@app.put("/tasks/{task_id}", response_model=schemas.Task)
async def update_task(task_id: str, task_update: schemas.TaskUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Task).where(models.Task.id == task_id))
    db_task = result.scalars().first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    update_data = task_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_task, key, value)
        
    await db.commit()
    await db.refresh(db_task)
    return db_task

@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Task).where(models.Task.id == task_id))
    db_task = result.scalars().first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    await db.delete(db_task)
    await db.commit()
    return {"ok": True}
