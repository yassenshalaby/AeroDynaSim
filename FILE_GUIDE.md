# Lap Time Simulator — Complete File Guide

A full rundown of every file and folder in the project, what it does, and what language it's written in.

---

## Root Directory (`/Desktop/grad/`)

### Core Application Files

| File                       | Language | Description                              |
|----------------------------|----------|------------------------------------------|
| `app.py`                   | Python   | The main Flask web server application    |
| `aero_laptime_pipeline.py` | Python   | Original standalone pipeline script      |
| `app_v1_backup.py`         | Python   | Backup of the first version of app.py    |

- **`app.py`** — Powers the entire Lap Time Simulator. Contains: the 23 geometric parameter definitions, the `BODY_TYPE_SPECS` vehicle physics profiles for Sedan/Wagon/Fastback, the `load_drivaernet_data()` CSV parser, the `params_to_aero_coeffs()` KNN/IDW algorithm, `generate_ini_file()` for building temporary vehicle configs, `run_single_simulation()` for calling the physics engine, and all API routes (`/api/templates`, `/api/simulate`, `/api/tracks`, etc.).
- **`aero_laptime_pipeline.py`** — The first version of the project before the web app was built. Runs a complete aerodynamic lap time simulation from the command line without a UI. Kept for reference.
- **`app_v1_backup.py`** — The original Flask app that used F1/Formula E car templates with direct Cd/Cl sliders instead of geometric parameters. Kept as a rollback safety net.

### Dataset Files

| File                                     | Format | Description                                |
|------------------------------------------|--------|--------------------------------------------|
| `DrivAerNetPlusPlus_CarDesign_Areas.csv`  | CSV    | Frontal projected areas for 8,008 designs  |
| `DrivAerNetPlusPlus_Cd_8k_Updated.csv`   | CSV    | CFD drag coefficients for 8,122 designs    |

- **`DrivAerNetPlusPlus_CarDesign_Areas.csv`** — Contains car design IDs and their exact frontal projected areas in m². Used by `load_frontal_areas()` in `app.py` to dynamically calculate the true frontal area for each matched car instead of using a hard-coded baseline.
- **`DrivAerNetPlusPlus_Cd_8k_Updated.csv`** — Contains car design IDs and their CFD-simulated drag values (Cd). A supplementary data source from the DrivAerNet++ extended dataset.

### Documentation

| File                | Format   | Description                                  |
|---------------------|----------|----------------------------------------------|
| `PROJECT_NOTES.md`  | Markdown | Q&A knowledge base (12 detailed questions)   |
| `METHODOLOGIES.md`  | Markdown | Academic methodology report                  |
| `FILE_GUIDE.md`     | Markdown | This file — complete project file reference   |

### System Files (Auto-Generated)

| File/Folder      | Description                                            |
|------------------|--------------------------------------------------------|
| `.venv/`         | Python virtual environment (Flask, NumPy, etc.)        |
| `__pycache__/`   | Python bytecode cache                                  |
| `.DS_Store`      | macOS Finder metadata                                  |

---

## `static/` — Frontend Assets

All files served directly to the browser.

| File                 | Language   | Description                              |
|----------------------|------------|------------------------------------------|
| `app.js`             | JavaScript | Main frontend logic                      |
| `style.css`          | CSS        | Complete visual design / dark theme      |
| `three.min.js`       | JavaScript | Three.js 3D library (third-party)        |
| `OrbitControls.js`   | JavaScript | Three.js camera controls (third-party)   |
| `app_v1_backup.js`   | JavaScript | Backup of the first frontend version     |

- **`app.js`** — Handles all UI interactions: tab navigation, rendering body type cards, rendering 23 parameter sliders by category, managing saved presets, calling `/api/simulate`, displaying results in the comparison table, and rendering the 2D track visualization on a `<canvas>` element.
- **`style.css`** — Premium dark racing theme with red accents, glassmorphism effects, gradient backgrounds, smooth animations, and responsive layout. Styles every component: header, tabs, cards, sliders, results table, track canvas, loading overlay, and modals.
- **`three.min.js`** — Third-party Three.js library (r128). Provides the WebGL-powered 3D viewport in the Customize tab. Minified production build — not our code.
- **`OrbitControls.js`** — Third-party Three.js plugin. Lets users click-and-drag to rotate, zoom, and pan the 3D camera. Not our code.
- **`app_v1_backup.js`** — Original app.js that used F1/Formula E templates with direct aero coefficient sliders. Kept as a rollback.

