# Analysis catalog

Use these standard architectural site-analysis drawings. Always project to a metric CRS before calculating distances, slopes, or areas.

## Site context / figure-ground

- Buildings filled black or dark grey, ground white/very light grey, water light blue, green light green.
- Show major roads as dark lines and minor roads as thin grey lines.
- Add site boundary (if known) in red, north arrow, scale bar.

## Circulation and access

- Classify roads by OSM `highway`: motorway/trunk/primary thick; secondary/tertiary medium; residential/service/footway/path/cycleway thin.
- Mark transit stops (bus, tram, rail) and pedestrian routes.

## Land use / green-blue network

- Green: `landuse=grass/forest/meadow`, `leisure=park/garden`, `natural=wood/scrub/grassland`.
- Blue: `natural=water`, `waterway`, `landuse=reservoir/basin`.
- Grey: built-up/commercial/industrial/residential where tags are available.

## Terrain

- Contours at the requested interval (default 5 m), labeled where feasible.
- Slope in degrees, binned into a clear ramp (flat < 2°, gentle 2–6°, moderate 6–12°, steep 12–20°, very steep > 20°).
- Aspect in 8 compass sectors; use a symmetric color wheel so flat areas are neutral.
- Hillshade with azimuth from the south/east or from the prevailing sun direction.

## Sun / solar

- Use latitude and date ranges to compute a sun path if implementing it manually; otherwise summarize Open-Meteo shortwave/direct radiation and note seasonal variation.
- Hillshade for winter/summer solstice or equinox is more informative than a single generic hillshade.

## Wind

- Aggregate hourly wind direction into 16 sectors and speed into calm/light/moderate/strong bands.
- Draw a wind rose with north up. Use the same color ramp across projects.

## Views and photo viewpoints

- Plot photo positions as numbered markers when GPS is available; otherwise show them as a non-georeferenced inset. Label the direction of view.

## Common drawing conventions

- North arrow: a simple arrow with "N", rotated to true north (no declination unless stated).
- Scale bar: a clean segmented bar in meters (e.g. 0 / 100 / 200 m).
- Legend: boxed, top or bottom right, with no unnecessary items.
- Source note: `OSM © OpenStreetMap contributors`, `SRTM/OpenTopoData`, `Open-Meteo`, and the retrieval date.
