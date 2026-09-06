"""항상 위에 뜨는 도트 팝업. 실행하면 바로 뜬다.

    py -3.12 -m tokenfishing

왜 브라우저가 아니라 tkinter인가: Document PiP API는 **사용자 제스처가 필수**라
페이지 로드만으로 창을 띄울 수 없다. 버튼을 한 번 눌러야 한다. "실행하면 짠 하고
뜨는" 팝업이 목표라면 브라우저로는 안 된다. tkinter는 표준 라이브러리고 always-on-top을
지원하니 의존성 0으로 목표가 그대로 달성된다.

HTML 화면(render.py)은 버리지 않는다 — Phase 3에서 MCP App으로 포장할 때 그게 표시
계층이 된다. 지금 당장 필요한 건 이쪽이다.
"""

from __future__ import annotations

import math
import os
import random
import sys
import threading
import tkinter as tk
from pathlib import Path

from . import __version__, config, debug, i18n
from .state import GameState, build_state
from . import themes

SCALE = 2
W, H = themes.W, themes.H   # 가상 도트 해상도. 실제 창은 이것의 SCALE배.
SEA = themes.HORIZON        # 지평선. 테마가 배경을 그리려면 같은 값을 봐야 한다.
REFRESH_SEC = 10
FRAME_MS = 66            # 약 15fps. 도트 화면에 그 이상은 필요 없다.

STALE_MIN = 15
"""공식 수치가 이보다 오래됐으면 제목에 나이를 적는다.

앱 기록이 15분 간격이라 그 안쪽은 정상 지연이다. 그보다 오래됐다는 건 그 기기가
한동안 Claude Code를 안 썼다는 뜻이고, 그때부터 다른 기기와 숫자가 갈린다."""

ACTIVITY_SPEED = (0.10, 0.22, 0.45, 0.85)
"""활동 등급(4단계) → 움직이는 속도. 등급 이름은 테마마다 다르므로 순번으로 찾는다."""


