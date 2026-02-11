import streamlit as st
import httpx
import os

# Backend URL 설정
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
REQUEST_TIMEOUT = 60.0

# 페이지 설정
st.set_page_config(
    page_title="Newsletter RAG Assistant",
    page_icon="📬",
    layout="wide"
)

st.title("📬 Newsletter RAG Assistant")
st.caption("뉴스레터 기반 지식 검색 시스템")


# ============ Helper Functions ============

def call_api(method: str, endpoint: str, **kwargs) -> dict | None:
    """Backend API 호출"""
    try:
        req_timeout = kwargs.pop("timeout", REQUEST_TIMEOUT)
        with httpx.Client(timeout=req_timeout) as client:
            url = f"{BACKEND_URL}{endpoint}"
            if method == "GET":
                response = client.get(url, **kwargs)
            else:
                response = client.post(url, **kwargs)

            if response.status_code == 200:
                return response.json()
            else:
                st.error(f"API Error: {response.status_code} - {response.text}")
                return None
    except httpx.TimeoutException:
        st.error("요청 시간이 초과되었습니다. 다시 시도해주세요.")
        return None
    except Exception as e:
        st.error(f"연결 오류: {str(e)}")
        return None


# ============ Sidebar ============

with st.sidebar:
    st.header("📊 시스템 상태")

    # 시스템 통계 조회
    if st.button("상태 새로고침", use_container_width=True):
        stats = call_api("GET", "/stats")
        if stats:
            st.session_state["stats"] = stats

    # 통계 표시
    if "stats" in st.session_state:
        stats = st.session_state["stats"]
        col1, col2 = st.columns(2)
        with col1:
            st.metric("뉴스레터", stats.get("newsletters", 0))
        with col2:
            st.metric("벡터", stats.get("vectors", 0))

        scheduler = stats.get("scheduler", {})
        if scheduler.get("running"):
            st.success("스케줄러 실행 중")
        else:
            st.warning("스케줄러 중지됨")

    st.divider()

    st.header("🔄 동기화")
    if st.button("지금 동기화", use_container_width=True):
        with st.spinner("Gmail 동기화 중... (최대 10분 소요)"):
            result = call_api("POST", "/sync", timeout=600.0)
            if result:
                gmail = result.get("gmail_result", {})
                etl = result.get("etl_result", {})
                st.success(
                    f"동기화 완료!\n"
                    f"- 새 이메일: {gmail.get('inserted_count', 0)}개\n"
                    f"- 처리됨: {etl.get('processed', 0)}개"
                )
                # 통계 새로고침
                stats = call_api("GET", "/stats")
                if stats:
                    st.session_state["stats"] = stats

    st.divider()

    st.header("📧 최근 뉴스레터")
    newsletters = call_api("GET", "/newsletters", params={"limit": 5})
    if newsletters and newsletters.get("items"):
        for nl in newsletters["items"]:
            with st.expander(f"{nl['subject'][:30]}...", expanded=False):
                st.caption(f"📤 {nl['from_address']}")
                st.caption(f"📅 {nl['received_at']}")
                status = "✅ 처리됨" if nl["processed"] else "⏳ 대기 중"
                st.caption(status)
    else:
        st.info("수집된 뉴스레터가 없습니다.")


# ============ Helper: 쿼리 분석 파이프라인 표시 ============

