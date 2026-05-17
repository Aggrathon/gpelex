"""
Pytest tests for gpelex.py
Run with: `uvx --with-requirements gpelex.py pytest test_gpelex.py`
"""

import os

import gpxpy
import gpxpy.gpx
import numpy as np
import srtm

from gpelex import ElevationDataManager, add_elevation_to_gpx


def create_test_gpx_file(gpx_path: str, with_elevation: bool = False) -> None:
    """Create a test GPX file with or without elevation data.

    Args:
        gpx_path: Path to save the GPX file.
        with_elevation: If True, include dummy elevation data in the GPX file.
    """
    gpx = gpxpy.gpx.GPX()

    track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(track)

    segment = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(segment)

    points = [
        (48.8584, 2.2945),  # Paris, France
        (51.5074, -0.1278),  # London, UK
        (40.7128, -74.0060),  # New York, USA
    ]

    for lat, lon in points:
        point = gpxpy.gpx.GPXTrackPoint(latitude=lat, longitude=lon)
        if with_elevation:
            point.elevation = 100.0  # Dummy elevation
        segment.points.append(point)

    with open(gpx_path, "w") as f:
        f.write(gpx.to_xml())


def test_add_elevation_to_gpx_without_elevation(tmp_path):
    """Test adding elevation data to a GPX file without existing elevation data."""
    input_gpx = tmp_path / "input.gpx"
    output_gpx = tmp_path / "output.gpx"

    create_test_gpx_file(str(input_gpx), with_elevation=False)
    add_elevation_to_gpx(str(input_gpx), None, str(output_gpx), force_overwrite=False)

    assert output_gpx.exists()

    with open(output_gpx, "r") as f:
        gpx = gpxpy.parse(f)

    for point in gpx.walk(True):
        assert isinstance(point.elevation, (int, float, np.integer))


def test_add_elevation_to_gpx_with_elevation_no_force(tmp_path):
    """Test that existing elevation data is not overwritten without --force."""
    input_gpx = tmp_path / "input.gpx"
    output_gpx = tmp_path / "output.gpx"

    create_test_gpx_file(str(input_gpx), with_elevation=True)
    add_elevation_to_gpx(str(input_gpx), None, str(output_gpx), force_overwrite=False)

    assert not output_gpx.exists()


def test_add_elevation_to_gpx_with_elevation_force(tmp_path):
    """Test that existing elevation data is overwritten with --force."""
    input_gpx = tmp_path / "input.gpx"
    output_gpx = tmp_path / "output.gpx"

    create_test_gpx_file(str(input_gpx), with_elevation=True)
    add_elevation_to_gpx(str(input_gpx), None, str(output_gpx), force_overwrite=True)

    assert output_gpx.exists()

    with open(output_gpx, "r") as f:
        gpx = gpxpy.parse(f)

    for point in gpx.walk(True):
        assert isinstance(point.elevation, (int, float, np.integer))


def test_query_elevation_from_srtm_api():
    """Test querying elevation data from the srtm.py library."""
    with ElevationDataManager(None) as elevation_manager:
        elevation = elevation_manager.query_elevation(48.8584, 2.2945)
    assert isinstance(elevation, (int, float, np.integer))


def test_query_elevation_from_dem_file(tmp_path):
    """Test querying elevation data from a DEM file."""
    elevation_data = srtm.get_data()
    dem_file = elevation_data.get_file(48.8584, 2.2945)

    if dem_file is None:
        raise ValueError("Could not retrieve DEM file for the given coordinates")

    dem_file_path = os.path.join(str(tmp_path), dem_file.file_name)
    with open(dem_file_path, "wb") as f:
        f.write(dem_file.data)

    with ElevationDataManager([dem_file_path]) as elevation_manager:
        elevation = elevation_manager.query_elevation(48.8584, 2.2945)
    assert isinstance(elevation, (int, float, np.integer))
