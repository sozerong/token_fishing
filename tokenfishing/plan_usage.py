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

1. 최신 사용률 — 화면에 **그대로** 띄운다. 최대 15분 뒤처지지만 손대지 않는다.

   한때 (조업량 ÷ 공식 사용률)로 한도를 역산해 그 뒤 쌓인 만큼을 더하는 보정을
   넣었다. 이 저장소 기록으로 뒤돌아 검증하니 28승 49무 11패였는데, 이긴 건
   1~4%p인 반면 진 건 최대 46%p 더 틀렸고 **11패 중 7건이 10%p 넘게, 전부
   100% 포화 방향**이었다. 우리가 못 보는 웹·모바일 사용이 공식 사용률을
   올려두면 역산한 한도가 작게 나오고, 그 작은 눈금 위에서 조업량이 조금만
   늘어도 100%로 튄다. 중앙값 1.7%p를 벌자고 "한도 다 썼다"는 거짓말을 살
   이유가 없다. 신선도가 필요하면 상태줄 훅을 쓴다 — 그쪽은 정확하고 실시간이다.
2. 리셋 경계   — fh == 0 이거나 fh가 급락한 지점 뒤로 창이 열렸다. 그 뒤 첫
                 요청이 지금 창의 시작이고, 거기에 5시간을 더하면 리셋이다.
                 **이건 하한 추정이다.** 정확한 리셋 시각은 상태줄 훅에만 있다
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import debug

RESET_DROP = 20
"""fh가 이만큼(%p) 떨어지면 창이 리셋된 것으로 본다.

사용률은 쓸수록 오르기만 한다. 내려간 건 리셋뿐이다. 실측에서는 99 → 0으로
떨어졌다. 20%p는 표본 잡음과 진짜 리셋을 가르기에 넉넉한 문턱이다."""


def candidate_paths() -> list[Path]:
    """앱 기록이 있을 만한 곳 전부. 존재 여부는 보지 않는다.

    윈도우에서 Claude 데스크톱 앱은 **MSIX(스토어) 패키지 앱**이라 %APPDATA% 쓰기가
    패키지 컨테이너로 리다이렉트된다:

        논리  %APPDATA%/Claude/plan-usage-history.json
        실제  %LOCALAPPDATA%/Packages/Claude_<id>/LocalCache/Roaming/Claude/...

    앱 안에서 실행되면 논리 경로가 알아서 실제 경로로 풀리지만, **밖에서 띄우면
    논리 경로는 존재하지도 않는다.** 팝업을 일반 PowerShell에서 실행하면 파일을
    통째로 못 찾아 화면이 어림으로 떨어졌다 — 실측으로 확인한 사례다.
    그래서 리다이렉트 경로를 직접 후보에 넣는다. 패키지 이름의 해시는 설치마다
    다를 수 있으니 글롭으로 잡는다.
    """
    if sys.platform == "darwin":
        return [Path.home() / "Library/Application Support/Claude/plan-usage-history.json"]
    if sys.platform != "win32":
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return [base / "Claude" / "plan-usage-history.json"]

    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    found = [roaming / "Claude" / "plan-usage-history.json"]
    try:
        found += sorted(
            (local / "Packages").glob(
                "Claude_*/LocalCache/Roaming/Claude/plan-usage-history.json"
            )
        )
    except OSError:
        pass
    return found


def history_path() -> Path | None:
    """앱 기록 파일. 없으면 None.

    후보가 여러 개면 **가장 최근에 쓰인 것**을 쓴다. 예전 설치가 남긴 파일이
    같이 걸리면 먼저 찾은 걸 쓰다가 조용히 낡은 숫자를 보여주게 된다.
    """
    live = [(p.stat().st_mtime, p) for p in candidate_paths() if p.exists()]
    return max(live)[1] if live else None


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


READ_ATTEMPTS = 3
"""앱이 파일을 다시 쓰는 순간에 걸리면 몇 번 더 해 본다.

한 번 실패하면 그 프로세스는 눈이 먼다. 갓 시작한 프로세스는 _cache도 비어 있어서
화면 전체가 어림으로 떨어진다 — 실제로 그 상태의 스크린샷을 받았다. 재시도 세 번은
쓰기가 끝나기를 기다리기에 충분하고, 실패해도 잃는 건 150ms뿐이다."""


