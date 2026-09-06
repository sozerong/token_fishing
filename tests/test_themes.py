"""화면 컨셉. 테마는 말과 그림만 바꾸고 숫자는 건드리지 않는다.

pytest 없이도 돌아간다:  py -3.12 tests/test_themes.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccpet import themes  # noqa: E402
from ccpet.aggregate import Snapshot, Window  # noqa: E402
from ccpet.state import MAX_FISH_DRAWN, to_game_state  # noqa: E402

# 화면 크기는 themes 가 들고 있다. 팝업이 그걸 임포트해 쓴다.
W, H, SEA = themes.W, themes.H, themes.HORIZON


def snap(catch: int = 60_000, pct: float | None = 40.0) -> Snapshot:
    now = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)
    window = Window(now - timedelta(hours=1), 12, 100, catch - 100, 5, 5)
    return Snapshot(window, 3_000.0, now, used_percentage=pct)


def record(theme: themes.Theme) -> list[tuple]:
    """한 화면을 통째로 그려서 찍힌 도트를 모은다. 배경 두 겹까지 포함한다."""
    dots: list[tuple] = []

    def px(x, y, w, h, color):
        dots.append((x, y, w, h, color))

    for daylight in (1.0, 0.5, 0.0):        # 대낮 · 오후 · 리셋 직전
        for frame in (0, 37, 120):
            theme.sky_decor(px, theme, daylight, frame)
            theme.edge(px, theme, daylight, frame)
    top, _ = theme.unit_band
    for frame in (0, 37, 120):
        for direction in (1, -1):
            theme.sprite(px, W / 2, top + 6, theme.unit_colors[0], direction, frame)
        theme.base(px, 16, SEA - 8, frame)
        theme.ambient(px, theme, 0.7, frame)
        theme.pile(px, theme, 40, SEA, 12, frame)
    return dots


def test_every_theme_is_complete():
    assert len(themes.THEMES) == 8, tuple(themes.THEMES)
    for key, theme in themes.THEMES.items():
        assert theme.key == key
        assert theme.name and theme.unit and theme.activity_word and theme.action_word
        assert len(theme.unit_colors) >= 4, key
        assert record(theme), f"{key}: 아무것도 안 그린다"


def test_tier_boundaries_are_identical_across_themes():
    """이름만 다르고 등급이 바뀌는 지점은 같아야 한다.

    경계까지 테마마다 다르면 같은 사용량을 두고 화면이 서로 다른 말을 하게 된다.
    테마는 은유일 뿐 숫자의 뜻을 바꾸는 장치가 아니다.
    """
    reference = themes.FISHING
    for key, theme in themes.THEMES.items():
        for name, table in (
            ("fill", "fill_tiers"), ("catch", "catch_tiers"), ("activity", "activity_tiers")
        ):
            mine = [step for step, _ in getattr(theme, table)]
            theirs = [step for step, _ in getattr(reference, table)]
            assert mine == theirs, f"{key}: {name} 경계가 낚시와 다르다"


def test_tier_names_are_distinct_within_a_theme():
    """한 테마 안에서 등급 이름이 겹치면 등급이 올라도 화면이 안 변한다."""
    for key, theme in themes.THEMES.items():
        assert len({n for _, n in theme.fill_tiers}) == 5, key
        assert len({n for _, n in theme.activity_tiers}) == 4, key


def test_theme_changes_words_but_not_numbers():
    """같은 Snapshot 이면 테마가 달라도 숫자는 한 글자도 안 바뀐다."""
    base = to_game_state(snap(), theme="fishing")
    for key in themes.THEME_KEYS:
        state = to_game_state(snap(), theme=key)
        assert state.catch == base.catch, key
        assert state.fish == base.fish, key
        assert state.fill == base.fill, key
        assert state.casts == base.casts, key
        assert state.used_percentage == base.used_percentage, key
        assert state.theme == key

    labels = {to_game_state(snap(), theme=k).tier for k in themes.THEME_KEYS}
    assert len(labels) == 7, f"테마마다 등급 이름이 달라야 한다: {labels}"


def test_tier_label_comes_from_the_active_theme():
    for key, theme in themes.THEMES.items():
        # 80% 이상이면 마지막 등급
        state = to_game_state(snap(pct=95.0), theme=key)
        assert state.tier == theme.fill_tiers[-1][1], key
        # 사용률을 모르면 절대량 표로 떨어진다
        blind = to_game_state(snap(catch=60_000, pct=None), theme=key)
        assert blind.tier == theme.catch_tiers[2][1], key


def test_unknown_theme_falls_back_instead_of_crashing():
    """설정 파일이 낡아도 화면은 떠야 한다."""
    assert themes.get("no-such-theme") is themes.FISHING
    assert themes.get(None) is themes.FISHING
    assert to_game_state(snap(), theme="no-such-theme").theme == "fishing"


def test_nothing_is_drawn_outside_the_canvas():
    """세로로 넘치면 잘린 채 보인다. 도트 화면에서는 바로 티가 난다.

    가로는 흐르는 배경(구름·차선)이 화면 밖에서 들어왔다 나가는 게 정상이므로
    가장 넓은 요소(구름 26px) 한 개 폭만큼 여유를 준다. 그보다 크게 벗어나면
    좌표 계산이 틀린 것이다.
    """
    SLACK = 40
    for key, theme in themes.THEMES.items():
        for x, y, w, h, _ in record(theme):
            assert -SLACK <= x and x + w <= W + SLACK, f"{key}: 가로가 크게 벗어난다 ({x}..{x + w})"
            assert 0 <= y and y + h <= H, f"{key}: 세로가 화면을 벗어난다 ({y}..{y + h})"


def test_units_live_where_the_theme_says():
    """우주는 화면 전체가 하늘(은하), 나머지는 지면에. 구간이 뒤집히면 화면이 말이 안 된다."""
    for key, theme in themes.THEMES.items():
        top, bottom = theme.unit_band
        assert 0 <= top < bottom <= H, key
    # 우주는 지표면이 없다 — 별이 화면 전체(구 지평선 위아래 모두)에 떠야 한다.
    assert themes.SPACE.unit_band == (6, H - 8), "은하는 화면 전체가 하늘이다"
    for key in ("fishing", "village", "ranch", "garden", "mine", "city"):
        assert themes.THEMES[key].unit_band[0] >= SEA, f"{key}: 지면 아래여야 한다"
    assert not themes.GARDEN.unit_drifts, "심긴 꽃은 돌아다니지 않는다"
    assert not themes.MINE.unit_drifts, "벽에 박힌 광석은 돌아다니지 않는다"
    assert not themes.MINE.unit_bobs, "벽에 박힌 광석은 위아래로도 흔들리지 않는다"
    assert not themes.CITY.unit_bobs, "차는 차선을 지킨다 — 위아래로 흔들리지 않는다"
    assert themes.BEE.unit_band[0] < SEA, "벌은 지평선 위까지 날아오른다"


def test_solo_themes_stay_out_of_the_toggle():
    """--bee 전용 테마는 테마 버튼 순환에 끼면 안 된다.

    양봉은 축적 모드 전용이라, 모드 토글이 있는 보통 화면에 섞이면 고갈
    모드에서 아무것도 안 쌓이는 빈 화면이 된다.
    """
    for key in themes.SOLO_KEYS:
        assert key in themes.THEMES, key
        assert key not in themes.THEME_KEYS, key


def test_pile_and_units_add_up_in_depletion_mode():
    """고갈 모드에서 화면의 것 + 쌓인 더미 = 항상 MAX_FISH_DRAWN.

    테마를 바꿔도 이 불변식은 유지돼야 한다 — 안 그러면 더미가 넘치거나 빈다.
    """
    for key in themes.THEME_KEYS:
        for pct in (0.0, 25.0, 50.0, 99.0, 100.0):
            state = to_game_state(snap(pct=pct), mode="depletion", theme=key)
            assert state.fish_uncapped + state.on_boat == MAX_FISH_DRAWN, (key, pct)
            assert 0 <= state.on_boat <= MAX_FISH_DRAWN, (key, pct)


def test_every_fishing_spot_draws_on_canvas():
    """배경 7종 전부 자기 몫을 그리고 화면(가로 여유 포함) 안에 있어야 한다."""
    SLACK = 20
    assert len(themes.FISHING_SPOTS) == 7, themes.FISHING_SPOT_KEYS
    for key, spot in themes.FISHING_SPOTS.items():
        assert spot.key == key
        assert len(spot.unit_colors) >= 4, key
        dots: list[tuple] = []

        def px(x, y, w, h, color):
            dots.append((x, y, w, h, color))

        for frame in (0, 37, 120):
            spot.base(px, 16, SEA - 6, frame)
        assert dots, f"{key}: 아무것도 안 그린다"
        for x, y, w, h, _ in dots:
            assert -SLACK <= x and x + w <= W + SLACK, f"{key}: 가로가 크게 벗어난다"
            assert 0 <= y and y + h <= H, f"{key}: 세로가 화면을 벗어난다 ({y}..{y + h})"


def test_fishing_spot_changes_scenery_but_not_numbers():
    """배경을 바꿔도 등급·집계는 낚시 테마 그대로다 — 물고기 색과 고정물만 바뀐다."""
    plain = themes.FISHING
    for key in themes.FISHING_SPOT_KEYS:
        dressed = themes.apply_spot(plain, key)
        assert dressed.fill_tiers == plain.fill_tiers, key
        assert dressed.catch_tiers == plain.catch_tiers, key
        assert dressed.activity_tiers == plain.activity_tiers, key
        assert dressed.key == plain.key == "fishing"

    # 낚시가 아닌 테마에는 배경을 입혀도 아무 효과가 없다
    assert themes.apply_spot(themes.CITY, "island") is themes.CITY


def test_lakeside_spots_keep_swimming_units_off_dry_land():
    """차박·캠핑은 바닥 절반이 땅이다 — 헤엄치는 범위도 물 쪽으로 좁혀야
    물고기가 잔디 위를 헤엄치지 않는다."""
    for key in ("car", "camp"):
        dressed = themes.apply_spot(themes.FISHING, key)
        lo, hi = dressed.unit_x_range
        assert lo >= 60, f"{key}: 헤엄치는 범위가 땅까지 넘어온다"
        assert hi <= W

    for key in ("sea", "pier", "rocks", "breakwater", "island"):
        dressed = themes.apply_spot(themes.FISHING, key)
        assert dressed.unit_x_range == themes.FISHING.unit_x_range, f"{key}: 안 바뀌어야 한다"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
        else:
            print(f"ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
