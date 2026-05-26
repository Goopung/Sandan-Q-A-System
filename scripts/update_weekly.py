import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_command(command: list[str]) -> str:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    print("[RUN]", " ".join(command))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if output.strip():
        print(output[-8000:])
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{output[-8000:]}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly update: collect new data and update index.")
    parser.add_argument("--full", action="store_true", help="Re-download all files and rebuild changed records.")
    parser.add_argument("--force-index", action="store_true", help="Force re-index all records.")
    parser.add_argument("--max-pages", type=int, default=300)
    parser.add_argument("--show-pdf-warnings", action="store_true")
    parser.add_argument("--no-pdf-repair", action="store_true")
    args = parser.parse_args()

    collect_command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "collect_data.py"),
        "--max-pages",
        str(args.max_pages),
    ]
    if args.full:
        collect_command.append("--full")
    if args.show_pdf_warnings:
        collect_command.append("--show-pdf-warnings")
    if args.no_pdf_repair:
        collect_command.append("--no-pdf-repair")

    index_command = [sys.executable, str(PROJECT_ROOT / "scripts" / "build_index.py")]
    if args.force_index:
        index_command.append("--force")

    run_command(collect_command)
    run_command(index_command)
    print("[UPDATE DONE]")


if __name__ == "__main__":
    main()
