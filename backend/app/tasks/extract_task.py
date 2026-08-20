import logging
import os
import hashlib
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func, delete

from app.config import settings
from app.core.llm_extractor import LLMExtractor, _classify_llm_error
from app.core.document_parser import extract_text
from app.core.pdf_table_parser import extract_tables_markdown
from app.core.text_preprocessor import preprocess
from app.models.base import async_session
from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.models.extraction_history import ExtractionHistory
from app.models.titer_table import TiterTable
from app.tasks.celery_app import celery_app
from app.tasks.async_runner import run_async
from app.core.minio_client import get_minio_client
from app.core.term_normalizer import normalize_province, CHINA_PROVINCE_NAMES
from app.core.extraction_grounding import (
    ground_extraction,
    validate_extraction_schema,
    validate_data_type as _validate_data_type,
    validate_confidence as _validate_confidence,
    validate_review_status as _validate_review_status,
    ValidationFlags,
)

logger = logging.getLogger("celery.task")


def _compute_age_group(age_min: Optional[int], age_max: Optional[int]) -> Optional[str]:
    """A4：根据 age_min/age_max 生成标准年龄组标签，便于前端筛选和地图聚合。

    规则：
    - 两者都有 → "{min}-{max}岁"
    - 只有 min → "{min}岁及以上"
    - 只有 max → "{max}岁及以下"
    - 都没有 → None
    """
    if age_min is not None and age_max is not None:
        return f"{age_min}-{age_max}岁"
    if age_min is not None:
        return f"{age_min}岁及以上"
    if age_max is not None:
        return f"{age_max}岁及以下"
    return None


# B6：表格 Markdown 哈希缓存（进程级，避免同一文件重抽时重复提取）
_table_hash_cache: dict[str, str] = {}


async def _load_feedback_examples(db) -> list[str]:
    """B9：从数据库加载最近被 rejected 的数据点，格式化为 few-shot 示例。

    返回格式：["省份'XX'错误：应为'YY'", "数值超范围：87.3% 应在0-100之间", ...]
    """
    count = getattr(settings, "LLM_FEEDBACK_FEW_SHOT_COUNT", 5)
    result = await db.execute(
        select(DataPoint)
        .where(DataPoint.review_status == "rejected")
        .order_by(DataPoint.updated_at.desc())
        .limit(count)
    )
    rejected_points = result.scalars().all()
    if not rejected_points:
        return []

    examples: list[str] = []
    for dp in rejected_points:
        issues = []
        if dp.province and dp.province not in CHINA_PROVINCE_NAMES:
            issues.append(f"省份'{dp.province}'不在标准枚举中")
        if dp.value is not None:
            if dp.data_type == "seroprevalence" and not (0 <= float(dp.value) <= 100):
                issues.append(f"阳性率{dp.value}超出0-100范围")
            elif dp.data_type == "gmc" and float(dp.value) < 0:
                issues.append(f"GMC值{dp.value}为负数")
        if not dp.is_grounded:
            issues.append("原文片段无法在文献中定位")
        if dp.confidence == "low":
            issues.append("置信度过低")

        if issues:
            desc = f"[{dp.disease or '未知疾病'}] "
            if dp.province:
                desc += f"{dp.province} "
            desc += "；".join(issues)
            examples.append(desc)

    return examples[:count]


# 本地存储目录（与 literature_service 保持一致）
_LOCAL_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "pdfs"


