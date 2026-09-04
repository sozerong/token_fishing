"""Claude 데스크톱 앱이 남기는 플랜 사용량 기록을 읽는다.

    %APPDATA%/Claude/plan-usage-history.json        (Windows)
    ~/Library/Application Support/Claude/...        (macOS)
    ~/.config/Claude/...                            (Linux)

앱이 15분마다 한 줄씩 쌓는다:

    {"t": 1788552000000, "org": "...", "u": {"fh": 79, "sd": 23}}

    fh  5시간 창 사용률 (%)
    sd  주간 사용률 (%)

이건 계정 기준 공식 수치다. 웹·모바일 사용까지 들어 있고, 상태줄 훅을 설치하거나
Claude Code를 재시작할 필요가 없다. 앱이 켜져 있으면 그냥 쌓인다.

두 가지를 뽑아 쓴다:

1. 최신 사용률 — 화면에 그대로 띄운다
2. 리셋 경계   — fh가 급락한 지점이 이전 창이 끝난 순간이다.
                 그 뒤 첫 요청이 지금 창의 시작이고, 거기에 5시간을 더하면 리셋이다
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

RESET_DROP = 20
"""fh가 이만큼(%p) 떨어지면 창이 리셋된 것으로 본다.

사용률은 쓸수록 오르기만 한다. 내려간 건 리셋뿐이다. 실측에서는 99 → 0으로
떨어졌다. 20%p는 표본 잡음과 진짜 리셋을 가르기에 넉넉한 문턱이다."""

MIN_PCT_TO_CALIBRATE = 5.0
"""이 사용률 아래에서는 한도를 역산하지 않는다. 나눗셈 오차가 너무 커진다."""


def history_path() -> Path | None:
    """앱이 기록을 남기는 위치. 없으면 None."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / "Claude" / "plan-usage-history.json"
    return path if path.exists() else None


@dataclass(frozen=True, slots=True)
class Sample:
    at: datetime
    five_hour: float | None
    seven_day: float | None


_cache: list[Sample] = []
"""마지막으로 성공한 읽기.

앱이 이 파일을 주기적으로 다시 쓴다. 그 순간에 읽으면 반쯤 쓰인 JSON을 만나
빈 목록이 나오고, 그러면 리셋 경계를 못 찾아 화면이 통째로 엉뚱한 추정값으로
떨어진다. 실제로 그 순간이 스크린샷에 잡혔다. 직전 값을 들고 있으면 끝난다."""


def samples() -> list[Sample]:
    """시간순 샘플. 읽기에 실패하면 마지막으로 성공한 값을 그대로 쓴다."""
    global _cache

    path = history_path()
    if path is None:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _cache

    rows = []
    for raw in data.get("samples") or []:
        try:
            at = datetime.fromtimestamp(raw["t"] / 1000, timezone.utc)
        except (KeyError, TypeError, ValueError, OSError):
            continue
        u = raw.get("u") or {}
        rows.append(Sample(at, u.get("fh"), u.get("sd")))
    rows.sort(key=lambda s: s.at)
    if not rows:
        return _cache
    _cache = rows
    return rows


def latest(rows: list[Sample] | None = None) -> Sample | None:
    rows = samples() if rows is None else rows
    for s in reversed(rows):
        if s.five_hour is not None:
            return s
    return None


def last_reset_before(rows: list[Sample], now: datetime) -> datetime | None:
    """마지막으로 창이 리셋된 시점의 하한.

    fh가 급락한 두 샘플 사이 어딘가에서 리셋됐다. 이른 쪽 시각을 돌려준다 —
    그 시점 이후의 첫 요청이 지금 창을 열었기 때문이다.
    """
    previous: Sample | None = None
    boundary: datetime | None = None
    for s in rows:
        if s.at > now or s.five_hour is None:
            continue
        if previous is not None and s.five_hour < previous.five_hour - RESET_DROP:
            boundary = previous.at
        previous = s
    return boundary


def calibrated_percentage(
    sample: Sample, catch_at_sample: int, catch_now: int
) -> float | None:
    """샘플 시점의 공식 사용률을 기준으로 지금 사용률을 환산한다.

    샘플은 최대 15분 뒤처진다. 그 사이에도 토큰은 쌓이므로 그냥 쓰면 낮게 나온다.
    샘플 시점의 (우리 조업량 ÷ 공식 사용률)로 이 계정의 한도를 재고, 그 뒤에 쌓인
    양을 같은 눈금으로 더한다.

    한도를 추측하는 게 아니라 **공식 수치로 눈금을 맞추는 것**이다. 기준점이
    공식이라 P90 추정과는 성격이 다르다.
    """
    pct = sample.five_hour
    if pct is None or pct < MIN_PCT_TO_CALIBRATE or catch_at_sample <= 0:
        return None
    limit = catch_at_sample / (pct / 100)
    if limit <= 0:
        return None
    return max(0.0, min(100.0, catch_now / limit * 100))
