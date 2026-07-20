import asyncio, sys, traceback
from app.models.base import async_session
from app.services.extraction_service import trigger_extraction

LIT_ID = "2d850998-e0ad-4489-8985-5ff92cde9558"

async def main():
    async with async_session() as db:
        try:
            result = await trigger_extraction(db, LIT_ID, model="deepseek-chat")
            sys.stderr.write(f"SUCCESS: {result}\n")
            sys.stdout.write(f"SUCCESS: {result}\n")
        except Exception as e:
            sys.stderr.write(f"ERROR: {e}\n")
            sys.stdout.write(f"ERROR: {e}\n")
            traceback.print_exc()

asyncio.run(main())
