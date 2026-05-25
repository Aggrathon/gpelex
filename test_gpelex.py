# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pytest",
#   "rasterio",
#   "srtm.py",
#   "numpy",
#   "scipy",
# ]
# ///
"""
Pytest tests for gpelex.py
Run with: `uvx --with-requirements gpelex.py pytest test_gpelex.py`
"""

import tarfile
import zipfile

import numpy as np
import rasterio
import srtm
from rasterio.transform import from_bounds

from gpelex import GPX, ElevationDataManager, add_elevation_to_gpx


def create_tif_from_single_elevation(
    path: str, latitude: float, longitude: float, elevation: float = 0.0
):
    create_tif_from_multiple_elevations(
        path,
        longitude - 0.0001,
        latitude - 0.0001,
        longitude + 0.0001,
        latitude + 0.0001,
        np.full((1, 1), elevation),
    )


def create_tif_from_multiple_elevations(
    path: str,
    west: float,
    south: float,
    east: float,
    north: float,
    elevations: np.ndarray,
):
    height, width = elevations.shape
    transform = from_bounds(west, south, east, north, width, height)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=elevations.dtype,
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999,
    ) as dst:
        dst.write(elevations, 1)


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
    add_elevation_to_gpx(str(input_gpx), None, str(output_gpx), overwrite=False)

    gpx = GPX(output_gpx)
    for point in gpx.points():
        assert point.elevation is not None


def test_add_elevation_to_gpx_with_elevation_no_force(tmp_path):
    """Test that existing elevation data is not overwritten without --force."""
    input_gpx = tmp_path / "input.gpx"
    output_gpx = tmp_path / "output.gpx"

    create_gpx_file(str(input_gpx), with_elevation=True)
    add_elevation_to_gpx(
        str(input_gpx), None, str(output_gpx), overwrite=False, verbose=1
    )

    assert not output_gpx.exists()


def test_add_elevation_to_gpx_with_elevation_force(tmp_path):
    """Test that existing elevation data is overwritten with --force."""
    input_gpx = tmp_path / "input.gpx"
    output_gpx = tmp_path / "output.gpx"

    create_gpx_file(str(input_gpx), with_elevation=True)
    add_elevation_to_gpx(
        str(input_gpx), None, str(output_gpx), overwrite=True, verbose=2
    )

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
    elevation = float(elevation_data.get_elevation(48.8584, 2.2945))
    with ElevationDataManager(None) as mgr:
        assert elevation == mgr.query_elevation(48.8584, 2.2945)

    tif_path = tmp_path / "dem_test.tif"
    create_tif_from_single_elevation(tif_path, 48.8584, 2.2945, elevation)
    with ElevationDataManager([str(tif_path)]) as mgr:
        assert mgr.query_elevation(48.8584, 2.2945) == elevation

    tif_path2 = tmp_path / "dem_test2.tif"
    create_tif_from_single_elevation(tif_path2, 51.5074, -0.1278, 125.0)
    with ElevationDataManager([str(tif_path), str(tif_path2)], verbose=True) as mgr:
        assert mgr.query_elevation(48.8584, 2.2945) == elevation
        assert mgr.query_elevation(51.5074, -0.1278) == 125.0


def test_query_archive_zip(tmp_path):
    """Test querying elevation from ZIP archive."""
    create_tif_from_single_elevation(tmp_path / "north.tif", 48.8584, 2.2945, 175.0)
    create_tif_from_single_elevation(tmp_path / "south.tif", 51.5074, -0.1278, 124.0)
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(tmp_path / "north.tif", "north.tif")
        zf.write(tmp_path / "south.tif", "tmp/south.tif")
    with ElevationDataManager([str(zip_path)]) as mgr:
        assert mgr.query_elevation(48.8584, 2.2945) == 175.0
        assert mgr.query_elevation(51.5074, -0.1278) == 124.0
    with ElevationDataManager([str(zip_path)], extract=True) as mgr:
        assert mgr.query_elevation(48.8584, 2.2945) == 175.0
        assert mgr.query_elevation(51.5074, -0.1278) == 124.0


def test_query_archive_tar(tmp_path):
    """Test querying elevation from TAR archive."""
    create_tif_from_single_elevation(tmp_path / "east.tif", 40.7128, -74.0060, 10.0)
    create_tif_from_single_elevation(tmp_path / "west.tif", 35.6762, 139.6503, 40.0)
    tar_path = tmp_path / "test.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(tmp_path / "east.tif", "east.tif")
        tf.add(tmp_path / "west.tif", "tmp/west.tif")
    with ElevationDataManager([str(tar_path)]) as mgr:
        assert mgr.query_elevation(40.7128, -74.0060) == 10.0
        assert mgr.query_elevation(35.6762, 139.6503) == 40.0
    with ElevationDataManager([str(tar_path)], extract=True) as mgr:
        assert mgr.query_elevation(40.7128, -74.0060) == 10.0
        assert mgr.query_elevation(35.6762, 139.6503) == 40.0


def test_interpolate_elevations(tmp_path):
    """Test creating a GeoTIFF from multiple elevation values using from_bounds."""
    elevations = np.array(
        [
            [100.0, 102.0, 101.0],
            [103.0, 104.0, 105.0],
            [108.0, 107.0, 106.0],
        ],
        dtype=np.float32,
    )
    west, south, east, north = 2.2940, 48.8580, 2.2950, 48.8590
    tif_path = tmp_path / "multi_elev.tif"
    create_tif_from_multiple_elevations(
        str(tif_path), west, south, east, north, elevations
    )
    points = np.array(
        [
            [[y, x] for x in np.linspace(west, east, 7)[1:-1:2]]
            for y in reversed(np.linspace(south, north, 7)[1:-1:2])
        ]
    )

    with ElevationDataManager([str(tif_path), str(tif_path)]) as mgr:
        assert mgr.query_elevation(south + 1e-4, west + 1e-4) > elevations[2, 0]
        assert mgr.query_elevation(north - 1e-4, west + 1e-4) < elevations[0, 0]
        assert mgr.query_elevation(north - 1e-4, east - 1e-4) < elevations[0, 2]
        for i in range(3):
            for j in range(3):
                for k in range(max(i - 1, 0), min(i + 2, 3)):
                    for l in range(max(j - 1, 0), min(j + 2, 3)):
                        lat = (points[i, j, 0] + points[k, l, 0]) * 0.5
                        lon = (points[i, j, 1] + points[k, l, 1]) * 0.5
                        if abs(i - k) + abs(j - l) < 2:
                            ele = (elevations[i, j] + elevations[k, l]) * 0.5
                            assert abs(mgr.query_elevation(lat, lon) - ele) <= 0.1
                        else:
                            emax = max(elevations[i, j], elevations[k, l])
                            emin = min(elevations[i, j], elevations[k, l])
                            assert emin < mgr.query_elevation(lat, lon) < emax


def test_gpx_class_parse(tmp_path):
    """Test the GPX class for parsing GPX files."""
    input_gpx = tmp_path / "input.gpx"
    output_gpx = tmp_path / "output.gpx"

    create_gpx_file(str(input_gpx), with_elevation=True)
    gpx = GPX(input_gpx)
    points = list(gpx.points())
    assert len(points) == 3

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
