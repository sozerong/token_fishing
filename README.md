# ccpet

Claude Code 사용량을 로컬 JSONL에서 직접 읽어 정확한 토큰 숫자를 내는 파서.

Phase 1 목표는 숫자 세 개뿐이다: **현재 윈도우 누적 토큰 / burn rate / 리셋까지 남은 시간.**
UI는 없다. 네트워크 전송도 없다. 전부 로컬에서 끝난다.

## 왜 직접 만드나

[claude-monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor)가 이미 같은 일을
한다. 이 저장소는 그걸 **대조군**으로 쓴다 — 분석 로직은 베끼지 않고 직접 구현한 뒤,
항목별로 숫자를 맞춰본다. 맞추는 과정 자체가 목적이다.

## 데이터 소스

```
~/.claude/projects/<인코딩된-작업경로>/<세션-uuid>.jsonl                 메인 세션
~/.claude/projects/<인코딩된-작업경로>/<세션-uuid>/subagents/*.jsonl     서브에이전트
```

`CLAUDE_CONFIG_DIR`을 존중하고, `~/.config/claude`도 함께 본다.

문서화되지 않은 내부 포맷이라 CLI 업데이트마다 바뀔 수 있다. 실측 결과와 그 위에서
반드시 지켜야 하는 함정 네 개는 [CLAUDE.md](CLAUDE.md)에 정리돼 있다. **코드보다 그걸 먼저 읽어라.**

## 실행

```bash
py -3.12 -m ccpet.aggregate     # 숫자 세 개: 누적 토큰 / burn rate / 리셋까지
```

```bash
py -3.12 tests/test_parser.py && py -3.12 tests/test_aggregate.py
```

## 정확도

claude-monitor 4.0.0과 항목별 대조 (2026-09-04):

| 항목 | 우리 | 레퍼런스 | 차이 |
|---|---|---|---|
| input | 180 | 180 | 0 |
| output | 90,383 | 90,383 | 0 |
| cache_w | 310,805 | 310,805 | 0 |
| cache_r | 12,581,106 | 12,581,106 | 0 |

윈도우 경계도 일치. **총합만 비교하면 무효다** — 함정 1(과대)과 함정 2(과소)는 방향이
반대라 둘 다 틀려도 총합이 우연히 맞는다. 그래서 항상 네 항목을 따로 본다.

```bash
py -3.12 -m pip install claude-monitor
py -3.12 -m claude_monitor --once --output json > tests/reference/snapshot.json
py -3.12 -m ccpet.compare tests/reference/snapshot.json
```

## 프라이버시

`~/.claude/projects/` JSONL에는 실제 대화 본문이 들어 있다. 저장소에 실제 세션 파일을
커밋하지 않는다(`.gitignore`). 테스트 픽스처는 전부 손으로 만든 합성 데이터다.
로그에는 토큰 수와 모델명만 남긴다.
