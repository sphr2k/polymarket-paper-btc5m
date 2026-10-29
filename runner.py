"""Run read-only collector and dashboard together on one small Fly Machine."""
import os
import signal
import subprocess
import sys
import time

processes = []
terminating = False

def stop(_sig, _frame):
    global terminating
    terminating = True
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
os.makedirs(os.path.dirname(os.environ.get("PAPER_DB", "/data/paper.sqlite3")), exist_ok=True)
processes.append(subprocess.Popen([sys.executable, "-u", "/app/paper_btc5m.py", "run", "--interval", "15"]))
processes.append(subprocess.Popen([sys.executable, "-u", "/app/dashboard.py"]))
try:
    while not terminating:
        for proc in processes:
            if proc.poll() is not None:
                print(f"Child {proc.args!r} exited with code {proc.returncode}", flush=True)
                terminating = True
                break
        if not terminating:
            time.sleep(1)
finally:
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
    for proc in processes:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
sys.exit(0 if terminating and all(p.returncode in (0, -15) for p in processes) else 1)
