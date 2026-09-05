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

from dataclasses import dataclass, replace
from typing import Callable, Protocol


class Px(Protocol):
    def __call__(self, x: float, y: float, w: int, h: int, color: str) -> None: ...


W, H = 180, 120
"""가상 도트 해상도. 실제 창은 SCALE배. 배경을 그리려면 테마도 이 크기를 알아야 한다."""

HORIZON = 62
"""지평선 y. 위가 하늘, 아래가 바닥."""

Decor = Callable[[Px, "Theme", float, int], None]
"""(px, theme, daylight, frame) -> 배경 한 겹.

daylight 는 1.0(창 시작)에서 0.0(리셋 직전)으로 떨어진다. frame 은 애니메이션용.
"""

Sprite = Callable[[Px, float, float, str, int, int], None]
"""(px, x, y, color, direction, frame) -> 움직이는 것 하나. direction 은 +1/-1."""

Base = Callable[[Px, float, float, int], None]
"""(px, x, y, frame) -> 화면 왼쪽 고정물 하나. y 는 지평선 기준."""

Pile = Callable[[Px, "Theme", float, float, int, int], None]
"""(px, theme, x, y, count, frame) -> 화면에 못 담아 모아 둔 것 전부.

물고기는 위로 쌓이지만 사람·차·별이 똑같이 쌓이면 이상하다 — 테마마다 모으는
방식(쌓기/무리짓기/눕히기/흩어놓기)이 다르므로 이것도 테마가 고른다."""


def _no_ambient(px: Px, theme: "Theme", d: float, t: int) -> None:
    """대부분의 테마는 마리 수 말고 따로 그릴 게 없다. 광차·나비 같은 것만 쓴다."""
    return None


# -------------------------------------------------------------- 모으는 방식
# 고갈 모드에서 사라진 만큼을 어디에 어떤 모양으로 모아 둘지(축적 모드는
# state.py가 더미를 안 만들므로 여기까지 안 온다). count는 항상
# 0~24(state.MAX_FISH_DRAWN) — 그 숫자는 여기서 몰라도 된다, 자리만 24개
# 이상 두면 그만이다. (x, y)는 고정물의 기준점 그대로다 — 오프셋은 각자 알아서
# 잡는다. 배마다 고정물 폭이 달라서(보트/부둣가/방파제 ...) 한 오프셋을
# 공유하면 어느 하나는 꼭 겹친다.


_PILE_MAX = 24
"""state.MAX_FISH_DRAWN과 같아야 한다. themes는 state를 몰라야 하므로 값을
그대로 옮겨 적었다 — 이 숫자를 바꾸려면 두 곳 다 고쳐야 한다."""


def _no_pile(px: Px, theme: "Theme", x: float, y: float, count: int, t: int) -> None:
    """아무것도 안 모은다. 마을·도시는 사람/차가 줄어드는 것만으로 충분하다 —
    억지로 모아 두면 화면에 없던 물건이 하나 더 생길 뿐이다."""
    return None


def _oval_slots(rx=22, ry=13, step_x=7, step_y=4) -> list[tuple[int, int]]:
    """둥근 우리·화단 안쪽에 고르게 들어차는 자리. 가운데 줄이 가장 넓다."""
    import math

    slots = []
    y = -ry + step_y
    while y <= ry - step_y:
        half = rx * math.sqrt(max(0.0, 1 - (y / ry) ** 2)) - step_x * 0.6
        x = -half
        while x <= half:
            slots.append((round(x), round(y)))
            x += step_x
        y += step_y
    return slots


_OVAL_SLOTS = _oval_slots()


def _oval_ring(px: Px, cx: float, cy: float, rx: int, ry: int, color: str, step=10) -> None:
    """타원 둘레에 말뚝을 박는다. 안은 안 채우고 테두리만."""
    import math

    for a in range(0, 360, step):
        r = math.radians(a)
        px(cx + rx * math.cos(r), cy + ry * math.sin(r), 2, 2, color)


def _oval_fill(px: Px, cx: float, cy: float, rx: int, ry: int, color: str) -> None:
    """타원을 채운다. 화단 흙처럼 안쪽이 있어야 하는 것에만."""
    import math

    for dy in range(-ry, ry + 1):
        half = rx * math.sqrt(max(0.0, 1 - (dy / ry) ** 2))
        if half >= 1:
            px(cx - half, cy + dy, round(half * 2), 1, color)


