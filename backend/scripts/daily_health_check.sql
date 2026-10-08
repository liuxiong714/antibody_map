-- V6-04: 数据红线巡检 SQL —— 全 0 即收口
-- 来源: docs/change-checklist.md §4 (最终版 · 2026-10-06 验证通过)
-- ⚠️ seroprevalence 存的是百分比数值 (0-100%), 不是 0-1 小数
--    gmc 是滴度 (1:x), 无上界
-- 用法:
--   psql -U antibody -d antibody_map -f backend/scripts/daily_health_check.sql
--   或通过 Python 包装: python backend/scripts/check_health.py

-- 1. 重复指纹 (uq_dp_lit_fingerprint 唯一索引应全部命中)
SELECT COUNT(*) AS dup_groups FROM (
  SELECT 1 FROM data_point
  WHERE review_status != 'rejected'
    AND content_fingerprint IS NOT NULL AND content_fingerprint != ''
  GROUP BY literature_id, content_fingerprint
  HAVING COUNT(*) > 1) t;

-- 2. pending 超 7 天 (卡 processing) — ⚠️ 业务状态豁免, 仅 warning
SELECT COUNT(*) AS pending_older_than_7d FROM data_point
WHERE review_status = 'pending'
  AND created_at < NOW() - INTERVAL '7 days';

-- 3. approved value 真越界
SELECT COUNT(*) AS bad FROM data_point WHERE review_status = 'approved'
  AND ((data_type = 'seroprevalence' AND (value IS NULL OR value < 0 OR value > 100))
    OR (data_type = 'gmc' AND (value IS NULL OR value < 0)));

-- 4. approved 未溯源 (source_page + source_context 都空)
SELECT COUNT(*) AS bad FROM data_point WHERE review_status = 'approved'
  AND source_page IS NULL
  AND (source_context IS NULL OR btrim(source_context) = '');

-- 5. is_grounded=false 但 approved (语义矛盾)
SELECT COUNT(*) AS bad FROM data_point
WHERE review_status = 'approved' AND is_grounded = FALSE;

-- 6. FK 完整性
SELECT 'dp->lit orphan' AS check, COUNT(*) AS bad FROM data_point dp
  WHERE dp.literature_id NOT IN (SELECT id FROM literature)
UNION ALL
SELECT 'dp->eh orphan', COUNT(*) FROM data_point dp
  WHERE dp.extraction_history_id IS NOT NULL
    AND dp.extraction_history_id::uuid NOT IN (SELECT id FROM extraction_history)
UNION ALL
SELECT 'eh->lit orphan', COUNT(*) FROM extraction_history eh
  WHERE eh.literature_id IS NOT NULL
    AND eh.literature_id NOT IN (SELECT id FROM literature);

-- 7. V8-05 幻觉率红线: is_grounded=false 且 review_status='approved' (应为 0)
-- 与 #5 不同: #5 统计"矛盾点总数", 本条只算"已审核但未溯源"的精准幻觉
SELECT COUNT(*) AS hallucination_count FROM data_point
WHERE review_status = 'approved'
  AND is_grounded = FALSE
  AND (source_context IS NULL OR btrim(source_context) = '');

-- 8. V8-05 幻觉率月度趋势 (监控, 非红线): 按月+模型分组
SELECT date_trunc('month', created_at) AS month,
       model_used,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE is_grounded = FALSE) AS ungrouned,
       ROUND(
         COUNT(*) FILTER (WHERE is_grounded = FALSE)::numeric
         / GREATEST(COUNT(*), 1), 4
       ) AS hallucination_rate
FROM data_point
WHERE created_at > NOW() - INTERVAL '6 months'
GROUP BY 1, 2
ORDER BY 1 DESC NULLS LAST;
