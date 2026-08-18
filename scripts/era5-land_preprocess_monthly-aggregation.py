"""
ERA5-Land Monthly Preprocessing
================================

Processing workflow

Instant variables:
    hourly data
        -> quality control
        -> outlier removal
        -> monthly mean
        -> unit conversion
        -> clip to China
        -> reproject
        -> spatial resampling
        -> save

Accumulated variables:
    hourly accumulated data
        -> extract daily final accumulation
        -> quality control
        -> outlier removal
        -> monthly sum
        -> unit conversion
        -> clip to China
        -> reproject
        -> spatial resampling
        -> save


ERA5-Land accumulation convention
----------------------------------

For accumulation variables (e, tp, sro):

    D 00 UTC
        = accumulation from the previous forecast period

    D 01 UTC
        = accumulation from D 00-01

    ...

    D+1 00 UTC
        = complete accumulation for day D

Therefore:

    Daily accumulation for day D
        = value at D+1 00 UTC

To process the last day of month M,
the first 00 UTC value of month M+1 is required.

Output
------

/Volumes/PortableSSD/data/processed/ERA5Land/
    ├── t2m/
    │   ├── t2m_2000_01.nc
    │   └── ...
    ├── swvl1/
    ├── e/
    ├── sro/
    └── tp/

Restart / Checkpoint
--------------------

The existence of a successfully written output NetCDF file
is treated as the checkpoint.

If:

    output_file.exists()
    and output_file.stat().st_size > 0

then the variable/month is considered completed and will be
skipped automatically when the script is restarted.

No separate checkpoint file is required.
"""

from __future__ import annotations

import gc
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rioxarray
import xarray as xr
import yaml

from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import calculate_default_transform, reproject


# =============================================================================
# Configuration
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config.yaml"


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG = load_config()

ERA5_CONFIG = CONFIG["era5land"]

RAW_DIR = Path(ERA5_CONFIG["raw_data"])
PROCESSED_DIR = Path(ERA5_CONFIG["processed_data"])

BOUNDARY_FILE = PROJECT_ROOT / CONFIG["paths"]["boundary"]

TARGET_RESOLUTION = CONFIG["preprocess"]["target_resolution"]

TARGET_CRS = CONFIG["projection"]["crs"]

NODATA = CONFIG["preprocess"]["nodata"]

START_YEAR = CONFIG["project"]["start_year"]
END_YEAR = CONFIG["project"]["end_year"]


# =============================================================================
# Variable configuration
# =============================================================================

VARIABLES = {

    # -------------------------------------------------------------------------
    # Instantaneous variables
    # -------------------------------------------------------------------------

    "t2m": {
        "raw_name": "t2m",
        "source_name": "2m_temperature",
        "type": "instant",
        "monthly_method": "mean",
        "spatial_method": "bilinear",
        "unit_method": "temperature",
    },

    "swvl1": {
        "raw_name": "swvl1",
        "source_name": "volumetric_soil_water_layer_1",
        "type": "instant",
        "monthly_method": "mean",
        "spatial_method": "bilinear",
        "unit_method": "none",
    },

    # -------------------------------------------------------------------------
    # Accumulated variables
    # -------------------------------------------------------------------------

    "e": {
        "raw_name": "e",
        "source_name": "total_evaporation",
        "type": "accumulated",
        "monthly_method": "sum",
        "spatial_method": "average",
        "unit_method": "evaporation",
    },

    "sro": {
        "raw_name": "sro",
        "source_name": "surface_runoff",
        "type": "accumulated",
        "monthly_method": "sum",
        "spatial_method": "average",
        "unit_method": "water_depth",
    },

    "tp": {
        "raw_name": "tp",
        "source_name": "total_precipitation",
        "type": "accumulated",
        "monthly_method": "sum",
        "spatial_method": "average",
        "unit_method": "water_depth",
    },
}


# =============================================================================
# Logging
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# =============================================================================
# File utilities
# =============================================================================

