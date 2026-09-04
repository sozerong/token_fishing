# CLAUDE.md

Claude Code 사용량을 픽셀 아트로 시각화하는 도구. 이 파일은 매 세션 자동으로 로드된다.

## 지금 단계

**Phase 2: 게임 상태 매핑 + 도트 화면.**
성공 기준은 "PiP 창에 도트 화면이 뜨고, 거기 있는 숫자가 Phase 1과 같다".

Phase 1(파서 + 검증 하네스)은 완료됐다. claude-monitor 4.0.0과 항목별 대조에서
input/output/cache_w/cache_r 네 항목 전부 차이 0. **그 정확도를 깨지 말 것** —
화면을 붙이다가 숫자가 틀리면 Phase 1을 되돌리는 것이다. `compare`는 계속 통과해야 한다.

은유는 **낚시**다. 저장소 이름 그대로. 패키지 이름 `ccpet`은 초기 잔재고 은유가 아니다.

Phase 3(MCP App 포장)과 Phase 4(호스트 `pip` 선언)는 표시 계층 이관이다. 지금은
브라우저 Document Picture-in-Picture API로 단독 실행한다 — MCP 호스트 없이도 PiP가 된다.

## 데이터 소스

Claude Code가 세션마다 쓰는 JSONL:

```
~/.claude/projects/<인코딩된-작업경로>/<세션-uuid>.jsonl
```

어시스턴트 턴에 포함된 사용량 (2026-09-04 실측, 4개 세션 파일 대조):

```json
{
  "type": "assistant",
  "requestId": "req_…",
  "timestamp": "2026-08-31T16:32:37.811Z",
  "message": {
    "id": "msg_…",
    "model": "claude-opus-5",
    "role": "assistant",
    "stop_reason": "tool_use",
    "usage": {
      "input_tokens": 2,
      "output_tokens": 440,
      "cache_creation_input_tokens": 26555,
      "cache_read_input_tokens": 33714,
      "output_tokens_details": { "thinking_tokens": 156 },
      "cache_creation": {
        "ephemeral_1h_input_tokens": 26555,
        "ephemeral_5m_input_tokens": 0
      },
      "iterations": [ { "...": "usage 필드 대부분의 사본, 길이 항상 1" } ],
      "server_tool_use": { "web_search_requests": 0, "web_fetch_requests": 0 },
      "service_tier": "standard",
      "inference_geo": "not_available",
      "speed": "standard"
    }
  }
}
```

핵심 4필드(input_tokens / output_tokens / cache_creation_input_tokens / cache_read_input_tokens)는
실측과 일치. 그 외 필드(`output_tokens_details`, `cache_creation`, `iterations`, `server_tool_use`,
`service_tier`, `inference_geo`, `speed`, top-level `effort`)는 문서에 없던 것들 — 파서는
"파서 규칙"의 "모르는 필드는 무시" 원칙대로 그냥 통과시킨다. `cache_creation`은
`cache_creation_input_tokens`를 1h/5m TTL로 쪼갠 값(합이 상위 필드와 같음) — 나중에 캐시 비용
분리가 필요해지면 여기서 가져온다.

top-level `type`은 `assistant`/`user` 외에도 `queue-operation`, `attachment`, `last-prompt`,
`custom-title`, `bridge-session`, `atis-latch`, `system`, `frame-link`,
`artifact-comment-monitor`, `mode` 등 usage와 무관한 envelope 행이 섞여 있다.
`message.usage`가 없는 행은 그냥 건너뛴다.

**이 포맷은 문서화되지 않은 내부 구현이다.** 버전 필드 없고 안정성 보장 없다.
CLI 업데이트마다 바뀔 수 있으므로, 필드가 위와 다르면 **실제 파일을 우선하고 이 문서를 고쳐라.**

## 반드시 지킬 함정 네 개

이걸 어기면 숫자가 틀린다. 코드 리뷰 시 최우선 확인 항목.

### 1. 한 응답이 여러 줄로 쪼개진다

Claude Code 2.1+는 콘텐츠 블록(thinking / text / tool_use)마다 행을 하나씩 쓰고,
**각 행이 동일한 usage 사본을 들고 있다.**

