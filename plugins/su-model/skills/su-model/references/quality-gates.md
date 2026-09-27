# SketchUp quality gates

Apply these gates to the requested work. For a new complete model, validate the model as a whole. For an existing model, check affected elements and required deliverables; record unrelated pre-existing defects without expanding the task into a general cleanup.

## Numeric gate

- `su_validate_model` reports no newly introduced duplicate semantic IDs, unnamed top-level containers, zero-size bounds, or top-level loose geometry in the requested scope; new complete models must satisfy the full model check.
- Critical overall and component dimensions match the brief within the declared tolerance.
- Distinguish design inputs, bounding extents and measured finished clearances. A copied input width/height is not an independent readback of the resulting opening; use the relevant actual faces/edges and applied transforms for the claimed measurement, with source units and tolerance.
- Units are explicit and inspection output records both model display units and SketchUp's internal inch convention.

## Semantic gate

- Architectural components created or modified for semantic editing have unique stable `spec_id` values; a visual-only change does not require retrofitting IDs onto an entire existing model.
- Level, kind, certainty, and source are present for inferred or confirmed elements.
- For newly created or reused target components, check that source, phase and certainty describe the current adopted evidence, including relevant parent/child differences. A correctly labelled parent does not validate descendants; a helper's default project/year can silently leak into reused geometry. Pass current provenance explicitly when reusing helpers, or mark it unresolved. Do not globally relabel legacy components or overwrite genuine historical sources.
- No user-confirmed fact is silently replaced by an inference.

## Spatial use gate, when relevant

- Identify the user/material movement, important start/end points and relevant use states. Check the continuous relationship and critical bottlenecks, turns, level changes, door movement, furniture and activity clearance at the requested planning/detail level. A door component or a hole-centre test alone does not establish usable access.
- Use actual geometry measurements, sections, path checks or supported representative envelopes as appropriate. For point/ray sampling, state covered positions/heights, exclusions and remaining uncertainty; a clear sample set is not proof of an entire route or swept body. Do not invent tool parameters or require a complete human simulation for every task.
- Record revision and the scene/Tag visibility and open/closed states that affect the result. Preserve intentionally hidden recovery copies, verify that the intended display uses the correct shell, and do not hide participating obstacles to obtain a pass. Excluding a decorative person does not check crowd or working-state compatibility.
- Check only the states that can change the present decision (for example stored versus working furniture or a moving shutter). Use justified project/standard thresholds when needed; a model coordination pass is not regulatory approval. Unknown evidence limits only the claim dependent on it.

## Visual gate

- Reuse valid views and choose the smallest sufficient set to reveal the current subject and relevant hidden errors. Add a local section or native measurement when it answers the question better; no fixed axonometric or full orthographic set is required for every edit.
- No accidental intersections, floating parts, missing faces, wrong material assignments, severe clipping, or distorted camera.
- Render-ready capture preserves geometry and restores the user's camera/style state after export.
- Check the actual delivered view at its intended size: can the intended spatial/phase relationship be understood, and is the important subject visible? Separate a camera/lighting or annotation problem from a geometry fault. A raw native capture can rely on accompanying explanation; do not automatically add board labels or rebuild geometry.
- Compare source and candidate with appropriate revision/camera/projection/crop controls when claiming fidelity; otherwise keep the conclusion qualitative. Visual similarity does not prove dimensions or full functionality, and an image-generation step is not required for QA.
- For furniture or small-part revisions, compare the affected view at the intended delivery scale. Confirm that repair, custom modeling, or a sourced replacement resolves the observed issue without changing approved architecture/layout or adding disproportionate geometry/texture load; stop when further detail would not improve the deliverable.

## Delivery gate

- Check the hierarchy against the grouping rules in `../SKILL.md`: meaningful editable groups/components, useful parent containers only, no added whole-model delivery wrapper, and no flattening into loose edges/faces. A named outer group alone does not establish editability.
- Inspect representative editable parts within the requested scope: each can be located and entered for editing independently, with no unintended locks or component linkage. Preserve intentional protection and shared-component behavior; when reorganizing, verify retained child groups, placement, materials, tags, and semantic attributes.
- The current `su_inspect_model` and `su_validate_model` inspect top-level entities only. For nested content, supplement them with a read-only recursive inspection or an Outliner/edit-context check; a top-level pass or screenshot alone does not prove internal grouping and editability.
- For adopted external assets, record the source and applicable usage permission; verify actual import, dimensions, materials/textures, placement, editable grouping, and intended instance linkage in the working SKP. Verify required asset dependencies after saving to the chosen destination; handle downloaded candidates under the staging and retention rules.
- Keep working saves in task staging. Save the final SKP under the current global save policy and this task's authorization, using the specified or confirmed location; overwrite requires explicit authorization.
- Report final path, model revision, unit, validation result, key dimensions, and unresolved assumptions.
- Retain the clean SU capture during verification. At closeout, handle baselines and variants under the current global retention policy; preserve required deliverables and dependencies.
