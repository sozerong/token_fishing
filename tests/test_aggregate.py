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
    model_breakdown,
    snapshot,
    totals_of,
    weekly_end,
    weekly_start,
    weekly_totals,
)
from ccpet import statusline  # noqa: E402
from ccpet.parser import UsageEntry, parse_file  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

# 테스트는 이 기계의 상태에 의존하면 안 된다. 상태줄 훅이 남긴 실제 공식 수치
# 파일이 있으면 snapshot()이 그걸 우선하므로, 없는 경로로 돌려놓는다.
statusline.STATE_PATH = Path(__file__).parent / "_no_such_limits.json"


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


def test_model_breakdown_groups_and_sorts():
    """모델별 집계에는 추측이 없다. 이미 파싱한 model 필드를 묶기만 한다."""
    entries = [
        entry("a", utc(9), out=100, inp=1),
        entry("b", utc(10), out=50, inp=1),
        entry("c", utc(11), out=10, inp=1),
    ]
    from dataclasses import replace

    entries = [
        replace(e, model=m) for e, m in zip(entries, ["opus", "sonnet", "opus"])
    ]

    rows = model_breakdown(entries)

    assert [m for m, _ in rows] == ["opus", "sonnet"], "조업량 많은 순"
    opus = dict(rows)["opus"]
    assert opus.requests == 2
    assert opus.catch == 112          # (1+100) + (1+10)
    assert dict(rows)["sonnet"].catch == 51


def test_weekly_starts_on_the_configured_weekday():
    """공식 화면이 "(화) 오전 12:00에 재설정"이라 기본값이 화요일이다."""
    import os

    # 2026-09-04는 금요일. 직전 화요일은 2026-09-01.
    friday = datetime(2026, 9, 4, 17, 0, tzinfo=timezone.utc).astimezone()
    start = weekly_start(friday)

    assert start.astimezone().weekday() == 1, "화요일"
    assert start.astimezone().hour == 0
    assert weekly_end(friday) - start == timedelta(days=7)

    os.environ["TOKENFISHING_WEEKLY_RESET_DAY"] = "0"  # 월요일
    try:
        assert weekly_start(friday).astimezone().weekday() == 0
    finally:
        del os.environ["TOKENFISHING_WEEKLY_RESET_DAY"]


def test_weekly_totals_excludes_older_entries():
    now = datetime(2026, 9, 4, 17, 0, tzinfo=timezone.utc)
    start = weekly_start(now)

    entries = [
        entry("old", start - timedelta(days=1), out=999),   # 지난 주
        entry("new1", start + timedelta(hours=1), out=10),
        entry("new2", now - timedelta(minutes=5), out=20),
    ]

    wk = weekly_totals(entries, now)

    assert wk.requests == 2
    assert wk.catch == 32           # (1+10) + (1+20)
    assert 999 not in (wk.output_tokens,)


def test_totals_of_separates_catch_from_cache():
    t = totals_of([
        UsageEntry("a", "s", utc(9), "opus", 10, 20, 300, 4000, False, "stable"),
    ])
    assert t.catch == 30
    assert t.total_tokens == 4330


def test_official_limits_beat_every_guess():
    """상태줄 훅이 받아둔 공식 수치가 있으면 추정도 수동 고정도 무시한다.

    공식 값은 웹·모바일 사용까지 반영돼 있어서, JSONL만 보는 추정보다 항상 낫다.
    """
    import json
    import os
    import tempfile

    now = utc(17, 0)
    reset = utc(20, 11)
    entries = [
        entry("old", utc(13, 36), 999),    # 공식 창 밖 — 이전 창 것
        entry("cur", utc(15, 30), 10),
        entry("cur2", utc(16, 30), 20),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "limits.json"
        path.write_text(json.dumps({
            "captured_at": utc(16, 45).isoformat(),   # 마지막 요청보다 뒤 → 아직 유효
            "rate_limits": {
                "five_hour": {"used_percentage": 51, "resets_at": reset.timestamp()},
                "seven_day": {"used_percentage": 20, "resets_at": reset.timestamp()},
            }
        }), encoding="utf-8")

        original = statusline.STATE_PATH
        statusline.STATE_PATH = path
        # 수동 고정도 걸어둔다 — 공식 수치가 이겨야 한다
        os.environ["TOKENFISHING_RESET_AT"] = utc(23, 0).isoformat()
        try:
            snap = snapshot(entries, now=now)
        finally:
            statusline.STATE_PATH = original
            del os.environ["TOKENFISHING_RESET_AT"]

    assert snap.pinned is True
    assert snap.used_percentage == 51
    assert snap.weekly_percentage == 20
    assert snap.window is not None
    assert snap.window.start == utc(15, 11)
    assert snap.window.end == reset
    assert snap.window.entries == 2, "공식 창 밖의 요청은 빠진다"
    assert snap.window.output_tokens == 30
    assert snap.time_to_reset == timedelta(hours=3, minutes=11)


def test_official_percentage_is_used_even_after_more_requests():
    """캡처 이후 요청이 있어도 공식 사용률을 버리지 않는다.

    한때 "그 뒤에 요청이 있으면 낡은 값"이라며 버렸는데, 상태줄 훅은 대화가 오갈
    때마다 다시 실행되므로 읽는 시점에는 거의 항상 그 뒤에 요청이 하나쯤 있다.
    결과적으로 공식 값이 매번 버려지고 훨씬 부정확한 근사로 떨어졌다 —
    실측에서 공식 75%인데 화면은 ~59%를 보여줬다.

    토큰은 Claude Code가 돌 때만 쓰이고 훅도 그때 돈다. 몇 초 뒤처진 공식 수치가
    한참 빗나간 추정보다 언제나 낫다.
    """
    import json
    import tempfile

    reset = utc(20, 11)
    entries = [entry("before", utc(15, 30), 10), entry("after", utc(16, 30), 20)]

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "limits.json"
        path.write_text(json.dumps({
            "captured_at": utc(16, 0).isoformat(),      # 16:30 요청보다 앞선다
            "rate_limits": {
                "five_hour": {"used_percentage": 75, "resets_at": reset.timestamp()},
                "seven_day": {"used_percentage": 23, "resets_at": reset.timestamp()},
            },
        }), encoding="utf-8")
        original = statusline.STATE_PATH
        statusline.STATE_PATH = path
        try:
            snap = snapshot(entries, now=utc(17, 0))
        finally:
            statusline.STATE_PATH = original

    assert snap.used_percentage == 75
    assert snap.weekly_percentage == 23


def test_expired_official_limits_are_ignored():
    """리셋 시각이 지난 공식 값은 버린다. 오래된 창을 붙들고 있으면 안 된다."""
    import json
    import tempfile

    now = utc(17, 0)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "limits.json"
        path.write_text(json.dumps({
            "rate_limits": {
                "five_hour": {"used_percentage": 99,
                              "resets_at": utc(16, 0).timestamp()},
            }
        }), encoding="utf-8")
        original = statusline.STATE_PATH
        statusline.STATE_PATH = path
        try:
            snap = snapshot([entry("a", utc(16, 30), 10)], now=now)
        finally:
            statusline.STATE_PATH = original

    assert snap.pinned is False
    assert snap.used_percentage is None


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
