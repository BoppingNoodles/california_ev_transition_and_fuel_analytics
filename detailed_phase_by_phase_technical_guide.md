# California EV Transition & Fuel Station Analytics - Detailed Phase-by-Phase Implementation Guide

This guide walks through the logic, math, file responsibilities, and validation steps for the California EV Transition and Fuel Station Analytics project. It is intentionally code-free: the goal is to make each script, notebook, and output clear before you implement it.

The project answers three main questions:

1. Where in California is EV charging coverage materially weaker than gasoline access?
2. Which gas stations are strong candidates for future EV charging conversion?
3. How stable are those findings when assumptions, buffers, and scoring weights change?

---

## General Architectural Setup

For every Python script you write:

1. **Module imports**
   - Import standard libraries for paths, dates, JSON, timing, and errors.
   - Import third-party libraries only when needed, such as `requests`, `pandas`, `geopandas`, `numpy`, `scipy`, `shapely`, and visualization libraries.
   - Import shared project values from `src/config.py` instead of hard-coding paths, URLs, CRS values, or output folders.

2. **Project path resolution**
   - Scripts should run from the terminal without depending on the current working directory.
   - Resolve the project root dynamically from the script location.
   - Load shared config after the project source path is available.

3. **Coordinate reference system convention**
   - Load raw external sources in their native CRS, usually **EPSG:4326** for latitude/longitude.
   - Perform spatial joins, nearest-neighbor calculations, distance measurements, buffers, and area calculations in **EPSG:3310**.
   - Export web maps and GeoJSON files in **EPSG:4326**.

4. **Folder conventions**
   - `data/raw/`: dated snapshots exactly as downloaded or lightly flattened for inspection.
   - `data/external/`: manually downloaded context layers such as Census tracts, ACS data, highways, or ZEV registrations.
   - `data/processed/`: cleaned, analysis-ready Parquet or GeoParquet files.
   - `outputs/geojson/`: final spatial layers for sharing or mapping.
   - `outputs/tables/`: final CSV tables.
   - `outputs/maps/`: exported HTML or static maps.

5. **Reproducibility rule**
   - Raw data files should be dated.
   - Processed files may use stable names, but should include metadata columns or notebook notes indicating source snapshot dates.
   - Every notebook should print the source files it loaded and the row counts it produced.

---

## Phase 1 - Data Ingestion

### Phase Goal

Collect raw source data for EV chargers, gas stations, Census geography, and demographics. At the end of this phase, you should have dated raw snapshots and a notebook proving the files are populated, geographically plausible, and ready for cleaning.

### Primary Inputs

- NREL AFDC EV charging station API.
- California Energy Commission gas station FeatureServer.
- Census tract boundaries.
- ACS tract-level demographic data.

### Primary Outputs

- `data/raw/afdc_ev_stations_<date>.json`
- `data/raw/afdc_ev_stations_<date>.csv`
- `data/raw/cec_gas_stations_<date>.geojson`
- `data/raw/cec_gas_stations_<date>.csv`
- Census and demographic files placed in `data/external/`
- `notebooks/01_data_acquisition.ipynb`

### 1.1. EV Charging Ingestion: `src/ingest/fetch_afdc.py`

This module pulls California electric charging station data from the NREL Alternative Fuels Data Center API.

**Purpose**

- Create a reproducible raw snapshot of all California electric charging stations available from AFDC.
- Preserve the full API response for traceability.
- Also create a smaller flat CSV for quick inspection and downstream cleaning.

**API configuration**

- Endpoint: use `AFDC_API_URL` from `src/config.py`.
- API key: read `NREL_API_KEY` from the environment through `src/config.py`.
- Request parameters:
  - `fuel_type`: electric only.
  - `state`: California only.
  - `status`: all, so raw data keeps open, planned, temporarily unavailable, or other statuses for later filtering.
  - `access`: all, so public/private filtering happens in the cleaning phase.
  - `limit`: all, to avoid partial downloads.

**Recommended function boundaries**

- A fetch function that sends the request, raises an error on failed HTTP responses, parses JSON, and returns the station list.
- A save function that writes both the raw JSON snapshot and the flattened CSV snapshot.
- A QC function that prints counts, coordinate completeness, access-code distribution, and DC fast charging totals.
- A script entry point that runs fetch, save, and QC in order.

**Fields to preserve in the flat CSV**

- Stable identifiers: station ID.
- Location fields: station name, address, city, state, ZIP, latitude, longitude.
- Access/status fields: status code, access code, owner type, facility type.
- Charging fields: connector types, Level 1 ports, Level 2 ports, DC fast ports, network, pricing.
- Planning/context fields: funding sources, open date, date last confirmed.

**Edge cases to handle**

- API key missing or invalid.
- API returns zero stations.
- API response contains a top-level error object.
- Some station objects lack coordinate or charging-count fields.
- Port-count fields may be missing, null, or stored as values that need numeric conversion later.

**QC checks**

- Total station records fetched.
- Percent of records with both latitude and longitude.
- Number of rows where state is not `CA`.
- Count of public/private/restricted access values.
- Sum of raw DC fast ports.
- Snapshot filenames printed to the console.

### 1.2. Gas Stations Ingestion: `src/ingest/fetch_gas_stations.py`

This module retrieves gas station point features from the CEC ArcGIS FeatureServer.

**Purpose**

- Download the full gas station FeatureServer layer despite server page limits.
- Save one complete GeoJSON snapshot and one flattened CSV for review.

**API configuration**

- Query URL: use `CEC_GAS_STATIONS_URL` from `src/config.py`.
- Parameters:
  - `where=1=1` to request all features.
  - `outFields=*` to keep all attributes.
  - `f=geojson` to request GeoJSON output.
  - `resultRecordCount` set to a page size such as 2,000.
  - `resultOffset` incremented for pagination.

**Pagination logic**

- Start at offset 0.
- Request one page.
- Append the returned features to a running list.
- Print the offset, page count, and running total.
- Stop when the returned page contains fewer records than the page size.
- Sleep briefly between requests so the service is not hammered.

**Recommended function boundaries**

- A fetch function that handles pagination and returns all features.
- A save function that rebuilds a valid GeoJSON FeatureCollection and creates a flat CSV.
- A QC function that reports record count and valid geometry rate.
- A script entry point that times the full run and exits clearly on zero features.

**Fields to preserve in the flat CSV**

- All original properties from the FeatureServer.
- Derived longitude and latitude from point geometry.
- The original object ID or feature ID.

**Edge cases to handle**

- ArcGIS returns an `error` object even with HTTP 200.
- A page returns malformed or missing geometry.
- Coordinates are reversed or null.
- Server paging limit differs from the requested page size.
- Layer schema changes over time.

**QC checks**

- Total features fetched.
- Valid geometry percentage.
- Approximate coordinate extent.
- A spot check that longitude is negative and latitude is positive for California.
- Saved GeoJSON and CSV paths.

### 1.3. Tract Shapefiles and Census Demographics Ingestion

This subphase creates the geographic and demographic base for tract-level analysis.

**Spatial unit layer**

- Download California Census tract geometries from TIGER/Line.
- Store them in `data/external/`.
- Keep the original downloaded files intact so you can rerun joins later.
- Use tract GEOID as the stable join key.

**Demographics layer**

- Download ACS 5-year tract-level estimates.
- Minimum required variables:
  - Total population.
  - Median household income.
- Useful optional variables:
  - Households without vehicles.
  - Race/ethnicity summary variables.
  - Poverty rate.
  - Commute mode or commute time.
  - Housing units or household count.

**Data shape expectations**

- The tract layer should have one row per Census tract polygon.
- The demographic table should have one row per tract GEOID.
- GEOID fields should be text, not numeric, so leading zeros are preserved.

**QC checks**

- Confirm only California tracts are included.
- Confirm tract GEOID values are unique.
- Confirm ACS GEOID values are unique.
- Count unmatched tract GEOIDs after joining demographics.
- Check that population and income fields have plausible ranges.

### 1.4. Validation Notebook: `notebooks/01_data_acquisition.ipynb`

This notebook proves that Phase 1 data acquisition worked.

**Notebook flow**

- Import project paths and date constants.
- Run or document the two ingestion scripts.
- Locate the newest AFDC and CEC raw files.
- Load the EV CSV, gas CSV, gas GeoJSON, tract layer, and demographics table.
- Print row counts, column counts, and file paths.

**Validation checks**

- Files exist and have non-zero size.
- EV and gas records have non-zero row counts.
- Latitude and longitude fall within a broad California bounding box.
- Gas station GeoJSON loads as valid point geometry.
- Census tract geometry loads as polygons or multipolygons.
- Demographic table has the required GEOID and population fields.

**Phase 1 exit criteria**

- Both ingestion scripts run end-to-end.
- Raw files are saved with date stamps.
- External Census and ACS files are available.
- Notebook shows no obvious empty datasets, coordinate failures, or missing required fields.

---

## Phase 2 - EDA and Cleaning

### Phase Goal

Convert raw snapshots into cleaned, projected, analysis-ready spatial datasets. This phase removes unusable records, standardizes schemas, calculates basic charging counts, and saves stable processed files.

### Primary Inputs

- Latest raw AFDC EV station snapshot.
- Latest raw CEC gas station snapshot.
- Optional county or state boundary layer for map checks.

### Primary Outputs

- `data/processed/ev_stations.parquet`
- `data/processed/gas_stations.parquet`
- `notebooks/02_eda_and_qc.ipynb`

### 2.1. Ingest Cleaning Pipeline: `src/transform/clean_stations.py`

Build a pipeline that reads raw snapshots, cleans attributes, creates geometries, projects to California Albers, and writes fast processed files.

**Recommended module structure**

- A helper that finds the latest raw file matching a filename pattern.
- An EV cleaning function.
- A gas station cleaning function.
- Shared helpers for coordinate validation, projection, and output writing.
- A script entry point that runs both cleaning functions and prints QC summaries.

**EV station cleaning steps**

