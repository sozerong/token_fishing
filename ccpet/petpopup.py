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
PET_SCALE = 1.4
"""동물 스프라이트 확대 배율. animal.py의 그리기 함수는 그대로 두고, 동물의
기준점(pos)을 축으로 픽셀 사각형을 키워서 그린다.

스프라이트 자체가 커진 뒤로는 배율이 낮아도 화면에서 더 크다. 배율만 올려
키우면 픽셀 덩어리만 커지고 형태는 그대로다 — 크기는 여기서, 형태는
animal.py에서 늘린다."""

BOWL_AT = (24, animal.FLOOR + 2)
TOY_AT = (142, animal.FLOOR + 16)
BOWL_TARGET = (BOWL_AT[0] + 11, BOWL_AT[1] + 6)
TOY_TARGET = (TOY_AT[0] - 13, TOY_AT[1] + 6)
"""걸어가서 설 자리. 기준점이 아니라 **머리**가 그릇/공에 닿아야 한다.

밥그릇은 오른쪽에서 다가가므로(왼쪽을 보게 된다) 머리가 기준점에 오고, 장난감은
왼쪽에서 다가가므로 머리가 기준점보다 한 몸 앞에 온다 — 그만큼 미리 물러 세운다.
둘 다 ROAM_MARGIN 안쪽이라 모서리에서 잘리지도 않는다."""

MIRROR_AXIS = 8
"""좌우 반전의 축(기준점에서 오른쪽으로). 스프라이트 한가운데다.

기준점 자체를 축으로 뒤집으면 왼쪽을 볼 때 몸 전체가 기준점 왼쪽으로 넘어가서,
밥그릇으로 걸어가도 머리가 그릇에서 한참 떨어진 데 가 있다."""

ROAM_MARGIN = 34
"""동물이 돌아다니는 좌우 벽. 키운 몸(기준점에서 오른쪽으로 최대 23px × 배율)이
모서리에 잘리지 않을 만큼 안쪽으로."""

ROAM_TOP, ROAM_BOTTOM = animal.FLOOR - 4, H - 28
"""돌아다니는 세로 구간. 기준점은 몸통 왼쪽 위라 발은 여기서 한참 아래에 찍힌다 —
위쪽은 걸레받이보다 조금 높아도 발이 바닥에 놓이고(멀리 있는 것처럼 보인다),
아래쪽은 발이 창밖으로 나가지 않을 만큼 띄운다."""

TOUCH = 16
"""동물을 클릭한 것으로 칠 반경. 몸이 커진 만큼 같이 넓혔다."""

STYLE_FACTOR = {
    "walk": lambda t: 1.0,
    "hop": lambda t: 1.0 if (t // 4) % 2 == 0 else 0.0,      # 깡충 - 멈춤 - 깡충
    "dash": lambda t: 1.8 if (t // 12) % 3 == 2 else 0.5,
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

        self.pos = [W / 2, (ROAM_TOP + ROAM_BOTTOM) / 2]
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

        # 버튼은 동물 고르기 하나뿐이다. 이 화면에는 고갈 모드가 없다 —
        # 밥그릇이 차는 것이 곧 사용량이라, 거꾸로 비워지면 은유가 뒤집힌다.
        self.pet_btn = button(self._next_pet)
        self._apply_buttons()

        debug(f"start(animal) pet={self.settings['pet']} "
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

    def _next_pet(self) -> None:
        self.settings["pet"] = config.next_in(
            animal.PET_KEYS, self.settings.get("pet", animal.DEFAULT)
        )
        self._commit_settings()

    def _build_state(self) -> GameState:
        """축적 모드로 고정한다. settings를 복사해 고치지 않는 이유는
        state.build_state의 주석 참고 — 여기서 정한 모드가 설정 파일에
        눌러앉으면 보통 화면의 고갈 모드가 조용히 풀린다."""
        return build_state(self.settings, mode=config.CATCH)

    def _commit_settings(self) -> None:
        config.save(self.settings)
        self.state = self._build_state()
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
                    self.state = self._build_state()
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
        if abs(vx - self.pos[0]) < TOUCH and abs(vy - self.pos[1]) < TOUCH:
            self.target, self.target_kind = None, None
            self.mood, self.busy_until = "pet", self.frame + 40
            return
        if abs(vx - TOY_TARGET[0]) < 12 and abs(vy - TOY_TARGET[1]) < 12:
            self.target, self.target_kind = TOY_TARGET, "toy"
        elif abs(vx - BOWL_TARGET[0]) < 14 and abs(vy - BOWL_TARGET[1]) < 12:
            self.target, self.target_kind = BOWL_TARGET, "bowl"
        else:
            self.target = (
                max(ROAM_MARGIN, min(W - ROAM_MARGIN, vx)),
                max(ROAM_TOP, min(ROAM_BOTTOM, vy)),
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
        """동물 그리기 전용. (ox, oy) 기준점을 축으로 PET_SCALE배 키워서 찍는다."""
        self._px(
            ox + (x - ox) * PET_SCALE, oy + (y - oy) * PET_SCALE,
            max(1, round(w * PET_SCALE)), max(1, round(h * PET_SCALE)), color,
        )

    def _pet_px(self):
        """이번 프레임의 동물용 px. 확대에 좌우 반전까지 얹어서 돌려준다.

        animal.py는 오른쪽만 보고 그린다 — 왼쪽을 볼 때 여기서 기준점을 축으로
        x를 뒤집는다. 좌우 두 벌을 손으로 그리면 한쪽만 고치는 실수가 난다."""
        ox, oy = self.pos
        if self.facing > 0:
            return lambda x, y, w, h, c: self._px_pet(ox, oy, x, y, w, h, c)
        axis = ox + MIRROR_AXIS
        return lambda x, y, w, h, c: self._px_pet(ox, oy, 2 * axis - x - w, y, w, h, c)

    def _step_pet(self) -> None:
        t = self.frame
        if t < self.busy_until:
            return  # 먹거나 노는 중 — 제자리에서 포즈만 바뀐다
        if self.target is None:
            if t >= self.next_wander:
                self.target = (
                    random.uniform(ROAM_MARGIN, W - ROAM_MARGIN),
                    random.uniform(ROAM_TOP, ROAM_BOTTOM),
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
            self.next_wander = t + random.randint(25, 90)     # 한자리에 오래 서 있지 않는다
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
        self.pet.draw(self._pet_px(), px, py, self.mood, t)
        if self.mood == "pet":                                # 쓰다듬는 중 — 하트가 뜬다
            animal.hearts(self._px, px + 4, py - 16, t)

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
