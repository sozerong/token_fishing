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


def test_block_start_is_floored_to_the_hour():
    """13:36에 시작한 블록은 13:00~18:00이 된다 (레퍼런스 claude-monitor와 일치).

    overlapping.jsonl은 전부 정시/30분이라 이 동작을 못 잡는다. 그래서 엔트리를
    직접 만든다 — 파서를 거칠 이유가 없는 집계 층의 문제다.
    """
    entries = [
        UsageEntry(
            request_id="req_a", session_id="s", timestamp=utc(13, 36),
            model="claude-opus-5", input_tokens=1, output_tokens=10,
            cache_creation_tokens=0, cache_read_tokens=0,
            is_sidechain=False, provenance="stable",
        ),
        # 18:00에 블록이 닫히므로 18:10은 새 블록을 연다. 내림이 없으면 같은 블록이다.
        UsageEntry(
            request_id="req_b", session_id="s", timestamp=utc(18, 10),
            model="claude-opus-5", input_tokens=1, output_tokens=20,
            cache_creation_tokens=0, cache_read_tokens=0,
            is_sidechain=False, provenance="stable",
        ),
    ]

    windows = build_windows(entries)

    assert len(windows) == 2
    assert windows[0].start == utc(13)
    assert windows[0].end == utc(18)
    assert windows[0].output_tokens == 10
    assert windows[1].start == utc(18)
    assert windows[1].output_tokens == 20


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