def is_valid_nc_file(path: Path) -> bool:
    """
    Ignore hidden/system files and accept only .nc files.
    """

    if path.name.startswith("."):
        return False

    if not path.is_file():
        return False

    if path.suffix.lower() != ".nc":
        return False

    return True


def get_month_file(year: int, month: int) -> Path:
    """
    Return the raw ERA5-Land monthly file.
    """

    return RAW_DIR / f"ERA5Land_{year:04d}_{month:02d}.nc"


def get_output_file(
    variable: str,
    year: int,
    month: int,
) -> Path:
    """
    Return the expected processed output file.
    """

    return (
        PROCESSED_DIR
        / variable
        / f"{variable}_{year:04d}_{month:02d}.nc"
    )


def is_monthly_output_complete(
    variable: str,
    year: int,
    month: int,
) -> bool:
    """
    Check whether a monthly output file exists.

    A non-empty NetCDF file is treated as a completed checkpoint.

    The file itself is the checkpoint, so no separate checkpoint
    metadata file is required.
    """

    output_file = get_output_file(
        variable,
        year,
        month,
    )

    return (
        output_file.exists()
        and output_file.stat().st_size > 0
    )


def next_month(
    year: int,
    month: int,
) -> tuple[int, int]:

    if month == 12:
        return year + 1, 1

    return year, month + 1


# =============================================================================
# Dataset opening
# =============================================================================

def open_dataset(path: Path) -> xr.Dataset:
    """
    Open ERA5-Land NetCDF lazily.

    Use chunks='auto' instead of manually specifying
    24 / 100 / 100 chunks.

    This avoids warnings caused by splitting the original
    NetCDF chunk structure.
    """

    if not path.exists():
        raise FileNotFoundError(path)

    ds = xr.open_dataset(
        path,
        chunks="auto",
    )

    return ds


# =============================================================================
# Variable extraction
# =============================================================================

def get_variable(
    ds: xr.Dataset,
    internal_name: str,
) -> xr.DataArray:
    """
    Get a variable using its internal ERA5-Land name.

    Expected raw ERA5-Land names:
        t2m
        swvl1
        e
        sro
        tp
    """

    if internal_name in ds.data_vars:

        da = ds[internal_name]

        da.name = internal_name

        return da

    raise KeyError(
        f"Variable '{internal_name}' not found. "
        f"Available variables: {list(ds.data_vars)}"
    )


# =============================================================================
# Quality control
# =============================================================================

def quality_control(
    da: xr.DataArray,
    variable: str,
) -> xr.DataArray:
    """
    Physical-range QC.

    Invalid values are replaced with NaN.
    """

    if variable == "t2m":

        da = da.where(
            (da >= 180.0)
            & (da <= 330.0)
        )

    elif variable == "swvl1":

        da = da.where(
            (da >= 0.0)
            & (da <= 1.0)
        )

    elif variable in {"tp", "sro"}:

        da = da.where(
            da >= 0.0
        )

    elif variable == "e":

        # ERA5 evaporation is normally negative.
        da = da.where(
            (da >= -1.0)
            & (da <= 1.0)
        )

    return da


# =============================================================================
# Outlier removal
# =============================================================================

def remove_outliers(
    da: xr.DataArray,
    sigma: float = 5.0,
) -> xr.DataArray:
    """
    Robust temporal outlier filtering.

    Uses:

        median ± sigma * 1.4826 * MAD

    Filtering is performed along valid_time.

    Pixels containing no valid data are kept as NaN.
    """

    if "valid_time" not in da.dims:
        return da

    valid_count = da.count(
        dim="valid_time"
    )

    median = da.median(
        dim="valid_time",
        skipna=True,
    )

    deviation = np.abs(
        da - median
    )

    mad = deviation.median(
        dim="valid_time",
        skipna=True,
    )

    threshold = (
        sigma
        * 1.4826
        * mad
    )

    mask = (
        np.abs(da - median)
        <= threshold
    )

    # If MAD == 0, do not filter.
    mask = (
        mask
        | (mad == 0)
    )

    # Pixels with no valid observations remain NaN.
    mask = (
        mask
        & (valid_count > 0)
    )

    return da.where(mask)


