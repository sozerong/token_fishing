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

Draw = Callable[[Px, float, float, Mood, int], None]
"""(px, x, y, mood, frame) -> 동물 한 마리. (x, y)는 몸통 왼쪽 위.

**전부 오른쪽을 보고 그린다.** 왼쪽을 볼 때는 팝업이 px를 뒤집어 넘긴다
(petpopup._mirrored) — 좌우 두 벌을 손으로 그리면 한쪽만 고치는 실수가 난다."""


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
    """밥그릇. ratio(0~1)만큼 사료가 쌓인다 — 많이 쓸수록 그릇이 찬다.

    ratio는 5시간 창을 얼마나 썼는지 그대로다. 이 화면에는 모드 토글이 없고
    (축적 전용) 그릇이 차는 것 하나로 사용량을 읽는다."""
    px(x, y + 4, 22, 5, "#6b6b76")                            # 그릇
    px(x + 1, y + 2, 20, 3, "#8b8b96")
    px(x + 1, y + 9, 20, 1, "#4a4a52")                        # 그림자
    mound = max(0, round(ratio * 7))
    for i in range(mound):                                    # 쌓인 사료
        w = 18 - i * 2
        px(x + 2 + i, y + 2 - i, max(w, 3), 2, "#c9772f" if i % 2 else "#e3944a")
    if ratio >= 0.8 and t % 40 < 10:                           # 배부르면 하트가 뜬다
        hearts(px, x + 8, y - 8, t)