def samples() -> list[Sample]:
    """시간순 샘플. 읽기에 실패하면 마지막으로 성공한 값을 그대로 쓴다."""
    global _cache

    why = "no file"
    for attempt in range(READ_ATTEMPTS):
        # 파일이 없는 것도 실패로 친다. 앱이 지웠다 다시 쓰는 순간일 수 있다.
        path = history_path()
        data = None
        if path is not None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                why = f"{type(e).__name__}: {e}"
            if data is not None:
                rows = []
                for raw in data.get("samples") or []:
                    try:
                        at = datetime.fromtimestamp(raw["t"] / 1000, timezone.utc)
                    except (KeyError, TypeError, ValueError, OSError):
                        continue
                    u = raw.get("u") or {}
                    rows.append(Sample(at, u.get("fh"), u.get("sd")))
                if rows:
                    rows.sort(key=lambda s: s.at)
                    _cache = rows
                    return rows
        if attempt + 1 < READ_ATTEMPTS:
            time.sleep(0.05)

    # 여기 오면 화면이 어림으로 떨어진다. **왜인지 삼키지 말 것** — 조용히 빈
    # 목록을 뱉는 바람에 재현 안 되는 화면을 붙들고 시간을 버렸다.
    debug(f"app history unreadable ({why}), {len(_cache)} cached samples")
    return _cache


def latest(rows: list[Sample] | None = None) -> Sample | None:
    rows = samples() if rows is None else rows
    for s in reversed(rows):
        if s.five_hour is not None:
            return s
    return None


def window_floor(rows: list[Sample], now: datetime) -> datetime | None:
    """지금 창이 열린 시각의 **하한**. 이 시각 이후의 첫 요청이 창을 열었다.

    신호가 두 개다. 늦은 쪽이 더 좁은 하한이므로 늦은 쪽을 택한다:

        급락    fh가 뚝 떨어졌으면 그 직전 샘플 이후 어딘가에서 리셋됐다
        빈 창   fh == 0 이면 그 시각에 창이 비어 있었다는 사실 자체다

    급락만 쓰면 앱이 꺼져 있을 때 무너진다. 샘플이 15분 간격일 땐 급락 구간이
    15분이라 하한이 쓸 만하지만, 앱이 꺼져 있으면 그 구간이 통째로 몇 시간이 된다.
    실측: 18:59 fh=100 → (7시간 32분 공백) → 02:31 fh=0. 급락만 보면 하한이
    18:59라 이전 창의 요청까지 끌어와 이미 만료된 창이 나온다. fh=0을 보면 02:31이다.

    fh == 0 은 나이와 무관하게 항상 유효한 하한이다 — 그 시각에 창이 비어 있었다면
    지금 창은 그 뒤에 열렸다. 그래서 오래된 fh=0 샘플이 섞여도 틀리지 않는다.
    """
    previous: Sample | None = None
    floor: datetime | None = None
    for s in rows:
        if s.at > now or s.five_hour is None:
            continue
        if previous is not None and s.five_hour < previous.five_hour - RESET_DROP:
            floor = previous.at
        if s.five_hour == 0 and (floor is None or s.at > floor):
            floor = s.at
        previous = s
    return floor


