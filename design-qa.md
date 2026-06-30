# Design QA

## Reference

`codex-clipboard-3eb55b0f-4a97-4ec3-b5f3-60aabbf5cadb.png`

## Checks

- Initial state: large centered Mapbox globe, no visible card border.
- Scroll transition: globe camera zooms toward Guangdong while the globe moves left.
- Card reveal: border opacity begins late in the transition and resolves to a 14px rounded map card.
- Replay state: existing decision controls, route playback, marker animation, and camera following remain functional.
- Reverse scroll: the same progress-driven geometry and camera values return to the initial globe state.
- Responsive state: mobile keeps the existing stacked layout.
- Build: `npm run build` passes.

## Result

final result: passed
