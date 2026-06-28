# Hydro-Vegetation Analysis

## Project Overview

This project analyzes the spatiotemporal variation of vegetation and hydrological variables in China from 2000 to 2025.

The workflow includes:

- Standardized preprocessing pipeline
  - Quality control
  - Outlier removal
  - Unit conversion
  - China boundary clipping
  - Resampling to 1 km
  - Albers Equal Area projection

- Trend analysis
  - Theil–Sen slope estimation
  - Mann–Kendall significance test
  - Sliding T-test for change point detection

- Spatial statistical analysis
  - Global Moran's I
  - Local Indicators of Spatial Association (LISA)
  - Hotspot and coldspot identification

---

## Project Structure

```text
data_analysis/
│
├── .gitignore
├── environment.yml        # Conda environment
├── README.md
├── LICENSE
├── config.yaml            # Project configuration
│
├── data/
│   ├── raw/               # Original datasets
│   ├── processed/         # Standardized datasets
│   └── boundary/          # China boundary shapefile
│
├── scripts/
│   ├── preprocess.py
│   ├── trend_analysis.py
│   ├── mk_test.py
│   ├── moran_analysis.py
│   └── utils.py
│
├── outputs/
│
└── figures/
```

---

## Environment

Create the Conda environment:

```bash
conda env create -f environment.yml
conda activate hydro
```

---

## Usage

### 1. Data preprocessing

```bash
python scripts/preprocess.py
```

### 2. Trend analysis

```bash
python scripts/trend_analysis.py
```

### 3. Mann–Kendall test

```bash
python scripts/mk_test.py
```

### 4. Moran's I and LISA

```bash
python scripts/moran_analysis.py
```

---

## Input Data

- LAI
- Evapotranspiration (ET)
- Soil Moisture (SM)
- Runoff
- China boundary shapefile

---

## Outputs

- Standardized raster datasets
- Trend maps
- Mann–Kendall significance maps
- Change point maps
- Moran's I statistics
- LISA cluster maps

---

## Author

Yongzhe Wong

Collage of Hydrology and Water Resources

Hohai University

---

2026.06.28