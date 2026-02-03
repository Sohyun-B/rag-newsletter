-- ============================================
-- 뷰 생성 (schema.sql 실행 후 별도 실행)
-- ============================================

CREATE VIEW newsletter.vw_chunks_with_email AS
SELECT
    ec.id AS chunk_id,
    ec.chunk_index,
    ec.content,
    ec.chroma_id,
    ec.metadata_json,
    re.id AS email_id,
    re.gmail_id,
    re.subject,
    re.from_address,
    re.received_at,
    re.labels
FROM newsletter.email_chunks ec
INNER JOIN newsletter.raw_email re ON ec.email_id = re.id;
