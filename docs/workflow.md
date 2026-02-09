# Newsletter RAG System - Workflow

## 1. 데이터 수집 (Gmail → MSSQL)

```
Gmail 받은편지함
    │
    ▼
fetcher.py ── 쿼리: "category:promotions OR label:newsletter"
    │           또는 /sync/senders로 특정 발신인 지정
    │
    ▼
newsletter.raw_email 테이블에 INSERT
    (gmail_id, subject, from_address, body_html, body_text 등)
    (gmail_id UNIQUE로 중복 방지)
```

- **자동**: `scheduler.py`가 APScheduler로 **5분마다** `sync_gmail()` 실행
- **수동**: `/sync` 또는 `/sync/senders` 엔드포인트로 트리거

---

## 2. ETL 파이프라인 (전처리 → 청킹 → 임베딩)

```
raw_email (processed=0인 행 조회)
    │
    ▼
preprocessor.py ── HTML → 텍스트 변환
    │                (script, style, footer, 구독취소 링크 제거)
    │
    ▼
chunker.py ── RecursiveCharacterTextSplitter
    │           (512토큰 단위, 50토큰 오버랩)
    │
    ▼
embedder.py ── OpenAI text-embedding-3-small로 임베딩 생성
    │
    ├──▶ Chroma (로컬 파일) ── 벡터 임베딩 저장 (chroma_id 발급)
    │
    └──▶ MSSQL newsletter.email_chunks ── 청크 텍스트 + chroma_id 저장

    raw_email.processed = 1로 업데이트
```

---

## 3. 질문 응답 (`/chat` 엔드포인트)

```
사용자 질문: "AI 트렌드에 대해 알려줘"
    │
    ▼
search.py ── 질문을 OpenAI 임베딩으로 변환
    │
    ▼
Chroma ── 코사인 유사도 검색 (top_k=10)
    │         → chroma_id + distance 반환
    │
    ▼
MSSQL ── chroma_id로 메타데이터 조회
    │       (subject, from_address, received_at, content)
    │
    ▼
agent.py ── 청크를 [문서 1], [문서 2] 형식으로 조합
    │          → OpenAI gpt-4o-mini에 전달
    │          → 시스템 프롬프트: "출처 [1],[2] 형식으로 인용하여 답변"
    │
    ▼
응답: { text: "...[1]...[2]...", citations: [...], sources: [...] }
    │
    ▼
Streamlit UI ── 답변 표시 + "출처 보기" 확장 패널
```

---

## 전체 흐름 요약

| 단계 | 컴포넌트 | 저장소 |
|------|----------|--------|
| 수집 | Gmail API → `fetcher.py` | MSSQL `raw_email` |
| 전처리 | `preprocessor.py` | - |
| 청킹 | `chunker.py` (512토큰) | - |
| 임베딩 | OpenAI `text-embedding-3-small` | Chroma (벡터), MSSQL (메타데이터) |
| 검색 | Chroma 유사도 → MSSQL 조인 | - |
| 답변 | OpenAI `gpt-4o-mini` | - |
| UI | Streamlit 채팅 | 세션 상태 |

---

## 핵심 설계 포인트

**벡터(Chroma)와 메타데이터(MSSQL) 분리 구조**
- 검색은 Chroma에서 빠르게 수행
- 출처 정보(제목, 발신자, 날짜 등)는 MSSQL에서 조회
- `chroma_id`로 두 저장소를 연결
