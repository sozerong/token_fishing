"""GameState 매핑 기대값. 은유가 숫자를 왜곡하지 않는지 고정한다.

pytest 없이도 돌아간다:  py -3.12 tests/test_state.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccpet.aggregate import Snapshot, Window  # noqa: E402
from ccpet import config  # noqa: E402
from ccpet.state import FISH_PER_TOKEN, MAX_FISH_DRAWN, to_game_state  # noqa: E402


def utc(h: int, m: int = 0) -> datetime:
    return datetime(2026, 9, 2, h, m, tzinfo=timezone.utc)


def window(inp: int, out: int, cw: int = 0, cr: int = 0, entries: int = 1) -> Window:
    return Window(utc(9), entries, inp, out, cw, cr)


def snap(w: Window | None, per_min: float = 0.0, now: datetime | None = None) -> Snapshot:
    return Snapshot(window=w, tokens_per_minute=per_min, now=now or utc(11))


def test_catch_is_input_plus_output_only():
    """조업량은 한도가 실제로 세는 값이다. cache가 섞이면 화면이 캐시 그래프가 된다."""
    gs = to_game_state(snap(window(inp=156, out=82_439, cw=300_000, cr=10_000_000)))

    assert gs.catch == 82_595
    # 캐시는 버리지 않고 원본으로 실어둔다
    assert gs.tokens["cache_read"] == 10_000_000
    assert gs.tokens["cache_creation"] == 300_000
    assert gs.catch != gs.tokens["cache_read"]


def test_fish_count_is_capped_for_drawing_but_truth_is_kept():
    big = to_game_state(snap(window(inp=0, out=FISH_PER_TOKEN * 500)))

    assert big.fish_uncapped == 500
    assert big.fish == MAX_FISH_DRAWN
    assert big.fish < big.fish_uncapped, "화면은 잘라도 진짜 숫자는 남아야 한다"

    small = to_game_state(snap(window(inp=0, out=FISH_PER_TOKEN * 3)))
    assert small.fish == 3 and small.fish_uncapped == 3


def test_tier_and_bite_thresholds():
    """사용률을 모를 때는 절대 토큰으로 등급을 매긴다."""
    assert to_game_state(snap(window(0, 0))).tier == "빈 바구니"
    assert to_game_state(snap(window(0, 10_000))).tier == "잔챙이"
    assert to_game_state(snap(window(0, 60_000))).tier == "반 바구니"
    assert to_game_state(snap(window(0, 250_000))).tier == "한 바구니"
    assert to_game_state(snap(window(0, 2_000_000))).tier == "만선"

    assert to_game_state(snap(window(0, 1), per_min=0)).bite == "잠잠"
    assert to_game_state(snap(window(0, 1), per_min=600)).bite == "잔잔"
    assert to_game_state(snap(window(0, 1), per_min=9_000)).bite == "활발"
    assert to_game_state(snap(window(0, 1), per_min=120_000)).bite == "폭주"


def test_daylight_tracks_time_left():
    w = window(0, 100)  # 09:00 ~ 14:00

    start = to_game_state(snap(w, now=utc(9)))
    assert start.daylight == 1.0
    assert start.minutes_left == 300

    mid = to_game_state(snap(w, now=utc(11, 30)))
    assert abs(mid.daylight - 0.5) < 1e-9
    assert mid.minutes_left == 150

    edge = to_game_state(snap(w, now=utc(14)))
    assert edge.daylight == 0.0
    assert edge.minutes_left == 0


def test_no_active_window_means_fishing_is_over():
    gs = to_game_state(snap(None, per_min=0))

    assert gs.is_fishing is False
    assert gs.catch == 0
    assert gs.fish == 0
    assert gs.minutes_left is None
    assert gs.daylight == 0.0


def test_provenance_is_carried_to_the_screen():
    """숫자의 출처를 화면에서도 숨기지 않는다."""
    gs = to_game_state(
        snap(window(1, 2)), provenance={"stable": 70, "aborted_mid_stream": 1}
    )
    assert gs.provenance["aborted_mid_stream"] == 1


def test_daylight_never_leaves_zero_to_one():
    w = window(0, 1)
    for hour in (9, 12, 14, 20):
        gs = to_game_state(snap(w, now=utc(hour)))
        assert 0.0 <= gs.daylight <= 1.0, hour


def test_tier_follows_the_percentage_when_it_is_known():
    """사용률을 알면 비율로 등급을 매긴다.

    절대량으로 매기면 플랜에 따라 뜻이 달라진다 — Pro의 20만 토큰과 Max 20x의
    20만 토큰은 전혀 다른 상황인데 같은 등급이 나온다.
    """
    w = window(inp=0, out=200_000)   # 토큰만 보면 "한 바구니"

    def tier_at(pct):
        return to_game_state(
            Snapshot(window=w, tokens_per_minute=0.0, now=utc(11),
                     pinned=True, used_percentage=pct)
        ).tier

    assert tier_at(0) == "빈 바구니"
    assert tier_at(10) == "잔챙이"
    assert tier_at(35) == "반 바구니"
    assert tier_at(65) == "한 바구니"
    assert tier_at(95) == "만선"

    # 같은 토큰 수인데 사용률이 낮으면 등급도 낮다
    assert tier_at(5) != to_game_state(snap(w)).tier


def test_depletion_mode_empties_the_sea_as_you_spend():
    """고갈 모드: 바다가 가득 찬 상태로 시작해 쓸수록 비어 간다."""
    w = window(inp=0, out=100)

    empty = to_game_state(snap(w, now=utc(11)), mode=config.DEPLETION)
    # 공식 사용률이 없으면 채움 비율을 모른다 → 고갈로 그릴 근거가 없다
    assert empty.fill is None
    assert empty.fill_source == "none"

    for pct, expected in ((0, MAX_FISH_DRAWN), (50, MAX_FISH_DRAWN // 2), (100, 0)):
        s = Snapshot(window=w, tokens_per_minute=0.0, now=utc(11),
                     pinned=True, used_percentage=pct)
        gs = to_game_state(s, mode=config.DEPLETION)
        assert gs.fish == expected, pct
        assert gs.fill_source == "official"


def test_catch_mode_is_unaffected_by_percentage():
    """축적 모드는 예전 그대로 — 조업량만큼 물고기가 쌓인다."""
    w = window(inp=0, out=FISH_PER_TOKEN * 7)
    s = Snapshot(window=w, tokens_per_minute=0.0, now=utc(11),
                 pinned=True, used_percentage=90)

    gs = to_game_state(s, mode=config.CATCH)

    assert gs.fish == 7, "사용률이 높아도 축적 모드는 잡은 만큼 센다"


def test_plan_fills_in_when_official_percentage_is_missing():
    """공식 수치가 없을 때만 플랜 눈금을 쓴다. 있으면 공식이 이긴다."""
    catch = config.PLAN_CATCH_LIMITS["pro"] // 4        # Pro 기준 25%
    w = window(inp=0, out=catch)

    by_plan = to_game_state(snap(w, now=utc(11)), mode=config.DEPLETION, plan="pro")
    assert by_plan.fill_source == "plan"
    assert abs(by_plan.fill - 0.25) < 0.01
    assert by_plan.fish == round(MAX_FISH_DRAWN * 0.75)

    official = to_game_state(
        Snapshot(window=w, tokens_per_minute=0.0, now=utc(11),
                 pinned=True, used_percentage=80),
        mode=config.DEPLETION, plan="pro",
    )
    assert official.fill_source == "official", "공식 수치가 플랜 눈금을 이긴다"
    assert abs(official.fill - 0.80) < 0.01


def test_learned_limit_beats_the_plan_table():
    """공식 사용률을 한 번 보면 이 계정의 한도를 재서 기억한다.

    표에 박아둔 근사치보다 실제로 관측한 값이 낫다. 플랜을 안 골라도 된다.
    """
    settings = dict(config.DEFAULTS)

    # 공식 75%인 순간의 조업량이 225,478이었다면 한도는 약 300,637
    assert config.learn_limit(settings, 225_478, 75.0) is True
    assert abs(settings["learned_limit"] - 300_637) < 10

    # 너무 이른 시점(사용률이 낮을 때)에는 배우지 않는다. 나눗셈 오차가 크다.
    early = dict(config.DEFAULTS)
    assert config.learn_limit(early, 3_000, 1.0) is False
    assert early["learned_limit"] is None

    # 잔떨림으로 매번 다시 쓰지 않는다
    assert config.learn_limit(settings, 225_500, 75.0) is False

    # 배운 값이 플랜 표를 이긴다
    w = window(inp=0, out=150_000)
    gs = to_game_state(
        snap(w, now=utc(11)), plan="max20",
        learned_limit=settings["learned_limit"],
    )
    assert gs.fill_source == "learned"
    assert abs(gs.fill - 150_000 / settings["learned_limit"]) < 0.01


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
        else:
            print(f"ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
