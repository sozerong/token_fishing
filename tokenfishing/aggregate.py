"""5시간 윈도우 집계와 burn rate. UsageEntry만 알고 JSONL은 모른다.

겹치는 세션 처리 — 이 프로젝트의 유일한 알고리즘 판단:

    한도는 **계정 단위**로 걸린다. 세션 파일이 여러 개인 건 트랜스크립트 레이아웃의
    사정이지 청구의 사정이 아니다. 따라서 sessionId별로 윈도우를 따로 세지 않고,
    모든 파일의 엔트리를 하나의 시간축에 합친 뒤 그 위에서 5시간 블록을 자른다.
    동시에 돌던 두 세션은 자동으로 같은 블록에 들어간다.

    반례가 나오면(예: 세션별로 세야 한다면) 항목별 비율로
    드러난다. 그때 이 결정만 갈아끼우면 된다.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import plan_usage, statusline
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
    def catch(self) -> int:
        """5시간 한도가 실제로 세는 값. Totals.catch와 같은 정의."""
        return self.input_tokens + self.output_tokens

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


@dataclass(frozen=True, slots=True)
class Totals:
    """임의의 엔트리 묶음의 합. 창 개념이 없는 집계(주간·모델별·전체)에 쓴다."""

    requests: int
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int

    @property
    def catch(self) -> int:
        """5시간 한도가 실제로 세는 값."""
        return self.input_tokens + self.output_tokens

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens + self.output_tokens
            + self.cache_creation_tokens + self.cache_read_tokens
        )


def totals_of(entries: Iterable[UsageEntry]) -> Totals:
    rows = list(entries)
    return Totals(
        len(rows),
        sum(e.input_tokens for e in rows),
        sum(e.output_tokens for e in rows),
        sum(e.cache_creation_tokens for e in rows),
        sum(e.cache_read_tokens for e in rows),
    )


def _window(start: datetime, rows: list[UsageEntry]) -> Window:
    """엔트리 묶음 하나를 창으로. 합산은 totals_of 한 곳에만 둔다."""
    t = totals_of(rows)
    return Window(
        start, t.requests, t.input_tokens, t.output_tokens,
        t.cache_creation_tokens, t.cache_read_tokens,
    )


def model_breakdown(entries: Iterable[UsageEntry]) -> list[tuple[str, Totals]]:
    """모델별 사용량. 조업량 많은 순.

    추측이 하나도 안 들어간다 — 이미 파싱해 둔 model 필드를 묶기만 한다.
    """
    buckets: dict[str, list[UsageEntry]] = {}
    for e in entries:
        buckets.setdefault(e.model, []).append(e)
    pairs = [(m, totals_of(rows)) for m, rows in buckets.items()]
    return sorted(pairs, key=lambda p: p[1].catch, reverse=True)


WEEKLY_RESET_ENV = "TOKENFISHING_WEEKLY_RESET_DAY"
DEFAULT_WEEKLY_RESET_DAY = 1
"""주간 한도가 리셋되는 요일 (월=0 … 일=6). 기본 화요일.

