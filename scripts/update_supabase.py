import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sandan_rag.bootstrap import configure_utf8

configure_utf8()


def run_command(command: list[str]) -> None:
    print(f"[RUN] {' '.join(command)}")
    result = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=300)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-upload-files", action="store_true")
    args = parser.parse_args()

    collect_cmd = [sys.executable, "scripts/collect_data.py", "--max-pages", str(args.max_pages)]
    if args.full:
        collect_cmd.append("--full")
    run_command(collect_cmd)

    migrate_cmd = [sys.executable, "scripts/migrate_local_to_supabase.py"]
    if args.force:
        migrate_cmd.append("--force")
    if args.no_upload_files:
        migrate_cmd.append("--no-upload-files")
    run_command(migrate_cmd)


if __name__ == "__main__":
    main()