- Load the raw AFDC CSV or JSON.
- Keep rows where state is exactly `CA`.
- Remove records missing latitude or longitude.
- Remove records with coordinates outside a broad California bounding box.
- Filter to public-access stations for the main processed dataset.
- Keep status fields so later analysis can optionally restrict to operational or open stations.
- Convert Level 1, Level 2, and DC fast port fields to numeric values.
- Treat missing port counts as zero.
- Add:
  - `level1_ports`
  - `level2_ports`
  - `dcfc_ports`
  - `total_ev_ports`
  - `has_dcfc`
  - `source_snapshot_date`
- Create point geometry from longitude and latitude in **EPSG:4326**.
- Project to **EPSG:3310** before saving.
- Save as `data/processed/ev_stations.parquet`.

**EV edge cases**

- Public access may be represented by more than one value or include nulls.
- Some stations may have connector types but no port counts.
- Some sites may have only planned or temporarily unavailable status.
- Duplicate station IDs may appear if the raw source changes shape.

**Gas station cleaning steps**

- Load the raw CEC GeoJSON.
- Confirm geometry is point geometry.
- Project to **EPSG:3310**.
- Create rounded X/Y coordinate columns at roughly 10-meter precision.
- Drop duplicate stations sharing the same rounded X/Y coordinates.
- Standardize schema columns:
  - `station_id`
  - `name`
  - `address`
  - `city`
  - `zip`
  - `source`
  - `source_snapshot_date`
  - `geometry`
- Preserve original ID and name fields if the source schema is uncertain.
- Save as `data/processed/gas_stations.parquet`.

**Gas edge cases**

- Some features may have missing or invalid geometry.
- Source attributes may use unclear field names.
- Multiple records may represent the same site.
- The CEC gas station layer may be old, so cleaned outputs should retain source date notes.

**Shared QC checks**

- Raw row count vs. cleaned row count.
- Number of records dropped for missing coordinates.
- Number of records dropped for non-public EV access.
- Number of duplicate gas stations removed.
- Final CRS for both processed layers.
- Geometry validity count.
- Bounding-box check after projection and after reprojecting to web CRS.

### 2.2. QC Notebook: `notebooks/02_eda_and_qc.ipynb`

Use this notebook to understand the cleaned datasets and catch spatial problems before analysis.

**Notebook sections**

- Load processed EV and gas station files.
- Print schemas, CRS values, and row counts.
- Summarize EV stations by access code, network, status, and port type.
- Summarize gas stations by county or source attributes if county is available.
- Plot Level 2 and DC fast port distributions.
- Map EV and gas points over a California boundary layer.
- Check for outliers far outside the state.

**Recommended visual checks**

- Scatter map of all EV stations and all gas stations.
- Histogram of total EV ports per station.
- Histogram of DC fast ports per station.
- Table of top charging networks.
- Table of cities or counties with the most gas stations.

**Phase 2 exit criteria**

- Processed EV and gas Parquet files exist.
- Both files are in **EPSG:3310**.
- Public EV station filtering is documented.
- Duplicate gas station logic is documented.
- Notebook maps show both point layers aligning with California.

---

## Phase 3 - Charging Desert Analysis

### Phase Goal

Create tract-level metrics that compare EV charging supply, gasoline access, population context, and distance to DC fast charging. Convert those metrics into a transparent desert score and severity classification.

### Primary Inputs

- `data/processed/ev_stations.parquet`
- `data/processed/gas_stations.parquet`
- Census tract geometries.
- ACS demographic table.

### Primary Outputs

- `outputs/geojson/charging_deserts.geojson`
- Optional processed tract metrics file in `data/processed/`
- `notebooks/03_charging_deserts.ipynb`

### 3.1. Spatial Unit Context and Coverage: `src/analysis/coverage_metrics.py`

This module associates infrastructure points with Census tracts and calculates accessibility metrics.

**Recommended module responsibilities**

- Load cleaned EV stations, gas stations, tract geometries, and demographics.
- Standardize tract GEOID fields.
- Project all spatial layers to **EPSG:3310**.
- Join demographics to tract geometries.
- Calculate area, density, counts, and nearest-neighbor metrics.
- Return or save a tract-level GeoDataFrame.

**Core tract metrics**

- `tract_area_sq_km`: tract geometry area in square kilometers.
- `population`: ACS total population.
- `median_household_income`: ACS median income.
- `population_density`: population divided by tract area.
- `ev_station_count`: count of public EV stations inside the tract.
- `level2_ports`: sum of Level 2 ports inside the tract.
- `dcfc_ports`: sum of DC fast ports inside the tract.
- `total_ev_ports`: sum of all public EV ports inside the tract.
- `ev_port_density`: total EV ports divided by tract area.
- `ev_ports_per_1000_people`: total EV ports divided by population, scaled to 1,000 residents.
- `gas_station_count`: count of gas stations inside the tract.
- `gas_access_count_2km`: number of gas stations within 2 kilometers of the tract centroid.
- `nearest_dcfc_km`: distance from tract centroid to nearest DC fast charging station.

**Spatial join logic**

- Use point-in-polygon joins for station counts inside tracts.
- Use tract centroids for nearest-neighbor calculations.
- Use a 2-kilometer centroid buffer or spatial index query for nearby gas access.
- Use only stations with positive DC fast port counts when calculating nearest DCFC distance.

**Important metric decisions**

- Large rural tracts can distort area-based density. Keep both area-based and population-based metrics so you can compare them.
- If population is zero or missing, avoid division errors and explicitly mark derived population metrics as null or zero according to the analysis rule.
- For island or remote tracts, nearest-neighbor straight-line distance may be less realistic than road distance. Document this limitation.

**QC checks**

- Number of tracts before and after demographic join.
- Number of tracts with missing population.
- Total EV station count before and after tract join.
- Total gas station count before and after tract join.
- Minimum, median, and maximum nearest DCFC distance.
- Number of tracts with no EV ports.

### 3.2. Desert Classification Engine: `src/analysis/desert_detection.py`

This module turns tract metrics into normalized scores and severity classes.

**Purpose**

- Make charging-desert classification explicit, repeatable, and easy to test.
- Keep the scoring formula separate from metric generation so you can rerun sensitivity analysis later.

**Normalizing inputs**

- Convert each selected metric to a 0-to-1 scale before combining.
- For values where higher means worse, normalize directly.
- For values where lower means worse, normalize the inverse.
- Handle constant columns safely. If min equals max, assign a neutral value rather than dividing by zero.

**Recommended normalized components**

- `gas_access_component`: higher when nearby gasoline access is high.
- `population_density_component`: higher when more people may be affected.
- `ev_gap_component`: higher when EV port density is low.
- `dcfc_distance_component`: higher when the nearest DC fast charger is farther away.

**Composite desert score**

Use a 0-to-100 weighted score:

```text
desert_score =
    100 * (
        w_gas_access * gas_access_component
      + w_population * population_density_component
      + w_ev_gap * ev_gap_component
      + w_dcfc_distance * dcfc_distance_component
    )
```

Default weights to test:

- `w_gas_access = 0.25`
- `w_population = 0.25`
- `w_ev_gap = 0.35`
- `w_dcfc_distance = 0.15`

Note: Distance to DCFC should increase the desert score when chargers are farther away. Treat it as a positive gap component, not a subtraction.

**Severity classifications**

- `severe_desert`: score greater than or equal to 75.
- `moderate_desert`: score from 50 to less than 75.
- `adequate`: score less than 50.

**Optional eligibility filters**

- Require population greater than 500, or flag low-population tracts separately.
- Flag tracts with no EV ports and at least one nearby gas station.
- Keep rural and urban results comparable by reporting both statewide ranks and county-level ranks.

**QC checks**

- Scores are always between 0 and 100.
- Every tract receives a severity label.
- Component columns are always between 0 and 1.
- Severe-desert tracts are inspected on a map for plausibility.
- Top-ranked desert tracts are not all artifacts of huge rural tract area.

### 3.3. In-Depth Analysis Notebook: `notebooks/03_charging_deserts.ipynb`

This notebook presents the first real analytical result of the project.

**Notebook sections**

- Load tract metrics and desert scores.
- Summarize score distribution.
- Map desert score as a choropleth.
- Map severity classes.
- List the top 15 severe-desert tracts.
- Summarize severe-desert counts by county if county attribution is available.
- Compare desert score with median household income and population density.

**Recommended outputs**

- `outputs/geojson/charging_deserts.geojson`
- Optional CSV summary table by county.
- Notebook charts for score histogram and component distributions.

**Phase 3 exit criteria**

- Every tract has metric columns, desert score, and severity label.
- Output GeoJSON opens correctly in a web map.
- The formula and weights are documented in the notebook.
- Top severe-desert examples have been manually inspected.

---

## Phase 4 - Conversion Candidates

### Phase Goal

Rank existing gas stations by their suitability for EV charging conversion using local charging gaps, distance from existing DC fast charging, population context, corridor access, redundancy, and planned infrastructure.

### Primary Inputs

- Clean gas station layer.
- Clean EV station layer.
- Charging desert tract layer.
- Optional highway layer.
- Optional NEVI or planned charging layer.

### Primary Outputs

- `outputs/tables/conversion_candidates.csv`
- Optional candidate GeoJSON.
- `notebooks/04_conversion_candidates.ipynb`

### 4.1. Gas Station Scoring Logic: `src/analysis/conversion_scoring.py`

This module calculates a 0-to-100 conversion suitability score for each gas station.

**Recommended module responsibilities**

- Load gas stations, EV stations, and desert tracts.
- Attach each gas station to a tract and local desert score.
- Calculate distance from each gas station to the nearest DCFC.
- Calculate nearby gas station redundancy.
- Calculate highway proximity if a highway layer is available.
- Apply scoring components and penalties.
- Produce a ranked table with clear rationale fields.

**Scoring components**

1. **Local charging gap: 30 points**
   - Use the gas station's tract `desert_score`.
   - Higher desert score gives more points.
   - This ties candidate selection to the Phase 3 accessibility analysis.

