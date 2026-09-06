"""픽스처별 기대값을 코드에 명시한다. 주석에 적힌 숫자는 테스트가 아니다.

pytest 없이도 돌아간다:  py -3.12 tests/test_parser.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tokenfishing.parser import parse_file  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def totals(entries):
    return (
        sum(e.input_tokens for e in entries),
        sum(e.output_tokens for e in entries),
        sum(e.cache_creation_tokens for e in entries),
        sum(e.cache_read_tokens for e in entries),
    )


def test_normal():
    r = parse_file(FIXTURES / "normal.jsonl")

    assert len(r.entries) == 3
    assert totals(r.entries) == (60, 600, 6000, 18000)
    assert r.bad_lines == 0
    assert [e.model for e in r.entries] == [
        "claude-opus-5", "claude-opus-5", "claude-sonnet-5"
    ]
    assert [e.request_id for e in r.entries] == [
        "req_normal_1", "req_normal_2", "req_normal_3"
    ]
    assert all(e.provenance == "stable" for e in r.entries)
    assert not any(e.is_sidechain for e in r.entries)
    # user 행에는 usage가 없다. 엔트리로 새면 안 된다.
    assert all(e.request_id.startswith("req_") for e in r.entries)


def test_multiblock_dedup():
    """함정 1: 5행이 같은 usage 사본을 들고 있다. 1회만 계산돼야 한다."""
    r = parse_file(FIXTURES / "multiblock.jsonl")

    assert len(r.entries) == 1
    assert totals(r.entries) == (5, 777, 1234, 4321)

    # dedup을 빠뜨리면 정확히 이 값이 나온다. 회귀 방지용.
    naive = (5 * 5, 5 * 777, 5 * 1234, 5 * 4321)
    assert totals(r.entries) != naive
    assert naive == (25, 3885, 6170, 21605)


def test_partial_line_does_not_kill_parser():
    """마지막 줄이 잘려도 앞 줄은 정상 처리한다."""
    r = parse_file(FIXTURES / "partial.jsonl")

    assert len(r.entries) == 2
    assert totals(r.entries) == (3, 33, 333, 3333)
    assert r.bad_lines == 1


def test_unknown_fields_are_ignored_but_counted():
    r = parse_file(FIXTURES / "unknown_fields.jsonl")

    assert len(r.entries) == 2
    assert totals(r.entries) == (15, 150, 1500, 15000)

    assert r.unknown_fields["quantumFlux"] == 2
    assert r.unknown_fields["sparkleIndex"] == 1
    assert r.unknown_fields["payload"] == 1
    # 아는 키는 카운터에 들어가면 안 된다
    assert "requestId" not in r.unknown_fields
    assert "timestamp" not in r.unknown_fields
    assert "message" not in r.unknown_fields


def test_subagent_partial_output_takes_max():
    """함정 2: 서브에이전트 파일에서 output_tokens가 자란다. max를 집는다."""
    r = parse_file(FIXTURES / "subagent_partial.jsonl")

    assert len(r.entries) == 2

    grown = next(e for e in r.entries if e.request_id == "req_sub_1")
    assert grown.output_tokens == 292
    assert grown.input_tokens == 3
    assert grown.cache_creation_tokens == 500
    assert grown.cache_read_tokens == 9000
    assert grown.is_sidechain is True
    assert grown.provenance == "reconstructed_from_partial"

    stable = next(e for e in r.entries if e.request_id == "req_sub_2")
    assert stable.output_tokens == 15
    assert stable.provenance == "stable"

    assert totals(r.entries) == (7, 307, 1100, 18500)


def test_aborted_mid_stream_is_labelled():
    """중단된 응답은 최종값이 존재하지 않는다. stable이라 부르면 거짓말이다."""
    r = parse_file(FIXTURES / "aborted.jsonl")

    assert len(r.entries) == 2

    aborted = next(e for e in r.entries if e.request_id == "req_abort_1")
    assert aborted.provenance == "aborted_mid_stream"
    # 성장도 했지만(2 → 9) 중단이 더 나쁜 소식이라 그쪽이 이긴다
    assert aborted.output_tokens == 9

    ok = next(e for e in r.entries if e.request_id == "req_abort_2")
    assert ok.provenance == "stable"
    assert ok.output_tokens == 50


def test_overlapping_sessions_parse():
    """윈도우 계산은 aggregate의 몫. 여기선 파싱 사실만 고정한다."""
    r = parse_file(FIXTURES / "overlapping.jsonl")

    assert len(r.entries) == 6
    assert totals(r.entries) == (6, 210, 600, 6000)
    assert {e.session_id for e in r.entries} == {"s-A", "s-B"}

    first = r.entries[0]
    assert first.timestamp == datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc)
    assert first.timestamp.tzinfo is not None, "naive datetime은 윈도우 계산을 망친다"

    # 파일에 적힌 순서 그대로 (세션이 섞여 들어온다)
    assert [e.session_id for e in r.entries] == [
        "s-A", "s-A", "s-B", "s-A", "s-B", "s-B"
    ]


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