def _mix(a, b, t: float) -> str:
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class Popup:
    def __init__(self, root: tk.Tk, state: GameState) -> None:
        self.root = root
        self.state = state
        self.settings = config.load()
        # 창이 자기 언어를 스스로 정한다. main()에만 두면 창을 직접 만드는
        # 경로(테스트·다른 진입점)에서 라벨이 설정과 어긋난다. 다만 이번 실행에
        # `--ko`를 준 경우엔 그쪽이 이긴다 — 안 그러면 플래그가 창에만 안 먹는다.
        if not i18n.EXPLICIT:
            i18n.set_lang(self.settings.get("lang"))
        self.frame = 0
        self.fish: list[dict] = []
        self._reroll_layout()
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

        def button(command):
            b = tk.Button(
                bar, command=command, font=("Consolas", 9),
                bg="#21262d", fg="#c9d1d9", activebackground="#30363d",
                relief="flat", borderwidth=0, padx=6, cursor="hand2",
            )
            b.pack(side="left", fill="x", expand=True, padx=(0, 2))
            return b

        self.theme_btn = button(self._next_theme)
        self.spot_btn = button(self._next_spot)      # 낚시일 때만 보인다
        self.mode_btn = button(self._toggle_mode)    # 고갈 모드가 있는 테마만
        self._apply_buttons()

        debug(f"start fill={state.fill_source} official={state.official_source} "
              f"pct={state.used_percentage} left={state.minutes_left} "
              f"mode={state.mode} theme={state.theme}")
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
            where = i18n.t({"hook": "공식·훅", "app": "공식·앱"}
                           .get(s.official_source, "공식"))
            # 공식 수치라도 지금 값은 아니다. 그 기기에서 Claude Code를 한동안
            # 안 쓰면 몇 시간 전 값이 그대로 남는다 — 다른 기기와 안 맞아 보이는
            # 이유가 이것이라, 낡았으면 낡았다고 적는다.
            if s.official_age_min is not None and s.official_age_min >= STALE_MIN:
                where += i18n.fmt("age", n=s.official_age_min)
        else:
            # 왜 공식이 아닌지 적는다. "어림"만 뜨면 훅이 없는 건지 앱이 꺼진
            # 건지 알 수가 없어서, 재현 안 되는 화면을 붙들고 시간을 버렸다.
            label = i18n.t({"learned": "어림", "none": "?"}.get(s.fill_source, "?"))
            where = i18n.fmt("no_official", label=label)
        return f"token fishing {__version__} · {where}"

    # ---- 토글 ----

    def _apply_buttons(self) -> None:
        base = themes.get(self.settings.get("theme"))
        self.theme_btn.configure(text=i18n.t(base.name))
        if base.catch_only:
            # 고갈 모드가 말이 안 되는 테마(양봉)에서는 모드 버튼을 감춘다.
            # 고른 모드는 설정에 그대로 남아서 다른 테마로 넘어가면 되살아난다.
            self.mode_btn.pack_forget()
        else:
            self.mode_btn.configure(
                text=i18n.t(config.MODE_LABELS[self.settings["mode"]]))
            self.mode_btn.pack(side="left", fill="x", expand=True, padx=(0, 2))
        if base.key == "fishing":
            spot = themes.get_spot(self.settings.get("fishing_spot"))
            self.spot_btn.configure(text=i18n.t(spot.name))
            self.spot_btn.pack(side="left", fill="x", expand=True, padx=(0, 2), before=self.mode_btn)
        else:
            # 낚시가 아니면 배경 고를 게 없다 — 눌러도 아무 효과 없는 버튼을
            # 남겨두지 않는다.
            self.spot_btn.pack_forget()

    @property
    def theme(self) -> themes.Theme:
        base = themes.get(self.settings.get("theme"))
        return themes.apply_spot(base, self.settings.get("fishing_spot"))

    def _build_state(self) -> GameState:
        """축적 전용 테마에서는 모드를 덮어쓴다. settings를 복사해 고쳐 넘기면
        안 되는 이유는 state.build_state의 주석 참고 — 잠깐 들른 테마 때문에
        사용자가 골라 둔 고갈 모드가 설정 파일에서 지워진다."""
        return build_state(
            self.settings,
            mode=config.CATCH if self.theme.catch_only else None,
        )

    def _reroll_layout(self) -> None:
        """고정물 x를 새로 뽑는다. 배경이 바뀔 때만 부른다 — 매 프레임 부르면
        고정물이 아니라 흔들리는 것이 된다. 범위는 테마가 정한다 (차박·캠핑은
        땅이 왼쪽뿐이라 좁다)."""
        self.base_x = random.uniform(*self.theme.base_x_range)

    def _next_theme(self) -> None:
        self.settings["theme"] = config.next_in(
            themes.THEME_KEYS, self.settings.get("theme", themes.DEFAULT)
        )
        self._reroll_layout()
        self._commit_settings()

    def _next_spot(self) -> None:
        self.settings["fishing_spot"] = config.next_in(
            themes.FISHING_SPOT_KEYS, self.settings.get("fishing_spot", themes.DEFAULT_SPOT)
        )
        self._reroll_layout()
        self._commit_settings()

    def _toggle_mode(self) -> None:
        self.settings["mode"] = config.next_in(config.MODES, self.settings["mode"])
        self._commit_settings()

    def _commit_settings(self) -> None:
        config.save(self.settings)
        self.state = self._build_state()
        # 테마가 바뀌면 색과 속도가 통째로 달라진다. 남겨두면 이전 테마의
        # 것들이 새 화면에 섞여 돌아다닌다.
        self.fish.clear()
        self._sync_fish()
        self.root.title(self._title())
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
                    self.state = self._build_state()
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

    def _speed(self) -> float:
        """활동 등급 → 속도. 등급 이름은 테마마다 다르므로 표에서 순번을 찾는다."""
        names = [n for _, n in self.theme.activity_tiers]
        index = names.index(self.state.bite) if self.state.bite in names else 1
        return ACTIVITY_SPEED[index]

    def _unit_band(self) -> tuple[float, float]:
        """돌아다니는 것들이 실제로 쓸 수 있는 y 구간.

        더미가 화면에 있는 동안에는 그 자리를 비켜 준다 — 안팎이 확실해야
        동물이 울타리를 통과하거나 주민이 집을 뚫고 서 있는 것처럼 안 보인다.

        더미가 위에 있는 테마(마을의 집)와 아래에 있는 테마(목장의 우리, 정원의
        화단)가 둘 다 있어서, 남는 쪽으로 비켜 준다.
        """
        look = self.theme
        top, bottom = look.unit_band
        if not look.pile_band or self.state.on_boat <= 0:
            return top, bottom

        keep_top, keep_bottom = look.pile_band
        margin = 6                                   # 스프라이트가 y 위아래로 뻗는 만큼
        room_above = (keep_top - margin) - top
        room_below = bottom - (keep_bottom + margin)
        if room_below >= room_above:
            top = max(top, keep_bottom + margin)     # 더미 아래로 내려보낸다
        else:
            bottom = min(bottom, keep_top - margin)  # 더미 위로 올려보낸다
        return top, max(top + 4, bottom)

    def _new_fish(self) -> dict:
        look = self.theme
        top, bottom = self._unit_band()
        if look.unit_lanes:
            # 차선. 구간을 N등분해 그 위에서만 다니게 한다 — 아무 y나 고르면
            # 차들이 도로를 벗어나 대각선으로 떠다니는 것처럼 보인다.
            lane = random.randrange(look.unit_lanes)
            y = top + (bottom - top) * (lane + 0.5) / look.unit_lanes
            # 방향도 차선이 정한다 — 중앙선을 기준으로 왼쪽/오른쪽이 각자 한
            # 방향으로만 다녀야 도로처럼 보인다. 무작위면 서로 마주 보고 가다
            # 서다 하는 것처럼 어색해 보였다.
            direction = 1 if lane % 2 == 0 else -1
        else:
            y = random.uniform(top, bottom)
            direction = random.choice((-1, 1))
        x_lo, x_hi = look.unit_x_range
        return {
            "x": random.uniform(x_lo, x_hi),
            "y": y,
            "dir": direction,
            # 심겨 있는 테마(정원)는 가로로 움직이지 않는다. 흔들림만 남는다.
            "s": self._speed() * random.uniform(0.6, 1.4) if look.unit_drifts else 0.0,
            "c": random.choice(look.unit_colors),
            "phase": random.uniform(0, 6.28),      # 위아래 흔들림이 겹치지 않게
        }

    def _sync_fish(self) -> None:
        """개수를 맞춘다. 늘어난 만큼만 새로 넣고 기존 것들은 그대로 움직인다."""
        n = self.state.fish
        while len(self.fish) > n:
            self.fish.pop()
        while len(self.fish) < n:
            self.fish.append(self._new_fish())

    def _apply_text(self) -> None:
        s = self.state
        if not s.is_fishing:
            self.labels["catch"].configure(text=i18n.fmt("closed_line"), fg="#6e7681")
        elif s.fill is None:
            # 사용률을 모른다. 퍼센트를 지어내지 않고 절대량만 보여준다.
            self.labels["catch"].configure(
                text=i18n.fmt("tokens", n=s.catch), fg="#7ee787")
        else:
            # ~ 는 플랜 눈금으로 어림한 값이라는 표시. 공식 수치면 안 붙는다.
            mark = "" if s.fill_source == "official" else "~"
            pct = s.fill * 100
            self.labels["catch"].configure(
                text=i18n.fmt("pct_tokens", mark=mark, pct=pct, n=s.catch),
                fg="#f85149" if pct >= 90 else "#d29922" if pct >= 70 else "#7ee787",
            )
        # 마리 수는 화면에 그려져 있다. 숫자로 또 적지 않는다.
        self.labels["tier"].configure(text=i18n.t(s.tier))
        look = self.theme
        self.labels["bite"].configure(text=i18n.fmt(
            "activity", act=i18n.t(look.activity_word), tier=i18n.t(s.bite),
            action=i18n.t(look.action_word), n=s.casts,
        ))
        # 추정값을 확실한 척 보여주지 않는다. ~ 가 붙어 있으면 틀릴 수 있다는 뜻.
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

    # ---- 그리기 ----

    def _px(self, x: float, y: float, w: int, h: int, color: str) -> None:
        x, y = int(x) * SCALE, int(y) * SCALE
        self.canvas.create_rectangle(
            x, y, x + w * SCALE, y + h * SCALE, fill=color, width=0
        )

    def _draw(self) -> None:
        """뼈대는 모든 테마가 같다. 색과 스프라이트만 테마에서 가져온다."""
        s, t, look = self.state, self.frame, self.theme
        self.canvas.delete("all")
        d = s.daylight if s.is_fishing else 0.0

        # 하늘: 바탕색만 여기서 칠하고, 그 위는 테마가 그린다.
        # 해가 뜨는 곳도 있고 별이 뜨거나 암반 천장이 덮인 곳도 있다.
        self._px(0, 0, W, SEA, _mix(*look.sky, d))
        look.sky_decor(self._px, look, d, t)

        # 바닥: 마찬가지로 바탕색 위에 테마가 결을 얹는다 (파도·풀·자갈·차선).
        self._px(0, SEA, W, H - SEA, _mix(*look.ground, d))
        look.edge(self._px, look, d, t)

        # 돌아다니는 것들. 구간이 좁아졌으면(고갈 모드에서 울타리가 생겼으면)
        # 이미 자리 잡은 것들도 밖으로 밀어낸다.
        band_top, band_bottom = self._unit_band()
        for f in self.fish:
            f["y"] = min(max(f["y"], band_top), band_bottom)
            f["x"] += f["dir"] * f["s"]
            if look.unit_lanes:
                # 차선은 방향이 고정이라 튕기면 안 된다 — 반대편에서 다시 들어온다.
                if f["x"] < -8:
                    f["x"] = W + 6
                elif f["x"] > W + 8:
                    f["x"] = -6
            else:
                x_lo, x_hi = look.unit_x_range
                if f["x"] < x_lo:
                    f["x"], f["dir"] = x_lo, 1
                if f["x"] > x_hi:
                    f["x"], f["dir"] = x_hi, -1
            # 차선을 지키는 차, 벽에 박힌 광석은 위아래로도 흔들면 안 된다.
            y = f["y"] + (math.sin(t * 0.25 + f["phase"]) * 1.2 if look.unit_bobs else 0)
            look.sprite(self._px, f["x"], y, f["c"], f["dir"], t)

        # 마리 수와 무관한 배경 연출 (광차, 나비 ...). 대부분의 테마는 아무것도 안 그린다.
        look.ambient(self._px, look, d, t)

        # 고정물. 살짝 흔들려야 정지 화면으로 안 보인다.
        # x는 테마가 바뀔 때마다 새로 뽑는다(self.base_x) — 매번 같은 자리에
        # 박혀 있으면 배경이 바뀌어도 화면 구도가 똑같아 보인다. ground_sink는
        # 땅에 서는 고정물(집·헛간·타워 ...)을 경계선보다 살짝 더 내려 앉힌다 —
        # 안 그러면 경계선에 걸쳐 떠 보인다. 물 위에 뜨는 배·로켓은 0이라 그대로.
        # 흔들리는 건 물 위에 뜬 것(배)뿐이다. 땅에 선 집·타워·차·텐트가
        # 흔들리면 위로 떴을 때 밑동이 지평선 위로 올라가 공중에 뜬 것처럼 보인다.
        bob = math.sin(t * 0.2) * 1.2 if look.base_bobs else 0
        bx, by = self.base_x, SEA - 6 + look.ground_sink + bob
        look.base(self._px, bx, by, t)

        # 모아 둔 것. 고갈 모드에서 화면에서 사라진 만큼이 여기로 온다(축적
        # 모드는 state.py가 애초에 0으로 둔다). 테마마다 모으는 방식이 다르다
        # (쌓기/줄서기/울타리/불꽃/건물 창/카트/그물/호수) — 오프셋은 각
        # pile 함수가 고정물 폭에 맞춰 알아서 잡으므로 여기선 기준점만 넘긴다.
        look.pile(self._px, look, bx, by + 4, s.on_boat, t)

        if not s.is_fishing:
            self.canvas.create_rectangle(
                0, 0, W * SCALE, H * SCALE, fill="#000000", stipple="gray50", width=0
            )
            self.canvas.create_text(
                W * SCALE // 2, H * SCALE // 2, text=i18n.fmt("closed"),
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

    child = subprocess.Popen([executable, "-m", "tokenfishing", *rest], **options)
    print(i18n.pick(f"백그라운드 실행 중 (PID {child.pid})",
                     f"running in the background (PID {child.pid})"))
    return 0


USAGE_KO = f"""token fishing {__version__} - Claude 사용량 도트 팝업

  tokenfishing [옵션]

옵션
  -d, --detach            백그라운드로 띄우고 셸을 돌려준다
      --ko, --en          이번 실행에 쓸 언어. 기본은 영어
      --lang ko|en        기본 언어를 바꾼다. 설정에 기억한다
      --debug             진단 로그를 stderr로 출력한다
      --doctor            사용량 데이터 소스를 진단하고 끝낸다
      --install-statusline
                          Claude Code 상태줄 훅을 등록한다 (정확한 리셋 시각)
      --uninstall-statusline
                          등록한 상태줄 훅과 남은 설정 파일을 지운다
  -V, --version           버전을 출력한다
  -h, --help              이 도움말
"""

USAGE_EN = f"""token fishing {__version__} - a pixel window for your Claude Code usage

  tokenfishing [options]

Options
  -d, --detach            run in the background and hand the shell back
      --ko, --en          language for this run. English by default
      --lang ko|en        change the default language and remember it
      --debug             print diagnostics to stderr
      --doctor            diagnose the usage data sources and exit
      --install-statusline
                          register the Claude Code statusline hook
                          (needed for an exact reset time)
      --uninstall-statusline
                          remove the hook and the files this tool created
  -V, --version           print the version
  -h, --help              this help
"""


def usage() -> str:
    return USAGE_KO if i18n.LANG == "ko" else USAGE_EN


def main(argv: list[str] | None = None) -> int:
    # 윈도우 콘솔이 cp949라 한글과 기호에서 죽는다. 도움말도 못 읽으면 의미가 없다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    argv = list(sys.argv[1:] if argv is None else argv)

    # 도움말도 고른 언어로 나와야 하므로 여기서 먼저 정한다. 언어 인자는
    # i18n.init이 걷어내므로 아래 "모르는 옵션" 검사에 걸리지 않는다.
    try:
        argv = i18n.init(argv)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2

    unknown = [a for a in argv if a.startswith("-") and a not in {
        "-d", "--detach", "--debug", "--doctor",
        "--install-statusline", "--uninstall-statusline",
        "-V", "--version", "-h", "--help",
    }]
    if unknown or {"-h", "--help"} & set(argv):
        if unknown:
            joined = " ".join(unknown)
            print(i18n.pick(f"모르는 옵션: {joined}",
                             f"unknown option: {joined}"), file=sys.stderr)
            print(file=sys.stderr)
        print(usage(), end="")
        return 2 if unknown else 0

    if {"-V", "--version"} & set(argv):
        print(f"token fishing {__version__}")
        return 0

    if "--debug" in argv:
        import tokenfishing

        tokenfishing.DEBUG = True

    if "--doctor" in argv:
        from .plan_usage import _doctor

        _doctor()
        return 0

    if "--install-statusline" in argv:
        from .statusline import install

        return install()

    if "--uninstall-statusline" in argv:
        from .statusline import uninstall

        return uninstall()

    if "-d" in argv or "--detach" in argv:
        return _detach(argv)

    root = tk.Tk()
    Popup(root, build_state())  # 설정은 Popup이 다시 읽어 반영한다
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
