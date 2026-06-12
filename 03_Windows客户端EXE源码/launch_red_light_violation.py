import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_TITLE = "Smart Traffic Assistant"
DEFAULT_PYTHONW = Path(r"C:\Users\Username\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe")


def show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(0, message, APP_TITLE, 0x10)


def find_pythonw() -> tuple[list[str], str]:
    env_python = os.environ.get("RED_LIGHT_PYTHON", "").strip()
    if env_python and Path(env_python).exists():
        return [env_python], env_python

    if DEFAULT_PYTHONW.exists():
        return [str(DEFAULT_PYTHONW)], str(DEFAULT_PYTHONW)

    pythonw = shutil.which("pythonw.exe") or shutil.which("pythonw")
    if pythonw:
        return [pythonw], pythonw

    pyw = shutil.which("pyw.exe") or shutil.which("pyw")
    if pyw:
        return [pyw, "-3"], pyw

    python = shutil.which("python.exe") or shutil.which("python")
    if python:
        return [python], python

    py = shutil.which("py.exe") or shutil.which("py")
    if py:
        return [py, "-3"], py

    raise FileNotFoundError("No usable Python interpreter was found.")


def main() -> None:
    launcher_path = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    base_dir = launcher_path.parent
    script_path = base_dir / "red_light_violation_gui.py"

    if not script_path.exists():
        show_error(f"Cannot find GUI script:\n{script_path}")
        raise SystemExit(1)

    try:
        python_cmd, python_display = find_pythonw()
    except FileNotFoundError as exc:
        show_error(
            "Python runtime was not found.\n\n"
            "Please make sure this machine still has the Python environment used for this tool,\n"
            "or set RED_LIGHT_PYTHON to a valid pythonw.exe path.\n\n"
            f"Details:\n{exc}"
        )
        raise SystemExit(1)

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        subprocess.Popen(
            [*python_cmd, str(script_path)],
            cwd=str(base_dir),
            env=env,
        )
    except Exception as exc:
        show_error(
            "Failed to launch the GUI.\n\n"
            f"Python: {python_display}\n"
            f"Script: {script_path}\n\n"
            f"Error:\n{exc}"
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
