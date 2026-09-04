# Claude Code 킥오프 프롬프트

아래를 그대로 복사해서 Claude Code 첫 메시지로 붙여넣는다.
`CLAUDE.md`는 저장소 루트에 미리 넣어둘 것.

---

## 붙여넣을 내용

```
Claude Code 사용량을 픽셀 아트로 시각화하는 도구를 만든다.
지금은 Phase 1: 파서와 검증 하네스만 만든다. UI는 만들지 않는다.

CLAUDE.md를 먼저 읽어라. 특히 "반드시 지킬 함정 세 개" 절이 이 프로젝트의 핵심이다.

### 0단계: 실제 데이터 정찰 (가장 먼저)

코드를 쓰기 전에 실제 JSONL을 확인하고 결과를 보고해라.

1. ~/.claude/projects/ 아래에 파일이 있는지 확인
2. 임의의 세션 파일에서 message.usage를 가진 행 20개를 추출
3. 다음을 보고:
   - CLAUDE.md에 적힌 필드명(input_tokens, output_tokens,
     cache_creation_input_tokens, cache_read_input_tokens)이 실제와 일치하는가
   - requestId 필드가 존재하는가
   - 같은 message.id가 여러 행에 반복되는가 (함정 1의 실재 여부)
   - timestamp 필드의 이름과 포맷
   - 그 외 처음 보는 최상위 키 목록

주의: 대화 본문(content, text)은 출력하지 마라. 필드 구조와 usage 숫자만.

실제와 CLAUDE.md가 다르면 코드를 쓰기 전에 알려라. CLAUDE.md를 먼저 고친다.

### 1단계: 저장소 스캐폴딩

0단계 결과를 반영해서 아래 구조를 만든다.

  ccpet/
    __init__.py
    paths.py       세션 파일 탐색 (CLAUDE_CONFIG_DIR 환경변수 존중, macOS/Linux/Windows)
    parser.py      JSONL → UsageEntry 스트리밍 파서
    aggregate.py   5시간 윈도우 집계, burn rate
    state.py       GameState 변환 (숫자 → 게임 의미)
    compare.py     claude-monitor 출력과 항목별 대조
  tests/
    fixtures/      전부 손으로 만든 합성 JSONL
    reference/     대조용 스냅샷 (gitignore)
    test_parser.py
    test_aggregate.py
  CLAUDE.md
  .gitignore       *.jsonl, tests/reference/ 반드시 포함
  README.md
  pyproject.toml

### 2단계: 합성 픽스처

실제 데이터는 커밋하지 않는다. 아래 케이스를 손으로 만들어라.

  normal.jsonl           단일 블록 응답 3개. 기대 총합을 주석이 아닌
                         테스트 코드에 명시
  multiblock.jsonl       한 응답이 thinking + text + tool_use 3개 =
                         5행으로 쪼개지고 전부 같은 usage 사본을 가짐.
                         dedup 후 1회만 계산되어야 함
  partial.jsonl          마지막 줄이 중간에서 잘림. 파서가 죽지 않고
                         앞의 줄들을 정상 처리해야 함
  unknown_fields.jsonl   모르는 최상위 키가 섞임. 무시하고 진행하되
                         미지 필드 카운터가 증가해야 함
  overlapping.jsonl      5시간 윈도우 두 개가 겹치는 타임스탬프 배치

각 픽스처마다 기대값을 명시한 테스트를 함께 작성한다.

### 3단계: 파서 구현

CLAUDE.md의 "파서 규칙"을 따른다. 특히:
- 스트리밍 (f.read() 금지)
- JSONDecodeError는 continue
- requestId 우선, 없으면 message.id로 dedup
- UsageEntry에 provenance 필드를 두고, output_tokens가
  중간값 문제의 영향을 받는다는 사실을 값에 실어라

### 4단계: 검증 하네스

compare.py는 claude-monitor의 --once --output json 결과와
내 파서 결과를 항목별로 비교한다.

절대 총합만 비교하지 마라. input / output / cache_write / cache_read를
각각 비교하고, 각 항목의 비율(mine / reference)을 출력한다.
CLAUDE.md의 오차 해석 표를 참고해 진단 문구를 함께 출력한다.

### 진행 방식

각 단계 끝날 때마다 멈추고 결과를 보여줘라. 한 번에 다 하지 마라.
0단계 결과를 보고할 때까지는 파일을 만들지 마라.
```

---

## 넘기기 전 체크리스트

- [ ] `CLAUDE.md`를 저장소 루트에 배치
- [ ] `git init` 및 `.gitignore`에 `*.jsonl`, `tests/reference/` 선반영
- [ ] Python 3.11+ 확인
- [ ] `~/.claude/projects/`에 세션 파일이 실제로 존재하는지 확인
      (없으면 Claude Code를 몇 번 써서 데이터를 만든 뒤 시작)

## 왜 0단계가 먼저인가

이 JSONL 포맷은 문서화되지 않은 내부 구현이고 CLI 업데이트마다 바뀔 수 있다.
CLAUDE.md에 적힌 필드명이 지금도 맞다는 보장이 없다.

**틀린 전제 위에 코드를 쌓으면 4단계에서 원인을 못 찾는다.**
30초짜리 확인으로 그걸 막는다.

## Phase 2 이후 (지금은 열지 말 것)

- Phase 2: 게임 상태 매핑과 도트 화면 (브라우저에서 단독 실행)
- Phase 3: MCP App 포장, 로컬 stdio 서버 + MCPB 패키징
- Phase 4: `availableDisplayModes`에 `pip` 선언, 호스트 응답 확인

Phase 3~4는 표시 계층이라 Phase 1 결과물을 그대로 재사용한다.
PiP가 승인되지 않더라도 Phase 1~2는 낭비되지 않는다.
