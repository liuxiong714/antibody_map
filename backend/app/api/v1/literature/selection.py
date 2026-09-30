"""文献批量选中 & 标签（编组）管理 —— 从 TXT/CSV 导入匹配、批量打标签。"""

import csv
import io
import logging
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models.literature import Literature
from app.models.literature_tag import Tag
from app.schemas.common import ApiResponse

router = APIRouter()
logger = logging.getLogger("uvicorn")


# ── 匹配工具函数 ──

# UUID 正则（标准 8-4-4-4-12）
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _is_uuid(text: str) -> bool:
    """判断是否为标准 UUID 字符串。"""
    t = text.strip()
    return bool(_UUID_RE.match(t))


def _parse_file_content(raw: str, filename: str) -> list[tuple[int, str]]:
    """
    解析文件内容为 (行号, 清理后的行内容) 列表。

    支持格式：
    - .txt / 无扩展名：每行一条，空行跳过
    - .csv：按逗号分隔，优先识别含「uuid/标题/title」等表头的列；
            若首行看起来不像表头（含 36 字符 UUID 或非短词），则按单列处理
    """
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext == "csv" and len(lines) >= 2:
        # 尝试 CSV 解析
        try:
            reader = csv.reader(io.StringIO(raw))
            rows = list(reader)
            if not rows:
                return []

            # 首行是表头吗？
            header = [h.strip().lower() for h in rows[0]]
            uuid_col = None
            title_col = None
            for i, h in enumerate(header):
                if h in ("uuid", "id", "literature_id", "文献id", "文献编号"):
                    uuid_col = i
                elif h in ("title", "标题", "literature_title", "文献标题", "name"):
                    title_col = i

            if uuid_col is not None or title_col is not None:
                # 有明确表头 → 按指定列取值
                result = []
                for row_idx, row in enumerate(rows[1:], start=2):
                    val = ""
                    if uuid_col is not None and uuid_col < len(row) and row[uuid_col].strip():
                        val = row[uuid_col].strip()
                    elif title_col is not None and title_col < len(row) and row[title_col].strip():
                        val = row[title_col].strip()
                    if val:
                        result.append((row_idx, val))
                return result

            # 无明确表头 → 回退：逐行取第一个非空单元格
            result = []
            for row_idx, row in enumerate(rows, start=1):
                for cell in row:
                    cell = cell.strip()
                    if cell:
                        result.append((row_idx, cell))
                        break
            return result
        except Exception:
            pass  # CSV 解析失败 → 回退到 TXT 模式

    # 默认：TXT 模式，每行一条
    result = []
    for row_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped:
            result.append((row_idx, stripped))
    return result


async def _match_one(
    db: AsyncSession,
    text: str,
) -> tuple[Literal["matched", "unmatched", "ambiguous"], dict | None]:
    """
    对单条输入进行匹配。

    返回:
      ("matched",    {id, title, match_type}) — 精确命中 1 篇
      ("ambiguous",  {count, candidates})     — 命中多篇，返回前 5 个候选
      ("unmatched",  None)                     — 未找到
    """
    text = text.strip()

    # 1) UUID 精确匹配
    if _is_uuid(text):
        try:
            lit_id = uuid.UUID(text)
            result = await db.execute(
                select(Literature)
                .where(Literature.id == lit_id)
                .options(selectinload(Literature.tags))
            )
            lit = result.scalar_one_or_none()
            if lit:
                return ("matched", {
                    "id": str(lit.id),
                    "title": lit.title,
                    "match_type": "uuid",
                    "authors": lit.authors or "",
                    "pub_year": lit.pub_year,
                    "province": lit.province or "",
                })
            return ("unmatched", None)
        except ValueError:
            pass  # UUID 解析失败 → 继续按标题匹配

    # 2) 标题精确匹配（大小写不敏感、去除首尾空白）
    result = await db.execute(
        select(Literature)
        .where(Literature.title.ilike(text))
        .options(selectinload(Literature.tags))
    )
    exact_hits = result.scalars().all()
    if len(exact_hits) == 1:
        lit = exact_hits[0]
        return ("matched", {
            "id": str(lit.id),
            "title": lit.title,
            "match_type": "title_exact",
            "authors": lit.authors or "",
            "pub_year": lit.pub_year,
            "province": lit.province or "",
        })
    if len(exact_hits) > 1:
        return ("ambiguous", {
            "count": len(exact_hits),
            "candidates": [
                {"id": str(c.id), "title": c.title, "authors": c.authors or ""}
                for c in exact_hits[:5]
            ],
        })

    # 3) 标题模糊匹配（包含关系）
    result = await db.execute(
        select(Literature)
        .where(Literature.title.ilike(f"%{text}%"))
        .options(selectinload(Literature.tags))
        .limit(10)
    )
    fuzzy_hits = result.scalars().all()
    if len(fuzzy_hits) == 1:
        lit = fuzzy_hits[0]
        return ("matched", {
            "id": str(lit.id),
            "title": lit.title,
            "match_type": "title_fuzzy",
            "authors": lit.authors or "",
            "pub_year": lit.pub_year,
            "province": lit.province or "",
        })
    if len(fuzzy_hits) > 1:
        return ("ambiguous", {
            "count": len(fuzzy_hits),
            "candidates": [
                {"id": str(c.id), "title": c.title, "authors": c.authors or ""}
                for c in fuzzy_hits[:5]
            ],
        })

    return ("unmatched", None)