# =============================================================================
# Extract daily accumulation
# =============================================================================

def extract_daily_accumulation(
    current_ds: xr.Dataset,
    next_ds: xr.Dataset,
    variable: str,
    year: int,
    month: int,
) -> xr.DataArray:
    """
    Extract complete daily accumulation.

    For day D:

        daily[D] = accumulation at D+1 00 UTC
    """

    current = get_variable(
        current_ds,
        variable,
    )

    next_data = get_variable(
        next_ds,
        variable,
    )

    # -------------------------------------------------------------------------
    # Current month 00 UTC
    # -------------------------------------------------------------------------

    current_00 = current.sel(
        valid_time=current.valid_time.dt.hour == 0
    )

    # -------------------------------------------------------------------------
    # Next month 00 UTC
    #
    # The first timestamp of next month is needed for
    # the last day of current month.
    # -------------------------------------------------------------------------

    next_00 = next_data.sel(
        valid_time=next_data.valid_time.dt.hour == 0
    )

    combined = xr.concat(
        [current_00, next_00],
        dim="valid_time",
    )

    # Remove duplicated timestamps.
    timestamps = combined.valid_time.values

    _, unique_indices = np.unique(
        timestamps,
        return_index=True,
    )

    combined = combined.isel(
        valid_time=np.sort(unique_indices)
    )

    # -------------------------------------------------------------------------
    # Target days
    # -------------------------------------------------------------------------

    start = pd.Timestamp(
        year=year,
        month=month,
        day=1,
    )

    if month == 12:

        end = pd.Timestamp(
            year=year + 1,
            month=1,
            day=1,
        )

    else:

        end = pd.Timestamp(
            year=year,
            month=month + 1,
            day=1,
        )

    days = pd.date_range(
        start=start,
        end=end - pd.Timedelta(days=1),
        freq="D",
    )

    target_times = (
        days
        + pd.Timedelta(days=1)
    )

    # -------------------------------------------------------------------------
    # Select D+1 00 UTC
    # -------------------------------------------------------------------------

    daily = combined.sel(
        valid_time=target_times
    )

    daily = daily.assign_coords(
        valid_time=days
    )

    daily.name = variable

    return daily


# =============================================================================
# Monthly aggregation
# =============================================================================

def aggregate_month(
    current_ds: xr.Dataset,
    next_ds: xr.Dataset | None,
    variable: str,
    variable_type: str,
    year: int,
    month: int,
) -> xr.DataArray:

    # -------------------------------------------------------------------------
    # Instantaneous variables
    # -------------------------------------------------------------------------

    if variable_type == "instant":

        da = get_variable(
            current_ds,
            variable,
        )

        da = quality_control(
            da,
            variable,
        )

        da = remove_outliers(
            da,
        )

        monthly = da.mean(
            dim="valid_time",
            skipna=True,
        )

    # -------------------------------------------------------------------------
    # Accumulated variables
    # -------------------------------------------------------------------------

    elif variable_type == "accumulated":

        if next_ds is None:
            raise FileNotFoundError(
                "Next month dataset is required "
                f"for accumulated variable {variable}."
            )

        daily = extract_daily_accumulation(
            current_ds,
            next_ds,
            variable,
            year,
            month,
        )

        daily = quality_control(
            daily,
            variable,
        )

        daily = remove_outliers(
            daily,
        )

        monthly = daily.sum(
            dim="valid_time",
            skipna=True,
        )

    else:

        raise ValueError(
            f"Unknown variable type: {variable_type}"
        )

    monthly.name = variable

    return monthly


