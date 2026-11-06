# WMO Support dataset: access and ingestion notes

This project is designed to process GRIB/GRIB2 files delivered through the ECMWF WMO Support dataset. It does not assume that every account sees the same folders, regions, or products.

## Official access information

- The ECMWF technical guide describes file-based delivery through the DISS FTP service. It says the account username is the user's wmo_xx account and the FTP password is a separate password supplied by ECMWF Data Support.
- The guide describes date-organised folders and says the FTP view contains the most recent four days of data. Always inspect the live directory listing rather than hardcoding a folder name or filename pattern.
- The ECMWF DISS portal may expose additional transfer methods depending on the service endpoint and account permissions. Use only the endpoint and method actually shown for the account in the official portal.

Official references:
- [ECMWF WMO Support dataset technical documentation](https://confluence.ecmwf.int/spaces/DAC/pages/669614969/Technical+documentation+page)
- [ECMWF WMO Support dataset overview and access conditions](https://www.ecmwf.int/en/forecasts/datasets/wmo-support-dataset-formerly-soff-dataset)
- [ECMWF DISS portal](https://diss.ecmwf.int/)

## Credential and data handling

1. Never put usernames, passwords, tokens, or private connection URLs in source files, commits, screenshots, or issue reports.
2. Do not upload restricted WMO Support GRIB files to this public repository.
3. Keep downloaded source files in a local data/raw/ directory, which is excluded by .gitignore.
4. Use the access method and redistribution conditions approved by ECMWF and the National Meteorological and Hydrological Service.
5. Do not assume that a password used for another ECMWF service is also the dataset transfer password.

## Recommended ingestion sequence

1. Sign in to the official DISS service using the account details provided to the authorised organisation.
2. Inspect the available date folders and product filenames. Do not assume a fixed directory layout.
3. Download one small representative GRIB file to a local data/raw/ directory.
4. Run: python inspect_grib.py data/raw/example.grib2 --output data/processed/grib_inventory.json
5. Review the inventory to identify actual shortName, units, levels, forecast steps, grid type, and dimensions.
6. Only then configure the processing pipeline for the variables and grid actually present in the file.

## Why inspection comes before conversion

WMO deliveries can contain multiple GRIB messages and different parameter/level combinations. The inventory utility reports message-level metadata without assuming that a file contains only 10-metre wind. The current wind converter remains a first prototype and must be tested against a real, locally available sample before it is treated as operational.