# ── 接口 1：从文件匹配文献 ──

class MatchByTextResponse(BaseModel):
    total_lines: int
    matched_count: int
    unmatched_count: int
    ambiguous_count: int
    matched: list[dict]
    unmatched: list[dict]
    ambiguous: list[dict]


@router.post(
    "/literatures/match-by-text",
    response_model=ApiResponse,
    summary="从 TXT/CSV 文件匹配文献",
    description="接收上传的 TXT/CSV 文件，逐行识别 UUID 或标题，返回匹配预览结果",
)
async def match_by_text(
    file: UploadFile = File(..., description="包含 UUID 或标题的 TXT/CSV 文件"),
    db: AsyncSession = Depends(get_db),
):
    """从文本文件中批量匹配文献。"""
    raw_bytes = await file.read()
    try:
        raw_text = raw_bytes.decode("utf-8-sig")  # 兼容 BOM
    except UnicodeDecodeError:
        raw_text = raw_bytes.decode("gbk", errors="replace")  # 兜底 GBK

    entries = _parse_file_content(raw_text, file.filename or "")
    if not entries:
        raise HTTPException(status_code=400, detail="文件内容为空或无法解析")

    matched_list: list[dict] = []
    unmatched_list: list[dict] = []
    ambiguous_list: list[dict] = []

    for row_idx, text in entries:
        status, payload = await _match_one(db, text)
        if status == "matched" and payload:
            matched_list.append({"line": row_idx, "input": text, **payload})
        elif status == "ambiguous" and payload:
            ambiguous_list.append({"line": row_idx, "input": text, **payload})
        else:
            unmatched_list.append({"line": row_idx, "input": text})

    return ApiResponse(data={
        "total_lines": len(entries),
        "matched_count": len(matched_list),
        "unmatched_count": len(unmatched_list),
        "ambiguous_count": len(ambiguous_list),
        "matched": matched_list,
        "unmatched": unmatched_list,
        "ambiguous": ambiguous_list,
    })


# ── 接口 2：批量给文献加/去标签 ──

class BatchTagItem(BaseModel):
    tag_id: str | None = None
    tag_name: str | None = None  # 若 tag_id 为空，按名称查找/创建
    color: str | None = "#1677ff"


class BatchTagsRequest(BaseModel):
    literature_ids: list[str]
    tags: list[BatchTagItem]  # 要添加的标签（不存在时会自动创建）
    action: Literal["add", "remove", "set"] = "add"
    # add:   保留原有标签 + 追加新标签
    # remove: 从每篇文献上移除指定标签（不影响其他标签）
    # set:   全量替换为指定标签


class BatchTagsResult(BaseModel):
    success_count: int
    failed_count: int
    tag_ids_used: list[str]
    tag_names_used: list[str]


@router.post(
    "/literatures/batch-tags",
    response_model=ApiResponse,
    summary="批量给文献设置标签（编组）",
    description="给多篇文献批量添加/移除/替换标签。若指定 tag_name 但标签不存在，会自动创建",
)
async def batch_set_tags(
    req: BatchTagsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量设置文献标签。"""
    if not req.literature_ids:
        raise HTTPException(status_code=400, detail="literature_ids 不能为空")
    if not req.tags:
        raise HTTPException(status_code=400, detail="tags 不能为空")

    # 1) 解析/创建标签 → 得到 tag_id 列表
    resolved_tags: list[Tag] = []
    for item in req.tags:
        tag: Tag | None = None
        if item.tag_id:
            try:
                tag_uuid = uuid.UUID(item.tag_id)
                result = await db.execute(select(Tag).where(Tag.id == tag_uuid))
                tag = result.scalar_one_or_none()
            except ValueError:
                tag = None

        if tag is None and item.tag_name:
            # 按名称查找或创建
            result = await db.execute(select(Tag).where(Tag.name == item.tag_name.strip()))
            tag = result.scalar_one_or_none()
            if tag is None:
                tag = Tag(name=item.tag_name.strip(), color=item.color or "#1677ff")
                db.add(tag)
                await db.flush()
                logger.info(f"[batch-tags] 自动创建标签: id={tag.id}, name={tag.name}")

        if tag is None:
            raise HTTPException(
                status_code=400,
                detail="无法解析标签：既没有有效的 tag_id 也没有 tag_name",
            )
        resolved_tags.append(tag)

    # 2) 逐篇文献处理标签
    success_count = 0
    failed_count = 0

    for lit_id_str in req.literature_ids:
        try:
            lit_uuid = uuid.UUID(lit_id_str)
        except ValueError:
            failed_count += 1
            continue

        result = await db.execute(
            select(Literature)
            .where(Literature.id == lit_uuid)
            .options(selectinload(Literature.tags))
        )
        lit = result.scalar_one_or_none()
        if not lit:
            failed_count += 1
            continue

        if req.action == "set":
            lit.tags = list(resolved_tags)
        elif req.action == "add":
            existing_ids = {t.id for t in lit.tags}
            for t in resolved_tags:
                if t.id not in existing_ids:
                    lit.tags.append(t)
        elif req.action == "remove":
            remove_ids = {t.id for t in resolved_tags}
            lit.tags = [t for t in lit.tags if t.id not in remove_ids]

        success_count += 1

    await db.commit()

    return ApiResponse(data={
        "success_count": success_count,
        "failed_count": failed_count,
        "tag_ids_used": [str(t.id) for t in resolved_tags],
        "tag_names_used": [t.name for t in resolved_tags],
    })
