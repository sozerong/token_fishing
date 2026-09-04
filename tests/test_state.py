"""GameState 매핑 기대값. 은유가 숫자를 왜곡하지 않는지 고정한다.

pytest 없이도 돌아간다:  py -3.12 tests/test_state.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccpet.aggregate import Snapshot, Window  # noqa: E402
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
    assert to_game_state(snap(window(0, 0))).tier == "빈 바구니"
    assert to_game_state(snap(window(0, 10_000))).tier == "잔챙이"
    assert to_game_state(snap(window(0, 60_000))).tier == "제법"
    assert to_game_state(snap(window(0, 250_000))).tier == "월척"
    assert to_game_state(snap(window(0, 2_000_000))).tier == "대물"

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
