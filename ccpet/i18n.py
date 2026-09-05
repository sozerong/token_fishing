"""화면에 뜨는 말을 한국어/영어로 고른다.

번역표의 **열쇠가 한국어 원문 자체다.** 별도의 키(`theme.fishing.name` 같은)를
두지 않는 이유: 테마·펫 정의가 이미 한국어 문자열을 값으로 들고 있고, 그걸 키로
바꾸려면 자료 구조를 통째로 갈아엎어야 한다. 지금 방식이면 표시하는 자리만
`t()`로 감싸면 되고, 자료 구조는 손대지 않아도 된다.

대신 대가가 하나 있다. 한국어 라벨을 고치면 번역이 조용히 원문으로 떨어진다.
그래서 `tests/test_i18n.py`가 모든 테마·펫의 라벨이 번역표에 있는지 검사한다 —
빠뜨리면 테스트가 먼저 잡는다.

숫자가 끼어드는 문장은 단어 치환으로 안 된다(어순이 다르다). 그런 건 `fmt()`가
문장 틀을 통째로 골라 쓴다.
"""

from __future__ import annotations

import locale
import os

LANG = "ko"
"""지금 쓰는 언어. popup.main()이 시작할 때 한 번 정한다."""

CHOICES = ("ko", "en")


def system_lang() -> str:
    """시스템이 한국어면 ko, 아니면 en.

    환경변수를 먼저 본다 — 리눅스·macOS에서는 이쪽이 실제로 쓰는 값이고,
    locale.getlocale()은 setlocale을 안 부른 상태에서 None이 나오기도 한다.
    """
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name, "")
        if value:
            return "ko" if value.lower().startswith("ko") else "en"
    try:
        loc = (locale.getlocale()[0] or "").lower()
    except (ValueError, TypeError):
        loc = ""
    return "ko" if loc.startswith("ko") or "korea" in loc else "en"


def resolve(setting: str | None) -> str:
    """설정값 -> 실제로 쓸 언어. 모르는 값이면 시스템에 맡긴다."""
    return setting if setting in CHOICES else system_lang()


def set_lang(code: str | None) -> str:
    global LANG
    LANG = resolve(code)
    return LANG


def t(text: str) -> str:
    """라벨 한 개. 번역이 없으면 원문 그대로 — 화면이 비는 것보다는 낫다."""
    return text if LANG == "ko" else _EN.get(text, text)


def fmt(key: str, **kw) -> str:
    """숫자가 끼어드는 문장. 언어마다 어순이 달라 틀째로 고른다."""
    ko, en = _LINES[key]
    return (ko if LANG == "ko" else en).format(**kw)


_LINES: dict[str, tuple[str, str]] = {
    "tokens":      ("{n:,} 토큰",                        "{n:,} tokens"),
    "pct_tokens":  ("{mark}{pct:.0f}%  ·  {n:,} 토큰",   "{mark}{pct:.0f}%  ·  {n:,} tokens"),
    "activity":    ("{act} {tier} · {action} {n:,}회",   "{act} {tier} · {action} ×{n:,}"),
    "reset":       ("리셋까지 {mark}{h}시간 {m}분",       "resets in {mark}{h}h {m}m"),
    "reset_none":  ("리셋까지 —",                        "reset —"),
    "weekly_pct":  ("주간 {pct:.0f}%  ·  {n:,} 토큰",    "week {pct:.0f}%  ·  {n:,} tokens"),
    "weekly":      ("주간 {n:,} 토큰",                   "week {n:,} tokens"),
    "age":         (" {n}분 전",                         " {n}m ago"),
    "no_official": ("{label}(공식수치 없음)",             "{label} (no official figure)"),
    "closed":      ("조업 종료",                         "window closed"),
    "closed_line": ("— 창 종료",                         "— window closed"),
    "idle":        ("사용 기록 없음",                     "no usage yet"),
    "idle_line":   ("— 사용 기록 없음",                   "— no usage yet"),
    "left":        ("· {h}시간 {m}분 남음",              "· {h}h {m}m left"),
    "week_pct":    ("주간 {pct:.0f}%",                   "week {pct:.0f}%"),
}