2. **Nearest DCFC distance: 25 points**
   - Measure distance from the gas station to the nearest station with positive DC fast ports.
   - Cap the scoring distance at 15 kilometers.
   - A site 15 kilometers or farther from DCFC receives full points for this component.
   - A site already very close to DCFC receives few points.

3. **Population and corridor context: 20 points**
   - Use tract population or population density.
   - Add highway proximity if a major-road layer is available.
   - A practical rule is to award more points to populated tracts and sites within 5 kilometers of a major highway.
   - If no highway layer is available, document that this component is population-only for v1.

4. **Site suitability proxy: up to 15 points**
   - If parcel or footprint data is not available, use simple proxies.
   - Potential proxies include standalone station type, facility type, distance from dense urban core, or whether the site is near a highway.
   - Keep this component clearly labeled as a proxy unless real parcel/land-use data is added.

5. **Redundancy penalty: subtract up to 10 points**
   - Count other gas stations within 1 kilometer.
   - Apply a larger penalty when many nearby gas stations would create clustered recommendations.
   - Do not make the penalty so strong that it eliminates all urban candidates.

6. **Planned infrastructure penalty: subtract up to 10 points**
   - If NEVI-funded or planned charging stations are available, penalize candidates within 3 kilometers.
   - If no planned-infrastructure layer is available, set this penalty to zero and document the limitation.

**Recommended output columns**

- `rank`
- `station_id`
- `name`
- `address`
- `city`
- `zip`
- `latitude`
- `longitude`
- `final_score`
- `tract_geoid`
- `desert_score`
- `nearest_dcfc_km`
- `nearby_gas_stations_1km`
- `highway_distance_km`
- `nevi_penalty`
- `rationale`

**Rationale field**

The rationale should be a concise sentence or phrase explaining why the candidate ranked highly, such as:

- High local desert score.
- Far from existing DC fast charging.
- Located in a populated tract.
- Limited nearby gas station redundancy.
- Near a major corridor.

**QC checks**

- Final scores are between 0 and 100.
- Every gas station receives a score.
- Top-ranked candidates have valid coordinates.
- No duplicate station IDs appear in the output.
- The top 50 candidates are inspected on a map.
- Scores are broken into components so the ranking is explainable.

### 4.2. Validation Notebook: `notebooks/04_conversion_candidates.ipynb`

This notebook turns the candidate score table into a reviewable analysis product.

**Notebook sections**

- Load scored candidates.
- Display the top 50 candidates.
- Plot candidates on top of charging desert tracts.
- Overlay existing DC fast charging stations.
- Show histograms of candidate scores and nearest DCFC distances.
- Show a score-component table for the top candidates.

**Recommended exports**

- `outputs/tables/conversion_candidates.csv`
- Optional `outputs/geojson/conversion_candidates.geojson`
- Static or interactive candidate map.

**Phase 4 exit criteria**

- Ranked CSV exists and contains all required columns.
- Top candidates have transparent score components.
- Notebook map confirms top candidates are located in plausible charging-gap areas.
- Any missing optional layers, such as NEVI or highways, are documented.

---

## Phase 5 - Delivery and Visualizations

### Phase Goal

Package the analysis into shareable outputs: sensitivity analysis, maps, dashboard, and written findings. This phase is about making the work understandable and defensible.

### Primary Inputs

- Charging desert GeoJSON.
- Conversion candidate CSV or GeoJSON.
- Processed EV and gas station layers.
- Optional context layers such as ZEV registrations, highways, or county boundaries.

### Primary Outputs

- `notebooks/05_sensitivity_and_report.ipynb`
- `outputs/maps/charging_deserts.html`
- `app/streamlit_app.py`
- README findings section or separate written summary.

### 5.1. Sensitivity Analysis: `notebooks/05_sensitivity_and_report.ipynb`

Assess whether the results are stable or overly dependent on one assumption.

**Weight sensitivity**

- Increase and decrease major desert-score weights by about 10%.
- Re-normalize weights so the total remains interpretable.
- Record how many severe-desert tracts remain severe.
- Compare top candidate ranks across scenarios.

**Buffer sensitivity**

- Test gasoline access buffers such as 2 kilometers and 5 kilometers.
- Test redundancy buffers such as 1 kilometer and 2 kilometers.
- Compare how many tracts or candidates change class.

**Metric sensitivity**

- Compare EV supply measured as:
  - Total EV port density.
  - DCFC-only density.
  - EV ports per 1,000 residents.
- Compare statewide normalization against county-level or urban/rural normalization if time allows.

**Stable candidate definition**

- A stable candidate is a gas station that appears in the top 20 or top 50 across most scenarios.
- Track candidate rank under each scenario.
- Create a stability count or average rank.

**Recommended notebook outputs**

- Table of stable top candidates.
- Rank-change chart for top candidates.
- Before/after maps for at least one sensitivity scenario.
- Short written interpretation of which assumptions matter most.

### 5.2. Web Map Generator: `src/viz/maps.py`

Create an interactive map that lets users inspect desert tracts, EV stations, and conversion candidates.

**Map responsibilities**

- Load desert GeoJSON and candidate table or candidate GeoJSON.
- Convert spatial layers to **EPSG:4326** for web display.
- Initialize a California-centered map.
- Add a tract choropleth layer for desert score.
- Add severity-class styling.
- Add EV station markers or clustered markers.
- Add top candidate markers with readable popups.
- Save the final HTML file to `outputs/maps/charging_deserts.html`.

**Recommended map layers**

- Charging desert choropleth.
- Severe desert outline.
- Existing Level 2 charging stations.
- Existing DC fast charging stations.
- Top 50 gas-to-EV conversion candidates.
- Optional county boundaries.

**Popup content**

- Candidate rank.
- Station name.
- Address or city.
- Final score.
- Local desert score.
- Distance to nearest DCFC.
- Rationale.

**QC checks**

- HTML map file is created.
- File opens locally.
- Candidate markers appear in California.
- Choropleth colors match score values.
- Popups are readable and not overloaded.
- Large point layers do not make the map unusably slow.

### 5.3. Dashboard Interface: `app/streamlit_app.py`

Build a lightweight dashboard for interactive review.

**Dashboard layout**

- Sidebar filters:
  - County.
  - Minimum candidate score.
  - Severity class.
  - Show/hide EV stations.
  - Show/hide gas candidates.
- Main metrics:
  - Number of analyzed gas stations.
  - Number of severe-desert tracts.
  - Number of top-priority candidates.
  - Median nearest DCFC distance among filtered candidates.
- Main views:
  - Interactive map.
  - Ranked candidate table.
  - Score-component chart or summary.

**Export behavior**

- Allow the filtered candidate table to be downloaded as CSV.
- Clearly label whether the export is filtered or full-state.

**Run documentation**

- Add launch instructions to the README or notebook:
  - Environment setup.
  - Required processed files.
  - Streamlit run command.

**QC checks**

- Dashboard starts without missing-file errors.
- Filters update the table and map consistently.
- Empty filter results show a useful message instead of crashing.
- Large GeoJSON layers are simplified or cached if performance is slow.

### 5.4. Written Findings and Limitations

Finish with a concise written summary so the project is understandable without reading every notebook.

**Recommended findings section**

- Statewide count of severe and moderate desert tracts.
- Counties or regions with the strongest gaps.
- Top conversion candidates and why they rank highly.
- Sensitivity findings: which candidates are stable and which assumptions shift results.
- Equity or demographic observations if supported by the data.

**Limitations to document**

- Gas station source age and possible closures.
- EV station availability vs. listing presence.
- Straight-line distance vs. drive-time access.
- Lack of parcel ownership, zoning, grid capacity, and site electrical feasibility.
- Census tract size differences, especially in rural California.
- Planned charging infrastructure may be incomplete if NEVI or funding layers are unavailable.

**Phase 5 exit criteria**

- Sensitivity notebook is complete.
- Interactive map exists and opens.
- Candidate table and charging desert GeoJSON are exported.
- Dashboard runs if included in scope.
- README or written summary explains data sources, method, findings, and limitations.

---

## Final Project Deliverables

| Deliverable | Path | Purpose |
|---|---|---|
| Raw EV snapshots | `data/raw/afdc_ev_stations_<date>.*` | Reproducible AFDC source data |
| Raw gas snapshots | `data/raw/cec_gas_stations_<date>.*` | Reproducible CEC source data |
| Clean EV layer | `data/processed/ev_stations.parquet` | Analysis-ready public EV stations |
| Clean gas layer | `data/processed/gas_stations.parquet` | Analysis-ready gas stations |
| Charging desert layer | `outputs/geojson/charging_deserts.geojson` | Tract-level desert score map |
| Candidate table | `outputs/tables/conversion_candidates.csv` | Ranked gas-to-EV conversion sites |
| Interactive map | `outputs/maps/charging_deserts.html` | Shareable visual output |
| Dashboard | `app/streamlit_app.py` | Optional interactive review tool |
| Notebooks | `notebooks/01` through `notebooks/05` | Reproducible workflow and analysis story |

---

## Suggested Phase Order

1. Finish Phase 1 ingestion and prove raw data quality.
2. Finish Phase 2 cleaning before building any scoring logic.
3. Build Phase 3 tract metrics first, then desert classification.
4. Build Phase 4 candidate scoring only after desert scores look plausible.
5. Use Phase 5 to test assumptions, polish outputs, and write findings.

This order keeps the project defensible: every later score depends on validated raw data, cleaned geometry, and documented metric choices.

---

## Expanded Implementation Detail by Phase

Use this section as a hands-on build checklist. The earlier sections explain what each phase means; this section explains how to move through each phase in a practical order.

---

## Phase 1 Expanded Build Plan - Data Ingestion

### 1.1. EV Charging Ingestion Detailed Build Steps

**Step 1: Confirm configuration exists**

- Open `src/config.py`.
- Confirm it defines the AFDC endpoint, raw data directory, project root, today's date string, and California state abbreviation.
- Confirm `.env` contains `NREL_API_KEY`.
- Confirm `.env.example` shows the expected variable name but does not contain a real key.

**Step 2: Build the request**

