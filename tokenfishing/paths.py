"""세션 JSONL 파일 탐색. 파일시스템 레이아웃을 아는 유일한 모듈."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from pathlib import Path

# 실측(Windows, CLI 2.1.x)은 ~/.claude, claude-monitor의 기본값은 ~/.config/claude.
# 둘 다 본다. 없는 경로는 조용히 건너뛴다.
DEFAULT_CONFIG_DIRS = ("~/.claude", "~/.config/claude")


def config_dirs() -> list[Path]:
    """CLAUDE_CONFIG_DIR이 있으면 그것만, 없으면 기본 후보 전부."""
    env = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if env:
        # 여러 경로를 os.pathsep으로 넘기는 관행을 존중한다.
        return [Path(p).expanduser() for p in env.split(os.pathsep) if p.strip()]
    return [Path(p).expanduser() for p in DEFAULT_CONFIG_DIRS]


def session_files(dirs: Iterable[Path] | None = None) -> Iterator[Path]:
    """모든 세션 JSONL을 경로순으로 내놓는다. 같은 실경로는 한 번만.

    두 종류를 모두 포함한다 (함정 3):
        projects/<enc>/<uuid>.jsonl                      메인 세션
        projects/<enc>/<uuid>/subagents/agent-<id>.jsonl 서브에이전트
    서브에이전트를 빼면 토큰이 통째로 빠지고, message.id가 겹치지 않으므로
    둘 다 세도 이중계상되지 않는다.
    """
    seen: set[Path] = set()
    for d in config_dirs() if dirs is None else dirs:
        projects = d / "projects"
        if not projects.is_dir():
            continue
        # ponytail: rglob 하나로 메인/서브에이전트 둘 다 잡힌다. 글롭 두 개 안 쓴다.
        for f in sorted(projects.rglob("*.jsonl")):
            try:
                key = f.resolve()
            except OSError:
                key = f.absolute()
            if key not in seen:
                seen.add(key)
                yield f


def is_subagent(path: Path) -> bool:
    """서브에이전트 트랜스크립트인가. 함정 2(중간 스냅샷)가 여기서만 관찰됐다."""
    return "subagents" in path.parts


def _selfcheck() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "cfg"
        main = root / "projects" / "C--proj" / "s1.jsonl"
        sub = root / "projects" / "C--proj" / "s1" / "subagents" / "agent-x.jsonl"
        noise = root / "projects" / "C--proj" / "memory" / "notes.md"
        for p in (main, sub, noise):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("", encoding="utf-8")

        found = list(session_files([root]))
        assert main in found, found
        assert sub in found, "서브에이전트 파일이 빠졌다 (함정 3)"
        assert noise not in found, ".jsonl 아닌 파일이 섞였다"
        assert len(found) == 2, found

        assert is_subagent(sub) and not is_subagent(main)

        # 중복 디렉터리를 줘도 한 번만 나와야 한다
        assert len(list(session_files([root, root]))) == 2

        # 없는 경로는 조용히 무시
        assert list(session_files([Path(tmp) / "nope"])) == []

        # CLAUDE_CONFIG_DIR 존중
        os.environ["CLAUDE_CONFIG_DIR"] = str(root)
        try:
            assert config_dirs() == [root]
        finally:
            del os.environ["CLAUDE_CONFIG_DIR"]

    print("paths.py selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
