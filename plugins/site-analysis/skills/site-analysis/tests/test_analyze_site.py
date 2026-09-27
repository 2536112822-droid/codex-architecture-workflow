import importlib.util
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ["SITE_ANALYSIS_SKIP_BOOTSTRAP"] = "1"

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_site.py"
SPEC = importlib.util.spec_from_file_location("site_analysis_runtime", SCRIPT)
site = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(site)


class SiteAnalysisContractTests(unittest.TestCase):
    def setUp(self):
        site.OSM_QUERY_LOG.clear()

    def quality_inputs(self):
        args = site.parse_args(["--lat", "-32.9", "--lon", "151.7"])
        utm = site.utm_crs_for(args.lon, args.lat)
        layers = {key: site.gpd.GeoDataFrame(geometry=[site.Point(0, 0)], crs=utm)
                  for key in ("buildings", "roads", "landuse", "transit", "photos")}
        boundary = layers["buildings"]
        return args, utm, layers, boundary

    def fetch_synthetic_dem(self, complete=False, sparse=False):
        class Tile:
            shape = (3601, 3601)

            def __getitem__(self, indices):
                rows, cols = indices
                values = (rows + cols).astype(float)
                if sparse:
                    values[:] = site.np.nan
                    values.flat[:3] = 100.0
                elif not complete:
                    values[cols % 2 == 0] = site.np.nan
                return values

        response = unittest.mock.Mock(content=b"synthetic-hgt")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(site, "_bounds_for_radius", return_value=(0.5, 0.5006, 0.5, 0.5006)), \
                patch.object(site.requests, "get", return_value=response), \
                patch.object(site, "_read_hgt", return_value=Tile()):
            return site.fetch_elevation_grid(0.5, 0.5, 30, site.utm_crs_for(0.5, 0.5),
                                             cache_dir=Path(tmp))

    def test_dem_fill_does_not_turn_partial_source_into_full_coverage(self):
        terrain = self.fetch_synthetic_dem()
        self.assertEqual(terrain["finite_fraction"], 1.0)
        self.assertLess(terrain["observed_finite_fraction"], 0.99)
        self.assertGreater(terrain["interpolated_fraction"], 0.0)
        self.assertAlmostEqual(terrain["observed_finite_fraction"] + terrain["interpolated_fraction"], 1.0)
        args, utm, layers, boundary = self.quality_inputs()
        qa = site.evaluate_quality(args, utm, (0, 0, 1000, 1000), layers, terrain, {}, boundary)
        check = next(c for c in qa["checks"] if c["name"] == "elevation_coverage")
        self.assertEqual(check["status"], "warn")
        self.assertIn("interpolated", check["detail"])

    def test_complete_dem_passes_and_too_sparse_dem_still_fails(self):
        terrain = self.fetch_synthetic_dem(complete=True)
        self.assertEqual(terrain["observed_finite_fraction"], 1.0)
        self.assertEqual(terrain["interpolated_fraction"], 0.0)
        args, utm, layers, boundary = self.quality_inputs()
        qa = site.evaluate_quality(args, utm, (0, 0, 1000, 1000), layers, terrain, {}, boundary)
        self.assertEqual(next(c for c in qa["checks"] if c["name"] == "elevation_coverage")["status"], "pass")
        with self.assertRaisesRegex(RuntimeError, "Elevation data unavailable"):
            self.fetch_synthetic_dem(sparse=True)

    def test_dem_98_percent_source_warns_despite_complete_final_grid(self):
        args, utm, layers, boundary = self.quality_inputs()
        terrain = {"elevation": site.np.ones((10, 10)), "finite_fraction": 1.0,
                   "observed_finite_fraction": 0.98, "interpolated_fraction": 0.02}
        qa = site.evaluate_quality(args, utm, (0, 0, 1000, 1000), layers, terrain, {}, boundary)
        check = next(c for c in qa["checks"] if c["name"] == "elevation_coverage")
        self.assertEqual(check["status"], "warn")
        self.assertIn("98.0%", check["detail"])

    def test_partial_osm_failure_keeps_status_through_projection_and_report(self):
        empty = site.gpd.GeoDataFrame(geometry=[], crs=site.WGS84)

        def feature(center, tags, dist):
            if "building" in tags:
                raise RuntimeError("synthetic connection failure")
            return empty.copy()

        edges = site.gpd.GeoDataFrame({"highway": ["residential"]},
                                     geometry=[site.Point(151.7, -32.9)], crs=site.WGS84)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(site.ox, "features_from_point", side_effect=feature), \
                patch.object(site.ox, "graph_from_point", return_value=object()), \
                patch.object(site.ox, "graph_to_gdfs", return_value=edges):
            raw = site.fetch_osm(-32.9, 151.7, 50, Path(tmp))
        args, utm, layers, boundary = self.quality_inputs()
        layers.update({key: site.project_gdf(value, utm) for key, value in raw.items()})
        layers["transit"] = site.pointify_markers(layers["transit"])
        statuses = site.osm_source_status(layers)
        self.assertEqual(statuses["buildings"]["status"], "unavailable")
        self.assertIn("connection failure", statuses["buildings"]["reason"])
        self.assertEqual(statuses["landuse"]["status"], "empty")
        self.assertEqual(statuses["transit"]["status"], "empty")
        self.assertEqual(statuses["roads"]["status"], "available")
        qa = site.evaluate_quality(args, utm, (0, 0, 1000, 1000), layers, {}, {}, boundary)
        self.assertEqual(next(c for c in qa["checks"] if c["name"] == "osm_layers")["status"], "warn")
        provenance = site.build_provenance(args, "test", Path.cwd(), utm, {}, {}, layers)
        self.assertEqual(provenance["osm"]["layer_status"], statuses)
        self.assertTrue(any(q["status"] == "error" for q in provenance["osm"]["queries"]))

    def test_overpass_fallback_recovers_without_inventing_source_time(self):
        result = object()
        fn = unittest.mock.Mock(side_effect=[RuntimeError("first endpoint failed"), result])
        with patch.object(site, "utc_now_iso", return_value="2026-09-19T00:00:00+00:00"):
            self.assertIs(site._query_osm(fn, "buildings"), result)
        self.assertEqual([q["status"] for q in site.OSM_QUERY_LOG], ["error", "returned"])
        query = site.OSM_QUERY_LOG[-1]
        self.assertEqual(query["accessed_at_utc"], query["retrieved_at_utc"])
        self.assertIsNone(query["source_observed_at_utc"])
        self.assertEqual(query["cache_status"], "unknown")
        self.assertNotIn("age", query)

    def test_osmnx_empty_exception_is_specific_and_runs_do_not_share_logs(self):
        args, utm, layers, _ = self.quality_inputs()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(site.ox, "features_from_point", side_effect=site.ox._errors.InsufficientResponseError(
                    "No matching features. Check query location, tags, and log.")), \
                patch.object(site.ox, "graph_from_point", return_value=object()), \
                patch.object(site.ox, "graph_to_gdfs", side_effect=ValueError("malformed graph")):
            raw = site.fetch_osm(args.lat, args.lon, 50, Path(tmp))
            self.assertEqual(raw["buildings"].attrs["source_status"]["status"], "no_matches")
            self.assertEqual(raw["roads"].attrs["source_status"]["status"], "unavailable")
            site.OSM_QUERY_LOG.append({"layer": "previous_run"})
            raw = site.fetch_osm(args.lat, args.lon, 50, Path(tmp))
            self.assertFalse(any(q["layer"] == "previous_run" for q in site.OSM_QUERY_LOG))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(site.ox, "features_from_point", side_effect=site.ox._errors.InsufficientResponseError(
                    "Malformed response")), \
                patch.object(site.ox, "graph_from_point", side_effect=ValueError("no graph")):
            raw = site.fetch_osm(args.lat, args.lon, 50, Path(tmp))
            self.assertEqual(raw["buildings"].attrs["source_status"]["status"], "unavailable")

    def test_real_osmnx_feature_empty_payload_remains_distinct_from_failure(self):
        edges = site.gpd.GeoDataFrame({"highway": ["residential"]},
                                     geometry=[site.Point(151.7, -32.9)], crs=site.WGS84)
        for payload in ({"elements": []}, {"elements": [], "remark": "runtime error: Query timed out"}):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(site.requests.sessions.Session, "request", side_effect=AssertionError("network forbidden")), \
                    patch.object(site.ox.features._overpass, "_download_overpass_features",
                                 side_effect=lambda *args, **kwargs: iter([payload])), \
                    patch.object(site.ox, "graph_from_point", return_value=object()), \
                    patch.object(site.ox, "graph_to_gdfs", return_value=edges):
                raw = site.fetch_osm(-32.9, 151.7, 50, Path(tmp))
            self.assertEqual(raw["buildings"].attrs["source_status"]["status"], "no_matches")
            self.assertNotEqual(raw["buildings"].attrs["source_status"]["status"], "empty")
            self.assertEqual(raw["roads"].attrs["source_status"]["status"], "available")

    def test_real_osmnx_timeout_remark_does_not_prevent_fallback_recovery(self):
        responses = [iter([{"elements": [], "remark": "runtime error: Query timed out"}]),
                     iter([{"elements": [{"type": "node", "id": 1, "lat": -32.9,
                                           "lon": 151.7, "tags": {"building": "yes"}}]}])]
        with patch.object(site.requests.sessions.Session, "request", side_effect=AssertionError("network forbidden")), \
                patch.object(site.ox.features._overpass, "_download_overpass_features", side_effect=responses):
            result = site._query_osm(lambda: site.ox.features_from_point(
                (-32.9, 151.7), tags={"building": True}, dist=50), "buildings")
        self.assertEqual(len(result), 1)
        self.assertEqual([q["status"] for q in site.OSM_QUERY_LOG], ["error", "returned"])

    def test_notes_make_missing_osm_and_interpolation_visible(self):
        _, _, layers, _ = self.quality_inputs()
        layers["buildings"].attrs["source_status"] = {"status": "unavailable"}
        layers["transit"].attrs["source_status"] = {"status": "skipped"}
        fig = site.plt.figure()
        try:
            site.add_osm_status_note(fig, layers)
            site.add_terrain_status_note(fig, {"observed_finite_fraction": 0.5,
                                                 "interpolated_fraction": 0.5})
            texts = " ".join(text.get_text() for text in fig.texts)
            self.assertIn("buildings: UNAVAILABLE", texts)
            self.assertIn("transit: SKIPPED", texts)
            self.assertIn("50.0%", texts)
        finally:
            site.plt.close(fig)

    def test_missing_tags_never_become_nan_strings_or_water(self):
        row = site.pd.Series(
            {"landuse": site.np.nan, "leisure": None, "natural": None,
             "waterway": site.np.nan, "water": None}
        )
        self.assertEqual(site.normalize_tag(site.np.nan), "")
        self.assertEqual(site.classify_landuse(row), "other")

    def test_polygon_pois_are_rendered_as_points(self):
        polygon = site.Point(0, 0).buffer(10)
        gdf = site.gpd.GeoDataFrame(
            {"name": ["Library"]}, geometry=[polygon], crs="EPSG:3857"
        )
        points = site.pointify_markers(gdf)
        self.assertEqual(points.geometry.iloc[0].geom_type, "Point")
        self.assertEqual(points.source_geometry_type.iloc[0], "Polygon")

    def test_north_arrow_points_up(self):
        tail, tip = site.north_arrow_vector()
        self.assertEqual(tail[0], tip[0])
        self.assertLess(tail[1], tip[1])

    def test_scale_bar_uses_architectural_round_number(self):
        self.assertEqual(site.choose_scale_bar_length(1000), 200)
        self.assertEqual(site.choose_scale_bar_length(310), 50)

    def test_climate_requests_and_normalizes_metres_per_second(self):
        params = site.climate_request_params(-32.9, 151.7, 2022, 2023)
        self.assertEqual(params["wind_speed_unit"], "ms")
        wind = site.wind_rose_data(
            {
                "hourly": {
                    "wind_direction_10m": [0, 90],
                    "wind_speed_10m": [3.6, 7.2],
                },
                "hourly_units": {"wind_speed_10m": "km/h"},
            }
        )
        self.assertTrue(site.np.allclose(wind["speed"], [1.0, 2.0]))
        rose = site.wind_rose_frequencies(wind["direction"], wind["speed"])
        self.assertAlmostEqual(float(rose["frequencies"].sum()), 1.0)

    def test_run_ids_cannot_escape_the_output_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                site.create_run_dir(Path(tmp), "../outside")

    def test_manifest_is_explicit_and_hash_addressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "diagram.svg"
            artifact.write_text("<svg/>", encoding="utf-8")
            entries = site.build_output_manifest([artifact, artifact], root)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["path"], "diagram.svg")
            self.assertEqual(len(entries[0]["sha256"]), 64)
            json.dumps(entries)


if __name__ == "__main__":
    unittest.main()