- Create a request parameter dictionary with API key, fuel type, state, status, access, and limit.
- Keep this dictionary easy to print during debugging.
- Do not hard-code the API URL or key inside the ingest script.

**Step 3: Fetch and validate response**

- Send the request with a timeout so the script cannot hang forever.
- Immediately call response failure handling.
- Parse JSON only after the HTTP response succeeds.
- Pull the station list from the expected `fuel_stations` field.
- If the station list is missing or empty, fail loudly instead of saving empty files.

**Step 4: Save raw data**

- Save the full station list to JSON first.
- Save a flattened CSV second.
- Keep both outputs dated because AFDC changes over time.
- Print the exact paths after saving so the notebook can reference them.

**Step 5: Run EV QC**

- Count total stations.
- Count valid coordinates.
- Count non-California rows.
- Count access-code values.
- Sum Level 2 and DC fast ports separately.
- Print the date-last-confirmed range if available.

**Step 6: Expected result**

- You should see thousands of station records.
- Most records should have valid coordinates.
- Access codes should include public and private/restricted values because filtering has not happened yet.
- The raw CSV should be readable in Pandas without custom parsing.

### 1.2. Gas Station Ingestion Detailed Build Steps

**Step 1: Confirm the FeatureServer query endpoint**

- Use the layer query endpoint, not the human-readable ArcGIS layer page.
- Confirm the URL ends with `/FeatureServer/0/query`.
- Keep the URL in `src/config.py`.

**Step 2: Build one-page query first**

- Use `where=1=1`, `outFields=*`, `f=geojson`.
- Set `resultRecordCount` to the page size.
- Set `resultOffset` to zero.
- Verify the first response has a `features` list.

**Step 3: Add pagination**

- Wrap the query in a loop.
- Track `offset`.
- Add returned features into `all_features`.
- Stop when a page returns fewer records than the page size.
- Print progress on every page.

**Step 4: Save consolidated output**

- Rebuild a GeoJSON FeatureCollection from all features.
- Save it as a dated `.geojson` file.
- Flatten properties plus coordinates into a dated `.csv`.
- Keep all original source attributes, even if names are messy.

**Step 5: Run gas QC**

- Count total features.
- Count valid point geometries.
- Print min/max longitude and latitude.
- Confirm coordinates roughly fall within California.
- Print a few example property keys so you know which fields are available for cleaning.

**Step 6: Expected result**

- The script should fetch all pages, not just the first 2,000 records.
- The final GeoJSON should load in GeoPandas.
- The CSV should include longitude and latitude fields derived from geometry.

### 1.3. Census and Demographics Detailed Build Steps

**Step 1: Choose the spatial unit**

- Use Census tracts for the first full version because ACS data joins cleanly to tract GEOIDs.
- Keep H3 or hex grids as an optional extension, not the first implementation.

**Step 2: Store source files predictably**

- Put tract boundary files under `data/external/census_tracts/` or a similarly named folder.
- Put ACS tables under `data/external/acs/`.
- Avoid renaming source columns manually until the cleaning/join step.

**Step 3: Preserve GEOID integrity**

- Treat GEOID as text.
- Never allow GEOID to become an integer, because leading zeros can be lost.
- Check the GEOID length for California tracts.

**Step 4: Identify required ACS variables**

- Population is required for demand context.
- Median household income is useful for equity/context analysis.
- Vehicle availability, poverty, and commute variables are useful but optional.

**Step 5: Expected result**

- A tract geometry file with one row per California tract.
- A demographic table with a GEOID column and at least population and median income.
- A joinable key shared by both files.

### 1.4. Acquisition Notebook Detailed Structure

Build `notebooks/01_data_acquisition.ipynb` in this order:

1. **Setup cell**
   - Resolve project root.
   - Import config paths.
   - Import ingest functions.
   - Print project root and raw directory.

2. **Run ingestion cell**
   - Optionally run AFDC fetch/save/QC.
   - Optionally run gas fetch/save/QC.
   - If you do not want the notebook to re-download every time, make this cell clearly marked as "run only when refreshing raw data."

3. **Locate latest raw files cell**
   - Find latest AFDC CSV/JSON by filename date.
   - Find latest CEC CSV/GeoJSON by filename date.
   - Print selected file paths.

4. **Load raw files cell**
   - Load EV CSV with Pandas.
   - Load gas CSV with Pandas.
   - Load gas GeoJSON with GeoPandas if installed.
   - Load tracts and ACS if they exist.

5. **Coordinate QC cell**
   - Check California bounding ranges.
   - Print invalid coordinate counts.
   - Show the first few suspicious rows if any exist.

6. **Notebook conclusion cell**
   - Record whether Phase 1 passed.
   - List missing external files if Census or ACS data has not been downloaded yet.

---

## Phase 2 Expanded Build Plan - EDA and Cleaning

### 2.1. `clean_stations.py` Detailed Build Steps

**Step 1: Add latest-file helpers**

- Create logic to find the newest file matching `afdc_ev_stations_*.csv`.
- Create logic to find the newest file matching `cec_gas_stations_*.geojson`.
- Print the exact files being cleaned.
- Fail clearly if no matching raw files exist.

**Step 2: Clean EV attributes**

- Standardize column names into lowercase snake case if needed.
- Convert latitude and longitude to numeric.
- Convert port counts to numeric.
- Fill missing port counts with zero.
- Create a `total_ev_ports` field.
- Create a `has_dcfc` boolean.
- Keep source fields such as network, pricing, owner type, status, and date last confirmed.

**Step 3: Filter EV rows**

- Drop missing coordinates.
- Drop coordinates outside a broad California bounding box.
- Keep only California rows.
- Keep public-access rows in the primary processed output.
- Decide whether to keep only operational/open stations or keep status flexible. For v1, keeping status fields and documenting the choice is better than silently dropping useful rows.

**Step 4: Build EV geometry**

- Create point geometry from longitude and latitude.
- Assign CRS as **EPSG:4326**.
- Project to **EPSG:3310**.
- Save the processed layer.

**Step 5: Clean gas attributes**

- Load GeoJSON.
- Drop null geometries.
- Confirm all geometries are points.
- Project to **EPSG:3310**.
- Extract projected X/Y coordinates.
- Round X/Y to the nearest 10 meters.
- Drop duplicate rounded coordinate pairs.

**Step 6: Standardize gas schema**

- Map source-specific names to stable names.
- Preserve raw source ID if available.
- Add `source = "cec"`.
- Add source snapshot date parsed from the filename if practical.
- Save the processed layer.

**Step 7: Produce a cleaning report**

- Print raw EV count and cleaned EV count.
- Print raw gas count and cleaned gas count.
- Print number of dropped coordinate rows.
- Print number of gas duplicates removed.
- Print CRS for both outputs.

### 2.2. EDA Notebook Detailed Structure

Build `notebooks/02_eda_and_qc.ipynb` in this order:

1. **Load processed files**
   - Load EV and gas Parquet files.
   - Print CRS, row counts, and columns.

2. **Schema inspection**
   - Display data types.
   - Confirm required columns exist.
   - Confirm geometry columns are active.

3. **EV distribution analysis**
   - Count stations by network.
   - Count stations by status.
   - Summarize Level 2, DCFC, and total port counts.
   - Plot histograms for port counts.

4. **Gas station inspection**
   - Count records by city, ZIP, or available administrative field.
   - Inspect duplicate-removal impact.
   - Show rows with missing names or addresses.

5. **Spatial sanity checks**
   - Reproject both layers to **EPSG:4326** for plotting.
   - Plot points over a California boundary or simple coordinate extent.
   - Confirm no large clusters appear offshore or outside California.

6. **EDA conclusion**
   - State whether the data is ready for tract-level analysis.
   - List any known issues to carry forward.

---

## Phase 3 Expanded Build Plan - Charging Desert Analysis

### 3.1. `coverage_metrics.py` Detailed Build Steps

**Step 1: Load and align CRS**

- Load tracts, demographics, EV stations, and gas stations.
- Project tracts and point layers to **EPSG:3310**.
- Confirm all geometry operations happen in meters.

**Step 2: Prepare tract base**

- Keep tract GEOID and geometry.
- Join ACS fields onto tracts.
- Calculate tract area in square kilometers.
- Calculate population density.
- Flag zero-population and missing-population tracts.

**Step 3: Aggregate EV infrastructure**

- Spatially join EV stations to tracts.
- Group by tract GEOID.
- Count EV stations.
- Sum Level 2 ports.
- Sum DCFC ports.
- Sum total EV ports.
- Join these aggregates back to all tracts.
- Fill missing infrastructure counts with zero.

**Step 4: Aggregate gas infrastructure**

- Spatially join gas stations to tracts.
- Count gas stations per tract.
- Join counts back to all tracts.
- Fill missing gas counts with zero.

**Step 5: Calculate gas access near tract centroids**

- Create tract centroid geometries in **EPSG:3310**.
- Find gas stations within 2 kilometers of each centroid.
- Count nearby gas stations.
- Store as `gas_access_count_2km`.

**Step 6: Calculate nearest DCFC distance**

- Filter EV stations to records where `dcfc_ports > 0`.
- Use a spatial index or KD-tree for efficient nearest-neighbor distance.
- Calculate distance from each tract centroid to the nearest DCFC.
- Convert meters to kilometers.
- Store as `nearest_dcfc_km`.

**Step 7: Create final metric columns**

- Calculate EV ports per square kilometer.
- Calculate EV ports per 1,000 residents.
- Calculate DCFC ports per 1,000 residents.
- Preserve all raw count fields and derived density fields.

**Step 8: Save intermediate metrics**

- Save a tract metrics file before desert scoring.
- This makes debugging easier because metric generation and scoring are separate.

### 3.2. `desert_detection.py` Detailed Build Steps

**Step 1: Choose scoring inputs**

- Use `gas_access_count_2km` for existing gasoline access.
- Use `population_density` for affected population intensity.
- Use `ev_port_density` or `ev_ports_per_1000_people` for EV supply.
- Use `nearest_dcfc_km` for fast-charging access.

**Step 2: Normalize safely**

