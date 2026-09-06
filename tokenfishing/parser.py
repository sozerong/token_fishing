"""JSONL → UsageEntry. 이 모듈만 JSONL 구조를 안다.

게임 로직이 이 아래로 내려오면 안 된다:

    JSONL → [parser] → UsageEntry → [aggregate] → GameState
                         ↑ 이 경계
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# 2026-09-05 실측으로 관찰된 최상위 키. 여기 없는 키는 미지 필드 카운터로 샌다.
# 개수가 급증하면 CLI가 스키마를 바꿨다는 신호 — 조기 경보용이지 거부 목록이 아니다.
KNOWN_TOP_KEYS = frozenset({
    "accountUuid", "agentId", "aiTitle", "apiBlockIndex", "apiErrorStatus",
    "artifactCount", "artifacts", "attributionAgent", "error", "frameUrl",
    "isAbortedMidStream", "isApiErrorMessage", "mode", "path",
    "queueSkipAttachments", "sourceToolUseID", "title", "toolDenialKind", "v",
    "atis", "attachment", "attributionMcpServer", "attributionMcpTool",
    "attributionPlugin", "attributionSkill", "bridgeSessionId", "content",
    "customTitle", "cwd", "effort", "entrypoint", "gitBranch", "hasOutput",
    "hookAdditionalContext", "hookCount", "hookErrors", "hookInfos", "isMeta",
    "isSidechain", "lastPrompt", "lastSequenceNum", "leafUuid", "level",
    "message", "operation", "origin", "ownerAccountUuid",
    "ownerOrganizationUuid", "parentUuid", "permissionMode", "preventedContinuation",
    "promptId", "promptSource", "reason", "requestId", "sessionId",
    "sourceToolAssistantUUID", "stopReason", "subtype", "timestamp",
    "toolUseID", "toolUseResult", "turnCompanion", "type", "userType",
    "uuid", "version",
})

STABLE = "stable"
RECONSTRUCTED = "reconstructed_from_partial"
ABORTED = "aborted_mid_stream"


@dataclass(frozen=True, slots=True)
class UsageEntry:
    """청구 대상 요청 하나. requestId당 정확히 하나."""

    request_id: str
    session_id: str
    timestamp: datetime  # 요청 시작(첫 행) 기준, tz-aware
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    is_sidechain: bool
    provenance: str
    """STABLE        모든 행의 output_tokens가 같았다. 신뢰 가능
    RECONSTRUCTED    자라는 중간 스냅샷을 max로 복원했다 (함정 2). 서브에이전트에서 발생
    ABORTED          isAbortedMidStream. 최종값이 애초에 존재하지 않는다 — 확정적 과소 계상

    이 구분을 숨기지 말 것. 숫자만 내놓고 출처를 감추면 4단계에서 원인을 못 찾는다."""


@dataclass
class ParseResult:
    entries: list[UsageEntry] = field(default_factory=list)
    unknown_fields: Counter = field(default_factory=Counter)
    bad_lines: int = 0
    skipped: Counter = field(default_factory=Counter)
    """버린 행의 이유별 개수. 조용히 사라지는 토큰이 없도록 노출한다."""


@dataclass
class _Acc:
    """같은 requestId의 여러 행을 모으는 중간 상태."""

    request_id: str
    session_id: str
    timestamp: datetime
    model: str
    is_sidechain: bool
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    output_varied: bool = False
    aborted: bool = False

    def merge(self, usage: dict, model: str) -> None:
        out = _int(usage.get("output_tokens"))
        if out != self.output_tokens:
            # 함정 2: 서브에이전트 파일에서 output_tokens가 자란다.
            # max 하나로 메인/서브에이전트 둘 다 처리된다 — 분기 없음.
            self.output_varied = True
            self.output_tokens = max(self.output_tokens, out)
        # 입력·캐시는 요청 시작 시 확정이라 상수여야 하지만, max가 더 안전하다.
        self.input_tokens = max(self.input_tokens, _int(usage.get("input_tokens")))
        self.cache_creation_tokens = max(
            self.cache_creation_tokens, _int(usage.get("cache_creation_input_tokens"))
        )
        self.cache_read_tokens = max(
            self.cache_read_tokens, _int(usage.get("cache_read_input_tokens"))
        )
        if self.model in ("", "unknown") and model:
            self.model = model

    def freeze(self) -> UsageEntry:
        return UsageEntry(
            request_id=self.request_id,
            session_id=self.session_id,
            timestamp=self.timestamp,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_creation_tokens=self.cache_creation_tokens,
            cache_read_tokens=self.cache_read_tokens,
            is_sidechain=self.is_sidechain,
            provenance=self._provenance(),
        )

    def _provenance(self) -> str:
        # 중단이 가장 나쁜 소식이라 우선한다 — 복원해도 최종값이 없다.
        if self.aborted:
            return ABORTED
        return RECONSTRUCTED if self.output_varied else STABLE


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _parse_ts(raw) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        # 실측 포맷: "2026-08-31T16:32:37.811Z" — 3.11+는 Z를 직접 받는다.
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return ts if ts.tzinfo else None


def parse_file(path: Path | str) -> ParseResult:
    """한 JSONL 파일을 스트리밍으로 읽어 requestId별로 dedup한다.

    엔트리 순서는 각 requestId가 처음 나타난 순서 (dict 삽입 순서).
    """
    result = ParseResult()
    acc: dict[str, _Acc] = {}

    # 스트리밍 필수. 파일이 200MB까지 간다 — read() 금지.
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # 실시간으로 쓰이는 중이라 반쯤 쓰인 줄을 읽을 수 있다. 죽지 않는다.
                result.bad_lines += 1
                continue
            if not isinstance(obj, dict):
                result.bad_lines += 1
                continue

            for k in obj:
                if k not in KNOWN_TOP_KEYS:
                    result.unknown_fields[k] += 1

            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue

            # dedup 키는 requestId 우선, 없으면 message.id (함정 1).
            key = obj.get("requestId") or msg.get("id")
            if not isinstance(key, str) or not key:
                result.skipped["no_dedup_key"] += 1
                continue

            existing = acc.get(key)
            if existing is not None:
                existing.merge(usage, msg.get("model") or "")
                existing.aborted |= obj.get("isAbortedMidStream") is True
                continue

            ts = _parse_ts(obj.get("timestamp"))
            if ts is None:
                result.skipped["no_timestamp"] += 1
                continue

            acc[key] = _Acc(
                request_id=key,
                session_id=obj.get("sessionId") or "",
                timestamp=ts,
                model=msg.get("model") or "unknown",
                is_sidechain=obj.get("isSidechain") is True,
                input_tokens=_int(usage.get("input_tokens")),
                output_tokens=_int(usage.get("output_tokens")),
                cache_creation_tokens=_int(usage.get("cache_creation_input_tokens")),
                cache_read_tokens=_int(usage.get("cache_read_input_tokens")),
                aborted=obj.get("isAbortedMidStream") is True,
            )

    result.entries = [a.freeze() for a in acc.values()]
    return result
