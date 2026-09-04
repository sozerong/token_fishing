"""팝업에서 토글한 선택을 기억한다. 파일 하나, 키 두 개.

    mode  "catch"     쓸수록 바다에 물고기가 늘어난다 (잡은 만큼 쌓인다)
          "depletion" 쓸수록 바다에서 물고기가 사라진다 (남은 만큼만 헤엄친다)
    plan  "auto" | "pro" | "max5" | "max20"
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

CONFIG_PATH = Path.home() / ".claude" / "tokenfishing-config.json"

CATCH = "catch"
DEPLETION = "depletion"
MODES = (CATCH, DEPLETION)

MODE_LABELS = {CATCH: "축적", DEPLETION: "고갈"}

# 플랜별 5시간 창 조업량(input+output) 근사치.
# Anthropic은 정확한 토큰 한도를 공개하지 않고 수요에 따라 달라진다. 이 값은
# 상태줄 훅에서 공식 사용률을 못 받을 때만 쓰이는 눈금이며, 정확한 수치가 아니다.
# 훅이 살아 있으면 이 표는 쓰이지 않는다 — 공식 퍼센트가 항상 우선한다.
PLAN_CATCH_LIMITS = {
    "pro": 380_000,
    "max5": 1_900_000,
    "max20": 7_600_000,
}
PLAN_LABELS = {"auto": "자동", "pro": "Pro", "max5": "Max 5x", "max20": "Max 20x"}
PLANS = tuple(PLAN_LABELS)

DEFAULTS = {"mode": CATCH, "plan": "auto"}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    if isinstance(saved, dict):
        if saved.get("mode") in MODES:
            data["mode"] = saved["mode"]
        if saved.get("plan") in PLANS:
            data["plan"] = saved["plan"]
    return data


def save(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONFIG_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, CONFIG_PATH)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def next_in(values: tuple[str, ...], current: str) -> str:
    """토글용. 다음 값으로 돌린다."""
    try:
        return values[(values.index(current) + 1) % len(values)]
    except ValueError:
        return values[0]
