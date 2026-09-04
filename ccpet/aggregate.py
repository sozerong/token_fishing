"""5시간 윈도우 집계와 burn rate. UsageEntry만 알고 JSONL은 모른다.

겹치는 세션 처리 — 이 프로젝트의 유일한 알고리즘 판단:

    한도는 **계정 단위**로 걸린다. 세션 파일이 여러 개인 건 트랜스크립트 레이아웃의
    사정이지 청구의 사정이 아니다. 따라서 sessionId별로 윈도우를 따로 세지 않고,
    모든 파일의 엔트리를 하나의 시간축에 합친 뒤 그 위에서 5시간 블록을 자른다.
    동시에 돌던 두 세션은 자동으로 같은 블록에 들어간다.

    반례가 나오면(예: 레퍼런스가 세션별로 센다면) 4단계 compare에서 항목별 비율로
    드러난다. 그때 이 결정만 갈아끼우면 된다.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .parser import UsageEntry, parse_file
from .paths import session_files

WINDOW = timedelta(hours=5)
BURN_SPAN = timedelta(hours=1)

FLOOR_TO_HOUR = False
"""블록 시작을 정시로 내림할 것인가. **공식 UI와 대조해 False로 확정.**

한때 True였다. claude-monitor가 첫 요청 13:36에 대해 session_start=13:00을 내놓길래
따라갔었다. 그런데 Claude 설정의 사용량 화면(공식)과 맞춰보니 실제 세션 시작은
**15:17**이었다 — 정시가 아니다. 레퍼런스를 근거로 삼은 게 오답이었다.

교훈: claude-monitor는 대조군이지 정답지가 아니다. 저쪽도 JSONL만 보고 추측한다.
둘이 일치한다고 맞는 게 아니다. 진짜 정답은 공식 UI뿐이다."""


@dataclass(frozen=True, slots=True)
class Window:
    """5시간 블록 하나. start는 이 블록 첫 요청 시각."""

    start: datetime
    entries: int
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int

    @property
    def end(self) -> datetime:
        return self.start + WINDOW

    @property
    def total_tokens(self) -> int:
        """네 항목의 합. cache_read가 실측에서 나머지를 압도한다(약 200배).
        게임 층에서 다르게 세고 싶으면 항목을 직접 골라 써라."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )

    def is_active(self, now: datetime) -> bool:
        return self.start <= now < self.end

    def time_to_reset(self, now: datetime) -> timedelta:
        return max(self.end - now, timedelta(0))


def collect_entries(files: Iterable[Path] | None = None) -> list[UsageEntry]:
    """모든 세션 파일을 읽어 시간순 UsageEntry 목록으로.

    requestId로 전역 dedup한다. 실측 데이터에는 파일 간 중복이 없었지만,
    세션을 재개/포크하면 이전 기록이 새 파일로 복사될 수 있다. 그러면 합계가
    조용히 2배가 된다 — 2줄로 막을 수 있는 실패 모드라 막아둔다.
    """
    seen: dict[str, UsageEntry] = {}
    for f in session_files() if files is None else files:
        for e in parse_file(f).entries:
            seen.setdefault(e.request_id, e)
    return sorted(seen.values(), key=lambda e: e.timestamp)


RESET_ENV = "TOKENFISHING_RESET_AT"


def pinned_reset(now: datetime) -> datetime | None:
    """공식 UI에서 읽은 리셋 시각. 없으면 None.

    JSONL만으로는 윈도우 경계를 알 수 없는 경우가 있다 — claude.ai 웹이나 모바일에서
    쓴 사용량도 같은 5시간 한도를 먹지만 여기엔 흔적이 안 남는다. 그런 사용이 창을
    열었으면 우리가 보는 첫 요청은 창의 시작이 아니다. 실측된 사례다:
    공식 세션 시작 15:17, 그날 Claude Code 첫 요청은 13:36.

    그래서 사용자가 진짜 값을 꽂을 수 있게 한다. Claude 설정 > 사용량에 뜨는
    "N시간 M분 후 재설정"을 시계 시각으로 바꿔 넣으면 된다:

        TOKENFISHING_RESET_AT=05:17                      로컬 시각, 다음 도래분
        TOKENFISHING_RESET_AT=2026-09-04T20:17:00+00:00  ISO 순간

    ponytail: 설정 파일 대신 환경변수 하나. 값이 하나뿐이고 수명도 짧다.
    """
    raw = os.environ.get(RESET_ENV, "").strip()
    if not raw:
        return None

    try:
        if ":" in raw and len(raw) <= 5:  # "HH:MM"
            hh, mm = (int(p) for p in raw.split(":"))
            local = now.astimezone()
            reset = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if reset <= local:  # 이미 지났으면 내일 그 시각
                reset += timedelta(days=1)
            return reset.astimezone(timezone.utc)
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def anchored_window(entries: Iterable[UsageEntry], reset_at: datetime) -> Window:
    """리셋 시각이 확실할 때, 그 창 [reset-5h, reset)만으로 집계한다.

    블록을 이어붙이지 않으므로 보이지 않는 사용량 때문에 경계가 밀리는 문제가 없다.
    """
    start = reset_at - WINDOW
    rows = [e for e in entries if start <= e.timestamp < reset_at]
    return Window(
        start,
        len(rows),
        sum(e.input_tokens for e in rows),
        sum(e.output_tokens for e in rows),
        sum(e.cache_creation_tokens for e in rows),
        sum(e.cache_read_tokens for e in rows),
    )


