"""
疾病名称标准化迁移脚本。

将 data_points 表中所有疾病名称通过 normalize_disease 规范化，
确保旧数据中的"麻腮风"、"丁型病毒性肝炎"等名称被统一。

使用前需确保后端环境变量已配置（.env 文件存在）。

运行：
  cd backend
  python -m scripts.normalize_diseases
"""

import asyncio
import sys
from pathlib import Path

# 确保后端模块可导入
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, distinct, update, text
from app.core.term_normalizer import normalize_disease
from app.models.data_point import DataPoint
from app.models.base import async_session


async def normalize_all_diseases():
    """规范化数据库中所有疾病名称。"""
    async with async_session() as session:
        # 查询所有不重复的疾病名称
        result = await session.execute(
            select(distinct(DataPoint.disease)).where(DataPoint.disease.isnot(None))
        )
        raw_diseases = [row[0] for row in result.all() if row[0]]

        print(f"[疾病标准化] 发现 {len(raw_diseases)} 个不重复的疾病名称")

        mapping: dict[str, str] = {}
        updated_count = 0
        skip_count = 0

        for raw in sorted(raw_diseases):
            normalized = normalize_disease(raw)
            if normalized and normalized != raw:
                mapping[raw] = normalized
                # 执行更新
                result = await session.execute(
                    update(DataPoint)
                    .where(DataPoint.disease == raw)
                    .values(disease=normalized)
                )
                affected = result.rowcount
                updated_count += affected
                print(f"  「{raw}」 → 「{normalized}」  ({affected} 条记录)")
            else:
                skip_count += 1

        await session.commit()

        print(f"\n[疾病标准化] 完成：更新 {updated_count} 条，跳过 {skip_count} 个已标准名称")

        if mapping:
            print("\n变更汇总：")
            for old, new in mapping.items():
                print(f"  {old!r} → {new!r}")


if __name__ == "__main__":
    asyncio.run(normalize_all_diseases())
