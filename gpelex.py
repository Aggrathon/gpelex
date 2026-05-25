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
import logging
import os
import tarfile
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from typing import Iterator

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import rowcol
from rasterio.warp import transform
from rasterio.windows import Window
from scipy.interpolate import interpn


def open_dem_files(paths: list[str], extract: bool = False) -> list:
    """Open DEM files, expanding archives and extracting archive items if needed."""
    dem_files = []
    geospatial_ext = (".tif", ".tiff", ".img", ".jp2", ".ras", ".dat", ".hgt")

    for path in paths:
        if path.endswith(geospatial_ext):
            dem_file = rasterio.open(path)
            dem_files.append(dem_file)
            continue

        try:
            with zipfile.ZipFile(path) as archive:
                items = [
                    item for item in archive.namelist() if item.endswith(geospatial_ext)
                ]
                if extract and items:
                    with tempfile.TemporaryDirectory() as tmpdir:
                        for item in items:
                            dem_file = rasterio.open(archive.extract(item, tmpdir))
                            dem_files.append(dem_file)
                else:
                    for item in items:
                        dem_file = rasterio.open(f"zip+file://{path}!{item}")
                        dem_files.append(dem_file)
                continue
        except (zipfile.BadZipFile, OSError):
            pass

        try:
            with tarfile.open(path) as archive:
                items = [
                    item for item in archive.getnames() if item.endswith(geospatial_ext)
                ]
                if extract and items:
                    with tempfile.TemporaryDirectory() as tmpdir:
                        for item in items:
                            archive.extract(item, tmpdir, filter="data")
                            dem_file = rasterio.open(os.path.join(tmpdir, item))
                            dem_files.append(dem_file)
                elif not extract:
                    for item in items:
                        dem_file = rasterio.open(f"tar+file://{path}!{item}")
                        dem_files.append(dem_file)
                continue
        except (tarfile.TarError, OSError):
            pass

        dem_file = rasterio.open(path)
        dem_files.append(dem_file)

    return dem_files


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
        ele.text = f"{value:.3g}"


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
                Supports both regular files and zip/tar archives with multiple files.
                Also supports archive:// URLs (e.g., zip:///path/to/file.zip!dataset.tif).
        extract: If True, force extract archive contents before processing (on platforms where archive:// URLs are not working).
        verbose: If True, print information about the data source.
    """

    def __init__(
        self, dem_paths: list[str] | None, extract: bool = False, verbose: int = 0
    ):
        self.dem_paths = dem_paths
        self.dem_files = []
        self.elevation_data = None
        self.extract = extract
        self.verbose = verbose
        self.crs = CRS.from_epsg(4326)

    def __enter__(self):
        if self.dem_paths is not None:
            self.dem_files = open_dem_files(self.dem_paths, self.extract)
            if self.verbose:
                if self.dem_files:
                    logging.info(f"Using DEM files ({len(self.dem_files)})")
                    if self.verbose > 1:
                        logging.info("Using DEM files:")
                        for dem_file in self.dem_files:
                            logging.info(
                                f" - {dem_file.name}: {dem_file.lnglat()} {dem_file.crs}"
                            )
                else:
                    logging.info("No DEM files supplied")
        else:
            import srtm

            self.elevation_data = srtm.get_data()
            if self.verbose:
                logging.info("Using online SRTM (30m) data")
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
        lon, lat = transform(self.crs, dem_file.crs, [longitude], [latitude])
        row, col = rowcol(dem_file.transform, lon[0], lat[0])
        if 0 <= row < height and 0 <= col < width:
            x, y = rowcol(dem_file.transform, lon[0], lat[0], op=lambda v: v)
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
    input_path: str,
    dem_paths: list[str] | None,
    output_path: str | None = None,
    overwrite: bool = False,
    extract: bool = False,
    verbose: int = 0,
) -> str:
    """Add elevation data to a GPX file using DEM files or the SRTM API.

    Args:
        input_path: Path to the input GPX file.
        dem_paths: List of paths to DEM files. If None, the SRTM API will be used.
        output_path: Path to the output GPX file. If None, a default name is generated.
        overwrite: If True, overwrite existing elevation data.
        extract: If True, (force) extract archive contents before processing.
        verbose: Verbose level (1: summary info, 2: per-point details).

    Returns:
        The path to the output GPX file.
    """

    if output_path is None:
        output_path = f"{os.path.splitext(input_path)[0]}_with_elevation.gpx"

    gpx = GPX(input_path)
    point_updates = 0

    if verbose >= 1:
        logging.info(f"Loading GPX file: {input_path}")

    with ElevationDataManager(
        dem_paths if dem_paths else None, extract, verbose
    ) as elevation:
        point_count = 0
        for point in gpx.points():
            point_count += 1
            if overwrite or point.elevation is None:
                if verbose >= 2:
                    logging.info(
                        f"Querying elevation at lat={point.latitude}, lon={point.longitude}, ele={point.elevation}"
                    )
                value = elevation.query_elevation(point.latitude, point.longitude)
                if value is not None:
                    point.elevation = value
                    point_updates += 1
                    if verbose >= 2:
                        logging.info(f"Elevation set to: {value}m")

        if verbose >= 1:
            logging.info(f"Processed {point_count} points, {point_updates} updated")

    if point_updates:
        gpx.write(output_path)
        if verbose >= 1:
            logging.info(f"GPX file saved to: {output_path}")
        return output_path

    if verbose >= 1:
        logging.info(f"No changes made to: {input_path}")
    return input_path


def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

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
        help="Path to one or more DEM files (e.g., .tif files or archives containing .tif files). If not provided, elevation data will be queried using the SRTM library.",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force overwrite existing elevation data in the GPX file.",
    )
    parser.add_argument(
        "--extract-archives",
        "-e",
        action="store_true",
        help="Extract archive contents before processing (only needed for special file systems)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Enable verbose output (use -vv for more details per point)",
    )

    args = parser.parse_args()

    if args.verbose > 0:
        logging.getLogger().setLevel(logging.INFO)
        logging.info(
            "Verbose mode enabled"
            if args.verbose == 1
            else "Verbose mode (per-point) enabled"
        )

    output = add_elevation_to_gpx(
        args.INPUT,
        args.dem,
        args.output,
        args.force,
        args.extract_archives,
        verbose=args.verbose,
    )
    print(output)


if __name__ == "__main__":
    main()
