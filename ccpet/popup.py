"""항상 위에 뜨는 도트 팝업. 실행하면 바로 뜬다.

    py -3.12 -m ccpet

왜 브라우저가 아니라 tkinter인가: Document PiP API는 **사용자 제스처가 필수**라
페이지 로드만으로 창을 띄울 수 없다. 버튼을 한 번 눌러야 한다. "실행하면 짠 하고
뜨는" 팝업이 목표라면 브라우저로는 안 된다. tkinter는 표준 라이브러리고 always-on-top을
지원하니 의존성 0으로 목표가 그대로 달성된다.

HTML 화면(render.py)은 버리지 않는다 — Phase 3에서 MCP App으로 포장할 때 그게 표시
계층이 된다. 지금 당장 필요한 건 이쪽이다.
"""

from __future__ import annotations

import os
import random
import sys
import threading
import tkinter as tk
from pathlib import Path

from . import config
from . import __version__, debug
from .state import GameState
from .render import build_state

SCALE = 2
W, H = 180, 120          # 가상 도트 해상도. 실제 창은 이것의 SCALE배.
SEA = 62
REFRESH_SEC = 10
FRAME_MS = 66            # 약 15fps. 도트 화면에 그 이상은 필요 없다.

DUSK, DAY = (26, 26, 58), (92, 160, 214)
SEA_DUSK, SEA_DAY = (10, 18, 44), (30, 90, 140)
FISH_COLORS = ("#e3a447", "#d96f4a", "#7ee787", "#79c0ff")
BITE_SPEED = {"잠잠": 0.10, "잔잔": 0.22, "활발": 0.45, "폭주": 0.85}


def _pile_slots(rows=(7, 6, 5, 4, 2)) -> list[tuple[int, int]]:
    """갑판에 쌓이는 자리. 아래가 넓고 위로 갈수록 좁아진다.

    합이 MAX_FISH_DRAWN(24)이라 100%일 때 바다가 비고 더미가 꽉 찬다.
    """
    slots = []
    for row, count in enumerate(rows):
        indent = row  # 위 줄일수록 안쪽으로
        for col in range(count):
            slots.append((indent * 2 + col * 4, row * 2))
    return slots


_PILE_SLOTS = _pile_slots()


