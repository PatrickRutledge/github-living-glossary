"""Rebuild project paths from a downloaded GitHub Gist archive."""
import argparse
from pathlib import Path
from zipfile import ZipFile


PREFIX = "github-living-glossary__"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, default=Path("github-living-glossary"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.archive) as archive:
        files = [entry for entry in archive.infolist() if not entry.is_dir()]
        restored = 0
        for entry in files:
            name = Path(entry.filename).name
            if not name.startswith(PREFIX):
                continue
            relative = Path(name[len(PREFIX):].replace("__", "/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unsafe archive path: {relative}")
            destination = args.output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(entry))
            restored += 1
    if not restored:
        raise ValueError("No project files found in archive")
    print(f"Restored {restored} project files into {args.output}")


if __name__ == "__main__":
    main()
