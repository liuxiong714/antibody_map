import re
from typing import Optional

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.literature import Literature
from app.config import settings
from app.services.literature._common import (
    logger,
    LOCAL_STORAGE_DIR,
    _clean_filename_title,
    _read_literature_file_bytes,
    _TITLE_EXT_PATTERN,
    _TITLE_YEAR_PREFIX,
    _TITLE_SUFFIX,
)


# 中文字符间下划线 → 斜杠（如 麻疹_风疹 → 麻疹/风疹）
_TITLE_UNDERSCORE_TO_SLASH = re.compile(r"([\u4e00-\u9fff])_([\u4e00-\u9fff])")
# 末尾 _作者姓名（2-4 个中文字，如 血清学调查_苏中华 → 血清学调查）
_TITLE_AUTHOR_SUFFIX = re.compile(r"_([\u4e00-\u9fff]{2,4})$")


def _propose_title_fix(raw: str) -> str:
    """对一条疑似文件名来源的标题提出修正建议。

    依次应用：
    1. _clean_filename_title 的已有逻辑（路径、扩展名、年份前缀、序号后缀）
    2. 末尾 `_作者姓名` 删除（如 血清学调查_苏中华 → 血清学调查）
    3. 中文字符间 `_` → `/`（如 麻疹_风疹 → 麻疹/风疹）
    4. 首尾多余空白/标点清理
    """
    t = _clean_filename_title(raw)
    # 循环去除末尾 _作者姓名（处理 标题_作者1_作者2 → 标题）
    while True:
        new_t = _TITLE_AUTHOR_SUFFIX.sub("", t).strip()
        if new_t == t:
            break
        t = new_t
    # 中文字符间下划线 → 斜杠
    t = _TITLE_UNDERSCORE_TO_SLASH.sub(r"\1/\2", t)
    t = t.strip(" ._-,;:")
    return t if t else raw


async def fix_titles(
    db: AsyncSession,
    dry_run: bool = True,
    fixes: Optional[list[tuple[str, str]]] = None,
) -> dict:
    """扫描并修正文件名来源的文献标题（年份前缀、中文字符间 `_` 等）。

    当提供 `fixes` 时，仅应用指定的修正项（支持手动编辑的标题），
    返回修正数量。
    否则走原有 dry_run 逻辑，返回 {"preview_count": int, "fixed_count": int, "changes": list[dict]}。
    """
    from sqlalchemy import select, update

    # 选择性提交模式
    if fixes is not None:
        fixed = 0
        for lit_id, new_title in fixes:
            await db.execute(
                update(Literature)
                .where(Literature.id == lit_id)
                .values(title=new_title)
            )
            fixed += 1
        await db.commit()
        return fixed

    # 原有预览/全部应用模式
    stmt = select(Literature).order_by(Literature.created_at)
    result = await db.execute(stmt)
    lits = result.scalars().all()

    changes = []
    for lit in lits:
        proposed = _propose_title_fix(lit.title)
        if proposed == lit.title:
            continue
        changes.append({
            "id": str(lit.id),
            "old_title": lit.title,
            "new_title": proposed,
        })

    if not dry_run and changes:
        for c in changes:
            await db.execute(
                update(Literature)
                .where(Literature.id == c["id"])
                .values(title=c["new_title"])
            )
        await db.commit()

    return {
        "preview_count": len(changes),
        "fixed_count": 0 if dry_run else len(changes),
        "changes": changes,
    }


_TITLE_VERIFY_SYSTEM_PROMPT = (
    "你是一个文献标题提取助手。给定一段学术文献文本内容，提取该文献的真实标题。"
    "只返回标题文本本身，不要附加任何解释、引号或标点。"
    "如果文本中无法确定标题，返回空字符串。"
)

_TITLE_VERIFY_USER_PROMPT = (
    "以下是某篇文献的文本内容片段（开头部分）。请提取该文献的标题：\n\n{text}"
)


async def ai_verify_titles(
    db: AsyncSession,
    limit: int = 50,
    model: Optional[str] = None,
) -> dict:
    """用 LLM 从文献文档内容中提取真实标题，与数据库存储标题比对找出差异。

    只处理有文档文件的文献（file_path 非空），从文档中提取开头文本后调用 LLM
    提取标题，与数据库存储的 title 字段比对。

    返回 {"total": int, "verified": int, "mismatches": list[dict]}。
    """
    from difflib import SequenceMatcher
    from openai import AsyncOpenAI

    from app.core.document_parser import extract_text

    # 查询有文档文件的文献
    stmt = (
        select(Literature)
        .where(
            and_(
                Literature.file_path.isnot(None),
                Literature.deleted_at.is_(None),
            )
        )
        .order_by(Literature.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    lits = result.scalars().all()

    if not lits:
        return {"total": 0, "verified": 0, "mismatches": []}

    # 初始化 LLM 客户端
    effective_model = model or settings.LLM_MODEL
    # 解析 API 配置
    api_key = settings.LLM_API_KEY
    base_url = settings.LLM_BASE_URL
    # 处理 vendor 前缀
    api_model = effective_model
    if ":" in effective_model:
        parts = effective_model.split(":")
        if parts[0] in ("ollama", "deepseek", "qwen", "openai"):
            api_model = ":".join(parts[1:])
    # 处理 Ollama 本地地址
    _url = (base_url or "").rstrip("/")
    if "localhost" in _url or "127.0.0.1" in _url:
        _url = getattr(settings, "OLLAMA_BASE_URL", _url)
    client = AsyncOpenAI(
        api_key=api_key or "ollama",
        base_url=_url or "http://localhost:11434/v1",
        timeout=30,
    )

    mismatches = []
    verified = 0

    for lit in lits:
        # 读取文件内容
        try:
            file_bytes = _read_literature_file_bytes(lit.file_path)
            if not file_bytes:
                continue
            ext = (
                "." + str(lit.file_path).replace("\\", "/").split("/")[-1].split(".")[-1]
            ).lower() if "." in str(lit.file_path).replace("\\", "/").split("/")[-1] else ""
            doc_text = extract_text(file_bytes, ext)
            if not doc_text or len(doc_text.strip()) < 200:
                continue
        except Exception as e:
            logger.debug(f"[AI标题验证] 读取文献 {lit.id} 文件失败: {e}")
            continue

        # 调用 LLM 提取标题
        try:
            resp = await client.chat.completions.create(
                model=api_model,
                messages=[
                    {"role": "system", "content": _TITLE_VERIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": _TITLE_VERIFY_USER_PROMPT.format(
                        text=doc_text[:2000]
                    )},
                ],
                temperature=0.1,
                max_tokens=200,
            )
            ai_title = (resp.choices[0].message.content or "").strip().strip("\"'").strip()
        except Exception as e:
            logger.debug(f"[AI标题验证] LLM 调用失败 {lit.id}: {e}")
            continue

        verified += 1
        if not ai_title:
            continue

        # 比对相似度
        stored = (lit.title or "").strip()
        # 简单归一化后比较
        _norm = lambda s: re.sub(r"\s+", "", s).lower()
        sim = SequenceMatcher(None, _norm(stored), _norm(ai_title)).ratio()
        if sim < 0.6:
            mismatches.append({
                "id": str(lit.id),
                "stored_title": stored,
                "ai_title": ai_title,
                "similarity": round(sim, 4),
            })

    return {
        "total": len(lits),
        "verified": verified,
        "mismatches": mismatches,
    }