- 그냥 합산하면 멀티블록 턴이 블록 수만큼 중복 → 실측 사례에서 약 2.3배 과대
- dedup 키는 `requestId`, 없으면 `message.id`
- **엔트리 자체를 병합하지 말 것.** 서로 다른 요청의 행이 디스크상에서 섞여 들어온다. 중복된 건 usage뿐이다
- `message.id`만으로 dedup하면 첫 블록 이후 콘텐츠가 사라진다. 청구 필드만 dedup하고 콘텐츠는 합집합

### 2. output_tokens는 최종값이 아니다 — **서브에이전트 파일에서만 실재**

전체 세션 파일 20개, message_id 1438개를 훑은 결과 (2026-09-05):

| 파일 종류 | 성장하는 message_id |
|---|---|
| 메인 세션 (`projects/<enc>/<uuid>.jsonl`) | **0 / 1388** |
| 서브에이전트 (`projects/<enc>/<uuid>/subagents/agent-*.jsonl`) | **27 / 50** |

메인 세션 파일에서는 같은 `message.id`의 모든 행이 동일한 최종 `output_tokens`를 들고
있다. 반면 서브에이전트 트랜스크립트에서는 자란다 — 실측 예:

```
output_tokens_sequence = [2, 2, 2, 292]     # 마지막 행만 최종값
output_tokens_sequence = [3, 1182]
output_tokens_sequence = [5, 407]
```

앞 행을 쓰면 최대 100배 가까이 과소 계상된다. CLI 버전과는 무관했다 — 같은 2.1.187에서
메인 파일은 0/14, 서브에이전트는 20/36이었다. **파일 종류의 문제다.**

- 대응: `requestId`별 **`max(output_tokens)`**. 메인 파일에선 모든 행이 같은 값이라
  무해하고, 서브에이전트에선 정확히 최종값을 집는다. **분기 없이 한 규칙으로 둘 다 처리된다**
- `stop_reason`은 판별에 못 쓴다. usage를 가진 assistant 행에서는 전부
  `tool_use`/`end_turn`이었고 `null`은 user 행에만 나왔다
- input·cache 토큰은 요청 시작 시 확정이라 정확 (같은 requestId 안에서 항상 상수)
- **`provenance`에 남길 것**: 그 requestId의 output_tokens가 성장 관찰됐는지 여부
  (`reconstructed_from_partial` vs `stable`). 오차를 숨기지 마라

### 3. 서브에이전트 파일을 빠뜨리지 마라 (그리고 이중계상도 하지 마라)

서브에이전트 사용량은 **별도 파일**에 있다:

```
projects/<enc>/<세션-uuid>/subagents/agent-<id>.jsonl
```

`projects/*/*.jsonl` 글롭만 쓰면 이 토큰이 통째로 빠진다. 실측에서 서브에이전트 파일이
usage 행 106개를 들고 있었다.

- **이중계상 위험은 없다.** 서브에이전트 파일의 `message.id`와 부모 세션 파일의
  `message.id` 교집합은 두 사례 모두 **0**이었다. 둘 다 세면 된다
- `isSidechain`이 깔끔하게 갈린다: 메인 파일 전부 `False`, 서브에이전트 파일 전부 `True`.
  경로 대신 이 플래그로 라벨링하는 게 낫다
- `model: "<synthetic>"` 행이 존재하지만 usage가 전부 0이라 필터링 불필요.
  괜히 규칙 늘리지 말 것

### 4. 두 오차는 방향이 반대다

```
함정 1 미처리 → 메시지당 행 수(실측 2~4)만큼 과대
함정 2 미처리 → 서브에이전트 출력 토큰이 최대 100배 과소
```

**둘 다 틀리면 총합이 우연히 맞아 보인다.**
따라서 검증은 **반드시 항목별(input / output / cache_w / cache_r)로 따로** 한다.
총합 비교만 하는 테스트는 이 프로젝트에서 무효다.

## 파서 규칙

