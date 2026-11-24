"""Every installation path pins the same dependency versions (re-validation R2).

The notebook's requirements.yaml is the specification. The desktop installer's requirements
and lock files, the Colab install cell and the profiler checks' requirements must pin each
git dependency at the same commit, and the Colab cell's other pins at the same versions.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "notebooks" / "OpticalFlow3D_Profiler" / "requirements.yaml"
NOTEBOOK = SPEC.with_name("OpticalFlow3D_Profiler.ipynb")
INSTALL_FILES = (
    "requirements.txt",
    "requirements.lock.txt",
    "requirements_gpu.txt",
    "requirements_gpu.lock.txt",
    "tools/requirements-checks.txt",
)
GIT_PIN = re.compile(r"([A-Za-z0-9_.-]+) @ git\+https://[^@\s\"]+@([^\s\"]+)")  # commit or tag
VERSION_PIN = re.compile(r"([A-Za-z0-9_.-]+)==([^\s\"',]+)")


def pins(text: str, pattern: re.Pattern) -> dict[str, str]:
    found: dict[str, str] = {}
    for name, value in pattern.findall(text):
        assert found.setdefault(name.lower(), value) == value, f"{name} pinned twice"
    return found


def colab_install_cell() -> str:
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    found = [
        "".join(c["source"]) for c in cells if "pip install" in "".join(c["source"])
        and "git+" in "".join(c["source"])
    ]  # fmt: skip
    assert len(found) == 1
    return found[0]


def test_every_installation_path_pins_the_specified_git_commits():
    spec = pins(SPEC.read_text(encoding="utf-8"), GIT_PIN)
    assert {"morphobricks-normalization", "morphocoverage"} <= set(spec)
    for name in INSTALL_FILES:
        assert pins((ROOT / name).read_text(encoding="utf-8"), GIT_PIN) == spec, name
    assert pins(colab_install_cell(), GIT_PIN) == spec


def test_the_colab_cell_pins_the_specified_versions():
    spec = pins(SPEC.read_text(encoding="utf-8"), VERSION_PIN)
    for name, version in pins(colab_install_cell(), VERSION_PIN).items():
        assert spec.get(name) == version, name


def test_every_installation_path_pins_the_specified_versions():
    # Round 3: only the Colab cell's own version pins were compared with the specification.
    spec = pins(SPEC.read_text(encoding="utf-8"), VERSION_PIN)
    assert {"numpy", "tifffile", "pandas"} <= set(spec)
    for name in ("requirements.txt", "requirements_gpu.txt"):
        found = pins((ROOT / name).read_text(encoding="utf-8"), VERSION_PIN)
        assert {k: found.get(k) for k in spec} == spec, name
