"""데스크톱 앱의 플랜 사용량 기록 읽기.

pytest 없이도 돌아간다:  py -3.12 tests/test_plan_usage.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccpet import plan_usage  # noqa: E402


def utc(h: int, m: int = 0) -> datetime:
    return datetime(2026, 9, 4, h, m, tzinfo=timezone.utc)


def write(rows: list[tuple[datetime, int | None, int | None]]) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "plan-usage-history.json"
    tmp.write_text(json.dumps({
        "version": 2,
        "samples": [
            {"t": int(at.timestamp() * 1000), "org": "o",
             "u": {k: v for k, v in (("fh", fh), ("sd", sd)) if v is not None}}
            for at, fh, sd in rows
        ],
    }), encoding="utf-8")
    plan_usage.history_path = lambda: tmp
    return tmp


def test_latest_sample_wins():
    write([(utc(17, 29), 44, 20), (utc(17, 44), 61, 22), (utc(17, 59), 79, 23)])

    s = plan_usage.latest()

    assert s is not None
    assert s.at == utc(17, 59)
    assert s.five_hour == 79
    assert s.seven_day == 23


def test_reset_shows_up_as_a_drop():
    """사용률은 쓸수록 오르기만 한다. 내려간 건 창이 리셋된 것뿐이다."""
    write([
        (utc(13, 59), 99, 16),
        (utc(14, 29), 99, 16),
        (utc(14, 44), 0, 16),     # ← 여기서 리셋
        (utc(15, 29), 6, 16),
        (utc(17, 59), 79, 23),
    ])

    boundary = plan_usage.last_reset_before(plan_usage.samples(), utc(18, 0))

    # 리셋은 두 샘플 사이 어딘가다. 이른 쪽을 돌려준다 —
    # 그 뒤의 첫 요청이 지금 창을 열었기 때문이다.
    assert boundary == utc(14, 29)


def test_small_dips_are_not_resets():
    """표본 잡음으로 1~2%p 흔들리는 건 리셋이 아니다."""
    write([(utc(16, 0), 40, 10), (utc(16, 15), 38, 10), (utc(16, 30), 45, 11)])

    assert plan_usage.last_reset_before(plan_usage.samples(), utc(17, 0)) is None


def test_calibration_extends_a_stale_sample():
    """샘플은 최대 15분 뒤처진다. 그 사이 쌓인 양을 같은 눈금으로 더한다."""
    write([(utc(17, 59), 79, 23)])
    sample = plan_usage.latest()
    assert sample is not None

    # 샘플 시점 조업량 236,571 이 79% → 한도 약 299,457
    pct = plan_usage.calibrated_percentage(sample, 236_571, 236_571)
    assert pct is not None and abs(pct - 79) < 0.5, "그 시점에는 샘플 값 그대로"

    later = plan_usage.calibrated_percentage(sample, 236_571, 255_348)
    assert later is not None
    assert 84 < later < 86, later
    assert later > pct, "그 뒤에 쓴 만큼 올라가야 한다"


def test_calibration_refuses_when_the_reading_is_too_small():
    """사용률이 낮을 때 나눗셈하면 작은 오차가 크게 튄다. 그냥 포기한다."""
    write([(utc(15, 29), 2, 16)])
    sample = plan_usage.latest()
    assert sample is not None

    assert plan_usage.calibrated_percentage(sample, 5_000, 9_000) is None


def test_missing_file_is_not_an_error():
    plan_usage.history_path = lambda: None

    assert plan_usage.samples() == []
    assert plan_usage.latest() is None


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