- **스트리밍 필수.** 파일이 200MB까지 갈 수 있다. `f.read()` 금지, 줄 단위 이터레이션
- **깨진 줄에서 죽지 말 것.** 파일이 실시간으로 쓰이는 중이라 반쯤 쓰인 줄을 읽을 수 있다. `JSONDecodeError`는 `continue`
- **모르는 필드는 무시하고 아는 것만 꺼낸다.** 엄격한 스키마 검증으로 전체를 거부하지 말 것
- **미지 필드 카운터를 유지한다.** 처음 보는 키의 개수가 급증하면 스키마가 바뀐 신호. 조기 경보 장치
- **파서를 얇은 층으로 격리한다.** 게임 로직이 JSONL 구조를 직접 알면 안 된다

```
JSONL → [parser] → UsageEntry(정규화) → [aggregate] → GameState
                     ↑ 이 경계 넘지 말 것
```

## 세션 윈도우

Claude Code는 5시간 롤링 윈도우로 동작한다.

- 세션은 첫 메시지에서 시작, 정확히 5시간 지속. **정시로 내리지 않는다**
  (`FLOOR_TO_HOUR = False`). 한때 True였다 — claude-monitor가 13:36 요청에 대해
  13:00을 내놓길래 맞췄었다. 2026-09-05 공식 사용량 화면과 대조하니 실제 세션 시작은
  **15:17**이었다. 정시가 아니다. **레퍼런스는 대조군이지 정답지가 아니다** —
  저쪽도 JSONL만 보고 추측한다. 둘이 일치한다고 맞는 게 아니다
- **여러 세션이 동시에 활성일 수 있다.** 겹치는 구간 처리가 이 프로젝트의 유일한 알고리즘 판단.
  **결론: 계정 단위 하나의 시간축으로 합친다.** 한도는 계정에 걸리지 파일에 걸리지 않는다.
  sessionId별로 윈도우를 나누지 않고, 전 파일 엔트리를 시간순으로 합친 뒤 블록을 자른다
- burn rate: 최근 1시간의 모든 활성 세션에서 수집 → 분당 토큰.
  **레퍼런스와 정의가 다르다** — claude-monitor는 `윈도우 총량 / 윈도우 경과시간`을 쓴다.
  둘 다 맞는 지표이고 용도가 다르다(우리 건 반응성, 저쪽 건 소진 예측). compare가 저쪽
  정의를 우리 데이터로 재현해 0.03% 안에 드는 걸 보여주므로, 이 차이는 버그가 아니라
  정의 차이임이 증명된다. 재현이 1% 넘게 어긋나면 그때는 진짜 불일치다

### 윈도우 경계는 JSONL만으로 못 맞출 수 있다 (2026-09-05 확인)

**claude.ai 웹과 모바일 사용량도 같은 5시간 한도를 먹지만 JSONL에 흔적을 안 남긴다.**
그 사용이 창을 열었으면, 우리가 보는 첫 요청은 창의 시작이 아니다.

실측 사례:

```
공식 화면          "2시간 53분 후 재설정"  → 리셋 20:17 → 세션 시작 15:17 UTC
우리 데이터        15:17:08 에 요청 있음   ← 시작 시각이 정확히 일치
그런데 그날 첫 요청 13:36 (그 앞 96분 공백)
```

15:17이 *새* 창을 열었다면 13:36을 담은 창은 이미 끝났어야 하고, 그러려면 그 창이
10:17 이전에 시작됐어야 한다. 그런데 그날 Claude Code 첫 요청은 13:36이다.
→ **10:17경의 창을 연 건 JSONL에 없는 사용이다.**

결과적으로 추정 창(13:36~18:36)은 이전 창의 요청 18건 18,785토큰을 잘못 포함했고,
리셋 시각도 1시간 7분 vs 2시간 48분으로 틀렸다.

- "첫 메시지가 창을 연다"는 모델 자체는 맞다. 시작 시각이 정확히 일치했다
- 못 맞추는 건 **보이지 않는 입력** 때문이지 알고리즘 때문이 아니다. 알고리즘을
  더 만져도 해결되지 않는다
- 대응: `TOKENFISHING_RESET_AT`으로 공식 화면의 리셋 시각을 꽂으면 그 창만으로 센다
- **화면에서 추정값을 확실한 척 보여주지 말 것.** 고정 안 됐으면 `~`를 붙이고
  색을 바꾼다. 틀릴 수 있는 숫자다