def _net_at(px: Px, theme: "Theme", nx: float, ny: float, count: int, t: int) -> None:
    """그물망 하나. 낱개로 흩어놓지 않고 담아 둔다 — 자리는 부르는 쪽이 정한다."""
    ratio = min(1.0, count / _PILE_MAX)
    if ratio <= 0:
        return
    for i in range(0, 13, 4):                                # 그물코 — 세로줄
        px(nx + i, ny, 1, 12, "#d8cbb0")
    for j in range(0, 13, 4):                                # 그물코 — 가로줄
        px(nx, ny + j, 12, 1, "#d8cbb0")
    for i in range(round(ratio * 6)):
        theme.sprite(px, nx + 1 + (i % 3) * 4, ny + 1 + (i // 3) * 5,
                     theme.unit_colors[i % 4], 1, t)


def _pile_net(px: Px, theme: "Theme", x: float, y: float, count: int, t: int) -> None:
    """낚시 기본. 그물은 사람이 딛고 선 것(갑판·데크·바위·모래) 위에 놓는다 —
    물 위에 두면 잡은 물고기가 바다에 떠 있는 것처럼 보인다."""
    _net_at(px, theme, x + theme.pile_offset, y - 10, count, t)


def _pile_net_shore(px: Px, theme: "Theme", x: float, y: float, count: int, t: int) -> None:
    """차박·캠핑. 그물을 물가 풀밭에 내려놓는다.

    고정물 x는 배경이 바뀔 때마다 흔들리지만 물가 위치는 화면에 고정이라,
    여기서는 넘겨받은 x를 쓰지 않고 화면 좌표를 직접 쓴다."""
    _net_at(px, theme, 10, HORIZON + 14, count, t)


def _pile_corral(px: Px, theme: "Theme", x: float, y: float, count: int, t: int) -> None:
    """목장. 헛간 아래에 둥근 울타리를 치고 그 안에만 동물을 모은다.

    축적 모드(count=0)에서는 울타리도 안 친다 — 빈 우리만 덩그러니 남는다."""
    if not count:
        return
    cx, cy = x + 22, y + 40
    _oval_ring(px, cx, cy, 26, 13, "#7d6b52")
    for i, (dx, dy) in enumerate(_OVAL_SLOTS[:count]):
        theme.sprite(px, cx + dx - 3, cy + dy - 2,
                     theme.unit_colors[i % 4], 1 if i % 2 else -1, t)


def _pile_bed(px: Px, theme: "Theme", x: float, y: float, count: int, t: int) -> None:
    """정원. 온실 아래에 둥근 화단을 만들고 거기에만 꽃을 심는다.

    축적 모드(count=0)에서는 화단도 안 만든다."""
    if not count:
        return
    cx, cy = x + 22, y + 40
    _oval_fill(px, cx, cy, 26, 13, "#4a3b28")                # 갈아 놓은 흙
    _oval_ring(px, cx, cy, 26, 13, "#6b5a42", step=14)       # 테두리 돌
    for i, (dx, dy) in enumerate(_OVAL_SLOTS[:count]):
        theme.sprite(px, cx + dx - 2, cy + dy - 1, theme.unit_colors[i % 4], 1, t)


_MAX_HOUSES = 6
"""한 줄에 들어가는 집 수. 아래로 줄을 늘리면 들판(잔디)을 다 덮어 버린다."""


def _pile_houses(px: Px, theme: "Theme", x: float, y: float, count: int, t: int) -> None:
    """마을. 사람이 모이는 게 아니라 **집이 는다** — 큰 집 옆으로 같은 크기의
    집이 한 채씩, 지평선 쪽 한 줄로만 들어선다."""
    homes = round(count / _PILE_MAX * _MAX_HOUSES)
    if count and not homes:
        homes = 1                                            # 한 채라도 들어서야 변화가 보인다
    for i in range(homes):
        _house_at(px, x + 30 + i * 23, y + 2, i + 1)         # 폭 20 + 사이 3


_MAX_LIT = 8


def _pile_towers(px: Px, theme: "Theme", x: float, y: float, count: int, t: int) -> None:
    """도시. 한 건물이 밝아지는 게 아니라 **불 켜진 건물이 는다**.

    한 줄로만 세운다 — 줄을 겹쳐 놓으면 건물끼리 겹치고, 뒷줄은 밑동이
    지평선 위로 올라가 공중에 뜬 것처럼 보인다."""
    lit = round(count / _PILE_MAX * _MAX_LIT)
    if count and not lit:
        lit = 1
    for i in range(lit):
        bx = x + 26 + i * 11                                 # 폭 9 + 사이 2 → 안 겹친다
        h = 12 + (i * 7 % 3) * 6
        px(bx, y - h, 9, h, "#3b4252")                       # 건물 (밑동은 지면에)
        px(bx, y - h, 9, 1, "#4c566a")
        for win in range(1, h // 5):
            px(bx + 2, y - h + win * 5, 2, 2, "#ffe08a")
            px(bx + 5, y - h + win * 5, 2, 2, "#c9a227")


def _pile_flame(px: Px, theme: "Theme", x: float, y: float, count: int, t: int) -> None:
    """우주. 별은 쌓이지 않는다 — 로켓 불꽃이 커지고 밝아진다.

    조금씩 커지면 눈에 안 띈다. 다 차면 로켓만 한 화염이 되도록 크게 키운다."""
    ratio = min(1.0, count / _PILE_MAX)
    if ratio <= 0:
        return
    grow = round(ratio * 16)
    flicker = (t // 3) % 2
    outer = "#ff9a5a" if ratio < 0.6 else "#f85149"
    # 동체(_rocket: x+8 ~ x+14) 한가운데를 축으로 좌우 대칭으로 키운다.
    # 시작 x에서 폭을 더하는 식으로 짜면 커질수록 한쪽으로 밀린다.
    cx = x + 11
    wide, core = 6 + grow // 2, 4 + grow // 4
    px(cx - wide // 2, y - 2, wide, 4 + grow + flicker, outer)
    px(cx - core // 2, y - 2, core, 3 + grow // 2 + flicker, "#ffd76e")


def _pile_cart(px: Px, theme: "Theme", x: float, y: float, count: int, t: int) -> None:
    """광차에 담긴 광석. 낱개를 세기보다 얼마나 찼는지가 중요해서 그릇처럼 채운다."""
    ox = x + 30
    ratio = min(1.0, count / _PILE_MAX)
    px(ox, y - 4, 14, 5, "#8a8a94")                          # 카트 몸체
    px(ox + 1, y - 5, 12, 1, "#c9c9d1")
    mound = round(ratio * 4)
    for i in range(mound):
        w = 12 - i * 2
        px(ox + 1 + i, y - 5 - i, max(w, 2), 2, theme.unit_colors[i % 4])
    px(ox, y + 1, 2, 2, "#3a3a3e")                           # 바퀴
    px(ox + 11, y + 1, 2, 2, "#3a3a3e")


def _pile_lake(px: Px, theme: "Theme", x: float, y: float, count: int, t: int) -> None:
    """차박·캠핑 전용. 고정물(차/텐트)은 땅 위, 잡은 물고기는 호수 쪽에 둔다.

    호수는 화면에서 고정된 자리(_edge_lakeside 참고)라 고정물의 x(=랜덤 배치)를
    따라가면 물 밖 땅으로 넘어간다 — 그래서 여기서는 x를 무시하고 고정 좌표를 쓴다."""
    lx, ly = 100, HORIZON + 16
    for i, (dx, dy) in enumerate(_HEAP_SLOTS[:count]):
        theme.sprite(px, lx + dx, ly - dy, theme.unit_colors[i % 4], 1, t)


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

    sky_decor: Decor
    """지평선 위. 해·달·별·구름·천장 — 테마마다 하늘의 정체가 다르다."""

    edge: Decor
    """지평선 아래. 파도·풀·자갈·차선 — 바닥의 결이 다르다."""

    sun: tuple[str, str] = ("#ffd76e", "#ff9a5a")
    """하늘에 뜬 것의 색 (낮, 노을). 해일 수도 달일 수도 있다."""

    unit_band: tuple[int, int] = (HORIZON + 6, H - 8)
    """움직이는 것들이 사는 y 구간. 기본은 지평선 아래 = 지상.

    우주는 하늘에 별이 떠야 하므로 지평선 **위**를 쓴다. 지면 아래를 헤엄치는
    별은 별로 안 보인다."""

    unit_drifts: bool = True
    """가로로 돌아다니는가. 정원의 꽃은 심겨 있으므로 제자리에서 흔들리기만 한다."""

    unit_bobs: bool = True
    """위아래로 흔들리는가. 차선을 지키는 차, 벽에 박힌 광석은 흔들면 안 된다."""

    unit_lanes: int = 0
    """0이면 구간 안에서 아무 y나. N이면 그 구간을 N개 차선으로 나눠 그 위만 다닌다."""

    ambient: Decor = _no_ambient
    """마리 수와 무관하게 도는 것 하나. 광산의 광차, 정원의 나비 같은 배경 연출."""

    ground_sink: int = 0
    """고정물을 지평선에서 얼마나 더 내려 앉힐까. 배는 물 위에 뜨는 게 맞지만,
    집·헛간·타워처럼 땅에 서는 것들은 경계선에 딱 걸치면 살짝 떠 보인다."""

    base_bobs: bool = True
    """고정물이 위아래로 흔들리는가. 물 위에 뜬 것(배)만 True — 땅에 선 것이
    흔들리면 위로 떴을 때 밑동이 지평선을 넘어 공중에 뜬 것처럼 보인다."""

    pile: Pile = _no_pile
    """고갈 모드에서 사라진 만큼을 어떻게 모아 둘까. 기본은 안 모으기 —
    화면의 것이 줄어드는 것만으로 충분한 테마가 더 많다."""

    pile_offset: int = 2
    """_pile_net 전용. 고정물 폭이 배경마다 달라서(보트/부둣가/방파제 ...)
    낚시 배경별로 이 값만 바꿔 사람과 겹치지 않게 한다."""

    unit_x_range: tuple[float, float] = (4, W - 12)
    """돌아다니는 것들이 사는 가로 구간. 차박·캠핑처럼 바닥 절반이 땅인
    배경만 좁혀서 쓴다 — 안 그러면 물고기가 잔디 위를 헤엄친다."""

    base_x_range: tuple[float, float] = (6, 50)
    """고정물을 놓을 x 범위. 배경이 바뀔 때마다 이 안에서 새로 뽑는다.
    차박·캠핑처럼 땅이 화면 왼쪽뿐인 배경은 좁혀야 차·텐트가 물에 안 잠긴다."""

    pile_band: tuple[int, int] | None = None
    """모아 둔 것이 차지하는 y 구간. 더미가 떠 있는 동안 돌아다니는 것들은
    여기로 못 들어온다 — 울타리·화단 안팎이 확실해야 통과하는 것처럼 안 보인다."""


@dataclass(frozen=True, slots=True)
class FishingSpot:
    """낚시 테마 하나 안에서 고르는 배경. 등급·집계는 그대로 두고 어디서 낚느냐와
    무엇이 잡히느냐만 바꾼다 — 테마가 숫자를 안 바꾸는 것과 같은 원칙."""

    key: str
    name: str
    unit_colors: tuple[str, ...]
    """이 배경에서 잡히는 물고기 색(=종류)."""
    base: Base

    # 전부 기본값 None = 낚시 테마(바다) 그대로 쓴다. 차박·캠핑처럼 물 위가
    # 아니라 물가인 배경만 바닥·하늘·배경 연출을 갈아 끼운다.
    ground: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None
    horizon: str | None = None
    horizon_dusk: str | None = None
    edge: Decor | None = None
    sky_decor: Decor | None = None
    ambient: Decor | None = None
    pile: Pile | None = None
    """None이면 기본 쌓기(_pile_heap)를 그대로 쓴다. 그물(바다 계열)이나
    호숫가(차박·캠핑)처럼 모으는 방식 자체가 다른 배경만 갈아 끼운다."""
    pile_offset: int | None = None
    """_pile_heap을 그대로 쓰는 배경(방파제·섬)이 고정물 폭에 맞춰 미세조정할 때만."""
    unit_x_range: tuple[float, float] | None = None
    """차박·캠핑처럼 바닥 절반이 땅인 배경만 물 쪽으로 좁힌다."""
    base_x_range: tuple[float, float] | None = None
    """차박·캠핑처럼 땅이 왼쪽뿐인 배경만 좁힌다 — 안 그러면 차가 물에 잠긴다."""
    ground_sink: int | None = None
    """땅에 세우는 배경(차박·캠핑)만 내려 앉힌다. 물 위 구조물은 0 그대로."""
    base_bobs: bool | None = None
    """흔들리는 건 배뿐이다. 부둣가·갯바위·방파제·차·텐트는 안 흔들린다."""


# 등급 경계는 모든 테마가 공유한다. 숫자가 아니라 부르는 이름만 테마마다 다르다 —
# 경계까지 테마마다 다르면 같은 사용량을 두고 화면이 서로 다른 말을 하게 된다.
_FILL_STEPS = (0.0, 0.01, 0.20, 0.50, 0.80)
_CATCH_STEPS = (0, 5_000, 50_000, 200_000, 1_000_000)
_ACTIVITY_STEPS = (0, 500, 5_000, 50_000)


def labels(fill_names, catch_names, activity_names) -> dict:
    """세 라벨 표를 한 번에. Theme(...) 안에서 ** 로 펼쳐 쓴다.

    animal.py도 이 표(경계값)를 그대로 가져다 쓴다 — 반려동물 모드도 등급이
    바뀌는 지점만은 나머지 테마들과 같아야 하기 때문이다."""
    return {
        "fill_tiers": tuple(zip(_FILL_STEPS, fill_names)),
        "catch_tiers": tuple(zip(_CATCH_STEPS, catch_names)),
        "activity_tiers": tuple(zip(_ACTIVITY_STEPS, activity_names)),
    }


# ---------------------------------------------------------------- 배경 (하늘)
# 지평선 위를 그린다. 바탕색은 팝업이 이미 칠했고 여기는 그 위에 얹는다.


def _orb(px, theme, d: float, size: int = 11) -> tuple[float, float]:
    """해/달 하나. 남은 시간이 많을수록 높이 뜬다. 자리를 돌려준다."""
    x, y = 26 + (1 - d) * (W - 60), 8 + (1 - d) * (HORIZON - 22)
    color = theme.sun[0] if d > 0.35 else theme.sun[1]
    px(x, y, size, size, color)
    px(x + 2, y - 1, size - 4, size + 2, color)
    return x, y


def _sky_open(px, theme, d: float, t: int) -> None:
    """해만 뜬 하늘. 낚시처럼 배경이 비어야 물 위가 넓어 보인다."""
    _orb(px, theme, d)


def _sky_clouds(px, theme, d: float, t: int) -> None:
    """해와 흘러가는 구름. 마을·목장·정원처럼 지상 테마의 기본 하늘."""
    _orb(px, theme, d)
    tint = "#f2f6fa" if d > 0.35 else "#6b6f8a"
    for lane, (y, scale, width) in enumerate(((14, 0.10, 26), (30, 0.06, 18))):
        x = (lane * 90 + t * scale) % (W + width) - width
        px(x, y, width, 4, tint)
        px(x + 4, y - 3, width - 10, 3, tint)


def _sky_stars(px, theme, d: float, t: int) -> None:
    """별밭과 달. 해가 아니라 달이므로 색도 다르다(theme.sun 이 흰빛)."""
    _orb(px, theme, d, size=9)
    for i in range(26):
        # 고정 좌표를 규칙으로 만든다. 난수를 쓰면 매 프레임 별이 튄다.
        x, y = (i * 47) % W, (i * 29) % (HORIZON - 6)
        twinkle = (t // 8 + i) % 5
        if twinkle:
            px(x, y, 1, 1, "#e8ecff" if twinkle > 2 else "#8b93c8")


def _sky_cave(px, theme, d: float, t: int) -> None:
    """땅속이라 하늘이 없다. 암반 천장과 종유석, 그리고 램프 불빛.

    광산에 해가 뜨면 안 된다. 대신 남은 시간을 램프 밝기로 옮긴다 —
    시간이 줄면 불이 사그라든다.
    """
    px(0, 0, W, 9, "#4a3b2b")                                # 암반
    px(0, 8, W, 2, "#2a2018")                                # 그늘진 아래면
    for i in range(0, W, 11):                                # 종유석
        drop = 3 + (i * 3 % 7)
        x = i + (i % 5)
        px(x, 9, 3, drop, "#4a3b2b")
        px(x, 9, 1, drop, "#6b5642")                         # 밝은 면이 있어야 입체
        px(x + 1, 9 + drop, 1, 2, "#2a2018")
    for i in range(0, W, 7):                                 # 암반 결
        px(i + (i % 3), 2 + (i * 2 % 4), 3, 1, "#6b5642")

    lx, ly = 150, 18
    px(lx + 2, ly - 8, 1, 8, "#6b5a42")                      # 걸이
    px(lx, ly, 5, 6, "#5a4a36")                              # 램프
    glow = "#ffd76e" if d > 0.35 else "#c9772f"
    px(lx + 1, ly + 1, 3, 4, glow)
    # 불빛은 사각형으로 칠하지 않는다 — 배경에 구멍이 뚫린 것처럼 보였다.
    # 남은 시간이 많을수록 멀리 뻗는 광선으로 대신한다.
    for ray in range(1, int(2 + d * 5)):
        px(lx + 2 - ray, ly + 6 + ray * 2, 1 + ray * 2, 1, "#6b5230")


def _sky_skyline(px, theme, d: float, t: int) -> None:
    """해와 원경 스카이라인. 차와 같이 흘러야 도시가 살아있는 것처럼 보인다."""
    _orb(px, theme, d)
    far = "#2b3040" if d > 0.35 else "#1a1d29"
    heights = (10, 18, 8, 24, 14, 20, 9, 16, 12, 22, 7, 15)
    widths = [10 + (i % 3) * 4 for i in range(len(heights))]
    total = sum(widths)
    scroll = (t * 0.3) % total
    for start in (-scroll, -scroll + total):                 # 두 벌 그려 이음매를 감춘다
        x = start
        for height, width in zip(heights, widths):
            if x + width > -20 and x < W + 20:
                px(x, HORIZON - height, width - 2, height, far)
                if d < 0.5:                                  # 해가 지면 창에 불이
                    for row in range(1, height // 5):
                        px(x + 2, HORIZON - height + row * 5, 2, 2, "#ffd76e")
                        px(x + 6, HORIZON - height + row * 5, 2, 2, "#c9a227")
            x += width


# ---------------------------------------------------------------- 배경 (바닥)
# 지평선 아래. 바탕색 위에 결을 얹어 무엇으로 된 바닥인지 알려준다.


def _edge_waves(px, theme, d: float, t: int) -> None:
    """출렁이는 수면. 물결이 흐르는 방향이 있어야 바다로 읽힌다.

    진폭을 블록 높이보다 작게 잡아 이어 붙인다 — 크게 잡으면 칸마다 y가
    들쭉날쭉 벌어져서 물결이 아니라 화면을 가로지르는 점선으로 보였다.
    """
    import math

    tint = theme.horizon if d > 0.35 else theme.horizon_dusk
    for x in range(0, W, 2):
        px(x, HORIZON + math.sin((x + t * 2) * 0.18) * 0.8, 2, 2, tint)
    for i in range(10):                                      # 잔물결. 격자가 아니라 흩어진 자리
        x = (i * 47 + t * (2 + i % 3)) % (W + 6) - 3
        y = HORIZON + 8 + (i * 7) % 22
        px(x, y, 2 + i % 2, 1, tint)


def _edge_grass(px, theme, d: float, t: int) -> None:
    """풀밭. 지평선에 풀포기가 서고 바닥에도 드문드문 난다."""
    import math

    tint = theme.horizon if d > 0.35 else theme.horizon_dusk
    px(0, HORIZON, W, 1, tint)
    for i in range(0, W, 3):
        # 높이를 흩는다. 같은 높이로 촘촘히 세우면 풀이 아니라 울타리로 보인다.
        blade = (i * 7 % 5) // 2
        if not blade:
            continue
        px(i + math.sin((i + t) * 0.09), HORIZON - blade, 1, blade, tint)
    for i in range(0, W, 13):                                # 바닥 잡초
        y = HORIZON + 12 + (i * 5 % 7) * 5
        px(i + 3, y, 1, 2, tint)
        px(i + 2, y + 1, 3, 1, tint)


def _edge_galaxy(px, theme, d: float, t: int) -> None:
    """행성 표면이 없다. 지평선 아래도 위와 같은 은하다 — 별과 성운이 이어진다.

    바닥을 따로 두지 않는다: 발 디딜 땅이 있으면 우주가 아니라 행성이 된다.
    """
    tint = theme.horizon if d > 0.35 else theme.horizon_dusk
    for i in range(30):
        # sky_stars와 다른 배수를 써서 두 별밭이 같은 무늬로 겹치지 않게 한다.
        x, y = (i * 53) % W, HORIZON + (i * 31) % (H - HORIZON - 3)
        twinkle = (t // 9 + i) % 6
        if twinkle:
            px(x, y, 1, 1, "#e8ecff" if twinkle > 3 else tint)
    for i in range(4):                                       # 옅은 성운
        x = (i * 61 + 10 + t // 6) % (W + 8) - 4
        y = HORIZON + 6 + (i * 17) % (H - HORIZON - 12)
        px(x, y, 6, 3, "#3a2f66" if d > 0.35 else "#241d45")


def _edge_rubble(px, theme, d: float, t: int) -> None:
    """갱도 바닥. 자갈과 침목, 그리고 광차가 다니는 레일."""
    tint = theme.horizon if d > 0.35 else theme.horizon_dusk
    px(0, HORIZON, W, 2, tint)
    for i in range(0, W, 9):                                 # 침목
        px(i, HORIZON + 6, 5, 2, "#4a3d2c")
    px(0, HORIZON + 5, W, 1, "#8b8b96")                      # 레일
    px(0, HORIZON + 9, W, 1, "#8b8b96")
    for i in range(0, W, 13):                                # 자갈
        px(i + 2, HORIZON + 18 + (i // 13 % 4) * 8, 3, 2, tint)
        px(i + 7, HORIZON + 24 + (i // 13 % 3) * 9, 2, 2, tint)


def _edge_road(px, theme, d: float, t: int) -> None:
    """도로. 연석 두 줄 사이를 중앙선이 반으로 갈라 2차선이 된다.

    중앙선은 노면(연석 HORIZON+4 ~ 반대편 연석 H-4)의 정확히 한가운데에
    둔다 — 한쪽으로 치우치면 차가 차선 위를 밟고 달리는 것처럼 보인다.
    """
    tint = theme.horizon if d > 0.35 else theme.horizon_dusk
    top, bottom = HORIZON + 4, H - 4
    middle = (top + bottom) // 2 - 1
    px(0, HORIZON, W, 2, tint)                               # 연석
    px(0, HORIZON + 3, W, 1, "#4a4a52")
    for x in range(0, W + 16, 16):                           # 중앙선 (흐른다)
        px((x - t * 1.2) % (W + 16) - 8, middle, 9, 2, "#e3c447")
    px(0, bottom, W, 1, "#4a4a52")                           # 반대편 연석


# ---------------------------------------------------------------- 스프라이트
# 전부 5~7픽셀이다. 도트 화면에서 이보다 크면 스무 마리가 겹쳐 안 읽힌다.


def _fish(px: Px, x: float, y: float, c: str, d: int, t: int) -> None:
    back = -1 if d > 0 else 5
    fork = back + (-1 if d > 0 else 1)
    px(x, y, 5, 3, c)
    px(x + back, y, 1, 3, c)
    px(x + fork, y - 1, 1, 1, c)
    px(x + fork, y + 3, 1, 1, c)
    px(x + (3 if d > 0 else 1), y + 1, 1, 1, "#0d1117")      # 눈


def _person(px: Px, x: float, y: float, c: str, d: int, t: int) -> None:
    px(x + 1, y - 4, 3, 3, "#e8c39e")                        # 머리
    px(x + 1, y - 1, 3, 4, c)                                # 몸
    px(x, y + 3, 2, 1, "#3d2a16")                            # 다리
    px(x + 3, y + 3, 2, 1, "#3d2a16")
    seed = sum(map(ord, c))
    if (t + seed) % 140 < 24:                                # 가끔 멈춰서 손을 흔든다
        px(x + (5 if d > 0 else -2), y - 4, 1, 3, "#e8c39e")


def _animal(px: Px, x: float, y: float, c: str, d: int, t: int) -> None:
    head = x + (5 if d > 0 else -1)
    px(x, y, 6, 3, c)                                        # 몸통
    seed = sum(map(ord, c))
    if (t + seed) % 160 < 30:                                # 가끔 고개 숙여 풀을 뜯는다
        px(head, y + 1, 2, 2, c)
        px(head + (0 if d > 0 else 1), y + 2, 1, 1, "#0d1117")
    else:
        px(head, y - 2, 2, 3, c)                             # 머리
        px(head + (0 if d > 0 else 1), y - 2, 1, 1, "#0d1117")  # 눈
    px(x + 1, y + 3, 1, 2, "#5a4632")                        # 다리
    px(x + 4, y + 3, 1, 2, "#5a4632")


def _star(px: Px, x: float, y: float, c: str, d: int, t: int) -> None:
    px(x + 1, y, 3, 3, c)
    px(x, y + 1, 5, 1, c)
    px(x + 2, y - 1, 1, 5, c)


def _flower(px: Px, x: float, y: float, c: str, d: int, t: int) -> None:
    px(x + 2, y, 1, 4, "#3f7d3f")                            # 줄기
    px(x + 1, y + 2, 3, 1, "#3f7d3f")                        # 잎
    px(x + 1, y - 2, 3, 2, c)                                # 꽃잎
    px(x + 2, y - 3, 1, 1, c)
    px(x + 2, y - 1, 1, 1, "#ffe08a")                        # 꽃술


def _gem(px: Px, x: float, y: float, c: str, d: int, t: int) -> None:
    px(x + 1, y, 3, 1, c)
    px(x, y + 1, 5, 2, c)
    px(x + 1, y + 3, 3, 1, c)
    seed = sum(map(ord, c))
    if (t + seed) % 24 < 12:                                 # 박혀 있는 대신 반짝임으로 산다
        px(x + 1, y + 1, 1, 1, "#ffffff")


def _car(px: Px, x: float, y: float, c: str, d: int, t: int) -> None:
    px(x, y, 7, 3, c)                                        # 차체
    px(x + 1, y - 2, 4, 2, "#c9d1d9")                        # 지붕
    px(x + 1, y + 3, 1, 1, "#0d1117")                        # 바퀴
    px(x + 5, y + 3, 1, 1, "#0d1117")
    px(x + (6 if d > 0 else 0), y + 1, 1, 1, "#ffe08a")      # 전조등


def _ambient_butterflies(px: Px, theme: "Theme", d: float, t: int) -> None:
    """마리 수와 무관한 배경 연출. 꽃은 심겨 있으니 나비가 대신 날아다닌다."""
    import math

    for i, c in enumerate(("#fff2b8", "#ffd6e8", "#c9f7ff")):
        x = 20 + i * 55 + math.sin(t * 0.05 + i * 2) * 18
        y = HORIZON - 8 + math.sin(t * 0.13 + i) * 6 - i * 3
        wing = 2 if int(t * 0.3 + i) % 2 else 1
        px(x, y, wing, 2, c)
        px(x + wing + 1, y, wing, 2, c)
        px(x + wing, y + 1, 1, 1, "#3d2a16")


def _ambient_minecart(px: Px, theme: "Theme", d: float, t: int) -> None:
    """광차가 이따금 레일을 오간다. 광석은 벽에 박혀 있으니 움직이는 건 이것뿐."""
    period, travel = 340, 90
    phase = t % period
    if phase >= travel:
        return
    x = 20 + (W - 50) * (phase / travel)
    rail_y = HORIZON + 5
    px(x, rail_y - 4, 6, 4, "#c9c9d1")                       # 광차 몸체
    px(x + 1, rail_y - 5, 4, 1, "#8a8a94")                   # 테두리
    px(x + 1, rail_y, 1, 1, "#3a3a3e")                       # 바퀴
    px(x + 4, rail_y, 1, 1, "#3a3a3e")


# ---------------------------------------------------------------- 고정물


WATER_Y = HORIZON + 4
"""수면 y. 낚싯줄은 배경이 뭐든 여기까지 내려와야 물에 담근 것으로 보인다."""


def _angler(px: Px, x: float, y: float, t: int, water_y: float = WATER_Y) -> None:
    """낚시꾼 한 명. 배·부둣가·갯바위 등 낚시 배경이면 다 이 위에 선다.

    낚싯대는 비스듬히 세워 들고, 낚싯줄은 water_y(수면)까지 **반드시** 내려간다.
    배경마다 사람이 선 높이가 달라서 줄 길이를 고정해 두면 갯바위·방파제에서는
    줄이 허공에서 끊긴다.

    대부분은 대기. 가끔 손맛을 봐서 대가 더 서고 사람이 뒤로 젖혀진다 — 그
    모션을 배경마다 새로 짜지 않도록 여기 한 군데에 둔다.
    """
    biting = t % 180 < 18
    lean = 2 if biting else 0
    px(x + 4 - lean, y - 6, 2, 10, "#3d2a16")                # 몸
    px(x + 3 - lean, y - 10, 4, 4, "#e8c39e")                # 머리

    hx, hy = x + 6 - lean, y - 5                             # 손
    rise = 2 if biting else 1                                # 손맛 보면 대를 더 세운다
    tip_x, tip_y = hx, hy
    for i in range(1, 13):                                   # 대각선 낚싯대(계단식)
        tip_x, tip_y = hx + i, hy - (i * rise) // 2
        px(tip_x, tip_y, 1, 1, "#a97b4f")

    px(tip_x, tip_y, 1, max(1, round(water_y - tip_y)), "#7d8590")   # 낚싯줄
    if biting:
        px(tip_x - 2, water_y - 3, 5, 4, "#f85149")          # 물 위로 튀어오른 손맛
    else:
        px(tip_x - 1, water_y - 1, 3, 3, "#f85149")          # 찌


def _boat(px: Px, x: float, y: float, t: int) -> None:
    """바다 위. 돛대와 깃발, 갑판의 구명튜브 — 먼바다에 나온 배."""
    px(x, y + 6, 46, 5, "#6b4423")                           # 선체
    px(x + 3, y + 4, 40, 2, "#8b5a2b")                       # 갑판
    px(x + 18, y - 15, 1, 19, "#8a6a4a")                     # 돛대
    px(x + 19, y - 15, 7, 5, "#d8dee9")                      # 깃발
    px(x + 19, y - 13, 7, 1, "#f85149")
    px(x + 40, y, 5, 5, "#f85149")                           # 구명튜브
    px(x + 41, y + 1, 3, 3, "#8b5a2b")
    _angler(px, x + 30, y, t)                                # 줄이 뱃전 밖 물에 닿는 자리


_HOUSE_STYLES = (
    # (벽, 지붕, 지붕 높이, 창 개수) — 같은 크기에 모양만 다르게.
    ("#c8a882", "#8a4b3a", 11, 1),                           # 뾰족한 박공지붕
    ("#d8c49a", "#5f7d4b", 6, 2),                            # 낮은 모임지붕
    ("#b89a72", "#7d5a36", 11, 2),                           # 목조 박공
    ("#cbb08c", "#4a6b8a", 8, 1),                            # 파란 기와
    ("#e0cba8", "#a9432f", 6, 2),                            # 붉은 모임지붕
)


def _house_at(px: Px, x: float, y: float, style: int) -> None:
    """집 한 채. y는 바닥선. 크기는 다 같고 지붕·벽·창만 달라진다 —
    마을이 늘어날 때 같은 집이 복사된 것처럼 보이면 안 된다."""
    wall, roof, peak, windows = _HOUSE_STYLES[style % len(_HOUSE_STYLES)]
    px(x + 2, y - 6, 20, 12, wall)                           # 벽 (x+2 ~ x+22)
    for i in range(peak):                                    # 지붕 — 벽과 같은 x에서 시작해야
        px(x + 2 + i, y - 7 - i, 20 - 2 * i, 2, roof)        # 좌우가 안 어긋난다
    px(x + 8, y - 1, 6, 7, "#5a3a24")                        # 문
    px(x + 16, y - 4, 4, 4, "#ffe08a")                       # 창
    if windows > 1:
        px(x + 4, y - 4, 3, 3, "#ffe08a")


def _house(px: Px, x: float, y: float, t: int) -> None:
    _house_at(px, x, y, 0)


def _barn(px: Px, x: float, y: float, t: int) -> None:
    px(x + 2, y - 5, 22, 11, "#a9432f")                      # 벽
    for i in range(8):
        px(x + 1 + i, y - 6 - i, 22 - 2 * i, 2, "#7d2f20")   # 지붕
    px(x + 10, y - 1, 7, 7, "#e8d9c0")                       # 문
    px(x + 13, y - 1, 1, 7, "#a9432f")
    px(x + 26, y + 2, 2, 4, "#7d6b52")                       # 울타리
    px(x + 24, y + 2, 6, 1, "#7d6b52")


def _rocket(px: Px, x: float, y: float, t: int) -> None:
    px(x + 8, y - 14, 6, 12, "#d8dee9")                      # 동체
    px(x + 9, y - 17, 4, 3, "#d8dee9")                       # 노즈콘
    px(x + 10, y - 18, 2, 1, "#f85149")
    px(x + 9, y - 11, 4, 3, "#79c0ff")                       # 창
    px(x + 5, y - 5, 3, 4, "#f85149")                        # 날개
    px(x + 14, y - 5, 3, 4, "#f85149")
    px(x + 9, y - 2, 4, 3, "#ff9a5a")                        # 화염


def _greenhouse(px: Px, x: float, y: float, t: int) -> None:
    px(x + 2, y - 8, 22, 14, "#9fd8c8")                      # 유리
    for i in range(9):
        px(x + 2 + i, y - 9 - i, 22 - 2 * i, 1, "#5f9e8c")   # 지붕
    for c in range(4):                                       # 창틀
        px(x + 4 + c * 5, y - 8, 1, 14, "#5f9e8c")
    px(x + 26, y + 1, 3, 5, "#8a6a4a")                       # 물뿌리개
    px(x + 29, y + 2, 2, 1, "#8a6a4a")


def _mineshaft(px: Px, x: float, y: float, t: int) -> None:
    px(x + 1, y - 3, 24, 9, "#8a6f4a")                       # 갱구 테두리
    px(x + 4, y - 1, 18, 7, "#0d0b08")                       # 입구 (안이 캄캄해야 갱도)
    px(x + 1, y - 5, 24, 2, "#a98a5c")                       # 상인방
    px(x + 3, y - 12, 3, 9, "#8a6f4a")                       # 도르래 기둥
    px(x + 20, y - 12, 3, 9, "#8a6f4a")
    px(x + 3, y - 14, 20, 2, "#a98a5c")                      # 도르래 대들보
    px(x + 12, y - 12, 1, 7, "#d8cbb0")                      # 밧줄
    px(x + 10, y - 5, 5, 3, "#c9c9d1")                       # 광차


def _tower(px: Px, x: float, y: float, t: int) -> None:
    px(x + 2, y - 16, 9, 22, "#3b4252")                      # 고층
    px(x + 13, y - 9, 8, 15, "#4c566a")                      # 저층
    for row in range(5):                                     # 창
        for col in range(3):
            px(x + 3 + col * 3, y - 14 + row * 4, 2, 2, "#ffe08a")
    for row in range(3):
        for col in range(2):
            px(x + 15 + col * 3, y - 7 + row * 4, 2, 2, "#ffe08a")
    px(x + 6, y - 19, 1, 3, "#f85149")                       # 안테나


# ---------------------------------------------------------- 낚시 배경 고정물
# 낚시 테마 하나를 여러 배경으로 나눈다. 전부 물가에 서서 _angler를 부른다 —
# 낚는 사람의 동작은 배경마다 다시 만들지 않는다.


def _spot_pier(px: Px, x: float, y: float, t: int) -> None:
    """부둣가. 말뚝 위 판자 데크에 가로등과 나무 상자, 감아 둔 밧줄."""
    for i in range(0, 52, 12):
        px(x + i, y + 6, 3, 11, "#5a4128")                   # 말뚝 (물속까지)
    px(x - 2, y + 2, 54, 4, "#8b5a2b")                       # 데크 판자
    px(x - 2, y + 1, 54, 1, "#a97b4f")
    px(x + 20, y - 16, 2, 18, "#4a4a52")                     # 가로등 기둥
    px(x + 18, y - 19, 6, 4, "#4a4a52")
    px(x + 19, y - 18, 4, 2, "#ffe08a" if t % 60 < 45 else "#c9a227")
    px(x + 27, y - 4, 8, 6, "#a97b4f")                       # 나무 상자
    px(x + 27, y - 1, 8, 1, "#7d5a36")
    px(x + 46, y - 2, 5, 2, "#d8cbb0")                       # 감아 둔 밧줄
    px(x + 47, y - 3, 3, 1, "#d8cbb0")
    _angler(px, x + 36, y - 4, t)                            # 줄이 데크 밖 물에 닿는 자리


def _spot_rocks(px: Px, x: float, y: float, t: int) -> None:
    """갯바위. 검은 바위 무더기에 해초가 붙고 물보라가 부딪친다."""
    rocks = ((0, 5), (8, 9), (18, 13), (30, 8))
    for rx, h in rocks:
        px(x + rx, y + 6 - h, 12, h + 6, "#4a4844")
        px(x + rx + 1, y + 6 - h, 8, 2, "#6b6862")           # 하이라이트
    for sx, sh in ((3, 3), (14, 2), (35, 3)):                # 해초
        px(x + sx, y + 5 - sh, 1, sh, "#3f7d5f")
        px(x + sx + 1, y + 4 - sh, 1, 2, "#3f7d5f")
    splash = 3 if t % 40 < 12 else 1                         # 바위에 부딪히는 물보라
    px(x + 42, y + 3 - splash, 3, splash + 3, "#c9e4f5")
    px(x + 45, y + 5 - splash, 2, splash + 1, "#c9e4f5")
    _angler(px, x + 26, y - 11, t)                           # 가장 높은 바위 위


def _spot_breakwater(px: Px, x: float, y: float, t: int) -> None:
    """방파제. 물가(화면 왼쪽 끝)에서 이어진 둑 위에 빨간 등대가 선다 — 물 위에
    뚝 떨어진 콘크리트 덩어리처럼 보이면 안 된다."""
    tip = x + 34
    px(0, y + 3, tip + 10, 4, "#8b8b96")                     # 상판 — 왼쪽 끝부터
    for i in range(0, int(tip), 10):
        px(i, y + 7, 8, 5, "#6b6b76")                        # 테트라포드 몸통
        px(i + 2, y + 4, 4, 4, "#6b6b76")
    lx = x + 18                                              # 등대
    px(lx, y - 15, 7, 18, "#e8e8ee")
    px(lx, y - 11, 7, 3, "#f85149")
    px(lx, y - 4, 7, 3, "#f85149")
    px(lx + 1, y - 19, 5, 4, "#4a4a52")
    px(lx + 2, y - 18, 3, 2, "#ffe08a" if t % 40 < 20 else "#c9772f")
    _angler(px, x + 30, y - 3, t)                            # 둑 끝, 줄은 그 앞바다에


def _spot_island(px: Px, x: float, y: float, t: int) -> None:
    """섬. 모래톱과 야자수 — 코코넛, 굴러다니는 공, 조개껍데기."""
    px(x, y + 3, 48, 5, "#e0c98a")                           # 모래
    px(x, y + 3, 48, 1, "#f0dda8")                           # 마른 모래
    px(x + 5, y - 16, 2, 19, "#8a6a4a")                      # 야자수 줄기
    for dx, dy in ((-6, -2), (1, -5), (6, -2), (-1, -6)):
        px(x + 5 + dx, y - 16 + dy, 6, 3, "#3f9d5f")         # 야자잎
    px(x + 3, y - 12, 2, 2, "#7d5a36")                       # 코코넛
    px(x + 7, y - 11, 2, 2, "#7d5a36")
    px(x + 30, y + 4, 4, 3, "#f85149")                       # 공
    px(x + 31, y + 4, 2, 1, "#e8e8ee")
    px(x + 43, y + 6, 3, 1, "#f0dda8")                       # 조개껍데기
    px(x + 46, y + 5, 2, 2, "#e8d9c0")
    _angler(px, x + 34, y - 3, t)                            # 줄은 모래톱 너머 물에


def _spot_car(px: Px, x: float, y: float, t: int) -> None:
    """차박낚시. 트렁크를 연 차 옆에 캠핑 의자와 걸어 둔 랜턴."""
    px(x, y - 6, 30, 9, "#5a6a7a")                           # 차체
    px(x + 4, y - 11, 14, 6, "#3d4a56")                      # 트렁크 (열림)
    px(x + 6, y - 4, 8, 5, "#c9d1d9")                        # 창문
    px(x + 2, y + 3, 3, 2, "#0d1117")                        # 바퀴
    px(x + 24, y + 3, 3, 2, "#0d1117")
    px(x + 26, y - 4, 2, 2, "#ffe08a")                       # 미등
    px(x + 22, y - 16, 4, 4, "#c9d1d9")                      # 랜턴
    px(x + 23, y - 15, 2, 2, "#ffe08a" if t % 50 < 40 else "#c9a227")
    px(x + 33, y - 7, 1, 4, "#7d8590")                       # 캠핑 의자
    px(x + 33, y - 4, 7, 1, "#7d8590")
    px(x + 33, y - 3, 1, 3, "#4a4a52")
    px(x + 39, y - 3, 1, 3, "#4a4a52")
    _angler(px, x + 42, y - 3, t)                            # 물가에 서서 호수로 던진다


def _spot_camp(px: Px, x: float, y: float, t: int) -> None:
    """캠핑낚시. 텐트와 모닥불 — 걸어 둔 냄비와 랜턴."""
    px(x, y - 2, 20, 8, "#c9772f")                           # 텐트 몸체
    for i in range(9):
        px(x + i, y - 2 - i, 20 - 2 * i, 1, "#a9572f")       # 삼각 지붕
    px(x + 8, y + 1, 4, 5, "#7d3f1f")                        # 입구
    flick = 3 if t % 6 < 3 else 2                            # 깜빡이는 불씨
    px(x + 24, y + 4, 6, 2, "#5a4128")                       # 장작
    px(x + 26, y + 4 - flick, 3, flick, "#ff9a5a")           # 모닥불
    px(x + 23, y - 4, 1, 8, "#4a4a52")                       # 냄비 걸이
    px(x + 30, y - 4, 1, 8, "#4a4a52")
    px(x + 23, y - 5, 8, 1, "#4a4a52")
    px(x + 25, y - 3, 4, 3, "#6b6b76")                       # 냄비
    px(x + 35, y - 18, 1, 4, "#8a6a4a")                      # 랜턴 걸이
    px(x + 34, y - 14, 4, 4, "#c9d1d9")                      # 랜턴
    px(x + 35, y - 13, 2, 2, "#ffe08a" if t % 50 < 40 else "#c9a227")
    _angler(px, x + 42, y - 3, t)                            # 물가에 서서 호수로 던진다


def _edge_lakeside(px: Px, theme: "Theme", d: float, t: int) -> None:
    """호숫가. 차박·캠핑은 물 위가 아니라 물가에서 한다 — 바닥 대부분은 땅이고
    한쪽에만 호수가 있어야 차·텐트가 물 위에 뜬 것처럼 안 보인다.

    풀은 땅 쪽(x<60)에만 심는다 — 전체 폭에 깔면 물 위로도 잔디가 삐져나온다.
    물가 경계도 일직선이 아니라 삐뚤빼뚤해야 인공 수영장이 아니라 호수로 보인다.
    """
    import math

    tint = theme.horizon if d > 0.35 else theme.horizon_dusk
    px(0, HORIZON, 56, 1, tint)
    for i in range(0, 56, 3):                                # 잔디 — 땅 쪽에만
        blade = (i * 7 % 5) // 2
        if blade:
            px(i + math.sin((i + t) * 0.09), HORIZON - blade, 1, blade, tint)
    for i in range(0, 46, 13):                               # 바닥 잡초
        y = HORIZON + 12 + (i * 5 % 7) * 5
        px(i + 3, y, 1, 2, tint)

    # 물 — 땅은 왼쪽, 물은 오른쪽이므로 물가는 **세로** 경계다. 한 줄에 사각형
    # 하나씩(왼쪽 끝만 흔들어서) 채우면 틈이 생길 수 없고, 물 위쪽에 땅 색이
    # 띠처럼 남지도 않는다. 예전처럼 위쪽 경계를 흔들면 수면 위로 초록 띠가 떴다.
    water = "#4a7a9e" if d > 0.35 else "#2a4258"
    for dy in range(H - HORIZON):
        wobble = ((dy * 5) % 7) - 3                          # -3..3
        sx = 58 + wobble
        px(sx, HORIZON + dy, W - sx, 1, water)
    # 물결은 수면 **맨 위**에 놓는다. 안쪽에 그으면 물 위에 파란 선이 하나 더
    # 그어진 것처럼 보인다 — 물결 자체가 물의 윗 경계여야 한다.
    # theme.horizon(=잔디색)을 쓰면 호수에 초록 점이 뜨므로 물빛으로 찍는다.
    ripple = "#8fb8d8" if d > 0.35 else "#5a6b8c"
    for x in range(62, W, 2):                                # 물가 요철(최대 3)보다 안쪽에
        px(x, HORIZON + max(0.0, math.sin((x + t * 2) * 0.18) * 1.4), 2, 2, ripple)


def _ambient_gulls(px: Px, theme: "Theme", d: float, t: int) -> None:
    """갈매기 두 마리가 수평선 위를 미끄러진다. 바다 배경 공통 소품."""
    import math

    tint = "#e8e8ee" if d > 0.35 else "#8b93a8"
    for i in range(2):
        x = (t * (0.5 + i * 0.25) + i * 90) % (W + 24) - 12
        y = 15 + i * 10 + math.sin(t * 0.06 + i) * 3
        flap = (t // 6 + i) % 2
        px(x, y, 2, 1, tint)
        px(x - 3, y - flap, 3, 1, tint)
        px(x + 2, y - flap, 3, 1, tint)


def _ambient_sea(px: Px, theme: "Theme", d: float, t: int) -> None:
    """먼바다 — 지나가는 배와 갈매기."""
    _ambient_passing_boat(px, theme, d, t)
    _ambient_gulls(px, theme, d, t)


def _ambient_passing_boat(px: Px, theme: "Theme", d: float, t: int) -> None:
    """먼바다에 배 한 척이 가끔 지나간다. 대부분은 아무것도 안 그린다."""
    period, travel = 600, 160
    phase = t % period
    if phase >= travel:
        return
    x = -16 + (W + 32) * (phase / travel)
    y = HORIZON - 5
    tint = "#2b3040" if d > 0.35 else "#1a1d29"
    px(x, y, 12, 2, tint)
    px(x + 4, y - 3, 4, 3, tint)


# ---------------------------------------------------------------- 테마 정의

FISHING = Theme(
    key="fishing", name="낚시", unit="물고기",
    activity_word="입질", action_word="캐스팅",
    **labels(
        ("빈 바구니", "잔챙이", "반 바구니", "한 바구니", "만선"),
        ("빈 바구니", "잔챙이", "반 바구니", "한 바구니", "만선"),
        ("잠잠", "잔잔", "활발", "폭주"),
    ),
    sky=((26, 26, 58), (92, 160, 214)),
    ground=((10, 18, 44), (30, 90, 140)),
    horizon="#8fb8d8", horizon_dusk="#5a6b8c",
    unit_colors=("#e3a447", "#d96f4a", "#7ee787", "#79c0ff"),
    sprite=_fish, base=_boat,
    sky_decor=_sky_open, edge=_edge_waves,
    pile=_pile_net,                                          # 잡은 것은 그물에 담아 발치에 둔다
)

FISHING_SPOTS: dict[str, FishingSpot] = {
    s.key: s for s in (
        # 배경마다 물빛·하늘·소품이 다르다. 고정물만 바꾸면 결국 같은 바다에
        # 배 모양만 바뀐 것처럼 보인다.
        FishingSpot(
            "sea", "바다 위", FISHING.unit_colors, _boat,
            ambient=_ambient_sea,                              # 지나가는 배 + 갈매기
        ),
        FishingSpot(
            "pier", "부둣가", ("#5a9bd6", "#8fd9c4", "#c9d1d9", "#4a7a9e"), _spot_pier,
            base_bobs=False,                                   # 데크는 안 흔들린다
            ground=((10, 24, 42), (38, 96, 118)),              # 항구 물빛(초록기)
            horizon="#7fc0c0", horizon_dusk="#4a6b74",
            sky_decor=_sky_clouds, ambient=_ambient_gulls,
        ),
        FishingSpot(
            "rocks", "갯바위", ("#8a6a4a", "#5a7a4a", "#c98a5a", "#3d5a3d"), _spot_rocks,
            base_bobs=False,
            ground=((8, 14, 34), (24, 74, 118)),               # 차고 깊은 물
            horizon="#7fa8c8", horizon_dusk="#4a5f7a",
            ambient=_ambient_gulls,
        ),
        FishingSpot(
            "breakwater", "방파제", ("#c9d1d9", "#a5d8ff", "#c77dff", "#7d8590"), _spot_breakwater,
            base_bobs=False,
            ground=((10, 18, 46), (34, 86, 132)),
            sky_decor=_sky_clouds, ambient=_ambient_gulls,
            pile_offset=2,                                     # 바다 위가 아니라 방파제 상판 위에
        ),
        FishingSpot(
            "island", "섬", ("#ff7b72", "#ffd166", "#79c0ff", "#7ee787"), _spot_island,
            base_bobs=False,
            ground=((12, 44, 62), (58, 152, 168)),             # 열대 에메랄드빛
            horizon="#a8e4e0", horizon_dusk="#5f8f92",
            sky_decor=_sky_clouds, ambient=_ambient_gulls,
            pile_offset=16,                                    # 바다 위가 아니라 모래톱 위에
        ),
        FishingSpot(
            "car", "차박낚시", ("#8a9a5a", "#c9a227", "#6a8a4a", "#a97b4f"), _spot_car,
            # 물 위가 아니라 물가 — 바닥을 들판으로, 한쪽에만 호수를 둔다.
            ground=((28, 34, 26), (86, 122, 62)),
            horizon="#9ed46a", horizon_dusk="#4a5a3c",
            ground_sink=6, base_bobs=False,                    # 차는 잔디에 붙어 서 있어야 한다
            edge=_edge_lakeside, sky_decor=_sky_clouds,
            pile=_pile_net_shore,                              # 그물은 물가 풀밭에
            unit_x_range=(64, W - 6),                          # 헤엄치는 물고기도 물 밖으로 못 나간다
            base_x_range=(2, 6),                               # 차가 호수에 잠기면 안 된다
        ),
        FishingSpot(
            "camp", "캠핑낚시", ("#e8a0a0", "#7ee787", "#d9c07a", "#8fa8c9"), _spot_camp,
            ground=((30, 36, 24), (108, 142, 70)),
            horizon="#b6e07a", horizon_dusk="#55613e",
            ground_sink=6, base_bobs=False,
            edge=_edge_lakeside, sky_decor=_sky_clouds,
            pile=_pile_net_shore,
            unit_x_range=(64, W - 6),
            base_x_range=(2, 6),
        ),
    )
}
FISHING_SPOT_KEYS = tuple(FISHING_SPOTS)
DEFAULT_SPOT = "sea"


def get_spot(key: str | None) -> FishingSpot:
    """없는 키가 오면 기본 배경(바다 위). 설정 파일이 낡아도 화면은 뜬다."""
    return FISHING_SPOTS.get(key or "", FISHING_SPOTS[DEFAULT_SPOT])


def apply_spot(theme: Theme, spot_key: str | None) -> Theme:
    """낚시 테마에 배경을 입힌다. 낚시가 아니면 그대로 돌려준다 — 등급·집계는
    손대지 않고 배 대신 부둣가/갯바위를 세우고 물고기 색만 바꾼다.

    차박·캠핑처럼 물가인 배경은 바닥·하늘·배경 연출까지 같이 갈아 끼운다 —
    None인 필드는 낚시(바다) 기본값을 그대로 물려받는다."""
    if theme.key != "fishing":
        return theme
    spot = get_spot(spot_key)
    changes = {"base": spot.base, "unit_colors": spot.unit_colors}
    for field in (
        "ground", "horizon", "horizon_dusk", "edge", "sky_decor", "ambient",
        "pile", "pile_offset", "unit_x_range", "base_x_range",
        "ground_sink", "base_bobs",
    ):
        value = getattr(spot, field)
        if value is not None:
            changes[field] = value
    return replace(theme, **changes)


VILLAGE = Theme(
    key="village", name="마을", unit="주민",
    activity_word="북적임", action_word="방문",
    **labels(
        ("빈 터", "오두막", "작은 마을", "큰 마을", "번화가"),
        ("빈 터", "오두막", "작은 마을", "큰 마을", "번화가"),
        ("고요", "한산", "붐빔", "장날"),
    ),
    sky=((32, 28, 52), (128, 176, 208)),
    ground=((28, 34, 26), (86, 122, 62)),
    horizon="#9ed46a", horizon_dusk="#4a5a3c",
    unit_colors=("#d98b6f", "#7fa7d9", "#c9a227", "#a48fd0"),
    sprite=_person, base=_house,
    sky_decor=_sky_clouds, edge=_edge_grass,
    ground_sink=4,                                            # 집이 경계선에 걸치면 떠 보인다
    base_bobs=False,                                          # 집은 안 흔들린다
    base_x_range=(4, 10),                                     # 옆으로 집 한 줄이 다 들어갈 자리
    pile=_pile_houses,                                         # 고갈 모드: 집이 한 채씩 는다
)

RANCH = Theme(
    key="ranch", name="목장", unit="동물",
    activity_word="울음소리", action_word="먹이 주기",
    **labels(
        ("빈 우리", "몇 마리", "무리", "큰 무리", "가득한 목장"),
        ("빈 우리", "몇 마리", "무리", "큰 무리", "가득한 목장"),
        ("낮잠", "느긋", "활발", "야단법석"),
    ),
    sky=((38, 30, 46), (146, 190, 214)),
    ground=((30, 36, 24), (108, 142, 70)),
    horizon="#b6e07a", horizon_dusk="#55613e",
    unit_colors=("#f0e6d2", "#c98a5a", "#8a6a4a", "#e8c39e"),
    sprite=_animal, base=_barn,
    sky_decor=_sky_clouds, edge=_edge_grass,
    ground_sink=4,
    base_bobs=False,
    pile=_pile_corral,                                         # 헛간 아래 둥근 울타리 안으로 모인다
    pile_band=(84, 116),                                       # 우리 안쪽은 돌아다니는 동물 금지
)

SPACE = Theme(
    key="space", name="우주", unit="별",
    activity_word="전파", action_word="교신",
    **labels(
        ("빈 하늘", "첫 별", "성단", "은하", "가득한 우주"),
        ("빈 하늘", "첫 별", "성단", "은하", "가득한 우주"),
        ("정적", "미약", "활발", "폭발"),
    ),
    # 바닥이 하늘과 같은 색이다 — 행성 표면을 따로 두지 않는다. 발 디딜 지면이
    # 있으면 우주가 아니라 행성이 된다.
    sky=((8, 6, 24), (36, 30, 78)),
    ground=((8, 6, 24), (36, 30, 78)),
    horizon="#4b4380", horizon_dusk="#241f45",
    unit_colors=("#ffe08a", "#a5d8ff", "#ffb3c7", "#d0bfff"),
    sprite=_star, base=_rocket,
    sky_decor=_sky_stars, edge=_edge_galaxy,
    unit_band=(6, H - 8),                                    # 은하는 화면 전체가 하늘이다
    sun=("#f2f2f2", "#cfc4a8"),
    pile=_pile_flame,                                          # 별은 안 쌓인다 — 로켓 불꽃이 커진다
)

GARDEN = Theme(
    key="garden", name="정원", unit="꽃",
    activity_word="개화", action_word="물주기",
    **labels(
        ("맨 흙", "새싹", "화단", "만발", "꽃밭"),
        ("맨 흙", "새싹", "화단", "만발", "꽃밭"),
        ("잠듦", "느릿", "한창", "폭발"),
    ),
    sky=((44, 34, 54), (168, 200, 224)),
    ground=((34, 30, 22), (96, 116, 58)),
    horizon="#c2e07a", horizon_dusk="#5b6440",
    unit_colors=("#ff8fab", "#ffd166", "#c77dff", "#ff9770"),
    sprite=_flower, base=_greenhouse,
    sky_decor=_sky_clouds, edge=_edge_grass,
    unit_drifts=False,
    ambient=_ambient_butterflies,
    ground_sink=4,
    base_bobs=False,
    pile=_pile_bed,                                            # 온실 아래 둥근 화단에 꽃이 는다
    pile_band=(84, 116),                                       # 화단 안쪽은 들꽃 금지
)

MINE = Theme(
    key="mine", name="광산", unit="광석",
    activity_word="곡괭이질", action_word="채굴",
    **labels(
        ("빈 갱도", "부스러기", "광맥", "노다지", "대박"),
        ("빈 갱도", "부스러기", "광맥", "노다지", "대박"),
        ("멈춤", "느릿", "활발", "전속력"),
    ),
    sky=((18, 14, 12), (58, 46, 38)),
    ground=((12, 10, 9), (44, 36, 30)),
    horizon="#6b5a42", horizon_dusk="#2e2721",
    unit_colors=("#79c0ff", "#7ee787", "#ff7b72", "#e3c447"),
    sprite=_gem, base=_mineshaft,
    sky_decor=_sky_cave, edge=_edge_rubble,
    sun=("#ffd76e", "#8a6a4a"),
    unit_drifts=False, unit_bobs=False,                      # 광석은 벽에 박혀 있다
    ambient=_ambient_minecart,
    ground_sink=4,
    base_bobs=False,
    pile=_pile_cart,                                          # 못 담은 광석은 광차에 채운다
)

CITY = Theme(
    key="city", name="도시", unit="차",
    activity_word="교통량", action_word="운행",
    **labels(
        ("텅 빈 도로", "드문드문", "차량 행렬", "정체", "꽉 막힘"),
        ("텅 빈 도로", "드문드문", "차량 행렬", "정체", "꽉 막힘"),
        ("한밤", "한산", "붐빔", "출퇴근"),
    ),
    sky=((22, 20, 40), (110, 140, 180)),
    ground=((20, 20, 24), (58, 58, 66)),
    horizon="#8b8b96", horizon_dusk="#3a3a42",
    unit_colors=("#f85149", "#79c0ff", "#e3c447", "#d8dee9"),
    sprite=_car, base=_tower,
    sky_decor=_sky_skyline, edge=_edge_road,
    unit_bobs=False, unit_lanes=2,                           # 중앙선 기준 왼쪽/오른쪽이 각자 한 방향
    # 차선 한가운데를 달리도록 구간을 도로 폭(연석 66 ~ 반대편 연석 116)에 맞춘다.
    # 차 스프라이트가 y-2..y+4라 차선 중심에서 1px 올려 잡아야 가운데가 맞는다.
    unit_band=(65, 115),
    ground_sink=4,
    base_bobs=False,
    pile=_pile_towers,                                        # 고갈 모드: 불 켜진 건물이 는다
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

        top, bottom = theme.unit_band
        assert 0 <= top < bottom <= H, f"{key}: 사는 구간이 화면 밖이다"

        for layer, call in (
            ("sprite", lambda: theme.sprite(px, 10, top + 6, theme.unit_colors[0], 1, 30)),
            ("base", lambda: theme.base(px, 10, HORIZON - 8, 30)),
            ("sky_decor", lambda: theme.sky_decor(px, theme, 0.7, 30)),
            ("edge", lambda: theme.edge(px, theme, 0.7, 30)),
        ):
            before = len(drawn)
            call()
            assert len(drawn) > before, f"{key}: {layer} 가 아무것도 안 그린다"

        # pile은 아무것도 안 그리는 게 정상인 테마(마을·도시)가 있다.
        # 그리는지가 아니라 터지지 않는지만 본다.
        theme.pile(px, theme, 40, HORIZON, 12, 30)

    print(f"themes.py selfcheck OK ({len(THEMES)}개)")


if __name__ == "__main__":
    _selfcheck()
