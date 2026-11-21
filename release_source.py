"""Create a release archive containing only approved project source files."""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
SOURCE_FILES = """
.gitignore ACCEPTANCE.md AGENTS.md PRD.md README.md VERSION
app.py assets.js attachments.py backups.py browser.test.js catalog.py date-picker.js
exchange.py icon_import.py image_import.py index.html inventory.js inventory.py ledger.py
ocr-ui.js ocr.ps1 planning.py portfolio.py recognition_repair.py release_source.py
reports.js reports.test.js requirements.txt start.cmd style.css test.cmd
test_app.py test_catalog.py test_icon_import.py test_improvements.py test_inventory.py
test_ocr_repair.py test_portfolio.py test_workspace.py ui.js workspace-ui.js
""".split()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="Print the approved source file paths")
    args = parser.parse_args()
    files = [ROOT / name for name in SOURCE_FILES]
    if any(not path.is_file() or path.resolve().parent != ROOT for path in files):
        parser.error("A release source is missing or points outside the project")
    if args.list:
        print("\n".join(SOURCE_FILES))
        return
    version = (ROOT / "VERSION").read_text(encoding="ascii").strip()
    if not version or any(not part.isdecimal() for part in version.split(".")):
        parser.error("VERSION must contain a numeric release version")
    target = ROOT / "dist" / f"My-Record-APP-{version}-source.zip"
    target.parent.mkdir(exist_ok=True)
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.name)
    print(target)


if __name__ == "__main__":
    main()
