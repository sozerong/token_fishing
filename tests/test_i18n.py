"""ko/en 전환. 번역이 빠지면 화면이 조용히 한국어로 돌아가므로 여기서 잡는다.

pytest 없이도 돌아간다:  py -3.12 tests/test_i18n.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccpet import animal, config, i18n, themes  # noqa: E402


def displayed_labels() -> set[str]:
    """화면에 그대로 뜨는 한국어 라벨 전부."""
    words: set[str] = set()
    for theme in themes.THEMES.values():
        words |= {theme.name, theme.unit, theme.activity_word, theme.action_word}
        for table in (theme.fill_tiers, theme.catch_tiers, theme.activity_tiers):
            words |= {name for _, name in table}
    words |= {spot.name for spot in themes.FISHING_SPOTS.values()}
    for pet in animal.PETS.values():
        words |= {pet.name, pet.unit, pet.activity_word, pet.action_word}
        for table in (pet.fill_tiers, pet.catch_tiers, pet.activity_tiers):
            words |= {name for _, name in table}
    words |= set(config.MODE_LABELS.values())
    return words


def test_every_label_has_an_english_translation():
    """테마·펫 라벨 중 번역이 빠진 게 있으면 안 된다.

    빠져도 프로그램은 안 죽고 그 자리만 한국어로 남는다 — 그래서 눈으로는
    놓치기 쉽고, 이 테스트가 유일한 안전장치다.
    """
    missing = sorted(w for w in displayed_labels() if w not in i18n._EN)
    assert not missing, f"영어 번역이 없는 라벨: {missing}"


def test_english_labels_are_actually_english():
    """번역해 놓고 한국어를 그대로 둔 항목이 없어야 한다."""
    def has_hangul(s: str) -> bool:
        return any("\uac00" <= ch <= "\ud7a3" for ch in s)

    left = sorted(k for k, v in i18n._EN.items() if has_hangul(v))
    assert not left, f"영어 자리에 한국어가 남았다: {left}"


def test_switching_language_changes_what_is_shown():
    try:
        i18n.set_lang("ko")
        assert i18n.t("낚시") == "낚시"
        assert i18n.fmt("tokens", n=1234) == "1,234 토큰"

        i18n.set_lang("en")
        assert i18n.t("낚시") == "Fishing"
        assert i18n.fmt("tokens", n=1234) == "1,234 tokens"

        # 번역이 없는 말은 원문 그대로 — 화면이 비면 안 된다
        assert i18n.t("듣도보도 못한 라벨") == "듣도보도 못한 라벨"
    finally:
        i18n.set_lang("ko")


def test_every_line_template_exists_in_both_languages():
    for key, (ko, en) in i18n._LINES.items():
        assert ko and en, key
        # 두 틀이 같은 이름표를 써야 한 쪽만 KeyError로 죽지 않는다
        import string
        fields = lambda s: {f for _, f, _, _ in string.Formatter().parse(s) if f}
        assert fields(ko) == fields(en), f"{key}: 치환 이름이 다르다"


def test_unknown_language_falls_back_to_the_system():
    assert i18n.resolve("en") == "en"
    assert i18n.resolve("ko") == "ko"
    assert i18n.resolve("klingon") in i18n.CHOICES
    assert i18n.resolve(None) in i18n.CHOICES


def main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
        else:
            print(f"ok   {name}")
    print(f"\n{'실패 ' + str(failed) if failed else '전부 통과'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