def render_analysis(a: dict, expanded: bool = False):
    """쿼리 분석 과정을 단계별 파이프라인으로 표시"""
    if not a:
        return

    needs_retrieval = a.get("needs_retrieval", True)

    with st.expander("🔍 쿼리 분석 파이프라인", expanded=expanded):
        # --- Step 1: Routing ---
        st.markdown("**Step 1. Routing**")
        if needs_retrieval:
            st.success("검색 필요 → RAG 파이프라인 실행")
        else:
            st.info("검색 불필요 → 직접 답변")
            return

        st.divider()

        # --- Step 2: Query Rewrite ---
        st.markdown("**Step 2. Query Rewrite**")
        col1, col2 = st.columns(2)
        with col1:
            st.caption("원본 질문")
            st.markdown(f"`{a.get('original_query', '')}`")
        with col2:
            st.caption("변환된 검색어")
            st.markdown(f"`{a.get('rewritten_query', '')}`")

        if a.get("keywords"):
            st.caption(f"키워드: {', '.join(a['keywords'])}")

        st.divider()

        # --- Step 3: HyDE ---
        st.markdown("**Step 3. HyDE (Hypothetical Document)**")
        if a.get("hypothetical_document"):
            st.markdown(f"> {a['hypothetical_document']}")
        else:
            st.caption("가상 문서 없음")

        st.divider()

        # --- Step 4: Multi-Query ---
        st.markdown("**Step 4. Multi-Query Expansion**")
        if a.get("multi_queries"):
            for i, mq in enumerate(a["multi_queries"], 1):
                st.markdown(f"  {i}. `{mq}`")
        else:
            st.caption("다중 쿼리 없음")

        st.divider()

        # --- Step 5: Filters + Results ---
        st.markdown("**Step 5. 검색 실행**")
        filter_parts = []
        if a.get("date_from") or a.get("date_to"):
            filter_parts.append(f"날짜: {a.get('date_from', '?')} ~ {a.get('date_to', '?')}")
        if a.get("sender_filter"):
            filter_parts.append(f"발신인: {a['sender_filter']}")

        if filter_parts:
            st.caption("필터: " + " | ".join(filter_parts))
        else:
            st.caption("필터 없음 (전체 검색)")

        chunks_found = a.get("chunks_found", 0)
        if chunks_found > 0:
            st.success(f"검색 결과: {chunks_found}개 청크")
        else:
            st.warning("검색 결과: 0개 청크")


# ============ Main Chat Interface ============

# 채팅 기록 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 기존 메시지 표시
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        # 쿼리 분석 결과 표시
        if message["role"] == "assistant" and message.get("analysis"):
            render_analysis(message["analysis"], expanded=False)

        # 출처 표시 (assistant 메시지만)
        if message["role"] == "assistant" and message.get("citations"):
            with st.expander("📚 출처 보기", expanded=False):
                for cite in message["citations"]:
                    source = cite.get("source", {})
                    st.markdown(
                        f"**[{cite['index']}]** {source.get('subject', 'Unknown')}\n"
                        f"- 발신: {source.get('from_address', '')}\n"
                        f"- 날짜: {source.get('received_at', '')}"
                    )
                    if cite.get("cited_text"):
                        st.caption(f'"{cite["cited_text"][:100]}..."')
                    st.divider()

# 사용자 입력
if prompt := st.chat_input("뉴스레터에 대해 질문하세요"):
    # 사용자 메시지 추가
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Assistant 응답
    with st.chat_message("assistant"):
        with st.spinner("답변 생성 중..."):
            response = call_api("POST", "/chat", json={"query": prompt})

        if response:
            answer_text = response.get("text", "응답을 생성할 수 없습니다.")
            citations = response.get("citations", [])
            analysis = response.get("analysis")

            # 쿼리 분석 과정 표시
            if analysis:
                render_analysis(analysis, expanded=True)

            st.markdown(answer_text)

            # 출처 표시
            if citations:
                with st.expander("📚 출처 보기", expanded=False):
                    for cite in citations:
                        source = cite.get("source", {})
                        st.markdown(
                            f"**[{cite['index']}]** {source.get('subject', 'Unknown')}\n"
                            f"- 발신: {source.get('from_address', '')}\n"
                            f"- 날짜: {source.get('received_at', '')}"
                        )
                        if cite.get("cited_text"):
                            st.caption(f'"{cite["cited_text"][:100]}..."')
                        st.divider()

            # 메시지 저장
            st.session_state.messages.append({
                "role": "assistant",
                "content": answer_text,
                "citations": citations,
                "analysis": analysis,
            })
        else:
            error_msg = "응답을 받을 수 없습니다. 백엔드 연결을 확인하세요."
            st.error(error_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_msg,
                "citations": []
            })

# 채팅 기록 초기화 버튼
if st.session_state.messages:
    if st.button("💬 대화 초기화"):
        st.session_state.messages = []
        st.rerun()
