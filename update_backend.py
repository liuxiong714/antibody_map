import sys

# Update map_data.py
f = r"e:\linux\trae_project\antibody_map01\backend\app\api\v1\map_data.py"
d = open(f, encoding="utf-8").read()
old = """    year_end: Optional[int] = Query(None, description="\u7ed3\u675f\u5e74\u4efd"),
    db: AsyncSession = Depends(get_db),
):
    \"\"\"\u83b7\u53d6\u7701\u4efd\u7ea7\u805a\u5408\u5730\u56fe\u6570\u636e\"\"\"
    data = await map_service.get_province_data(
        db=db,
        disease=disease,
        data_type=data_type,
        province=province,
        age_group=age_group,
        year_start=year_start,
        year_end=year_end,
    )"""
new = """    year_end: Optional[int] = Query(None, description="\u7ed3\u675f\u5e74\u4efd"),
    gender: Optional[str] = Query(None, description="\u6027\u522b"),
    occupation: Optional[str] = Query(None, description="\u804c\u4e1a"),
    db: AsyncSession = Depends(get_db),
):
    \"\"\"\u83b7\u53d6\u7701\u4efd\u7ea7\u805a\u5408\u5730\u56fe\u6570\u636e\"\"\"
    data = await map_service.get_province_data(
        db=db,
        disease=disease,
        data_type=data_type,
        province=province,
        age_group=age_group,
        year_start=year_start,
        year_end=year_end,
        gender=gender,
        occupation=occupation,
    )"""
d = d.replace(old, new)
open(f, "w", encoding="utf-8").write(d)
print("map_data.py done")

# Update map_service.py
f2 = r"e:\linux\trae_project\antibody_map01\backend\app\services\map_service.py"
d2 = open(f2, encoding="utf-8").read()

# Update function signature to add gender and occupation params
old_sig = "    year_end: Optional[int] = None,\n) -> list[dict]:"
new_sig = "    year_end: Optional[int] = None,\n    gender: Optional[str] = None,\n    occupation: Optional[str] = None,\n) -> list[dict]:"
d2 = d2.replace(old_sig, new_sig)

# Add age_group filter (after province filter)
old_age = "    if province:\n        base = base.where(DataPoint.province.ilike(f\"%{province}%\"))"
new_age = "    if province:\n        base = base.where(DataPoint.province.ilike(f\"%{province}%\"))\n    if age_group:\n        base = base.where(DataPoint.age_group == age_group)"
d2 = d2.replace(old_age, new_age)

# Add gender and occupation filters (after year_end)
old_year = "    if year_end:\n        base = base.where(DataPoint.collection_year <= year_end)\n\n    result = await db.execute(base)"
new_year = "    if year_end:\n        base = base.where(DataPoint.collection_year <= year_end)\n    if gender:\n        base = base.where(DataPoint.population.ilike(f\"%{gender}%\"))\n    if occupation:\n        base = base.where(DataPoint.population.ilike(f\"%{occupation}%\"))\n\n    result = await db.execute(base)"
d2 = d2.replace(old_year, new_year)

open(f2, "w", encoding="utf-8").write(d2)
print("map_service.py done")