- For each metric, calculate min and max.
- If max equals min, assign a neutral normalized value.
- Clip normalized values between 0 and 1.
- Keep normalized component columns in the output for transparency.

**Step 3: Build the EV gap component**

- EV supply is good when higher, so desert pressure is the inverse.
- High EV port density should reduce the EV gap component.
- Zero EV ports should produce a high EV gap component.

**Step 4: Build the final score**

- Multiply each normalized component by its weight.
- Sum weighted components.
- Multiply by 100.
- Round to a sensible number of decimals, such as one or two.

**Step 5: Add severity labels**

- `severe_desert` for score >= 75.
- `moderate_desert` for score >= 50 and < 75.
- `adequate` for score < 50.
- Optionally add `low_population_flag` separately instead of hiding those tracts.

**Step 6: Save scored tracts**

- Save a processed tract file for reuse.
- Export a web GeoJSON version in **EPSG:4326**.

### 3.3. Charging Desert Notebook Detailed Structure

Build `notebooks/03_charging_deserts.ipynb` in this order:

1. **Load metric and scored tract layers**
   - Print row counts and CRS.
   - Confirm all required score columns exist.

2. **Score distribution**
   - Show descriptive statistics for desert score.
   - Plot a histogram of score values.
   - Count tracts by severity class.

3. **Component interpretation**
   - Plot or summarize each component.
   - Identify whether scores are mostly driven by EV gaps, population density, gas access, or DCFC distance.

4. **Map outputs**
   - Create a choropleth of desert score.
   - Create a severity map.
   - Inspect the top 15 severe tracts.

5. **Demographic context**
   - Compare desert score against median household income.
   - Compare desert score against population density.
   - Avoid making causal claims unless supported by the analysis.

6. **Export**
   - Save final charging desert GeoJSON.
   - Save optional summary CSVs.

---

## Phase 4 Expanded Build Plan - Conversion Candidate Scoring

### 4.1. `conversion_scoring.py` Detailed Build Steps

**Step 1: Load required layers**

- Load cleaned gas stations.
- Load cleaned EV stations.
- Load scored desert tracts.
- Optionally load highways and NEVI/planned charging layers.

**Step 2: Attach gas stations to tracts**

- Spatially join each gas station point to a Census tract.
- Bring in tract GEOID, desert score, population, and severity label.
- Handle gas stations that do not join to a tract by flagging them.

**Step 3: Calculate nearest DCFC distance**

- Filter EV stations to DCFC locations.
- Calculate nearest DCFC distance for each gas station.
- Cap distance score at 15 kilometers.

**Step 4: Calculate redundancy**

- Count other gas stations within 1 kilometer.
- Exclude the station itself from its nearby count.
- Convert nearby count into a penalty.

**Step 5: Calculate corridor or population context**

- If highway data exists, calculate distance to nearest major highway.
- Award corridor points for sites within 5 kilometers.
- If highway data does not exist, use tract population or population density only.

**Step 6: Apply score components**

- Local gap component: up to 30 points.
- DCFC distance component: up to 25 points.
- Population/corridor component: up to 20 points.
- Site suitability proxy: up to 15 points.
- Redundancy penalty: subtract up to 10 points.
- Planned infrastructure penalty: subtract up to 10 points.

**Step 7: Clamp and rank**

- Clamp final score to 0 through 100.
- Sort descending by final score.
- Add rank starting at 1.
- Keep component columns for review.

**Step 8: Generate rationale**

- Build a readable rationale from the strongest score drivers.
- Mention no more than two or three reasons per candidate.
- Avoid vague statements; use concrete facts like "12.4 km from nearest DCFC" or "severe desert tract."

### 4.2. Conversion Candidate Notebook Detailed Structure

Build `notebooks/04_conversion_candidates.ipynb` in this order:

1. **Load candidate output**
   - Print row count.
   - Confirm required columns.
   - Display top 20.

2. **Score review**
   - Plot final score distribution.
   - Show component columns for the top 50.
   - Check for ties or suspicious repeated values.

3. **Spatial review**
   - Map candidates over charging desert tracts.
   - Overlay existing DCFC stations.
   - Check whether top candidates are far enough from existing DCFC to make sense.

4. **Export**
   - Save top 50 candidates to CSV.
   - Save candidate GeoJSON if useful for mapping.

5. **Interpretation**
   - Summarize the strongest regions.
   - Identify any questionable top-ranked candidates needing manual review.

---

## Phase 5 Expanded Build Plan - Delivery and Visualizations

### 5.1. Sensitivity Notebook Detailed Build Steps

**Step 1: Define scenarios**

- Baseline weights.
- Higher EV gap weight.
- Higher DCFC distance weight.
- Larger gasoline access buffer.
- DCFC-only EV supply metric.

**Step 2: Re-run scoring under each scenario**

- Keep scenario names short and consistent.
- Save scores under scenario-specific column names.
- Avoid overwriting baseline outputs until the comparison is complete.

**Step 3: Compare tract severity**

- Count how many tracts change class.
- Count how many severe tracts stay severe.
- Map class changes if useful.

**Step 4: Compare candidate rankings**

- Re-score candidates under each scenario.
- Track top 20 and top 50 membership.
- Calculate average rank and top-N frequency.

**Step 5: Identify stable outputs**

- Mark candidates that appear in top 20 across most scenarios.
- Mark tracts that remain severe across most scenarios.
- Use these stable results in the final written findings.

### 5.2. Web Map Detailed Build Steps

**Step 1: Prepare map-ready layers**

- Reproject all layers to **EPSG:4326**.
- Simplify tract geometries if the GeoJSON is too large.
- Keep only map-needed columns to reduce file size.

**Step 2: Build choropleth**

- Use desert score as the color value.
- Use a clear color scale where high scores stand out.
- Include a legend.

**Step 3: Add infrastructure overlays**

- Add DCFC markers separately from Level 2 markers.
- Use marker clustering if there are too many points.
- Add top candidate markers with larger or more distinct styling.

**Step 4: Add popups**

- Keep popups short.
- Include candidate rank, score, address, nearest DCFC distance, and rationale.
- Avoid dumping every column into the popup.

**Step 5: Save and test**

- Save HTML map.
- Open it locally.
- Pan around urban and rural areas.
- Confirm layers are aligned and popups work.

### 5.3. Streamlit Dashboard Detailed Build Steps

**Step 1: Load data with caching**

- Cache expensive file loads.
- Load candidates, desert tracts, and optional EV station layers.

**Step 2: Build filters**

- Minimum candidate score.
- County or region.
- Severity class.
- Toggle EV station overlays.
- Toggle candidate overlays.

**Step 3: Build metric cards**

- Total candidates after filtering.
- Average or median score.
- Severe desert tracts visible.
- Median nearest DCFC distance.

**Step 4: Build map and table**

- Display filtered candidates on the map.
- Display filtered candidate table below the map.
- Add a CSV download button for the filtered table.

**Step 5: Handle missing files**

- If outputs are missing, show a clear message telling which phase must run first.
- Do not let the dashboard crash with a long traceback for normal missing-output cases.

### 5.4. Final Report Detailed Structure

Your final written summary should be short but specific:

1. **Data snapshot**
   - AFDC pull date.
   - CEC gas station source date or download date.
   - ACS year.

2. **Method**
   - One paragraph explaining tract metrics.
   - One paragraph explaining desert score.
   - One paragraph explaining candidate scoring.

3. **Findings**
   - Number of severe and moderate desert tracts.
   - Top counties or corridors.
   - Top conversion candidates.
   - Stable candidates from sensitivity analysis.

4. **Limitations**
   - Data freshness.
   - Straight-line distance.
   - Missing grid capacity and parcel feasibility.
   - Planned charging infrastructure incompleteness.

5. **Next steps**
   - Add drive-time analysis.
   - Add parcel/grid feasibility.
   - Add latest planned charging awards.
   - Compare tract results with H3 or another grid.

---

## Technical Guidance: How to Actually Implement Each Subphase

This section is the practical bridge between the plan and the code. Use it when you are sitting in a script or notebook and are unsure what operation comes next.

---

## Phase 1 Technical Guidance - Ingestion

### 1.1. EV Charging Ingestion: How to Implement `fetch_afdc.py`

At a technical level, this script does four things:

1. Build an API request.
2. Download JSON.
3. Save the raw response.
4. Flatten part of the response into CSV.

**Core Python tools**

- `requests.get()` for the API call.
- `response.raise_for_status()` to fail on HTTP errors.
- `response.json()` to parse JSON.
- `json.dump()` to save the raw data.
- `pandas.json_normalize()` to flatten nested station dictionaries.
- `Path.mkdir()` to ensure the output folder exists.

**Recommended function design**

Use three small functions instead of one large script:

```text
fetch_afdc_stations() -> list[dict]
save_raw(stations: list[dict]) -> tuple[Path, Path]
quality_control(stations: list[dict]) -> None
```

**How the fetch function should work**

1. Create a `params` dictionary.
2. Send `requests.get(AFDC_API_URL, params=params, timeout=60)`.
3. Call `raise_for_status()`.
4. Parse `payload = response.json()`.
5. Extract `stations = payload.get("fuel_stations", [])`.
6. Return `stations`.

**Why use `payload.get()` instead of direct indexing**

Direct indexing like `payload["fuel_stations"]` crashes if the API shape changes. Using `.get()` lets you return an empty list and then raise your own clearer error.

**How the save function should work**

1. Ensure `RAW_DIR` exists.
2. Build two filenames using `TODAY_STR`.
3. Save JSON with `json.dump(stations, file, indent=2)`.
4. Convert to a DataFrame with `pd.json_normalize(stations)`.
5. Keep only columns that actually exist.
6. Save CSV.

The "keep only columns that exist" detail matters because API fields can change. If you ask Pandas for a column that is missing, it raises a `KeyError`.

**How the QC function should work**

Convert the station list to a DataFrame and calculate:

- `len(df)` for row count.
- `df[["latitude", "longitude"]].dropna().shape[0]` for valid coordinate count.
- `df["access_code"].value_counts(dropna=False)` for public/private breakdown.
- `pd.to_numeric(df["ev_dc_fast_num"], errors="coerce").fillna(0).sum()` for DCFC ports.

