# token fishing

Claude Code 사용량을 픽셀 아트 낚시 화면으로 보여주는 항상-위 팝업입니다.

지금 얼마나 썼는지, 얼마나 빨리 쓰고 있는지, 언제 리셋되는지를 창 하나로 확인할 수
있습니다. 설정 화면을 열 필요가 없습니다.

| 화면 요소 | 의미 |
|---|---|
| 물고기 마리 수와 등급 | 이번 5시간 창에서 쓴 양 |
| 물고기가 헤엄치는 속도 | 분당 토큰 (burn rate) |
| 해의 높이 | 리셋까지 남은 시간 — 높으면 대낮, 낮으면 노을 |

등급은 창을 얼마나 채웠는지에 따라 **빈 바구니 → 잔챙이 → 반 바구니 → 한 바구니 →
만선** 순으로 올라갑니다.

- 런타임 의존성 없음 — 표준 라이브러리만 사용합니다
- 네트워크 전송 없음 — 모든 처리가 로컬에서 끝납니다
- 사용률과 리셋 시각은 Claude가 제공하는 공식 값을 그대로 사용합니다

### 표시 모드

창 아래 **모드** 버튼으로 전환하며, 선택은 저장됩니다.

| 모드 | 동작 |
|---|---|
| 축적 | 쓸수록 물고기가 늘어납니다. "오늘 얼마나 낚았나" |
| 고갈 | 가득 찬 바다에서 시작해 쓸수록 사라집니다. "얼마나 남았나" |

---

## 요구 사항

- Python 3.11 이상
- tkinter (표준 라이브러리 GUI 모듈)
- Claude Code 사용 기록 — `~/.claude/projects/`

설치된 환경을 먼저 확인합니다.

```bash
python3 -c "import sys, tkinter; print(sys.version)"
```

`ModuleNotFoundError: No module named 'tkinter'` 가 나오면 아래를 설치합니다.

| 환경 | 명령 |
|---|---|
| Debian · Ubuntu | `sudo apt install python3-tk` |
| Fedora · RHEL | `sudo dnf install python3-tkinter` |
| Arch | `sudo pacman -S tk` |
| macOS (Homebrew Python) | `brew install python-tk` |
| macOS (python.org 설치본) | 이미 포함되어 있습니다 |
| Windows | 이미 포함되어 있습니다 |

---

## 설치

### macOS · Linux

```bash
pip3 install git+https://github.com/sozerong/token_fishing.git
```

### Windows

```powershell
py -3.12 -m pip install git+https://github.com/sozerong/token_fishing.git
```

설치하면 `tokenfishing`(팝업)과 `tokenfishing-console`(콘솔 출력) 명령이 생성됩니다.

<details>
<summary>다른 설치 방법</summary>

```bash
# 전역 환경을 건드리지 않고 설치
pipx install git+https://github.com/sozerong/token_fishing.git

# 설치 없이 즉시 실행
uvx --from git+https://github.com/sozerong/token_fishing.git tokenfishing

# 소스를 수정할 경우
git clone https://github.com/sozerong/token_fishing.git
cd token_fishing
pip3 install -e .
```

소스에서 직접 실행할 때는 저장소 루트에서 `python3 -m ccpet` 를 사용합니다.
</details>

---

## 사용

```bash
tokenfishing
```

항상 위에 표시되는 창이 열리고 10초마다 갱신됩니다. 창을 닫으면 종료됩니다.

### 명령행 옵션

```
tokenfishing [옵션]

  -d, --detach            백그라운드로 실행하고 셸을 즉시 반환합니다
      --debug             진단 로그를 stderr로 출력합니다
      --doctor            사용량 데이터 소스를 진단하고 종료합니다
      --install-statusline
                          Claude Code 상태줄 훅을 등록합니다
  -V, --version           버전을 출력합니다
  -h, --help              도움말을 출력합니다
```

터미널을 계속 쓰려면 `-d` 로 띄웁니다. Windows에서는 `pythonw` 로 실행되어 콘솔
창이 함께 뜨지 않고, macOS·Linux에서는 새 세션으로 분리되어 터미널을 닫아도
살아 있습니다.

