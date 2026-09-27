---
name: architecture-studio
description: Orchestrate architectural projects across site evidence, design decisions, SketchUp or Rhino modeling, CAD drawings, and coordinated presentation outputs. Use for a site or brief to a building package, or work spanning these stages with linked revisions. Do not use for an isolated CAD, SketchUp, Rhino, site-analysis, or reference-review operation.
metadata:
  short-description: 建筑设计全流程总控与跨工具迭代
---

# Architecture Studio

## 文件保存与收尾

文件暂存、正式保存、中间数据保留与清理遵循当前全局 AGENTS.md 和本任务已有授权。已有授权或默认策略覆盖的事项直接执行，只询问仍缺少的必要决定；本节优先于下文及参考文件中的保存和保留默认值。


Coordinate the project through a versioned record of adopted sources and decisions. Different phases or alternatives may have separate geometry baselines; do not imply they share one aligned model. Keep facts, assumptions, geometry, drawings, views, validation, and deliverables linked instead of rebuilding each stage from memory.

## Start from evidence

When continuing an existing project or carrying work across tasks, first follow [project continuity](references/project-continuity.md). Recover the relevant decision state and actual artifact paths before proposing replacement geometry. Reuse the project's existing entry point and contract; a technical subproject contract is not automatically the authority for the entire design.

1. Identify the relevant supplied files and their versions; record actual reading coverage and missing material in the existing evidence index. Inspect images at original detail when scale, text, linework, openings, or material boundaries matter. Record what is visible, what is inferred, and what remains unknown.
2. Establish explicit units, coordinate reference, site identity, scale anchors, deliverables, and tolerances. Never infer coordinates or legal site boundaries from appearance alone.
3. Reuse existing progress and contracts. When a new project needs coordinated outputs or stable cross-tool handoffs, read [project contract](references/project-contract.md) and create the working `.architecture/architecture-project.json` under task staging, or update an existing contract within the authorized edit. Early discussion or a reference-only exploration can use the existing brief/progress until structured handoff is useful; do not create duplicate state merely because several future stages were mentioned. Preserve stable IDs and increment a contract revision after accepted changes.
4. Read [workflow modes](references/workflow-modes.md) only for the path that matches the request.

When selecting, combining, or revising a site/model baseline, or deciding whether an element exists or is proposed, use [source baselines and element status](references/source-baselines.md). Keep real-world evidence, model representation, and design phase distinct across site analysis, native models, drawings, metrics, and presentation. Missing model geometry does not establish real-world absence; a later source does not automatically replace an adopted design.

For a brief with several requirements or an evolving cross-stage design, use [brief to package](references/brief-to-package.md) to identify the current design maturity, stage outcome and appropriate spatial/technical coordination, then apply its requirement coverage steps. At stage handoff, substantive feedback, and delivery, carry forward still-valid requirements, this task's commitments, and unmet items with their actual scope. Verify the intended outcome, not only the existence of an object or file; a local task need not complete the whole project or enter construction stages.

## 与用户分阶段设计

按全局设计协作偏好推进：方向未定时先比较少量真正不同的方向，选定后按关键节点深化。先自主说明本次阶段及当前要交给用户判断的具体成果；阶段数量和顺序由任务决定，不把下文工具执行流程理解为一口气完成整套设计的授权。

- 早期方向用共同的场地、任务要求及比较口径，解释空间策略与代价；已有确认方向继续沿用。用户的一句话想法可以发展为候选，不直接当作全部设计关系已成立。
- 在会影响后续大量工作的节点展示可评成果，例如总体空间关系、入口到街巷的代表性样段、能校准表现深度的总览。先完成相关事实与使用逻辑检查，双方讨论设计取舍；不用文件保存成功替代方案成立，也不把基本查错交给用户。
- 给出自己的判断、重要矛盾和可行调整，再提少量会改变下一步的问题。沿用用户已确认的决定；需要讨论的决定未获得回复前，保留候选，只继续独立准备。阶段内研究、试做、核验及已确认内容的常规生产自主完成。
- 在已有进度或契约的允许字段中简记所选方向、反馈依据、未决项及下一节点。用户反馈更新其影响的成果与检查；发现新证据时可以返回相关节点，不重新启动全部流程。无需新增数据库或每阶段单独报告。

## Coordinate Codex-native execution

