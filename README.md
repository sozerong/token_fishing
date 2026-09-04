# token fishing

Claude Code 사용량을 낚시 도트 화면으로 보여주는 도구.
실행하면 **항상 위에 뜨는 작은 창**이 나타나 지금 얼마나 썼는지 보여준다.

```
조업량 = 이번 5시간 윈도우에서 쓴 토큰      물고기 마리 수, 등급
입질   = 분당 토큰 (burn rate)              물고기 헤엄 속도
해     = 리셋까지 남은 시간                 높으면 대낮, 낮으면 노을
```

숫자는 [claude-monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor)와
항목별로 대조해 **차이 0**을 확인했다. 아래 [정확도](#정확도) 참고.

## 설치

의존성이 없다. 받아서 바로 실행하면 된다.

```bash
git clone https://github.com/sozerong/token_fishing.git
cd token_fishing
```

**필요한 것**

- Python 3.11 이상
- tkinter — 파이썬 표준 설치에 들어 있다.
  Windows/macOS 공식 설치본은 그대로 있고, 일부 리눅스만 따로 깔아야 한다
  (Ubuntu/Debian: `sudo apt install python3-tk`)
- Claude Code를 한 번이라도 써서 `~/.claude/projects/` 아래에 세션 파일이 있어야 한다

확인:

```bash
python -c "import sys, tkinter; print(sys.version)"
```

> 위 출력이 3.11 미만이거나 `python`이 안 잡히면, 아래 예시의 `python`을
> `py -3.12`(Windows) 또는 `python3.12`로 바꿔 읽으면 된다.
> 여러 버전이 깔린 Windows에서는 `python`이 옛 버전을 가리키는 경우가 흔하다.

## 실행

### 1. 도트 팝업 (기본)

```bash
python -m ccpet
```

항상 위에 뜨는 창이 바로 열린다. 10초마다 스스로 갱신한다. 창을 닫으면 끝난다.

### 2. 콘솔 숫자만

```bash
python -m ccpet.aggregate
```

```
요청 1485개, 윈도우 16개

현재 윈도우  2026-09-04 13:00 ~ 18:00 UTC, 요청 72개
  input                144
  output            75,596
  cache_w          292,786
  cache_r        9,229,990
  합계           9,598,516
리셋까지     1시간 41분
burn rate    89,206 토큰/분 (최근 1시간)

provenance   {'stable': 1457, 'reconstructed_from_partial': 27, 'aborted_mid_stream': 1}
```

### 3. 브라우저 화면 (HTML)

```bash
python -m ccpet.render
```

자체 완결 HTML을 만들고 브라우저로 연다. 안에 **PiP 창으로 띄우기** 버튼이 있다.

> 브라우저 PiP는 버튼을 눌러야만 열린다. Document Picture-in-Picture API가 사용자
> 제스처를 요구하기 때문이고, 우회할 방법이 없다. 클릭 없이 바로 뜨는 창을 원하면
> `python -m ccpet`을 쓰면 된다.

## 데이터 소스

```
~/.claude/projects/<인코딩된-작업경로>/<세션-uuid>.jsonl                 메인 세션
~/.claude/projects/<인코딩된-작업경로>/<세션-uuid>/subagents/*.jsonl     서브에이전트
```

`CLAUDE_CONFIG_DIR`을 존중하고, `~/.config/claude`도 함께 본다.
**읽기만 한다.** 세션 파일을 고치거나 지우지 않는다.

문서화되지 않은 내부 포맷이라 CLI 업데이트마다 바뀔 수 있다. 실측 결과와 그 위에서
반드시 지켜야 하는 함정 네 개는 [CLAUDE.md](CLAUDE.md)에 정리돼 있다.
**코드보다 그걸 먼저 읽어라.**

## 정확도

`claude-monitor` 4.0.0과 항목별 대조 (2026-09-04):

| 항목 | 우리 | 레퍼런스 | 차이 |
|---|---|---|---|
| input | 180 | 180 | 0 |
| output | 90,383 | 90,383 | 0 |
| cache_w | 310,805 | 310,805 | 0 |
| cache_r | 12,581,106 | 12,581,106 | 0 |

윈도우 경계도 일치. **총합만 비교하면 무효다** — dedup 누락(과대)과 중간 스냅샷(과소)은
방향이 반대라 둘 다 틀려도 총합이 우연히 맞는다. 그래서 항상 네 항목을 따로 본다.

직접 대조해 보려면 (개발용, 런타임 의존성 아님):

```bash
python -m pip install claude-monitor
python -m claude_monitor --once --output json > tests/reference/snapshot.json
python -m ccpet.compare tests/reference/snapshot.json
```

## 테스트

```bash
python tests/test_parser.py
python tests/test_aggregate.py
python tests/test_state.py
python -m ccpet.paths          # 세션 파일 탐색 자체 점검
```

pytest 없이 그냥 돌아간다. 픽스처는 전부 손으로 만든 합성 데이터다.

## 구조

```
JSONL → [paths] → [parser] → UsageEntry → [aggregate] → Snapshot → [state] → GameState → 화면
                    ↑ JSONL 구조를 아는 유일한 층        ↑ 여기서만 숫자를 만든다
```

`state.py`는 새 숫자를 만들지 않는다. 화면도 마찬가지다.
새 집계가 필요하면 `aggregate`에 넣고 `compare`로 검증한 뒤 가져다 쓴다.

## 프라이버시

`~/.claude/projects/` JSONL에는 **실제 대화 본문이 들어 있다.**

- 저장소에 실제 세션 파일을 커밋하지 않는다 (`.gitignore`)
- 생성된 `tokenfishing.html`에는 실제 사용량이 박히므로 함께 무시한다
- 로그에는 토큰 수와 모델명만 남긴다. 프롬프트나 응답 본문은 찍지 않는다
- **네트워크 전송이 없다.** 전부 로컬에서 끝난다
