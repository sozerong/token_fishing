"""상태줄 훅. 남의 상태줄을 뺏지 않고 앞에 서는 게 핵심이다.

pytest 없이도 돌아간다:  py -3.12 tests/test_statusline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tokenfishing import statusline  # noqa: E402


def test_only_recognises_its_own_command():
    """이름에 statusline이 들어간 남의 훅을 제 것으로 착각하면 안 된다.

    실제로 겪은 사례: 플러그인이 `ponytail-statusline.sh`를 걸어 뒀는데,
    파일명만 비교하니 우리 것으로 보여서 덮어쓸 뻔했다.
    """
    theirs = [
        'bash "/Users/me/plugins/hooks/ponytail-statusline.sh"',
        'py -3.12 "/tmp/other-statusline.py"',
        "starship prompt",
        "",
    ]
    for cmd in theirs:
        assert not statusline.is_ours(cmd), cmd

    ours = [
        '"/usr/bin/python3" "/home/me/site-packages/tokenfishing/statusline.py"',
        r'"C:\Py\python.exe" "C:\lib\tokenfishing\statusline.py" --chain',
    ]
    for cmd in ours:
        assert statusline.is_ours(cmd), cmd


def test_chain_keeps_the_original_visible(tmp_path, monkeypatch):
    """이어붙이면 화면에는 원래 상태줄이 그대로 보이고, 우리는 조용히 받아 적는다."""
    import json
    from datetime import datetime, timedelta, timezone

    other = tmp_path / "other.py"
    other.write_text(
        "import sys, json\n"
        "json.load(sys.stdin)\n"
        "print('ORIGINAL LINE')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(statusline, "STATE_PATH", tmp_path / "limits.json")
    monkeypatch.setattr(statusline, "CHAIN_PATH", tmp_path / "chain.json")
    statusline.save_chain(f'"{sys.executable}" "{other}"')

    resets = (datetime.now(timezone.utc) + timedelta(hours=2)).timestamp()
    payload = json.dumps({
        "rate_limits": {
            "five_hour": {"used_percentage": 47, "resets_at": resets},
            "seven_day": {"used_percentage": 60},
        }
    })

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        statusline.run_chained(payload)

    assert buf.getvalue().strip() == "ORIGINAL LINE", "원래 상태줄이 그대로 보여야 한다"

    saved = json.loads((tmp_path / "limits.json").read_text(encoding="utf-8"))
    assert saved["rate_limits"]["five_hour"]["used_percentage"] == 47, "받아 적기는 했어야"
    assert saved["captured_at"], "언제 받았는지도 남겨야 한다"


def test_uninstall_only_touches_the_paths_it_was_given(tmp_path, monkeypatch):
    """지우는 파일은 전부 모듈 상수를 거쳐야 한다.

    예전엔 uninstall()이 설정 파일 경로를 그 자리에서 만들어 썼다. 그래서 경로를
    갈아끼운 시험 실행이 **진짜 설정 파일을 지웠다.** 실제로 한 번 날렸다.
    """
    import json

    monkeypatch.setattr(statusline, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(statusline, "STATE_PATH", tmp_path / "limits.json")
    monkeypatch.setattr(statusline, "CHAIN_PATH", tmp_path / "chain.json")
    monkeypatch.setattr(statusline, "CONFIG_PATH", tmp_path / "config.json")
    for name in ("limits.json", "chain.json", "config.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    statusline.SETTINGS_PATH.write_text(json.dumps(
        {"statusLine": {"type": "command", "command": statusline.hook_command()}}
    ), encoding="utf-8")

    real = Path.home() / ".claude" / "tokenfishing-config.json"
    before = real.exists()
    statusline.uninstall()

    assert not (tmp_path / "config.json").exists(), "준 경로는 지웠어야 한다"
    assert real.exists() == before, "홈 디렉터리의 진짜 설정 파일은 건드리면 안 된다"


def test_chain_falls_back_when_the_original_is_gone(tmp_path, monkeypatch):
    """플러그인 경로는 세션마다 바뀐다. 원래 게 사라져도 빈 줄을 내면 안 된다."""
    import io
    import json
    from contextlib import redirect_stdout
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(statusline, "STATE_PATH", tmp_path / "limits.json")
    monkeypatch.setattr(statusline, "CHAIN_PATH", tmp_path / "chain.json")
    statusline.save_chain(f'"{sys.executable}" "{tmp_path / "gone.py"}"')

    resets = (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
    payload = json.dumps({
        "rate_limits": {"five_hour": {"used_percentage": 12, "resets_at": resets}}
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        statusline.run_chained(payload)

    assert "12%" in buf.getvalue(), "원래 게 죽으면 우리 줄이라도 나와야 한다"


def main() -> int:
    import tempfile

    class Patch:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            if "tmp_path" in fn.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d), Patch())
            else:
                fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
        else:
            print(f"ok   {name}")
    print(f"\n{'실패 ' + str(failed) if failed else '전부 통과'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
