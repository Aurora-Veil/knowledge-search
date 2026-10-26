-- 一次性回填：search_count 旧口径把翻页也算一次，这里改成只数 page = 1。
-- 只改 search_log 里还能找到对应 (user_id, kind, query, filters) 的行；
-- 日志已清理、或只有翻页记录的旧行保持原值。
--
-- 预演：
--   SELECT count(*) FILTER (WHERE s.n < h.search_count) AS lowers,
--          count(*) FILTER (WHERE s.n > h.search_count) AS raises,
--          count(*) AS matched
--     FROM search_history h JOIN (SELECT ...) s USING (user_id, kind, query, filters);
--
-- 核对用总数相减（历史行数 - matched），不要写 NOT EXISTS 反连接：
-- pg 容器 mem_limit 512 MB，96k × 3M 的反连接会把并行 worker OOM 掉。
--
-- 执行：
--   docker compose -f docker-compose.cluster.yml -f docker-compose.app.yml \
--     exec -T pg psql -U postgres -d knowledge_db < schema/backfill_search_count.sql

BEGIN;

UPDATE search_history h
   SET search_count = s.n
  FROM (
        SELECT user_id, kind, query, filters, count(*) AS n
          FROM search_log
         WHERE page = 1
           AND outcome = 'ok'
         GROUP BY user_id, kind, query, filters
       ) s
 WHERE h.user_id = s.user_id
   AND h.kind    = s.kind
   AND h.query   = s.query
   AND h.filters = s.filters;

COMMIT;
