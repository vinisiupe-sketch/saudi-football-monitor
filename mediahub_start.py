"""Executa o monitor com tela virtual no servidor e encerra os processos juntos."""
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    display = None
    try:
        if sys.platform == "linux" and not os.environ.get("DISPLAY") and os.environ.get("MEDIAHUB_HEADLESS") != "1":
            display = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x720x24", "-nolisten", "tcp"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(100):
                if display.poll() is not None:
                    raise RuntimeError("A tela virtual não iniciou.")
                if Path("/tmp/.X11-unix/X99").exists():
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("Tempo esgotado ao iniciar a tela virtual.")
            os.environ["DISPLAY"] = ":99"
        # O driver do navegador deve herdar DISPLAY desde a sua criação.
        import runpy
        runpy.run_path(str(Path(__file__).with_name("mediahub_monitor.py")), run_name="__main__")
    finally:
        if display:
            display.terminate()
            try:
                display.wait(timeout=5)
            except subprocess.TimeoutExpired:
                display.kill()
                display.wait()


if __name__ == "__main__":
    main()