# =============================================================================
# Unit conversion
# =============================================================================

def convert_units(
    da: xr.DataArray,
    variable: str,
) -> xr.DataArray:

    if variable == "t2m":

        da = da - 273.15

        da.attrs["units"] = "degC"

    elif variable == "e":

        # ERA5 evaporation:
        # negative = evaporation from surface
        da = -da * 1000.0

        da.attrs["units"] = "mm"

    elif variable in {"tp", "sro"}:

        da = da * 1000.0

        da.attrs["units"] = "mm"

    elif variable == "swvl1":

        da.attrs["units"] = "m3 m-3"

    return da


# =============================================================================
# Boundary
# =============================================================================

def load_boundary() -> gpd.GeoDataFrame:

    boundary = gpd.read_file(
        BOUNDARY_FILE
    )

    if boundary.crs is None:
        raise ValueError(
            "China boundary has no CRS."
        )

    boundary = boundary.to_crs(
        "EPSG:4326"
    )

    return boundary


# =============================================================================
# Clip to China
# =============================================================================

def clip_to_china(
    da: xr.DataArray,
    boundary: gpd.GeoDataFrame,
) -> xr.DataArray:

    da = da.rio.set_spatial_dims(
        x_dim="longitude",
        y_dim="latitude",
        inplace=False,
    )

    da = da.rio.write_crs(
        "EPSG:4326",
        inplace=False,
    )

    # ERA5 latitude should be descending.
    if (
        da.latitude.values[0]
        < da.latitude.values[-1]
    ):

        da = da.sortby(
            "latitude",
            ascending=False,
        )

    clipped = da.rio.clip(
        boundary.geometry,
        boundary.crs,
        drop=True,
        all_touched=False,
    )

    return clipped


# =============================================================================
# Reproject + spatial resampling
# =============================================================================

