# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "rasterio",
#   "srtm.py",
#   "pytest"
# ]
# ///
"""
Pytest tests for gpelex.py
Run with: `uvx --with-requirements gpelex.py pytest test_gpelex.py`
"""

import numpy as np
import rasterio
import srtm
from rasterio.transform import Affine

from gpelex import GPX, ElevationDataManager, add_elevation_to_gpx


def create_tif_from_elevation(
    path: str, lat: float, lon: float, elevation_value: float, pixel_size: float = 0.01
):
    """Create a GeoTIFF file from a single elevation value."""
    elevation_array = np.array([[elevation_value]], dtype=np.float32)
    transform = Affine(pixel_size, 0, lon, 0, -pixel_size, lat)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=1,
        width=1,
        count=1,
        dtype=elevation_array.dtype,
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999,
    ) as dst:
        dst.write(elevation_array, 1)


def create_gpx_file(gpx_path: str, with_elevation: bool = False) -> None:
    """Create a test GPX file with or without elevation data."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="GPeleX" xmlns="http://www.topografix.com/GPX/1/1">',
        "  <trk>",
        "    <trkseg>",
    ]
    ele = "<ele>100.0</ele>" if with_elevation else ""
    for lat, lon in [(48.8584, 2.2945), (51.5074, -0.1278), (40.7128, -74.006)]:
        lines.append(f'      <trkpt lat="{lat}" lon="{lon}">{ele}</trkpt>')
    lines.extend(["    </trkseg>", "  </trk>", "</gpx>"])

    with open(gpx_path, "w") as f:
        f.write("\n".join(lines))


def test_add_elevation_to_gpx_without_elevation(tmp_path):
    """Test adding elevation data to a GPX file without existing elevation data."""
    input_gpx = tmp_path / "input.gpx"
    output_gpx = tmp_path / "output.gpx"

    create_gpx_file(str(input_gpx), with_elevation=False)
    add_elevation_to_gpx(str(input_gpx), None, str(output_gpx), force_overwrite=False)

    gpx = GPX(output_gpx)
    for point in gpx.points():
        assert point.elevation is not None


def test_add_elevation_to_gpx_with_elevation_no_force(tmp_path):
    """Test that existing elevation data is not overwritten without --force."""
    input_gpx = tmp_path / "input.gpx"
    output_gpx = tmp_path / "output.gpx"

    create_gpx_file(str(input_gpx), with_elevation=True)
    add_elevation_to_gpx(str(input_gpx), None, str(output_gpx), force_overwrite=False)

    assert not output_gpx.exists()


def test_add_elevation_to_gpx_with_elevation_force(tmp_path):
    """Test that existing elevation data is overwritten with --force."""
    input_gpx = tmp_path / "input.gpx"
    output_gpx = tmp_path / "output.gpx"

    create_gpx_file(str(input_gpx), with_elevation=True)
    add_elevation_to_gpx(str(input_gpx), None, str(output_gpx), force_overwrite=True)

    gpx = GPX(output_gpx)
    for point in gpx.points():
        assert point.elevation is not None


def test_query_elevation_from_srtm_api():
    """Test querying elevation data from the srtm.py library."""
    with ElevationDataManager(None) as elevation_manager:
        elevation = elevation_manager.query_elevation(48.8584, 2.2945)
    assert isinstance(elevation, float)


def test_query_elevation_from_dem_file(tmp_path):
    """Test querying elevation data from a DEM file and compare with SRTM API."""
    elevation_data = srtm.get_data()
    elevation_api = float(elevation_data.get_elevation(48.8584, 2.2945))
    with ElevationDataManager(None) as mgr:
        assert elevation_api == mgr.query_elevation(48.8584, 2.2945)

    tif_path = tmp_path / "dem_test.tif"
    create_tif_from_elevation(tif_path, 48.8584, 2.2945, elevation_api)
    with ElevationDataManager([str(tif_path)]) as mgr:
        assert mgr.query_elevation(48.8584, 2.2945) == elevation_api

    tif_path2 = tmp_path / "dem_test2.tif"
    create_tif_from_elevation(tif_path2, 51.5074, -0.1278, 125.0)
    with ElevationDataManager([str(tif_path), str(tif_path2)]) as mgr:
        assert mgr.query_elevation(48.8584, 2.2945) == elevation_api
        assert mgr.query_elevation(51.5074, -0.1278) == 125.0


def test_gpx_class_parse(tmp_path):
    """Test the GPX class for parsing GPX files."""
    input_gpx = tmp_path / "input.gpx"
    output_gpx = tmp_path / "output.gpx"

    create_gpx_file(str(input_gpx), with_elevation=True)
    gpx = GPX(input_gpx)
    points = list(gpx.points())
    assert len(points) == 3  # 3 waypoints in the GPX file

    for point in points:
        assert point.elevation == 100.0

    assert abs(points[0].latitude - 48.8584) < 0.0001
    assert abs(points[0].longitude - 2.2945) < 0.0001

    assert abs(points[1].latitude - 51.5074) < 0.0001
    assert abs(points[1].longitude - (-0.1278)) < 0.0001

    assert abs(points[2].latitude - 40.7128) < 0.0001
    assert abs(points[2].longitude - (-74.0060)) < 0.0001

    # Test writing with GPX class
    gpx.write(str(output_gpx))
    gpx2 = GPX(output_gpx)
    points2 = list(gpx2.points())
    assert len(points2) == 3
