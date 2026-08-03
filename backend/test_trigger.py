import asyncio
from app.models.base import async_session
from app.services.extraction_service import trigger_extraction, get_extraction_status

LIT_ID = "2d850998-e0ad-4489-8985-5ff92cde9558"

async def main():
    async with async_session() as db:
        try:
            result = await trigger_extraction(db, LIT_ID, model="deepseek-chat")
            print("TASK RESULT:", result)
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")

asyncio.run(main())