def reproject_and_resample(
    da: xr.DataArray,
    variable: str,
    target_crs: str,
    target_resolution: float,
) -> xr.DataArray:
    """
    Reproject from EPSG:4326 to target Albers Equal Area
    and resample to target resolution.

    Continuous/state variables:
        t2m, swvl1 -> bilinear

    Accumulated water-depth variables:
        e, tp, sro -> average

    The output x/y coordinates are real projected coordinates,
    not row/column indices.

    CRS and GeoTransform are explicitly written to the
    resulting DataArray.
    """

    # -------------------------------------------------------------------------
    # Select resampling method
    # -------------------------------------------------------------------------

    if variable in {"t2m", "swvl1"}:

        resampling = Resampling.bilinear

    elif variable in {"e", "tp", "sro"}:

        resampling = Resampling.average

    else:

        raise ValueError(
            f"Unknown variable: {variable}"
        )

    # -------------------------------------------------------------------------
    # Remove unnecessary dimensions
    # -------------------------------------------------------------------------

    da = da.squeeze(
        drop=True
    )

    # -------------------------------------------------------------------------
    # Make sure latitude is descending
    # -------------------------------------------------------------------------

    if da.latitude.values[0] < da.latitude.values[-1]:

        da = da.sortby(
            "latitude",
            ascending=False,
        )

    # -------------------------------------------------------------------------
    # Source array
    # -------------------------------------------------------------------------

    src_array = da.values.astype(
        np.float32,
        copy=False,
    )

    # -------------------------------------------------------------------------
    # Source spatial resolution
    # -------------------------------------------------------------------------

    src_x_res = float(
        abs(
            da.longitude.values[1]
            - da.longitude.values[0]
        )
    )

    src_y_res = float(
        abs(
            da.latitude.values[1]
            - da.latitude.values[0]
        )
    )

    # -------------------------------------------------------------------------
    # Source transform
    # -------------------------------------------------------------------------

    src_transform = from_origin(
        float(da.longitude.values.min()),
        float(da.latitude.values.max()),
        src_x_res,
        src_y_res,
    )

    src_crs = "EPSG:4326"

    height, width = src_array.shape

    # -------------------------------------------------------------------------
    # Calculate target transform
    # -------------------------------------------------------------------------

    (
        dst_transform,
        dst_width,
        dst_height,
    ) = calculate_default_transform(
        src_crs,
        target_crs,
        width,
        height,
        left=float(da.longitude.values.min()),
        bottom=float(da.latitude.values.min()),
        right=float(da.longitude.values.max()),
        top=float(da.latitude.values.max()),
        resolution=target_resolution,
    )

    logger.info(
        "Target raster size: %d x %d",
        dst_width,
        dst_height,
    )

    logger.info(
        "Target transform: %s",
        dst_transform,
    )

    # -------------------------------------------------------------------------
    # Destination array
    # -------------------------------------------------------------------------

    dst_array = np.full(
        (dst_height, dst_width),
        NODATA,
        dtype=np.float32,
    )

    # -------------------------------------------------------------------------
    # Reprojection + resampling
    # -------------------------------------------------------------------------

    reproject(
        source=src_array,
        destination=dst_array,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=np.nan,
        dst_transform=dst_transform,
        dst_crs=target_crs,
        dst_nodata=NODATA,
        resampling=resampling,
    )

    # -------------------------------------------------------------------------
    # Build REAL projected x/y coordinates
    # -------------------------------------------------------------------------

    x_coords = (
        dst_transform.c
        + (
            np.arange(dst_width)
            + 0.5
        ) * dst_transform.a
    )

    y_coords = (
        dst_transform.f
        + (
            np.arange(dst_height)
            + 0.5
        ) * dst_transform.e
    )

    # -------------------------------------------------------------------------
    # Create DataArray with real spatial coordinates
    # -------------------------------------------------------------------------

    result = xr.DataArray(
        dst_array,
        dims=("y", "x"),
        coords={
            "y": y_coords,
            "x": x_coords,
        },
        attrs=da.attrs.copy(),
        name=variable,
    )

    # -------------------------------------------------------------------------
    # Write CRS and GeoTransform
    # -------------------------------------------------------------------------

    result = result.rio.set_spatial_dims(
        x_dim="x",
        y_dim="y",
        inplace=False,
    )

    result = result.rio.write_crs(
        target_crs,
        inplace=False,
    )

    result = result.rio.write_transform(
        dst_transform,
        inplace=False,
    )

    # -------------------------------------------------------------------------
    # Metadata
    # -------------------------------------------------------------------------

    result.attrs["spatial_resolution"] = (
        f"{target_resolution} m"
    )

    result.attrs["resampling_method"] = (
        resampling.name
    )

    return result


# =============================================================================
# Save
# =============================================================================

