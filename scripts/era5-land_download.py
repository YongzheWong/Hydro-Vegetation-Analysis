"""
Download ERA5-Land hourly data from CDS.

Author: Yongzhe Wong
Project: Hydro-Vegetation Analysis
"""

import sys
from pathlib import Path

import cdsapi

sys.path.append(str(Path(__file__).resolve().parent.parent))
from utils import load_config


def main():
    # =========================
    # Load configuration
    # =========================
    config = load_config()

    project = config["project"]
    era5 = config["era5land"]

    start_year = project["start_year"]
    end_year = project["end_year"]

    output_dir = Path(era5["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset = era5["dataset"]
    variables = era5["variables"]
    hours = era5["hours"]

    area = [
        era5["area"]["north"],
        era5["area"]["west"],
        era5["area"]["south"],
        era5["area"]["east"],
    ]

    client = cdsapi.Client()

    # =========================
    # Download loop
    # =========================
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):

            outfile = output_dir / f"ERA5Land_{year}_{month:02d}.nc"

            if outfile.exists():
                print(f"[Skip] {outfile.name}")
                continue

            print("=" * 60)
            print(f"Downloading {year}-{month:02d}")
            print("=" * 60)

            try:
                client.retrieve(
                    dataset,
                    {
                        "variable": variables,
                        "year": str(year),
                        "month": f"{month:02d}",
                        "day": [f"{d:02d}" for d in range(1, 32)],
                        "time": hours,
                        "data_format": "netcdf",
                        "download_format": "unarchived",
                        "area": area,
                    },
                    str(outfile),
                )

                print(f"[Done] {outfile.name}")

            except Exception as e:
                print(f"[Failed] {year}-{month:02d}")
                print(e)

    print("\nAll downloads finished.")

if __name__ == "__main__":
    main()