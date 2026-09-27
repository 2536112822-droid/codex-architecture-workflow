# Render pipeline

## Codex-native path

1. For geometry changes, validate affected geometry and resolve defects introduced by the change. For material or presentation-only work, verify the affected appearance and that geometry is unchanged; reuse valid existing geometry checks. Record unrelated pre-existing model defects without automatically rebuilding or repairing them. Resolve defects that block the requested result only within the authorized scope.
2. Export a clean view with `su_render`; retain this PNG as the geometry baseline.
3. Use ImageGen with the baseline as the structural reference. A useful prompt separates invariants from variables:
   - invariants: camera, building mass, floor count, roof geometry, openings, major circulation;
   - variables: material finish, planting, furniture, sky, weather, season and lighting;
   - exclusions: no extra windows, doors, floors, cantilevers or structural members.
4. Compare the generated image with the baseline. Reject variants that alter invariants, even when they look attractive.
5. Make geometry changes in SketchUp, not by painting over the render; capture a new baseline and regenerate.

For image edits, provide the local SU capture to the image-generation tool and ask for the smallest visual change needed. Keep each accepted render linked to the source model revision and camera view.

## Optional RunningHub compatibility

If the user explicitly prefers the Leo workflows referenced in the original setup, `su_render` still produces a compatible clean input:

- [SU 一键室内效果图 V2 Kontext](https://pre-cn.runninghub.cn/ai-detail/1950110773063368705)
- [FLUX Kontext 言出法随](https://pre-cn.runninghub.cn/ai-detail/1933036680708493313)

These are optional third-party services. Do not claim current pricing, availability, speed, or success rate without checking them. The model and validation workflow remains authoritative regardless of render provider.

