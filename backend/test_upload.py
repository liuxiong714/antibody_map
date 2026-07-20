import asyncio
from app.models.base import async_session
from app.services.literature_service import upload_literature


async def test():
    with open("test_doc.pdf", "rb") as f:
        data = f.read()

    async with async_session() as db:
        r = await upload_literature(db, data, "test.pdf", "test")
        print("Result:", r.id if r else "None")


asyncio.run(test())