```bash
tokenfishing -d
# 백그라운드 실행 중 (PID 18556)
```

종료할 때는 창을 닫거나 프로세스를 종료합니다.

```bash
pkill -f "ccpet"                       # macOS · Linux
taskkill /F /IM pythonw.exe            # Windows
```

### 콘솔 출력

숫자만 필요하면 콘솔 명령을 사용합니다.

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

브라우저용 HTML은 `python3 -m ccpet.render` 로 생성할 수 있습니다.

---

## 사용률은 어디서 오나

사용률은 두 곳에서 읽으며, **항목마다 더 정확한 쪽을 선택**합니다.

| 소스 | 갱신 주기 | 장점 | 필요 조건 |
|---|---|---|---|
| Claude 데스크톱 앱 기록 | 5–15분 | 설정 불필요. 웹·모바일 사용량까지 포함 | 데스크톱 앱 (Windows · macOS) |
| Claude Code 상태줄 훅 | 대화 턴마다 | 정확한 리셋 시각. 실시간 | 훅 등록 + Pro/Max |

데스크톱 앱 기록의 위치는 다음과 같습니다.

| 플랫폼 | 경로 |
|---|---|
| Windows | `%APPDATA%\Claude\plan-usage-history.json` |
| macOS | `~/Library/Application Support/Claude/plan-usage-history.json` |
| Linux | `~/.config/Claude/plan-usage-history.json` |

> **Windows 참고**
> Claude 데스크톱 앱이 MSIX(스토어) 패키지로 설치된 경우 위 경로에 대한 쓰기가
> `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\` 로 리디렉션됩니다.
> token fishing은 두 경로를 모두 확인하므로 별도 설정이 필요하지 않습니다.

> **Linux 참고**
> Claude 데스크톱 앱은 Linux를 지원하지 않습니다. Linux에서는 상태줄 훅을
> 등록해야 공식 사용률을 받을 수 있습니다.

### 창 제목으로 출처 확인

창 제목에 버전과 데이터 출처가 함께 표시됩니다.

| 제목 | 의미 |
|---|---|
| `token fishing 0.6.0 · 공식·훅` | 상태줄 훅에서 받은 실시간 공식 값 |
| `token fishing 0.6.0 · 공식·앱` | 데스크톱 앱 기록의 공식 값 (최대 15분 지연) |
| `token fishing 0.6.0 · 어림(공식수치 없음)` | 공식 값을 받지 못해 자체 추정치로 표시 중 |

리셋까지 남은 시간 앞의 `~` 는 계산으로 추정한 값이라는 표시입니다. 상태줄 훅이
동작하면 사라집니다.

### 상태줄 훅 등록

정확한 리셋 시각이 필요하거나 Linux를 사용한다면 훅을 등록합니다.

```bash
tokenfishing --install-statusline
```

`~/.claude/settings.json` 이 백업된 뒤 `statusLine` 항목만 추가됩니다. 등록 후
Claude Code를 다시 시작하면 적용되며, 상태줄에도 사용률 한 줄이 표시됩니다.

`rate_limits` 는 Pro/Max 구독에서, 세션의 첫 API 응답 이후에 전달됩니다. 훅이
실행되었는데도 진단에 `five_hour=(비어 있음)` 으로 나온다면 해당 클라이언트가
`rate_limits` 를 전달하지 않는 경우이며, 이때는 데스크톱 앱 기록이 사용됩니다.

리셋 시각을 직접 지정할 수도 있습니다. Claude 설정 → 사용량의 "N시간 M분 후
재설정"을 시계 시각으로 환산해 넣습니다.

```bash
export TOKENFISHING_RESET_AT=05:17
```

---

## 문제 해결

제목에 `어림(공식수치 없음)` 이 표시되면 진단을 실행합니다.

```bash
tokenfishing --doctor
```

```
python      /usr/bin/python3
APPDATA     (none)
앱 기록     ~/Library/Application Support/Claude/plan-usage-history.json
  읽기      OK (135,423 바이트)
  version   2
  samples   1514개 (원본)
  파싱      1514개
  최신      12:20:27  fh=75 sd=33
  clean_pct fh→75.0  sd→33.0
  latest()  OK
