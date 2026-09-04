"""claude-monitor 스냅샷과 항목별 대조.

    py -3.12 -m claude_monitor --once --output json > tests/reference/snapshot.json
    py -3.12 -m ccpet.compare tests/reference/snapshot.json

레퍼런스는 **의존이 아니라 대조군이다.** 저쪽 분석 로직은 읽지도 베끼지도 않는다.
숫자만 맞춰보고, 어긋나면 어느 함정인지 진단한다.

총합만 비교하는 건 이 프로젝트에서 무효다 — 함정 1(과대)과 함정 2(과소)는 방향이
반대라 둘 다 틀려도 총합이 우연히 맞는다. 그래서 항상 네 항목을 따로 본다.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .aggregate import build_windows, burn_rate, collect_entries, current_window

# 레퍼런스 JSON의 필드명 → 우리 Window 속성명
ITEMS = (
    ("input", "input_tokens", "input_tokens"),
    ("output", "output_tokens", "output_tokens"),
    ("cache_w", "cache_creation_input_tokens", "cache_creation_tokens"),
    ("cache_r", "cache_read_input_tokens", "cache_read_tokens"),
)


@dataclass(frozen=True, slots=True)
class Row:
    label: str
    mine: int
    theirs: int

    @property
    def ratio(self) -> float | None:
        if self.theirs == 0:
            return None
        return self.mine / self.theirs


def diagnose(rows: list[Row]) -> list[str]:
    """CLAUDE.md의 오차 해석 표를 코드로. 증상 → 원인."""
    notes: list[str] = []
    ratios = {r.label: r.ratio for r in rows}

    def near(x: float | None, target: float, tol: float) -> bool:
        return x is not None and abs(x - target) <= tol

    if any(r is not None and r >= 2 for r in ratios.values()):
        notes.append("2배 이상 높은 항목 있음 → dedup 누락 (함정 1). "
                     "requestId별로 모으고 있는지 확인")

    out, inp = ratios.get("output"), ratios.get("input")
    if out is not None and inp is not None and out < inp * 0.8:
        notes.append("출력만 유독 낮음 → requestId별 max 미적용 (함정 2). "
                     "서브에이전트 파일의 성장 스냅샷 확인")

    if all(near(r, 1.0, 0.02) for r in ratios.values() if r is not None):
        notes.append("항목별 전부 ±2% 이내. 상쇄가 아니라 진짜로 맞는다")
    elif all(r is not None and 0.9 <= r < 0.98 for r in ratios.values()):
        notes.append("전 항목이 고르게 조금 낮음 → subagents/ 글롭 누락(함정 3)이거나 "
                     "측정 시점 차이")

    if any(r == 0 for r in ratios.values()):
        notes.append("0인 항목 있음 → 경로/필드명 변경 의심")

    return notes


def compare(snapshot_path: Path | str) -> int:
    ref = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))

    local = ref.get("local") or {}
    ref_tokens = local.get("tokens") or {}
    if not ref_tokens:
        print("레퍼런스 스냅샷에 local.tokens가 없다. 스키마가 바뀌었는지 확인할 것.")
        return 2

    # 레퍼런스가 측정한 시각을 그대로 쓴다. 안 그러면 그 사이에 쌓인 토큰이
    # 우리 쪽에만 잡혀서, 알고리즘 차이인지 시차인지 구분이 안 된다.
    now = datetime.fromisoformat(ref["generated_at"])

    entries = [e for e in collect_entries() if e.timestamp <= now]
    windows = build_windows(entries)
    mine = current_window(windows, now)

    print(f"레퍼런스  claude-monitor {ref.get('tool', {}).get('version', '?')}"
          f"  (generated_at {now:%Y-%m-%d %H:%M:%S} UTC)")
    print(f"대조 시점의 우리 엔트리 {len(entries)}개, 윈도우 {len(windows)}개")
    print()

    if mine is None:
        print("우리 쪽 활성 윈도우 없음. 레퍼런스는 활성이라고 한다"
              if local.get("is_active") else "양쪽 다 활성 윈도우 없음")
        if local.get("is_active"):
            return 1

    # --- 윈도우 경계 (여기서 정시 내림 여부가 드러난다) ---
    print("윈도우 경계")
    print(f"  레퍼런스  {local.get('session_start')} ~ {local.get('session_end')}")
    if mine is not None:
        print(f"  우리      {mine.start.isoformat()} ~ {mine.end.isoformat()}")
        ref_start = local.get("session_start")
        if ref_start and datetime.fromisoformat(ref_start) != mine.start:
            print("  ! 시작 시각이 다르다. 레퍼런스는 블록 시작을 정시로 내림하는 것으로 보인다")
    print()

    # --- 항목별 대조 ---
    rows = [
        Row(label, getattr(mine, attr) if mine else 0, int(ref_tokens.get(key) or 0))
        for label, key, attr in ITEMS
    ]

    print(f"{'항목':<10}{'우리':>14}{'레퍼런스':>16}{'비율':>10}{'차이':>14}")
    for r in rows:
        ratio = "  n/a" if r.ratio is None else f"{r.ratio:8.4f}"
        print(f"{r.label:<10}{r.mine:>14,}{r.theirs:>16,}{ratio:>10}{r.mine - r.theirs:>+14,}")

    total_mine = sum(r.mine for r in rows)
    total_theirs = sum(r.theirs for r in rows)
    total_ratio = total_mine / total_theirs if total_theirs else float("nan")
    print(f"{'(총합)':<10}{total_mine:>14,}{total_theirs:>16,}{total_ratio:>10.4f}"
          f"{total_mine - total_theirs:>+14,}")
    print("  총합은 참고용이다. 판단은 위 네 줄로 한다")
    print()

    # --- burn rate (정의가 다를 수 있어 참고용) ---
    ref_burn = local.get("burn_rate_tokens_per_minute")
    if ref_burn and mine is not None:
        print(f"burn rate  우리 {burn_rate(entries, now):,.0f} / "
              f"레퍼런스 {ref_burn:,.0f} 토큰/분")
        print("  정의가 다르다. 우리는 CLAUDE.md대로 '최근 1시간'을 쓰고,")
        print("  레퍼런스는 '윈도우 총량 / 윈도우 경과시간'을 쓴다.")

        # 저쪽 정의를 우리 숫자로 재현해서, 차이가 버그가 아니라 정의 때문임을 증명한다.
        elapsed_min = (now - mine.start).total_seconds() / 60
        if elapsed_min > 0:
            theirs_reproduced = mine.total_tokens / elapsed_min
            gap = abs(theirs_reproduced - ref_burn) / ref_burn
            print(f"  저쪽 정의를 우리 데이터로 재현: {theirs_reproduced:,.0f} "
                  f"(레퍼런스 대비 {gap:.2%} 차이)")
            if gap > 0.01:
                print("  ! 재현이 1% 넘게 어긋난다. 정의 차이가 아니라 진짜 불일치일 수 있다")
        print()

    notes = diagnose(rows)
    print("진단")
    for n in notes or ["특이사항 없음"]:
        print(f"  - {n}")

    return 0 if all(r.ratio is not None and 0.98 <= r.ratio <= 1.02 for r in rows) else 1


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) != 2:
        print(__doc__)
        return 2
    return compare(argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