---

## `templates/` — HTML Templates

Served by Flask's Jinja2 template engine.

| File                     | Language | Description                              |
|--------------------------|----------|------------------------------------------|
| `index.html`             | HTML     | The main (and only) page                 |
| `index_v1_backup.html`   | HTML     | Backup of the first UI version           |

- **`index.html`** — Defines the full UI structure: the "LAP TIME SIMULATOR" header, 4-tab navigation bar (Body Type, Customize, Track, Results), body type selection grid, parameter sliders + 3D viewport + presets layout, track selection grid, results table + track visualization canvas, loading overlay with progress bar, and preset save modal.
- **`index_v1_backup.html`** — The original step-based wizard layout with F1/FE car cards. Kept as a safety net.

---

## `DrivAerNet-main/` — Aerodynamic Research Dataset

The DrivAerNet++ open-source dataset from Mohamed Elrefaie et al. (Harvard Dataverse).

### Root Files

| File                      | Format   | Description                                |
|---------------------------|----------|--------------------------------------------|
| `README.md`               | Markdown | Dataset documentation                      |
| `LICENSE`                  | Text     | Creative Commons license                   |
| `SUBMISSION_GUIDELINES.md` | Markdown | Dataset contribution guidelines            |
| `requirements.txt`        | Text     | Python deps for DrivAerNet scripts         |

### `ParametricModels/` — The Core Data

| File                                | Language | Description                                |
|-------------------------------------|----------|--------------------------------------------|
| `DrivAerNet_ParametricData.csv`     | CSV      | Primary dataset — 4,165 designs × 30 cols  |
| `AutoML_parametric.py`              | Python   | AutoML regression script (not used)        |
| `projected_frontal_area_in_m2.py`   | Python   | Frontal area calculator (not used)         |
| `align_grids_on_cutline.py`         | Python   | Mesh grid alignment script (not used)      |
| `morph_box_load_elements.py`        | Python   | Mesh morphing script (not used)            |

- **`DrivAerNet_ParametricData.csv`** — **THE primary dataset.** Each row is a unique car design with an experiment ID (e.g. `N_S_WWC_WM_001`), 23 geometric parameters (car length, roof height, trunk angle, mirror rotation, bumper curvature, etc.), and 8 CFD-simulated aerodynamic coefficients (Average Cd, Cl_f, Cl_r, and standard deviations). This is what our KNN algorithm searches through.

### Other DrivAerNet Subfolders (Reference Only)

| Folder                      | Description                                            |
|-----------------------------|--------------------------------------------------------|
| `DeepSurrogates/`           | Deep learning surrogate models (not used)              |
| `DrivAerNet_v1/`            | Original v1 DrivAerNet codebase (not used)             |
| `RegDGCNN_SurfaceFields/`   | Graph neural network for surface fields (not used)     |
| `mlcroissant/`              | ML metadata standard files (not used)                  |
| `train_val_test_splits/`    | Predefined ML train/val/test splits (not used)         |
| `tutorials/`                | Jupyter notebook tutorials (not used)                  |

---

## `laptime-simulation-master/` — Physics Simulation Engine

An open-source lap time simulator by TUMFTM (Technical University of Munich).

### Root Files

| File                   | Language | Description                                  |
|------------------------|----------|----------------------------------------------|
| `main_laptimesim.py`   | Python   | Simulation entry point — called by app.py    |
| `main_opt_raceline.py` | Python   | Raceline optimiser (not used)                |
| `test_laptimesim.py`   | Python   | Unit tests for the simulation engine         |
| `requirements.txt`     | Text     | Dependencies: NumPy, SciPy, Matplotlib       |
| `README.md`            | Markdown | Documentation for the simulation engine      |
| `LICENSE`              | Text     | LGPL-3.0 license                             |
| `setup.cfg`            | INI      | Python package configuration                 |

