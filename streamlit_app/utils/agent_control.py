"""Agent 프로세스 제어 유틸 (Start / Stop / Pause / Resume)."""
import os
import sys
import signal
import subprocess
from pathlib import Path

_ROOT       = Path(__file__).resolve().parent.parent.parent
_RUNTIME    = _ROOT / "runtime"
_PID_FILE   = _RUNTIME / "agent.pid"
_PAUSE_FILE = _RUNTIME / "agent.pause"
_MAIN_PY    = _ROOT / "main.py"


# ── 상태 조회 ─────────────────────────────────────────────────────────────────

def _read_pid() -> int | None:
    try:
        return int(_PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def get_status() -> dict:
    """현재 에이전트 상태를 반환."""
    pid = _read_pid()
    running = pid is not None and _pid_alive(pid)
    if not running and _PID_FILE.exists():
        _PID_FILE.unlink(missing_ok=True)   # 좀비 PID 파일 정리
    paused  = running and _PAUSE_FILE.exists()
    return {
        "running": running,
        "paused":  paused,
        "pid":     pid if running else None,
        "label":   ("🟡 일시정지 중" if paused else "🟢 실행 중") if running else "🔴 중지됨",
    }


# ── 제어 함수 ─────────────────────────────────────────────────────────────────

def start() -> str:
    st = get_status()
    if st["running"]:
        return "이미 실행 중입니다."
    _RUNTIME.mkdir(exist_ok=True)
    _PAUSE_FILE.unlink(missing_ok=True)
    subprocess.Popen(
        [sys.executable, str(_MAIN_PY)],
        cwd=str(_ROOT),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    return "에이전트를 시작했습니다."


def stop() -> str:
    st = get_status()
    if not st["running"]:
        return "실행 중인 에이전트가 없습니다."
    pid = st["pid"]
    try:
        if os.name == "nt":
            subprocess.call(["taskkill", "/F", "/PID", str(pid)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
        _PID_FILE.unlink(missing_ok=True)
        _PAUSE_FILE.unlink(missing_ok=True)
        return f"에이전트(PID {pid})를 중지했습니다."
    except Exception as e:
        return f"중지 실패: {e}"


def pause() -> str:
    st = get_status()
    if not st["running"]:
        return "실행 중인 에이전트가 없습니다."
    if st["paused"]:
        return "이미 일시정지 중입니다."
    _PAUSE_FILE.touch()
    return "일시정지 신호를 보냈습니다."


def resume() -> str:
    st = get_status()
    if not st["running"]:
        return "실행 중인 에이전트가 없습니다."
    if not st["paused"]:
        return "일시정지 상태가 아닙니다."
    _PAUSE_FILE.unlink(missing_ok=True)
    return "재개했습니다."