def _download_pdf(object_name: str) -> Optional[bytes]:
    """从本地文件系统或 MinIO 下载 PDF 文件（多重查找策略）"""
    # 策略1: 直接作为本地路径读取
    local_path = Path(object_name)
    if local_path.exists() and local_path.is_file():
        try:
            return local_path.read_bytes()
        except Exception as e:
            logger.error(f"直接路径读取失败: {e}")

    # 策略2: 从 MinIO 路径中提取文件名，在本地存储目录查找
    # 兼容 Windows 反斜杠路径（Linux 容器内 Path().name 不识别反斜杠）
    filename = str(object_name).replace("\\", "/").split("/")[-1]
    local_candidate = _LOCAL_STORAGE_DIR / filename
    if local_candidate.exists():
        try:
            logger.info(f"从本地存储目录找到文件: {local_candidate}")
            return local_candidate.read_bytes()
        except Exception as e:
            logger.error(f"本地存储读取失败: {e}")

    # 策略3: 搜索本地存储目录中所有文件（兼容不同 UUID 重命名情况）
    expected_suffix = Path(object_name).suffix.lower()
    if _LOCAL_STORAGE_DIR.exists():
        for f in _LOCAL_STORAGE_DIR.iterdir():
            if f.is_file() and (not expected_suffix or f.suffix.lower() == expected_suffix):
                try:
                    logger.info(f"从本地存储目录找到备选文件: {f}")
                    return f.read_bytes()
                except Exception as e:
                    logger.error(f"备选文件读取失败: {e}")
                    continue

    # 策略4: 从 MinIO 下载
    client = get_minio_client()
    if client is None:
        logger.error(
            f"MinIO 不可用，且本地也未找到文件: object_name={object_name}, "
            f"local_dir={_LOCAL_STORAGE_DIR}"
        )
        return None

    try:
        response = client.get_object(
            bucket_name=settings.MINIO_BUCKET_LITERATURE,
            object_name=object_name,
        )
        data = response.read()
        response.close()
        response.release_conn()
        return data
    except Exception as e:
        logger.error(f"MinIO 下载失败: {e}")
        return None


async def _link_subgroup_parents(db, all_data_points: list[DataPoint]) -> None:
    """P1-1：归并子估计的 parent_id 到对应主估计。

    匹配策略（按优先级）：
    1. 子估计的 _parent_group 文本包含主估计的 province 名称，且 disease 和 data_type 匹配
    2. 若无匹配主估计，子估计保持 parent_id=None（独立数据点）

    需要先 flush 让主估计获得 id，再回填子估计的 parent_id。
    """
    # 先 flush，让主估计拿到 id
    await db.flush()

    primaries = [dp for dp in all_data_points if dp.estimate_type == "primary"]
    subgroups = [dp for dp in all_data_points if dp.estimate_type == "subgroup"]

    if not subgroups or not primaries:
        return

    linked = 0
    for sub in subgroups:
        parent_group = getattr(sub, "_parent_group", None) or ""
        # 在主估计中找匹配：disease + data_type 相同，且 parent_group 包含主估计的 province
        best_match = None
        for pri in primaries:
            if pri.disease != sub.disease:
                continue
            if pri.data_type != sub.data_type:
                continue
            # parent_group 文本匹配主估计的 province 或 city
            if pri.province and pri.province in parent_group:
                best_match = pri
                break
            if pri.city and pri.city in parent_group:
                best_match = pri
                break
            # 兜底：parent_group 为空或通用描述，取同 disease+data_type 的第一个主估计
            if not parent_group and best_match is None:
                best_match = pri

        if best_match is not None:
            sub.parent_id = best_match.id
            linked += 1

    if linked:
        logger.info(f"P1-1 子估计归并: {linked}/{len(subgroups)} 个子估计已关联到主估计")