def _block_start(ts: datetime) -> datetime:
    if not FLOOR_TO_HOUR:
        return ts
    return ts.replace(minute=0, second=0, microsecond=0)


def build_windows(entries: Iterable[UsageEntry]) -> list[Window]:
    """시간순 엔트리를 5시간 블록으로 자른다.

    블록은 첫 요청에서 시작해 정확히 5시간 지속한다. 그 안에 안 들어가는 첫 엔트리가
    다음 블록을 연다. 유휴 시간에 대한 별도 규칙은 두지 않는다 — 5시간이 지나면
    어차피 다음 엔트리가 새 블록을 열기 때문에 규칙을 더 만들 이유가 없다.

    블록 시작은 FLOOR_TO_HOUR에 따라 정시로 내림한다(레퍼런스와 맞춤).
    """
    windows: list[Window] = []
    start: datetime | None = None
    n = i = o = cw = cr = 0

    def flush() -> None:
        nonlocal start, n, i, o, cw, cr
        if start is not None:
            windows.append(Window(start, n, i, o, cw, cr))
        start, n, i, o, cw, cr = None, 0, 0, 0, 0, 0

    for e in sorted(entries, key=lambda x: x.timestamp):
        if start is None or e.timestamp >= start + WINDOW:
            flush()
            start = _block_start(e.timestamp)
        n += 1
        i += e.input_tokens
        o += e.output_tokens
        cw += e.cache_creation_tokens
        cr += e.cache_read_tokens
    flush()
    return windows


def current_window(windows: Iterable[Window], now: datetime) -> Window | None:
    """지금 활성인 블록. 마지막 블록이 이미 만료됐으면 None (리셋된 상태)."""
    for w in windows:
        if w.is_active(now):
            return w
    return None


def burn_rate(
    entries: Iterable[UsageEntry], now: datetime, span: timedelta = BURN_SPAN
) -> float:
    """최근 span(기본 1시간) 동안의 분당 토큰. 활성 세션 전부에서 모은다."""
    since = now - span
    total = sum(
        e.input_tokens + e.output_tokens + e.cache_creation_tokens + e.cache_read_tokens
        for e in entries
        if since <= e.timestamp <= now
    )
    return total / (span.total_seconds() / 60)


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Phase 1이 내놓아야 하는 숫자 세 개."""

    window: Window | None
    tokens_per_minute: float
    now: datetime
    pinned: bool = False
    """리셋 시각이 공식 UI에서 온 값인가. False면 JSONL로 추정한 값이라 틀릴 수 있다."""

    @property
    def total_tokens(self) -> int:
        return self.window.total_tokens if self.window else 0

    @property
    def time_to_reset(self) -> timedelta | None:
        return self.window.time_to_reset(self.now) if self.window else None


def snapshot(entries: Iterable[UsageEntry], now: datetime | None = None) -> Snapshot:
    now = now or datetime.now(timezone.utc)
    entries = list(entries)

    reset = pinned_reset(now)
    if reset is not None and now < reset:
        return Snapshot(
            window=anchored_window(entries, reset),
            tokens_per_minute=burn_rate(entries, now),
            now=now,
            pinned=True,
        )

    return Snapshot(
        window=current_window(build_windows(entries), now),
        tokens_per_minute=burn_rate(entries, now),
        now=now,
    )


def _main() -> None:
    import sys
    from collections import Counter

    # Windows 콘솔이 cp949라 한글/기호에서 죽는다. 숫자를 못 보면 의미가 없다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    entries = collect_entries()
    snap = snapshot(entries)
    prov = Counter(e.provenance for e in entries)

    print(f"요청 {len(entries)}개, 윈도우 {len(build_windows(entries))}개")
    print()
    if snap.window is None:
        print("활성 윈도우 없음 (마지막 블록이 이미 리셋됨)")
    else:
        w = snap.window
        print(f"현재 윈도우  {w.start:%Y-%m-%d %H:%M} ~ {w.end:%H:%M} UTC, 요청 {w.entries}개")
        print(f"  input     {w.input_tokens:>14,}")
        print(f"  output    {w.output_tokens:>14,}")
        print(f"  cache_w   {w.cache_creation_tokens:>14,}")
        print(f"  cache_r   {w.cache_read_tokens:>14,}")
        print(f"  합계      {w.total_tokens:>14,}")
        rest = snap.time_to_reset
        assert rest is not None
        print(f"리셋까지     {int(rest.total_seconds() // 3600)}시간 "
              f"{int(rest.total_seconds() % 3600 // 60)}분")
    print(f"burn rate    {snap.tokens_per_minute:,.0f} 토큰/분 (최근 1시간)")
    print()
    print(f"provenance   {dict(prov)}")


if __name__ == "__main__":
    _main()
