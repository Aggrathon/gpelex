# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "gpxpy",
#   "rasterio",
#   "srtm.py",
# ]
# ///
"""
Script to add elevation data to a GPX file using one or more DEM files or the SRTM API.

Usage:
    uv run --script gpelex.py INPUT [--output OUTPUT] [--dem DEM_FILE ...] [--force]

Arguments:
    INPUT: Path to the input GPX file.
    --output OUTPUT: Path to the output GPX file with elevation data added.
    --dem DEM_FILE ...: Path to one or more DEM files (e.g., .tif files).
    --force: Force overwrite existing elevation data in the GPX file.
"""

import argparse
import os

import gpxpy
import rasterio
from rasterio.transform import rowcol


class ElevationDataManager:
    """Context manager for DEM files to simplify elevation queries.

    Args:
        dem_paths: List of paths to DEM files. If None, the SRTM API will be used.
    """

    def __init__(self, dem_file_paths: list[str] | None):
        self.dem_paths = dem_file_paths
        self.dem_files: list = []
        self.elevation_data = None

    def __enter__(self):
        if self.dem_paths is not None:
            for dem_path in self.dem_paths:
                dem_file = rasterio.open(dem_path)
                self.dem_files.append(dem_file)
        else:
            import srtm

            self.elevation_data = srtm.get_data()

        return self

    def query_elevation(self, latitude: float, longitude: float) -> float | None:
        """Query elevation for a point using DEM files or the SRTM API.

        Args:
            latitude: Latitude of the point.
            longitude: Longitude of the point.

        Returns:
            Elevation in meters, or None if unavailable.
        """
        if self.dem_paths is not None:
            for dem_file in self.dem_files:
                row, col = rowcol(dem_file.transform, longitude, latitude)

                if 0 <= row < dem_file.height and 0 <= col < dem_file.width:
                    elevation_value = dem_file.read(1)[row, col]
                    if elevation_value != dem_file.nodata:
                        return elevation_value
        else:
            if self.elevation_data is not None:
                return self.elevation_data.get_elevation(latitude, longitude)

        return None

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        for dem_file in self.dem_files:
            dem_file.close()
        self.dem_files = []


def add_elevation_to_gpx(
    input_gpx_path: str,
    dem_paths: list[str] | None,
    output_gpx_path: str | None = None,
    force_overwrite: bool = False,
) -> str:
    """Add elevation data to a GPX file using DEM files or the SRTM API.

    Args:
        input_gpx_path: Path to the input GPX file.
        dem_paths: List of paths to DEM files. If None, the SRTM API will be used.
        output_gpx_path: Path to the output GPX file. If None, a default name is generated.
        force_overwrite: If True, overwrite existing elevation data.

    Returns:
        The path to the output GPX file.
    """

    if output_gpx_path is None:
        output_gpx_path = f"{os.path.splitext(input_gpx_path)[0]}_with_elevation.gpx"

    with open(input_gpx_path, "r") as gpx_file:
        gpx = gpxpy.parse(gpx_file)

    if not force_overwrite:
        no_ele = not gpx.has_elevations()
        assert no_ele, "GPX file already has elevation data. Use --force to overwrite."

    with ElevationDataManager(dem_paths if dem_paths else None) as elevation:
        for point in gpx.walk(True):
            if point.elevation is not None and not force_overwrite:
                continue

            value = elevation.query_elevation(point.latitude, point.longitude)
            if value is not None:
                point.elevation = value

    with open(output_gpx_path, "w") as gpx_file:
        gpx_file.write(gpx.to_xml())
    return output_gpx_path


def main():
    parser = argparse.ArgumentParser(
        description="Add elevation data to a GPX file using one or more DEM files or the elevation library."
    )
    parser.add_argument(
        "INPUT",
        type=str,
        help="Path to the input GPX file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Path to the output GPX file with elevation data added. If not provided, the output file will be named based on the input file.",
    )
    parser.add_argument(
        "-d",
        "--dem",
        metavar="DEM_FILE",
        type=str,
        nargs="*",
        default=None,
        help="Path to one or more DEM files (e.g., .tif files). If not provided, elevation data will be queried using the elevation library.",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force overwrite existing elevation data in the GPX file.",
    )

    args = parser.parse_args()
    output = add_elevation_to_gpx(args.INPUT, args.dem, args.output, args.force)
    print(f"GPX file saved successfully. Output saved to {output}")


if __name__ == "__main__":
    main()
