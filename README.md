# GPeleX: Add elevation data to GPX files

> This project has been superseded by [GPhiX](https://github.com/Aggrathon/gphix), which also includes fixing missing elevation functionality.  

Add elevation data to GPX trackpoints using local DEM (Digital Elevation Maps) files or [online SRTM](https://github.com/tkrajina/srtm.py) (Shuttle Radar Topography Mission) elevation data.

> [Run it in your browser here!](https://aggrathon.github.io/gpelex)

Useful for GPX tracks and routes that are missing elevation, e.g., as exported by some sport watches.
The added elevation (approximately) follows the ground level.

SRTM data is captured from space and, thus, relatively coarse and affected by buildings and vegetation.
National databases can, depending on location, provide higher resolution and more accurate DEM data but require manual downloads.
Higher quality data covering multiple countries is available from, for example, [https://viewfinderpanoramas.org/dem3.html](https://viewfinderpanoramas.org/dem3.html).

## Usage

### Python CLI

Easiest way to run is to download the [gpelex.py](gpelex.py) file and use [uv](https://github.com/astral-sh/uv):

```bash
uv run gpelex.py input.gpx --dem elevation.tif --output output.gpx
```
Or without manually downloading:
```bash
uv run https://raw.githubusercontent.com/Aggrathon/gpelex/main/gpelex.py --help
```

Alternatively, create a Python (>=3.11) environment with [`rasterio`](https://rasterio.readthedocs.io) and [`scipy`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.interpn.html) for local DEM files or [`srtm.py`](https://github.com/tkrajina/srtm.py) for online SRTM data.

#### Arguments:

| Flag | Description |
|---|---|
| `INPUT` | Path to the input GPX file |
| `-o, --output FILE` | Output GPX path (defaults to `<input>_with_elevation.gpx`) |
| `-d, --dem FILE ...` | One or more DEM files (`.tif`, `.zip`, `.tar.gz`, etc.) |
| `-f, --force` | Overwrite existing elevation data |
| `-v, --verbose` | Verbose output (use `-vv` for per-point details) |

If no `--dem` files are provided, the tool fetches elevation from the [SRTM API](https://github.com/tkrajina/srtm.py) (30 m resolution).

### Browser

Open [https://aggrathon.github.io/gpelex](https://aggrathon.github.io/gpelex) in a browser. Select a GPX file and one or more elevation map files (`.tif`, `.zip`, `.tar.gz`), then click **Add elevation** (after [Pyodide](https://pyodide.org) has loaded all dependencies). All processing runs locally in your browser — nothing is uploaded.

Alternatively, download [gpelex.py](gpelex.py) and [index.html](index.html) and serve it yourself (requires at least a basic server such as `uvx python -m http.server` since bare html files are not allowed to read local files).

## Testing

```bash
uvx --with-requirements gpelex.py pytest test_gpelex.py
```

## Project Structure

| File | Description |
|---|---|
| `gpelex.py` | Main script — CLI entry point and library |
| `index.html` | Browser-based UI running via [Pyodide](https://pyodide.org) |
| `test_gpelex.py` | [Pytest](https://pytest.org) test suite |
