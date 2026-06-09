from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models.db import Professor
from models.schemas import ProfessorResponse

router = APIRouter()


@router.get("", response_model=list[ProfessorResponse])
async def list_professors(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Professor))
    return result.scalars().all()


@router.get("/{professor_id}", response_model=ProfessorResponse)
async def get_professor(professor_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Professor).where(Professor.id == professor_id))
    prof = result.scalar_one_or_none()
    if not prof:
        raise HTTPException(status_code=404, detail="Professor not found")
    return prof
