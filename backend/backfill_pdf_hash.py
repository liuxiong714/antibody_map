"""Backfill pdf_hash for existing literature records."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, ".")

from sqlalchemy import select, update

from app.models.base import async_session
from app.models.literature import Literature
from app.services.literature_service import compute_pdf_hash


async def main():
    async with async_session() as db:
        r = await db.execute(select(Literature).where(Literature.pdf_hash.is_(None)))
        lits = list(r.scalars())
        print(f"Found {len(lits)} literature without pdf_hash")
        updated = 0
        for l in lits:
            if not l.file_path:
                continue
            p = Path(l.file_path)
            if not p.exists():
                print(f"  SKIP (file missing): {l.title[:40]}")
                continue
            h = compute_pdf_hash(p.read_bytes())
            await db.execute(update(Literature).where(Literature.id == l.id).values(pdf_hash=h))
            updated += 1
        await db.commit()
        print(f"Backfilled {updated} records with pdf_hash")


if __name__ == "__main__":
    asyncio.run(main())
