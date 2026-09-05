"""Claude 사용량을 도트 화면으로 보여주는 항상-위 팝업."""

__version__ = "0.7.1"

DEBUG = False
"""진단 로그를 stderr로 낼 것인가. `--debug` 만 이 값을 켠다.

한때 환경변수(TOKENFISHING_DEBUG)로 켰는데, 셸에 한 번 설정해 두면 그 뒤로
계속 따라다녀서 원치 않는 로그가 계속 떴다. 스위치는 하나면 된다.
"""


def debug(message: str) -> None:
    """DEBUG 일 때만 stderr로. 팝업이 조용히 실패한 이유를 남기는 통로다."""
    if DEBUG:
        import sys

        print(f"[tokenfishing] {message}", file=sys.stderr, flush=True)
