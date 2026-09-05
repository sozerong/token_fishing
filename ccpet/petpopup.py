"""`--animal`로 실행하면 뜨는 반려동물 팝업.

popup.py(Popup)와 데이터 파이프라인은 완전히 같다 — build_state가 주는
GameState 하나를 그대로 받는다. 다른 건 그림뿐이다: 실내 방 하나, 밥그릇,
장난감, 그리고 클릭에 반응하는 동물 한 마리. 그래서 Popup을 상속하지 않고
따로 둔다 — 옥외 풍경(sky/edge/base)과 실내 장면은 그리는 방식이 아예 달라서,
억지로 한 클래스에 넣으면 조건문만 늘어난다.

등급 말은 animal.Pet의 표에서, 숫자는 GameState에서 온다. GameState.tier 는
쓰지 않는다 — 그건 build_state를 부를 때 넘긴 기본 테마(낚시) 말로 이미
굳어 있어서, 여기서는 같은 원리(state._level)를 동물 자신의 표에 다시 적용한다.
"""

from __future__ import annotations

import math
import random
import threading
import tkinter as tk

from . import __version__, animal, config, debug, i18n
from .state import GameState, _level, build_state

SCALE = 2
W, H = animal.W, animal.H
FRAME_MS = 66
PET_SCALE = 2.0
"""동물 스프라이트 확대 배율. animal.py의 그리기 함수는 그대로 두고, 동물의
발밑(pos)을 중심으로 픽셀 사각형을 키워서 그린다."""

BOWL_AT = (10, animal.FLOOR - 2)
TOY_AT = (144, animal.FLOOR + 18)
BOWL_TARGET = (BOWL_AT[0] + 8, BOWL_AT[1] + 6)
TOY_TARGET = (TOY_AT[0] + 3, TOY_AT[1] + 6)

ROAM_MARGIN = 18
"""동물이 돌아다니는 벽. 2배로 키운 몸이 벽/모서리에 잘리지 않을 만큼 안쪽으로."""

