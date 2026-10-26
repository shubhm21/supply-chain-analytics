"""Run the full supply-chain analytics pipeline end to end."""
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
STEPS = [
    "01_generate_data.py",
    "02_clean_data.py",
    "03_run_sql.py",
    "04_eda_abc.py",
    "05_forecast.py",
    "06_inventory_policy.py",
    "07_build_excel.py",
]

if __name__ == "__main__":
    start = time.time()
    for step in STEPS:
        print(f"\n=== {step} ===", flush=True)
        subprocess.run([sys.executable, str(SRC / step)], check=True)
    print(f"\nPipeline finished in {time.time() - start:.1f}s")
