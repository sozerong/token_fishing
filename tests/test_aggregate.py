"""윈도우/burn rate 기대값. overlapping.jsonl이 주인공이다.

pytest 없이도 돌아간다:  py -3.12 tests/test_aggregate.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccpet.aggregate import (  # noqa: E402
    build_windows,
    burn_rate,
    collect_entries,
    current_window,
    snapshot,
)
from ccpet.parser import UsageEntry, parse_file  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def utc(h: int, m: int = 0, day: int = 2) -> datetime:
    return datetime(2026, 9, day, h, m, tzinfo=timezone.utc)


def overlapping():
    return parse_file(FIXTURES / "overlapping.jsonl").entries


def test_overlapping_sessions_merge_into_one_timeline():
    """s-A와 s-B는 서로 다른 세션이지만 한도는 계정 단위다. 한 블록에 합쳐진다."""
    windows = build_windows(overlapping())

    assert len(windows) == 2

    first = windows[0]
    assert first.start == utc(9)
    assert first.end == utc(14)
    # 09:00(A) 11:00(A) 12:30(B) 13:30(A) — 세션이 섞여 들어간다
    assert first.entries == 4
    assert first.input_tokens == 4
    assert first.output_tokens == 100
    assert first.cache_creation_tokens == 400
    assert first.cache_read_tokens == 4000
    assert first.total_tokens == 4504

    second = windows[1]
    assert second.start == utc(15)
    assert second.end == utc(20)
    # 14:00에 첫 블록이 끝나서 15:00(B)이 새 블록을 연다
    assert second.entries == 2
    assert second.output_tokens == 110
    assert second.total_tokens == 2 + 110 + 200 + 2000


def entry(rid: str, ts: datetime, out: int, inp: int = 1) -> UsageEntry:
    return UsageEntry(
        request_id=rid, session_id="s", timestamp=ts, model="claude-opus-5",
        input_tokens=inp, output_tokens=out, cache_creation_tokens=0,
        cache_read_tokens=0, is_sidechain=False, provenance="stable",
    )


def test_block_start_is_not_floored():
    """13:36에 시작한 블록은 13:36~18:36이다. 정시로 내리지 않는다.

    한때 내렸다. claude-monitor가 13:00을 내놓길래 맞춘 건데, 공식 사용량 화면과
    대조하니 실제 세션 시작은 15:17 — 정시가 아니었다. 레퍼런스는 대조군이지
    정답지가 아니다.
    """
    windows = build_windows([entry("a", utc(13, 36), 10), entry("b", utc(18, 40), 20)])

    assert len(windows) == 2
    assert windows[0].start == utc(13, 36)
    assert windows[0].end == utc(18, 36)
    assert windows[1].start == utc(18, 40)


def test_pinned_reset_overrides_the_guess(monkeypatch=None):
    """공식 UI에서 읽은 리셋 시각을 꽂으면 그 창만으로 센다.

    JSONL만 보면 13:36이 창을 연 것처럼 보이지만, 실제로는 보이지 않는 웹/모바일
    사용이 이미 창을 열어둔 상태였고 15:17이 새 창의 시작이었다. 실측 사례다.
    """
    import os

    entries = [
        entry("before", utc(13, 36), 999),   # 이전 창에 속한다
        entry("after", utc(15, 20), 10),     # 진짜 현재 창
        entry("after2", utc(16, 00), 20),
    ]

    guessed = snapshot(entries, now=utc(17, 0))
    assert guessed.window is not None
    assert guessed.window.start == utc(13, 36), "고정 없으면 첫 요청을 창 시작으로 본다"
    assert guessed.window.output_tokens == 1029
    assert guessed.pinned is False

    os.environ["TOKENFISHING_RESET_AT"] = utc(20, 17).isoformat()
    try:
        pinned = snapshot(entries, now=utc(17, 0))
    finally:
        del os.environ["TOKENFISHING_RESET_AT"]

    assert pinned.pinned is True
    assert pinned.window is not None
    assert pinned.window.start == utc(15, 17)
    # 이전 창의 999 토큰이 빠진다
    assert pinned.window.output_tokens == 30
    assert pinned.window.entries == 2
    assert pinned.time_to_reset == timedelta(hours=3, minutes=17)


def test_current_window_and_reset():
    windows = build_windows(overlapping())

    active = current_window(windows, utc(13))
    assert active is not None and active.start == utc(9)
    assert active.time_to_reset(utc(13)) == timedelta(hours=1)

    # 14:00~15:00 사이에는 활성 블록이 없다. 리셋된 상태.
    assert current_window(windows, utc(14, 30)) is None

    later = current_window(windows, utc(16))
    assert later is not None and later.start == utc(15)
    assert later.time_to_reset(utc(16)) == timedelta(hours=4)

    # 만료된 블록의 남은 시간은 음수가 아니라 0
    assert windows[0].time_to_reset(utc(23)) == timedelta(0)


def test_burn_rate_counts_only_the_last_hour():
    entries = overlapping()

    # 12:30~13:30 두 건: (1+40+100+1000) + (1+30+100+1000) = 2272
    assert burn_rate(entries, utc(13, 30)) == 2272 / 60

    # 조용한 구간
    assert burn_rate(entries, utc(23)) == 0.0

    # span을 넓히면 잡히는 토큰은 늘지만 분당 비율은 오히려 낮아진다.
    # 09:00~13:30의 4건 = 4504 토큰을 300분에 펴 바르기 때문. 합계가 아니라 비율이다.
    assert burn_rate(entries, utc(13, 30), timedelta(hours=5)) == 4504 / 300
    assert burn_rate(entries, utc(13, 30), timedelta(hours=5)) < burn_rate(
        entries, utc(13, 30)
    )


def test_snapshot_gives_the_three_numbers():
    snap = snapshot(overlapping(), now=utc(13))

    assert snap.total_tokens == 4504
    assert snap.time_to_reset == timedelta(hours=1)
    assert snap.tokens_per_minute > 0

    idle = snapshot(overlapping(), now=utc(14, 30))
    assert idle.window is None
    assert idle.total_tokens == 0
    assert idle.time_to_reset is None


def test_collect_entries_dedups_across_files():
    """같은 파일을 두 번 줘도 합계가 두 배가 되면 안 된다 (세션 재개 시나리오)."""
    f = FIXTURES / "overlapping.jsonl"

    once = collect_entries([f])
    twice = collect_entries([f, f])

    assert len(once) == 6
    assert len(twice) == 6
    assert sum(e.output_tokens for e in twice) == 210


def test_entries_are_sorted_by_time():
    entries = collect_entries([FIXTURES / "overlapping.jsonl"])
    assert [e.timestamp for e in entries] == sorted(e.timestamp for e in entries)


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
