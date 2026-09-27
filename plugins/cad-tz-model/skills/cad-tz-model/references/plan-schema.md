# CAD plan schema

`cad_apply_plan` is the preferred drawing entry point. Commit a clear plan with the latest document guard and a plan-version-specific idempotency key. Use a separate dry-run for unfamiliar operations, uncertain or complex geometry, or a requested preview. Every commit performs its own side-effect-free preflight before guarded setup and one atomic geometry batch, then returns numeric validation and final state. Inspect these results before requesting additional checks.

```json
{
  "unit": "mm",
  "precision": 3,
  "expected_document_id": "drawing-token-from-cad-state",
  "expected_revision": 8,
  "idempotency_key": "project-a-l01-plan-v4",
  "dry_run": false,
  "layers": [
    {"name": "A-WALL", "color": 7},
    {"name": "A-DOOR", "color": 3},
    {"name": "A-GRID", "color": 8},
    {"name": "A-DIMS", "color": 3}
  ],
  "text_style": {
    "name": "hz",
    "font": "simsun.ttc",
    "bigfont": "gbcbig.shx",
    "height": 0,
    "set_active": true
  },
  "operations": [
    {"id": "wall-outline", "type": "rect", "p": [0, 0, 10000, 8000], "layer": "A-WALL"},
    {"id": "grid-a", "type": "line", "p": [0, 4000, 10000, 4000], "layer": "A-GRID"},
    {"id": "title", "type": "text", "p": [0, -600], "text": "首层平面", "height": 350, "style": "hz"},
    {"id": "dim-x", "type": "dim", "p": [0, 0, 10000, 0, 5000, -900], "layer": "A-DIMS"}
  ],
  "required_layers": ["A-WALL", "A-DOOR", "A-GRID", "A-DIMS"],
  "tolerance": 0.01,
  "require_closed_polylines": true
}
```

## Drawing operations

| Type | Geometry fields |
|---|---|
| `line` | `p: [x1,y1,x2,y2]` |
| `rect` | `p: [x,y,width,height]` |
| `circle` | `p: [cx,cy,radius]` |
| `arc` | `p: [cx,cy,radius,start_deg,end_deg]` |
| `polyline` | `pts: [[x,y], ...]`, optional `closed` |
| `text` | `p: [x,y]`, `text`, optional `height`, `rotation`, `style` |
| `mtext` | `p: [x,y]`, `text`, optional `height`, `width`, `style` |
| `dim` | `p: [x1,y1,x2,y2,line_x,line_y]`, optional `text`, `dimstyle` |

Every entity may include `id` for result mapping and `layer`. Coordinates are interpreted in the plan's declared drawing unit.

## Retry contract

- `expected_document_id` and `expected_revision` are required for dry-runs and commits.
- If a commit response is lost, retry the exact same plan with the same key and original guards. A completed batch returns `idempotent_replay` without duplicate entities.
- Reusing the key with different units, setup, operations, or QA requirements returns `idempotency_conflict`.
- A stale revision with an unused key is rejected before setup or geometry writes. Get a new `cad_state` and make a new plan version.
- Unit/layer/text-style setup is individually revision-guarded. The geometry operations themselves share one AutoCAD database transaction and roll back together on failure.

## Patch operations

Use handles returned by commit/query with `cad_edit`: `move`, `copy`, `rotate`, `scale`, `mirror`, `offset`, or `erase`. Offset also needs a side point (`side_x`, `side_y`). Verify edited handles and affected geometry after a patch; consecutive small edits within one stage may share a final inspection. Reuse earlier evidence only while the state it proves remains unchanged.
