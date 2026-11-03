"""Export only reviewed source roots, excluding private jobs, builds, and environments."""
import hashlib
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release"
ROOT_FILES = {"README.md", "README.upstream.md", "LICENSE", "NOTICE.md", "UPSTREAM.md",
              "VALIDATION.md", "pyproject.toml", "requirements-build.txt",
              "requirements-build-lock.txt", "Start.cmd", "CONTRIBUTING.md",
              ".gitignore", ".gitattributes", "run.py"}
ROOTS = ("codex_relocate", "tests", "docs", "scripts", ".github", "licenses")
SUFFIXES = {".py", ".md", ".txt", ".toml", ".yml", ".yaml", ".ps1", ".cmd",
            ".terms", ".png", ".svg"}
SKIP = {"__pycache__", ".git", ".venv", "local-qa", "local-state", "dist", "build", "release"}


def sources():
    files = []
    for name in sorted(ROOT_FILES):
        path = ROOT / name
        if not path.is_file():
            raise RuntimeError("Missing required source file: " + name)
        files.append(path)
    stack = [ROOT / name for name in ROOTS if (ROOT / name).is_dir()]
    while stack:
        directory = stack.pop()
        if os.lstat(directory).st_file_attributes & 0x400:
            raise RuntimeError("Linked source directory refused")
        for item in directory.iterdir():
            if os.lstat(item).st_file_attributes & 0x400:
                raise RuntimeError("Linked source entry refused: " + item.name)
            if item.is_dir():
                if item.name not in SKIP:
                    stack.append(item)
            elif item.suffix.lower() in SUFFIXES:
                files.append(item)
    for file in files:
        if os.lstat(file).st_file_attributes & 0x400:
            raise RuntimeError("Linked source file refused")
        if ROOT not in file.parents:
            raise RuntimeError("Source export escaped the repository")
    return sorted(set(files))


def main():
    RELEASE.mkdir(exist_ok=True)
    destination = RELEASE / "CodexStorageWorkbench-0.2.0.dev1-source.zip"
    files = sources()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output:
        for file in files:
            output.write(file, "CodexStorageWorkbench-source/" + file.relative_to(ROOT).as_posix())
    expected = {"CodexStorageWorkbench-source/" + p.relative_to(ROOT).as_posix(): p for p in files}
    with zipfile.ZipFile(destination) as archive:
        if set(archive.namelist()) != set(expected):
            raise RuntimeError("Source ZIP inventory mismatch")
        for name, file in expected.items():
            if archive.read(name) != file.read_bytes():
                raise RuntimeError("Source ZIP content mismatch")
            if name.endswith(".py"):
                compile(archive.read(name), name, "exec")
    sums = []
    for file in sorted(RELEASE.glob("*.zip")):
        sums.append(hashlib.sha256(file.read_bytes()).hexdigest() + "  " + file.name)
    (RELEASE / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="ascii")
    print("Verified source export:", len(files), "files", destination.name)


if __name__ == "__main__":
    main()

