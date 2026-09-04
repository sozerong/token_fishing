"""GameState → 자체 완결 HTML 한 파일. 더블클릭으로 열리고 PiP 창으로 띄운다.

    py -3.12 -m ccpet.render            생성하고 브라우저로 연다
    py -3.12 -m ccpet.render out.html   경로 지정

PiP는 브라우저의 Document Picture-in-Picture API를 쓴다. MCP 호스트 없이도 항상-위
작은 창이 된다. Phase 3에서 MCP App으로 포장할 때 이 화면을 그대로 재사용한다.

숫자는 생성 시점에 박힌다(정직하게 시각을 찍어둔다). 움직이는 건 물결·해·물고기뿐이고
수치를 지어내지 않는다. 실시간이 필요하면 stdlib http.server로 /state.json을 물려주면
되는데, 그건 필요해진 다음에 붙인다.
"""

from __future__ import annotations

import json
import sys
import webbrowser
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .aggregate import (
    build_windows,
    collect_entries,
    current_window,
    snapshot,
    weekly_totals,
)
from . import config
from .state import GameState, to_game_state

DEFAULT_OUT = Path("tokenfishing.html")


def build_state(settings: dict | None = None) -> GameState:
    settings = settings or config.load()
    entries = collect_entries()
    now = datetime.now(timezone.utc)
    snap = snapshot(entries, now)

    window = current_window(build_windows(entries), now)
    in_window = (
        [e for e in entries if window and window.start <= e.timestamp < window.end]
        if window
        else []
    )
    prov = dict(Counter(e.provenance for e in in_window))
    return to_game_state(
        snap,
        prov,
        weekly_catch=weekly_totals(entries, now).catch,
        mode=settings["mode"],
        plan=settings["plan"],
    )


def render(state: GameState, generated_at: datetime) -> str:
    payload = {
        "isFishing": state.is_fishing,
        "catch": state.catch,
        "fish": state.fish,
        "fishUncapped": state.fish_uncapped,
        "tier": state.tier,
        "bite": state.bite,
        "bitePerMin": state.bite_per_min,
        "minutesLeft": state.minutes_left,
        "daylight": state.daylight,
        "weeklyCatch": state.weekly_catch,
        "pinned": state.pinned,
        "tokens": state.tokens,
        "provenance": state.provenance,
        "generatedAt": generated_at.astimezone().strftime("%Y-%m-%d %H:%M"),
    }
    return _HTML.replace("__STATE__", json.dumps(payload, ensure_ascii=False))


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    out = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    state = build_state()
    out.write_text(render(state, datetime.now(timezone.utc)), encoding="utf-8")

    print(f"{out.resolve()}")
    if state.is_fishing:
        print(f"조업량 {state.catch:,}토큰 · {state.tier} · 입질 {state.bite} "
              f"· 남은 시간 {state.minutes_left}분")
    else:
        print("조업 종료 (활성 윈도우 없음)")
    webbrowser.open(out.resolve().as_uri())
    return 0