상태줄 훅   ~/.claude/tokenfishing-limits.json
  캡처      2026-09-05T03:22:22+00:00  five_hour=(비어 있음)

판정        사용률 출처=app  값=75.0  주간=33.0
            리셋=16:32 추정
```

| 진단 결과 | 조치 |
|---|---|
| `후보가 전부 비었다` | 데스크톱 앱을 실행한 상태로 15분 정도 기다립니다 |
| `읽기 실패` | 파일 권한을 확인합니다 |
| `캡처 없음` + 앱 기록도 없음 | `--install-statusline` 후 Claude Code를 재시작합니다 |
| `five_hour=(비어 있음)` | 해당 세션이 `rate_limits` 를 전달하지 않습니다. 앱 기록이 사용됩니다 |

동작 중인 값의 출처를 추적하려면 `--debug` 를 사용합니다.

```bash
tokenfishing --debug
# [tokenfishing] start fill=official official=app pct=64.0 left=270 mode=depletion
```

---

## 설정

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Claude 설정 폴더 |
| `TOKENFISHING_RESET_AT` | (없음) | 5시간 리셋 시각 직접 지정 |
| `TOKENFISHING_WEEKLY_RESET_DAY` | `1` (화) | 주간 리셋 요일 — 월=0 … 일=6 |

표시 모드는 `~/.claude/tokenfishing-config.json` 에 저장됩니다.

---

## 표시하는 값과 표시하지 않는 값

표시하는 값입니다.

- 현재 5시간 창의 input · output · 캐시 쓰기 · 캐시 읽기 토큰과 요청 수
- 사용률과 리셋까지 남은 시간
- burn rate (최근 1시간 기준 분당 토큰)
- 주간 사용량, 모델별 분포, 전체 누적

표시하지 않는 값입니다.

- **한도 대비 퍼센트를 추정한 값** — 공식 사용률을 받지 못하면 추정치임을 명시합니다
- **소진 예측** — 추정된 한도 위에 쌓인 값이라 신뢰할 수 없습니다
- **비용 환산** — 구독 사용자는 토큰당 과금되지 않으므로 실제 지출이 아닙니다

공식 값을 뒤처짐만큼 보정해 앞당기는 기능도 두지 않습니다. 실측 검증에서 중앙값은
1.3%p 개선되었지만 최악의 경우 68%p를 과대 표시했고, 오차가 항상 100% 방향으로
치우쳤습니다. 15분 지연된 정확한 값이 앞당겨진 부정확한 값보다 낫다고 판단했습니다.

---

## 동작 방식

Claude Code가 세션마다 남기는 로그를 읽습니다. **읽기만 하며 아무것도 수정하지
않습니다.**

```
~/.claude/projects/<프로젝트>/<세션>.jsonl                 메인 세션
~/.claude/projects/<프로젝트>/<세션>/subagents/*.jsonl     서브에이전트
```

로그에는 대화 내용이 포함되어 있지만 이 도구는 토큰 수와 모델 이름만 사용합니다.
프롬프트와 응답 본문은 읽지도, 기록하지도, 외부로 전송하지도 않습니다.

---

## 개발

```bash
git clone https://github.com/sozerong/token_fishing.git
cd token_fishing
pip3 install -e .
```

테스트는 pytest로도, 단독으로도 실행됩니다.

```bash
pytest tests -q

python3 tests/test_parser.py
python3 tests/test_aggregate.py
python3 tests/test_plan_usage.py
python3 tests/test_state.py
```

테스트 데이터는 전부 손으로 작성한 합성 로그입니다. 실제 세션 파일은 대화 내용을
포함하므로 저장소에 커밋하지 않습니다.

집계 정확도는 참조 구현(claude-monitor)과 항목별로 대조해 검증합니다.

```bash
pip3 install claude-monitor
python3 -m claude_monitor --once --output json > tests/reference/snapshot.json
python3 -m ccpet.compare tests/reference/snapshot.json
```

내부 구조와 로그 파싱 시 주의할 점은 [CLAUDE.md](CLAUDE.md)에 정리되어 있습니다.

---

## 라이선스

MIT — [LICENSE](LICENSE)
