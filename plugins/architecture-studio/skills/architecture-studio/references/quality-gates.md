# Quality gates

Read before final delivery. Record applicable gates as `pass`, `warning`, or `fail` in the existing project contract with evidence and artifact paths. Reuse valid evidence for unchanged state; do not rerun completed stages solely to populate the checklist.

## Requirement coverage

- Check still-valid requirements against this stage's declared commitment and scope, including phase and individual/group responsibility where relevant. Carry forward unresolved or deferred items; do not silently cancel them or inflate a local task into a whole-project obligation.
- Evidence proves the intended requirement at the agreed level of detail. An entrance component does not prove a continuous usable route; save/reopen QA does not prove design completeness. Use relevant functional, numeric, visual, or editable-file evidence as needed, reusing valid checks.
- Check both directions: each current commitment has an adequate result/check, and each delivered result answers the requested object, purpose, and format. Report partial, unverified, or deferred content and bound the completion claim. Lack of evidence is unverified, not an invented failure or pass; unread sources limit coverage claims.

## Design-stage coordination, when relevant

- The deliverable's design maturity and purpose are explicit; a planning horizon or detailed-looking model does not establish technical, construction or operational completion.
- Before committing significant spatial relationships, check the relevant use/programme, space and system interfaces described in [brief to package](brief-to-package.md) at the agreed depth. Carry unresolved consequential feasibility/performance conditions to the next responsible action; a visually coherent form alone cannot clear them.
- Evidence fits the claim and scope: a concept comparison may use reasoned assumptions or bounded estimates, while quantitative performance, construction and actual-use claims need their corresponding evidence. Do not require a full engineering package for a concept or rerun unrelated checks on a local edit.

## Evidence and site

- Location, units, CRS, study extent, data dates, and real site boundary status are explicit.
- Combined sources retain their units, coordinate/height/north references, accuracy, and evidenced transform/control points where applicable. Unregistered or approximate overlays are labelled; visual alignment alone does not pass dimensional coordination.
- Map scale and north direction are numerically correct; legends and sources are visible.
- Facts, inferences, and recommendations are separated. Missing evidence remains unknown; labelled conceptual design or model completion is allowed but must not be represented as verified existing conditions. Check consequential elements' reality evidence, representation, and design phase separately.
- For a supplied brief or multi-source study, reading coverage is explicit and consequential requirements link to their source location and relevant deliverable/check. Unread material is not represented as reviewed.

## Model geometry

- Expected levels, elements, openings, rooms/spaces, and stable IDs exist once.
- Bounds, elevations, wall/opening relationships, stairs, roof edges, clearances, and topology meet the stated tolerance.
- Reapplying the same plan is a no-op or a controlled update, not duplicated geometry.
- Capture operations leave model geometry, visibility, camera state, and dirty state unchanged unless the user requested a scene update.

## Spatial use, when relevant

- Identify the actual user or material movement, start/end points, and the operating state needed for this task. Trace the important sequence (such as room → opening → forecourt → lane), not just the presence of its components. Check relevant bottlenecks, turns, level changes, door movement and activity/furniture space; do not require every possible state or a full simulation for a conceptual study.
- Use suitable native geometry measurements, sections, path checks or supported representative clearance envelopes. Record which method and state the evidence covers. Sparse rays/points can detect sampled obstructions but cannot prove unsampled gaps or a complete swept volume. Input design dimensions and bounding boxes alone do not establish as-built model clear widths/heights; read the actual relevant geometry when making that claim.
- Bind results to the source revision, relevant scene/layer visibility, open/closed states and any excluded objects with reasons. A deliberately hidden source copy can remain for recovery; do not hide a real participating obstruction merely to pass a test. Human figures may be presentation context, but excluding them does not establish crowd or activity compatibility.
- Use thresholds from the task's agreed detail level, evidenced project rules, or verified applicable standards. Keep unavailable conditions unverified and qualify the dependent conclusion; do not turn a planning check into construction, accessibility or code certification, nor block unrelated design discussion.

## Drawings

- Plan, elevation, and section agree on grids, levels, openings, slabs, stairs, and roof geometry.
- Layers/tags, text, dimensions, lineweights, annotation scales, viewports, sheet sizes, and plot styles are explicit and valid.
- DWG/DXF/PDF exports match their extensions and requested versions. Reopening preserves geometry and semantic IDs where supported.

## Colored plans and indicators, when requested

- Colored-plan walls, openings, room boundaries, labels, legends, scale, and north direction agree with the current checked plan. Required linework and text remain editable; decorative raster layers do not replace geometric evidence.
- Key metrics state the measured geometry/revision, boundary or space scope, inclusions/exclusions, formula, units, and target source. Compare area subtotals with totals on the same basis; unknown boundaries or rules remain unresolved rather than receiving a compliance pass.

## Visual review

- Choose views that answer the current design question, reusing valid captures. A whole-site view may show organization while a local section or close view reveals an interface; use only the needed combination. Do not require a fixed orthographic set, extra image generation, or an axonometric for an unrelated small edit.
- Check three independent claims at the agreed depth: **use** (supported by suitable spatial evidence), **fidelity** (consistent with the adopted source/phase and explicit protection), and **communication** (the intended audience can identify the idea and relevant relationships in this deliverable). Record gaps in the existing notes without forcing a score or a new report.
- View the actual affected model capture, drawing/export, board or slide at its intended delivery size/format. Check relevant hierarchy, labels, legends, context, contrast and material/lighting legibility; a clean unlabelled model view is not automatically a complete planning explanation. Judge a raw model capture as such, considering any accompanying explanation; do not require board graphics on every native view. Use the existing architecture-aesthetics media review when it helps, with the appropriate drawing/presentation tool for native edits.
- Clean views reveal the intended subject without severe clipping, UI overlays or accidental visibility states. If an obstruction hides the subject, distinguish camera/lighting/presentation clutter from a spatial fault before deciding what to change. Preserve the user's actual document state during temporary captures.
- Direct fidelity comparisons use aligned source revision, projection/camera and crop, or state that the comparison is qualitative. Inspect only relevant protected shapes, openings and boundaries; changed lighting or perspective alone does not establish a geometry defect. Exploration is assessed against its brief, not forced to copy the old image.
- Presentation renders remain non-authoritative for dimensions and construction. Generated labels or visual detail cannot upgrade unknown site evidence, prove invisible geometry, or replace numeric/source checks. New geometry proposed by an image must be treated as a design change before claiming a verified coordinated model.
- Before a design discussion, AI checks applicable basics and brings a concrete located issue, its effect and a proposed correction/tradeoff. User feedback resolves design intent and subjective choices at the existing key nodes; routine fixes do not require repeat approval. Adequate results stop here; expand or repeat review only for a material gap/change, not to manufacture variants.

## Delivery

- Requested source files and deliverables are listed with the provenance and QA needed to assess them. Do not create unrequested exchange formats, renders, or reports solely to fill this list.
- Each artifact records the project revision that produced it.
- Current deliverables have valid source dependencies and applicable QA. Superseded outputs are identified as historical, and a pass from an older changed subject is not presented as current validation.
- A newer baseline's changed objects are traced only to affected dependent outputs; unresolved correspondence remains a review item. Legends, schedules, dimensions, metrics, and renders preserve the source's status and accuracy limits rather than turning a schematic or reconstructed element into a surveyed or newly built one.
- Final paths exist, are readable, and do not silently overwrite the user's originals.
