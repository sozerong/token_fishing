"""Claude Code 상태줄 훅. 공식 사용량 수치를 받아 저장하고 한 줄로 출력한다.

Claude Code는 상태줄 명령에 세션 JSON을 stdin으로 넘기는데, 거기에 구독 사용량이
들어 있다:

    rate_limits.five_hour.used_percentage   0~100
    rate_limits.five_hour.resets_at         Unix epoch seconds
    rate_limits.seven_day.{used_percentage, resets_at}

이 값은 **추정이 아니라 공식 수치다.** 세션 창의 시작 시각을 JSONL에서 추측할 필요가
없어진다 — claude.ai 웹이나 모바일에서 쓴 사용량까지 이미 반영돼 있다.

설치:

    tokenfishing --install-statusline

또는 ~/.claude/settings.json에 직접:

    "statusLine": { "type": "command", "command": "python -m ccpet.statusline" }

참고 (공식 문서):
- rate_limits는 Pro/Max 구독에서만, 그리고 세션의 첫 API 응답 뒤에 나타난다
- 창이 리셋 시각을 지나면 Claude Code가 해당 창을 빼고 보낸다
- 리셋 시각이 되면 상태줄이 자동으로 다시 실행된다
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path.home() / ".claude" / "tokenfishing-limits.json"


def save(payload: dict) -> None:
    """원자적으로 쓴다. 팝업이 동시에 읽어도 반쯤 쓰인 파일을 보지 않게."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, STATE_PATH)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load() -> dict | None:
    """저장된 공식 수치. 없거나 깨졌으면 None."""
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _bar(pct: float, width: int = 10) -> str:
    filled = max(0, min(width, round(pct / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def _line(limits: dict, now: datetime) -> str:
    parts = []
    five = limits.get("five_hour") or {}
    if five.get("used_percentage") is not None:
        pct = float(five["used_percentage"])
        text = f"🎣 {_bar(pct)} {pct:.0f}%"
        resets = five.get("resets_at")
        if resets:
            left = datetime.fromtimestamp(float(resets), timezone.utc) - now
            mins = max(0, int(left.total_seconds() // 60))
            text += f" · {mins // 60}시간 {mins % 60}분 남음"
        parts.append(text)

    week = limits.get("seven_day") or {}
    if week.get("used_percentage") is not None:
        parts.append(f"주간 {float(week['used_percentage']):.0f}%")
    return "  |  ".join(parts)


SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def hook_command() -> str:
    """이 훅을 실행하는 명령. 어느 폴더에서 실행되든 동작해야 한다.

    이 파일은 표준 라이브러리만 import하므로 패키지 설치 없이 경로로 직접 실행된다.
    상태줄은 세션의 작업 폴더에서 실행되지 저장소 폴더에서 실행되지 않기 때문에,
    `-m ccpet.statusline` 대신 절대 경로를 쓴다.
    """
    return f'"{sys.executable}" "{Path(__file__).resolve()}"'


def install() -> int:
    """~/.claude/settings.json에 상태줄을 등록한다. 나머지 설정은 그대로 둔다."""
    settings: dict = {}
    if SETTINGS_PATH.exists():
        try:
            settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"{SETTINGS_PATH} 를 읽을 수 없다. 직접 고쳐라.")
            return 1

    existing = (settings.get("statusLine") or {}).get("command")
    if existing and Path(__file__).name not in existing:
        print("이미 다른 상태줄이 설정돼 있다. 덮어쓰지 않는다:")
        print(f"  {existing}")
        print()
        print("바꾸려면 ~/.claude/settings.json 의 statusLine.command 를 이걸로 교체해라:")
        print(f"  {hook_command()}")
        return 1

    settings["statusLine"] = {"type": "command", "command": hook_command()}
    backup = SETTINGS_PATH.with_suffix(".json.bak")
    if SETTINGS_PATH.exists():
        backup.write_text(SETTINGS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"상태줄 등록 완료: {SETTINGS_PATH}")
    if backup.exists():
        print(f"이전 설정 백업:  {backup}")
    print()
    print("Claude Code를 새로 시작하면 상태줄이 뜨고, 그때부터 공식 사용량을 쓴다.")
    print("(구독 사용량은 Pro/Max에서 세션의 첫 응답 뒤에 들어온다)")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if "--install" in sys.argv:
        return install()

    try:
        session = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # 상태줄은 절대 시끄럽게 실패하면 안 된다

    limits = session.get("rate_limits")
    if not isinstance(limits, dict) or not limits:
        # Pro/Max가 아니거나 아직 첫 API 응답 전이다. 조용히 지나간다.
        return 0

    now = datetime.now(timezone.utc)
    save({"rate_limits": limits, "captured_at": now.isoformat()})

    line = _line(limits, now)
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
