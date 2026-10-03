"""Replay the validation recordings used in the article, without calling a model.

Run with the repository environment: .venv/bin/python demo/prepare_evidence.py
Every replay is checked against its recorded observations and final score.
All generated assets and copied records stay under demo/.
"""

import json
from pathlib import Path
import shutil
import tarfile

from doomlab.report.demo import _animate


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
checks = {}

for version in ("v0", "v1"):
    filename = "health_gathering_supreme-s101-react_single.jsonl"
    local = HERE / "data" / f"trial-{version}-seed101.jsonl"
    original = ROOT / "runs/improve-trial-v1" / version / filename
    if original.exists():
        shutil.copyfile(original, local)
    if not local.exists():
        raise FileNotFoundError(f"Need the recorded validation trace: {original}")
    target = HERE / "assets" / f"health-gathering-s101-{version}.webp"
    result = _animate(local, target)
    expected = 1088 if version == "v0" else 416
    assert result["score"] == expected, result
    checks[version] = {"source": local.name, "matches": True, **result}
    print(f"Verified {version}: {expected} tics; wrote {target.name}")

# Keep a complete original episode for the readable rejection example.
with tarfile.open(ROOT / "results/traces/eval-test.tar.gz") as archive:
    for seed in range(1000, 1010):
        name = f"defend_the_center-s{seed}-react_single.jsonl"
        raw = archive.extractfile(name).read()
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        rejected = next((e for e in events if e["event"] == "tool_exec"
                         and not e["ok"] and e.get("code") == "NO_ENEMY_IN_CONE"), None)
        if rejected:
            (HERE / "data" / "rejected-action-trace.jsonl").write_bytes(raw)
            checks["rejected_action"] = {"episode": name, "seed": seed, "step": rejected["step"]}
            print(f"Saved rejection example from {name}, step {rejected['step']}")
            break
    else:
        raise ValueError("Could not locate the recorded rejected attack")

(HERE / "data/evidence-checks.json").write_text(json.dumps(checks, indent=2) + "\n")