async def _extract_result_to_datapoints(
    literature_id: str,
    extract_result: dict,
    *,
    clean_text: str,
    extractor: Optional[LLMExtractor] = None,
) -> list[DataPoint]:
    """将 LLM 提取结果转换为 DataPoint 列表，并附加：
       1) 精确字符级溯源（grounding）
       2) 强 Schema 校验（province 枚举 / 值域校验）

    A3：当 grounding 失败且 extractor 可用时，用 LLM 重新提取 source_context 再匹配。
    """
    data_points = []

    # ---- 步骤 A：字符级溯源 grounding ----
    source_ctx = extract_result.get("source_context")
    grounding = ground_extraction(clean_text, source_ctx, extract_result)

    # A3：grounding 失败时用 LLM 重抽 source_context
    if not grounding.is_grounded and extractor and getattr(settings, "GROUNDING_LLM_REGROUND", True):
        try:
            new_ctx = await extractor.reground_source_context(clean_text, extract_result)
        except Exception as e:
            logger.warning(f"A3 重抽 source_context 异常: {e}")
            new_ctx = None
        if new_ctx:
            # 用新片段重新 grounding
            grounding = ground_extraction(clean_text, new_ctx, extract_result)
            if grounding.is_grounded:
                logger.info(f"A3 重抽 source_context 后 grounding 成功: {new_ctx[:40]!r}")
            # 无论 grounding 是否成功，都更新 source_context
            extract_result = {**extract_result, "source_context": new_ctx}

    # ---- 步骤 B：强 Schema 校验 + province 枚举 ----
    cleaned, flags = validate_extraction_schema(extract_result, grounded=grounding.is_grounded)

    province_raw = cleaned.get("province")
    if province_raw:
        normalized = normalize_province(province_raw)
        if normalized and normalized in CHINA_PROVINCE_NAMES:
            province = normalized
            if not flags.province_valid:
                flags.province_valid = True
        else:
            province = province_raw
    else:
        province = None

    # ---- 步骤 C：合并 schema flags -> confidence 降级策略 ----
    # 规则（严格但不丢弃数据）：
    #   - 非 grounded        ->  confidence = low
    #   - province 非枚举    ->  confidence = low
    #   - value 超出合理范围 ->  confidence = low
    #   - 多个问题同时存在 ->  confidence = low （最低档），并在 review 列表前置
    confidence = "medium"
    reasons = flags.schema_issues
    if not grounding.is_grounded:
        reasons = reasons + ["not_grounded"]
    if "province_not_in_enum" in reasons:
        confidence = "low"
    if "value_out_of_range" in reasons:
        confidence = "low"
    if "not_grounded" in reasons and confidence != "low":
        # 非 grounding 单独仅降为 medium（保留人工判断空间），如果还有其他问题 -> low
        # 这里保持默认 medium，不做更严降级
        pass
    if len(reasons) >= 2:
        confidence = "low"

    logger.info(
        f"[extract_to_dp] validation: province_ok={flags.province_valid} "
        f"value_range_ok={flags.value_range_valid} grounded={grounding.is_grounded} "
        f"-> confidence={confidence} reasons={reasons}"
    )

    # 保存最终修正过的 source_context（如果 grounding 匹配到更精确的片段）
    final_source_context = (
        grounding.matched_snippet
        if grounding.is_grounded and grounding.matched_snippet
        else (extract_result.get("source_context"))
    )

    common = {
        "literature_id": literature_id,
        "disease": cleaned.get("disease_name"),
        "province": province,
        "city": cleaned.get("city"),
        "age_min": cleaned.get("age_min"),
        "age_max": cleaned.get("age_max"),
        "age_group": _compute_age_group(cleaned.get("age_min"), cleaned.get("age_max")),
        "sample_size": cleaned.get("sample_size"),
        "method": cleaned.get("detection_method"),
        "assay": cleaned.get("antibody_type"),
        "population": cleaned.get("population_type"),
        "collection_year": cleaned.get("sample_year") or cleaned.get("study_start_year"),
        "source_page": cleaned.get("source_page"),
        "source_context": final_source_context,
        # P0：精确字符级溯源字段
        "source_char_start": grounding.source_char_start,
        "source_char_end": grounding.source_char_end,
        "is_grounded": bool(grounding.is_grounded),
        "review_status": "pending",
        "confidence": confidence,
        # P1-1：主估计/子估计层级
        "estimate_type": cleaned.get("estimate_type", "primary"),
    }

    # P1-1：记录 parent_group 标识，供主流程归并子估计的 parent_id
    parent_group = cleaned.get("parent_group")

    # 血清阳性率数据点
    if cleaned.get("positivity_rate") is not None:
        dp_sp = DataPoint(
            data_type="seroprevalence",
            value=cleaned["positivity_rate"],
            unit="%",
            ci_lower=cleaned.get("positivity_ci_lower"),
            ci_upper=cleaned.get("positivity_ci_upper"),
            **common,
        )
        # P1-1：暂存 parent_group 到私有属性，主流程归并时使用
        if parent_group:
            dp_sp._parent_group = parent_group
        data_points.append(dp_sp)

    # GMC 数据点
    if cleaned.get("gmc_value") is not None:
        dp_gmc = DataPoint(
            data_type="gmc",
            value=cleaned["gmc_value"],
            unit=cleaned.get("gmc_unit"),
            ci_lower=cleaned.get("gmc_ci_lower"),
            ci_upper=cleaned.get("gmc_ci_upper"),
            **common,
        )
        if parent_group:
            dp_gmc._parent_group = parent_group
        data_points.append(dp_gmc)

    return data_points


