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

DEFAULT = "en"
"""기본 언어.

한때 시스템 로케일을 따라갔다. 그러면 한국어 로케일 기기에서 처음 켠 사람에게만
한국어가 나오는데, 그 기준으로는 이 도구를 받는 사람 대다수가 못 읽는 화면을 본다.
읽을 사람이 정하게 두는 게 낫다 — 기본은 영어, `--ko`를 주면 한국어."""

LANG = DEFAULT
"""지금 쓰는 언어. 각 진입점이 시작할 때 한 번 정한다."""

CHOICES = ("ko", "en")

EXPLICIT = False
"""이번 실행에서 언어를 인자로 골랐는가.

창이 뜰 때 설정 파일을 다시 읽어 언어를 정하는데(popup.Popup 참고), 그게
`--ko`를 덮어써서 "플래그를 줬는데 창만 영어"가 된다. 그 덮어쓰기를 막는 표시."""


def resolve(setting: str | None) -> str:
    """설정값 -> 실제로 쓸 언어. 모르는 값이면 기본값."""
    return setting if setting in CHOICES else DEFAULT


def set_lang(code: str | None) -> str:
    global LANG
    LANG = resolve(code)
    return LANG


def pick(ko: str, en: str) -> str:
    """골라 쓴 언어의 문장. 번역표에 넣을 만큼 재사용되지 않는 한 줄짜리용."""
    return ko if LANG == "ko" else en


def init(argv: list[str]) -> list[str]:
    """`--ko` / `--en` / `--lang ko|en` 을 떼어내고 언어를 정한다.

    모든 진입점(창, 콘솔, --doctor)이 이걸 부른다. 한 곳에서 정해야 창은
    영어인데 콘솔만 한국어인 상태가 안 생긴다.

    `--ko`/`--en`은 **그 실행에만** 적용된다. `--lang ko`는 설정에 적어 둔다 —
    창은 아이콘으로도 띄우니 매번 플래그를 붙일 수가 없어서 기억할 자리가 필요하다.
    한 번 준 플래그가 조용히 눌러앉는 것보다, 기억할지 말지를 이름으로 가르는 게 낫다.

    돌려주는 값은 언어 관련 인자를 걷어낸 나머지 argv.
    """
    global EXPLICIT
    from . import config

    rest: list[str] = []
    chosen: str | None = None
    remember: str | None = None
    skip = False
    for i, arg in enumerate(argv):
        if skip:
            skip = False
            continue
        if arg in ("--ko", "--en"):
            chosen = arg[2:]
        elif arg == "--lang":
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            if nxt not in CHOICES:
                raise ValueError(f"--lang needs one of: {', '.join(CHOICES)}")
            chosen = remember = nxt
            skip = True
        else:
            rest.append(arg)

    settings = config.load()
    if remember and remember != settings.get("lang"):
        settings["lang"] = remember
        config.save(settings)
    EXPLICIT = chosen is not None
    set_lang(chosen or settings.get("lang"))
    return rest


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
    "정원": "Garden", "광산": "Mine", "도시": "City", "양봉": "Apiary",

    # ---- 낚시 배경 ----
    "바다 위": "Open sea", "부둣가": "Pier", "갯바위": "Rocks",
    "방파제": "Breakwater", "섬": "Island",
    "차박낚시": "Car camp", "캠핑낚시": "Tent camp",

    # ---- 세는 것 / 활동 / 행위 ----
    "물고기": "fish", "주민": "villagers", "동물": "animals", "별": "stars",
    "꽃": "flowers", "광석": "ore", "차": "cars", "벌": "bees",
    "입질": "Bites", "북적임": "Bustle", "울음소리": "Calls", "전파": "Signal",
    "개화": "Bloom", "곡괭이질": "Picks", "교통량": "Traffic", "날갯짓": "Wingbeat",
    "캐스팅": "casts", "방문": "visits", "먹이 주기": "feeds", "교신": "calls",
    "물주기": "waterings", "채굴": "digs", "운행": "trips", "채밀": "harvests",

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

    # ---- 양봉 ----
    "빈 벌통": "Empty hive", "첫 벌": "First bee", "일벌 무리": "Worker swarm",
    "꿀 절반": "Half honey", "꿀 가득": "Full honey",
    "붕붕": "Buzzing", "벌떼": "Swarming",
}