## 검증 방법

레퍼런스 구현과 대조한다. **의존이 아니라 대조군이다.**

```bash
py -3.12 -m pip install claude-monitor
py -3.12 -m claude_monitor --once --output json > tests/reference/snapshot.json
py -3.12 -m ccpet.compare tests/reference/snapshot.json
```

compare는 레퍼런스의 `generated_at`을 `now`로 쓰고 그 이후 엔트리를 잘라낸다.
안 그러면 측정 사이에 쌓인 토큰이 우리 쪽에만 잡혀서, 알고리즘 차이인지 시차인지
구분이 안 된다.

**2026-09-04 대조 결과: input / output / cache_w / cache_r 네 항목 전부 차이 0,
윈도우 경계까지 일치.** 상쇄가 아니라는 건 항목별로 확인했다.

오차 해석:

| 증상 | 원인 |
|---|---|
| 2~5배 높음 | dedup 누락 (함정 1) |
| 출력만 낮음 | requestId별 max 미적용 (함정 2) — 서브에이전트 파일 확인 |
| 전반적으로 조금 낮음 | `subagents/` 글롭 누락 (함정 3) |
| 0 또는 예외 | 경로/필드명 변경 |
| 총합만 맞음 | **상쇄 의심. 항목별 재확인** |

## 프라이버시 — 위반 금지

`~/.claude/projects/` 안의 JSONL에는 **실제 대화 내용이 들어 있다.**

- **실제 세션 파일을 저장소에 커밋하지 말 것**
- 테스트 픽스처는 전부 손으로 만든 합성 데이터
- 로그에 프롬프트나 응답 본문을 찍지 말 것. 토큰 수와 모델명만
- 네트워크 전송 없음. 이 도구는 완전히 로컬이다

## 코드 규칙

- Python 3.11+, 표준 라이브러리 우선. 의존성 추가 전에 물어볼 것
- 파서 코어는 외부 의존성 0을 목표로 한다
- 타입 힌트 사용
- 새 기능마다 픽스처 기반 테스트 추가
- 커밋 메시지 한국어 또는 영어, 일관되게

## 하지 말 것

- claude-monitor의 분석 로직을 복사하지 말 것. 직접 구현하는 게 이 프로젝트의 목적
- Rich TUI 출력을 파싱하지 말 것. 원본 데이터만 읽는다
- CSV 리포트, 웨어하우스 영속화 같은 기능 확장 금지
- **한도(limit) 퍼센트와 소진 예측을 만들어내지 말 것.** 레퍼런스는 `token_limit`을
  P90으로 추정해 `used_percentage` / `pace` / `forecast`를 내놓는다. 실측으로
  틀린 게 확인됐다 — 레퍼런스 **82.6%**, 같은 시점 공식 화면 **35%**.
  두 배 넘게 틀렸고, `pace`와 `forecast`는 그 틀린 값 위에 쌓여 있다

### 레퍼런스 필드를 베낄지 판단하는 기준

"claude-monitor가 주니까 우리도" 는 이유가 아니다. **추측이 들어가는가**로 가른다.

| 넣는다 (순수 집계) | 안 넣는다 (추측 필요) |
|---|---|
| 모델별 분포 — 파싱해 둔 `model`을 묶기만 함 | `token_limit` — P90 추정 |
| 주간 사용량 — 리셋 요일만 알면 정확 | `used_percentage` — 위 추정에 의존 |
| 전체 누적, 요청 수 | `pace`, `forecast` — 위 추정에 의존 |

`cost_usd`도 안 넣는다. 가격표를 하드코딩해야 하고 가격이 바뀌면 조용히 틀린다.
무엇보다 **구독제 사용자는 토큰당 돈을 내지 않는다** — 그 숫자는 실제 지출이 아니다.
정 필요하면 "API로 환산하면 얼마" 라고 이름을 정직하게 붙여서 옵션으로 넣어라.
- 화면에서 숫자를 만들지 말 것. `state.py`는 `aggregate`가 준 값을 은유로 옮기기만 한다.
  새 집계가 필요하면 `aggregate`에 넣고 compare로 검증한 뒤 가져다 쓴다
