# CAD quality gates

## Before commit

- Correct AutoCAD instance and active `document_id/revision` are locked.
- Unit, layer names, text style and required output format are explicit.
- The exact intended operations pass the built-in preflight before commit; use a separate dry-run when the plan is unfamiliar, uncertain, complex, or requires a preview.

## Numeric QA

- Required layers exist.
- No zero-length or duplicate lines, invalid circles, degenerate polylines, unintended non-zero Z, or open boundaries that are required to be closed.
- Query critical outlines, dimensions and labels by handle/layer and compare them with the brief.

## Visual QA

- Screenshot the selected process after zooming to the relevant extent.
- Check lineweight hierarchy, visibility, text encoding, dimension placement, overlapping objects, title orientation and page composition.
- A screenshot never replaces numeric validation. Verify changed geometry numerically and changed appearance visually; unchanged state may reuse existing evidence. Both applicable gates must pass before delivery.

## File QA

- Separate staging saves from final delivery. Final saving follows the current global save policy and this task's authorization at the specified or confirmed location; overwrite requires explicit authorization.
- File extension and requested `fmt` agree.
- DXF output is generated through AutoCAD's DXF writer, not by renaming a DWG.
- Report unresolved interactive Tianzheng jobs and do not present an enqueued job as complete.