def clean_pct(value: object) -> float | None:
    """사용률로 쓸 수 있는 값인가. 아니면 None.

    상태줄 페이로드에 `used_percentage` 자리로 `resets_at` epoch이 새는 버그가
    보고돼 있다(anthropics/claude-code#52326). 그대로 쓰면 화면에 100%가 박힌다.
    100을 넘으면 반올림 오차(101까지)만 100으로 깎고 나머지는 버린다.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN/Infinity
        return None
    if value < 0:
        return None
    if value > 100:
        return 100.0 if value <= 101 else None
    return float(value)


def _doctor() -> None:
    """왜 공식 수치를 못 받는지 한 화면에 뱉는다.

        py -3.12 -m tokenfishing.plan_usage

    "어림"만 뜨고 이유가 없어서 재현 안 되는 화면을 붙들고 시간을 버린 적이 있다.
    다음엔 이 한 줄로 끝낸다.
    """
    import os
    import sys
    from datetime import datetime, timezone

    from . import i18n

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    pick = i18n.pick

    print(f"python      {sys.executable}")
    print(f"APPDATA     {os.environ.get('APPDATA')}")

    path = history_path()
    none = pick("없음 (후보 경로에 파일이 없다)", "not found (no candidate path exists)")
    print(pick("앱 기록     ", "app history ") + f"{path if path else none}")
    if path is not None and str(path) != str(candidate_paths()[0]):
        print(pick("  (패키지 컨테이너 경로에서 찾았다 — 앱이 MSIX로 설치돼 있다)",
                   "  (found under the package container — the app is an MSIX install)"))
    if path is None:
        # 같은 경로가 셸마다 다르게 보이는 일이 실제로 있었다. 컨테이너/샌드박스
        # 안에서 돌면 AppData 가 통째로 다른 곳을 가리킨다. 그걸 여기서 가른다.
        for c in candidate_paths():
            print(pick(f"  후보      {c}  존재={c.exists()}",
                       f"  candidate {c}  exists={c.exists()}"))
        expected = candidate_paths()[0]
        print(pick(f"  부모 폴더 {expected.parent} 존재={expected.parent.is_dir()}",
                   f"  parent    {expected.parent} exists={expected.parent.is_dir()}"))
        if expected.parent.is_dir():
            try:
                names = sorted(q.name for q in expected.parent.iterdir())
            except OSError as e:
                names = [f"<unreadable {type(e).__name__}>"]
            listing = f"{names[:12]}{' …' if len(names) > 12 else ''}"
            print(pick(f"  그 안 내용 {listing}", f"  contents  {listing}"))
            print(pick("  → 폴더는 보이는데 파일만 없다. 앱이 아직 안 만들었거나 지웠다.",
                       "  -> the folder is there but the file is not. The app has not "
                       "written it yet, or removed it."))
        else:
            print(pick("  → 후보가 전부 비었다. 데스크톱 앱이 아직 기록을 안 만들었거나",
                       "  -> none of the candidates exist. Either the desktop app has "
                       "not written"))
            print(pick("     설치 형태가 달라 경로가 또 다르다. 앱을 켜두고 15분 기다려 봐라.",
                       "     its history yet, or it is installed somewhere else. Leave "
                       "the app open for 15 minutes and try again."))
        print(f"  whoami    {os.environ.get('USERNAME')}@{os.environ.get('USERDOMAIN')}")
        print(f"  home      {Path.home()}")
        return

    try:
        raw = path.read_text(encoding="utf-8")
        print(pick(f"  읽기      OK ({len(raw):,} 바이트)",
                   f"  read      OK ({len(raw):,} bytes)"))
    except OSError as e:
        print(pick(f"  읽기      실패 {type(e).__name__}: {e}",
                   f"  read      failed {type(e).__name__}: {e}"))
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(pick(f"  JSON      깨짐 {e}", f"  JSON      broken {e}"))
        return
    print(f"  version   {data.get('version')}")
    n = len(data.get("samples") or [])
    print(pick(f"  samples   {n}개 (원본)", f"  samples   {n} (raw)"))

    rows = samples()
    print(pick(f"  파싱      {len(rows)}개", f"  parsed    {len(rows)}"))
    if rows:
        r = rows[-1]
        print(pick("  최신      ", "  newest    ")
              + f"{r.at.astimezone():%H:%M:%S}  fh={r.five_hour!r} sd={r.seven_day!r}")
        print(f"  clean_pct fh→{clean_pct(r.five_hour)!r}  sd→{clean_pct(r.seven_day)!r}")
    s = latest(rows)
    bad = pick("None ← 여기가 문제다", "None <- this is the problem")
    print(f"  latest()  {'OK' if s else bad}")

    from .statusline import STATE_PATH, load

    print(pick("상태줄 훅   ", "statusline  ") + f"{STATE_PATH}")
    saved = load()
    if saved is None:
        print(pick("  캡처      없음 — 훅이 아직 한 번도 안 돌았다",
                   "  capture   none - the hook has never run"))
    else:
        five = (saved.get("rate_limits") or {}).get("five_hour") or {}
        empty = pick("(비어 있음)", "(empty)")
        print(pick("  캡처      ", "  capture   ")
              + f"{saved.get('captured_at')}  five_hour={five or empty}")

    from .aggregate import collect_entries, resolve_official

    off = resolve_official(collect_entries(), datetime.now(timezone.utc))
    print()
    print(pick(f"판정        사용률 출처={off.source}  값={off.used_percentage!r}"
               f"  주간={off.weekly_percentage!r}",
               f"verdict     usage source={off.source}  value={off.used_percentage!r}"
               f"  week={off.weekly_percentage!r}"))
    if off.reset_at:
        how = (pick("확정", "exact") if off.reset_exact else pick("추정", "estimated"))
        print(pick("            리셋=", "            reset=")
              + f"{off.reset_at.astimezone():%H:%M} {how}")
    else:
        print(pick("            리셋=모름", "            reset=unknown"))


if __name__ == "__main__":
    import sys

    from . import i18n

    i18n.init(sys.argv[1:])
    _doctor()
