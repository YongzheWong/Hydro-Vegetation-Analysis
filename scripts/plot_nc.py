import xarray as xr
import matplotlib.pyplot as plt

file = "/Volumes/PortableSSD/data/processed/ERA5Land/e/e_2022_03.nc"

ds = xr.open_dataset(file)

sro = ds["e"].isel(time=0)

sro.plot(
    figsize=(10, 7)
)

plt.title("Evaporation - 2022-03")
plt.xlabel("X (m)")
plt.ylabel("Y (m)")
plt.show()