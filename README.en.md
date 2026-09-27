# Codex Architecture Workflow

[简体中文](README.md) | [English](README.en.md)

A personal Codex workflow for architectural learning and design: reference research, site evidence, design decisions, editable models, CAD drawings, and delivery checks.

**Public release v0.1.0 · Chinese-first skills · MIT License**

This project is for architecture students, designers, and developers who want AI assistance while retaining design judgment and editable source files. Use one module for a focused task, or use the studio module to coordinate several stages. The repository contains skills, reference methods, helper scripts, and source code for selected local bridges. Applications, model services, and accounts must be obtained separately.

> **Adapt to your setup:** This workflow originated in a specific personal Windows environment. Software versions, paths, bridge configuration and available services vary. Downloaders should adjust and validate their own setup before real project work. See [Environment and adaptation](docs/ENVIRONMENT.md).

This English overview covers setup and the main working principles. The detailed guides and much of the skill content are currently in Chinese; this release does not claim complete English localization.

## Six modules

| Module | Purpose | Main requirements |
|---|---|---|
| [`architecture-studio`](plugins/architecture-studio/skills/architecture-studio/SKILL.md) | Coordinate briefs, decisions, models, drawings, checks, and project continuity | Codex; read-only planning and design discussion do not require commercial modeling software |
| [`architecture-aesthetics`](plugins/architecture-aesthetics/skills/architecture-aesthetics/SKILL.md) | Study and critique architectural projects, spatial strategies, theory, materials, and visual communication | Codex and readable reference material; Python for the persistent library scripts |
| [`site-analysis`](plugins/site-analysis/skills/site-analysis/SKILL.md) | Produce traceable site diagrams using real geographic, terrain, and climate data | Python, geospatial dependencies, network access, and available data services |
| [`su-model`](plugins/su-model/skills/su-model/SKILL.md) | Structured SketchUp modeling, local edits, materials, views, and SKP delivery | A licensed SketchUp installation, its extension, and the MCP bridge |
| [`cad-tz-model`](plugins/cad-tz-model/skills/cad-tz-model/SKILL.md) | Editable AutoCAD drawings, measurements, layers, and DWG/DXF delivery, with optional Tianzheng operations | AutoCAD 2025 and its bridge; Tianzheng T30 for Tianzheng-specific operations |
| [`rhino-model`](plugins/rhino-model/skills/rhino-model/SKILL.md) | Rhino curves, surfaces, solids, and Grasshopper workflows | Rhino 8, external RhinoMCP, and suitable desktop interaction tools |

## Quick start

Start with research and coordination. You do not need SketchUp, AutoCAD, Tianzheng, or Rhino to read a brief, discuss a design, or analyze supplied references.

For a Codex CLI version that supports plugin marketplaces:

```powershell
codex --version
codex plugin --help
codex plugin marketplace --help

codex plugin marketplace add 2536112822-droid/codex-architecture-workflow --ref main
codex plugin add architecture-studio@architecture-workflow
codex plugin add architecture-aesthetics@architecture-workflow
```

The marketplace index is [`.agents/plugins/marketplace.json`](.agents/plugins/marketplace.json), and its name is `architecture-workflow`. Check that the two plugins are visible in your Codex environment before using them. If a running conversation has not loaded newly installed skills, use the refresh or new-session mechanism provided by your client.

CLI features can vary by version. If the commands are unavailable, check the installed Codex version and its official plugin documentation. Do not replace an existing personal configuration just to work around an unsupported command. The `main` branch may change; record the commit and plugin version when reproducibility matters.

Add specialist modules when needed:

```powershell
codex plugin add site-analysis@architecture-workflow
codex plugin add su-model@architecture-workflow
codex plugin add cad-tz-model@architecture-workflow
codex plugin add rhino-model@architecture-workflow
```

Installing a skill does not install a commercial application or establish its desktop connection. See the Chinese [installation guide](docs/INSTALL.md) and [bridge guide](docs/BRIDGES.md) for prerequisites and configuration. The bridge installer at `scripts/install-bridges.ps1` only handles the scope described in that guide.

## Prompts you can use

**Read a brief before modeling:**

> Use $architecture-studio. Read my brief and drawings first. Recover confirmed decisions and separate facts, assumptions, and missing information. Explain the current stage, the reviewable output, and the evidence needed to complete it. If the direction is still open, compare a few meaningfully different spatial approaches and wait for my choice before dependent development.

**Study a reference project:**

> Use $architecture-aesthetics to analyze these references. Explain how activities, spatial organization, materials, construction, and presentation support the design. Identify useful ideas and the conditions for transferring them. Show the analysis before asking what, if anything, I want saved to a long-term or project-specific library.

**Build an evidence-based site analysis:**

> Use $site-analysis with the real address or coordinates and photos I provide. Verify location, study extent, and source coverage. Distinguish the study area from a verified property boundary. Produce traceable diagrams and appropriate quality checks; label missing data as unknown and keep schematic assumptions separate from measured facts.

**Edit a native model while protecting the original:**