def toy(px: Px, x: float, y: float, t: int) -> None:
    """장난감 공. 가만히 있다가 살짝 튀는 정도만 — 눌러보라는 힌트."""
    bob = 2 if (t // 16) % 4 == 0 else 0
    px(x, y - bob, 9, 9, "#e3c447")
    px(x + 1, y + 1 - bob, 3, 3, "#f2e08a")                   # 광
    px(x + 5, y + 5 - bob, 3, 3, "#8a6a00")


# ------------------------------------------------------------------ 동물들
# 전부 몸통 + 머리 + 다리 + 꼬리/특징. idle에서도 꼬리는 흔든다 — 완전히
# 멈춰 보이면 화면이 죽어 보인다. eat은 머리를 숙이고, play는 통통 튄다.
#
# 몸통이 15~17픽셀이다. 밖에서 한 번 더 키워 그리므로(petpopup.PET_SCALE)
# 이 해상도는 "크게 보이려고"가 아니라 **형태를 알아보려고** 쓴다 — 귀·주둥이·
# 발·눈 하이라이트가 각각 제 픽셀을 갖는 최소 크기가 이 정도다.


def _wag(t: int) -> int:
    """꼬리 흔들림. 대부분의 동물이 공유한다."""
    return int(t * 0.55) % 6 - 3


def _bob(mood: Mood, t: int, drop: int = 3, jump: int = 3) -> int:
    """먹을 땐 몸을 숙이고, 놀 땐 통통 튄다. 네 동물이 같은 규칙을 쓴다."""
    return (drop if mood == "eat" else 0) - (
        jump if mood == "play" and (t // 4) % 2 else 0
    )


def _stride(mood: Mood, t: int) -> int:
    """걸을 때 앞뒤 다리가 엇갈리는 폭. 서 있으면 0."""
    return (t // 4) % 2 if mood == "walk" else 0


def _dog(px: Px, x: float, y: float, mood: Mood, t: int) -> None:
    fur, dark, pale = "#c98a5a", "#95602f", "#f0dcc0"
    dy, step = _bob(mood, t), _stride(mood, t)
    px(x, y + dy, 17, 9, fur)                                # 몸통
    px(x, y + dy, 17, 1, dark)                               # 등 그늘
    px(x + 3, y + 7 + dy, 11, 2, pale)                       # 배 — 안쪽으로 좁게 넣는다.
    #                                                          몸통 폭을 다 채우면
    #                                                          털이 아니라 페인트로 보인다
    px(x + 1, y + 9 + dy, 3, 5 - step, dark)                 # 다리 넷
    px(x + 5, y + 9 + dy, 3, 4 + step, fur)
    px(x + 10, y + 9 + dy, 3, 4 + step, dark)
    px(x + 14, y + 9 + dy, 3, 5 - step, fur)
    hx, hy = x + 12, y - 7 + dy
    px(hx, hy, 9, 8, fur)                                    # 머리
    px(hx + 6, hy + 4, 5, 4, pale)                           # 주둥이
    px(hx + 9, hy + 4, 2, 2, "#2a2018")                      # 코
    px(hx + 5, hy + 2, 2, 2, "#2a2018")                      # 눈
    px(hx + 6, hy + 2, 1, 1, "#ffffff")
    px(hx - 1, hy + 1, 3, 6, dark)                           # 늘어진 귀
    px(x + 11, y + 1 + dy, 6, 2, "#f85149")                  # 목줄
    wag = _wag(t)
    px(x - 3, y - 1 + wag // 2 + dy, 4, 3, fur)              # 꼬리
    px(x - 5, y - 3 + wag + dy, 3, 3, fur)
    if mood == "eat":
        px(hx + 7, hy + 8, 2, 2, "#ff8fab")                  # 혀


def _cat(px: Px, x: float, y: float, mood: Mood, t: int) -> None:
    coat, dark, pale = "#6b6b7a", "#494956", "#c9c9d6"
    dy, step = _bob(mood, t, jump=2), _stride(mood, t)
    px(x, y + dy, 16, 8, coat)                               # 몸통
    px(x + 3, y + 6 + dy, 9, 2, pale)                        # 배
    px(x, y + dy, 16, 2, dark)                               # 등을 따라 어두운 결
    for i in (4, 8, 12):                                     # 등에서 내려오는 줄무늬.
        px(x + i, y + dy, 1, 4, dark)                        # 굵게 그으면 창살이 된다
    px(x + 1, y + 8 + dy, 3, 5 - step, dark)                 # 다리 넷
    px(x + 5, y + 8 + dy, 3, 4 + step, coat)
    px(x + 9, y + 8 + dy, 3, 4 + step, dark)
    px(x + 13, y + 8 + dy, 3, 5 - step, coat)
    hx, hy = x + 11, y - 7 + dy
    px(hx, hy, 8, 7, coat)                                   # 머리
    px(hx, hy - 3, 2, 3, coat)                               # 쫑긋한 귀
    px(hx + 6, hy - 3, 2, 3, coat)
    px(hx + 1, hy - 2, 1, 2, "#ff8fab")
    px(hx + 4, hy + 2, 2, 2, "#7ee787")                      # 눈
    px(hx + 7, hy + 2, 1, 2, "#7ee787")
    px(hx + 5, hy + 5, 3, 2, pale)                           # 주둥이
    px(hx + 6, hy + 4, 1, 1, "#ff8fab")                      # 코
    px(x - 3, y - 3 + dy, 3, 8, coat)                        # 꼬리 (도도하게 위로)
    px(x - 4, y - 6 + _wag(t) + dy, 3, 4, coat)


def _parrot(px: Px, x: float, y: float, mood: Mood, t: int) -> None:
    body, wing, belly = "#5ad06a", "#3f9d5f", "#ffe08a"
    hop = -4 if mood in ("walk", "play") and (t // 4) % 2 else 0
    dy = (3 if mood == "eat" else 0) + hop
    px(x + 2, y + dy, 11, 13, body)                          # 몸통
    px(x + 4, y + 6 + dy, 7, 6, belly)                       # 배
    px(x + 1, y + 2 + dy, 5, 9, wing)                        # 접은 날개
    px(x + 2, y + 3 + dy + ((t // 3) % 2), 3, 6, body)       # 날개 결
    hx, hy = x + 7, y - 8 + dy
    px(hx, hy, 8, 9, body)                                   # 머리
    px(hx + 5, hy + 3, 4, 4, "#f0e6d2")                      # 부리
    px(hx + 6, hy + 5, 3, 2, "#c9a227")
    px(hx + 3, hy + 2, 2, 2, "#0d1117")                      # 눈
    px(hx + 4, hy + 2, 1, 1, "#ffffff")
    px(hx + 1, hy - 4, 2, 4, "#f85149")                      # 볏
    px(hx + 3, hy - 5, 2, 5, "#ffd166")
    px(x - 3, y + 9 + dy, 6, 4, wing)                        # 꼬리깃
    px(x + 4, y + 13 + dy, 2, 3, "#c9a227")                  # 발
    px(x + 8, y + 13 + dy, 2, 3, "#c9a227")


def _hamster(px: Px, x: float, y: float, mood: Mood, t: int) -> None:
    fur, dark, pale = "#e0b380", "#b98a56", "#fff0dc"
    dy = _bob(mood, t, drop=2, jump=2)
    puff = 2 if mood == "eat" or (t // 12) % 3 == 0 else 0    # 볼주머니가 빵빵해진다
    px(x, y + dy, 15, 10, fur)                               # 통통한 몸
    px(x + 3, y + 7 + dy, 9, 3, pale)                        # 배
    px(x + 1, y + 10 + dy, 3, 3, dark)                       # 짧은 다리
    px(x + 10, y + 10 + dy, 3, 3, dark)
    hx, hy = x + 9, y - 4 + dy
    px(hx, hy, 8, 9, fur)                                    # 머리
    px(hx + 1, hy - 2, 3, 3, fur)                            # 동그란 귀
    px(hx + 5, hy - 2, 3, 3, fur)
    px(hx + 2, hy - 1, 1, 1, "#ff8fab")
    px(hx - 1, hy + 4, 3 + puff, 4 + puff, fur)              # 볼주머니
    px(hx + 5, hy + 3, 2, 2, "#0d1117")                      # 눈
    px(hx + 6, hy + 3, 1, 1, "#ffffff")
    px(hx + 7, hy + 6, 2, 2, "#ff8fab")                      # 코
    px(x - 2, y + 3 + dy, 2, 2, pale)                        # 짧은 꼬리


PETS: dict[str, Pet] = {
    p.key: p for p in (
        Pet(
            "dog", "강아지", unit="사료", activity_word="꼬리질", action_word="간식",
            **labels(
                ("빈 그릇", "한 입", "반 그릇", "가득", "배 터짐"),
                ("빈 그릇", "한 입", "반 그릇", "가득", "배 터짐"),
                ("낮잠", "느긋", "신남", "흥분"),
            ),
            draw=_dog, speed=0.95, style="walk",
        ),
        Pet(
            "cat", "고양이", unit="사료", activity_word="그루밍", action_word="간식",
            **labels(
                ("빈 그릇", "한 입", "반 그릇", "가득", "배 터짐"),
                ("빈 그릇", "한 입", "반 그릇", "가득", "배 터짐"),
                ("낮잠", "여유", "산책", "장난기"),
            ),
            draw=_cat, speed=0.8, style="walk",
        ),
        Pet(
            "parrot", "앵무새", unit="모이", activity_word="지저귐", action_word="모이",
            **labels(
                ("빈 모이통", "한 입", "반 통", "가득", "넘침"),
                ("빈 모이통", "한 입", "반 통", "가득", "넘침"),
                ("조용", "종알종알", "수다", "시끌벅적"),
            ),
            draw=_parrot, speed=1.6, style="hop",             # 깡충 뛰는 사이 멈춰 선다
        ),
        Pet(
            "hamster", "햄스터", unit="해바라기씨", action_word="씨앗",
            activity_word="볼주머니",
            **labels(
                ("빈 그릇", "한 줌", "반 그릇", "가득", "그릇 넘침"),
                ("빈 그릇", "한 줌", "반 그릇", "가득", "그릇 넘침"),
                ("잠듦", "느긋", "부산함", "쳇바퀴"),
            ),
            draw=_hamster, speed=1.15, style="dash",
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

    assert len(PETS) == 4, PET_KEYS
    assert get("no-such-pet") is PETS[DEFAULT]

    for key, pet in PETS.items():
        assert pet.key == key
        assert len(pet.fill_tiers) == 5, key
        assert len(pet.catch_tiers) == 5, key
        assert len(pet.activity_tiers) == 4, key
        assert len({n for _, n in pet.fill_tiers}) == 5, f"{key}: 등급 이름이 겹친다"

        for mood in ("idle", "walk", "eat", "play"):
            before = len(drawn)
            pet.draw(px, 40, 40, mood, 30)
            assert len(drawn) > before, f"{key}/{mood}: 아무것도 안 그린다"

    before = len(drawn)
    room(px, 30)
    bowl(px, 10, FLOOR - 4, 0.9, 30)
    toy(px, 100, FLOOR - 4, 30)
    assert len(drawn) > before, "방/그릇/장난감이 아무것도 안 그린다"

    print(f"animal.py selfcheck OK ({len(PETS)}종)")


if __name__ == "__main__":
    _selfcheck()
