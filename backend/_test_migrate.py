import asyncio, logging, traceback, sys
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

def _run_migrations():
    from alembic.config import Config
    from alembic import command
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    print("Database migrations applied successfully")

async def main():
    try:
        await asyncio.to_thread(_run_migrations)
        print("SUCCESS")
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()

asyncio.run(main())
