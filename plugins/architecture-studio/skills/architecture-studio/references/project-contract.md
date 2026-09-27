# Project contract

Read this reference when a task spans multiple architectural stages or must remain editable across turns and tools.

Stage a new contract as `.architecture/architecture-project.json` inside this task's temporary work directory. Deliver it when needed under the current global save policy and this task's authorization to the specified or confirmed folder; an existing contract may be updated within an explicitly authorized project edit. Validate it against [architecture-project.schema.json](architecture-project.schema.json). Keep it small enough to review in a diff; put large geometry and analysis results in referenced artifact files.

## Required semantics

- `project_id` and every element, view, evidence item, and artifact ID remain stable across revisions.
- `units` is explicit. Coordinates state their CRS or are identified as local project coordinates.
- `known`, `inferred`, and `unknown` are distinct. Each inference has confidence and source evidence.
- For consequential source/status decisions, follow [source baselines](source-baselines.md). Scope certainty to the specific claim: real-world evidence, model representation, and adopted design action/phase are separate. Use existing evidence/element/artifact fields or one linked note; do not add required top-level keys or backfill every element.
- `revision` increases only after an accepted write. A rejected or rolled-back operation does not advance it.
- Artifacts record their source revision, producing stage, absolute or project-relative path, and validation state.
- For multiple source documents, use existing `evidence` items to record version/date, actual pages or sections read, and missing material. Store a longer requirements or metrics schedule as a linked artifact; keep the strict top-level schema unchanged.
- Preserve requirement validity separately from implementation and verification. At relevant handoffs use [brief to package](brief-to-package.md): retain source, subject/phase/team scope, this task's commitment, artifact/check links, and unresolved or deferred items. Existing notes or permitted evidence/artifact/QA fields suffice; do not introduce mandatory top-level keys or a parallel tracker.
- Do not embed access tokens, cookies, credentials, or private connector data.

## Minimal example

```json
{
  "schema_version": "1.0",
  "project_id": "villa-01",
  "title": "Small villa study",
  "revision": 3,
  "units": "mm",
  "coordinate_reference": {"kind": "local", "origin": [0, 0, 0]},
  "brief": {
    "known": ["Two storeys", "Garage for one car"],
    "inferred": [{"statement": "Entry faces south", "confidence": 0.65, "evidence_ids": ["IMG-01"]}],
    "unknown": ["Structural system"]
  },
  "levels": [{"id": "L01", "elevation": 0, "height": 3000}],
  "elements": [],
  "views": [],
  "evidence": [{"id": "IMG-01", "type": "reference_image", "path": "references/front.jpg"}],
  "artifacts": [],
  "qa": [],
  "history": [{"revision": 3, "summary": "Moved garage opening 400 mm east"}]
}
```

## Handoff rules

- Site analysis writes verified constraints and artifact links; it does not invent building geometry.
- The selected native model tool (SketchUp or Rhino) consumes the current levels/elements/views and writes back model identity, stable element IDs and application IDs/GUIDs where supported, captures, dimensions, and validation. Cross-tool exports record units and any semantic loss.
- CAD consumes the same stable IDs and levels so plan, elevation, and section remain coordinated.
- Colored plans and indicator schedules use the same checked plan geometry and declared measurement scope. Link them to their source artifacts rather than independently inventing outlines or numbers.
- Presentation image generation consumes a verified view and writes back its source view ID, prompt, and purpose as `presentation_only`. Optional pre-model references instead link the adopted design, available views/scale sources, and unresolved assumptions as described in [brief to package](brief-to-package.md); an adopted reference still does not become measured geometry.

## Changes, dependencies, and resuming work

- For cross-task context recovery, use [project continuity](project-continuity.md). Reuse an authorized project entry point; link its compact decision record through existing evidence/artifact fields when relevant, without adding top-level schema keys. Keep local technical contracts scoped to their actual subject. A saved/reopened file, an assistant's implementation, and a user's design acceptance are different states.
- Where derived outputs exist, record `source_artifact_ids` and the relevant source document revision on artifact entries. QA may record `artifact_ids` and `subject_revision`; these are supported additional fields, not new top-level keys. Keep artifact identity stable; when retaining several versions, give each retained artifact version its own ID and connect it with `supersedes_artifact_id`.
- Include the inputs that actually produced an output: geometry extracts, parameters, generation/editing scripts, adopted references, and relevant explanatory assumptions, not only the main model. Link their versions or existing receipts where useful. A PDF/PPT may contain static copies; finding the source model does not establish that its diagrams, images, numbers, or captions have been updated. No full inventory is required for an isolated edit.
- Before adopting a newer baseline, identify its changed objects, their correspondence to the working model, and any coordinate/registration changes. A discovery alone is not an accepted source change. Where impact is unverified, flag only potentially affected dependencies for review; do not replace the entire design, advance its revision, or invalidate all prior checks merely because a newer file exists. Source-preservation QA proves preservation, not survey accuracy.
- After an accepted source change, trace affected dependencies, including indirect ones. Mark obsolete derivative artifact entries `superseded`; retain their paths and original source revisions. If dependency coverage is unclear, mark potentially affected outputs for review rather than assuming they remain current. Preserve unrelated artifacts and checks whose proven state is unchanged.
- A changed subject cannot inherit an old QA `pass`. Keep that evidence as historical and record the current check as `warning` pending revalidation, or `fail` when a mismatch is established. Include the reason and affected IDs; old evidence alone cannot clear the new check. Preserve any established unresolved failure. A presentation image remains `presentation_only` when regenerated and visually checked.
- When rebuilding a derivative, verify it against the current source before treating it as current. Do not merely rewrite its `source_revision` or remove a warning. Never delete the old file solely because it is superseded; follow the existing retention policy.
- At a useful stage boundary, save the actual editable work and update the existing progress/contract with input revision, output path, completed checks, and next action. Use [project continuity](project-continuity.md) for the compact stage closeout and for diagnosing, applying and verifying later feedback. On resume, read that compact state and inspect the actual document before writing. Reuse valid work; do not create a separate report or mandatory approval for every step.

### Determine the actual change and finish only affected work

A hash/revision change signals investigation; it cannot identify the design meaning of a change. Use the actual edit receipt, relevant object/state comparison, and the check's coverage. Examples below guide judgment, not a compulsory checklist:

| Change | Trace and verify as relevant | Reuse boundary |
|---|---|---|
| Geometry, coordinates, openings or levels | Affected model objects, plans/sections, areas/clearances, views and embedded copies | Unrelated geometry and checks remain usable where their inputs/state are proven unchanged |
| Camera, material, style or Tag/layer visibility | Related captures, sheets/slides and their references; visibility-based extracts or use checks if their participating objects changed | A camera-only edit can retain geometry QA at its original revision with the no-geometry-change evidence; display changes are not automatically harmless to measurements |
| Object identity, phase, function or evidence | Relevant legends, captions, schedules, assumptions and design claims even when geometry is unchanged | Preserve checks of unchanged geometry; do not reuse an obsolete meaning or phase classification |
| Script, parameters, units or calculation/annotation logic | Outputs and downstream copies produced with those inputs, including quantities and scale/text checks | A unchanged model file does not prove these derivatives remain valid |

Keep planned, applied, checked and delivered states distinct in the existing progress/contract. A partial update should name the updated artifacts and remaining affected ones, their actual source versions, and the next action; do not advertise the package as synchronized. If a sheet or deck is only potentially affected and its source cannot yet be identified, leave that dependency unresolved rather than inventing one. Preserve old files and historical receipts; do not relabel a previous QA run as run against the newest revision. A newer snapshot observes a state; it cannot close an unfinished update.