### `laptimesim/src/` — The Physics Core

| File              | Language | Description                                     |
|-------------------|----------|-------------------------------------------------|
| `lap.py`          | Python   | Heart of the engine — full lap simulation loop  |
| `car.py`          | Python   | Vehicle dynamics model                          |
| `car_hybrid.py`   | Python   | Hybrid powertrain model                         |
| `car_electric.py` | Python   | Electric powertrain model (not used)            |
| `track.py`        | Python   | Track parser and curvature calculator           |
| `driver.py`       | Python   | Virtual driver behaviour model                  |
| `__init__.py`     | Python   | Package initialiser                             |

- **`lap.py`** — (56 KB) Iterates over every track segment, calculates drag force, downforce, tire grip, max acceleration, braking points, cornering speeds, energy management, and produces the final velocity profile and lap time. Uses Newton's F=ma at every point.
- **`car.py`** — Parses the `.ini` vehicle file, calculates engine torque curves, gear ratios, tire friction circles, weight distribution. This is where `c_w_a`, `c_z_a_f`, `c_z_a_r` (our DrivAerNet aero values) become actual drag/downforce in Newtons.
- **`car_hybrid.py`** — Extends `car.py` with hybrid electric motor logic: energy recovery, electric boost deployment, battery state management. All three body types use this.
- **`track.py`** — Reads track coordinates from `racelines/`, interpolates the racing line, calculates curvature at every point, applies weather conditions.
- **`driver.py`** — Simulates corner speed margins, DRS usage, yellow flag response, lift-and-coast strategy, and energy management.

### `laptimesim/input/vehicles/` — Vehicle Templates

| File                                | Format | Description                                 |
|-------------------------------------|--------|---------------------------------------------|
| `F1_Shanghai.ini`                   | INI    | Reference F1 hybrid template (not used)     |
| `FE_Berlin.ini`                     | INI    | Reference Formula E template (not used)     |
| `Preset_001_N_S_WWC_WM_407.ini`     | INI    | Generated Sedan preset (#407 aero)          |
| `Preset_002_E_S_WWC_WM_171.ini`     | INI    | Generated Wagon preset (#171 aero)          |
| `Preset_003_E_S_WW_WM_700.ini`      | INI    | Generated Wagon variant preset (#700 aero)  |

### `laptimesim/input/tracks/` — Track Data

| File/Folder        | Format     | Description                                   |
|--------------------|------------|-----------------------------------------------|
| `track_pars.ini`   | INI        | Configuration for all 24 circuits             |
| `racelines/`       | CSV files  | 24 racing line coordinate files (X/Y/width)   |
| `maps/`            | PNG images | 24 track satellite/layout images              |

---

## Language Summary

| Language       | Files              | Used For                                              |
|----------------|--------------------|-------------------------------------------------------|
| **Python**     | 15+                | Backend server, simulation engine, vehicle dynamics   |
| **JavaScript** | 3 (+ 2 libraries)  | Frontend UI, sliders, 3D viewport, track canvas       |
| **HTML**       | 1                  | Page structure and layout                             |
| **CSS**        | 1                  | Visual styling and animations                         |
| **CSV**        | 3+                 | Aerodynamic datasets (params, Cd, frontal areas)      |
| **INI**        | 6+                 | Vehicle physics templates and track configuration     |
| **Markdown**   | 4+                 | Documentation, project notes, methodology             |

---

## Data Flow Summary

```
User moves sliders (app.js)
       ↓
POST /api/simulate (app.py)
       ↓
params_to_aero_coeffs() — KNN search across DrivAerNet_ParametricData.csv
       ↓                   + frontal area from DrivAerNetPlusPlus_CarDesign_Areas.csv
       ↓
generate_ini_file() — merges BODY_TYPE_SPECS + custom Cd/Cl into temp .ini
       ↓
main_laptimesim.main() — physics engine reads .ini + track raceline CSV
       ↓
lap.py iterates F=ma at every track segment
       ↓
Returns: lap time, velocity profile, track coordinates
       ↓
Frontend renders results table + 2D track visualisation
```

---

_Last Updated: 2026-04-04_
