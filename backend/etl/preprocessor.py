import re
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 제거할 HTML 태그들
REMOVE_TAGS = ["script", "style", "footer", "nav", "aside", "header"]

# 의미없는 이미지 alt 키워드 (소문자)
USELESS_IMG_ALT = {
    "공유", "게시", "홈페이지", "인스타그램", "유튜브", "링크드인",
    "웹에서 보기", "앱에서 보기", "stibee", "logo", "ad", "icon",
    "arrow", "button", "banner", "spacer", "pixel", "tracker",
    "adchoices", "zeta", "whatsapp", "share", "tweet", "post",
    "forward", "author headshot",
}

# 제거할 텍스트 패턴 (구독 해지, 소셜 미디어, UI 요소 등)
REMOVE_PATTERNS = [
    # 구독/수신 관련
    r"unsubscribe",
    r"구독\s*취소",
    r"구독\s*해지",
    r"수신\s*거부",
    # 브라우저/앱 보기
    r"view\s+in\s+browser",
    r"브라우저에서\s*보기",
    r"잘림\s*없이\s*(읽기|보기)",
    r"앱에서\s*보기",
    r"웹에서\s*보기",
    r"크게\s*보기",
    # 저작권/법적
    r"©\s*\d{4}",
    r"all\s+rights\s+reserved",
    r"privacy\s+policy",
    r"terms\s+of\s+service",
    # 피드백 UI
    r"오늘\s*레터.*?좋았어요.*",
    r"이런\s*점은\s*아쉬워요.*",
    # 공유 버튼 (이미지 태그 포함)
    r"\[이미지:.*?\]\s*(공유하기|게시하기)",
    r"공유하기\s*$",
    r"게시하기\s*$",
    # CTA / 프로모션
    r"Subscribe to The Times",
    r"Get The New York Times app",
    r"Connect with us on:",
    # 빈 이미지 태그 잔여
    r"\[이미지:\s*\]",
    # 단독 구분자 줄
    r"^\s*\|\s*$",
]

# 풋터 감지 시그널 패턴
FOOTER_SIGNALS = [
    # 주소 패턴
    r"서울시\s*.+구\s*.+[로길]",
    r"\d+\s+(street|avenue|eighth|water)\b",
    r"\b\d{5}\b",  # 우편번호
    # 구독/연락처 관리
    r"구독\s*(정보|이메일)\s*(변경|수정)",
    r"구독정보\s*변경",
    r"manage\s+(your\s+)?email\s+settings",
    r"email\s+preferences",
    r"this\s+email\s+was\s+sent\s+to",
    r"click\s+here",
    r"고객센터",
    r"의견\s*전하기",
    r"카톡\s*친구\s*추가",
    r"California\s+Notices",
    # 플랫폼 브랜딩
    r"스티비가\s+함께",
    r"좋은\s+뉴스레터를\s+만들고",
    r"The New York Times Company",
    r"The Atlantic Monthly Group",
    # 이메일 주소 단독 줄
    r"^[\w.+-]+@[\w-]+\.[\w.]+$",
    # 구독 CTA
    r"^구독하기$",
    r"구독\s*이메일\s*변경",
    r"구독\s*정보\s*수정",
    # 프로모션/광고 시그널
    r"Introducing\s+Premium",
    r"Unlimited\s+access\s+for\s+you",
    r"less\s+than\s+\$\d+\s+a\s+week",
    r"오늘\s*레터는?\s*어땠나요",
    r"피드백을\s*반영해",
    r"더\s*다양하게\s*즐기는",
    r"데이터\s*분석\s*능력을?\s*업그레이드",
    r"오픈\s*카톡방\s*참여",
    r"데이터리안\s*콘텐츠와?\s*함께",
    r"you('ve)?\s+signed\s+up\s+to\s+receive",
    r"^Subscribe$",
]

# 컴파일된 풋터 패턴
_FOOTER_PATTERNS = [re.compile(p, re.IGNORECASE) for p in FOOTER_SIGNALS]


def is_meaningful_alt(alt: str) -> bool:
    """alt 텍스트가 실제 콘텐츠 설명인지 판단"""
    alt_stripped = alt.strip()
    alt_lower = alt_stripped.lower()
    if len(alt_stripped) < 2:
        return False
    if len(alt_stripped) > 20:
        return True
    if any(kw in alt_lower for kw in USELESS_IMG_ALT):
        return False
    return True


def remove_unwanted_elements(soup: BeautifulSoup) -> None:
    """불필요한 HTML 요소 제거"""
    # 태그 제거
    for tag in REMOVE_TAGS:
        for element in soup.find_all(tag):
            element.decompose()

    # 1픽셀 트래킹 이미지 제거
    for img in soup.find_all("img"):
        width = img.get("width", "")
        height = img.get("height", "")
        if width in ("1", "0") or height in ("1", "0"):
            img.decompose()

    # display:none 요소 제거
    for element in soup.find_all(style=re.compile(r"display\s*:\s*none", re.IGNORECASE)):
        element.decompose()

    # 구독 해지 링크 등 제거
    for a in soup.find_all("a"):
        href = a.get("href", "").lower()
        text = a.get_text().lower()
        if any(kw in href or kw in text for kw in ["unsubscribe", "구독취소", "수신거부"]):
            a.decompose()
            continue
        # 텍스트 없이 이미지만 있는 링크 제거
        if not a.get_text(strip=True) and a.find("img"):
            a.decompose()


def clean_text(text: str) -> str:
    """텍스트 정리"""
    # 불필요한 패턴 제거
    for pattern in REMOVE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)

    # 연속 공백/줄바꿈 정리
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\t+", " ", text)

    # 앞뒤 공백 제거
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)

    return text.strip()


def remove_footer(text: str, scan_lines: int = 50) -> str:
    """
    풋터 자동 감지 및 절삭

    마지막 scan_lines줄 내에서 풋터 시그널이 처음 등장하는 줄을 찾아
    그 줄부터 끝까지 잘라낸다.
    안전장치: 전체의 70% 이상이 잘리면 절삭하지 않음.
    """
    lines = text.split("\n")
    total = len(lines)

    if total < 5:
        return text

    search_start = max(0, total - scan_lines)

    # 스캔 범위 내에서 풋터 시그널이 처음 등장하는 줄 찾기
    first_signal = None
    for i in range(search_start, total):
        line = lines[i].strip()
        if not line:
            continue
        if any(p.search(line) for p in _FOOTER_PATTERNS):
            first_signal = i
            break

    if first_signal is None:
        return text

    # 안전장치: 70% 이상 잘리면 절삭하지 않음
    if first_signal < total * 0.3:
        return text

    result = "\n".join(lines[:first_signal]).strip()
    return result


def html_to_text(html: str) -> str:
    """HTML을 텍스트로 변환"""
    soup = BeautifulSoup(html, "html.parser")

    # 불필요한 요소 제거
    remove_unwanted_elements(soup)

    # 이미지: 콘텐츠성 alt만 보존, 나머지 제거
    for img in soup.find_all("img"):
        alt = img.get("alt", "")
        if alt and is_meaningful_alt(alt):
            img.replace_with(f"[이미지: {alt}]")
        else:
            img.decompose()

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

    # 풋터 제거
    text = remove_footer(text)

    # 최소 길이 체크
    if len(text) < 50:
        logger.warning(f"Preprocessed text too short: {len(text)} chars")

    return text
