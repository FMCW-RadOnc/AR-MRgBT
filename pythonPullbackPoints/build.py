"""Build with the installed MIM Python decorator; vendor code is not redistributed."""
import argparse
import importlib
from pathlib import Path
import sys
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mim-support", default=
                        "C:/Program Files/MIM Software/MIM/resources/python/py_support.zip")
    args = parser.parse_args()
    support = Path(args.mim_support)
    if not support.is_file():
        parser.error("Supply the installed MIM resources/python/py_support.zip")
    root = Path(__file__).resolve().parent
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(root / "src"), str(support)]
    ext = importlib.import_module("ext")
    metadata = {"ENTRY_COUNT": 1, "EXTENSION_TYPE": "Python"}
    metadata.update(ext.run.info)
    destination = root / "dist" / "pythonPullbackPoints.zip"
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("info.properties", "\n".join(
            "{}={}".format(k, v) for k, v in metadata.items()) + "\n")
        for path in sorted((root / "src").glob("*.py")):
            archive.write(path, "src/" + path.name)
    print(destination)


if __name__ == "__main__":
    main()