_EN: dict[str, str] = {
    # ---- 출처 ----
    "공식": "official", "공식·훅": "official·hook", "공식·앱": "official·app",
    "어림": "estimate", "?": "?",

    # ---- 모드 ----
    "축적": "Fill", "고갈": "Drain",

    # ---- 테마 이름 ----
    "낚시": "Fishing", "마을": "Village", "목장": "Ranch", "우주": "Space",
    "정원": "Garden", "광산": "Mine", "도시": "City",

    # ---- 낚시 배경 ----
    "바다 위": "Open sea", "부둣가": "Pier", "갯바위": "Rocks",
    "방파제": "Breakwater", "섬": "Island",
    "차박낚시": "Car camp", "캠핑낚시": "Tent camp",

    # ---- 세는 것 / 활동 / 행위 ----
    "물고기": "fish", "주민": "villagers", "동물": "animals", "별": "stars",
    "꽃": "flowers", "광석": "ore", "차": "cars",
    "입질": "Bites", "북적임": "Bustle", "울음소리": "Calls", "전파": "Signal",
    "개화": "Bloom", "곡괭이질": "Picks", "교통량": "Traffic",
    "캐스팅": "casts", "방문": "visits", "먹이 주기": "feeds", "교신": "calls",
    "물주기": "waterings", "채굴": "digs", "운행": "trips",

    # ---- 낚시 등급 ----
    "빈 바구니": "Empty basket", "잔챙이": "Small fry", "반 바구니": "Half basket",
    "한 바구니": "Full basket", "만선": "Full boat",
    "잠잠": "Still", "잔잔": "Calm", "활발": "Lively", "폭주": "Frenzy",

    # ---- 마을 ----
    "빈 터": "Empty lot", "오두막": "One hut", "작은 마을": "Hamlet",
    "큰 마을": "Village", "번화가": "Town centre",
    "고요": "Silent", "한산": "Quiet", "붐빔": "Busy", "장날": "Market day",

    # ---- 목장 ----
    "빈 우리": "Empty pen", "몇 마리": "A few", "무리": "A herd",
    "큰 무리": "Big herd", "가득한 목장": "Full ranch",
    "낮잠": "Napping", "느긋": "Easy", "야단법석": "Uproar",

    # ---- 우주 ----
    "빈 하늘": "Empty sky", "첫 별": "First star", "성단": "Cluster",
    "은하": "Galaxy", "가득한 우주": "Full sky",
    "정적": "Silence", "미약": "Faint", "폭발": "Burst",

    # ---- 정원 ----
    "맨 흙": "Bare soil", "새싹": "Sprouts", "화단": "Flower bed",
    "만발": "In bloom", "꽃밭": "Full garden",
    "잠듦": "Dormant", "느릿": "Slow", "한창": "Peak",

    # ---- 광산 ----
    "빈 갱도": "Empty shaft", "부스러기": "Scraps", "광맥": "A vein",
    "노다지": "Rich seam", "대박": "Motherlode",
    "멈춤": "Stopped", "전속력": "Full tilt",

    # ---- 도시 ----
    "텅 빈 도로": "Empty road", "드문드문": "Sparse", "차량 행렬": "Steady flow",
    "정체": "Congested", "꽉 막힘": "Gridlock",
    "한밤": "Dead of night", "출퇴근": "Rush hour",

    # ---- 반려동물 ----
    "강아지": "Dog", "고양이": "Cat", "앵무새": "Parrot",
    "고슴도치": "Hedgehog", "햄스터": "Hamster",
    "사료": "kibble", "모이": "seed", "밀웜": "mealworms", "해바라기씨": "seeds",
    "꼬리질": "Tail", "그루밍": "Grooming", "지저귐": "Chirps",
    "꼬물거림": "Wriggles", "볼주머니": "Cheeks", "간식": "treats", "씨앗": "seeds",
    "빈 그릇": "Empty bowl", "한 입": "A bite", "반 그릇": "Half bowl",
    "가득": "Full", "배 터짐": "Stuffed",
    "빈 모이통": "Empty feeder", "반 통": "Half feeder", "넘침": "Overflowing",
    "한 마리": "One worm", "여러 마리": "Several", "그릇 넘침": "Overflowing",
    "한 줌": "A handful",
    "신남": "Excited", "흥분": "Zoomies", "여유": "Relaxed", "산책": "Strolling",
    "장난기": "Playful", "조용": "Quiet", "종알종알": "Chatty", "수다": "Talkative",
    "시끌벅적": "Raucous", "웅크림": "Curled up", "꼬물꼬물": "Wriggling",
    "부산함": "Restless", "쳇바퀴": "On the wheel",
}
