# Data sources and caveats

## OpenStreetMap / Overpass

- Building footprints, roads, land use, water, and transit come from OSM and vary in completeness by region. Australian urban centers are usually good; rural sites are sparser.
- Treat missing data as a data gap, not as proof that a feature does not exist. Verify against the user's photos and satellite image.
- Respect Overpass usage limits: avoid parallel/duplicated queries, keep areas modest, and cache results.

## Elevation

- SRTM 1-arc-second (~30 m) tiles are downloaded from AWS `elevation-tiles-prod` and cropped locally. Use them for terrain trend, not for precise civil grading.
- The script downloads whole tiles, so it avoids fragile point-query rate limits. It still does not claim sub-30 m accuracy.
- A user-supplied survey/contour map always outranks SRTM. If a contour map is available, digitize or georeference it and reconcile with the DEM.

## Climate

- Open-Meteo archive is model reanalysis, not a local weather station. Use it for long-term average wind and solar patterns, then cross-check with any local airport/weather station data if the user has it.
- Wind direction is meteorological direction (where the wind comes from). Keep this convention in the legend.

## Coordinate extraction from screenshots

- Google Maps share links often embed coordinates after `@lat,lon,zoom`. Apple/Amap/Baidu use different schemes; check the URL or visible text.
- EXIF GPS can be read with `pillow` or `exiftool`.
- If coordinates cannot be recovered, ask the user for a single site point and use images only as orientation/photo evidence.

## Image overlays

- A screenshot is not automatically georeferenced. To overlay it accurately, the user must provide at least two control points with known coordinates (or an already georeferenced raster).
- Without control points, place imagery in an inset or side-by-side figure and label it "not to scale / orientation only".

## Attribution

- Always include `OSM © OpenStreetMap contributors`, `SRTM`, and `Open-Meteo` in reports and figure notes. Do not remove or obscure attributions when using basemaps.
