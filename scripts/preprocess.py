"""
Preprocess pipeline.

Author: Yongzhe Wong
Project: Hydro-Vegetation Analysis
"""

from pathlib import Path

import numpy as np
import xarray as xr

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


def main():
    config = load_config()

    raw_dir = Path(config["era5land"]["raw_data"])

    processed_dir = Path(config["era5land"]["processed_data"])
    processed_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    for nc_file in sorted(raw_dir.glob("*.nc")):
        print("=" * 50)
        print(f"Processing {nc_file.name}")

        ds = xr.open_dataset(nc_file)

        ds = quality_control(ds)
        ds = remove_outliers(ds)
        ds = convert_units(ds)

        output_file = (processed_dir/f"{nc_file.stem}_processed.nc")

        print(f"Saving to {output_file}")

        ds.to_netcdf(output_file)

        print("Finished:", output_file.name)

        ds.close()

    print("All preprocessing finished!")

if __name__ == "__main__":
    main()