"""화면 컨셉. 같은 숫자를 다른 은유로 그린다.

숫자는 state.GameState 하나뿐이고, 테마는 **말과 그림만** 바꾼다. 새 집계도,
새 분기도 만들지 않는다. 그래서 테마를 아무리 늘려도 정확도에 영향이 없다.

한 화면의 뼈대는 모든 테마가 같다:

    하늘          리셋까지 남은 시간 (해가 높으면 대낮, 낮으면 노을)
    바닥          테마마다 다른 땅 (바다 / 들판 / 우주 ...)
    돌아다니는 것  쓴 양 (마리 수), 움직이는 속도 = 분당 토큰
    고정물        화면 왼쪽의 기지 (배 / 집 / 헛간 ...)
    쌓인 더미      고갈 모드에서 사라진 만큼

그래서 테마는 색 몇 개와 스프라이트 두 개(움직이는 것, 고정물), 그리고 라벨
표만 내놓으면 된다. `px(x, y, w, h, color)` 는 팝업이 넘겨주는 도트 하나 찍는
함수다 — 이 모듈은 tkinter를 알지 못한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


class Px(Protocol):
    def __call__(self, x: float, y: float, w: int, h: int, color: str) -> None: ...


Sprite = Callable[[Px, float, float, str, int], None]
"""(px, x, y, color, direction) -> 움직이는 것 하나. direction 은 +1/-1."""

Base = Callable[[Px, float, float], None]
"""(px, x, y) -> 화면 왼쪽 고정물 하나. y 는 지평선 기준."""


@dataclass(frozen=True, slots=True)
class Theme:
    key: str
    name: str

    unit: str
    """움직이는 것 한 마리를 뭐라 부르나. "물고기", "주민" ..."""

    activity_word: str
    """분당 토큰 등급의 이름. "입질", "북적임" ..."""

    action_word: str
    """요청 한 건을 뭐라 부르나. "캐스팅", "방문" ..."""

    fill_tiers: tuple[tuple[float, str], ...]
    """채운 비율(0~1) -> 등급. 사용률을 알 때 쓴다."""

    catch_tiers: tuple[tuple[float, str], ...]
    """절대 토큰 수 -> 등급. 사용률을 모를 때만 쓴다."""

    activity_tiers: tuple[tuple[float, str], ...]
    """분당 토큰 -> 활동 등급. 네 단계."""

    sky: tuple[tuple[int, int, int], tuple[int, int, int]]
    ground: tuple[tuple[int, int, int], tuple[int, int, int]]

    horizon: str
    """지평선에 찍는 잔무늬 색 (낮). 파도, 풀, 별먼지 ..."""

    horizon_dusk: str
    unit_colors: tuple[str, ...]
    sprite: Sprite
    base: Base

    sun: tuple[str, str] = ("#ffd76e", "#ff9a5a")
    """해 색 (낮, 노을)."""


# 등급 경계는 모든 테마가 공유한다. 숫자가 아니라 부르는 이름만 테마마다 다르다 —
# 경계까지 테마마다 다르면 같은 사용량을 두고 화면이 서로 다른 말을 하게 된다.
_FILL_STEPS = (0.0, 0.01, 0.20, 0.50, 0.80)
_CATCH_STEPS = (0, 5_000, 50_000, 200_000, 1_000_000)
_ACTIVITY_STEPS = (0, 500, 5_000, 50_000)


def _labels(fill_names, catch_names, activity_names) -> dict:
    """세 라벨 표를 한 번에. Theme(...) 안에서 ** 로 펼쳐 쓴다."""
    return {
        "fill_tiers": tuple(zip(_FILL_STEPS, fill_names)),
        "catch_tiers": tuple(zip(_CATCH_STEPS, catch_names)),
        "activity_tiers": tuple(zip(_ACTIVITY_STEPS, activity_names)),
    }


# ---------------------------------------------------------------- 스프라이트
# 전부 5~7픽셀이다. 도트 화면에서 이보다 크면 스무 마리가 겹쳐 안 읽힌다.


def _fish(px: Px, x: float, y: float, c: str, d: int) -> None:
    back = -1 if d > 0 else 5
    fork = back + (-1 if d > 0 else 1)
    px(x, y, 5, 3, c)
    px(x + back, y, 1, 3, c)
    px(x + fork, y - 1, 1, 1, c)
    px(x + fork, y + 3, 1, 1, c)
    px(x + (3 if d > 0 else 1), y + 1, 1, 1, "#0d1117")      # 눈


def _person(px: Px, x: float, y: float, c: str, d: int) -> None:
    px(x + 1, y - 4, 3, 3, "#e8c39e")                        # 머리
    px(x + 1, y - 1, 3, 4, c)                                # 몸
    px(x, y + 3, 2, 1, "#3d2a16")                            # 다리
    px(x + 3, y + 3, 2, 1, "#3d2a16")


def _animal(px: Px, x: float, y: float, c: str, d: int) -> None:
    head = x + (5 if d > 0 else -1)
    px(x, y, 6, 3, c)                                        # 몸통
    px(head, y - 2, 2, 3, c)                                 # 머리
    px(head + (0 if d > 0 else 1), y - 2, 1, 1, "#0d1117")   # 눈
    px(x + 1, y + 3, 1, 2, "#5a4632")                        # 다리
    px(x + 4, y + 3, 1, 2, "#5a4632")


def _star(px: Px, x: float, y: float, c: str, d: int) -> None:
    px(x + 1, y, 3, 3, c)
    px(x, y + 1, 5, 1, c)
    px(x + 2, y - 1, 1, 5, c)


def _flower(px: Px, x: float, y: float, c: str, d: int) -> None:
    px(x + 2, y, 1, 4, "#3f7d3f")                            # 줄기
    px(x + 1, y + 2, 3, 1, "#3f7d3f")                        # 잎
    px(x + 1, y - 2, 3, 2, c)                                # 꽃잎
    px(x + 2, y - 3, 1, 1, c)
    px(x + 2, y - 1, 1, 1, "#ffe08a")                        # 꽃술


def _gem(px: Px, x: float, y: float, c: str, d: int) -> None:
    px(x + 1, y, 3, 1, c)
    px(x, y + 1, 5, 2, c)
    px(x + 1, y + 3, 3, 1, c)
    px(x + 1, y + 1, 1, 1, "#ffffff")                        # 반짝


def _car(px: Px, x: float, y: float, c: str, d: int) -> None:
    px(x, y, 7, 3, c)                                        # 차체
    px(x + 1, y - 2, 4, 2, "#c9d1d9")                        # 지붕
    px(x + 1, y + 3, 1, 1, "#0d1117")                        # 바퀴
    px(x + 5, y + 3, 1, 1, "#0d1117")
    px(x + (6 if d > 0 else 0), y + 1, 1, 1, "#ffe08a")      # 전조등


# ---------------------------------------------------------------- 고정물


def _boat(px: Px, x: float, y: float) -> None:
    px(x, y + 6, 46, 5, "#6b4423")                           # 선체
    px(x + 3, y + 4, 40, 2, "#8b5a2b")                       # 갑판
    px(x + 4, y - 6, 2, 10, "#3d2a16")                       # 낚시꾼
    px(x + 3, y - 10, 4, 4, "#e8c39e")
    px(x + 7, y - 9, 11, 1, "#a97b4f")                       # 낚싯대


def _house(px: Px, x: float, y: float) -> None:
    px(x + 2, y - 6, 20, 12, "#c8a882")                      # 벽
    for i in range(11):                                      # 박공지붕
        px(x + 1 + i, y - 7 - i, 20 - 2 * i, 2, "#8a4b3a")
    px(x + 8, y - 1, 6, 7, "#5a3a24")                        # 문
    px(x + 16, y - 4, 4, 4, "#ffe08a")                       # 창


def _barn(px: Px, x: float, y: float) -> None:
    px(x + 2, y - 5, 22, 11, "#a9432f")                      # 벽
    for i in range(8):
        px(x + 1 + i, y - 6 - i, 22 - 2 * i, 2, "#7d2f20")   # 지붕
    px(x + 10, y - 1, 7, 7, "#e8d9c0")                       # 문
    px(x + 13, y - 1, 1, 7, "#a9432f")
    px(x + 26, y + 2, 2, 4, "#7d6b52")                       # 울타리
    px(x + 24, y + 2, 6, 1, "#7d6b52")


def _rocket(px: Px, x: float, y: float) -> None:
    px(x + 8, y - 14, 6, 12, "#d8dee9")                      # 동체
    px(x + 9, y - 17, 4, 3, "#d8dee9")                       # 노즈콘
    px(x + 10, y - 18, 2, 1, "#f85149")
    px(x + 9, y - 11, 4, 3, "#79c0ff")                       # 창
    px(x + 5, y - 5, 3, 4, "#f85149")                        # 날개
    px(x + 14, y - 5, 3, 4, "#f85149")
    px(x + 9, y - 2, 4, 3, "#ff9a5a")                        # 화염


def _greenhouse(px: Px, x: float, y: float) -> None:
    px(x + 2, y - 8, 22, 14, "#9fd8c8")                      # 유리
    for i in range(9):
        px(x + 2 + i, y - 9 - i, 22 - 2 * i, 1, "#5f9e8c")   # 지붕
    for c in range(4):                                       # 창틀
        px(x + 4 + c * 5, y - 8, 1, 14, "#5f9e8c")
    px(x + 26, y + 1, 3, 5, "#8a6a4a")                       # 물뿌리개
    px(x + 29, y + 2, 2, 1, "#8a6a4a")


def _mineshaft(px: Px, x: float, y: float) -> None:
    px(x + 2, y - 2, 22, 8, "#3a3226")                       # 갱구
    px(x + 6, y - 1, 14, 7, "#0d1117")
    px(x + 2, y - 4, 22, 2, "#6b5a42")                       # 들보
    px(x + 4, y - 10, 2, 8, "#6b5a42")                       # 도르래 기둥
    px(x + 20, y - 10, 2, 8, "#6b5a42")
    px(x + 4, y - 11, 18, 2, "#6b5a42")
    px(x + 12, y - 9, 1, 5, "#a89878")                       # 밧줄
    px(x + 10, y - 4, 5, 3, "#a89878")                       # 광차


def _tower(px: Px, x: float, y: float) -> None:
    px(x + 2, y - 16, 9, 22, "#3b4252")                      # 고층
    px(x + 13, y - 9, 8, 15, "#4c566a")                      # 저층
    for row in range(5):                                     # 창
        for col in range(3):
            px(x + 3 + col * 3, y - 14 + row * 4, 2, 2, "#ffe08a")
    for row in range(3):
        for col in range(2):
            px(x + 15 + col * 3, y - 7 + row * 4, 2, 2, "#ffe08a")
    px(x + 6, y - 19, 1, 3, "#f85149")                       # 안테나


# ---------------------------------------------------------------- 테마 정의

FISHING = Theme(
    key="fishing", name="낚시", unit="물고기",
    activity_word="입질", action_word="캐스팅",
    **_labels(
        ("빈 바구니", "잔챙이", "반 바구니", "한 바구니", "만선"),
        ("빈 바구니", "잔챙이", "반 바구니", "한 바구니", "만선"),
        ("잠잠", "잔잔", "활발", "폭주"),
    ),
    sky=((26, 26, 58), (92, 160, 214)),
    ground=((10, 18, 44), (30, 90, 140)),
    horizon="#8fb8d8", horizon_dusk="#5a6b8c",
    unit_colors=("#e3a447", "#d96f4a", "#7ee787", "#79c0ff"),
    sprite=_fish, base=_boat,
)

VILLAGE = Theme(
    key="village", name="마을", unit="주민",
    activity_word="북적임", action_word="방문",
    **_labels(
        ("빈 터", "오두막", "작은 마을", "큰 마을", "번화가"),
        ("빈 터", "오두막", "작은 마을", "큰 마을", "번화가"),
        ("고요", "한산", "붐빔", "장날"),
    ),
    sky=((32, 28, 52), (128, 176, 208)),
    ground=((28, 34, 26), (86, 122, 62)),
    horizon="#9ed46a", horizon_dusk="#4a5a3c",
    unit_colors=("#d98b6f", "#7fa7d9", "#c9a227", "#a48fd0"),
    sprite=_person, base=_house,
)

RANCH = Theme(
    key="ranch", name="목장", unit="동물",
    activity_word="울음소리", action_word="먹이 주기",
    **_labels(
        ("빈 우리", "몇 마리", "무리", "큰 무리", "가득한 목장"),
        ("빈 우리", "몇 마리", "무리", "큰 무리", "가득한 목장"),
        ("낮잠", "느긋", "활발", "야단법석"),
    ),
    sky=((38, 30, 46), (146, 190, 214)),
    ground=((30, 36, 24), (108, 142, 70)),
    horizon="#b6e07a", horizon_dusk="#55613e",
    unit_colors=("#f0e6d2", "#c98a5a", "#8a6a4a", "#e8c39e"),
    sprite=_animal, base=_barn,
)

SPACE = Theme(
    key="space", name="우주", unit="별",
    activity_word="전파", action_word="교신",
    **_labels(
        ("빈 하늘", "첫 별", "성단", "은하", "가득한 우주"),
        ("빈 하늘", "첫 별", "성단", "은하", "가득한 우주"),
        ("정적", "미약", "활발", "폭발"),
    ),
    sky=((8, 6, 24), (36, 30, 78)),
    ground=((4, 3, 14), (18, 14, 46)),
    horizon="#4b4380", horizon_dusk="#241f45",
    unit_colors=("#ffe08a", "#a5d8ff", "#ffb3c7", "#d0bfff"),
    sprite=_star, base=_rocket,
    sun=("#f2f2f2", "#cfc4a8"),
)

GARDEN = Theme(
    key="garden", name="정원", unit="꽃",
    activity_word="개화", action_word="물주기",
    **_labels(
        ("맨 흙", "새싹", "화단", "만발", "꽃밭"),
        ("맨 흙", "새싹", "화단", "만발", "꽃밭"),
        ("잠듦", "느릿", "한창", "폭발"),
    ),
    sky=((44, 34, 54), (168, 200, 224)),
    ground=((34, 30, 22), (96, 116, 58)),
    horizon="#c2e07a", horizon_dusk="#5b6440",
    unit_colors=("#ff8fab", "#ffd166", "#c77dff", "#ff9770"),
    sprite=_flower, base=_greenhouse,
)

MINE = Theme(
    key="mine", name="광산", unit="광석",
    activity_word="곡괭이질", action_word="채굴",
    **_labels(
        ("빈 갱도", "부스러기", "광맥", "노다지", "대박"),
        ("빈 갱도", "부스러기", "광맥", "노다지", "대박"),
        ("멈춤", "느릿", "활발", "전속력"),
    ),
    sky=((18, 14, 12), (58, 46, 38)),
    ground=((12, 10, 9), (44, 36, 30)),
    horizon="#6b5a42", horizon_dusk="#2e2721",
    unit_colors=("#79c0ff", "#7ee787", "#ff7b72", "#e3c447"),
    sprite=_gem, base=_mineshaft,
    sun=("#ffd76e", "#8a6a4a"),
)

CITY = Theme(
    key="city", name="도시", unit="차",
    activity_word="교통량", action_word="운행",
    **_labels(
        ("텅 빈 도로", "드문드문", "차량 행렬", "정체", "꽉 막힘"),
        ("텅 빈 도로", "드문드문", "차량 행렬", "정체", "꽉 막힘"),
        ("한밤", "한산", "붐빔", "출퇴근"),
    ),
    sky=((22, 20, 40), (110, 140, 180)),
    ground=((20, 20, 24), (58, 58, 66)),
    horizon="#8b8b96", horizon_dusk="#3a3a42",
    unit_colors=("#f85149", "#79c0ff", "#e3c447", "#d8dee9"),
    sprite=_car, base=_tower,
)

THEMES: dict[str, Theme] = {
    t.key: t for t in (FISHING, VILLAGE, RANCH, SPACE, GARDEN, MINE, CITY)
}
THEME_KEYS = tuple(THEMES)
DEFAULT = FISHING.key


def get(key: str | None) -> Theme:
    """없는 키가 오면 기본 테마. 설정 파일이 낡아도 화면은 뜬다."""
    return THEMES.get(key or "", FISHING)


def _selfcheck() -> None:
    drawn: list[tuple] = []

    def px(x, y, w, h, color):
        drawn.append((x, y, w, h, color))

    assert len(THEMES) == 7, THEME_KEYS
    assert get("nope") is FISHING and get(None) is FISHING

    for key, theme in THEMES.items():
        assert theme.key == key
        assert len(theme.fill_tiers) == 5, key
        assert len(theme.catch_tiers) == 5, key
        assert len(theme.activity_tiers) == 4, key

        # 경계값은 전 테마 공통이어야 한다. 여기가 어긋나면 같은 사용량을 두고
        # 테마마다 다른 등급이 나와서 숫자를 믿을 수 없게 된다.
        assert [s for s, _ in theme.fill_tiers] == list(_FILL_STEPS), key
        assert [s for s, _ in theme.catch_tiers] == list(_CATCH_STEPS), key
        assert [s for s, _ in theme.activity_tiers] == list(_ACTIVITY_STEPS), key

        assert len({n for _, n in theme.fill_tiers}) == 5, f"{key}: 등급 이름이 겹친다"
        assert len(theme.unit_colors) >= 4, key

        before = len(drawn)
        theme.sprite(px, 10, 10, theme.unit_colors[0], 1)
        theme.sprite(px, 10, 10, theme.unit_colors[0], -1)
        theme.base(px, 10, 40)
        assert len(drawn) > before, f"{key}: 아무것도 안 그린다"

    print(f"themes.py selfcheck OK ({len(THEMES)}개)")


if __name__ == "__main__":
    _selfcheck()