> Use $su-model. Confirm the active model, units, and revision, then save a recoverable working copy before making the requested changes. Check actual dimensions, relevant circulation clearances, and necessary views. Preserve independently editable components, verify the saved SKP, and report anything that remains unverified. Do not overwrite the original.

The last prompt requires a connected SketchUp environment. Use the corresponding Rhino or CAD module for those applications, with an explicit target document and edit scope.

## How the workflow works

### Design in stages

The assistant carries out research, reversible trials, and basic checks within the agreed stage. At decisions that would affect substantial downstream work—spatial organization, a representative interface, major openings, roof relationships, or presentation depth—it presents concrete work, explains trade-offs, and seeks the user's design decision.

Confirmed choices are reused. Routine production does not require repeated approval. An unanswered question is not approval, although independent preparation can continue. Stages should fit the task: a reference study need not become a building model, and a local edit need not restart the whole project.

### Keep evidence and decisions connected

Read supplied material before deciding what external research is useful. Record what was actually inspected and distinguish verified facts, inferences, and unknowns. Real-world status, model representation, and design phase are separate claims: a missing model object does not prove that the real object is absent.

When continuing a project, recover adopted decisions, alternatives, superseded work, unresolved issues, and actual file locations. A file named “final” or a newer timestamp is not sufficient evidence of design approval.

### Protect editable sources

Create a recoverable copy before changing important files. Confirm document identity, units, and state, then work in small, inspectable batches. Keep one automated writer per live model or drawing. If a write times out, inspect the actual state before retrying; do not assume that every bridge offers transactions, revision protection, or idempotency.

### Check the right thing

Images support visual judgment. Native geometry and drawings support dimensional checks and editability. A generated rendering cannot establish measured dimensions, hidden structure, compliance, or complete circulation clearance. A saved file is not proof that the design works.

Use numerical checks, relevant views, actual editing behavior, and save verification as appropriate to the deliverable. Reuse a successful check only while the state it proves remains unchanged. Report missing evidence instead of marking it as passed.

### Update affected outputs

Models, drawings, calculations, and presentation images may share sources, scripts, or parameters. When a source changes, identify affected objects and dependencies before updating outputs. A changed file hash or project revision calls for review, not an automatic rebuild of every artifact. Camera and visibility changes can also affect images and checks based on visible geometry.

At meaningful handoffs, leave a compact continuation record in the existing project entry: current usable version, decisions and reasons, completed checks, file locations, unresolved issues, and next action. A completed stage does not imply completion or approval of the entire project.

### Let the user control the reference library

After each learning session, show the actual analysis before asking which aspects may be saved, whether they belong to a project or long-term library, and whether they are reference knowledge, a candidate method, or an explicit preference. Archiving source files is a separate choice.

Silence, liking an image, a previous session's consent, or the assistant's own trial does not authorize a new library entry. Reference knowledge does not automatically become a preference. The library is an editable record, not model-weight training, and a new project does not silently inherit another project's design decisions.

The detailed Chinese guide is [WORKFLOW.md](docs/WORKFLOW.md). An optional [architecture working-rules template](templates/AGENTS.architecture.md) can be reviewed and merged manually; it does not replace your global `AGENTS.md` automatically.

## Dependencies and limits

- **Commercial applications:** SketchUp, AutoCAD, Tianzheng, and Rhino must be installed and licensed separately. This repository does not distribute their installers, licenses, or proprietary SDK binaries.
- **Rhino integration:** The necessary MIT-licensed RhinoMCP Python server and contracts are included with attribution. The Rhino-side desktop plugin must be installed separately. See [third-party notices](THIRD_PARTY_NOTICES.md) and the bridge guide.
- **Optional creative tools:** Creative Production is third-party proprietary content and is not redistributed. Image generation, document, PDF, and presentation tools are optional extensions when available; they are not required for basic research and project coordination.
- **Services and data:** Model services and external data sources have their own access conditions, costs, coverage, and availability. The site-analysis dependencies are listed in [`requirements.txt`](plugins/site-analysis/skills/site-analysis/scripts/requirements.txt).
- **Personal data:** The public package excludes private design projects, conversation history, personal taste-library contents, account configuration, and secrets. Keep your own credentials and private references outside version control.
- **Validation scope:** Skill installation, bridge connection, native file creation, geometry validation, and operation on another computer are separate checks. This release does not claim unattended design, universal software compatibility, or successful validation on every user's machine.

The workflow does not replace surveying, engineering calculations, current local code checks, or qualified professional judgment. Use diagrams and generated images within the limits of their actual evidence.

See [release validation](docs/VALIDATION.md) for the checks completed and the desktop behaviors still requiring local verification.

## Share and contribute

Share the repository with friends:

[github.com/2536112822-droid/codex-architecture-workflow](https://github.com/2536112822-droid/codex-architecture-workflow)

They can begin with the two foundation modules and add desktop tools later. Please report reproducible issues through [GitHub Issues](https://github.com/2536112822-droid/codex-architecture-workflow/issues), including the module, software version, expected behavior, and a minimal public example. Do not upload credentials, private projects, or reference files you are not allowed to redistribute.

The original material in this repository is released under the [MIT License](LICENSE). External software, services, and referenced resources remain subject to their respective licenses.



