import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from docket.config import dataset_dir

ESTIMATE = re.compile(r"_estimate_(\d+)\.png$")
PART = re.compile(r"_part_(\d+)_")


@dataclass(frozen=True)
class Script:
    script_id: str
    task: int
    images: tuple[Path, ...]
    reference: Path | None
    official_score: int | None
    source: dict = field(default_factory=lambda: {"kind": "checkmat"}, compare=False)

    @property
    def image_sha256(self) -> str:
        digest = hashlib.sha256()
        for path in self.images:
            digest.update(path.read_bytes())
        return digest.hexdigest()


def _part(path: Path) -> int:
    match = PART.search(path.name)
    return int(match.group(1)) if match else 0


def load_script(folder: Path) -> Script:
    images = tuple(sorted((folder / "without_answer").glob("*.png"), key=_part))
    if not images:
        raise FileNotFoundError(f"no student images under {folder}")
    match = ESTIMATE.search(images[0].name)
    example = folder.parent
    references = sorted(example.glob("*_solve_true.png"))
    return Script(
        script_id=folder.name,
        task=int(folder.name.split(".")[0]),
        images=images,
        reference=references[0] if references else None,
        official_score=int(match.group(1)) if match else None,
    )


def all_scripts(root: Path | None = None) -> list[Script]:
    root = root or dataset_dir()
    folders = sorted({p.parent.parent for p in root.glob("*/*/*/without_answer/*.png")}, key=lambda p: [int(x) for x in p.name.split(".")])
    return [load_script(folder) for folder in folders]


def find_script(script_id: str) -> Script:
    for script in all_scripts():
        if script.script_id == script_id:
            return script
    raise KeyError(f"script {script_id} not in CHECK-MAT")


def script_for_case(case: dict) -> Script:
    source = case.get("source") or {"kind": "checkmat"}
    if source["kind"] == "s3":
        from docket.inputs import script_from_s3

        return script_from_s3(source["bucket"], source["keys"], source.get("referenceKey"), case["scriptId"], case["task"])
    if source["kind"] == "local":
        reference = source.get("reference")
        return Script(case["scriptId"], case["task"], tuple(Path(p) for p in source["paths"]), Path(reference) if reference else None, case.get("officialScore"), source)
    return find_script(case["scriptId"])


REFERENCE_NAME = re.compile(r"(reference|solve_true)[^/]*\.png$")


def load_folder(folder: Path) -> Script:
    pngs = sorted(folder.glob("*.png"))
    references = [p for p in pngs if REFERENCE_NAME.search(p.name)]
    pages = tuple(sorted((p for p in pngs if p not in references), key=lambda p: (_part(p), p.name)))
    if not pages:
        raise FileNotFoundError(f"no student pages in {folder}")
    match = ESTIMATE.search(pages[0].name)
    source = {"kind": "local", "paths": [str(p) for p in pages], "reference": str(references[0]) if references else None}
    return Script(folder.name, int(folder.name.split(".")[0]), pages, references[0] if references else None, int(match.group(1)) if match else None, source)


def script_from_path(path: Path) -> Script:
    path = path.resolve()
    if path.is_dir():
        return load_script(path) if (path / "without_answer").is_dir() else load_folder(path)
    if path.parent.name in ("without_answer", "with_answer"):
        return load_script(path.parent.parent)
    raise ValueError(f"{path} is not a CHECK-MAT script image or folder")