def save_monthly(
    da: xr.DataArray,
    variable: str,
    year: int,
    month: int,
):
    """
    Save one monthly result.

    The file is first written to a temporary file.
    Only after successful writing is it renamed to the
    final output filename.

    This prevents an interrupted write from leaving a
    seemingly complete but corrupted output file.
    """

    output_dir = (
        PROCESSED_DIR
        / variable
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = get_output_file(
        variable,
        year,
        month,
    )

    temp_file = output_dir / (
        f".{variable}_{year:04d}_{month:02d}.tmp.nc"
    )

    # -------------------------------------------------------------------------
    # Remove stale temporary file from a previous interrupted run
    # -------------------------------------------------------------------------

    if temp_file.exists():

        logger.warning(
            "Removing stale temporary file: %s",
            temp_file,
        )

        temp_file.unlink()

    # -------------------------------------------------------------------------
    # Make sure variable name is correct
    # -------------------------------------------------------------------------

    da.name = variable

    da.attrs["year"] = year
    da.attrs["month"] = month

    # -------------------------------------------------------------------------
    # Explicitly construct Dataset
    #
    # This prevents:
    #
    # __xarray_dataarray_variable__
    # -------------------------------------------------------------------------

    ds = xr.Dataset(
        {
            variable: da.astype(
                np.float32
            )
        }
    )

    # -------------------------------------------------------------------------
    # Encoding
    # -------------------------------------------------------------------------

    ds[variable].encoding = {
        "zlib": True,
        "complevel": 4,
        "dtype": "float32",
        "_FillValue": np.float32(NODATA),
    }

    try:

        # ---------------------------------------------------------------------
        # Write temporary file
        # ---------------------------------------------------------------------

        ds.to_netcdf(
            temp_file,
            mode="w",
            format="NETCDF4",
        )

        # ---------------------------------------------------------------------
        # Close dataset before replacing file
        # ---------------------------------------------------------------------

        ds.close()

        # ---------------------------------------------------------------------
        # Basic validation
        # ---------------------------------------------------------------------

        if (
            not temp_file.exists()
            or temp_file.stat().st_size == 0
        ):

            raise IOError(
                f"Temporary output file is empty: {temp_file}"
            )

        # ---------------------------------------------------------------------
        # Atomic replacement
        # ---------------------------------------------------------------------

        temp_file.replace(
            output_file
        )

        logger.info(
            "Saved: %s",
            output_file,
        )

    except Exception:

        # Close if an exception occurs.
        try:
            ds.close()
        except Exception:
            pass

        # Remove incomplete temporary file.
        if temp_file.exists():

            logger.warning(
                "Removing incomplete temporary file: %s",
                temp_file,
            )

            temp_file.unlink()

        raise


# =============================================================================
# Process one month
# =============================================================================

def process_month(
    year: int,
    month: int,
    boundary: gpd.GeoDataFrame,
):
    """
    Process one month.

    Existing successfully written outputs are automatically skipped.
    """

    current_file = get_month_file(
        year,
        month,
    )

    next_year, next_month_value = next_month(
        year,
        month,
    )

    next_file = get_month_file(
        next_year,
        next_month_value,
    )

    # -------------------------------------------------------------------------
    # Current file
    # -------------------------------------------------------------------------

    if not current_file.exists():

        logger.warning(
            "Missing file: %s",
            current_file,
        )

        return

    logger.info(
        "=" * 80
    )

    logger.info(
        "Processing %04d-%02d",
        year,
        month,
    )

    # -------------------------------------------------------------------------
    # Open current dataset
    # -------------------------------------------------------------------------

    current_ds = open_dataset(
        current_file
    )

    # -------------------------------------------------------------------------
    # Open next month only when available
    # -------------------------------------------------------------------------

    next_ds = None

    if next_file.exists():

        next_ds = open_dataset(
            next_file
        )

    try:

        for variable, info in VARIABLES.items():

            variable_type = info["type"]

            # ---------------------------------------------------------------
            # Checkpoint / restart
            # ---------------------------------------------------------------

            if is_monthly_output_complete(
                variable,
                year,
                month,
            ):

                logger.info(
                    "SKIP %04d-%02d %s: output already exists.",
                    year,
                    month,
                    variable,
                )

                continue

            logger.info(
                "Variable: %s",
                variable,
            )

            # ---------------------------------------------------------------
            # Check variable
            # ---------------------------------------------------------------

            if variable not in current_ds.data_vars:

                logger.warning(
                    "Variable '%s' not found in %s",
                    variable,
                    current_file.name,
                )

                continue

            # ---------------------------------------------------------------
            # Accumulated variables require next month
            # ---------------------------------------------------------------

            if (
                variable_type == "accumulated"
                and next_ds is None
            ):

                logger.error(
                    "Cannot process %s for %04d-%02d: "
                    "next month file is missing: %s",
                    variable,
                    year,
                    month,
                    next_file,
                )

                continue

            # ---------------------------------------------------------------
            # Temporal aggregation
            # ---------------------------------------------------------------

            monthly = aggregate_month(
                current_ds=current_ds,
                next_ds=next_ds,
                variable=variable,
                variable_type=variable_type,
                year=year,
                month=month,
            )

            # ---------------------------------------------------------------
            # Unit conversion
            # ---------------------------------------------------------------

            monthly = convert_units(
                monthly,
                variable,
            )

            # ---------------------------------------------------------------
            # Clip China
            # ---------------------------------------------------------------

            monthly = clip_to_china(
                monthly,
                boundary,
            )

            # ---------------------------------------------------------------
            # Reproject / resample
            # ---------------------------------------------------------------

            monthly = reproject_and_resample(
                monthly,
                variable,
                TARGET_CRS,
                TARGET_RESOLUTION,
            )

            # ---------------------------------------------------------------
            # Add time dimension
            # ---------------------------------------------------------------

            monthly = monthly.expand_dims(
                time=[
                    pd.Timestamp(
                        year=year,
                        month=month,
                        day=1,
                    )
                ]
            )

            # ---------------------------------------------------------------
            # Trigger computation
            # ---------------------------------------------------------------

            monthly = monthly.compute()

            # ---------------------------------------------------------------
            # Save
            # ---------------------------------------------------------------

            save_monthly(
                monthly,
                variable,
                year,
                month,
            )

            # ---------------------------------------------------------------
            # Release memory
            # ---------------------------------------------------------------

            del monthly

            gc.collect()

            logger.info(
                "Finished variable: %s",
                variable,
            )

    finally:

        current_ds.close()

        if next_ds is not None:
            next_ds.close()

        del current_ds
        del next_ds

        gc.collect()

        logger.info(
            "Released memory for %04d-%02d",
            year,
            month,
        )


# =============================================================================
# Main
# =============================================================================

def main():

    logger.info(
        "=" * 80
    )

    logger.info(
        "ERA5-LAND MONTHLY PREPROCESSING"
    )

    logger.info(
        "Period: %d-%d",
        START_YEAR,
        END_YEAR,
    )

    logger.info(
        "Raw directory: %s",
        RAW_DIR,
    )

    logger.info(
        "Processed directory: %s",
        PROCESSED_DIR,
    )

    logger.info(
        "Restart mode: AUTOMATIC RESUME"
    )

    # -------------------------------------------------------------------------
    # Boundary
    # -------------------------------------------------------------------------

    boundary = load_boundary()

    logger.info(
        "China boundary loaded."
    )

    # -------------------------------------------------------------------------
    # Raw files
    # -------------------------------------------------------------------------

    raw_files = sorted(
        p
        for p in RAW_DIR.iterdir()
        if is_valid_nc_file(p)
    )

    logger.info(
        "Found %d valid NetCDF files.",
        len(raw_files),
    )

    # -------------------------------------------------------------------------
    # Check final month requirement
    #
    # If END_YEAR is 2025:
    #
    #   2025-12 requires 2026-01
    #
    # because the complete accumulation of 2025-12-31
    # is stored at 2026-01-01 00 UTC.
    # -------------------------------------------------------------------------

    required_next_year, required_next_month = next_month(
        END_YEAR,
        12,
    )

    required_next_file = get_month_file(
        required_next_year,
        required_next_month,
    )

    if not required_next_file.exists():

        raise FileNotFoundError(
            "\n"
            "The requested processing period cannot be completed.\n"
            f"The final month {END_YEAR}-12 requires:\n"
            f"    {required_next_file}\n"
            "because the complete accumulation of the final day "
            "is stored at next month's 00 UTC."
        )

    # -------------------------------------------------------------------------
    # Process
    # -------------------------------------------------------------------------

    for year in range(
        START_YEAR,
        END_YEAR + 1,
    ):

        for month in range(
            1,
            13,
        ):

            process_month(
                year,
                month,
                boundary,
            )

    logger.info(
        "=" * 80
    )

    logger.info(
        "ALL PROCESSING FINISHED."
    )


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    main()