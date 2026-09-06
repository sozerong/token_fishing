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

from tokenfishing import plan_usage  # noqa: E402

REAL_CANDIDATES = plan_usage.candidate_paths

# 테스트는 후보 목록만 갈아끼운다. history_path() 자체(존재 확인 + 최신 선택)는
# 진짜를 그대로 돌려야 그 로직도 같이 검증된다.


def utc(h: int, m: int = 0, day: int = 4) -> datetime:
    return datetime(2026, 9, day, h, m, tzinfo=timezone.utc)


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
    plan_usage.candidate_paths = lambda: [tmp]
    return tmp


def test_latest_sample_wins():
    write([(utc(17, 29), 44, 20), (utc(17, 44), 61, 22), (utc(17, 59), 79, 23)])

    s = plan_usage.latest()

    assert s is not None
    assert s.at == utc(17, 59)
    assert s.five_hour == 79
    assert s.seven_day == 23


def test_empty_window_beats_the_drop_as_a_floor():
    """fh == 0 은 "그 시각에 창이 비어 있었다"는 사실이라 급락보다 좁은 하한이다."""
    write([
        (utc(13, 59), 99, 16),
        (utc(14, 29), 99, 16),
        (utc(14, 44), 0, 16),     # ← 여기서 리셋됐고, 아직 비어 있다
        (utc(15, 29), 6, 16),
        (utc(17, 59), 79, 23),
    ])

    # 급락만 보면 14:29(직전 샘플)지만, 14:44에 창이 비어 있었다는 게 더 좁다.
    assert plan_usage.window_floor(plan_usage.samples(), utc(18, 0)) == utc(14, 44)


def test_a_long_sampling_gap_does_not_drag_the_floor_backwards():
    """앱이 꺼져 있으면 급락 구간이 몇 시간이 된다. 그때 이른 쪽을 쓰면 무너진다.

    실측 사례: 18:59 fh=100 → (7시간 32분 공백) → 02:31 fh=0.
    급락 하한 18:59 를 쓰면 이전 창의 요청까지 끌어와 이미 만료된 창이 나왔다.
    """
    write([(utc(18, 59), 100, 25), (utc(2, 31, day=3), 0, 25)])

    floor = plan_usage.window_floor(plan_usage.samples(), utc(2, 34, day=3))

    assert floor == utc(2, 31, day=3)


def test_small_dips_are_not_resets():
    """표본 잡음으로 1~2%p 흔들리는 건 리셋이 아니다. fh=0 도 없으면 하한이 없다."""
    write([(utc(16, 0), 40, 10), (utc(16, 15), 38, 10), (utc(16, 30), 45, 11)])

    assert plan_usage.window_floor(plan_usage.samples(), utc(17, 0)) is None


def test_clean_pct_drops_a_leaked_epoch():
    """used_percentage 자리에 resets_at epoch이 새는 버그(#52326)."""
    assert plan_usage.clean_pct(63) == 63.0
    assert plan_usage.clean_pct(100.4) == 100.0, "반올림 오차는 깎아서 살린다"
    assert plan_usage.clean_pct(1_788_600_000) is None, "epoch 은 사용률이 아니다"
    assert plan_usage.clean_pct(-1) is None
    assert plan_usage.clean_pct(True) is None
    assert plan_usage.clean_pct("63") is None
    assert plan_usage.clean_pct(None) is None


def test_the_sample_is_shown_untouched():
    """앱 샘플에 손대지 않는다. 뒤처짐을 조업량으로 메우려던 보정은 삭제됐다.

    이 저장소 기록으로 뒤돌아 검증한 결과 28승 49무 11패였고, 11패 중 7건이
    10%p 넘게 더 틀렸으며 전부 100% 포화 방향이었다. 중앙값 1.7%p를 벌자고
    "한도 다 썼다"는 거짓말을 살 수는 없다.
    """
    assert not hasattr(plan_usage, "calibrated_percentage")
    assert not hasattr(plan_usage, "MIN_PCT_TO_CALIBRATE")

    write([(utc(17, 59), 79, 23)])
    s = plan_usage.latest()
    assert s is not None and s.five_hour == 79


def test_packaged_app_redirect_is_found_from_outside_the_container(monkeypatch=None):
    """MSIX 리다이렉트 경로를 찾는다. 이게 "어림"의 진짜 원인이었다.

    윈도우 Claude 데스크톱 앱은 스토어 패키지라 %APPDATA% 쓰기가 컨테이너로
    리다이렉트된다. 앱 **안**에서 실행하면 논리 경로가 알아서 풀리지만, 일반
    PowerShell에서 팝업을 띄우면 %APPDATA%/Claude 는 존재조차 하지 않는다.
    파일을 통째로 못 찾아 화면 전체가 어림으로 떨어졌다.
    """
    import os

    if sys.platform != "win32":
        return  # 리다이렉트는 윈도우에만 있다

    root = Path(tempfile.mkdtemp())
    roaming = root / "Roaming"                       # 컨테이너 밖: Claude 폴더 없음
    local = root / "Local"
    pkg = local / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
    pkg.mkdir(parents=True)
    (pkg / "plan-usage-history.json").write_text(
        json.dumps({"version": 2, "samples": [
            {"t": int(utc(17, 59).timestamp() * 1000), "u": {"fh": 79, "sd": 23}}
        ]}), encoding="utf-8")

    before = (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA"))
    os.environ["APPDATA"], os.environ["LOCALAPPDATA"] = str(roaming), str(local)
    plan_usage.candidate_paths = REAL_CANDIDATES
    try:
        found = plan_usage.history_path()
        assert found is not None, "리다이렉트 경로를 못 찾았다 — 화면이 어림으로 떨어진다"
        assert "Packages" in str(found)

        rows = plan_usage.samples()
        assert len(rows) == 1 and rows[0].five_hour == 79
    finally:
        for key, value in zip(("APPDATA", "LOCALAPPDATA"), before):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_the_newest_candidate_wins(monkeypatch=None):
    """후보가 둘이면 최근에 쓰인 쪽. 예전 설치가 남긴 파일을 조용히 쓰면 안 된다."""
    import os
    import time

    if sys.platform != "win32":
        return

    root = Path(tempfile.mkdtemp())
    roaming = root / "Roaming" / "Claude"
    local = root / "Local"
    pkg = local / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
    for d in (roaming, pkg):
        d.mkdir(parents=True)

    def dump(path: Path, fh: int) -> None:
        path.write_text(json.dumps({"version": 2, "samples": [
            {"t": int(utc(17, 59).timestamp() * 1000), "u": {"fh": fh, "sd": 1}}
        ]}), encoding="utf-8")

    dump(roaming / "plan-usage-history.json", 11)      # 낡은 설치의 잔재
    time.sleep(0.02)
    dump(pkg / "plan-usage-history.json", 99)          # 지금 앱이 쓰는 것

    before = (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA"))
    os.environ["APPDATA"] = str(root / "Roaming")
    os.environ["LOCALAPPDATA"] = str(local)
    plan_usage.candidate_paths = REAL_CANDIDATES
    try:
        rows = plan_usage.samples()
        assert rows[0].five_hour == 99, "낡은 파일을 집었다"
    finally:
        for key, value in zip(("APPDATA", "LOCALAPPDATA"), before):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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
