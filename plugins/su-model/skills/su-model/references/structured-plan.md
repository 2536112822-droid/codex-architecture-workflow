# Structured plan contract

Use `su_apply_plan` for normal modeling. Every plan requires an explicit unit, the revision returned by the latest inspection, and a plan-version-specific idempotency key.

```json
{
  "label": "L01 external envelope",
  "unit": "mm",
  "expected_revision": 12,
  "idempotency_key": "project-a-l01-envelope-v3",
  "operations": [
    {
      "type": "material",
      "id": "mat-concrete",
      "name": "Concrete - light",
      "color": "#D2CEC6",
      "roughness": 0.8,
      "metallic": 0.0
    },
    {
      "type": "box",
      "id": "wall-001",
      "name": "L01-WALL-EXT-001",
      "x": 0,
      "y": 0,
      "z": 0,
      "width": 8000,
      "depth": 200,
      "height": 3000,
      "semantic": {
        "spec_id": "L01-WALL-EXT-001",
        "kind": "external_wall",
        "level": "L01",
        "certainty": "confirmed",
        "source": "brief-v2"
      }
    },
    {"type": "assign_material", "target": "wall-001", "material": "mat-concrete"}
  ]
}
```

## Supported operations

| Type | Essential fields |
|---|---|
| `set_units` | `unit`, optional `precision` |
| `material` | `id`, `name`, `color`; optional `alpha`, `metallic`, `roughness` |
| `box` | `id/name`, `x/y/z`, `width/depth/height` |
| `cylinder` / `cone` | `id/name`, `x/y/z`, `radius/height`, optional `segments` |
| `ngon` | `id/name`, `x/y/z`, `radius`, `sides`, optional `height` |
| `curve` | `id/name`, `points` |
| `move` | `target`, `dx/dy/dz` |
| `rotate` | `target`, `degrees`, optional `axis` |
| `assign_material` | `target`, `material` |
| `mark` | `target`, `attributes` |
| `erase` | `target` |

References may use an operation-local `id`, an existing name, semantic `spec_id`, or persistent ID. Use local IDs inside the same plan and stable `spec_id` across revisions.

## Revision discipline

After every commit, use the returned revision for the next plan. If a response is lost, retry the exact same plan with the original revision and key; the stored plan fingerprint is checked before the revision guard, so a completed plan returns `idempotent_replay`. Reusing that key with different content returns `idempotency_conflict`. An idempotent replay is success only when the prior result is the intended result; inspect it instead of assuming. If an unused plan key fails the expected revision, stop and re-read the model before generating a new patch.