**Common mistakes**

- Importing config with the wrong path. Since this script is inside `src/ingest/`, `config.py` is one folder above it.
- Saving only the flattened CSV and losing the original JSON.
- Filtering to public stations too early. Keep raw data broad; filter during cleaning.
- Assuming every station has all port-count fields.

**How to know this subphase is working**

Run the script from the project root. You should see:

- A fetched station count.
- Two saved files in `data/raw/`.
- A QC summary with valid coordinate percentage and access-code counts.

### 1.2. Gas Station Ingestion: How to Implement `fetch_gas_stations.py`

At a technical level, this script handles an ArcGIS REST API that limits how many features come back in one request.

**Core Python tools**

- `requests.get()` for each API page.
- A `while True` loop for pagination.
- `resultOffset` to move through pages.
- `json.dump()` to save the complete FeatureCollection.
- `pandas.DataFrame()` to save a flattened CSV.
- `time.sleep()` to avoid aggressive repeated requests.

**Why pagination is needed**

FeatureServers often cap results at around 2,000 records per request. If you only make one request, you may silently get an incomplete dataset.

**Pagination algorithm**

```text
all_features = []
offset = 0

while True:
    request one page using resultOffset = offset
    parse features
    add features to all_features
    if returned feature count < page_size:
        stop
    offset = offset + page_size
    sleep briefly
```

**How each request should be structured**

Use these query parameters:

- `where`: `1=1`
- `outFields`: `*`
- `f`: `geojson`
- `resultRecordCount`: page size
- `resultOffset`: current offset

**How to save GeoJSON correctly**

ArcGIS returns page-level GeoJSON-like responses. Your final saved file should be one valid FeatureCollection:

```text
{
  "type": "FeatureCollection",
  "features": all_features
}
```

**How to flatten to CSV**

Loop through each feature:

1. Copy `feature["properties"]`.
2. Get `feature["geometry"]["coordinates"]`.
3. Store coordinate index `0` as longitude.
4. Store coordinate index `1` as latitude.
5. Append the row dictionary to a list.
6. Convert the list to a DataFrame.

**Common mistakes**

- Forgetting `resultOffset`, which fetches only the first page.
- Treating coordinates as latitude, longitude. GeoJSON coordinates are longitude, latitude.
- Not checking for an `"error"` key in the ArcGIS JSON response.
- Saving a list of features without wrapping it in a FeatureCollection.

**How to know this subphase is working**

The console should show multiple offsets if the layer has more than one page. The saved GeoJSON should load with `geopandas.read_file()`.

### 1.3. Tracts and Demographics: How to Handle External Files

This subphase is less about API code and more about keeping join keys clean.

**Core Python tools**

- `geopandas.read_file()` for tract shapefiles or GeoJSON.
- `pandas.read_csv()` for ACS demographic tables.
- String operations with `.astype(str)` and `.str.zfill()` if needed.
- `DataFrame.merge()` to join demographics to tracts.

**The most important technical concept: GEOID**

Every tract has a GEOID. That GEOID is the key that lets you join Census geometry to Census demographics.

Treat GEOID as text. Do not treat it as a number.

**How to prepare tracts**

1. Load the tract file with GeoPandas.
2. Inspect columns.
3. Identify the GEOID column, often named `GEOID`.
4. Keep only California tracts if the file includes more than California.
5. Make sure the GEOID column is a string.

**How to prepare ACS demographics**

1. Load the CSV with Pandas.
2. Identify the tract ID column.
3. Clean the ID so it matches the tract GEOID format.
4. Rename unclear ACS variable codes to readable names like `population` and `median_household_income`.
5. Convert numeric columns with `pd.to_numeric(errors="coerce")`.

**How to test the join**

Use a left join from tracts to demographics:

```text
tracts.merge(demographics, on="geoid", how="left")
```

Then check how many tracts have missing population. If many are missing, the GEOID formats do not match.

**Common mistakes**

- Losing leading zeros in GEOIDs.
- Joining on tract names instead of GEOIDs.
- Mixing ACS years with mismatched tract boundary years.
- Forgetting that ACS variable names are often codes until you rename them.

### 1.4. Acquisition Notebook: How to Build It Technically

This notebook should not do complex analysis. Its job is to prove Phase 1 worked. Think of it as a smoke test for data acquisition: it should show that your raw files exist, can be loaded, have plausible row counts, have usable coordinates, and are ready for Phase 2 cleaning.

The notebook should answer these questions:

- Can the project imports load correctly from a notebook?
- Did the ingestion scripts create files in `data/raw/`?
- Which exact raw files are being used?
- Are the EV and gas datasets non-empty?
- Do the coordinate columns look like California coordinates?
- Are Census tracts and demographics available yet?
- What still needs to be fixed before moving to Phase 2?

**Core Python tools**

- `pathlib.Path` for file discovery.
- `pandas.read_csv()` for flat raw snapshots.
- `geopandas.read_file()` for GeoJSON and tract files.
- `DataFrame.shape`, `DataFrame.head()`, `DataFrame.info()`, and `DataFrame.describe()` for inspection.
- `Path.glob()` for finding dated raw files.
- Small helper functions for repeated checks.

**Recommended notebook structure**

Use separate cells. Do not put the whole notebook into one long cell. Short cells make it easier to see which step failed.

**Cell 1: Title and purpose**

Add a markdown cell that says what the notebook validates:

- AFDC EV charging raw files.
- CEC gas station raw files.
- Census tract files.
- ACS demographic files.
- Coordinate plausibility.

**Cell 2: Imports and project root**

- Use `Path.cwd()`.
- If current folder is `notebooks`, use `Path.cwd().parent`.
- Add the project root to `sys.path`.
- Import config values and ingest functions.
- Import `pandas` as `pd`.
- Import `geopandas` as `gpd` if installed.
- Print the resolved project root.
- Print `RAW_DIR` and `EXTERNAL_DIR`.

This cell catches path mistakes early. If this cell fails, the rest of the notebook cannot be trusted.

**Cell 3: Define small validation helpers**

Create tiny helpers conceptually like:

```text
latest_file(folder, pattern) -> Path
check_file_exists(path) -> None
check_nonempty_dataframe(df, name) -> None
check_coordinate_bounds(df, lon_col, lat_col, name) -> DataFrame
```

You do not need these helpers to be fancy. Their job is to keep the notebook readable.

**What `latest_file()` should do**

1. Use `folder.glob(pattern)` to find matching files.
2. Sort the matches.
3. Return the last match.
4. If no files exist, print a clear message telling which ingestion script to run.

Example patterns:

```text
afdc_ev_stations_*.csv
afdc_ev_stations_*.json
cec_gas_stations_*.csv
cec_gas_stations_*.geojson
```

**Cell 4: Optional data refresh**

This cell is where you can call the ingestion functions, but it should be easy to skip.

Recommended approach:

- Add a variable such as `RUN_REFRESH = False`.
- If `RUN_REFRESH` is true, run AFDC fetch/save/QC and gas fetch/save/QC.
- If false, print that the notebook is using existing raw files.

This matters because API calls take time, require internet access, and should not run every time you open the notebook.

**What the refresh cell should do if enabled**

For AFDC:

1. Call `fetch_afdc_stations()`.
2. Call `save_afdc_raw(stations)`.
3. Call `quality_control_afdc(stations)`.

For gas stations:

1. Call `fetch_gas()`.
2. Call `save_gas_raw(features)`.
3. Call `quality_control_gas(features)`.

**Cell 5: Find latest raw files**

Use `Path.glob()`:

```text
RAW_DIR.glob("afdc_ev_stations_*.csv")
RAW_DIR.glob("afdc_ev_stations_*.json")
RAW_DIR.glob("cec_gas_stations_*.csv")
RAW_DIR.glob("cec_gas_stations_*.geojson")
```

Sort the matches and take the latest file for each source.

Print a small table or list:

```text
EV CSV: path
EV JSON: path
Gas CSV: path
Gas GeoJSON: path
```

If a path is missing, that tells you exactly which ingestion script did not run.

**Cell 6: Load raw files**

Load each raw file into memory:

- AFDC CSV with `pd.read_csv()`.
- CEC CSV with `pd.read_csv()`.
- CEC GeoJSON with `gpd.read_file()`.

For the AFDC JSON, you can either:

- Load it with `json.load()` to verify it is valid JSON.
- Or skip loading it if the CSV is enough for the notebook.

After loading, print:

- Row count.
- Column count.
- First five column names.
- First few rows with `.head()`.

**Cell 7: EV raw data checks**

Check the AFDC CSV specifically:

- Does it have `latitude`?
- Does it have `longitude`?
- Does it have `state`?
- Does it have `access_code`?
- Does it have `ev_level2_evse_num`?
- Does it have `ev_dc_fast_num`?

Then calculate:

- Total EV rows.
- Rows with valid latitude and longitude.
- Percent valid coordinates.
- State value counts.
- Access-code value counts.
- Sum of Level 2 ports.
- Sum of DCFC ports.

**What good EV results look like**

- Most rows have latitude and longitude.
- State should be almost entirely or entirely `CA`.
- Access code should include public/private categories because raw ingestion intentionally fetched all access types.
- Port-count fields should be numeric or convertible to numeric.

**Cell 8: Gas raw data checks**

Check the CEC CSV and GeoJSON:

- CSV row count.
- GeoJSON feature count.
- Whether CSV and GeoJSON counts match.
- Whether longitude and latitude columns exist in the CSV.
- Whether GeoJSON has point geometry.
- Whether geometry CRS is present.

Then calculate:

- Valid gas coordinate count.
- Min/max longitude.
- Min/max latitude.
- Geometry type counts from the GeoJSON.

**What good gas results look like**

- CSV and GeoJSON should have the same number of records.
- Most or all gas records should have valid point geometry.
- Longitude should be negative.
- Latitude should be positive.
- Geometry type should usually be `Point`.

**Cell 9: Coordinate bounding-box checks**

