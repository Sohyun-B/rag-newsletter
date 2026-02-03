import re
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 제거할 HTML 태그들
REMOVE_TAGS = ["script", "style", "footer", "nav", "aside", "header"]

# 제거할 텍스트 패턴 (구독 해지, 소셜 미디어 등)
REMOVE_PATTERNS = [
    r"unsubscribe",
    r"구독\s*취소",
    r"구독\s*해지",
    r"수신\s*거부",
    r"view\s+in\s+browser",
    r"브라우저에서\s*보기",
    r"facebook|twitter|instagram|linkedin|youtube",
    r"©\s*\d{4}",
    r"all\s+rights\s+reserved",
    r"privacy\s+policy",
    r"terms\s+of\s+service",
]


def remove_unwanted_elements(soup: BeautifulSoup) -> None:
    """불필요한 HTML 요소 제거"""
    # 태그 제거
    for tag in REMOVE_TAGS:
        for element in soup.find_all(tag):
            element.decompose()

    # 구독 해지 링크 등 제거
    for a in soup.find_all("a"):
        href = a.get("href", "").lower()
        text = a.get_text().lower()
        if any(pattern in href or pattern in text for pattern in ["unsubscribe", "구독취소", "수신거부"]):
            a.decompose()


def clean_text(text: str) -> str:
    """텍스트 정리"""
    # 불필요한 패턴 제거
    for pattern in REMOVE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # 연속 공백/줄바꿈 정리
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\t+", " ", text)

    # 앞뒤 공백 제거
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)

    return text.strip()


def html_to_text(html: str) -> str:
    """HTML을 텍스트로 변환"""
    soup = BeautifulSoup(html, "html.parser")

    # 불필요한 요소 제거
    remove_unwanted_elements(soup)

    # 이미지 alt 텍스트 보존
    for img in soup.find_all("img"):
        alt = img.get("alt", "")
        if alt:
            img.replace_with(f"[이미지: {alt}]")

    # 링크 텍스트 보존
    for a in soup.find_all("a"):
        text = a.get_text()
        if text:
            a.replace_with(text)

    # 리스트 항목에 bullet 추가
    for li in soup.find_all("li"):
        li.insert(0, "• ")

    # 텍스트 추출
    text = soup.get_text(separator="\n")

    return text


def preprocess_email(html_body: str, text_body: str) -> str:
    """
    이메일 본문 전처리

    Args:
        html_body: HTML 형식 본문
        text_body: Plain text 형식 본문

    Returns:
        정제된 텍스트
    """
    # HTML 우선 사용 (구조 정보 더 많음)
    if html_body and len(html_body) > 50:
        text = html_to_text(html_body)
    elif text_body:
        text = text_body
    else:
        logger.warning("Both HTML and text body are empty")
        return ""

    # 텍스트 정리
    text = clean_text(text)

    # 최소 길이 체크
    if len(text) < 50:
        logger.warning(f"Preprocessed text too short: {len(text)} chars")

    return text