STYLE_FACTOR = {
    "walk": lambda t: 1.0,
    "hop": lambda t: 1.0 if (t // 6) % 2 == 0 else 0.0,
    "dash": lambda t: 1.8 if (t // 15) % 3 == 2 else 0.5,
}


class AnimalPopup:
    def __init__(self, root: tk.Tk, state: GameState) -> None:
        self.root = root
        self.state = state
        self.settings = config.load()
        # 창이 자기 언어를 스스로 정한다. main()에만 두면 창을 직접 만드는
        # 경로(테스트·다른 진입점)에서 라벨이 설정과 어긋난다.
        i18n.set_lang(self.settings.get("lang"))
        self.frame = 0

        self.pos = [W / 2, animal.FLOOR + 20]
        self.facing = 1
        self.mood = "idle"
        self.target: tuple[float, float] | None = None
        self.target_kind: str | None = None
        self.busy_until = 0
        self.next_wander = 60

        root.title(self._title())
        root.attributes("-topmost", True)
        root.resizable(False, False)
        root.configure(bg="#0d1117")

        self.canvas = tk.Canvas(
            root, width=W * SCALE, height=H * SCALE,
            bg="#3a3244", highlightthickness=0,
        )
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_click)

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

        bar = tk.Frame(root, bg="#0d1117")
        bar.pack(fill="x", padx=6, pady=(2, 6))

        def button(command):
            b = tk.Button(
                bar, command=command, font=("Consolas", 9),
                bg="#21262d", fg="#c9d1d9", activebackground="#30363d",
                relief="flat", borderwidth=0, padx=6, cursor="hand2",
            )
            b.pack(side="left", fill="x", expand=True, padx=(0, 2))
            return b

        self.pet_btn = button(self._next_pet)
        self.mode_btn = button(self._toggle_mode)
        self._apply_buttons()

        debug(f"start(animal) pet={self.settings['pet']} mode={self.settings['mode']} "
              f"fill={state.fill_source} pct={state.used_percentage}")
        self._apply_text()
        self._start_refresh()
        self._tick()

    def _title(self) -> str:
        s = self.state
        if s.fill_source == "official":
            where = i18n.t({"hook": "공식·훅", "app": "공식·앱"}
                           .get(s.official_source, "공식"))
        else:
            label = i18n.t({"learned": "어림", "none": "?"}.get(s.fill_source, "?"))
            where = i18n.fmt("no_official", label=label)
        return f"token fishing {__version__} · {i18n.t(self.pet.name)} · {where}"

    # ---- 토글 ----

    @property
    def pet(self) -> animal.Pet:
        return animal.get(self.settings.get("pet"))

    def _apply_buttons(self) -> None:
        self.pet_btn.configure(text=i18n.t(self.pet.name))
        self.mode_btn.configure(text=i18n.t(config.MODE_LABELS[self.settings["mode"]]))

    def _next_pet(self) -> None:
        self.settings["pet"] = config.next_in(
            animal.PET_KEYS, self.settings.get("pet", animal.DEFAULT)
        )
        self._commit_settings()

    def _toggle_mode(self) -> None:
        self.settings["mode"] = config.next_in(config.MODES, self.settings["mode"])
        self._commit_settings()

    def _commit_settings(self) -> None:
        config.save(self.settings)
        self.state = build_state(self.settings)
        self.root.title(self._title())
        self._apply_buttons()
        self._apply_text()

    # ---- 데이터 ----

    def _start_refresh(self) -> None:
        def loop() -> None:
            while True:
                if self._stop.wait(10):
                    return
                try:
                    self.state = build_state(self.settings)
                    self.root.after(0, lambda: self.root.title(self._title()))
                    debug(f"fill={self.state.fill_source} pct={self.state.used_percentage}")
                except Exception as e:  # noqa: BLE001
                    debug(f"refresh failed: {type(e).__name__}: {e}")

        self._stop = threading.Event()
        threading.Thread(target=loop, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _close(self) -> None:
        self._stop.set()
        self.root.destroy()

    def _food_ratio(self) -> float:
        """밥그릇이 얼마나 찼나(0~1). fill이 없으면 절대량을 이 동물의 최상위
        등급 기준으로 근사한다 — catch_tiers 마지막 문턱값을 그대로 재사용한다."""
        s = self.state
        if s.fill is not None:
            return max(0.0, min(1.0, s.fill))
        top = self.pet.catch_tiers[-1][0]
        return max(0.0, min(1.0, s.catch / top)) if top else 0.0

    def _words(self) -> tuple[str, str]:
        s, pet = self.state, self.pet
        tier = (
            _level(s.fill, pet.fill_tiers) if s.fill is not None
            else _level(s.catch, pet.catch_tiers)
        )
        bite = _level(s.bite_per_min, pet.activity_tiers)
        return tier, bite

    def _apply_text(self) -> None:
        s, pet = self.state, self.pet
        if not s.is_fishing:
            self.labels["catch"].configure(text=i18n.fmt("idle_line"), fg="#6e7681")
        elif s.fill is None:
            self.labels["catch"].configure(
                text=i18n.fmt("tokens", n=s.catch), fg="#7ee787")
        else:
            mark = "" if s.fill_source == "official" else "~"
            pct = s.fill * 100
            self.labels["catch"].configure(
                text=i18n.fmt("pct_tokens", mark=mark, pct=pct, n=s.catch),
                fg="#f85149" if pct >= 90 else "#d29922" if pct >= 70 else "#7ee787",
            )
        tier, bite = self._words()
        self.labels["tier"].configure(text=i18n.t(tier))
        self.labels["bite"].configure(text=i18n.fmt(
            "activity", act=i18n.t(pet.activity_word), tier=i18n.t(bite),
            action=i18n.t(pet.action_word), n=s.casts,
        ))
        mark = "" if s.pinned else "~"
        self.labels["left"].configure(
            text=i18n.fmt("reset_none") if s.minutes_left is None
            else i18n.fmt("reset", mark=mark,
                          h=s.minutes_left // 60, m=s.minutes_left % 60)
        )
        self.labels["left"].configure(fg="#c9d1d9" if s.pinned else "#d29922")
        self.labels["weekly"].configure(
            text=i18n.fmt("weekly_pct", pct=s.weekly_percentage, n=s.weekly_catch)
            if s.weekly_percentage is not None
            else i18n.fmt("weekly", n=s.weekly_catch)
        )

    # ---- 상호작용 ----

    def _on_click(self, event: tk.Event) -> None:
        vx, vy = event.x / SCALE, event.y / SCALE
        # 동물 자체를 클릭하면 쓰다듬는다 — 반려동물 앱에서 가장 기본적인
        # 상호작용이다. 그 자리로 "걸어가라"는 명령으로 처리하면 이상하다.
        if abs(vx - self.pos[0]) < 8 and abs(vy - self.pos[1]) < 8:
            self.target, self.target_kind = None, None
            self.mood, self.busy_until = "pet", self.frame + 40
            return
        if abs(vx - TOY_TARGET[0]) < 10 and abs(vy - TOY_TARGET[1]) < 10:
            self.target, self.target_kind = TOY_TARGET, "toy"
        elif abs(vx - BOWL_TARGET[0]) < 12 and abs(vy - BOWL_TARGET[1]) < 10:
            self.target, self.target_kind = BOWL_TARGET, "bowl"
        else:
            self.target = (
                max(ROAM_MARGIN, min(W - ROAM_MARGIN, vx)),
                max(animal.FLOOR + 6, min(H - 10, vy)),
            )
            self.target_kind = None
        self.busy_until = 0  # 먹거나 놀던 중이어도 클릭하면 바로 반응한다

    # ---- 그리기 ----

    def _px(self, x: float, y: float, w: int, h: int, color: str) -> None:
        x, y = int(x) * SCALE, int(y) * SCALE
        self.canvas.create_rectangle(
            x, y, x + w * SCALE, y + h * SCALE, fill=color, width=0
        )

    def _px_pet(self, ox: float, oy: float, x: float, y: float, w: int, h: int, color: str) -> None:
        """동물 그리기 전용. (ox, oy) 발밑을 축으로 PET_SCALE배 키워서 찍는다."""
        self._px(
            ox + (x - ox) * PET_SCALE, oy + (y - oy) * PET_SCALE,
            max(1, round(w * PET_SCALE)), max(1, round(h * PET_SCALE)), color,
        )

    def _step_pet(self) -> None:
        t = self.frame
        if t < self.busy_until:
            return  # 먹거나 노는 중 — 제자리에서 포즈만 바뀐다
        if self.target is None:
            if t >= self.next_wander:
                self.target = (
                    random.uniform(ROAM_MARGIN, W - ROAM_MARGIN),
                    random.uniform(animal.FLOOR + 6, H - 10),
                )
                self.target_kind = None
            return
        tx, ty = self.target
        dx, dy = tx - self.pos[0], ty - self.pos[1]
        dist = math.hypot(dx, dy)
        if dist < 2:
            if self.target_kind == "toy":
                self.mood, self.busy_until = "play", t + 70
            elif self.target_kind == "bowl":
                self.mood, self.busy_until = "eat", t + 50
            else:
                self.mood = "idle"
            self.target = None
            self.next_wander = t + random.randint(60, 200)
            return
        self.facing = 1 if dx >= 0 else -1
        self.mood = "walk"
        speed = self.pet.speed * STYLE_FACTOR[self.pet.style](t)
        self.pos[0] += (dx / dist) * speed
        self.pos[1] += (dy / dist) * speed

    def _draw(self) -> None:
        t = self.frame
        self.canvas.delete("all")
        animal.room(self._px, t)
        animal.bowl(self._px, *BOWL_AT, self._food_ratio(), t)
        animal.toy(self._px, *TOY_AT, t)
        px, py = self.pos
        pet_px = lambda x, y, w, h, color: self._px_pet(px, py, x, y, w, h, color)
        self.pet.draw(pet_px, px, py, self.mood, self.facing, t)
        if self.mood == "pet":                                # 쓰다듬는 중 — 하트가 뜬다
            animal.hearts(self._px, px - 2, py - 10, t)

        if not self.state.is_fishing:
            self.canvas.create_rectangle(
                0, 0, W * SCALE, H * SCALE, fill="#000000", stipple="gray50", width=0
            )
            self.canvas.create_text(
                W * SCALE // 2, H * SCALE // 2, text=i18n.fmt("idle"),
                fill="#c9d1d9", font=("Consolas", 11),
            )

    def _tick(self) -> None:
        self.frame += 1
        self._step_pet()
        self._draw()
        if self.frame % 15 == 0:
            self._apply_text()
        self.root.after(FRAME_MS, self._tick)