Use broad California bounds:

- Longitude roughly between `-125` and `-113`.
- Latitude roughly between `32` and `43`.

Run this check for:

- EV raw CSV.
- Gas raw CSV.
- Gas GeoJSON after converting geometry to longitude/latitude if needed.

Create a small suspicious-row table for records outside the bounds. Do not automatically delete them in this notebook. Just inspect and report them.

**Why this matters**

This catches common problems:

- Latitude and longitude swapped.
- Missing coordinates encoded as zero.
- Bad geocoding.
- Non-California records that slipped through.

**Cell 10: External Census and ACS checks**

This cell checks whether manually downloaded external files are present.

Look inside `EXTERNAL_DIR` for:

- Tract boundary files.
- ACS demographic CSV files.

At this stage, the exact filenames may vary. The notebook can print what it finds instead of requiring a perfect filename.

For tract files:

- Try loading with `gpd.read_file()`.
- Print row count.
- Print CRS.
- Print geometry types.
- Print possible GEOID columns.

For ACS files:

- Load with `pd.read_csv()`.
- Print row count.
- Print possible GEOID columns.
- Print candidate population and income columns.

**If external files are missing**

Do not treat that as a Python error if you have not downloaded them yet. Instead, print a clear message:

```text
Missing Census tract file. Download tract boundaries before Phase 3.
Missing ACS demographics file. Download ACS data before Phase 3.
```

Phase 1 ingestion scripts can still be valid even if external files are not done yet, but you cannot complete Phase 3 without them.

**Cell 11: Simple visual spot check**

If GeoPandas plotting works:

- Plot gas station GeoJSON points.
- Plot EV points after creating temporary point geometry.
- Keep the plot simple.

This is not the final map. It is only a quick "do the points look like California?" check.

If plotting is annoying or dependencies are missing, skip the plot and rely on coordinate bounds for now.

**Cell 12: Phase 1 summary**

End the notebook with a small markdown or printed summary:

```text
Phase 1 status:
- AFDC raw CSV found: yes/no
- AFDC row count: number
- CEC raw GeoJSON found: yes/no
- CEC feature count: number
- EV coordinate pass rate: percent
- Gas coordinate pass rate: percent
- Census tracts available: yes/no
- ACS demographics available: yes/no
- Ready for Phase 2 cleaning: yes/no
```

This summary is the most important part of the notebook. It gives you a clear checkpoint before moving forward.

**Suggested pass/fail rules**

Mark Phase 1 as passing if:

- AFDC raw CSV exists and has rows.
- CEC raw GeoJSON exists and has rows.
- EV coordinate validity is high enough to proceed.
- Gas coordinate validity is high enough to proceed.
- Coordinates are broadly within California.

Mark Phase 1 as incomplete if:

- Raw files are missing.
- Either raw file has zero rows.
- Coordinate columns are missing.
- GeoJSON cannot be loaded.
- Most coordinates fall outside California.

**Common mistakes in this notebook**

- Running API refresh every time and accidentally creating many duplicate snapshots.
- Using notebook-relative paths like `"../data/raw"` everywhere instead of importing paths from `src/config.py`.
- Assuming the newest file is correct without printing its path.
- Treating missing Census files as a code failure when they may simply not have been downloaded yet.
- Doing cleaning in this notebook. Save cleaning for Phase 2.

**What this notebook should not do**

- It should not deduplicate gas stations.
- It should not filter public EV stations.
- It should not project to **EPSG:3310**.
- It should not calculate desert scores.
- It should not produce final outputs.

Those steps belong in later phases. The acquisition notebook only proves that the raw ingredients are present and plausible.

---

## Phase 2 Technical Guidance - Cleaning

### 2.1. Cleaning Pipeline: How to Implement `clean_stations.py`

This script is where raw data becomes analysis-ready data.

**Core Python tools**

- `pandas.read_csv()`
- `geopandas.read_file()`
- `geopandas.points_from_xy()`
- `GeoDataFrame.to_crs()`
- `GeoDataFrame.to_parquet()`
- `dropna()`, `query()`, `assign()`, `groupby()`, `drop_duplicates()`

**Recommended function design**

```text
latest_file(pattern: str) -> Path
clean_ev_stations(raw_path: Path) -> GeoDataFrame
clean_gas_stations(raw_path: Path) -> GeoDataFrame
main() -> None
```

**How to clean EV stations technically**

1. Load raw CSV.
2. Normalize important column names if needed.
3. Convert `latitude` and `longitude` to numeric.
4. Drop rows where either coordinate is missing.
5. Filter to California rows.
6. Filter to public access.
7. Convert port columns to numeric.
8. Fill missing port columns with zero.
9. Create total ports.
10. Create geometry.
11. Assign CRS as **EPSG:4326**.
12. Project to **EPSG:3310**.
13. Save to Parquet.

**Coordinate cleaning logic**

Use two checks:

- Missing coordinate check: latitude or longitude is null.
- Bounding-box check: coordinate is outside California's rough extent.

The bounding-box check catches swapped coordinates, zeros, and bad geocodes.

**Public-access filtering**

Look at `access_code`. Usually the value you want is `public`.

Do not guess blindly. Print value counts first, then filter. If values include mixed capitalization, normalize with lowercase strings.

**Port-count conversion**

Use numeric conversion with coercion:

```text
pd.to_numeric(column, errors="coerce").fillna(0)
```

This prevents strings or blanks from breaking the math.

**How to create EV geometry**

Use longitude for X and latitude for Y:

```text
geometry = geopandas.points_from_xy(df["longitude"], df["latitude"])
```

Then create a GeoDataFrame with CRS **EPSG:4326**.

**How to clean gas stations technically**

1. Load raw GeoJSON with GeoPandas.
2. Drop missing geometries.
3. Project to **EPSG:3310**.
4. Extract projected coordinates from geometry.
5. Round coordinates to a 10-meter grid.
6. Drop duplicate rounded coordinate pairs.
7. Rename source columns to standard output columns.
8. Save to Parquet.

**How 10-meter deduping works**

After projection to **EPSG:3310**, coordinates are in meters. If you round X and Y to the nearest 10 meters, stations at essentially the same location collapse to the same rounded coordinate pair.

Use that rounded pair as a duplicate key.

**Common mistakes**

- Doing distance or dedupe calculations in latitude/longitude degrees.
- Creating geometry with latitude as X and longitude as Y.
- Saving processed data in **EPSG:4326** and then accidentally measuring distances in degrees later.
- Dropping useful raw columns too early.

### 2.2. EDA Notebook: How to Use It Technically

The EDA notebook should answer, "Do the cleaned files make sense?"

**Technical checks to include**

- `ev.crs` and `gas.crs`
- `len(ev)` and `len(gas)`
- `ev.geometry.is_valid.mean()`
- `gas.geometry.is_valid.mean()`
- `ev["total_ev_ports"].describe()`
- `ev["dcfc_ports"].describe()`
- `ev["network"].value_counts().head()`, if network exists

**Spatial plotting approach**

For simple plotting:

1. Reproject to **EPSG:4326**.
2. Use `.plot()` for a quick static view.
3. Use small marker sizes because there are many stations.

For more interactive inspection:

- Use `.explore()` if GeoPandas has Folium support installed.
- Or save a quick sample to GeoJSON and view it externally.

**What suspicious results look like**

- Points forming a vertical or horizontal line.
- Points near `(0, 0)`.
- California points showing up in the ocean.
- DCFC port counts that are negative or implausibly huge.
- Cleaned row count much smaller than expected.

---

## Phase 3 Technical Guidance - Charging Desert Metrics

### 3.1. Coverage Metrics: How to Implement `coverage_metrics.py`

This is the most important technical phase. You are aggregating point data into tract polygons.

**Core Python tools**

- `geopandas.sjoin()` for point-in-polygon joins.
- `GeoDataFrame.to_crs()` for projection.
- `geometry.area` for tract area.
- `geometry.centroid` for tract centroids.
- `scipy.spatial.cKDTree` or GeoPandas spatial index for nearest-neighbor distances.
- `groupby()` for tract-level aggregation.

**Recommended function design**

```text
load_inputs() -> tuple[GeoDataFrame, GeoDataFrame, GeoDataFrame, DataFrame]
prepare_tracts(tracts, demographics) -> GeoDataFrame
aggregate_ev_by_tract(ev, tracts) -> DataFrame
aggregate_gas_by_tract(gas, tracts) -> DataFrame
calculate_nearest_dcfc(tracts, ev) -> Series
build_coverage_metrics() -> GeoDataFrame
```

**How point-in-polygon aggregation works**

You spatially join points to polygons:

```text
joined = geopandas.sjoin(points, tracts[["geoid", "geometry"]], predicate="within")
```

After the join, each point has the GEOID of the tract it falls inside. Then you group by GEOID.

**EV aggregation**

After joining EV points to tracts:

- Count station IDs for `ev_station_count`.
- Sum `level2_ports`.
- Sum `dcfc_ports`.
- Sum `total_ev_ports`.

Join those results back to the tract GeoDataFrame.

**Gas aggregation**

After joining gas points to tracts:

- Count station IDs for `gas_station_count`.

Join that result back to the tract GeoDataFrame.

**Why fill missing counts with zero**

If a tract has no EV station, it will not appear in the grouped result. After joining back to all tracts, that tract will have null count values. Those nulls should become zero because the tract truly has zero joined stations.

**How to calculate tract area**

Project tracts to **EPSG:3310** first. Then:

```text
tract_area_sq_km = geometry.area / 1_000_000
```

Do not calculate area in **EPSG:4326**.

**How to calculate nearest DCFC**

Filter EV stations to DC fast chargers:

```text
dcfc = ev[ev["dcfc_ports"] > 0]
```

Then use tract centroids and DCFC point coordinates in **EPSG:3310**.

Conceptually:

1. Create an array of DCFC X/Y coordinates.
2. Create an array of tract centroid X/Y coordinates.
3. Build a KD-tree from DCFC coordinates.
4. Query the tree with centroid coordinates.
5. Convert returned meters to kilometers.

