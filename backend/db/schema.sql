-- ============================================
-- Newsletter RAG System - MSSQL Schema
-- DBeaver에서 실행 (project_pm 데이터베이스)
-- ============================================
-- 실행 방법:
--   1. DBeaver에서 project_pm 데이터베이스 연결
--   2. 이 스크립트 전체 선택 후 실행 (Ctrl+Enter)
-- ============================================

-- 스키마 생성
IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = 'newsletter')
BEGIN
    EXEC('CREATE SCHEMA newsletter');
END;

-- ============================================
-- 테이블 생성
-- ============================================

-- 기존 테이블이 있으면 삭제 (초기 설정시에만 주석 해제)
-- DROP TABLE IF EXISTS newsletter.email_chunks;
-- DROP TABLE IF EXISTS newsletter.raw_email;
-- DROP TABLE IF EXISTS newsletter.sync_state;
-- DROP VIEW IF EXISTS newsletter.vw_chunks_with_email;

-- 원본 이메일
IF NOT EXISTS (SELECT * FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id WHERE s.name = 'newsletter' AND t.name = 'raw_email')
BEGIN
    CREATE TABLE newsletter.raw_email (
        id              BIGINT IDENTITY(1,1) PRIMARY KEY,
        gmail_id        NVARCHAR(255) NOT NULL,
        thread_id       NVARCHAR(255),
        from_address    NVARCHAR(500),
        subject         NVARCHAR(1000),
        received_at     DATETIMEOFFSET NOT NULL,
        body_html       NVARCHAR(MAX),
        body_text       NVARCHAR(MAX),
        labels          NVARCHAR(MAX),
        processed       BIT DEFAULT 0,
        created_at      DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET(),
        CONSTRAINT UQ_raw_email_gmail_id UNIQUE (gmail_id)
    );
END;

-- 청크 테이블
IF NOT EXISTS (SELECT * FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id WHERE s.name = 'newsletter' AND t.name = 'email_chunks')
BEGIN
    CREATE TABLE newsletter.email_chunks (
        id              BIGINT IDENTITY(1,1) PRIMARY KEY,
        email_id        BIGINT NOT NULL,
        chunk_index     INT NOT NULL,
        content         NVARCHAR(MAX) NOT NULL,
        chroma_id       NVARCHAR(255),
        metadata_json   NVARCHAR(MAX),
        created_at      DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET(),
        CONSTRAINT FK_email_chunks_raw_email
            FOREIGN KEY (email_id) REFERENCES newsletter.raw_email(id) ON DELETE CASCADE
    );
END;

-- Gmail 동기화 상태
IF NOT EXISTS (SELECT * FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id WHERE s.name = 'newsletter' AND t.name = 'sync_state')
BEGIN
    CREATE TABLE newsletter.sync_state (
        id                  INT IDENTITY(1,1) PRIMARY KEY,
        last_history_id     NVARCHAR(255),
        last_sync_at        DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET()
    );
END;

-- ============================================
-- 인덱스 생성
-- ============================================

-- raw_email 인덱스
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_raw_email_processed' AND object_id = OBJECT_ID('newsletter.raw_email'))
BEGIN
    CREATE INDEX IX_raw_email_processed ON newsletter.raw_email(processed) WHERE processed = 0;
END;

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_raw_email_received_at' AND object_id = OBJECT_ID('newsletter.raw_email'))
BEGIN
    CREATE INDEX IX_raw_email_received_at ON newsletter.raw_email(received_at DESC);
END;

-- email_chunks 인덱스
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_email_chunks_email_id' AND object_id = OBJECT_ID('newsletter.email_chunks'))
BEGIN
    CREATE INDEX IX_email_chunks_email_id ON newsletter.email_chunks(email_id);
END;

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_email_chunks_chroma_id' AND object_id = OBJECT_ID('newsletter.email_chunks'))
BEGIN
    CREATE INDEX IX_email_chunks_chroma_id ON newsletter.email_chunks(chroma_id);
END;

-- ============================================
-- 초기 데이터 삽입
-- ============================================

-- sync_state 초기 레코드 (없으면 삽입)
IF NOT EXISTS (SELECT * FROM newsletter.sync_state)
BEGIN
    INSERT INTO newsletter.sync_state (last_history_id) VALUES (NULL);
END;

-- ============================================
-- 뷰 생성
-- ============================================

-- 기존 뷰 삭제 후 재생성
IF EXISTS (SELECT * FROM sys.views v JOIN sys.schemas s ON v.schema_id = s.schema_id WHERE s.name = 'newsletter' AND v.name = 'vw_chunks_with_email')
BEGIN
    DROP VIEW newsletter.vw_chunks_with_email;
END;
