
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_point import DataPoint
from app.models.literature import Literature


async def search_literatures(
    db: AsyncSession,
    keyword: str | None = None,
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    extraction_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Literature], int]:
    """高级检索文献"""
    query = select(Literature)
    count_query = select(func.count(Literature.id))

    if keyword:
        like = f"%{keyword}%"
        query = query.where(
            Literature.title.ilike(like)
            | Literature.authors.ilike(like)
            | Literature.journal.ilike(like)
        )
        count_query = count_query.where(
            Literature.title.ilike(like)
            | Literature.authors.ilike(like)
            | Literature.journal.ilike(like)
        )

    if province:
        query = query.where(Literature.province == province)
        count_query = count_query.where(Literature.province == province)

    if extraction_status:
        query = query.where(Literature.extraction_status == extraction_status)
        count_query = count_query.where(Literature.extraction_status == extraction_status)

    if year_start:
        query = query.where(Literature.pub_year >= year_start)
        count_query = count_query.where(Literature.pub_year >= year_start)

    if year_end:
        query = query.where(Literature.pub_year <= year_end)
        count_query = count_query.where(Literature.pub_year <= year_end)

    # disease filter via subquery on data_point
    if disease:
        sub = select(DataPoint.literature_id).where(DataPoint.disease == disease).distinct()
        query = query.where(Literature.id.in_(sub))
        count_query = count_query.where(Literature.id.in_(sub))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(Literature.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def search_data_points(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    population_type: str | None = None,
    data_type: str | None = None,
    review_status: str | None = "approved",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[DataPoint], int]:
    """高级检索数据点"""
    query = select(DataPoint)
    count_query = select(func.count(DataPoint.id))

    if review_status is not None:
        query = query.where(DataPoint.review_status == review_status)
        count_query = count_query.where(DataPoint.review_status == review_status)

    if disease:
        query = query.where(DataPoint.disease == disease)
        count_query = count_query.where(DataPoint.disease == disease)

    if province:
        query = query.where(DataPoint.province.ilike(f"%{province}%"))
        count_query = count_query.where(DataPoint.province.ilike(f"%{province}%"))

    if data_type:
        query = query.where(DataPoint.data_type == data_type)
        count_query = count_query.where(DataPoint.data_type == data_type)

    if year_start:
        query = query.where(DataPoint.collection_year >= year_start)
        count_query = count_query.where(DataPoint.collection_year >= year_start)

    if year_end:
        query = query.where(DataPoint.collection_year <= year_end)
        count_query = count_query.where(DataPoint.collection_year <= year_end)

    if age_min is not None:
        query = query.where(DataPoint.age_min >= age_min)
        count_query = count_query.where(DataPoint.age_min >= age_min)

    if age_max is not None:
        query = query.where(DataPoint.age_max <= age_max)
        count_query = count_query.where(DataPoint.age_max <= age_max)

    if population_type:
        query = query.where(DataPoint.population.ilike(f"%{population_type}%"))
        count_query = count_query.where(DataPoint.population.ilike(f"%{population_type}%"))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(DataPoint.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total
