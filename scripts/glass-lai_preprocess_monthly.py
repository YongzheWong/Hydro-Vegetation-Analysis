#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GLASS LAI V6 monthly preprocessing

Input:
    /Volumes/PortableSSD/data/raw/GLASS_LAI/YYYY/*.hdf

Output:
    /Volumes/PortableSSD/data/processed/GLASS_LAI/lai_YYYY_MM.tif

Processing:
    1. Read GLASS LAI HDF
    2. Remove invalid values (255)
    3. Remove values outside valid range [0, 100]
    4. Apply scale factor 0.1
    5. Crop to China bounding box
    6. Reproject WGS84 -> Albers Equal Area
    7. Resample to 1 km using bilinear interpolation
    8. Clip exactly to China boundary
    9. Save GeoTIFF
    10. Explicitly release memory
    11. Ignore hidden/system files such as .DS_Store
"""

import gc
import re
import sys
from pathlib import Path

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.io import MemoryFile
from rasterio.mask import mask
from rasterio.transform import from_origin
from rasterio.warp import (
    calculate_default_transform,
    reproject,
    Resampling,
)
from pyhdf.SD import SD, SDC
import yaml


# ============================================================
# Configuration
# ============================================================

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.yaml"

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)


# ------------------------------------------------------------
# GLASS LAI paths
# ------------------------------------------------------------

glass_config = CONFIG["glass_lai"]

RAW_DIR = Path(
    glass_config["raw_data"]
)

OUTPUT_DIR = Path(
    glass_config["processed_data"]
)

# GLASS LAI product specification
VALID_MIN = float(
    glass_config["valid_min"]
)

VALID_MAX = float(
    glass_config["valid_max"]
)

FILL_VALUE = float(
    glass_config["fill_value"]
)

SCALE_FACTOR = float(
    glass_config["scale_factor"]
)

TARGET_RESOLUTION = int(
    glass_config["target_resolution"]
)

BOUNDARY_PATH = Path(
    CONFIG["paths"]["boundary"]
)

NODATA = float(
    CONFIG["preprocess"]["nodata"]
)

TARGET_CRS = CONFIG["projection"]["crs"]


# ============================================================
# Utility functions
# ============================================================

def log(message):
    """Print a simple processing message."""
    print(f"[GLASS LAI] {message}", flush=True)


def release_memory(*objects):
    """
    Explicitly release references and trigger garbage collection.
    """
    for obj in objects:
        del obj

    gc.collect()


def find_hdf_files(year):
    """
    Find GLASS LAI HDF files for a given year.

    Hidden/system files are explicitly ignored.
    """

    year_dir = RAW_DIR / str(year)

    if not year_dir.exists():
        raise FileNotFoundError(
            f"Input directory does not exist: {year_dir}"
        )

    files = []

    for path in sorted(year_dir.iterdir()):

        # Ignore hidden files such as .DS_Store
        if path.name.startswith("."):
            continue

        # Only HDF files
        if not path.is_file():
            continue

        if path.suffix.lower() != ".hdf":
            continue

        # Expected filename:
        # GLASS01H01.V61.A200002.2025248.hdf
        match = re.search(r"A(\d{4})(\d{2})\.", path.name)

        if match is None:
            log(f"Skipping file with unexpected name: {path.name}")
            continue

        files.append(path)

    return files


def extract_date_from_filename(path):
    """
    Extract YYYY and MM from:

    GLASS01H01.V61.A200002.2025248.hdf
                         ^^^^^^
                         YYYYMM
    """

    match = re.search(r"A(\d{4})(\d{2})\.", path.name)

    if match is None:
        raise ValueError(
            f"Cannot extract date from filename: {path.name}"
        )

    year = int(match.group(1))
    month = int(match.group(2))

    return year, month


# ============================================================
# HDF reading
# ============================================================

def read_glass_lai(hdf_path):
    """
    Read LAI SDS from GLASS HDF.

    Returns
    -------
    data : np.ndarray
        Raw LAI array.
    """

    log(f"Reading: {hdf_path.name}")

    hdf = None

    try:
        hdf = SD(str(hdf_path), SDC.READ)

        datasets = hdf.datasets()

        # Find LAI dataset
        lai_name = None

        for name in datasets.keys():
            if "LAI" in name.upper():
                lai_name = name
                break

        if lai_name is None:
            raise RuntimeError(
                f"No LAI dataset found in {hdf_path.name}.\n"
                f"Available datasets: {list(datasets.keys())}"
            )

        log(f"  SDS: {lai_name}")

        sds = hdf.select(lai_name)

        data = sds[:]

        # Convert immediately to float32.
        # This is necessary because we need NaN.
        data = np.asarray(data, dtype=np.float32)

        # Print useful information for first debugging
        log(f"  Shape: {data.shape}")
        log(f"  Raw dtype: {data.dtype}")

        return data

    finally:

        # Explicitly close HDF
        if hdf is not None:
            try:
                hdf.end()
            except Exception:
                pass

        gc.collect()


# ============================================================
# GLASS LAI quality control
# ============================================================

def quality_control(data):
    """
    Replace invalid values with NaN and apply scale factor.

    GLASS LAI:
        valid raw value: 0-100
        fill value: 255
        scale factor: 0.1

    Therefore:
        raw 0   -> LAI 0.0
        raw 10  -> LAI 1.0
        raw 50  -> LAI 5.0
        raw 100 -> LAI 10.0
        raw 255 -> NaN
    """

    log("Applying quality control...")

    # Invalid values
    invalid_mask = (
        (data == FILL_VALUE)
        | (data < VALID_MIN)
        | (data > VALID_MAX)
        | ~np.isfinite(data)
    )

    invalid_count = np.count_nonzero(invalid_mask)
    total_count = data.size

    invalid_percent = (
        invalid_count / total_count * 100
        if total_count > 0
        else 0
    )

    log(
        f"  Invalid pixels: "
        f"{invalid_count:,} "
        f"({invalid_percent:.2f}%)"
    )

    # Replace invalid values with NaN
    data[invalid_mask] = np.nan

    # Apply scale factor
    data *= SCALE_FACTOR

    valid = np.isfinite(data)

    if np.any(valid):
        log(
            f"  Valid LAI range after scaling: "
            f"{np.nanmin(data):.3f} - {np.nanmax(data):.3f}"
        )
    else:
        raise RuntimeError("No valid LAI pixels remain.")

    del invalid_mask
    gc.collect()

    return data


# ============================================================
# Global grid definition
# ============================================================

def get_global_transform(data):
    """
    Construct the geographic transform for the global 0.1° GLASS grid.

    Expected global grid:
        longitude: -180 to 180
        latitude:  90 to -90

    Pixel size:
        0.1° x 0.1°
    """

    height, width = data.shape

    pixel_size = 0.1

    # GLASS 0.1 degree global grid
    west = -180.0
    north = 90.0

    transform = from_origin(
        west,
        north,
        pixel_size,
        pixel_size,
    )

    return transform


# ============================================================
# Crop global data to China bounding box
# ============================================================

def crop_to_boundary_bbox(data, transform, boundary):
    """
    Crop the global raster to the bounding box of China.

    This is done BEFORE reprojection to greatly reduce memory usage.
    """

    log("Cropping global raster to China bounding box...")

    # Make sure boundary is WGS84
    boundary_wgs84 = boundary.to_crs("EPSG:4326")

    minx, miny, maxx, maxy = boundary_wgs84.total_bounds

    # Convert geographic coordinates to pixel indices
    col_start = int(
        np.floor((minx - transform.c) / transform.a)
    )

    col_end = int(
        np.ceil((maxx - transform.c) / transform.a)
    )

    row_start = int(
        np.floor((transform.f - maxy) / abs(transform.e))
    )

    row_end = int(
        np.ceil((transform.f - miny) / abs(transform.e))
    )

    height, width = data.shape

    # Keep indices inside raster
    col_start = max(0, min(width, col_start))
    col_end = max(0, min(width, col_end))

    row_start = max(0, min(height, row_start))
    row_end = max(0, min(height, row_end))

    if col_start >= col_end or row_start >= row_end:
        raise RuntimeError(
            "China boundary does not overlap the GLASS global raster."
        )

    cropped = data[
        row_start:row_end,
        col_start:col_end
    ]

    new_transform = rasterio.windows.transform(
        rasterio.windows.Window(
            col_start,
            row_start,
            col_end - col_start,
            row_end - row_start,
        ),
        transform,
    )

    log(
        f"  Cropped shape: "
        f"{cropped.shape[0]} × {cropped.shape[1]}"
    )

    return cropped, new_transform


# ============================================================
# Reprojection + resampling
# ============================================================

def reproject_to_albers(
    data,
    src_transform,
    target_crs,
    resolution,
):
    """
    Reproject WGS84 LAI data to Albers Equal Area at 1 km.

    Bilinear interpolation is used because LAI is a continuous variable.
    """

    log("Reprojecting to Albers Equal Area...")
    log(f"  Target resolution: {resolution} m")
    log(f"  Resampling: bilinear")

    src_height, src_width = data.shape

    # Determine source bounds
    left = src_transform.c
    top = src_transform.f

    right = (
        left
        + src_width * src_transform.a
    )

    bottom = (
        top
        + src_height * src_transform.e
    )

    dst_transform, dst_width, dst_height = (
        calculate_default_transform(
            "EPSG:4326",
            target_crs,
            src_width,
            src_height,
            left=left,
            bottom=bottom,
            right=right,
            top=top,
            resolution=resolution,
        )
    )

    log(
        f"  Output shape: "
        f"{dst_height} × {dst_width}"
    )

    # Float32 is sufficient and saves a lot of memory
    destination = np.full(
        (dst_height, dst_width),
        np.nan,
        dtype=np.float32,
    )

    reproject(
        source=data,
        destination=destination,
        src_transform=src_transform,
        src_crs="EPSG:4326",
        dst_transform=dst_transform,
        dst_crs=target_crs,
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
        num_threads=1,
    )

    return destination, dst_transform


# ============================================================
# Exact China clipping
# ============================================================

def clip_to_china(
    data,
    transform,
    boundary,
    target_crs,
):
    """
    Precisely mask the reprojected raster using the China boundary.
    """

    log("Applying exact China boundary mask...")

    boundary_projected = boundary.to_crs(target_crs)

    # Create temporary in-memory raster
    profile = {
        "driver": "GTiff",
        "height": data.shape[0],
        "width": data.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": target_crs,
        "transform": transform,
        "nodata": NODATA,
    }

    with MemoryFile() as memfile:

        with memfile.open(**profile) as dataset:

            # Convert NaN to explicit nodata before writing
            write_data = np.where(
                np.isfinite(data),
                data,
                NODATA,
            ).astype(np.float32)

            dataset.write(write_data, 1)

            del write_data
            gc.collect()

            geometries = [
                geom.__geo_interface__
                for geom in boundary_projected.geometry
                if geom is not None and not geom.is_empty
            ]

            clipped, clipped_transform = mask(
                dataset,
                geometries,
                crop=True,
                nodata=NODATA,
                filled=True,
            )

    # Convert nodata back to NaN internally
    clipped = clipped[0].astype(np.float32)

    clipped[clipped == NODATA] = np.nan

    log(
        f"  Final shape: "
        f"{clipped.shape[0]} × {clipped.shape[1]}"
    )

    return clipped, clipped_transform


# ============================================================
# Save GeoTIFF
# ============================================================

def save_geotiff(
    output_path,
    data,
    transform,
    crs,
):
    """
    Save processed LAI as compressed GeoTIFF.
    """

    log(f"Saving: {output_path.name}")

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    height, width = data.shape

    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": NODATA,
        "compress": "deflate",
        "predictor": 3,
        "zlevel": 4,
        "tiled": True,
        "BIGTIFF": "IF_SAFER",
    }

    with rasterio.open(
        output_path,
        "w",
        **profile,
    ) as dst:

        write_data = np.where(
            np.isfinite(data),
            data,
            NODATA,
        ).astype(np.float32)

        dst.write(write_data, 1)

        dst.set_band_description(
            1,
            "GLASS LAI"
        )

        dst.update_tags(
            1,
            long_name="Leaf Area Index",
            units="m2 m-2",
            source="GLASS LAI V6",
            spatial_resolution="1 km",
            temporal_resolution="monthly",
            scale_factor="0.1 applied",
            original_valid_range="0-100",
            original_fill_value="255",
        )

        del write_data
        gc.collect()


# ============================================================
# Process one file
# ============================================================

def process_one_file(
    hdf_path,
    boundary,
):
    """
    Process one monthly GLASS LAI file.
    """

    year, month = extract_date_from_filename(hdf_path)

    output_name = f"lai_{year:04d}_{month:02d}.tif"
    output_path = OUTPUT_DIR / output_name

    # --------------------------------------------------------
    # Skip existing output
    # --------------------------------------------------------

    if output_path.exists():
        log(
            f"Output already exists, skipping: "
            f"{output_path.name}"
        )
        return

    log("=" * 70)
    log(f"Processing {year}-{month:02d}")
    log(f"Input: {hdf_path}")

    data = None
    cropped = None
    reprojected = None
    clipped = None

    try:

        # ----------------------------------------------------
        # 1. Read HDF
        # ----------------------------------------------------

        data = read_glass_lai(hdf_path)

        # ----------------------------------------------------
        # 2. Quality control
        # ----------------------------------------------------

        data = quality_control(data)

        # ----------------------------------------------------
        # 3. Global transform
        # ----------------------------------------------------

        transform = get_global_transform(data)

        # ----------------------------------------------------
        # 4. Crop global data before reprojection
        # ----------------------------------------------------

        cropped, cropped_transform = (
            crop_to_boundary_bbox(
                data,
                transform,
                boundary,
            )
        )

        # Original global data no longer needed
        del data
        data = None

        gc.collect()

        # ----------------------------------------------------
        # 5. Reproject + 1 km resampling
        # ----------------------------------------------------

        reprojected, reprojected_transform = (
            reproject_to_albers(
                cropped,
                cropped_transform,
                TARGET_CRS,
                TARGET_RESOLUTION,
            )
        )

        del cropped
        cropped = None

        del cropped_transform
        gc.collect()

        # ----------------------------------------------------
        # 6. Exact China clipping
        # ----------------------------------------------------

        clipped, clipped_transform = (
            clip_to_china(
                reprojected,
                reprojected_transform,
                boundary,
                TARGET_CRS,
            )
        )

        del reprojected
        reprojected = None

        del reprojected_transform
        gc.collect()

        # ----------------------------------------------------
        # 7. Save
        # ----------------------------------------------------

        save_geotiff(
            output_path,
            clipped,
            clipped_transform,
            TARGET_CRS,
        )

        log(f"Finished: {output_path}")
        log("")

    except Exception as exc:

        log(
            f"ERROR processing {hdf_path.name}: "
            f"{type(exc).__name__}: {exc}"
        )

        raise

    finally:

        # ----------------------------------------------------
        # Aggressive memory release
        # ----------------------------------------------------

        data = None
        cropped = None
        reprojected = None
        clipped = None

        gc.collect()


# ============================================================
# Main
# ============================================================

def main():

    start_year = int(CONFIG["project"]["start_year"])
    end_year = int(CONFIG["project"]["end_year"])

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    log("Loading China boundary...")

    boundary = gpd.read_file(
        BOUNDARY_PATH
    )

    if boundary.empty:
        raise RuntimeError(
            "China boundary shapefile is empty."
        )

    log(
        f"Boundary CRS: {boundary.crs}"
    )

    # --------------------------------------------------------
    # Process year by year
    # --------------------------------------------------------

    total_files = 0

    for year in range(
        start_year,
        end_year + 1,
    ):

        log("=" * 70)
        log(f"Searching GLASS LAI files for {year}")

        files = find_hdf_files(year)

        if not files:
            log(
                f"No HDF files found for {year}"
            )
            continue

        log(
            f"Found {len(files)} HDF files."
        )

        total_files += len(files)

        for hdf_path in files:

            process_one_file(
                hdf_path,
                boundary,
            )

            # Force garbage collection after
            # every monthly file
            gc.collect()

    log("=" * 70)
    log(
        f"Processing completed. "
        f"Files found: {total_files}"
    )


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:
        print("\nProcessing interrupted by user.")
        sys.exit(1)

    except Exception as exc:
        print(
            f"\nProcessing failed: "
            f"{type(exc).__name__}: {exc}"
        )
        sys.exit(1)