async def _process_literature_async(
    literature_id: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    clear_existing_data: bool = True,
) -> dict:
    """异步文献处理：PDF 解析 → LLM 提取 → 保存数据点（含精确溯源和强 Schema）"""
    async with async_session() as db:
        # 1. 查找文献记录
        result = await db.execute(
            select(Literature).where(Literature.id == literature_id)
        )
        literature = result.scalar_one_or_none()
        if not literature:
            raise ValueError(f"文献不存在: {literature_id}")

        if not literature.file_path and not literature.abstract:
            raise ValueError(f"文献 {literature_id} 既无关联文件也无摘要，无法提取")

        logger.info(
            f"开始处理文献 {literature_id}: title={literature.title}, "
            f"file_path={literature.file_path}, model={model or 'default'}"
        )

        # 2. 获取提取输入：有 PDF 下载全文，无 PDF 但有摘要则直接用摘要
        if literature.file_path:
            file_bytes = _download_pdf(literature.file_path)
            if not file_bytes:
                raise RuntimeError(
                    f"文件下载失败: file_path={literature.file_path}, "
                    f"请确认文件存在于本地或 MinIO"
                )
            logger.info(f"文件下载成功: {len(file_bytes)} bytes")

            # 3. 解析文件文本（按扩展名分发：PDF/CAJ/EPUB/DOCX/TXT/HTML）
            file_ext = ("." + str(literature.file_path).replace("\\", "/").split("/")[-1].split(".")[-1]).lower() \
                if "." in str(literature.file_path).replace("\\", "/").split("/")[-1] else ""
            raw_text = extract_text(file_bytes, file_ext)
            if not raw_text or not raw_text.strip():
                raise RuntimeError(
                    "文件解析后文本为空，可能为扫描件或不支持的格式"
                )
            logger.info(f"文件解析成功: {len(raw_text)} 字符")
        else:
            # 无 PDF，但有摘要：直接用摘要作为提取输入
            raw_text = literature.abstract or ""
            file_ext = ""
            tables_md = ""
            logger.info(f"无 PDF，使用摘要作为提取输入: {len(raw_text)} 字符")

        # 3b. P0-1：PDF/CAJ 文件额外提取结构化表格 Markdown，注入 LLM 提示词
        # B6：表格 Markdown 哈希缓存，同一文件重抽时跳过 pdfplumber 提取
        tables_md = ""
        if file_ext in (".pdf", ".caj"):
            file_hash = hashlib.md5(file_bytes).hexdigest()
            if file_hash in _table_hash_cache:
                tables_md = _table_hash_cache[file_hash]
                logger.info(f"B6 表格 Markdown 命中缓存: {len(tables_md)} 字符 (hash={file_hash[:8]})")
            else:
                try:
                    tables_md = extract_tables_markdown(file_bytes)
                    if tables_md:
                        logger.info(f"P0-1 表格提取成功: {len(tables_md)} 字符 Markdown")
                        _table_hash_cache[file_hash] = tables_md
                    else:
                        logger.info("P0-1 未检测到结构化表格或 pdfplumber 不可用，跳过表格注入")
                except Exception as e:
                    logger.warning(f"P0-1 表格提取失败（不影响纯文本提取）: {e}")
                    tables_md = ""

        # 4. 预处理文本（保留 clean_text 用于 grounding）
        clean_text = preprocess(raw_text)
        logger.info(f"文本预处理完成: {len(clean_text)} 字符")

        # 4b. P2：保存 clean_text 到文件，供溯源查看使用
        try:
            text_dir = Path(settings.MINIO_BUCKET_LITERATURE) if False else Path("data/pdfs")
            text_dir.mkdir(parents=True, exist_ok=True)
            text_path = text_dir / f"{literature_id}.txt"
            text_path.write_text(clean_text, encoding="utf-8")
            logger.info(f"溯源文本已缓存: {text_path}")
        except Exception as e:
            logger.warning(f"缓存溯源文本失败（不影响提取）: {e}")

        # 5. LLM 提取（返回数据点列表）
        extractor = LLMExtractor(model=model, api_key=api_key, base_url=base_url)

        # B9：加载审核反馈示例（rejected 数据点），注入 prompt 提升准确度
        if getattr(settings, "LLM_FEEDBACK_FEW_SHOT", True):
            try:
                feedback_examples = await _load_feedback_examples(db)
                if feedback_examples:
                    extractor.set_feedback_examples(feedback_examples)
            except Exception as e:
                logger.warning(f"B9 加载审核反馈示例失败（不影响提取）: {e}")

        passes = getattr(settings, "LLM_EXTRACTION_PASSES", 2)
        logger.info(f"开始 LLM 提取: model={model or settings.LLM_MODEL}, extraction_passes={passes}")
        extract_results = await extractor.extract_with_retry(
            text=clean_text,
            language="zh",
            title=literature.title or "",
            journal=literature.journal or "",
            pub_year=literature.pub_year,
            tables_md=tables_md,
            extraction_passes=passes,
        )
        logger.info(f"LLM 提取完成: {len(extract_results)} 个数据点")

        # 5b. 清除该文献下已有的旧数据点（防止重新提取时新旧叠加）
        # 使用 ORM delete 确保 cascade 正确处理
        # 当 clear_existing_data=False 时，保留已审核通过(approved)的数据点
        if clear_existing_data:
            old_dp_result = await db.execute(
                select(DataPoint.id).where(DataPoint.literature_id == literature_id)
            )
            old_ids = old_dp_result.scalars().all()
            if old_ids:
                await db.execute(
                    delete(DataPoint).where(DataPoint.literature_id == literature_id)
                )
                logger.info(f"已清除 {len(old_ids)} 个旧数据点（文献 {literature_id}）")
            # P2-tt 试点：一并清除旧滴度矩阵
            await db.execute(
                delete(TiterTable).where(TiterTable.literature_id == literature_id)
            )
        else:
            # 仅清除未审核和已驳回的数据点，保留已审核通过的
            old_dp_result = await db.execute(
                select(DataPoint.id).where(
                    DataPoint.literature_id == literature_id,
                    DataPoint.review_status.in_(["pending", "rejected"]),
                )
            )
            old_ids = old_dp_result.scalars().all()
            if old_ids:
                await db.execute(
                    delete(DataPoint).where(
                        DataPoint.literature_id == literature_id,
                        DataPoint.review_status.in_(["pending", "rejected"]),
                    )
                )
                logger.info(f"已清除 {len(old_ids)} 个未审核/已驳回旧数据点，保留已审核数据点（文献 {literature_id}）")
            # P2-tt 试点：未审核/已驳回的滴度矩阵一并清除，保留已审核
            await db.execute(
                delete(TiterTable).where(
                    TiterTable.literature_id == literature_id,
                    TiterTable.review_status.in_(["pending", "rejected"]),
                )
            )

        # 5c. P2-tt 试点：持久化 LLM 提取到的滴度矩阵（TiterTable）
        titer_tables = extractor.get_titer_tables()
        for tt in titer_tables:
            db.add(TiterTable(
                literature_id=literature_id,
                assay_type=tt["assay_type"],
                ref_antisera=tt["ref_antisera"],
                antigens=tt["antigens"],
                titers=tt["titers"],
                unit=tt.get("unit"),
                quality_score=tt.get("quality_score"),
                source_page=tt.get("source_page"),
                source_context=tt.get("source_context"),
                confidence=tt.get("confidence"),
                review_status=tt.get("review_status", "pending"),
            ))
        if titer_tables:
            logger.info(f"P2-tt 试点: 已持久化 {len(titer_tables)} 张滴度矩阵表（文献 {literature_id}）")

        # 6. 为每个提取数据点创建 DataPoint 记录（含 grounding + schema 校验）
        all_data_points = []
        stats_grounded = 0
        stats_province_ok = 0
        for extract_result in extract_results:
            dp_list = await _extract_result_to_datapoints(
                literature_id,
                extract_result,
                clean_text=clean_text,
                extractor=extractor,
            )
            for dp in dp_list:
                if dp.is_grounded:
                    stats_grounded += 1
                if dp.province in CHINA_PROVINCE_NAMES:
                    stats_province_ok += 1
                db.add(dp)
                all_data_points.append(dp)

        # 6b. P1-1：归并子估计的 parent_id 到对应主估计
        # 逻辑：子估计的 _parent_group 标识匹配主估计的 (province+disease+data_type) 组合
        await _link_subgroup_parents(db, all_data_points)

        stats_primary = sum(1 for dp in all_data_points if dp.estimate_type == "primary")
        stats_subgroup = sum(1 for dp in all_data_points if dp.estimate_type == "subgroup")
        logger.info(
            f"数据点创建完成: {len(all_data_points)} 条 "
            f"(血清阳性率: {sum(1 for dp in all_data_points if dp.data_type == 'seroprevalence')}, "
            f"GMC: {sum(1 for dp in all_data_points if dp.data_type == 'gmc')}, "
            f"grounded: {stats_grounded}/{len(all_data_points) or 1}, "
            f"province_ok: {stats_province_ok}/{len(all_data_points) or 1}, "
            f"primary: {stats_primary}, subgroup: {stats_subgroup})"
        )

        # 7. 更新文献元信息（从所有提取数据点中聚合）
        if extract_results and all_data_points:
            first = extract_results[0]
            if first.get("authors") and not literature.authors:
                literature.authors = first["authors"]
            if first.get("journal") and not literature.journal:
                literature.journal = first["journal"]

            # 从数据点聚合 pub_year（取出现频率最高的 collection_year）
            if not literature.pub_year:
                years = []
                for dp in all_data_points:
                    y = getattr(dp, "collection_year", None)
                    if y:
                        years.append(y)
                if years:
                    literature.pub_year = max(set(years), key=years.count)
                    logger.info(
                        f"[MetadataSync] 文献 {literature_id} 聚合更新 pub_year={literature.pub_year} "
                        f"(来自 {len(all_data_points)} 个数据点)"
                    )

            # 从数据点聚合 province（取出现频率最高的省份）
            if not literature.province:
                provinces = [
                    dp.province for dp in all_data_points
                    if getattr(dp, "province", None) and dp.province in CHINA_PROVINCE_NAMES
                ]
                if provinces:
                    literature.province = max(set(provinces), key=provinces.count)  # 取众数
                    logger.info(
                        f"[MetadataSync] 文献 {literature_id} 聚合更新 province={literature.province} "
                        f"(覆盖{len(set(provinces))}省)"
                    )

        # 7b. 记录 LLM token 用量与费用到 literature 表
        try:
            usage_summary = extractor.get_usage_summary()
            literature.llm_model_used = usage_summary.get("primary_model")
            literature.prompt_tokens = usage_summary.get("total_prompt_tokens", 0)
            literature.completion_tokens = usage_summary.get("total_completion_tokens", 0)
            literature.total_tokens = usage_summary.get("total_tokens", 0)
            literature.llm_cost_usd = usage_summary.get("estimated_cost_usd", 0)
            literature.llm_call_count = usage_summary.get("total_call_count", 0)
            literature.llm_usage_detail = usage_summary.get("models")
            logger.info(
                f"[TokenUsage] 文献 {literature_id} 提取消耗: "
                f"model={literature.llm_model_used}, "
                f"prompt={literature.prompt_tokens}, "
                f"completion={literature.completion_tokens}, "
                f"total={literature.total_tokens}, "
                f"calls={literature.llm_call_count}, "
                f"cost=${literature.llm_cost_usd}"
            )
        except Exception as e:
            logger.warning(f"记录 token 用量失败（不影响提取结果）: {e}")

        # 8. 更新 literature 状态
        usage_summary = extractor.get_usage_summary() if extract_results else {}
        history_status = "success"
        if len(all_data_points) > 0:
            literature.extraction_status = "done"
            literature.extracted_count = len(all_data_points)
            history_status = "success"
        else:
            literature.extraction_status = "done_no_data"
            literature.extracted_count = 0
            history_status = "no_data"
            logger.warning(f"文献 {literature_id} 提取结果为空，状态标记为 done_no_data")

        # 8b. 写入提取历史记录
        try:
            history = ExtractionHistory(
                literature_id=literature_id,
                model=literature.llm_model_used,
                status=history_status,
                data_point_count=len(all_data_points),
                prompt_tokens=usage_summary.get("total_prompt_tokens", 0),
                completion_tokens=usage_summary.get("total_completion_tokens", 0),
                total_tokens=usage_summary.get("total_tokens", 0),
                llm_cost_usd=usage_summary.get("estimated_cost_usd", 0),
                llm_call_count=usage_summary.get("total_call_count", 0),
                llm_usage_detail=usage_summary.get("models"),
            )
            db.add(history)
        except Exception as e:
            logger.warning(f"写入提取历史记录失败（不影响提取结果）: {e}")

        await db.commit()

        # 质量精打：全文已可用，对已审核通过的数据点重新打分（幂等覆盖）
        try:
            approved_result = await db.execute(
                select(DataPoint.id).where(
                    DataPoint.literature_id == literature_id,
                    DataPoint.review_status == "approved",
                )
            )
            approved_ids = approved_result.scalars().all()
            if approved_ids:
                from app.tasks.quality_task import score_data_point_task

                for dp_id in approved_ids:
                    score_data_point_task.delay(str(dp_id))
                logger.info(f"全文精打: 已提交 {len(approved_ids)} 个已审核数据点质量打分")
        except Exception as e:
            logger.warning(f"全文精打任务提交失败（不影响提取结果）: {e}")

        return {
            "literature_id": literature_id,
            "extracted_count": len(all_data_points),
            "data_point_count": len(all_data_points),
        }


