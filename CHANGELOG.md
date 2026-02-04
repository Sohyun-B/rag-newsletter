# Newsletter RAG System - 작업 내역

## 2026-02-04 작업 요약

### 1. 인프라 설정 및 실행

**Docker Compose 실행 완료**
- `docker compose up --build -d`로 backend(FastAPI), frontend(Streamlit) 컨테이너 빌드 및 실행
- Backend: http://localhost:8000
- Frontend: http://localhost:8501

**MSSQL 포트 변경**
- 기본 포트로 원격 MSSQL 서버 연결 실패하여 `.env`에서 실제 운영 포트로 변경

**token.json 읽기 전용 해제**
- Gmail OAuth 토큰 만료 시 컨테이너 내에서 갱신할 수 있도록 `docker-compose.yml`에서 `:ro` 제거

---

### 2. MSSQL DATETIMEOFFSET 에러 수정

- pyodbc가 MSSQL의 `DATETIMEOFFSET` 타입(SQL type -155)을 처리하지 못하는 문제 해결
- `db/connection.py`에 output converter 등록

```python
def _handle_datetimeoffset(dto_value):
    tup = struct.unpack("<6hI2h", dto_value)
    return datetime(tup[0], tup[1], tup[2], tup[3], tup[4], tup[5], tup[6] // 1000,
                    timezone(timedelta(hours=tup[7], minutes=tup[8])))

# get_db_connection()에서 연결 시 converter 등록
conn.add_output_converter(-155, _handle_datetimeoffset)
```

---

### 3. 발신인 기반 Gmail 이메일 수집 기능 추가

기존에는 `category:promotions OR label:newsletter` 쿼리로 최근 이메일만 수집 가능했으나, 특정 발신인의 과거 이메일을 대량 수집하는 기능 추가.

**수정 파일:**
- `backend/gmail/fetcher.py` - `fetch_emails_by_senders()` 함수 추가
- `backend/gmail/__init__.py` - export 추가
- `backend/main.py` - `POST /sync/senders` 엔드포인트 추가

**API 사용법:**
```json
POST /sync/senders
{
    "senders": ["example@newsletter.com"],
    "max_per_sender": 500
}
```

---

### 4. 이메일 전처리(preprocessor.py) 개선

6개 뉴스레터 발신인의 HTML을 분석하여, 발신인별 하드코딩 없이 범용 패턴 기반으로 노이즈를 제거하도록 개선.

**수정 파일:** `backend/etl/preprocessor.py`

#### 4-1. 이미지 alt 텍스트 필터링

| 구분 | Before | After |
|------|--------|-------|
| `[이미지: 공유하기]` | 보존됨 | 제거 |
| `[이미지: Ad]` | 보존됨 | 제거 |
| `[이미지: ]` (빈 alt) | 보존됨 | 제거 |
| `[이미지: A photograph of...]` (긴 캡션) | 보존됨 | 보존 (콘텐츠) |

판단 기준:
- 2자 미만: 무조건 제거
- 20자 초과: 무조건 보존 (콘텐츠 설명일 가능성 높음)
- 2~20자: 키워드 매칭 (`공유, 게시, 홈페이지, logo, ad` 등이 포함되면 제거)

#### 4-2. HTML 단계 불필요 요소 제거 강화

- 1픽셀 트래킹 이미지 (`width=1` 또는 `height=1`)
- `display:none` 스타일 요소
- 텍스트 없이 이미지만 있는 빈 링크

#### 4-3. 풋터 자동 감지 및 절삭

텍스트 마지막 50줄 범위에서 풋터 시그널 패턴이 처음 등장하는 줄을 찾아 그 이하를 절삭.

풋터 시그널 패턴:
- 주소 패턴 (한국/영문)
- 구독 관리 문구 (구독정보 변경, manage email settings 등)
- 뉴스레터 플랫폼 브랜딩
- 이메일 주소 단독 줄
- 프로모션/구독 유도 문구

안전장치: 전체 텍스트의 70% 이상이 잘리면 절삭하지 않음.

#### 4-4. 텍스트 패턴 제거 확장

기존 패턴에 추가:
- 네비게이션 UI: "잘림 없이 보기", "앱에서 보기", "크게 보기"
- 피드백 UI: "오늘 레터 좋았어요", "이런 점은 아쉬워요"
- 공유 버튼: `[이미지:...] 공유하기/게시하기`
- 구독/구매 CTA

#### 전처리 결과 비교

| 발신인 | Before (자) | After (자) | 제거된 항목 |
|--------|-------------|------------|-------------|
| 매경 디깅 | 7,075 | 6,943 | 풋터(주소, SNS 이미지) |
| NYT The World | 13,253 | 11,490 | Ad 이미지, 풋터, 구독관리 |
| The Atlantic | 11,559 | 10,727 | 풋터, 프로모션 구간 |
| 뉴닉 | 5,903 | 5,490 | 이미지 버튼, 풋터, 프로모션 |
| 데이터리안 | 7,357 | 6,907 | SNS 이미지, 풋터 |
| 모두레터 | 1,643 | 1,521 | 풋터(주소, 구독관리) |

---

### 변경된 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| `docker-compose.yml` | token.json `:ro` 제거 |
| `backend/db/connection.py` | DATETIMEOFFSET output converter 추가 |
| `backend/etl/preprocessor.py` | 이미지 필터링, 풋터 절삭, 패턴 확장 |
| `backend/gmail/fetcher.py` | `fetch_emails_by_senders()` 함수 추가 |
| `backend/gmail/__init__.py` | 새 함수 export 추가 |
| `backend/main.py` | `POST /sync/senders` 엔드포인트 추가 |

---

### 현재 상태

- Docker 컨테이너: backend, frontend 정상 실행 중
- MSSQL / Gmail 연결: 정상
- DB 데이터: 뉴스레터 수집 완료, 전부 미처리(processed=0) 상태
- 다음 단계: ETL 실행 (전처리 → 청킹 → 임베딩 → 벡터DB 저장) 필요
