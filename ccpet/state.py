"""Snapshot → GameState. 숫자를 낚시 은유로 옮기기만 한다.

여기서 새 집계를 하지 않는다. 필요하면 aggregate에 넣고 compare로 검증한 뒤 가져온다.

    조업량   = input + output   (5시간 한도가 실제로 세는 값)
    입질     = burn rate
    해       = 리셋까지 남은 시간

왜 input+output만 조업량으로 쓰나: 레퍼런스의 5시간 한도 카운터와 정확히 일치한다
(실측 input 156 + output 82,439 = tokens_used 82,595). 총합을 쓰면 cache_read가 96%를
차지해서 화면이 사실상 캐시 읽기 그래프가 된다. 네 항목은 GameState에 그대로 실어두니
Phase 3에서 다르게 세고 싶으면 거기서 골라 쓰면 된다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config, themes
from .aggregate import WINDOW, Snapshot, collect_entries, snapshot, weekly_totals

# 튜닝 손잡이. 실측 감각으로 잡은 값이라 써 보고 고치라고 밖에 빼뒀다.
FISH_PER_TOKEN = 2_000
"""움직이는 것 하나 = 조업량 2,000토큰. 한 세션에 수십 개가 나오는 눈금."""

MAX_FISH_DRAWN = 24
"""화면에 그릴 최대 개수. 넘으면 숫자로만 센다 — 도트 화면이 덮이면 못 읽는다."""

# 라벨 표는 themes 로 옮겼다. 같은 경계값에 테마마다 다른 이름을 붙인다 —
# 등급이 바뀌는 지점은 전 테마 공통이므로 숫자의 뜻은 달라지지 않는다.
def _level(value: float, table: tuple[tuple[float, str], ...]) -> str:
    label = table[0][1]
    for threshold, name in table:
        if value >= threshold:
            label = name
    return label


@dataclass(frozen=True, slots=True)
class GameState:
    """도트 화면이 읽는 전부. 렌더러가 aggregate나 parser를 알 필요가 없다."""

    is_fishing: bool
    """활성 윈도우가 있는가. False면 조업 종료 상태."""

    catch: int
    """조업량 = input + output. 5시간 한도가 세는 값."""

    fish: int
    """그릴 물고기 마리 수 (MAX_FISH_DRAWN에서 잘림)."""

    fish_uncapped: int
    """자르기 전 마리 수. 화면에 '외 n마리'로 쓴다."""

    tier: str
    bite: str
    bite_per_min: float

    minutes_left: int | None
    daylight: float
    """1.0이면 방금 조업 시작, 0.0이면 리셋 직전. 해 높이로 그린다."""

    pinned: bool = False
    """리셋 시각이 공식 UI에서 꽂은 값인가.

    False면 JSONL로 추정한 값이다. claude.ai 웹/모바일 사용량은 같은 5시간 한도를
    먹지만 JSONL에 안 남기 때문에, 그런 사용이 창을 열었으면 추정이 어긋난다.
    화면에서 이걸 숨기지 말 것 — 틀릴 수 있는 숫자를 확실한 척 보여주면 안 된다."""

    used_percentage: float | None = None
    """5시간 창 사용률(0~100). 공식 수치가 있을 때만 채워진다. 추정하지 않는다."""

    weekly_percentage: float | None = None

    mode: str = config.CATCH
    """CATCH면 쓸수록 늘고, DEPLETION이면 쓸수록 줄어든다."""

    theme: str = themes.DEFAULT
    """화면 컨셉 키. 그림과 라벨만 바꾸고 숫자는 건드리지 않는다."""

    fill: float | None = None
    """창을 얼마나 채웠나 (0~1). 공식 사용률이 있으면 그 값, 없으면 플랜 눈금 기준.
    둘 다 없으면 None — 고갈 모드는 이 값이 있어야 의미가 있다."""

    fill_source: str = "none"
    """"official" | "learned" | "none". 어디서 온 숫자인지 화면에서 밝힌다."""

    official_age_min: int | None = None
    """공식 사용률을 받아둔 지 몇 분 됐나. 오래됐으면 화면이 그렇다고 밝힌다.

    기기가 두 대면 여기서 갈린다 — 값은 계정 기준이라 맞지만 그 기기가
    마지막으로 받아둔 시점이 다르다."""

    official_source: str = "none"
    """공식 사용률의 출처: "hook" | "app" | "none".

    fill_source가 official이 아닐 때 **왜인지**를 화면에 적는 데 쓴다.
    "어림"만 뜨고 이유가 없으면 훅이 없는 건지 앱이 꺼진 건지 알 수가 없다."""

    casts: int = 0
    """이번 창에서 던진 횟수 = 요청 수."""

    on_boat: int = 0
    """배 위에 쌓인 물고기. 고갈 모드에서 바다에서 사라진 만큼이다."""

    weekly_catch: int = 0
    """주간 리셋 이후 조업량. 공식 화면의 "주간 한도"에 대응한다. 0이면 미계산."""

    tokens: dict[str, int] = field(default_factory=dict)
    """네 항목 원본. 화면이 다르게 세고 싶을 때를 위해 그대로 싣는다."""

    provenance: dict[str, int] = field(default_factory=dict)
    """윈도우 안 요청들의 provenance 분포. 숫자의 출처를 화면에서도 숨기지 않는다."""


def _fill(
    snap: Snapshot, catch: int, learned_limit: int | None
) -> tuple[float | None, str]:
    """창을 얼마나 채웠는지 0~1로. 공식 수치가 있으면 그것, 없으면 학습한 한도."""
    if snap.used_percentage is not None:
        return max(0.0, min(1.0, snap.used_percentage / 100)), "official"
    if learned_limit:
        return max(0.0, min(1.0, catch / learned_limit)), "learned"
    return None, "none"


def to_game_state(
    snap: Snapshot,
    provenance: dict[str, int] | None = None,
    weekly_catch: int = 0,
    mode: str = config.CATCH,
    learned_limit: int | None = None,
    theme: str = themes.DEFAULT,
) -> GameState:
    look = themes.get(theme)
    w = snap.window
    catch = w.catch if w else 0
    # 창이 없으면 채운 비율도 없다. 등급은 절대량(0)으로 떨어진다.
    fill, fill_source = _fill(snap, catch, learned_limit) if w else (None, "none")

    on_boat = 0
    if w is None:
        uncapped = 0
    elif mode == config.DEPLETION and fill is not None:
        # 고갈 모드: 바다가 가득 찬 상태에서 시작해 쓸수록 비어 간다.
        # 바다에서 사라진 만큼이 배 위에 쌓인다 — 합은 항상 MAX_FISH_DRAWN.
        uncapped = round(MAX_FISH_DRAWN * (1.0 - fill))
        on_boat = MAX_FISH_DRAWN - uncapped
    else:
        # 축적 모드: 화면에 다 못 그리는 만큼(24마리 초과분)은 그냥 숫자로만
        # 남는다(fish_uncapped). 더미는 "사라진 만큼 쌓인다"는 고갈 모드의
        # 은유라 축적 모드에 가져오면 뜻이 안 맞는다 — 아무것도 안 쌓는다.
        uncapped = catch // FISH_PER_TOKEN

    left = snap.time_to_reset  # 창이 없으면 None

    return GameState(
        is_fishing=w is not None,
        catch=catch,
        fish=min(uncapped, MAX_FISH_DRAWN),
        fish_uncapped=uncapped,
        # 사용률을 알면 비율로, 모르면 절대량으로 등급을 매긴다.
        tier=(
            _level(fill, look.fill_tiers) if fill is not None
            else _level(catch, look.catch_tiers)
        ),
        bite=_level(snap.tokens_per_minute, look.activity_tiers),
        bite_per_min=snap.tokens_per_minute,
        minutes_left=None if left is None else int(left.total_seconds() // 60),
        # 남은 시간이 많을수록 해가 높다.
        daylight=max(0.0, min(1.0, left / WINDOW)) if left else 0.0,
        pinned=snap.pinned,
        mode=mode,
        theme=look.key,
        casts=w.entries if w else 0,
        on_boat=on_boat,
        fill=fill,
        fill_source=fill_source,
        official_source=snap.official_source,
        official_age_min=snap.official_age_min,
        used_percentage=snap.used_percentage,
        weekly_percentage=snap.weekly_percentage,
        weekly_catch=weekly_catch,
        tokens={
            "input": w.input_tokens,
            "output": w.output_tokens,
            "cache_creation": w.cache_creation_tokens,
            "cache_read": w.cache_read_tokens,
        } if w else {},
        provenance=provenance or {},
    )


def build_state(settings: dict | None = None) -> GameState:
    """디스크에 있는 것 전부 → 화면이 읽는 상태 하나. 팝업과 HTML의 공통 진입점.

    새 집계를 여기서 만들지 않는다. aggregate가 준 값을 모아 to_game_state에 넘길 뿐이다.
    """
    settings = settings or config.load()
    entries = collect_entries()
    now = datetime.now(timezone.utc)
    snap = snapshot(entries, now)
    w = snap.window

    # provenance는 화면에 뜬 그 창에 대한 것이어야 한다 — 창을 다시 계산하지 않는다.
    prov = Counter(e.provenance for e in entries if w and w.start <= e.timestamp < w.end)

    # 공식 사용률을 본 김에 이 계정의 한도를 재둔다. 나중에 훅이 없을 때 쓴다.
    if config.learn_limit(settings, w.catch if w else 0, snap.used_percentage):
        config.save(settings)

    return to_game_state(
        snap,
        dict(prov),
        weekly_catch=weekly_totals(entries, now).catch,
        mode=settings["mode"],
        learned_limit=settings.get("learned_limit"),
        theme=settings.get("theme", themes.DEFAULT),
    )
