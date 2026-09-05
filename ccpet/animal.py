"""애완동물 컨셉. `--animal`로 실행하면 이 화면이 뜬다.

낚시·마을 같은 7개 테마와 숫자 파이프라인은 완전히 같다 — JSONL → aggregate →
GameState는 그대로고, 여기서 하는 일은 그 숫자를 "밥그릇" 은유로 옮기는
것뿐이다. 등급 경계값도 themes.labels()가 쓰는 것과 같은 표를 가져다 쓴다.

다른 점은 그림 파이프라인이다. 7개 테마는 하늘/지평선/바닥이 있는 옥외
풍경이지만, 여긴 실내(방 하나)라 sky/edge/base 같은 Decor 개념이 안 맞는다.
그래서 Theme을 재사용하지 않고 Pet이라는 훨씬 작은 표를 따로 둔다 — 그림과
말만 바꾸고 숫자는 안 바꾼다는 원칙은 그대로 지킨다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .themes import labels


class Px(Protocol):
    def __call__(self, x: float, y: float, w: int, h: int, color: str) -> None: ...


W, H = 180, 120
FLOOR = 82
"""바닥 y. 위가 벽, 아래가 방바닥."""

Mood = str
"""'idle' | 'walk' | 'eat' | 'play'. 동물마다 이 네 개를 다 그릴 줄 알아야 한다."""

Draw = Callable[[Px, float, float, Mood, int, int], None]
"""(px, x, y, mood, facing, frame) -> 동물 한 마리. facing 은 +1/-1."""


@dataclass(frozen=True, slots=True)
class Pet:
    key: str
    name: str
    unit: str = "사료"
    activity_word: str = "식탐"
    action_word: str = "간식"

    fill_tiers: tuple[tuple[float, str], ...] = ()
    catch_tiers: tuple[tuple[float, str], ...] = ()
    activity_tiers: tuple[tuple[float, str], ...] = ()

    draw: Draw = lambda *a: None
    speed: float = 0.5
    """방을 가로지르는 기본 속도. 종마다 다리 길이가 다르다고 생각하면 된다."""

    style: str = "walk"
    """이동 방식. 'walk'(그냥 걷기) | 'hop'(깡충) | 'dash'(질주-정지 반복)."""


# ---------------------------------------------------------------------- 방

def room(px: Px, t: int) -> None:
    """벽과 바닥. 창문 하나로 시간 흐름을 살짝 비춘다(장식일 뿐, 해는 아니다)."""
    px(0, 0, W, FLOOR, "#3a3244")                            # 벽
    px(0, FLOOR, W, H - FLOOR, "#8a7259")                    # 바닥
    px(0, FLOOR, W, 1, "#6b5a42")                             # 걸레받이
    for x in range(0, W, 18):                                # 마루 결
        px(x, FLOOR + 6, 1, H - FLOOR - 6, "#7a6249")
    px(122, 14, 26, 20, "#5a6b8c")                            # 창문
    px(122, 14, 26, 2, "#2a2438")
    px(134, 14, 2, 20, "#2a2438")
    glow = "#ffe9a8" if (t // 200) % 2 == 0 else "#c9d1e0"    # 낮/밤이 천천히 바뀐다
    px(124, 16, 10, 8, glow)


def hearts(px: Px, x: float, y: float, t: int) -> None:
    """둥실 떠오르는 하트 두 개. 배부를 때, 쓰다듬을 때 둘 다 이걸 쓴다."""
    bob = (t % 10) // 3
    px(x - 1, y - bob, 2, 2, "#ff8fab")
    px(x + 2, y - bob, 2, 2, "#ff8fab")
    px(x, y + 2 - bob, 4, 2, "#ff8fab")


def bowl(px: Px, x: float, y: float, ratio: float, t: int) -> None:
    """밥그릇. ratio(0~1)만큼 사료가 쌓인다 — 많이 쓸수록 그릇이 찬다."""
    px(x, y + 3, 16, 4, "#6b6b76")                            # 그릇
    px(x + 1, y + 2, 14, 2, "#8b8b96")
    mound = max(0, round(ratio * 5))
    for i in range(mound):                                    # 쌓인 사료
        w = 12 - i * 2
        px(x + 2 + i, y + 2 - i, max(w, 2), 2, "#c9772f" if i % 2 else "#e3944a")
    if ratio >= 0.8 and t % 40 < 10:                           # 배부르면 하트가 뜬다
        hearts(px, x + 5, y - 6, t)


def toy(px: Px, x: float, y: float, t: int) -> None:
    """장난감 공. 가만히 있다가 살짝 튀는 정도만 — 눌러보라는 힌트."""
    bob = 1 if (t // 20) % 4 == 0 else 0
    px(x, y - bob, 6, 6, "#e3c447")
    px(x + 1, y + 1 - bob, 2, 2, "#8a6a00")


# ------------------------------------------------------------------ 동물들
# 전부 몸통 + 머리 + 다리 + 꼬리/특징. idle에서도 꼬리는 흔든다 — 완전히
# 멈춰 보이면 화면이 죽어 보인다. eat은 머리를 숙이고, play는 통통 튄다.


def _wag(t: int) -> int:
    """꼬리 흔들림. 대부분의 동물이 공유한다."""
    return int(t * 0.4) % 6 - 3


def _dog(px: Px, x: float, y: float, mood: Mood, facing: int, t: int) -> None:
    head = x + (7 if facing > 0 else -3)
    duck = 2 if mood == "eat" else 0
    bounce = -2 if mood == "play" and (t // 5) % 2 == 0 else 0
    px(x, y + duck + bounce, 9, 5, "#c98a5a")                # 몸통
    px(head, y - 2 + duck + bounce, 4, 4, "#c98a5a")         # 머리
    px(head + (3 if facing > 0 else -1), y - 1 + duck, 1, 1, "#3d2a16")  # 눈
    px(head + (0 if facing > 0 else 3), y + 2 + duck, 2, 2, "#8a6a4a")   # 귀
    tail = x + (-2 if facing > 0 else 9)
    px(tail, y + bounce + _wag(t) // 2, 2, 3, "#c98a5a")     # 꼬리
    if mood == "walk":
        px(x + 1, y + 5, 1, 1, "#5a4632")
        px(x + 6, y + 5, 1, 1, "#5a4632")


def _cat(px: Px, x: float, y: float, mood: Mood, facing: int, t: int) -> None:
    head = x + (6 if facing > 0 else -2)
    duck = 2 if mood == "eat" else 0
    bounce = -1 if mood == "play" and (t // 4) % 2 == 0 else 0
    px(x, y + duck + bounce, 8, 4, "#5a5a66")                # 몸통
    px(head, y - 2 + duck + bounce, 4, 4, "#5a5a66")         # 머리
    px(head + 1, y - 3 + duck, 1, 1, "#5a5a66")              # 귀 (뾰족)
    px(head + 2, y - 3 + duck, 1, 1, "#5a5a66")
    px(head + (3 if facing > 0 else -1), y - 1 + duck, 1, 1, "#7ee787")  # 눈
    tail_x = x + (-1 if facing > 0 else 8)
    tail_y = y + bounce - 2 + _wag(t)
    px(tail_x, tail_y, 1, 4, "#5a5a66")                      # 꼬리 (도도하게 위로)


def _parrot(px: Px, x: float, y: float, mood: Mood, facing: int, t: int) -> None:
    hop = -3 if mood in ("walk", "play") and (t // 6) % 2 == 0 else 0
    head = x + (5 if facing > 0 else -1)
    px(x, y + hop, 6, 6, "#7ee787")                          # 몸통
    px(head, y - 3 + hop, 4, 4, "#7ee787")                   # 머리
    px(head + (3 if facing > 0 else -1), y - 2 + hop, 1, 1, "#0d1117")  # 눈
    px(head + (1 if facing > 0 else 0), y - 5 + hop, 2, 2, "#ffd166")   # 볏
    px(x + (5 if facing > 0 else -2), y - 4 + hop, 2, 1, "#f0e6d2")     # 부리
    wing = _wag(t) // 3
    px(x + 1, y + 2 + hop + wing, 4, 2, "#4a9d5f")           # 날개
    if mood == "eat":
        px(head + (1 if facing > 0 else 0), y - 1, 1, 2, "#f0e6d2")


def _hedgehog(px: Px, x: float, y: float, mood: Mood, facing: int, t: int) -> None:
    duck = 1 if mood == "eat" else 0
    px(x, y + duck, 9, 4, "#8a6a4a")                          # 몸통(가시)
    for i in range(0, 9, 2):                                 # 가시 텍스처
        px(x + i, y - 1 + duck, 1, 1, "#5a4632")
    nose = x + (9 if facing > 0 else -1)
    px(nose, y + 1 + duck, 2, 2, "#e8c39e")                  # 코 끝 살색
    px(nose + (1 if facing > 0 else 0), y + 2 + duck, 1, 1, "#0d1117")
    if mood == "play":                                        # 놀 때만 몸을 만다
        px(x + 2, y - 1, 4, 2, "#5a4632")


def _hamster(px: Px, x: float, y: float, mood: Mood, facing: int, t: int) -> None:
    duck = 1 if mood == "eat" else 0
    puff = 1 if (t // 15) % 3 == 0 else 0                     # 볼주머니가 가끔 빵빵
    px(x, y + duck, 7, 4, "#e8c39e")                          # 몸통
    head = x + (5 if facing > 0 else -2)
    px(head, y - 1 + duck, 4, 3, "#e8c39e")                   # 머리
    px(head + (2 if facing > 0 else -1), y + duck, 1 + puff, 1 + puff, "#d9a876")  # 볼
    px(head + (3 if facing > 0 else -1), y - 1 + duck, 1, 1, "#0d1117")  # 눈
    px(x + 1, y - 2, 1, 1, "#e8c39e")                          # 귀
    px(x + 5, y - 2, 1, 1, "#e8c39e")


PETS: dict[str, Pet] = {
    p.key: p for p in (
        Pet(
            "dog", "강아지", unit="사료", activity_word="꼬리질", action_word="간식",
            **labels(
                ("빈 그릇", "한 입", "반 그릇", "가득", "배 터짐"),
                ("빈 그릇", "한 입", "반 그릇", "가득", "배 터짐"),
                ("낮잠", "느긋", "신남", "흥분"),
            ),
            draw=_dog, speed=0.55, style="walk",
        ),
        Pet(
            "cat", "고양이", unit="사료", activity_word="그루밍", action_word="간식",
            **labels(
                ("빈 그릇", "한 입", "반 그릇", "가득", "배 터짐"),
                ("빈 그릇", "한 입", "반 그릇", "가득", "배 터짐"),
                ("낮잠", "여유", "산책", "장난기"),
            ),
            draw=_cat, speed=0.45, style="walk",
        ),
        Pet(
            "parrot", "앵무새", unit="모이", activity_word="지저귐", action_word="모이",
            **labels(
                ("빈 모이통", "한 입", "반 통", "가득", "넘침"),
                ("빈 모이통", "한 입", "반 통", "가득", "넘침"),
                ("조용", "종알종알", "수다", "시끌벅적"),
            ),
            draw=_parrot, speed=0.5, style="hop",
        ),
        Pet(
            "hedgehog", "고슴도치", unit="밀웜", action_word="밀웜",
            activity_word="꼬물거림",
            **labels(
                ("빈 그릇", "한 마리", "여러 마리", "가득", "그릇 넘침"),
                ("빈 그릇", "한 마리", "여러 마리", "가득", "그릇 넘침"),
                ("웅크림", "느릿", "꼬물꼬물", "부산함"),
            ),
            draw=_hedgehog, speed=0.2, style="walk",
        ),
        Pet(
            "hamster", "햄스터", unit="해바라기씨", action_word="씨앗",
            activity_word="볼주머니",
            **labels(
                ("빈 그릇", "한 줌", "반 그릇", "가득", "그릇 넘침"),
                ("빈 그릇", "한 줌", "반 그릇", "가득", "그릇 넘침"),
                ("잠듦", "느긋", "부산함", "쳇바퀴"),
            ),
            draw=_hamster, speed=0.65, style="dash",
        ),
    )
}
PET_KEYS = tuple(PETS)
DEFAULT = "dog"


def get(key: str | None) -> Pet:
    """없는 키가 오면 강아지. 설정 파일이 낡아도 화면은 뜬다."""
    return PETS.get(key or "", PETS[DEFAULT])


def _selfcheck() -> None:
    drawn: list[tuple] = []

    def px(x, y, w, h, color):
        drawn.append((x, y, w, h, color))

    assert len(PETS) == 5, PET_KEYS
    assert get("no-such-pet") is PETS[DEFAULT]

    for key, pet in PETS.items():
        assert pet.key == key
        assert len(pet.fill_tiers) == 5, key
        assert len(pet.catch_tiers) == 5, key
        assert len(pet.activity_tiers) == 4, key
        assert len({n for _, n in pet.fill_tiers}) == 5, f"{key}: 등급 이름이 겹친다"

        for mood in ("idle", "walk", "eat", "play"):
            before = len(drawn)
            pet.draw(px, 40, 40, mood, 1, 30)
            assert len(drawn) > before, f"{key}/{mood}: 아무것도 안 그린다"

    before = len(drawn)
    room(px, 30)
    bowl(px, 10, FLOOR - 4, 0.9, 30)
    toy(px, 100, FLOOR - 4, 30)
    assert len(drawn) > before, "방/그릇/장난감이 아무것도 안 그린다"

    print(f"animal.py selfcheck OK ({len(PETS)}종)")


if __name__ == "__main__":
    _selfcheck()
