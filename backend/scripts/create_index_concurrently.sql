-- V3-05: 生产环境零停机建唯一索引脚本
-- ===========================================
-- 注意: CREATE INDEX CONCURRENTLY 必须在**事务外**执行！
--       不能用 BEGIN/END 包裹，不能放进 alembic 迁移，不能用 -1 (auto-commit off) 模式。
--
-- 使用方法:
--   psql "postgresql://user:pass@host:5432/dbname" -f scripts/create_index_concurrently.sql
-- 或
--   docker exec -it antibody_postgres psql -U postgres -d antibody_map -f /path/to/this.sql
--
-- 前置检查: 确认 data_point 表中无 fingerprint 重复组 (不含 rejected)
--   SELECT literature_id, content_fingerprint, count(*)
--   FROM data_point
--   WHERE content_fingerprint IS NOT NULL AND content_fingerprint != ''
--     AND review_status != 'rejected'
--   GROUP BY literature_id, content_fingerprint
--   HAVING count(*) > 1;
-- 若返回行 → 必须先处理重复数据 (reject/merge) 再跑本脚本。
--
-- 执行后验证:
--   SELECT i.relname AS indexname, idx.indisvalid, idx.indisunique, idx.indisconcurrent
--   FROM pg_index idx JOIN pg_class i ON i.oid = idx.indexrelid
--   JOIN pg_class t ON t.oid = idx.indrelid
--   WHERE i.relname = 'uq_dp_lit_fingerprint';

-- Step 1: 幂等 DROP（若开发/测试库已经手工建过非 CONCURRENTLY 版本）
DROP INDEX IF EXISTS uq_dp_lit_fingerprint;

-- Step 2: CONCURRENTLY 建索引（不锁表，允许并发写入）
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_dp_lit_fingerprint
    ON data_point (literature_id, content_fingerprint)
    WHERE content_fingerprint IS NOT NULL
      AND content_fingerprint != ''
      AND review_status != 'rejected';

-- Step 3: 验证（CONCURRENTLY 构建可能被中断，indisvalid=false 时需重建）
-- V4-03 fix: pg_indexes 没有 indexvalid 列，必须查 pg_index.indisvalid
DO $$
DECLARE
    v_valid boolean;
BEGIN
    SELECT indisvalid INTO v_valid
    FROM pg_index idx JOIN pg_class c ON c.oid = idx.indexrelid
    WHERE c.relname = 'uq_dp_lit_fingerprint';

    IF NOT FOUND OR v_valid IS DISTINCT FROM true THEN
        RAISE WARNING '[V3-05] ⚠️ 索引构建异常 — indisvalid=false 或索引不存在，建议重建:
        DROP INDEX CONCURRENTLY IF EXISTS uq_dp_lit_fingerprint;
        -- 然后重新执行本脚本';
    ELSE
        RAISE NOTICE '[V3-05] ✅ uq_dp_lit_fingerprint 已生效且有效';
    END IF;
END $$;
