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

# 플랜별 5시간 창 조업량(input+output) 근사치. 공식 사용률을 못 받을 때만 쓰인다.
#
# Anthropic은 정확한 토큰 한도를 공개하지 않고, 수요에 따라 달라진다고 밝히고 있다.
# pro 값은 실측으로 잡았다 — 공식 75%인 순간의 조업량 225,478 → 약 300,000.
# max 값들은 공표된 배수(5x / 20x)를 적용한 것이라 pro보다 근거가 약하다.
#
# 이 표는 마지막 수단이다. 공식 수치가 있으면 그게 이기고, 한 번이라도 공식
# 수치를 본 적이 있으면 그때 학습한 값(learned_limit)이 이 표보다 앞선다.
PLAN_CATCH_LIMITS = {
    "pro": 300_000,
    "max5": 1_500_000,
    "max20": 6_000_000,
}

MIN_PCT_TO_LEARN = 10.0
"""이 사용률 아래에서는 한도를 역산하지 않는다.

3%일 때 나눗셈을 하면 작은 오차가 크게 튄다. 어느 정도 찬 뒤에 재는 게 안정적이다."""
PLAN_LABELS = {"auto": "자동", "pro": "Pro", "max5": "Max 5x", "max20": "Max 20x"}
PLANS = tuple(PLAN_LABELS)

DEFAULTS = {"mode": CATCH, "plan": "auto", "learned_limit": None}


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
        limit = saved.get("learned_limit")
        if isinstance(limit, (int, float)) and limit > 0:
            data["learned_limit"] = int(limit)
    return data


def learn_limit(settings: dict, catch: int, used_percentage: float | None) -> bool:
    """공식 사용률을 봤을 때 한도를 역산해 기억한다. 바뀌었으면 True.

    표에 박아둔 근사치보다 이 값이 낫다 — 이 계정에서 실제로 관측된 값이고,
    플랜을 고를 필요도 없다. 나중에 훅이 잠깐 끊겨도 마지막으로 배운 눈금으로
    그릴 수 있다.

    한도는 수요에 따라 움직이므로 마지막 관측으로 계속 덮어쓴다.
    """
    if used_percentage is None or used_percentage < MIN_PCT_TO_LEARN or catch <= 0:
        return False
    limit = int(catch / (used_percentage / 100))
    previous = settings.get("learned_limit")
    if previous and abs(limit - previous) / previous < 0.02:
        return False  # 잔떨림으로 매번 파일을 쓰지 않는다
    settings["learned_limit"] = limit
    return True


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
