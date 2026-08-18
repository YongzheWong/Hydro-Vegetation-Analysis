import sys
import xarray as xr


def inspect_nc(file):
    ds = xr.open_dataset(file)

    print("=" * 60)
    print(f"File: {file}")
    print("=" * 60)

    print("\n[Dataset]")
    print(ds)

    print("\n[Dimensions]")
    for name, size in ds.sizes.items():
        print(f"  {name}: {size}")

    print("\n[Variables]")
    for name, var in ds.data_vars.items():
        print(f"\n  {name}")
        print(f"    dims:  {var.dims}")
        print(f"    shape: {var.shape}")
        print(f"    dtype: {var.dtype}")
        print(f"    units: {var.attrs.get('units', 'N/A')}")
        print(f"    long_name: {var.attrs.get('long_name', 'N/A')}")

        print(
            f"    min: {var.min().compute().item()}"
        )
        print(
            f"    max: {var.max().compute().item()}"
        )
        print(
            f"    mean: {var.mean().compute().item()}"
        )

    if "time" in ds.coords:
        print("\n[Time]")
        print(f"  start: {ds.time.min().values}")
        print(f"  end:   {ds.time.max().values}")
        print(f"  count: {ds.sizes['time']}")

    var = ds["t2m"]

    total = var.size
    valid = var.notnull().sum().compute().item()
    nan = total - valid

    print("Total:", total)
    print("Valid:", valid)
    print("NaN:", nan)
    print("NaN ratio:", nan / total * 100, "%")

    ds.close()


if __name__ == "__main__":
    inspect_nc(sys.argv[1])