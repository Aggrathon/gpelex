# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "rasterio",
#   "srtm.py",
#   "numpy",
#   "scipy"
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
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from typing import Iterator

import numpy as np
import rasterio
from rasterio.transform import rowcol
from rasterio.windows import Window
from scipy.interpolate import interpn


class GPXPoint:
    """Wrapper for a GPX point (trkpt, wpt, or rtept)."""

    def __init__(self, element: ET.Element, namespace: dict[str, str]):
        self._element = element
        self._namespace = namespace

    @property
    def latitude(self) -> float:
        return float(self._element.get("lat", ""))

    @property
    def longitude(self) -> float:
        return float(self._element.get("lon", ""))

    @property
    def elevation(self) -> float | None:
        ele = self._element.find("gpx:ele", self._namespace)
        return float(ele.text) if ele is not None and ele.text is not None else None

    @elevation.setter
    def elevation(self, value: float):
        ele = self._element.find("gpx:ele", self._namespace)
        if ele is None:
            ele = ET.SubElement(self._element, "ele")
        ele.text = str(value)


class GPX:
    """Lightweight GPX parser."""

    def __init__(self, file_source: str | os.PathLike):
        self.tree = ET.parse(file_source)
        self.root = self.tree.getroot()

        self.ns_uri = self.root.attrib.get("xmlns", "http://www.topografix.com/GPX/1/1")
        self.namespaces: dict[str, str] = {"gpx": self.ns_uri}

    def points(self) -> Iterator[GPXPoint]:
        """Generator yielding all points (trkpt, wpt, rtept) in the GPX file."""
        for tag in ["trkpt", "wpt", "rtept"]:
            for node in self.root.findall(f".//gpx:{tag}", self.namespaces):
                yield GPXPoint(node, self.namespaces)

    def write(self, output_path: str | os.PathLike) -> None:
        """Write the GPX to a file."""
        if self.ns_uri:
            ET.register_namespace("", self.ns_uri)
        self.tree.write(output_path, encoding="utf-8", xml_declaration=True)


class ElevationDataManager:
    """Context manager for DEM files to simplify elevation queries.

    Args:
        dem_paths: List of paths to DEM files. If None, the SRTM API will be used.
                  Automatically scans zip and tar files for DEM datasets inside.
                  Supports both regular files and archive:// URLs (e.g., zip:///path/to/file.zip!dataset.tif).
    """

    def __init__(self, dem_paths: list[str] | None):
        self.dem_paths = dem_paths
        self.dem_files = []
        self.elevation_data = None

    def _expand_archive_paths(self, paths: list[str]) -> list[str]:
        """Expand archive file paths to individual TIF paths inside."""
        expanded = []

        for path in paths:
            if path.startswith(("zip://", "tar://", "hdf5://")):
                expanded.append(path)
                continue

            geospatial_ext = (".tif", ".tiff", ".img", ".jp2", ".ras", ".dat")
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    expanded.extend(
                        f"zip://{path}!{n}"
                        for n in zf.namelist()
                        if n.lower().endswith(geospatial_ext)
                    )
                    continue
            except (zipfile.BadZipFile, OSError):
                pass

            try:
                with tarfile.open(path, "r:*") as tf:
                    expanded.extend(
                        f"tar://{path}!{n}"
                        for n in tf.getnames()
                        if n.lower().endswith(geospatial_ext)
                    )
                    continue
            except (tarfile.TarError, OSError):
                pass

            expanded.append(path)
        return expanded

    def __enter__(self):
        if self.dem_paths is not None:
            expanded_paths = self._expand_archive_paths(self.dem_paths)
            for dem_path in expanded_paths:
                dem_file = rasterio.open(dem_path)
                self.dem_files.append(dem_file)
        else:
            import srtm

            self.elevation_data = srtm.get_data()
        return self

    def query_elevation(self, latitude: float, longitude: float) -> float | None:
        """Query elevation for a point using DEM files or the SRTM API.

        When using DEM files, interpolates elevation by finding the three closest
        DEM pixels using rowcol and checking +/-1 neighbors, then performing
        triangulation-based interpolation.

        Args:
            latitude: Latitude of the point.
            longitude: Longitude of the point.

        Returns:
            Elevation in meters, or None if unavailable.
        """
        if self.dem_paths is not None:
            for dem_file in self.dem_files:
                elevation = self._dem_interpolate(dem_file, latitude, longitude)
                if elevation is not None:
                    return float(elevation)
        elif self.elevation_data is not None:
            elevation = self.elevation_data.get_elevation(latitude, longitude)
            if elevation is not None:
                return float(elevation)
        return None

    def _dem_interpolate(
        self, dem_file, latitude: float, longitude: float
    ) -> float | None:
        """Interpolate elevation using the 3 closest DEM pixels."""
        height, width = dem_file.shape
        row, col = rowcol(dem_file.transform, longitude, latitude)
        if 0 <= row < height and 0 <= col < width:
            x, y = rowcol(dem_file.transform, longitude, latitude, op=lambda v: v)
            rows = (max(row - 1, 0), min(row + 2, height))
            cols = (max(col - 1, 0), min(col + 2, width))
            dem = dem_file.read(1, window=Window.from_slices(rows, cols))
            if dem.size == 1:
                return float(dem[0, 0])
            elif dem.size:
                return interpn(
                    (np.arange(*rows), np.arange(*cols)),
                    dem[..., None],
                    [[x - 0.5, y - 0.5]],
                    method="slinear",
                    bounds_error=False,
                    fill_value=None,
                )[0, 0]

    def __exit__(self, exc_type, exc_val, exc_tb):
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

    gpx = GPX(input_gpx_path)
    elevation_was_added = False
    with ElevationDataManager(dem_paths if dem_paths else None) as elevation:
        for point in gpx.points():
            if force_overwrite or point.elevation is None:
                value = elevation.query_elevation(point.latitude, point.longitude)
                if value is not None:
                    point.elevation = value
                    elevation_was_added = True

    if elevation_was_added:
        gpx.write(output_gpx_path)
        return output_gpx_path
    return input_gpx_path


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
    if output == args.INPUT:
        print(f"No changes made to: {output}")
    else:
        print(f"GPX file saved successfully to: {output}")


if __name__ == "__main__":
    main()
