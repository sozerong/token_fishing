"""--animal 모드. 숫자는 GameState에서 그대로 오고, 여기서는 말/그림 표만 본다.

pytest 없이도 돌아간다:  py -3.12 tests/test_animal.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccpet import animal  # noqa: E402


def record_pet(pet: animal.Pet) -> list[tuple]:
    dots: list[tuple] = []

    def px(x, y, w, h, color):
        dots.append((x, y, w, h, color))

    for mood in ("idle", "walk", "eat", "play"):
        for facing in (1, -1):
            for frame in (0, 37, 120):
                pet.draw(px, 60, 60, mood, facing, frame)
    return dots


def test_every_pet_is_complete():
    assert len(animal.PETS) == 5, animal.PET_KEYS
    for key, pet in animal.PETS.items():
        assert pet.key == key
        assert pet.name and pet.unit and pet.activity_word and pet.action_word
        assert len(pet.fill_tiers) == 5, key
        assert len(pet.catch_tiers) == 5, key
        assert len(pet.activity_tiers) == 4, key
        assert record_pet(pet), f"{key}: 아무것도 안 그린다"


def test_tier_boundaries_match_the_shared_table():
    """동물마다 이름은 달라도 등급이 바뀌는 지점은 themes.py의 표와 같아야 한다.

    숫자의 뜻을 은유가 바꾸면 안 된다는 원칙은 동물 모드에도 그대로 적용된다.
    """
    from ccpet import themes

    for key, pet in animal.PETS.items():
        mine = [step for step, _ in pet.fill_tiers]
        theirs = [step for step, _ in themes.FISHING.fill_tiers]
        assert mine == theirs, f"{key}: fill 경계가 다르다"


def test_tier_names_are_distinct_within_a_pet():
    for key, pet in animal.PETS.items():
        assert len({n for _, n in pet.fill_tiers}) == 5, key
        assert len({n for _, n in pet.activity_tiers}) == 4, key


def test_unknown_pet_falls_back_instead_of_crashing():
    assert animal.get("no-such-pet") is animal.PETS[animal.DEFAULT]
    assert animal.get(None) is animal.PETS[animal.DEFAULT]


def test_nothing_is_drawn_outside_the_canvas():
    SLACK = 10
    for key, pet in animal.PETS.items():
        for x, y, w, h, _ in record_pet(pet):
            assert -SLACK <= x and x + w <= animal.W + SLACK, f"{key}: 가로 이탈"
            assert -SLACK <= y and y + h <= animal.H + SLACK, f"{key}: 세로 이탈"


def test_bowl_fills_up_with_ratio():
    """밥그릇 더미는 ratio가 클수록 커야 한다 — 안 그러면 많이 써도 안 찬 것처럼 보인다."""
    def mound_rows(ratio: float) -> int:
        dots: list[tuple] = []

        def px(x, y, w, h, color):
            dots.append((x, y, w, h, color))

        animal.bowl(px, 0, 0, ratio, 0)
        return len(dots)

    assert mound_rows(0.0) < mound_rows(0.5) < mound_rows(1.0)


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