**Why use a KD-tree**

A naive approach compares every tract to every DCFC. That is slow. A KD-tree finds nearest points much faster.

**How to calculate gas access within 2 km**

There are two good approaches:

1. Buffer each tract centroid by 2,000 meters and spatially join gas stations within those buffers.
2. Use a spatial index or KD-tree to count nearby gas station points.

The buffer method is easier to understand. The KD-tree method is faster.

**Common mistakes**

- Joining tracts to points backwards and losing tracts with zero stations.
- Calculating nearest distances before projecting to **EPSG:3310**.
- Forgetting to fill missing station counts with zero.
- Using all EV stations for nearest DCFC instead of only DCFC stations.

### 3.2. Desert Detection: How to Implement `desert_detection.py`

This script should take a tract metrics table and add scores.

**Core Python tools**

- Pandas arithmetic.
- `clip()` to keep values in range.
- `numpy.where()` or a small classification function.

**Recommended function design**

```text
normalize(series) -> Series
inverse_normalize(series) -> Series
score_deserts(metrics, weights) -> GeoDataFrame
classify_score(score) -> str
```

**How normalization works**

For a numeric column:

```text
normalized = (value - min_value) / (max_value - min_value)
```

This turns the smallest value into 0 and the largest value into 1.

**How inverse normalization works**

For EV supply, lower values are worse. So:

```text
ev_gap = 1 - normalize(ev_port_density)
```

That means a tract with very low EV density gets a high gap score.

**How to handle division by zero**

If every value in a column is the same, `max - min` is zero. In that case, return a neutral component such as `0.5` for all rows.

**How to classify**

Use ordered thresholds:

1. Score >= 75: severe.
2. Score >= 50: moderate.
3. Otherwise: adequate.

Order matters. Check the highest threshold first.

**Common mistakes**

- Subtracting DCFC distance from the desert score. Farther from DCFC should make the desert score worse, so it should add pressure.
- Normalizing columns that contain nulls without handling them.
- Combining raw metrics with different scales without normalizing.
- Hiding component columns, which makes the score hard to explain.

### 3.3. Charging Desert Notebook: How to Diagnose Results

The notebook should not only show a map. It should help you decide whether the scoring logic is credible.

**Technical checks**

- Confirm `desert_score.min()` is at least 0.
- Confirm `desert_score.max()` is at most 100.
- Confirm severity labels are not all one category.
- Display the top 20 tracts by score with component columns.
- Plot each component distribution.

**Map checks**

Look at:

- Los Angeles basin.
- Bay Area.
- Central Valley.
- Inland Empire.
- Rural northern California.
- Eastern Sierra/desert areas.

If all severe tracts are giant rural areas with very low population, consider adding a population flag or reporting rural and urban rankings separately.

---

## Phase 4 Technical Guidance - Candidate Scoring

### 4.1. Conversion Scoring: How to Implement `conversion_scoring.py`

This phase scores gas stations. Technically, it is similar to Phase 3, but the output unit is a gas station point instead of a tract polygon.

**Core Python tools**

- `geopandas.sjoin()` to attach tract scores to gas stations.
- KD-tree nearest-neighbor logic for distance to DCFC.
- Buffer or KD-tree logic for nearby gas station counts.
- Pandas arithmetic for score components.
- `sort_values()` and rank assignment.

**Recommended function design**

```text
attach_tract_context(gas, desert_tracts) -> GeoDataFrame
calculate_nearest_dcfc_for_sites(gas, ev) -> Series
calculate_gas_redundancy(gas, radius_m=1000) -> Series
score_candidates(gas_with_context) -> GeoDataFrame
build_rationale(row) -> str
```

**How to attach tract context**

Spatially join gas station points to desert tract polygons:

```text
gas_with_tract = geopandas.sjoin(gas, tracts, predicate="within")
```

Keep only tract columns you need:

- GEOID.
- Desert score.
- Severity class.
- Population.
- EV port density.
- Nearest DCFC for the tract, if useful.

**How to score local charging gap**

If desert score is already 0 to 100, convert it to a 0-to-30 component:

```text
local_gap_points = desert_score / 100 * 30
```

**How to score nearest DCFC distance**

If the cap is 15 km:

```text
dcfc_distance_points = min(nearest_dcfc_km, 15) / 15 * 25
```

This gives zero points to a site at 0 km and full points to a site 15 km or farther from DCFC.

**How to score population/corridor context**

For v1 without highway data:

- Normalize tract population or population density.
- Multiply by 20.

For v2 with highway data:

- Give part of the 20 points for population.
- Give part for being near a highway.

Example concept:

```text
population_points = normalized_population * 12
highway_points = 8 if highway_distance_km <= 5 else smaller scaled value
```

**How to calculate redundancy penalty**

Count other gas stations within 1 km.

Then convert count to penalty:

- 0 or 1 nearby stations: no penalty.
- 2 nearby stations: small penalty.
- 3 or more nearby stations: larger penalty, capped at 10.

Always cap the penalty so it cannot dominate the entire score.

**How to calculate planned-infrastructure penalty**

If NEVI/planned charger points exist:

- Calculate distance from gas site to nearest planned charger.
- If within 3 km, subtract up to 10 points.
- If no planned layer exists, set penalty to zero and include a note in limitations.

**How to build final score**

```text
final_score =
    local_gap_points
  + dcfc_distance_points
  + population_corridor_points
  + site_suitability_points
  - redundancy_penalty
  - planned_infrastructure_penalty
```

Then clamp:

```text
final_score = max(0, min(100, final_score))
```

**How to build the rationale field**

Use the component values to create a short explanation.

Example logic:

- If severity is severe, mention severe desert tract.
- If nearest DCFC is greater than 10 km, mention far from DCFC.
- If population component is high, mention populated tract.
- If redundancy penalty is low, mention limited nearby gas redundancy.

**Common mistakes**

- Ranking gas stations before filtering invalid geometries.
- Forgetting to exclude the gas station itself from nearby gas station counts.
- Letting penalties produce negative final scores.
- Outputting only final score and losing component explainability.

### 4.2. Conversion Notebook: How to Review Candidate Quality

**Technical checks**

- Confirm `final_score` is between 0 and 100.
- Confirm ranks are unique.
- Confirm top 50 have valid lat/lon.
- Confirm top 50 are not all from one dense city unless that result is explainable.
- Inspect candidates with high score but very high redundancy penalty.

**Useful tables**

- Top 50 candidates.
- Top candidates by county.
- Average score by county.
- Candidates in severe tracts.
- Candidates farther than 10 km from DCFC.

**Useful plots**

- Histogram of final scores.
- Scatter of desert score vs. nearest DCFC distance.
- Map of top candidates over desert tracts.

---

## Phase 5 Technical Guidance - Delivery

### 5.1. Sensitivity Analysis: How to Implement It

Sensitivity analysis means rerunning the score with changed assumptions and comparing the results.

**Core Python tools**

- Dictionaries to define scenarios.
- Loops to run each scenario.
- `merge()` to compare scenario outputs.
- Rank columns to track movement.

**How to define scenarios**

Create a list or dictionary like:

```text
baseline: normal weights
ev_gap_high: higher EV gap weight
dcfc_high: higher DCFC distance weight
gas_buffer_5km: larger gas access buffer
dcfc_only_supply: EV supply measured only by DCFC
```

**How to compare candidates**

For each scenario:

1. Produce a ranked candidate table.
2. Keep station ID, score, and rank.
3. Rename score and rank columns with scenario name.
4. Merge all scenarios on station ID.

Then calculate:

- How many scenarios each candidate appears in the top 20.
- Average rank.
- Worst rank.
- Rank standard deviation.

**What stable means technically**

A candidate is stable if it appears near the top under several reasonable assumptions. For example:

- Appears in top 20 in at least 4 of 5 scenarios.
- Or appears in top 50 in all scenarios.

### 5.2. Map Generator: How to Implement `maps.py`

**Core Python tools**

- `folium.Map`
- `folium.Choropleth`
- `folium.GeoJson`
- `folium.CircleMarker`
- `folium.LayerControl`
- `GeoDataFrame.to_crs("EPSG:4326")`

**Technical map sequence**

1. Load charging desert GeoJSON.
2. Load candidate CSV or GeoJSON.
3. Reproject spatial data to **EPSG:4326**.
4. Create a Folium map centered on California.
5. Add tract choropleth.
6. Add EV charger markers.
7. Add candidate markers.
8. Add layer control.
9. Save HTML.

**Performance guidance**

If the map is slow:

- Keep only needed columns.
- Simplify tract geometries.
- Show only top 50 candidates.
- Cluster EV stations.
- Do not put every gas station on the map by default.

### 5.3. Streamlit App: How to Implement `streamlit_app.py`

**Core Python tools**

- `streamlit` for UI.
- `pandas` and `geopandas` for loading data.
- `st.cache_data` for caching.
- `st.sidebar` for filters.
- `st.dataframe()` for tables.
- `st.download_button()` for CSV export.

**Technical app layout**

1. Load data with cached functions.
2. Show sidebar filters.
3. Apply filters to the candidate table.
4. Show summary metrics.
5. Show map.
6. Show filtered table.
7. Provide download button.

**Missing file handling**

Before loading, check whether required files exist. If not, show a message like:

```text
Run Phases 1-4 first. Missing: outputs/tables/conversion_candidates.csv
```

This is better than letting Streamlit crash.

### 5.4. Final Report: How to Write It from the Outputs

The report should be generated from actual numbers, not memory.

**Technical workflow**

1. Load `charging_deserts.geojson`.
2. Count severity classes.
3. Load `conversion_candidates.csv`.
4. Pull top 10 candidates.
5. Load sensitivity outputs.
6. Identify stable candidates.
7. Write findings using those computed values.

**Avoid unsupported claims**

Say:

- "Based on this scoring method..."
- "Using straight-line distance..."
- "In the current AFDC snapshot..."

Avoid:

- "This site is definitely feasible."
- "This tract has no charging access at all" unless your data supports that exact claim.
- "This is the best investment" without grid, ownership, zoning, and cost data.