def _mix(a, b, t: float) -> str:
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class Popup:
    def __init__(self, root: tk.Tk, state: GameState) -> None:
        self.root = root
        self.state = state
        self.settings = config.load()
        self.frame = 0
        self.fish: list[dict] = []
        self._sync_fish()

        # 어느 복사본이 도는지 제목으로 바로 보인다. 낡은 프로세스를 붙들고
        # 디버깅하는 일이 실제로 있었다.
        root.title(self._title())
        root.attributes("-topmost", True)
        root.resizable(False, False)
        root.configure(bg="#0d1117")

        self.canvas = tk.Canvas(
            root, width=W * SCALE, height=H * SCALE,
            bg="#0b1020", highlightthickness=0,
        )
        self.canvas.pack()

        self.labels: dict[str, tk.Label] = {}
        for key in ("catch", "tier", "bite", "left", "weekly"):
            lbl = tk.Label(
                root, anchor="w", justify="left",
                bg="#0d1117", fg="#c9d1d9",
                font=("Consolas", 10, "bold" if key == "catch" else "normal"),
            )
            lbl.pack(fill="x", padx=6)
            self.labels[key] = lbl
        self.labels["catch"].configure(fg="#7ee787", font=("Consolas", 13, "bold"))

        # 토글 두 개. 누르면 바뀌고 바로 저장된다.
        bar = tk.Frame(root, bg="#0d1117")
        bar.pack(fill="x", padx=6, pady=(2, 6))
        self.mode_btn = tk.Button(
            bar, command=self._toggle_mode, font=("Consolas", 9),
            bg="#21262d", fg="#c9d1d9", activebackground="#30363d",
            relief="flat", borderwidth=0, padx=6, cursor="hand2",
        )
        self.mode_btn.pack(fill="x")
        self._apply_buttons()

        debug(f"start fill={state.fill_source} official={state.official_source} "
               f"pct={state.used_percentage} left={state.minutes_left} "
               f"mode={self.settings['mode']}")
        self._apply_text()
        self._start_refresh()
        self._tick()

    def _title(self) -> str:
        """제목에 버전과 데이터 출처를 박는다.

        낡은 프로세스를 붙들고 "왜 안 맞지" 하는 일이 반복됐다. 버전이 다르면
        옛 창이고, 출처가 '공식'이 아니면 어림값이다. 창만 봐도 답이 나온다.
        """
        s = self.state
        if s.fill_source == "official":
            where = {"hook": "공식·훅", "app": "공식·앱"}.get(s.official_source, "공식")
        else:
            # 왜 공식이 아닌지 적는다. "어림"만 뜨면 훅이 없는 건지 앱이 꺼진
            # 건지 알 수가 없어서, 재현 안 되는 화면을 붙들고 시간을 버렸다.
            label = {"learned": "어림", "none": "?"}.get(s.fill_source, "?")
            where = f"{label}(공식수치 없음)"
        return f"token fishing {__version__} · {where}"

    # ---- 토글 ----

    def _apply_buttons(self) -> None:
        self.mode_btn.configure(text=f"모드: {config.MODE_LABELS[self.settings['mode']]}")

    def _toggle_mode(self) -> None:
        self.settings["mode"] = config.next_in(config.MODES, self.settings["mode"])
        self._commit_settings()

    def _commit_settings(self) -> None:
        config.save(self.settings)
        self.state = build_state(self.settings)
        self._sync_fish()
        self._apply_buttons()
        self._apply_text()

    # ---- 데이터 ----

    def _start_refresh(self) -> None:
        def loop() -> None:
            while True:
                if self._stop.wait(REFRESH_SEC):
                    return
                try:
                    # 참조 하나를 통째로 갈아끼운다. GIL 덕에 락이 필요 없다.
                    self.state = build_state(self.settings)
                    self.root.after(0, lambda: self.root.title(self._title()))
                    debug(f"fill={self.state.fill_source} "
                           f"official={self.state.official_source} "
                           f"pct={self.state.used_percentage} "
                           f"left={self.state.minutes_left}")
                except Exception as e:  # noqa: BLE001
                    # 파일이 쓰이는 중이라 읽기가 실패할 수 있다. 다음 주기에 다시 시도한다.
                    # 조용히 넘기되, 왜 멈췄는지 물어볼 수 있게 흔적은 남긴다.
                    debug(f"refresh failed: {type(e).__name__}: {e}")

        self._stop = threading.Event()
        threading.Thread(target=loop, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _close(self) -> None:
        self._stop.set()
        self.root.destroy()

    def _new_fish(self) -> dict:
        speed = BITE_SPEED.get(self.state.bite, 0.2)
        return {
            "x": random.uniform(4, W - 12),
            "y": random.uniform(SEA + 6, H - 8),
            "dir": random.choice((-1, 1)),
            "s": speed * random.uniform(0.6, 1.4),
            "c": random.choice(FISH_COLORS),
            "phase": random.uniform(0, 6.28),      # 위아래 흔들림이 겹치지 않게
        }

    def _sync_fish(self) -> None:
        """마리 수를 맞춘다. 늘어난 만큼만 새로 넣고 기존 물고기는 그대로 헤엄친다."""
        n = self.state.fish
        while len(self.fish) > n:
            self.fish.pop()
        while len(self.fish) < n:
            self.fish.append(self._new_fish())

    def _apply_text(self) -> None:
        s = self.state
        if not s.is_fishing:
            self.labels["catch"].configure(text="— 조업 종료", fg="#6e7681")
        elif s.fill is None:
            # 사용률을 모른다. 퍼센트를 지어내지 않고 절대량만 보여준다.
            self.labels["catch"].configure(text=f"{s.catch:,} 토큰", fg="#7ee787")
        else:
            # ~ 는 플랜 눈금으로 어림한 값이라는 표시. 공식 수치면 안 붙는다.
            mark = "" if s.fill_source == "official" else "~"
            pct = s.fill * 100
            self.labels["catch"].configure(
                text=f"{mark}{pct:.0f}%  ·  {s.catch:,} 토큰",
                fg="#f85149" if pct >= 90 else "#d29922" if pct >= 70 else "#7ee787",
            )
        # 마리 수는 화면에 그려져 있다. 숫자로 또 적지 않는다.
        self.labels["tier"].configure(text=s.tier)
        self.labels["bite"].configure(
            text=f"입질 {s.bite} · 캐스팅 {s.casts:,}회"
        )
        # 추정값을 확실한 척 보여주지 않는다. ~ 가 붙어 있으면 틀릴 수 있다는 뜻.
        mark = "" if s.pinned else "~"
        self.labels["left"].configure(
            text="리셋까지 —" if s.minutes_left is None
            else f"리셋까지 {mark}{s.minutes_left // 60}시간 {s.minutes_left % 60}분"
        )
        self.labels["left"].configure(fg="#c9d1d9" if s.pinned else "#d29922")
        self.labels["weekly"].configure(
            text=f"주간 {s.weekly_percentage:.0f}%  ·  {s.weekly_catch:,} 토큰"
            if s.weekly_percentage is not None
            else f"주간 {s.weekly_catch:,} 토큰"
        )

    # ---- 그리기 ----

    def _px(self, x: float, y: float, w: int, h: int, color: str) -> None:
        x, y = int(x) * SCALE, int(y) * SCALE
        self.canvas.create_rectangle(
            x, y, x + w * SCALE, y + h * SCALE, fill=color, width=0
        )

    def _draw(self) -> None:
        import math

        s, t = self.state, self.frame
        self.canvas.delete("all")
        d = s.daylight if s.is_fishing else 0.0

        self._px(0, 0, W, SEA, _mix(DUSK, DAY, d))

        sx, sy = 26 + (1 - d) * (W - 60), 8 + (1 - d) * (SEA - 22)
        sun = "#ffd76e" if d > 0.35 else "#ff9a5a"
        self._px(sx, sy, 11, 11, sun)
        self._px(sx + 2, sy - 1, 7, 13, sun)

        sea_color = _mix(SEA_DUSK, SEA_DAY, d)
        self._px(0, SEA, W, H - SEA, sea_color)

        for x in range(0, W, 2):
            y = SEA + math.sin((x + t * 2) * 0.18) * 1.6
            self._px(x, y, 2, 2, "#8fb8d8" if d > 0.35 else "#5a6b8c")

        for f in self.fish:
            f["x"] += f["dir"] * f["s"]
            if f["x"] < 2:
                f["x"], f["dir"] = 2, 1
            if f["x"] > W - 10:
                f["x"], f["dir"] = W - 10, -1
            y = f["y"] + math.sin(t * 0.25 + f["phase"]) * 1.2
            back = -1 if f["dir"] > 0 else 5
            fork = back + (-1 if f["dir"] > 0 else 1)
            self._px(f["x"], y, 5, 3, f["c"])
            self._px(f["x"] + back, y, 1, 3, f["c"])
            self._px(f["x"] + fork, y - 1, 1, 1, f["c"])
            self._px(f["x"] + fork, y + 3, 1, 1, f["c"])
            self._px(f["x"] + (3 if f["dir"] > 0 else 1), y + 1, 1, 1, "#0d1117")

        bob = math.sin(t * 0.2) * 1.2
        bx, by = 16, SEA - 8 + bob
        self._px(bx, by + 6, 46, 5, "#6b4423")          # 선체
        self._px(bx + 3, by + 4, 40, 2, "#8b5a2b")      # 갑판

        # 낚시꾼은 뱃머리 왼쪽. 갑판 오른쪽은 잡은 물고기 자리로 비워둔다.
        self._px(bx + 4, by - 6, 2, 10, "#3d2a16")
        self._px(bx + 3, by - 10, 4, 4, "#e8c39e")
        self._px(bx + 7, by - 9, 11, 1, "#a97b4f")      # 낚싯대
        lx, ly = bx + 18, by - 8
        self._px(lx, ly, 1, int((SEA + 8 + bob) - ly), "#7d8590")
        self._px(lx - 1, SEA + 7 + bob, 3, 3, "#f85149")

        # 잡은 물고기가 갑판에 쌓인다. 바다에서 사라진 만큼 여기로 온다.
        # 아래 줄부터 채우고 위로 갈수록 좁아진다 — 쌓인 더미처럼 보이게.
        for i, (dx, dy) in enumerate(_PILE_SLOTS[: s.on_boat]):
            self._px(bx + 22 + dx, by + 3 - dy, 3, 2, FISH_COLORS[i % 4])

        if not s.is_fishing:
            self.canvas.create_rectangle(
                0, 0, W * SCALE, H * SCALE, fill="#000000", stipple="gray50", width=0
            )
            self.canvas.create_text(
                W * SCALE // 2, H * SCALE // 2, text="조업 종료",
                fill="#c9d1d9", font=("Consolas", 11),
            )

    def _tick(self) -> None:
        self.frame += 1
        self._sync_fish()
        self._draw()
        if self.frame % 15 == 0:
            self._apply_text()
        self.root.after(FRAME_MS, self._tick)


def _detach(argv: list[str]) -> int:
    """자기 자신을 백그라운드로 다시 띄우고 셸을 돌려준다.

    데몬화 라이브러리를 쓰지 않는다. 창 하나 띄우는 게 전부라 부모와의 연을
    끊고 표준 입출력만 버리면 끝난다.
    """
    import subprocess

    rest = [a for a in argv if a not in ("-d", "--detach")]
    executable = sys.executable
    options: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "cwd": os.getcwd(),
    }
    if sys.platform == "win32":
        # pythonw 로 띄우면 콘솔 창이 같이 뜨지 않는다.
        windowless = Path(executable).with_name("pythonw.exe")
        if windowless.exists():
            executable = str(windowless)
        options["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        options["start_new_session"] = True

    child = subprocess.Popen([executable, "-m", "ccpet", *rest], **options)
    print(f"백그라운드 실행 중 (PID {child.pid})")
    return 0


USAGE = f"""token fishing {__version__} - Claude 사용량 도트 팝업

  tokenfishing [옵션]

옵션
  -d, --detach            백그라운드로 띄우고 셸을 돌려준다
      --debug             진단 로그를 stderr로 출력한다
      --doctor            사용량 데이터 소스를 진단하고 끝낸다
      --install-statusline
                          Claude Code 상태줄 훅을 등록한다 (정확한 리셋 시각)
  -V, --version           버전을 출력한다
  -h, --help              이 도움말
"""


def main(argv: list[str] | None = None) -> int:
    # 윈도우 콘솔이 cp949라 한글과 기호에서 죽는다. 도움말도 못 읽으면 의미가 없다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    argv = list(sys.argv[1:] if argv is None else argv)

    unknown = [a for a in argv if a.startswith("-") and a not in {
        "-d", "--detach", "--debug", "--doctor", "--install-statusline",
        "-V", "--version", "-h", "--help",
    }]
    if unknown or {"-h", "--help"} & set(argv):
        if unknown:
            print(f"모르는 옵션: {' '.join(unknown)}", file=sys.stderr)
            print(file=sys.stderr)
        print(USAGE, end="")
        return 2 if unknown else 0

    if {"-V", "--version"} & set(argv):
        print(f"token fishing {__version__}")
        return 0

    if "--debug" in argv:
        import ccpet

        ccpet.DEBUG = True

    if "--doctor" in argv:
        from .plan_usage import _doctor

        _doctor()
        return 0

    if "--install-statusline" in argv:
        from .statusline import install

        return install()

    if "-d" in argv or "--detach" in argv:
        return _detach(argv)

    root = tk.Tk()
    Popup(root, build_state())  # 설정은 Popup이 다시 읽어 반영한다
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
