-- ============================================
-- 스키마 생성 확인 쿼리
-- DBeaver에서 schema.sql 실행 후 이 쿼리로 확인
-- ============================================

-- 1. 스키마 존재 확인
SELECT
    name AS schema_name,
    schema_id
FROM sys.schemas
WHERE name = 'newsletter';

-- 2. 테이블 목록 확인
SELECT
    s.name AS schema_name,
    t.name AS table_name,
    t.create_date,
    t.modify_date
FROM sys.tables t
JOIN sys.schemas s ON t.schema_id = s.schema_id
WHERE s.name = 'newsletter'
ORDER BY t.name;

-- 3. 각 테이블 컬럼 상세 확인
SELECT
    t.name AS table_name,
    c.name AS column_name,
    ty.name AS data_type,
    c.max_length,
    c.is_nullable,
    c.is_identity
FROM sys.tables t
JOIN sys.schemas s ON t.schema_id = s.schema_id
JOIN sys.columns c ON t.object_id = c.object_id
JOIN sys.types ty ON c.user_type_id = ty.user_type_id
WHERE s.name = 'newsletter'
ORDER BY t.name, c.column_id;

-- 4. 인덱스 확인
SELECT
    t.name AS table_name,
    i.name AS index_name,
    i.type_desc AS index_type,
    i.is_unique
FROM sys.indexes i
JOIN sys.tables t ON i.object_id = t.object_id
JOIN sys.schemas s ON t.schema_id = s.schema_id
WHERE s.name = 'newsletter'
  AND i.name IS NOT NULL
ORDER BY t.name, i.name;

-- 5. 뷰 확인
SELECT
    s.name AS schema_name,
    v.name AS view_name,
    v.create_date
FROM sys.views v
JOIN sys.schemas s ON v.schema_id = s.schema_id
WHERE s.name = 'newsletter';

-- 6. sync_state 초기 데이터 확인
SELECT * FROM newsletter.sync_state;

-- 7. 테이블 행 수 확인 (빈 테이블 확인)
SELECT 'raw_email' AS table_name, COUNT(*) AS row_count FROM newsletter.raw_email
UNION ALL
SELECT 'email_chunks', COUNT(*) FROM newsletter.email_chunks
UNION ALL
SELECT 'sync_state', COUNT(*) FROM newsletter.sync_state;
