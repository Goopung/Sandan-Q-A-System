import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sandan_rag.bootstrap import configure_utf8
from sandan_collector import SandanAttachmentCollector
from sandan_rag.config import get_config


configure_utf8()


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect KHU research administration attachments.")
    parser.add_argument("--output-dir", type=str, default="data/sandan_attachment_kb")
    parser.add_argument("--sleep-sec", type=float, default=0.35)
    parser.add_argument("--timeout", type=int, default=40)
    parser.add_argument("--max-pages", type=int, default=300)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--show-pdf-warnings", action="store_true")
    parser.add_argument("--no-pdf-repair", action="store_true")
    args = parser.parse_args()
    config = get_config()

    collector = SandanAttachmentCollector(
        output_dir=args.output_dir,
        sleep_sec=args.sleep_sec,
        timeout=args.timeout,
        max_pages=args.max_pages,
        full=args.full,
        suppress_pdf_warnings=not args.show_pdf_warnings,
        repair_pdf=not args.no_pdf_repair,
        state_db_path=str(config.collection_state_path),
    )
    collector.run()


if __name__ == "__main__":
    main()