공식 사용량 화면의 "(화) 오전 12:00에 재설정"에서 가져왔다. 계정마다 다를 수 있어서
TOKENFISHING_WEEKLY_RESET_DAY로 바꿀 수 있다. 시각은 로컬 자정."""


def weekly_reset_day() -> int:
    raw = os.environ.get(WEEKLY_RESET_ENV, "").strip()
    if raw.isdigit() and 0 <= int(raw) <= 6:
        return int(raw)
    return DEFAULT_WEEKLY_RESET_DAY


def weekly_start(now: datetime) -> datetime:
    """직전 주간 리셋 시각 (로컬 자정)."""
    local = now.astimezone()
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    days_since = (midnight.weekday() - weekly_reset_day()) % 7
    return (midnight - timedelta(days=days_since)).astimezone(timezone.utc)


def weekly_end(now: datetime) -> datetime:
    return weekly_start(now) + timedelta(days=7)


def weekly_totals(entries: Iterable[UsageEntry], now: datetime) -> Totals:
    start = weekly_start(now)
    return totals_of(e for e in entries if start <= e.timestamp <= now)


RESET_ENV = "TOKENFISHING_RESET_AT"


def app_reset_floor(entries: list[UsageEntry], now: datetime) -> datetime | None:
    """앱 기록으로 추정한 리셋 시각. 확실치 않으면 None.

    앱은 사용률만 15분마다 남기고 창 경계는 안 남긴다. 그래서 "창이 비어 있던
    마지막 시각"(plan_usage.window_floor) 뒤의 첫 요청을 창의 시작으로 본다.
    그 첫 요청이 Claude Code 밖(웹·모바일)에서 일어났으면 몇 분 늦게 잡힌다 —
    실측에서 약 7분 차이였다. **추정이므로 상태줄의 resets_at보다 뒤에 선다.**

    이미 지난 창이 나오면 하한을 잘못 잡은 것이므로 버린다.
    """
    floor = plan_usage.window_floor(plan_usage.samples(), now)
    if floor is None:
        return None
    after = next((e.timestamp for e in entries if e.timestamp > floor), None)
    if after is None:
        return None
    reset_at = after + WINDOW
    return reset_at if reset_at > now else None


@dataclass(frozen=True, slots=True)
class Official:
    """공식 소스에서 뽑은 값 한 벌. **항목마다 출처가 다르다.**

    소스 두 개는 강점이 갈린다:

        상태줄 훅   resets_at이 서버가 준 정확한 값이다. 사용률도 공식.
                    단 훅 설치와 Claude Code 재시작이 필요하고, Pro/Max에서
                    세션 첫 응답 뒤에야 들어온다
        앱 기록     설치도 재시작도 필요 없고 웹·모바일 사용까지 반영된다.
                    단 15분 간격이라 창 경계는 추정할 수밖에 없다

    그래서 소스를 통째로 고르지 않고 **항목별로** 고른다. 한때는 앱 기록을
    통째로 1순위에 두고, 그쪽이 창 경계를 못 구하면 사용률까지 같이 버렸다.
    경계와 사용률은 서로 독립인데도 그랬다 — 앱이 몇 시간 꺼져 있으면 공식
    사용률을 손에 들고도 화면 전체가 어림으로 떨어졌다.
    """

    reset_at: datetime | None = None
    reset_exact: bool = False
    """리셋 시각이 서버가 준 값인가. False면 추정이라 화면에 ~를 붙인다."""

    used_percentage: float | None = None
    weekly_percentage: float | None = None
    weekly_reset_at: datetime | None = None

    captured_at: datetime | None = None
    """사용률을 **언제 받아둔 값인가.**

    공식 수치라고 해서 지금 값인 건 아니다. 훅은 Claude Code가 상태줄을 그릴 때만
    돌고, 앱 기록은 앱이 켜져 있을 때만 갱신된다. 그래서 그 기기에서 한동안
    Claude Code를 안 쓰면 몇 시간 전 사용률이 그대로 남아 있다 — 창이 아직
    안 끝났으므로 유효성 검사도 통과한다.

    기기 두 대에서 같은 계정을 쓰는데 사용률이 서로 다르게 나오는 원인이 이것이다.
    값 자체는 계정 기준이라 맞지만 **찍힌 시각이 다르다.** 그래서 나이를 같이
    들고 다니고, 오래된 값은 화면에서 오래됐다고 밝힌다."""

    source: str = "none"
    """사용률이 어디서 왔나: "hook" | "app" | "none".

    none이면 화면이 어림값으로 떨어진다. **왜 떨어졌는지 화면에 밝힌다** —
    "어림"만 뜨고 이유가 없으면 훅이 없는 건지 앱이 꺼진 건지 알 수가 없다.
    실제로 재현이 안 되는 어림 스크린샷을 받고 나서 넣었다."""


def resolve_official(entries: list[UsageEntry], now: datetime) -> Official:
    """항목별로 가장 믿을 만한 출처를 골라 한 벌로 묶는다."""
    hook = official_limits(now)
    rows = plan_usage.samples()
    sample = plan_usage.latest(rows)

    # --- 리셋 시각: 서버가 준 값 > 손으로 꽂은 값 > 앱 기록 추정 ---
    reset_at, reset_exact = None, False
    if hook is not None:
        reset_at, reset_exact = hook["reset_at"], True
    elif (pin := pinned_reset(now)) is not None and now < pin:
        reset_at, reset_exact = pin, True
    else:
        reset_at = app_reset_floor(entries, now)

    # --- 5시간 사용률: 둘 중 **더 최근에 찍힌 쪽** ---
    #
    # 예전에는 훅을 무조건 1순위로 뒀는데, 훅 값은 Claude Code가 상태줄을 그릴 때만
    # 갱신된다. 그 기기에서 Claude Code를 몇 시간 안 쓰면 낡은 사용률이 남아 있고,
    # 창이 아직 안 끝났으니 유효성 검사도 통과해 버린다. 그동안 앱이 켜져 있었다면
    # 앱 기록이 훨씬 최신인데도 낡은 훅 값을 썼다.
    #
    # 앱 샘플 값 자체에는 손대지 않는다. 조업량으로 한도를 역산해 뒤처진 만큼
    # 보정하는 코드가 한때 있었는데, 못 보는 웹·모바일 사용이 눈금을 망가뜨려
    # 100%로 튀었다 (근거는 plan_usage 모듈 도크스트링).
    hook_pct = plan_usage.clean_pct(hook["used_percentage"]) if hook else None
    hook_at = hook["captured_at"] if hook else None
    app_pct = plan_usage.clean_pct(sample.five_hour) if sample is not None else None
    app_at = sample.at if sample is not None else None

    used, source, captured_at = None, "none", None
    if hook_pct is not None and (
        app_pct is None or app_at is None or hook_at is None or hook_at >= app_at
    ):
        used, source, captured_at = hook_pct, "hook", hook_at
    elif app_pct is not None:
        used, source, captured_at = app_pct, "app", app_at

    # --- 주간: 사용률과 같은 출처를 따라간다 ---
    # 5시간은 훅, 주간은 앱처럼 섞으면 두 숫자가 서로 다른 시점을 가리킨다.
    weekly = hook["weekly"] if hook else {}
    if source == "app" and sample is not None:
        weekly_pct = plan_usage.clean_pct(sample.seven_day)
    else:
        weekly_pct = plan_usage.clean_pct(weekly.get("used_percentage"))
        if weekly_pct is None and sample is not None:
            weekly_pct = plan_usage.clean_pct(sample.seven_day)

    weekly_reset = None
    if weekly.get("resets_at") is not None:
        try:
            weekly_reset = datetime.fromtimestamp(
                float(weekly["resets_at"]), timezone.utc
            )
        except (TypeError, ValueError, OSError):
            weekly_reset = None

    return Official(
        reset_at, reset_exact, used, weekly_pct, weekly_reset, captured_at, source
    )


def official_limits(now: datetime) -> dict | None:
    """상태줄 훅이 받아둔 공식 사용량. 없으면 None.

    Claude Code가 상태줄 명령에 넘기는 `rate_limits`를 그대로 저장한 값이다.
    추정이 아니라 계정 기준 공식 수치라, 웹·모바일 사용량까지 반영돼 있다.
    창이 이미 지났으면 무시한다 (Claude Code도 지난 창은 빼고 보낸다).
    """
    saved = statusline.load()
    if not saved:
        return None
    five = (saved.get("rate_limits") or {}).get("five_hour") or {}
    resets = five.get("resets_at")
    if resets is None:
        return None
    try:
        reset_at = datetime.fromtimestamp(float(resets), timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    if reset_at <= now:
        return None

    try:
        captured_at = datetime.fromisoformat(saved["captured_at"])
    except (KeyError, TypeError, ValueError):
        captured_at = None

    return {
        "reset_at": reset_at,
        "captured_at": captured_at,
        "used_percentage": five.get("used_percentage"),
        "weekly": (saved.get("rate_limits") or {}).get("seven_day") or {},
    }


def pinned_reset(now: datetime) -> datetime | None:
    """수동으로 꽂은 리셋 시각. 없으면 None.

    상태줄 훅을 못 쓰는 경우(구독이 아니거나 훅 설치 전)를 위한 수단이다.
    훅이 있으면 그쪽이 우선한다.

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
    return _window(start, [e for e in entries if start <= e.timestamp < reset_at])


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
    bucket: list[UsageEntry] = []

    for e in sorted(entries, key=lambda x: x.timestamp):
        if start is None or e.timestamp >= start + WINDOW:
            if bucket:
                windows.append(_window(start, bucket))
            start, bucket = _block_start(e.timestamp), []
        bucket.append(e)
    if bucket:
        windows.append(_window(start, bucket))
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
    recent = totals_of(e for e in entries if since <= e.timestamp <= now)
    return recent.total_tokens / (span.total_seconds() / 60)


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Phase 1이 내놓아야 하는 숫자 세 개."""

    window: Window | None
    tokens_per_minute: float
    now: datetime
    pinned: bool = False
    """리셋 시각이 확정값인가. False면 JSONL로 추정한 값이라 틀릴 수 있다."""

    used_percentage: float | None = None
    """5시간 창 사용률(0~100). 공식 수치가 있을 때만 채워진다. 추정하지 않는다."""

    official_source: str = "none"
    """사용률의 출처: "hook" | "app" | "none". 화면이 이유를 밝히는 데 쓴다."""

    official_age_min: int | None = None
    """공식 사용률을 받아둔 지 몇 분 됐나. None이면 공식 수치가 없다는 뜻.

    값이 크면 그 기기에서 Claude Code를 한동안 안 쓴 것이다 — 숫자는 계정
    기준이라 맞지만 그 시점 기준이라, 다른 기기와 안 맞아 보이는 이유가 된다."""

    weekly_percentage: float | None = None
    weekly_reset_at: datetime | None = None

    @property
    def total_tokens(self) -> int:
        return self.window.total_tokens if self.window else 0

    @property
    def time_to_reset(self) -> timedelta | None:
        return self.window.time_to_reset(self.now) if self.window else None


def snapshot(entries: Iterable[UsageEntry], now: datetime | None = None) -> Snapshot:
    """창 하나와 그 안의 숫자들.

    출처 우선순위는 여기 없다 — resolve_official이 **항목별로** 이미 골라뒀다.
    여기서 남은 판단은 하나뿐이다: 리셋 시각을 아는가.

        안다   그 창 [reset-5h, reset)만 센다. 블록을 이어붙이지 않으므로
               보이지 않는 사용량 때문에 경계가 밀리지 않는다
        모른다 JSONL 블록으로 추정한다. 웹·모바일 사용이 있으면 어긋난다

    사용률은 이 판단과 무관하다. 창 경계를 몰라도 공식 사용률은 공식이다.
    """
    now = now or datetime.now(timezone.utc)
    entries = list(entries)
    official = resolve_official(entries, now)

    return Snapshot(
        window=(
            anchored_window(entries, official.reset_at)
            if official.reset_at is not None
            else current_window(build_windows(entries), now)
        ),
        tokens_per_minute=burn_rate(entries, now),
        now=now,
        pinned=official.reset_exact,
        used_percentage=official.used_percentage,
        official_source=official.source,
        official_age_min=(
            None if official.captured_at is None
            else max(0, int((now - official.captured_at).total_seconds() // 60))
        ),
        weekly_percentage=official.weekly_percentage,
        weekly_reset_at=official.weekly_reset_at,
    )


def _main() -> None:
    import sys
    from collections import Counter

    from . import i18n

    # Windows 콘솔이 cp949라 한글/기호에서 죽는다. 숫자를 못 보면 의미가 없다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        i18n.init(sys.argv[1:])
    except ValueError as e:
        print(e, file=sys.stderr)
        raise SystemExit(2)

    entries = collect_entries()
    snap = snapshot(entries)
    prov = Counter(e.provenance for e in entries)

    print(i18n.pick(
        f"요청 {len(entries)}개, 윈도우 {len(build_windows(entries))}개",
        f"{len(entries)} requests, {len(build_windows(entries))} windows"))
    print()
    if snap.used_percentage is not None:
        print(i18n.pick(f"사용률       {snap.used_percentage:.0f}%  (공식 수치)",
                        f"usage        {snap.used_percentage:.0f}%  (official)"))
    if snap.window is None:
        print(i18n.pick("활성 윈도우 없음 (마지막 블록이 이미 리셋됨)",
                        "no active window (the last block has already reset)"))
    else:
        w = snap.window
        head = i18n.pick("현재 윈도우 ", "window      ")
        tail = i18n.pick(f"요청 {w.entries}개", f"{w.entries} requests")
        print(f"{head} {w.start:%Y-%m-%d %H:%M} ~ {w.end:%H:%M} UTC, {tail}")
        print(f"  input     {w.input_tokens:>14,}")
        print(f"  output    {w.output_tokens:>14,}")
        print(f"  cache_w   {w.cache_creation_tokens:>14,}")
        print(f"  cache_r   {w.cache_read_tokens:>14,}")
        print(i18n.pick(f"  합계      {w.total_tokens:>14,}",
                        f"  total     {w.total_tokens:>14,}"))
        rest = snap.time_to_reset
        assert rest is not None
        h, m = int(rest.total_seconds() // 3600), int(rest.total_seconds() % 3600 // 60)
        print(i18n.pick(f"리셋까지     {h}시간 {m}분",
                        f"resets in    {h}h {m}m"))
    print(i18n.pick(
        f"burn rate    {snap.tokens_per_minute:,.0f} 토큰/분 (최근 1시간)",
        f"burn rate    {snap.tokens_per_minute:,.0f} tokens/min (last hour)"))

    # --- 주간 (공식 화면의 "주간 한도"에 대응) ---
    now = snap.now
    wk = weekly_totals(entries, now)
    days_left = (weekly_end(now) - now)
    d = int(days_left.total_seconds() // 86400)
    h = int(days_left.total_seconds() % 86400 // 3600)
    print()
    print(i18n.pick(
        f"주간         {weekly_start(now).astimezone():%m-%d %H:%M} 부터, 요청 {wk.requests}개",
        f"week         since {weekly_start(now).astimezone():%m-%d %H:%M}, {wk.requests} requests"))
    print(i18n.pick(f"  조업량    {wk.catch:>14,}   (input+output)",
                    f"  catch     {wk.catch:>14,}   (input+output)"))
    print(i18n.pick(f"  전체      {wk.total_tokens:>14,}   (캐시 포함)",
                    f"  total     {wk.total_tokens:>14,}   (cache included)"))
    print(i18n.pick(f"  다음 리셋까지 {d}일 {h}시간",
                    f"  resets in {d}d {h}h"))

    # --- 모델별 ---
    print()
    print(i18n.pick("모델별 (조업량 기준)", "by model (catch)"))
    total_catch = sum(t.catch for _, t in model_breakdown(entries)) or 1
    for model, t in model_breakdown(entries):
        req = i18n.pick(f"요청 {t.requests}", f"{t.requests} requests")
        print(f"  {model:<28}{t.catch:>12,}  {100 * t.catch / total_catch:5.1f}%  {req}")

    # --- 전체 누적 ---
    life = totals_of(entries)
    print()
    print(i18n.pick(
        f"전체 누적    요청 {life.requests:,}개 · 조업량 {life.catch:,} · "
        f"전체 {life.total_tokens:,}",
        f"all time     {life.requests:,} requests · catch {life.catch:,} · "
        f"total {life.total_tokens:,}"))
    print()
    print(f"provenance   {dict(prov)}")


if __name__ == "__main__":
    _main()
