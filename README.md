# token fishing

Claude 사용량을 낚시 도트 화면으로 보여주는 항상-위 팝업.

지금 얼마나 썼는지, 얼마나 빨리 쓰고 있는지, 언제 리셋되는지를 창 하나로 보여준다.
설정 화면을 열지 않아도 곁눈으로 확인된다.

```
조업량   이번 5시간 창에서 쓴 양      물고기 마리 수와 등급
입질     분당 토큰                    물고기가 헤엄치는 속도
해       리셋까지 남은 시간           높으면 대낮, 낮으면 노을
```

등급은 얼마나 찼는지에 따라 **빈 바구니 → 잔챙이 → 반 바구니 → 한 바구니 → 만선**으로 오른다.

### 두 가지 모드

창 아래 **모드** 버튼을 누르면 바뀐다. 선택은 저장된다.

| 모드 | 바다 |
|---|---|
| **축적** | 쓸수록 물고기가 늘어난다. 오늘 얼마나 낚았는지 |
| **고갈** | 가득 찬 바다에서 시작해 쓸수록 사라진다. 얼마나 남았는지 |

고갈 모드는 "얼마나 남았나"를 알아야 하므로 사용률이 필요하다. 사용률은 자동으로
읽어오므로 따로 설정할 게 없다.

- 의존성 0. 표준 라이브러리만 쓴다
- 네트워크 전송 없음. 전부 로컬에서 끝난다
- 사용량 수치는 Claude가 알려주는 공식 값을 그대로 쓴다

## 설치

```bash
pip install git+https://github.com/sozerong/token_fishing.git
```

`tokenfishing`(팝업)과 `tokenfishing-console`(콘솔) 명령이 생긴다.

<details>
<summary>다른 방법</summary>

```bash
# 전역 환경을 건드리지 않고
pipx install git+https://github.com/sozerong/token_fishing.git

# 설치 없이 그 자리에서 실행
uvx --from git+https://github.com/sozerong/token_fishing.git tokenfishing

# 코드를 고칠 거면
git clone https://github.com/sozerong/token_fishing.git
cd token_fishing && python -m ccpet
```
</details>

**필요한 것**

- Python 3.11 이상
- tkinter — 파이썬 표준 설치에 들어 있다.
  Ubuntu/Debian만 따로 필요하다: `sudo apt install python3-tk`
- Claude Code 사용 기록 (`~/.claude/projects/`)

```bash
python -c "import sys, tkinter; print(sys.version)"
```

> 3.11 미만이 뜨거나 `python`이 안 잡히면 아래 예시의 `python`을
> `py -3.12`(Windows) 또는 `python3.12`로 바꿔 읽으면 된다.

## 수치는 어디서 오나

사용률은 Claude 데스크톱 앱이 남기는 플랜 사용량 기록에서 읽는다. 계정 기준
공식 수치라 claude.ai 웹이나 모바일에서 쓴 양까지 들어 있다. **따로 설정할 게 없다.**

앱은 15분마다 기록하므로 그 사이 값은 로그로 보정해 채운다. 리셋 시각은
사용률이 리셋된 지점을 찾아 계산한다.

<details>
<summary>리셋 시각을 더 정확히 맞추려면</summary>

Claude Code 상태줄 훅을 등록하면 정확한 리셋 시각을 받아온다.

```bash
tokenfishing --install-statusline
```

등록 후 Claude Code를 새로 시작하면 적용된다. `~/.claude/settings.json`은
백업된 뒤 `statusLine` 항목만 추가되고, 상태줄에도 한 줄이 뜬다.

직접 넣어도 된다 — Claude 설정 → 사용량의 "N시간 M분 후 재설정"을 시계 시각으로:

```bash
export TOKENFISHING_RESET_AT=05:17
```

시각 앞에 `~`가 붙어 있으면 계산으로 맞춘 값이라는 뜻이다.
</details>

## 사용

```bash
tokenfishing
```

항상 위에 뜨는 창이 열린다. 10초마다 갱신되고, 닫으면 끝난다.

숫자만 보고 싶으면:

```bash
tokenfishing-console
```

```
현재 윈도우  2026-09-04 15:11 ~ 20:11 UTC, 요청 152개
  input                304
  output           143,128
  cache_w          406,903
  cache_r       33,867,920
리셋까지     2시간 30분
burn rate    89,206 토큰/분 (최근 1시간)

주간         09-01 00:00 부터, 요청 564개
  조업량           612,526
  전체         111,679,086

모델별 (조업량 기준)
  claude-opus-5                    911,680   63.9%  요청 1020
  claude-sonnet-5                  489,631   34.3%  요청 524
```

브라우저에서 보려면 `python -m ccpet.render`로 HTML을 만들 수 있다.
(브라우저 PiP 버튼 포함 — PiP는 브라우저 규칙상 클릭이 필요하다)

## 설정

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Claude 설정 폴더 |
| `TOKENFISHING_RESET_AT` | (없음) | 5시간 리셋 시각 직접 지정 |
| `TOKENFISHING_WEEKLY_RESET_DAY` | `1` (화) | 주간 리셋 요일, 월=0 … 일=6 |

모드와 플랜 선택은 `~/.claude/tokenfishing-config.json`에 저장된다.

## 보여주는 값

- 현재 5시간 창의 input / output / 캐시 쓰기 / 캐시 읽기, 요청 수
- 사용률과 리셋까지 남은 시간
- burn rate (최근 1시간 기준 분당 토큰)
- 주간 사용량, 모델별 분포, 전체 누적

사용률과 리셋 시각은 Claude가 준 공식 값이다. 한도를 짐작해서 만들어낸 퍼센트나
소진 예측은 표시하지 않는다.

## 동작 방식

Claude Code가 세션마다 남기는 로그를 읽는다. **읽기만 하고 아무것도 고치지 않는다.**

```
~/.claude/projects/<프로젝트>/<세션>.jsonl                 메인 세션
~/.claude/projects/<프로젝트>/<세션>/subagents/*.jsonl     서브에이전트
```

로그에는 대화 내용이 들어 있지만, 이 도구는 토큰 수와 모델 이름만 꺼내 쓴다.
프롬프트나 응답 본문은 읽지도, 기록하지도, 어디로 보내지도 않는다.

## 개발

```bash
python tests/test_parser.py
python tests/test_aggregate.py
python tests/test_state.py
```

pytest 없이 돌아간다. 테스트 데이터는 전부 손으로 만든 합성 로그다.

내부 구조와 파싱 시 주의할 점은 [CLAUDE.md](CLAUDE.md)에 정리돼 있다.

## 라이선스

MIT — [LICENSE](LICENSE)