_HTML = """<!doctype html>
<meta charset="utf-8">
<title>token fishing</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; background:#0d1117; color:#c9d1d9;
         font:12px/1.5 "Consolas","D2Coding",monospace; }
  #app { max-width:520px; margin:0 auto; padding:12px; }
  canvas { width:100%; image-rendering:pixelated; display:block;
           border:2px solid #30363d; background:#0b1020; }
  .row { display:flex; justify-content:space-between; gap:8px; padding:2px 0; }
  .k { color:#8b949e; }
  .v { color:#e6edf3; }
  .big { font-size:18px; color:#7ee787; }
  button { font:inherit; margin-top:8px; width:100%; padding:6px;
           background:#21262d; color:#c9d1d9; border:1px solid #30363d;
           border-radius:4px; cursor:pointer; }
  button:hover { background:#30363d; }
  .foot { color:#6e7681; font-size:11px; margin-top:6px; }
</style>
<div id="app">
  <div id="screen">
    <canvas id="c" width="180" height="120"></canvas>
    <div class="row"><span class="k">조업량</span><span class="v big" id="catch"></span></div>
    <div class="row"><span class="k">등급</span><span class="v" id="tier"></span></div>
    <div class="row"><span class="k">입질</span><span class="v" id="bite"></span></div>
    <div class="row"><span class="k">리셋까지</span><span class="v" id="left"></span></div>
    <div class="foot" id="foot"></div>
  </div>
  <button id="pip">PiP 창으로 띄우기</button>
</div>
<script>
const S = __STATE__;

// ---- 수치 표시 ----
const $ = id => document.getElementById(id);
$("catch").textContent = S.isFishing ? S.catch.toLocaleString() + " 토큰" : "—";
$("tier").textContent  = S.tier + (S.fishUncapped ? `  (물고기 ${S.fishUncapped}마리)` : "");
$("bite").textContent  = `${S.bite} · ${Math.round(S.bitePerMin).toLocaleString()} 토큰/분`;
$("left").textContent  = S.minutesLeft === null ? "조업 종료"
  : `${S.pinned ? "" : "~"}${Math.floor(S.minutesLeft/60)}시간 ${S.minutesLeft%60}분`;
if (!S.pinned) $("left").style.color = "#d29922";
const prov = Object.entries(S.provenance).map(([k,v]) => `${k} ${v}`).join(" · ");
$("foot").textContent = `${S.generatedAt} 기준 · ${S.pinned ? "공식값 고정" : "추정 (웹/모바일 사용은 안 보임)"} · ${prov || "요청 없음"}`;

// ---- 도트 화면 ----
const cv = $("c"), g = cv.getContext("2d");
g.imageSmoothingEnabled = false;
const W = cv.width, H = cv.height, SEA = 62;

const mix = (a,b,t) => a.map((v,i) => Math.round(v + (b[i]-v)*t));
const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;
const px = (x,y,w,h,c) => { g.fillStyle = c; g.fillRect(x|0,y|0,w,h); };

// daylight 1 = 방금 시작, 0 = 리셋 직전
const d = S.isFishing ? S.daylight : 0;
const DUSK = [26,26,58], DAY = [92,160,214];
const SEA_DUSK = [10,18,44], SEA_DAY = [30,90,140];

// 입질이 셀수록 물고기가 빨리 헤엄친다. 데이터가 움직임에 연결된다.
const speed = {"잠잠":0.10,"잔잔":0.22,"활발":0.45,"폭주":0.85}[S.bite] ?? 0.2;

const fish = Array.from({length: S.fish}, (_, i) => ({
  x: (i * 47 % (W - 20)) + 6,
  y: SEA + 10 + (i * 29 % (H - SEA - 20)),
  dir: i % 2 ? 1 : -1,
  s: speed * (0.7 + (i % 5) * 0.12),
  c: ["#e3a447","#d96f4a","#7ee787","#79c0ff"][i % 4],
}));

function draw(t) {
  // 하늘
  px(0,0,W,SEA, rgb(mix(DUSK, DAY, d)));
  // 해 — 남은 시간이 많을수록 높다
  const sx = 26 + (1-d) * (W-60), sy = 8 + (1-d) * (SEA-22);
  px(sx, sy, 11, 11, d > 0.35 ? "#ffd76e" : "#ff9a5a");
  px(sx+2, sy-1, 7, 13, d > 0.35 ? "#ffd76e" : "#ff9a5a");

  // 바다
  px(0,SEA,W,H-SEA, rgb(mix(SEA_DUSK, SEA_DAY, d)));

  // 물결
  for (let x = 0; x < W; x++) {
    const y = SEA + Math.sin((x + t*0.03) * 0.18) * 1.6;
    px(x, y, 1, 2, rgb(mix([255,255,255], mix(SEA_DUSK,SEA_DAY,d), 0.55)));
  }

  // 물고기
  for (const f of fish) {
    f.x += f.dir * f.s;
    if (f.x < 2) { f.x = 2; f.dir = 1; }
    if (f.x > W-10) { f.x = W-10; f.dir = -1; }
    const y = f.y + Math.sin((t*0.004) + f.x*0.3) * 1.2;
    const back = f.dir > 0 ? -1 : 5;   // 꼬리가 붙는 쪽
    px(f.x, y, 5, 3, f.c);                        // 몸통
    px(f.x + back, y, 1, 3, f.c);                 // 꼬리 뿌리
    px(f.x + back + (f.dir>0?-1:1), y-1, 1, 1, f.c); // 꼬리 위 갈래
    px(f.x + back + (f.dir>0?-1:1), y+3, 1, 1, f.c); // 꼬리 아래 갈래
    px(f.x + (f.dir>0 ? 3 : 1), y+1, 1, 1, "#0d1117"); // 눈
  }

  // 배 + 낚싯대
  const bob = Math.sin(t*0.003) * 1.2;
  const bx = 22, by = SEA - 8 + bob;
  px(bx, by+6, 34, 5, "#6b4423");
  px(bx+3, by+4, 28, 2, "#8b5a2b");
  px(bx+14, by-6, 2, 10, "#3d2a16");            // 사람 몸
  px(bx+13, by-10, 4, 4, "#e8c39e");            // 머리
  px(bx+17, by-9, 12, 1, "#a97b4f");            // 낚싯대
  const lx = bx+29, ly = by-8;
  px(lx, ly, 1, (SEA + 8 + bob) - ly, "#7d8590"); // 낚싯줄
  px(lx-1, SEA + 7 + bob, 3, 3, "#f85149");       // 찌

  if (!S.isFishing) {
    g.fillStyle = "rgba(0,0,0,0.55)"; g.fillRect(0,0,W,H);
    g.fillStyle = "#c9d1d9"; g.font = "10px monospace";
    g.fillText("조업 종료", W/2 - 24, H/2);
  }
  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);

// ---- PiP ----
const btn = $("pip");
if (!("documentPictureInPicture" in window)) {
  btn.textContent = "이 브라우저는 PiP 미지원 (Chrome/Edge에서 열어라)";
  btn.disabled = true;
} else {
  btn.onclick = async () => {
    const pip = await documentPictureInPicture.requestWindow({width: 320, height: 300});
    for (const s of document.styleSheets) {
      const css = [...s.cssRules].map(r => r.cssText).join("");
      const el = pip.document.createElement("style");
      el.textContent = css;
      pip.document.head.appendChild(el);
    }
    pip.document.body.append($("screen"));
    btn.textContent = "PiP 창에 표시 중";
    btn.disabled = true;
    pip.addEventListener("pagehide", () => {
      $("app").prepend($("screen"));
      btn.textContent = "PiP 창으로 띄우기";
      btn.disabled = false;
    });
  };
}
</script>
"""


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
