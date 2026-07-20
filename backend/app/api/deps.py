from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import async_session


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
