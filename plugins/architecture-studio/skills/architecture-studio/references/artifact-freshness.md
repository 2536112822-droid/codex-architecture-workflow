# Saved-artifact changes

Use this optional helper when saved project files already have explicit dependencies and checking their changes by hand is becoming unreliable. Ordinary modeling and isolated edits keep their existing workflow. The helper needs only Python's standard library; it never opens a desktop application, executes a model, rebuilds an output, or edits the project contract.

## Inputs and meaning

Use the existing `artifacts` entries in `.architecture/architecture-project.json`; do not change the strict top-level schema. An artifact's `source_artifact_ids` contains every declared artifact it depends on. An explicit `[]` means a declared root; a missing field means dependency coverage is unknown. Do not fill missing lists with `[]` merely to clear a warning. Link sources such as model, parameter and script files as artifacts where the existing project structure permits, and record other assumptions in the project context.

Supply `--root` as the base for project-relative artifact paths. Absolute local file paths are read as declared. Use saved files; a file fingerprint cannot see unsaved changes in AutoCAD, Rhino or SketchUp. Large or remote-mounted files can be expensive to hash; use this only for the relevant project contract.

```text
python <skill>/scripts/artifact_freshness.py snapshot --contract <project.json> --root <project-folder> --out <new-snapshot.json>
python <skill>/scripts/artifact_freshness.py check --contract <project.json> --root <project-folder> --snapshot <snapshot.json>
```

`snapshot` creates a new observation file and refuses an existing destination. Its parent folder must already exist. Capture a useful milestone after the intended saves and checks; its creation is not an acceptance or validity check. `check` prints JSON only. Exit code 0 means the declared observation has no reported issue/change; code 2 means attention/error, never a manufacturing or design verdict. Keep the snapshot in task/project staging under the existing save policy; there is no automatic archive or background scan.

## Acting on results

- A changed source affects its direct and indirect dependents. The comparison considers old and new dependency links, so deleting a link cannot silently erase an earlier dependency.
- Missing or unreadable files, unknown dependencies, invalid graphs, and changed project context need review. An unchanged global project revision is not a substitute for these checks.
- Project context includes units, coordinates, brief, levels, elements, views and evidence declarations. A change requires review of all artifacts because the helper cannot infer its scope. Evidence paths are metadata only; register a source as an artifact with explicit links when its file bytes need tracking. This is not a replacement for the existing contract schema validator.
- “Unchanged since snapshot” means only the observed saved bytes and declared metadata did not change. It does not mean current, synchronized, verified, reusable, or safe to skip required geometry/visual checks. A snapshot of an already outdated drawing stays an observation of an outdated drawing.
- Use affected IDs to scope investigation and the existing source/version/QA invalidation procedure. Read the live document identity and state before any model change. Preserve unresolved failures and `presentation_only`; this helper never promotes QA.
- The helper cannot distinguish camera, material, visibility, geometry or design-meaning changes within a file. Likewise, its all-artifact warning after a context change is conservative attention, not an instruction to rebuild everything or mark everything failed. Apply the change-scope examples in [project contract](project-contract.md), retain the original check revision and evidence for justified reuse, and leave unsupported reuse pending. It does not discover undeclared scripts, embedded slide images or other missing dependencies; an empty/unchanged report cannot establish their synchronization.
- After rebuilding and verifying outputs, create a new snapshot for that milestone. Never overwrite the old snapshot to hide a change or replace actual verification with a new timestamp/hash.

Per-file before/after checks detect ordinary changes during reading, but this is not a lock or a transaction across files. Wait for ongoing saves to finish before taking a milestone snapshot. Its self-check detects accidental corruption, not a trusted signature.

The approach adapts explicit dependency tracking from text-to-cad 0.6.5 (commit `4ebbd2cc6172e4c5d53560a5948df214192aefac`) to saved architectural artifacts. It intentionally does not copy the upstream geometry cache or assume that file identity controls an active desktop document.