- Parallelize independent read-only evidence analysis, research, option critique, and QA when that capability is available. Keep one writer for each live desktop model or drawing, including SketchUp, Rhino, and AutoCAD; sequence writes when they share project state.
- Prefer structured, high-level, dry-run-capable tools. Bind every write to explicit units, project/document identity, expected revision, and an operation or idempotency key when supported.
- Treat raw Ruby, LISP, command strings, and generic eval tools as expert fallbacks. Inspect state immediately after a fallback and do not blindly replay a failed write.
- Use numeric inspection and clean captured views together. A screenshot cannot prove dimensions; an object count cannot prove visual hierarchy.
- For spatial design or presentation work, apply the relevant spatial-use and visual-review methods in [quality gates](references/quality-gates.md). Check intended use, fidelity to the adopted source, and communication separately. Choose evidence for the actual unresolved question; do not require a fixed view set or image-generation step.
- Before translating an adopted design into geometry, use the optional reference preparation in [brief to package](references/brief-to-package.md) when critical forms or interfaces remain ambiguous. Consistent detailed views can guide better modeling; this preparation serves a different purpose from reviewing the built model. Explain the value and cost before adding views, without requiring a fixed set or generation step.
- Use image generation for design exploration, optional modeling references, and presentation. It may preserve and enhance a verified model view, but it never becomes geometric or construction truth.

## Route stages

- Use `$site-analysis` for real geospatial, terrain, climate, access, and evidence-backed site diagrams.
- Use `$architecture-aesthetics` when a consequential design choice needs reference interpretation, alternative reasoning, or critique; reuse its exploration and convergence guidance without imposing a fixed option count or scoring form.
- Use `$su-model` for semantic massing, building geometry, materials, stable scenes, and multi-view model capture.
- Use `$rhino-model` for NURBS, complex curves/surfaces, and Grasshopper work. Honor the user's chosen tool; otherwise select the native model that fits the geometry and editing needs. Do not build duplicate SU and Rhino models by default.
- Use `$cad-tz-model` for editable architectural drawings, Tianzheng-assisted objects, dimensions, layouts, and DWG/DXF/PDF delivery.
- Use `$imagegen` for justified pre-model reference generation or to edit a verified model capture into a presentation render. For the latter, preserve camera, massing, openings, and primary boundaries; for the former, check consistency against the adopted design and reliable scale sources before modeling.
- Carry the user's image-model and route constraints across skills. Keep requested model, submitted parameters, and returned evidence distinct in existing task records; an unselectable or unreported backend remains unknown. Do not silently substitute a model or a separately billed route.
- Use document, spreadsheet, presentation, or PDF skills only when the requested deliverable needs that artifact format.

Before declaring a required tool unavailable, check tool discovery, the skill's connection recovery, and applicable alternatives allowed by the user's chosen workflow. Use Computer Use for supported desktop startup or defined UI steps when appropriate; do not bypass a specialist skill's interface restrictions, change the requested deliverable, or replay an uncertain write. If the action remains blocked, preserve completed artifacts, continue independent work, and provide a reviewable specification or patch plan for that action. State exactly what was not executed. Never report a queued command, generated image, or guessed layer as a completed model change.

## Iterate through gates

Use the parts of this loop required by the stage and requested deliverable:

`brief/spec -> validate as needed -> apply once -> inspect affected state -> review necessary views -> patch and revalidate only if a problem remains`

Reuse successful checks while the state they prove remains unchanged. After an accepted source change, follow the dependency and QA invalidation rules in [project contract](references/project-contract.md); a project revision alone does not invalidate unrelated evidence. Text-only revisions do not require a geometry cycle; a small presentation change does not require regenerating site data or models. A blocked tool prevents its dependent action, not independent work that is still possible.

When a project has saved files with explicit artifact dependencies and manual change tracking is becoming error-prone, use the optional [saved-artifact check](references/artifact-freshness.md). It reports file changes and affected dependents; it does not establish geometry quality or the state of an open application.

Before final delivery, read [quality gates](references/quality-gates.md). Record pass, warning, fail, evidence, and artifact paths in the project contract. A failed gate blocks only the dependent deliverable; keep completed, valid artifacts usable.

For substantive feedback or an observed problem, follow the feedback steps in [project continuity](references/project-continuity.md). Diagnose the specific cause, check where the same mechanism can recur, and repair the applicable project/method/workflow layers. A changed rule is not proof of improved design or reduced rework; keep unsupported outcomes pending.

## Deliver

Return the current revision, key assumptions, validation summary, and clickable absolute paths for source files and final artifacts. Follow the current global save and retention policy and this task's existing authorization. Use the specified or confirmed destination; ask only for missing necessary decisions. Deliver the required results and dependencies without archiving the entire run history. Overwrite only with explicit authorization.

At a meaningful stage end, leave the compact milestone and next action in the existing authorized project entry using [project continuity](references/project-continuity.md). No feedback is needed to close a completed stage; missing feedback does not establish acceptance. Later feedback resumes only the affected work from its actual source/version.
