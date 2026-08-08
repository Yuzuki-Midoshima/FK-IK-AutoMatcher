# FK/IK Auto Matcher for Maya

A pose-matching tool for Autodesk Maya 2026 that aligns FK and IK controls in either direction. It is intended for riggers, technical artists, and technical animators working with three-point limb chains.

## Demo

Demo images and videos will be added under [`docs/media/`](docs/media/). Keeping portfolio media in this directory makes it possible to update the presentation without changing the Maya package.

## Overview

Select a node from an FK/IK rig and let the tool resolve the relevant controls and joints. Rig data is read from a Rig Module Builder manifest when one is available; otherwise, the resolver performs conservative discovery using scene names and connections. Every match is wrapped in one Maya undo chunk.

## Features

- Matches FK to IK by positioning the IK controller and pole-vector controller.
- Matches IK to FK by applying IK-joint rotations to the FK controllers.
- Preserves a stable pole-vector side and uses the middle joint's preferred angle as a fallback for straight chains.
- Resolves rig data from a `rigModuleBuilderManifest` network-node attribute.
- Provides conservative namespace- and limb-aware scene discovery when no manifest is available.
- Supports manual correction of resolved nodes and FK/IK switch settings.
- Saves and loads matcher settings as JSON.
- Groups each match into a single Maya undo operation.

## Installation

1. Download or clone this repository to a location available to Maya.
2. Add the repository root to Maya's Python path, or run the included launcher by its full path.

From Maya's Python Script Editor:

```python
import runpy

runpy.run_path(r"<path-to-repository>/launch_fk_ik_auto_matcher.py")
```

If the repository root is already on `PYTHONPATH`:

```python
from fk_ik_auto_matcher import show

show()
```

`reload_fk_ik_auto_matcher.py` is provided as a development helper for reloading the package during a Maya session.

## Usage

1. Select one node belonging to the target FK/IK limb.
2. Open the tool and use the selected node as the detection reference.
3. Review the resolved controls, joints, switch attribute, and pole-vector settings.
4. Run **FK to IK** or **IK to FK**.
5. If automatic discovery is not appropriate for the rig, enter the nodes manually and optionally save the settings as JSON.

## Technical Highlights

- Maya dependencies are injected at the service boundary, allowing matching and resolver logic to be tested with command-module fakes.
- Maya and PySide6 imports are lazy at the package entry point, so non-UI modules remain importable in standard Python.
- Pole-vector placement handles bent, nearly straight, and straight chains without normalizing an unstable near-axis direction.
- Settings use a typed dataclass with UTF-8 JSON serialization.
- Rig discovery prefers explicit manifest data over naming heuristics.

## Project Structure

```text
fk_ik_auto_matcher/          Maya package
  main.py                    Maya/PySide6 entry point
  ui.py                      User interface
  matcher.py                 FK/IK matching operations
  resolver.py                Manifest and scene discovery
  models.py                  Serializable settings model
tests/                       Maya-independent unit tests
docs/media/                  Demo media placeholder
launch_fk_ik_auto_matcher.py Shelf-friendly launcher
reload_fk_ik_auto_matcher.py Development reload helper
```

The existing flat package layout is intentional: it keeps Maya's import and launcher workflow straightforward.

## Requirements

- Autodesk Maya 2026
- Python 3.11 (included with Maya 2026)
- PySide6 and shiboken6 (included with Maya 2026)

The matcher targets start, middle, and end nodes in a three-point limb chain. Rig-specific systems such as custom stretch or matrix-network synchronization are outside its current scope.

## Testing

### Automated Tests

The automated suite covers settings serialization, switch-plug construction, limb-context filtering, and pole-vector behavior using a fake `maya.cmds` boundary. It does not require Maya:

```bash
python -m unittest discover -s tests -v
```

GitHub Actions also compiles every tracked Python file and verifies imports for the Maya-independent package surface.

### Maya Manual Tests

The following behavior requires an installed copy of Maya and a representative FK/IK rig:

- Launching and reopening the PySide6 window.
- Manifest-based and scene-based discovery against real Maya nodes.
- FK-to-IK and IK-to-FK matching across bent and straight limb poses.
- Pole-vector orientation and preferred-angle fallback.
- FK/IK switch updates, selection callbacks, and button-state updates.
- Single-step Maya Undo after each match.
- JSON save/load through Maya file dialogs.

## Development Workflow

Create changes on `feature/*`, `fix/*`, or `chore/*` branches, open a pull request to `main`, and merge only after CI passes. Keep `main` in a stable, portfolio-ready state.

## License

Licensed under the [MIT License](LICENSE).
