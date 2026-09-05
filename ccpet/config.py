"""팝업에서 토글한 선택을 기억한다. 파일 하나, 키 두 개.

    mode           "catch"     쓸수록 화면이 채워진다
                   "depletion" 쓸수록 화면이 비어 간다
    theme          화면 컨셉 키 ("fishing", "village", ...). themes 모듈 참고
    fishing_spot   낚시 테마일 때만 쓰는 배경 키 ("sea", "pier", ...). 다른
                   테마에서는 무시된다 — 낚시로 돌아왔을 때를 위해 기억만 해 둔다.
    pet            --animal 모드에서 고르는 동물 키. animal 모듈 참고
    learned_limit  공식 사용률에서 역산한 이 계정의 5시간 한도
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import animal, themes

CONFIG_PATH = Path.home() / ".claude" / "tokenfishing-config.json"

CATCH = "catch"
DEPLETION = "depletion"
MODES = (CATCH, DEPLETION)

MODE_LABELS = {CATCH: "축적", DEPLETION: "고갈"}

MIN_PCT_TO_LEARN = 10.0
"""이 사용률 아래에서는 한도를 역산하지 않는다.

3%일 때 나눗셈을 하면 작은 오차가 크게 튄다. 어느 정도 찬 뒤에 재는 게 안정적이다."""
DEFAULTS = {
    "mode": CATCH, "theme": themes.DEFAULT,
    "fishing_spot": themes.DEFAULT_SPOT, "pet": animal.DEFAULT,
    "learned_limit": None,
}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    if isinstance(saved, dict):
        if saved.get("mode") in MODES:
            data["mode"] = saved["mode"]
        if saved.get("theme") in themes.THEMES:
            data["theme"] = saved["theme"]
        if saved.get("fishing_spot") in themes.FISHING_SPOTS:
            data["fishing_spot"] = saved["fishing_spot"]
        if saved.get("pet") in animal.PETS:
            data["pet"] = saved["pet"]
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
