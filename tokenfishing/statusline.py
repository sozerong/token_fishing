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

    "statusLine": { "type": "command", "command": "python -m tokenfishing.statusline" }

참고 (공식 문서):
- rate_limits는 Pro/Max 구독에서만, 그리고 세션의 첫 API 응답 뒤에 나타난다
- 창이 리셋 시각을 지나면 Claude Code가 해당 창을 빼고 보낸다
- 리셋 시각이 되면 상태줄이 자동으로 다시 실행된다
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path.home() / ".claude" / "tokenfishing-limits.json"


def save(payload: dict) -> None:
    """원자적으로 쓴다. 팝업이 동시에 읽어도 반쯤 쓰인 파일을 보지 않게.

    ponytail: config.save와 같은 코드지만 합치지 않는다. 이 파일은 상태줄 훅으로
    **경로를 직접 지정해 실행**되므로(hook_command 참고) 패키지 상대 import를
    하는 순간 훅이 죽는다. 그래서 이 모듈만 표준 라이브러리로 자족한다.
    """
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


def _lang() -> str:
    """설정 파일에서 언어만 읽는다.

    i18n을 import하지 않는다 — 이 모듈은 상태줄 훅으로 **경로를 직접 지정해**
    실행되므로(hook_command 참고) 패키지 상대 import를 하는 순간 훅이 죽는다.
    표준 라이브러리만으로 자족해야 해서 여기서는 파일을 직접 읽는다.
    """
    try:
        saved = json.loads(
            (Path.home() / ".claude" / "tokenfishing-config.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return "ko"
    lang = saved.get("lang") if isinstance(saved, dict) else None
    return lang if lang in ("ko", "en") else "ko"


def _line(limits: dict, now: datetime) -> str:
    ko = _lang() == "ko"
    parts = []
    five = limits.get("five_hour") or {}
    if five.get("used_percentage") is not None:
        pct = float(five["used_percentage"])
        text = f"🎣 {_bar(pct)} {pct:.0f}%"
        resets = five.get("resets_at")
        if resets:
            left = datetime.fromtimestamp(float(resets), timezone.utc) - now
            mins = max(0, int(left.total_seconds() // 60))
            h, m = mins // 60, mins % 60
            text += f" · {h}시간 {m}분 남음" if ko else f" · {h}h {m}m left"
        parts.append(text)

    week = limits.get("seven_day") or {}
    if week.get("used_percentage") is not None:
        pct = float(week["used_percentage"])
        parts.append(f"주간 {pct:.0f}%" if ko else f"week {pct:.0f}%")
    return "  |  ".join(parts)


SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CHAIN_PATH = Path.home() / ".claude" / "tokenfishing-chain.json"


def hook_command() -> str:
    """이 훅을 실행하는 명령. 어느 폴더에서 실행되든 동작해야 한다.

    이 파일은 표준 라이브러리만 import하므로 패키지 설치 없이 경로로 직접 실행된다.
    상태줄은 세션의 작업 폴더에서 실행되지 저장소 폴더에서 실행되지 않기 때문에,
    `-m tokenfishing.statusline` 대신 절대 경로를 쓴다.
    """
    return f'"{sys.executable}" "{Path(__file__).resolve()}"'


def chain_command() -> str:
    """원래 상태줄을 살려 둔 채 우리가 앞에 서는 명령."""
    return f"{hook_command()} --chain"


OWN_MARK = "tokenfishing/statusline.py"
"""등록된 명령이 우리 것인지 알아보는 표시.

파일명(statusline.py)만 보면 안 된다 — 남의 훅이 `ponytail-statusline.sh`나
`other-statusline.py`처럼 이름에 statusline을 달고 있으면 우리 것으로 오인해서,
덮어쓰면 안 될 상태줄을 덮어쓰고 해제하면 안 될 것을 해제한다. 디렉터리까지
포함한 조각으로 봐야 구분된다. 설치 경로가 바뀌어도(venv 이동) 이 조각은 남는다.
"""


def is_ours(command: str) -> bool:
    return OWN_MARK in command.replace("\\", "/")


def save_chain(command: str) -> None:
    """원래 상태줄 명령을 따로 적어 둔다.

    등록 문자열 안에 끼워 넣지 않는 이유: 남의 명령에는 이미 따옴표가 들어 있어서
    (플러그인 경로에 공백이 흔하다) 중첩 인용이 금방 깨진다. 파일에 두면 인용이
    한 겹으로 끝나고, 해제할 때 되돌릴 원본도 여기서 그대로 읽는다.
    """
    CHAIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHAIN_PATH.write_text(
        json.dumps({"command": command}, ensure_ascii=False), encoding="utf-8"
    )


def load_chain() -> str:
    try:
        saved = json.loads(CHAIN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return saved.get("command", "") if isinstance(saved, dict) else ""


def run_chained(payload: str) -> int:
    """우리는 조용히 받아 적고, 원래 상태줄의 출력을 그대로 통과시킨다.

    상태줄 슬롯은 settings.json에 하나뿐이라 도구 둘이 동시에 가질 수 없다.
    그래서 자리를 뺏는 대신 앞에 서서, 같은 stdin을 원래 명령에도 그대로 넘긴다.
    사용자 눈에는 원래 쓰던 상태줄이 그대로 보이고, 우리는 공식 수치만 받아 적는다.
    """
    ours = capture(payload)
    original = load_chain()
    if not original:
        if ours:
            print(ours)
        return 0

    out = ""
    try:
        done = subprocess.run(
            original, shell=True, input=payload,
            capture_output=True, text=True, timeout=5,
        )
        out = done.stdout.strip("\n")
    except Exception:  # noqa: BLE001
        # 원래 명령이 사라졌거나(플러그인 경로는 세션마다 바뀐다) 멈춰도
        # 상태줄은 시끄럽게 실패하면 안 된다.
        out = ""

    # 원래 상태줄이 죽었으면 최소한 우리 줄이라도 보여준다. 빈 상태줄은
    # 왜 비었는지 알 방법이 없다.
    line = out or ours
    if line:
        print(line)
    return 0


def install() -> int:
    """~/.claude/settings.json에 상태줄을 등록한다. 나머지 설정은 그대로 둔다."""
    settings: dict = {}
    if SETTINGS_PATH.exists():
        try:
            settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"{SETTINGS_PATH} 를 읽을 수 없다. 직접 고쳐라.")
            return 1

    # 이미 남의 상태줄이 있으면 **뺏지 않고 앞에 선다.** 슬롯은 하나뿐이라
    # 예전에는 그냥 거절했는데, 그러면 사용자가 "쓰던 상태줄"과 "정확한 숫자"
    # 중 하나를 포기해야 했다. 둘 다 가질 수 있는데 그럴 이유가 없다.
    existing = (settings.get("statusLine") or {}).get("command", "")
    chained = bool(existing) and not is_ours(existing)
    if chained:
        save_chain(existing)

    settings["statusLine"] = {
        "type": "command",
        "command": chain_command() if chained or load_chain() else hook_command(),
    }
    backup = SETTINGS_PATH.with_suffix(".json.bak")
    if SETTINGS_PATH.exists():
        backup.write_text(SETTINGS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"상태줄 등록 완료: {SETTINGS_PATH}")
    if chained:
        print()
        print("이미 있던 상태줄은 그대로 둔다. 화면에는 그게 계속 보이고,")
        print("우리는 그 앞에서 공식 사용량만 받아 적는다:")
        print(f"  {existing}")
        print("(해제하면 이 명령이 원래대로 돌아간다)")
    if backup.exists():
        print(f"이전 설정 백업:  {backup}")
    print()
    print("Claude Code를 새로 시작하면 그때부터 공식 사용량을 쓴다.")
    print("(구독 사용량은 Pro/Max에서 세션의 첫 응답 뒤에 들어온다)")
    return 0


def uninstall() -> int:
    """등록했던 상태줄을 걷어낸다.

    이걸 안 하면 패키지를 지운 뒤에도 settings.json에 사라진 파일을 가리키는
    명령이 남는다. 훅은 조용히 실패하도록 만들어져 있어서(main 참고) 사용자는
    상태줄이 왜 빈칸인지 알 수가 없다. 우리가 넣은 것만 지우고 나머지는 둔다.
    """
    if not SETTINGS_PATH.exists():
        print(f"{SETTINGS_PATH} 가 없다. 지울 것도 없다.")
        return 0
    try:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"{SETTINGS_PATH} 를 읽을 수 없다. 직접 고쳐라.")
        return 1

    existing = (settings.get("statusLine") or {}).get("command", "")
    if not is_ours(existing):
        print("이 도구가 등록한 상태줄이 아니다. 건드리지 않는다.")
        return 0

    # 남의 상태줄 앞에 서 있었으면 그 자리를 돌려준다. 그냥 지우면 사용자가
    # 원래 쓰던 상태줄까지 같이 사라진다.
    original = load_chain()
    if original:
        settings["statusLine"] = {"type": "command", "command": original}
        print(f"원래 상태줄로 되돌림: {original}")
    else:
        settings.pop("statusLine", None)
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"상태줄 해제 완료: {SETTINGS_PATH}")

    for leftover in (STATE_PATH, CHAIN_PATH,
                     Path.home() / ".claude" / "tokenfishing-config.json"):
        if leftover.exists():
            leftover.unlink()
            print(f"삭제: {leftover}")
    return 0


def capture(payload: str) -> str:
    """세션 JSON에서 공식 수치를 받아 적고, 보여줄 한 줄을 돌려준다.

    이어붙이기 모드와 단독 모드가 같은 코드를 쓴다 — 받아 적는 일은 어느 쪽이든
    똑같이 일어나야 하고, 갈리는 건 무엇을 출력하느냐뿐이다.
    """
    try:
        session = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return ""  # 상태줄은 절대 시끄럽게 실패하면 안 된다

    now = datetime.now(timezone.utc)
    limits = session.get("rate_limits")
    if not isinstance(limits, dict) or not limits:
        # Pro/Max가 아니거나 아직 첫 API 응답 전이다. 조용히 지나가되 **비워둔다** —
        # 플랜이 내려가면 rate_limits가 사라지는데, 그때 옛 기록을 지우지 않으면
        # 화면이 지난 구독의 사용률을 공식이라며 영원히 보여준다.
        save({"rate_limits": None, "captured_at": now.isoformat()})
        return ""

    save({"rate_limits": limits, "captured_at": now.isoformat()})
    return _line(limits, now)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if "--install" in sys.argv:
        return install()
    if "--uninstall" in sys.argv:
        return uninstall()

    payload = sys.stdin.read()
    if "--chain" in sys.argv:
        return run_chained(payload)

    line = capture(payload)
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