@celery_app.task(bind=True, max_retries=3)
def process_literature(
    self,
    literature_id: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    clear_existing_data: bool = True,
):
    """Celery 任务：文献处理（PDF 解析 + AI 提取）"""
    try:
        result = run_async(
            _process_literature_async(
                literature_id, model, api_key, base_url, clear_existing_data
            )
        )
        logger.info(f"文献 {literature_id} 提取完成，数据点: {result['extracted_count']}")
        return result

    except Exception as e:
        err = _classify_llm_error(e)
        err_type = err["type"]
        logger.error(f"文献 {literature_id} 提取失败: [{err_type}] {err['message'][:500]}")

        # 连接类错误：保持 processing 状态快速重试（15s/30s/45s），
        # 只有重试耗尽时才标记 failed，避免瞬时网络故障直接把文献判死。
        is_conn = err_type == "connection_error"

        # 更新状态为 failed（连接类错误在最后一次重试耗尽时才标记）
        async def _mark_failed():
            async with async_session() as db:
                result = await db.execute(
                    select(Literature).where(Literature.id == literature_id)
                )
                lit = result.scalar_one_or_none()
                if lit:
                    lit.extraction_status = "failed"
                    # 写入失败历史记录（错误信息带类型前缀，便于前端/日志诊断）
                    try:
                        history = ExtractionHistory(
                            literature_id=lit.id,
                            model=lit.llm_model_used,
                            status="failed",
                            data_point_count=0,
                            error_message=f"[{err_type}] {err['message'][:2000]}",
                        )
                        db.add(history)
                    except Exception as he:
                        logger.warning(f"写入失败历史记录出错: {he}")
                    await db.commit()

        if not is_conn or self.request.retries >= self.max_retries:
            try:
                run_async(_mark_failed())
            except Exception:
                pass

        if is_conn:
            # 连接类错误：短退避快速重试（避免 60s/120s/240s 的长时间空等）
            retry_in = 15 * (self.request.retries + 1)
            logger.warning(
                f"文献 {literature_id} 连接类错误，{retry_in}s 后快速重试 "
                f"(第 {self.request.retries + 1}/{self.max_retries + 1} 次)"
            )
            raise self.retry(exc=e, countdown=retry_in)

        # 非连接错误：保留原有 60/120/240s 退避重试
        retry_in = 60 * (2 ** self.request.retries)
        raise self.retry(exc=e, countdown=retry_in)
