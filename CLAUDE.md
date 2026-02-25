# Newsletter RAG - 개발 참고

## DB 스키마 규칙
- MSSQL 스키마 이름: `newsletter` (`dbo` 아님)
  - `newsletter.raw_email`: `processed BIT` 플래그로 ETL 완료 여부 추적
  - `newsletter.email_chunks`: `chroma_id`로 Chroma 벡터와 1:1 연결
  - `newsletter.sync_state`: Gmail 히스토리 ID 보관, 항상 row 1개만 존재
- **DATETIMEOFFSET 타입(-155)**: pyodbc가 자동 변환하지 않음 → `struct.unpack("<6hI2h", ...)` 직접 파싱, `db/connection.py`의 `add_output_converter(-155, ...)`로 등록

## Chroma ↔ MSSQL 연결 구조
- Chroma 각 벡터의 메타데이터에 `email_id`(int)를 저장 → MSSQL pre-filter 후 `$in` where 필터로 날짜/발신인 조건 적용
- 코사인 거리 → 유사도 변환식: `score = 1 - (distance / 2)`, 기본 임계값 0.3
- Chroma ID는 UUID v4 (`vectorstore/chroma_store.py`의 `generate_chroma_id()`)

## Gmail 인증
- Docker 컨테이너 내부에서는 OAuth 브라우저 인증 불가 → 로컬에서 `scripts/setup_gmail_auth.py` 먼저 실행해 `token.json` 생성 후 볼륨 마운트
- `credentials.json`, `token.json` 모두 `.gitignore` 대상

## 이메일 수집
- **발신인 기반** (`SYNC_SENDERS`): 스케줄러 자동 동기화 및 `/sync` 엔드포인트에서 사용. `config.py`에 기본 발신인 목록 있음
- **쿼리 기반** (`category:promotions OR label:newsletter`): `gmail/fetcher.py`의 `fetch_new_newsletters()`
- `gmail_id` UNIQUE 제약으로 중복 수집 자동 방지

## RAG 파이프라인 핵심 수치
- 청크: 512토큰, 오버랩 50토큰
- 임베딩 배치: 최대 100개/회
- 검색 top_k: 서브쿼리당 10개, 병렬 병합 후 최종 15개
- LLM max_tokens: 쿼리 분석 1024, 답변 생성 2048

## 쿼리 타입별 처리 분기
- `simple / aggregation / opinion` → sub_queries 1개 → `generate_answer()`
- `comparison / temporal_comparison / multi_topic / multi_hop` → sub_queries 2~4개 병렬 검색 → `generate_structured_answer()`

## 풋터 제거 안전장치
`etl/preprocessor.py`에서 마지막 50줄 내 시그널 패턴 탐색 후 절삭하되, 탐색 지점이 전체 텍스트의 70% 이전이면 제거하지 않음 (본문 과도한 절삭 방지)
