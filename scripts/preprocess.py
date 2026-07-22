"""
Preprocess pipeline.

Author: Yongzhe Wong
Project: Hydro-Vegetation Analysis
"""

from pathlib import Path

import numpy as np
import xarray as xr
import geopandas as gpd
import rioxarray
from rasterio.enums import Resampling

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from utils import load_config


def quality_control(ds):
    print("Quality control...")

    ds = ds.where(np.isfinite(ds))

    return ds


def remove_outliers(ds):
    print("Removing outliers...")

    limits = {
        "t2m": (180, 350),              # K
        "e": (-0.05, 0.05),             # m
        "sro": (0.0, 0.1),              # m
        "swvl1": (0.0, 0.8),            # m3/m3
        "tp": (0.0, 0.2)                # m
    }

    for var, (vmin, vmax) in limits.items():
        if var not in ds:
            continue

        before = ds[var].count().item()

        ds[var] = ds[var].where(
            (ds[var] >= vmin) &
            (ds[var] <= vmax)
        )

        after = ds[var].count().item()

        ratio = (before - after) / before * 100

        print(
            f"{var:<35}"
            f" removed {before - after} values"
            f"({ratio:.2f}%)"
        )
    
    return ds


def convert_units(ds):
    print("Converting units...")

    # Temperature
    if "t2m" in ds:
        ds["t2m"] = ds["t2m"] - 273.15
        ds["t2m"].attrs["units"] = "degC"

    # Evaporation
    if "e" in ds:
        ds["e"] *= 1000
        ds["e"].attrs["units"] = "mm"

        ds["ET"] = -ds["e"]
        ds["ET"].attrs["units"] = "mm"

    # Surface runoff
    if "sro" in ds:
        ds["sro"] *= 1000
        ds["sro"].attrs["units"] = "mm"

    # Soil moisture
    if "swvl1" in ds:
        ds["swvl1"].attrs["units"] = "m3 m-3"

    # Precipitation
    if "tp" in ds:
        ds["tp"] *= 1000
        ds["tp"].attrs["units"] = "mm"

    return ds


def clip_to_boundary(ds, boundary):
    print("Clipping China boundary...")

    ds = ds.rio.write_crs("EPSG:4326")

    boundary = boundary.to_crs("EPSG:4326")

    ds = ds.rio.clip(
        boundary.geometry,
        boundary.crs,
        drop=True
    )

    return ds


def reproject_to_albers(ds, target_crs):
    print("Reprojecting to Albers...")

    ds = ds.rio.write_crs("EPSG:4326")

    ds = ds.rio.reproject(target_crs)

    return ds


RESAMPLING_METHODS = {
    "nearest": Resampling.nearest,
    "bilinear": Resampling.bilinear,
    "average": Resampling.average,
    "cubic": Resampling.cubic
}

def resample_to_1km(ds, resolution, continuous_vars, continuous_method, flux_vars, flux_method):
    print("Spacial resampling...")

    for var in ds.data_vars:
        if var in continuous_vars:
            method = continuous_method

        elif var in flux_vars:
            method = flux_method

        else:
            method = RESAMPLING_METHODS["bilinear"]

        print(f"{var}: {method.name}")

        ds[var] = (
            ds[var]
            .rio
            .reproject(
                ds.rio.crs,
                resolution=resolution,
                resampling=method
            )
        )

    return ds


def main():
    config = load_config()

    raw_dir = Path(config["era5land"]["raw_data"])

    processed_dir = Path(config["era5land"]["processed_data"])
    processed_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    boundary = gpd.read_file(config["paths"]["boundary"])

    target_crs = config["projection"]["crs"]

    resolution = config["preprocess"]["target_resolution"]

    resampling_config = config["preprocess"]["resampling"]
    continuous_vars = (resampling_config["continuous"]["variables"])
    continuous_method = RESAMPLING_METHODS[resampling_config["continuous"]["method"]]
    flux_vars = (resampling_config["flux"]["variables"])
    flux_method = RESAMPLING_METHODS[resampling_config["flux"]["method"]]
    
    for nc_file in sorted(f for f in raw_dir.glob("*.nc") if not f.name.startswith("._")):
        print("=" * 50)
        print(f"Processing {nc_file.name}")

        ds = xr.open_dataset(nc_file, engine="netcdf4")

        ds = quality_control(ds)
        ds = remove_outliers(ds)
        ds = convert_units(ds)
        ds = clip_to_boundary(ds, boundary)
        ds = reproject_to_albers(ds, target_crs)

        if "valid_time" in ds.dims:
            ds = ds.chunk({"valid_time": 24})
        elif "time" in ds.dims:
            ds = ds.chunk({"time": 24})

        ds = resample_to_1km(ds, resolution, continuous_vars, continuous_method, flux_vars, flux_method)

        output_file = (processed_dir/f"{nc_file.stem}_processed.nc")

        print(f"Saving to {output_file}")

        ds.to_netcdf(output_file)

        print("Finished:", output_file.name)

        ds.close()

    print("All preprocessing finished!")

if __name__ == "__main__":
    main()