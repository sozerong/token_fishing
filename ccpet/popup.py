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

import threading
import tkinter as tk

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


def _mix(a, b, t: float) -> str:
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class Popup:
    def __init__(self, root: tk.Tk, state: GameState) -> None:
        self.root = root
        self.state = state
        self.frame = 0
        self.fish: list[dict] = []
        self._sync_fish()

        root.title("token fishing")
        root.attributes("-topmost", True)
        root.resizable(False, False)
        root.configure(bg="#0d1117")

        self.canvas = tk.Canvas(
            root, width=W * SCALE, height=H * SCALE,
            bg="#0b1020", highlightthickness=0,
        )
        self.canvas.pack()

        self.labels: dict[str, tk.Label] = {}
        for key in ("catch", "tier", "bite", "left", "foot"):
            small = key == "foot"
            lbl = tk.Label(
                root, anchor="w", justify="left",
                bg="#0d1117", fg="#6e7681" if small else "#c9d1d9",
                font=("Consolas", 8 if small else 10, "bold" if key == "catch" else "normal"),
            )
            lbl.pack(fill="x", padx=6)
            self.labels[key] = lbl
        self.labels["catch"].configure(fg="#7ee787", font=("Consolas", 13, "bold"))

        self._apply_text()
        self._start_refresh()
        self._tick()

    # ---- 데이터 ----

    def _start_refresh(self) -> None:
        def loop() -> None:
            while True:
                if self._stop.wait(REFRESH_SEC):
                    return
                try:
                    # 참조 하나를 통째로 갈아끼운다. GIL 덕에 락이 필요 없다.
                    self.state = build_state()
                except Exception:  # noqa: BLE001
                    # 파일이 쓰이는 중이라 읽기가 실패할 수 있다. 다음 주기에 다시 시도한다.
                    pass

        self._stop = threading.Event()
        threading.Thread(target=loop, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _close(self) -> None:
        self._stop.set()
        self.root.destroy()

    def _sync_fish(self) -> None:
        """마리 수가 바뀌었을 때만 물고기를 다시 만든다."""
        n = self.state.fish
        if len(self.fish) == n:
            return
        speed = BITE_SPEED.get(self.state.bite, 0.2)
        self.fish = [
            {
                "x": (i * 47 % (W - 20)) + 6,
                "y": SEA + 10 + (i * 29 % (H - SEA - 20)),
                "dir": 1 if i % 2 else -1,
                "s": speed * (0.7 + (i % 5) * 0.12),
                "c": FISH_COLORS[i % 4],
            }
            for i in range(n)
        ]

    def _apply_text(self) -> None:
        s = self.state
        self.labels["catch"].configure(
            text=f"{s.catch:,} 토큰" if s.is_fishing else "— 조업 종료"
        )
        self.labels["tier"].configure(
            text=f"{s.tier}" + (f"  (물고기 {s.fish_uncapped}마리)" if s.fish_uncapped else "")
        )
        self.labels["bite"].configure(text=f"입질 {s.bite} · {s.bite_per_min:,.0f} 토큰/분")
        self.labels["left"].configure(
            text="리셋까지 —" if s.minutes_left is None
            else f"리셋까지 {s.minutes_left // 60}시간 {s.minutes_left % 60}분"
        )
        prov = " · ".join(f"{k} {v}" for k, v in s.provenance.items())
        self.labels["foot"].configure(text=f"input+output 기준 · {prov or '요청 없음'}")

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
            y = f["y"] + math.sin(t * 0.25 + f["x"] * 0.3) * 1.2
            back = -1 if f["dir"] > 0 else 5
            fork = back + (-1 if f["dir"] > 0 else 1)
            self._px(f["x"], y, 5, 3, f["c"])
            self._px(f["x"] + back, y, 1, 3, f["c"])
            self._px(f["x"] + fork, y - 1, 1, 1, f["c"])
            self._px(f["x"] + fork, y + 3, 1, 1, f["c"])
            self._px(f["x"] + (3 if f["dir"] > 0 else 1), y + 1, 1, 1, "#0d1117")

        bob = math.sin(t * 0.2) * 1.2
        bx, by = 22, SEA - 8 + bob
        self._px(bx, by + 6, 34, 5, "#6b4423")
        self._px(bx + 3, by + 4, 28, 2, "#8b5a2b")
        self._px(bx + 14, by - 6, 2, 10, "#3d2a16")
        self._px(bx + 13, by - 10, 4, 4, "#e8c39e")
        self._px(bx + 17, by - 9, 12, 1, "#a97b4f")
        lx, ly = bx + 29, by - 8
        self._px(lx, ly, 1, int((SEA + 8 + bob) - ly), "#7d8590")
        self._px(lx - 1, SEA + 7 + bob, 3, 3, "#f85149")

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


def main() -> int:
    root = tk.Tk()
    Popup(root, build_state())
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
