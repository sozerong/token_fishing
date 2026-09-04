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

from dataclasses import dataclass, field

from .aggregate import WINDOW, Snapshot

# 튜닝 손잡이. 실측 감각으로 잡은 값이라 써 보고 고치라고 밖에 빼뒀다.
FISH_PER_TOKEN = 2_000
"""물고기 한 마리 = 조업량 2,000토큰. 한 세션에 수십 마리가 나오는 눈금."""

MAX_FISH_DRAWN = 24
"""화면에 그릴 최대 마리 수. 넘으면 숫자로만 센다 — 도트 화면이 물고기로 덮이면 못 읽는다."""

BITE_LEVELS = (
    (0, "잠잠"),
    (500, "잔잔"),
    (5_000, "활발"),
    (50_000, "폭주"),
)
"""분당 토큰 → 입질 등급. 경계값 이상이면 그 등급."""

CATCH_TIERS = (
    (0, "빈 바구니"),
    (5_000, "잔챙이"),
    (50_000, "제법"),
    (200_000, "월척"),
    (1_000_000, "대물"),
)


def _level(value: float, table: tuple[tuple[int, str], ...]) -> str:
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

    tokens: dict[str, int] = field(default_factory=dict)
    """네 항목 원본. 화면이 다르게 세고 싶을 때를 위해 그대로 싣는다."""

    provenance: dict[str, int] = field(default_factory=dict)
    """윈도우 안 요청들의 provenance 분포. 숫자의 출처를 화면에서도 숨기지 않는다."""


def to_game_state(
    snap: Snapshot, provenance: dict[str, int] | None = None
) -> GameState:
    w = snap.window
    if w is None:
        return GameState(
            is_fishing=False,
            catch=0,
            fish=0,
            fish_uncapped=0,
            tier=CATCH_TIERS[0][1],
            bite=BITE_LEVELS[0][1],
            bite_per_min=snap.tokens_per_minute,
            minutes_left=None,
            daylight=0.0,
            tokens={},
            provenance=provenance or {},
        )

    catch = w.input_tokens + w.output_tokens
    uncapped = catch // FISH_PER_TOKEN
    left = snap.time_to_reset
    minutes_left = int(left.total_seconds() // 60) if left else 0

    return GameState(
        is_fishing=True,
        catch=catch,
        fish=min(uncapped, MAX_FISH_DRAWN),
        fish_uncapped=uncapped,
        tier=_level(catch, CATCH_TIERS),
        bite=_level(snap.tokens_per_minute, BITE_LEVELS),
        bite_per_min=snap.tokens_per_minute,
        minutes_left=minutes_left,
        # 남은 시간이 많을수록 해가 높다.
        daylight=max(0.0, min(1.0, (left.total_seconds() / WINDOW.total_seconds()) if left else 0.0)),
        tokens={
            "input": w.input_tokens,
            "output": w.output_tokens,
            "cache_creation": w.cache_creation_tokens,
            "cache_read": w.cache_read_tokens,
        },
        provenance=provenance or {},
    )
