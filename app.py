#!/usr/bin/env python3
"""
AeroDynaSim v2 — Flask Backend with Real Car Customization
Interactive Aerodynamics Lap Time Simulation App
"""

import os
import sys
import csv
import json
import types
import uuid
import pickle
import numpy as np
import math
from flask import Flask, render_template, jsonify, request, send_from_directory

# -------------------------------------------------------------------------------------
# PATHS & SETUP
# -------------------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAPTIME_DIR = os.path.join(SCRIPT_DIR, "laptime-simulation-master")
VEHICLES_DIR = os.path.join(LAPTIME_DIR, "laptimesim", "input", "vehicles")
TRACKS_DIR = os.path.join(LAPTIME_DIR, "laptimesim", "input", "tracks")
RACELINES_DIR = os.path.join(TRACKS_DIR, "racelines")
DRIVAERNET_CSV = os.path.join(SCRIPT_DIR, "DrivAerNet-main", "ParametricModels",
                              "DrivAerNet_ParametricData.csv")

# One STL per body type — maps body_code -> absolute path of the .stl file
STL_MESH_MAP = {
    "N": os.path.join(SCRIPT_DIR, "ns", "N_S_WWC_WM", "N_S_WWC_WM_001.stl"),
    "E": os.path.join(SCRIPT_DIR, "ns", "E_S_WWC_WM", "E_S_WWC_WM_005.stl"),
    "F": os.path.join(SCRIPT_DIR, "ns", "F_S_WWC_WM", "F_S_WWC_WM_001.stl"),
}

# Mock quadprog (binary incompatibility with Python 3.14)
_qp_mock = types.ModuleType("quadprog")
_qp_mock.solve_qp = lambda *a, **k: None
sys.modules["quadprog"] = _qp_mock

# Add laptime sim to path
sys.path.insert(0, LAPTIME_DIR)

app = Flask(__name__, template_folder="templates", static_folder="static")

@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# -------------------------------------------------------------------------------------
# GEOMETRIC PARAMETER DEFINITIONS
# -------------------------------------------------------------------------------------

# 23 geometric parameters with readable names, categories, and aerodynamic impact.
# cd_impact = actual Cd range (max_bin_avg - min_bin_avg across 5 percentile bins)
# calculated from all 4,165 CFD simulations — captures both linear and non-linear effects.
PARAM_DEFS = [
    # Body Basics (4 params)
    {"key": "A_Car_Length",            "name": "Car Length",           "unit": "mm", "category": "Body",     "cd_impact": 0.0057},
    {"key": "A_Car_Width",             "name": "Car Width",            "unit": "mm", "category": "Body",     "cd_impact": 0.0068},
    {"key": "A_Car_Roof_Height",       "name": "Roof Height",          "unit": "mm", "category": "Body",     "cd_impact": 0.0033},
    {"key": "A_Car_Green_House_Angle", "name": "Greenhouse Angle",     "unit": "°",  "category": "Body",     "cd_impact": 0.0030},

    # Exterior Styling (6 params)
    {"key": "B_Ramp_Angle",            "name": "Underbody Ramp Angle", "unit": "°",  "category": "Exterior", "cd_impact": 0.0090},
    {"key": "B_Diffusor_Angle",        "name": "Diffusor Angle",       "unit": "°",  "category": "Exterior", "cd_impact": 0.0236},
    {"key": "B_Trunklid_Angle",        "name": "Trunk Lid Angle",      "unit": "°",  "category": "Exterior", "cd_impact": 0.0020},
    {"key": "G_Trunklid_Curvature",    "name": "Trunk Lid Curvature",  "unit": "",   "category": "Exterior", "cd_impact": 0.0036},
    {"key": "G_Trunklid_Length",       "name": "Trunk Lid Length",     "unit": "mm", "category": "Exterior", "cd_impact": 0.0092},
    {"key": "E_Fenders_Arch_Offset",   "name": "Fender Arch Offset",   "unit": "mm", "category": "Exterior", "cd_impact": 0.0244},

    # Windows & Roof (5 params)
    {"key": "D_Rear_Window_Inclination","name": "Rear Window Angle",   "unit": "°",  "category": "Windows",  "cd_impact": 0.0073},
    {"key": "D_Rear_Window_Length",    "name": "Rear Window Length",   "unit": "mm", "category": "Windows",  "cd_impact": 0.0079},
    {"key": "D_Winscreen_Inclination", "name": "Windscreen Angle",     "unit": "°",  "category": "Windows",  "cd_impact": 0.0032},
    {"key": "D_Winscreen_Length",      "name": "Windscreen Length",    "unit": "mm", "category": "Windows",  "cd_impact": 0.0043},
    {"key": "E_A_B_C_Pillar_Thickness","name": "Pillar Thickness",     "unit": "mm", "category": "Windows",  "cd_impact": 0.0197},

    # Mirrors (3 params)
    {"key": "C_Side_Mirrors_Rotation",    "name": "Mirror Rotation",   "unit": "°",  "category": "Mirrors",  "cd_impact": 0.0024},
    {"key": "C_Side_Mirrors_Translate_X", "name": "Mirror X Position", "unit": "mm", "category": "Mirrors",  "cd_impact": 0.0023},
    {"key": "C_Side_Mirrors_Translate_Z", "name": "Mirror Z Position", "unit": "mm", "category": "Mirrors",  "cd_impact": 0.0019},

    # Bumpers & Details (5 params)
    {"key": "H_Front_Bumper_Curvature", "name": "Front Bumper Curve",     "unit": "",   "category": "Details", "cd_impact": 0.0040},
    {"key": "H_Front_Bumper_Length",    "name": "Front Bumper Length",    "unit": "mm", "category": "Details", "cd_impact": 0.0036},
    {"key": "F_Door_Handles_Thickness", "name": "Door Handle Thickness",  "unit": "mm", "category": "Details", "cd_impact": 0.0015},
    {"key": "F_Door_Handles_X_Position","name": "Door Handle X Pos",      "unit": "mm", "category": "Details", "cd_impact": 0.0031},
    {"key": "F_Door_Handles_Z_Position","name": "Door Handle Z Pos",      "unit": "mm", "category": "Details", "cd_impact": 0.0031},
]

# Actual min/max values computed from DrivAerNet_ParametricData.csv (all 4,165 designs)
PARAM_RANGES = {
    "A_Car_Length":              (-60,   130),
    "A_Car_Width":               (-60,   150),
    "A_Car_Roof_Height":         (-60,    90),
    "A_Car_Green_House_Angle":  (-200,   150),
    "B_Ramp_Angle":               (-8,    15),
    "B_Diffusor_Angle":           (-8,    15),
    "B_Trunklid_Angle":           (-8,    20),
    "G_Trunklid_Curvature":     (-0.4,   0.8),
    "G_Trunklid_Length":         (-40,    40),
    "E_Fenders_Arch_Offset":     (-25,    55),
    "D_Rear_Window_Inclination": (-1.8,   2.5),
    "D_Rear_Window_Length":      (-95,   150),
    "D_Winscreen_Inclination":   (-1.8,   2.5),
    "D_Winscreen_Length":        (-50,    50),
    "E_A_B_C_Pillar_Thickness":  (-15,     5),
    "C_Side_Mirrors_Rotation":   (-20,    20),
    "C_Side_Mirrors_Translate_X":(-10,    20),
    "C_Side_Mirrors_Translate_Z": (-5,    10),
    "H_Front_Bumper_Curvature":  (-0.4,   1.0),
    "H_Front_Bumper_Length":     (-25,    60),
    "F_Door_Handles_Thickness":  (-20,    30),
    "F_Door_Handles_X_Position": (-50,    50),
    "F_Door_Handles_Z_Position": (-30,    30),
}

# Per-parameter standard deviations from the dataset — used for KNN distance normalization
# so every parameter has equal influence regardless of its physical unit or scale
PARAM_STDS = {
    "A_Car_Length":               55.0,
    "A_Car_Width":                61.0,
    "A_Car_Roof_Height":          43.0,
    "A_Car_Green_House_Angle":   102.0,
    "B_Ramp_Angle":                6.6,
    "B_Diffusor_Angle":            6.7,
    "B_Trunklid_Angle":            8.1,
    "G_Trunklid_Curvature":        0.35,
    "G_Trunklid_Length":          20.6,
    "E_Fenders_Arch_Offset":      23.1,
    "D_Rear_Window_Inclination":   1.23,
    "D_Rear_Window_Length":       70.7,
    "D_Winscreen_Inclination":     1.24,
    "D_Winscreen_Length":         28.9,
    "E_A_B_C_Pillar_Thickness":    5.8,
    "C_Side_Mirrors_Rotation":    11.6,
    "C_Side_Mirrors_Translate_X":  8.6,
    "C_Side_Mirrors_Translate_Z":  4.3,
    "H_Front_Bumper_Curvature":    0.41,
    "H_Front_Bumper_Length":      24.5,
    "F_Door_Handles_Thickness":   14.4,
    "F_Door_Handles_X_Position":  28.9,
    "F_Door_Handles_Z_Position":  17.3,
}

# Cd adjustments for categorical parameters derived from DrivAerNetPlusPlus matched-pair analysis
WHEELS_CD_DELTA = {
    "WWC":  0.0000,   # Closed cover — dataset baseline
    "WW":   0.0006,   # Open detailed   (+0.2%, n=1069 matched pairs)
    "WWS": -0.0039,   # Open smooth     (-1.4%, n=1017 matched pairs)
}

# Smooth underbody = baseline for all 4,165 original designs.
# Detailed underbody delta estimated from F-body avg Cd diff (smooth WWC vs detailed WW)
# minus wheel contribution: 0.2732 - 0.2463 - 0.0006 ≈ +0.0263
UNDERBODY_CD_DELTA = {
    "S":  0.0000,   # Smooth — dataset baseline
    "D":  0.0263,   # Detailed (adds flow complexity under body)
}

# -------------------------------------------------------------------------------------
# ML SURROGATE — Gradient Boosting (sklearn HistGradientBoostingRegressor)
# -------------------------------------------------------------------------------------
# Trained once at startup on the parametric CSV.
# Provides smooth, accurate dCd/dparam gradients for sensitivity bars and suggestions.
# Falls back to KNN regression if training fails.

MODELS_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
GB_MODELS    = {}      # body_code -> fitted HistGradientBoostingRegressor
GB_AVAILABLE = False   # Set True at startup if training succeeds
PARAM_KEYS   = [p["key"] for p in PARAM_DEFS]   # stable column order for ML


# -------------------------------------------------------------------------------------
# DATA LOADING
# -------------------------------------------------------------------------------------

def load_drivaernet_data():
    """Load full DrivAerNet dataset with all parameters."""
    data = []
    with open(DRIVAERNET_CSV, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    return data


def train_or_load_gb_models():
    """Train sklearn HistGradientBoostingRegressor models for each body type, or load
    from disk cache.  Cache is invalidated when the CSV is newer than the pkl.

    Populates global GB_MODELS dict {body_code: model}.
    Returns True on success, False if training fails for any reason.
    """
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
    except ImportError:
        print("[ML] sklearn not available — falling back to KNN sensitivity")
        return False

    os.makedirs(MODELS_DIR, exist_ok=True)
    csv_mtime = os.path.getmtime(DRIVAERNET_CSV)
    data = load_drivaernet_data()

    for body_code in ["N", "E", "F"]:
        pkl_path = os.path.join(MODELS_DIR, f"gb_cd_{body_code}.pkl")

        # Load from cache if valid
        if os.path.exists(pkl_path) and os.path.getmtime(pkl_path) > csv_mtime:
            with open(pkl_path, "rb") as fh:
                GB_MODELS[body_code] = pickle.load(fh)
            print(f"[ML] Loaded cached model for body type {body_code}")
            continue

        # Filter designs for this body type
        rows = [r for r in data if r.get("Experiment", "").startswith(body_code + "_")]
        if len(rows) < 50:
            print(f"[ML] Not enough data for {body_code} ({len(rows)} rows) — skipping")
            continue

        # Build feature matrix (23 params) and target vector (Cd)
        X = []
        y = []
        for row in rows:
            try:
                x_row = [float(row.get(k, 0)) for k in PARAM_KEYS]
                cd_val = float(row["Average Cd"])
                X.append(x_row)
                y.append(cd_val)
            except (ValueError, KeyError):
                continue

        X = np.array(X)
        y = np.array(y)

        model = HistGradientBoostingRegressor(
            max_iter=400,
            max_depth=6,
            learning_rate=0.05,
            min_samples_leaf=10,
            l2_regularization=0.1,
            random_state=42,
        )
        model.fit(X, y)

        with open(pkl_path, "wb") as fh:
            pickle.dump(model, fh)

        GB_MODELS[body_code] = model
        print(f"[ML] Trained gradient boosting model for {body_code} on {len(y)} samples "
              f"| train R²={model.score(X, y):.4f}")

    return len(GB_MODELS) > 0


def gb_sensitivity(params, body_code="N"):
    """Compute per-parameter dCd sensitivity using finite differences on the GB model.

    For each parameter, nudge it by 2% of its range while holding others fixed,
    predict the resulting Cd change, and scale by the full parameter range.

    Sign convention matches existing KNN sensitivity:
      negative value = increasing the parameter lowers Cd (faster)
      positive value = increasing the parameter raises Cd (slower)

    Returns dict {param_key: signed_delta_cd} or None if model unavailable.
    """
    model = GB_MODELS.get(body_code)
    if model is None:
        return None

    base_vec = np.array([[params.get(k, 0.0) for k in PARAM_KEYS]], dtype=float)
    base_cd  = float(model.predict(base_vec)[0])

    sensitivity = {}
    for i, key in enumerate(PARAM_KEYS):
        lo, hi = PARAM_RANGES.get(key, (-100, 100))
        param_range = hi - lo
        step = 0.02 * param_range
        if abs(step) < 1e-9:
            sensitivity[key] = 0.0
            continue

        perturbed = base_vec.copy()
        perturbed[0, i] += step
        perturbed_cd = float(model.predict(perturbed)[0])
        dCd_dparam = (perturbed_cd - base_cd) / step
        sensitivity[key] = round(dCd_dparam * param_range, 5)

    return sensitivity


def sensitivity_to_seconds(local_sensitivity, cd, lap_time=None):
    """Convert per-parameter dCd sensitivity values to estimated lap time delta (seconds).

    Physics basis:
      Aerodynamic drag accounts for ~40% of total resistance on a mixed circuit.
      dT ≈ dCd * (lap_time * 0.40 / cd)
      delta_cd < 0 (less drag)  →  delta_seconds < 0  (faster)  ✓

    Args:
        local_sensitivity: dict {param_key: signed_dCd_times_range}
        cd:                current drag coefficient
        lap_time:          simulated lap time in seconds (default 90.0)

    Returns dict {param_key: delta_seconds}
    """
    if lap_time is None or lap_time <= 0:
        lap_time = 90.0
    if cd <= 0:
        cd = 0.30
    dT_per_dCd = (lap_time * 0.40) / cd   # positive constant
    return {key: round(val * dT_per_dCd, 3) for key, val in local_sensitivity.items()}


def _startup_train():
    """Called once at module load to train or restore ML models."""
    global GB_AVAILABLE
    try:
        GB_AVAILABLE = train_or_load_gb_models()
        if GB_AVAILABLE:
            print(f"[ML] Models ready: {list(GB_MODELS.keys())}")
        else:
            print("[ML] No models available — using KNN sensitivity fallback")
    except Exception as exc:
        print(f"[ML] Startup training error: {exc} — using KNN fallback")
        GB_AVAILABLE = False


_startup_train()


def get_body_type_representative(body_code):
    """Get a representative design for a given body type."""
    data = load_drivaernet_data()
    for row in data:
        exp = row["Experiment"]
        if exp.startswith(body_code + "_"):
            # Extract geometric parameters
            params = {}
            for param_def in PARAM_DEFS:
                key = param_def["key"]
                params[key] = float(row.get(key, 0))
            
            return {
                "experiment_id": exp,
                "body_code": body_code,
                "cd": round(float(row["Average Cd"]), 4),
                "cl_f": round(float(row["Average Cl_f"]), 4),
                "cl_r": round(float(row["Average Cl_r"]), 4),
                "params": params,
            }
    return None


def load_car_templates():
    """Load DrivAerNet body types as templates."""
    body_types = {
        "N": {"name": "Sedan", "icon": "🚗"},
        "E": {"name": "Wagon", "icon": "🚙"},
        "F": {"name": "Fastback", "icon": "🏎️"},
    }
    
    templates = []
    for code, info in body_types.items():
        rep = get_body_type_representative(code)
        if rep:
            templates.append({
                "body_code": code,
                "name": info["name"],
                "icon": info["icon"],
                "experiment_id": rep["experiment_id"],
                "cd": rep["cd"],
                "cl_f": rep["cl_f"],
                "cl_r": rep["cl_r"],
                "params": rep["params"],
            })
    
    return templates


def load_tracks():
    """Load all available track names and basic info."""
    tracks = []
    for f in sorted(os.listdir(RACELINES_DIR)):
        if f.endswith(".csv") and not f.startswith("."):
            name = f.replace(".csv", "")
            coords = load_track_coords(name, simplified=True)
            tracks.append({
                "name": name,
                "points": len(coords),
                "preview": coords,
            })
    return tracks


def load_track_coords(track_name, simplified=False):
    """Load track XY coordinates from CSV."""
    filepath = os.path.join(RACELINES_DIR, f"{track_name}.csv")
    coords = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    coords.append([float(parts[0]), float(parts[1])])
                except ValueError:
                    continue
    if simplified and len(coords) > 200:
        step = max(1, len(coords) // 200)
        coords = coords[::step]
    return coords


def experiment_folder(experiment_id):
    """
    Extract folder name from experiment ID.
    E.g. 'N_S_WWC_WM_001' -> 'N_S_WWC_WM'
         'F_D_WM_WW_001'  -> 'F_D_WM_WW'
    Works by stripping the trailing _NNN number suffix.
    """
    parts = experiment_id.split('_')
    # Last part is always the 3-digit number
    return '_'.join(parts[:-1])


def config_folder_prefix(body_code, underbody='S', wheels='WWC'):
    """
    Build the expected folder/experiment prefix from body + underbody + wheels.
    Smooth:   {body}_S_{wheels}_WM   e.g. N_S_WWC_WM
    Detailed: F_D_WM_WW              (only Fastback has detailed underbody)
    """
    b = body_code.upper()
    if underbody == 'D' and b == 'F':
        return 'F_D_WM_WW'
    # For smooth underbody, map wheels code to dataset naming
    wheels_map = {'WWC': 'WWC', 'WW': 'WW', 'WWS': 'WWS'}
    w = wheels_map.get(wheels, 'WWC')
    return f"{b}_S_{w}_WM"


def find_closest_design(params, body_code=None, underbody='S', wheels='WWC'):
    """
    Find the closest DrivAerNet design based on geometric parameters.
    Filters by body type, underbody, and wheel configuration.
    Returns the design's Cd, Cl_f, Cl_r values, and experiment ID.
    """
    data = load_drivaernet_data()

    prefix = config_folder_prefix(body_code or 'N', underbody, wheels) + '_'

    min_distance = float('inf')
    closest_design = None

    for row in data:
        exp = row.get("Experiment", "")
        # Filter to only designs matching the exact body+underbody+wheels config
        if not exp.startswith(prefix):
            continue

        # Normalised Euclidean distance in parameter space
        distance = 0
        for param_def in PARAM_DEFS:
            key = param_def["key"]
            try:
                design_val = float(row.get(key, 0))
                user_val = params.get(key, design_val)
                norm = PARAM_STDS.get(key, 50.0)
                distance += ((design_val - user_val) / norm) ** 2
            except (ValueError, TypeError):
                continue

        distance = distance ** 0.5
        if distance < min_distance:
            min_distance = distance
            closest_design = row

    if closest_design:
        return {
            "cd": round(float(closest_design["Average Cd"]), 4),
            "cl_f": round(float(closest_design["Average Cl_f"]), 4),
            "cl_r": round(float(closest_design["Average Cl_r"]), 4),
            "experiment_id": closest_design["Experiment"],
        }

    # Fallback — try again with just body code (ignore underbody/wheels)
    for row in data:
        if body_code and not row.get("Experiment", "").startswith(body_code.upper() + "_"):
            continue
        return {
            "cd": round(float(row["Average Cd"]), 4),
            "cl_f": round(float(row["Average Cl_f"]), 4),
            "cl_r": round(float(row["Average Cl_r"]), 4),
            "experiment_id": row["Experiment"],
        }

    return {"cd": 0.30, "cl_f": -0.05, "cl_r": 0.05, "experiment_id": "default"}


def load_drivaernet_summary():
    """Load DrivAerNet data summary for the UI."""
    designs = []
    data = load_drivaernet_data()
    for row in data:
        designs.append({
            "id": row["Experiment"],
            "cd": round(float(row["Average Cd"]), 4),
            "cl_f": round(float(row["Average Cl_f"]), 4),
            "cl_r": round(float(row["Average Cl_r"]), 4),
        })
    return designs


# -------------------------------------------------------------------------------------
# SIMULATION ENGINE
# -------------------------------------------------------------------------------------

# Realistic vehicle profiles for each body type
BODY_TYPE_SPECS = {
    "N": {  # Sedan (Notchback) — mid-range road car (e.g. BMW 3 Series, Mercedes C-Class)
        "name": "Sedan",
        "frontal_area": 2.16,
        "veh_pars": {
            "powertrain_type": "hybrid",
            "general": {
                "lf": 1.40, "lr": 1.45, "h_cog": 0.52,
                "sf": 1.55, "sr": 1.54,
                "m": 1500.0,
                "f_roll": 0.012,
                "c_w_a": 0.60,
                "c_z_a_f": 0.0,
                "c_z_a_r": 0.0,
                "g": 9.81, "rho_air": 1.225, "drs_factor": 0.0,
            },
            "engine": {
                "topology": "RWD",
                "pow_max": 200e3,
                "pow_diff": 20e3,
                "n_begin": 4500.0, "n_max": 6000.0, "n_end": 6800.0,
                "be_max": 30.0,
                "pow_e_motor": 10e3, "eta_e_motor": 0.9, "eta_e_motor_re": 0.15,
                "eta_etc_re": 0.10, "vel_min_e_motor": 27.777, "torque_e_motor_max": 50.0,
            },
            "gearbox": {
                "i_trans": [0.075, 0.120, 0.160, 0.200, 0.245, 0.290, 0.340, 0.400],
                "n_shift": [6500.0, 6500.0, 6500.0, 6500.0, 6500.0, 6500.0, 6500.0, 7000.0],
                "e_i": [1.14, 1.10, 1.08, 1.07, 1.07, 1.06, 1.06, 1.06],
                "eta_g": 0.94,
            },
            "tires": {
                "f": {"circ_ref": 2.04, "fz_0": 4500.0, "mux": 1.05, "muy": 1.00,
                      "dmux_dfz": -3.5e-5, "dmuy_dfz": -3.5e-5},
                "r": {"circ_ref": 2.04, "fz_0": 4500.0, "mux": 1.10, "muy": 1.05,
                      "dmux_dfz": -3.5e-5, "dmuy_dfz": -3.5e-5},
                "tire_model_exp": 1.7,
            },
        },
    },
    "E": {  # Wagon (Estate) — family estate (e.g. Audi A4 Avant, Volvo V60)
        "name": "Wagon",
        "frontal_area": 2.35,
        "veh_pars": {
            "powertrain_type": "hybrid",
            "general": {
                "lf": 1.38, "lr": 1.50, "h_cog": 0.55,
                "sf": 1.55, "sr": 1.54,
                "m": 1650.0,
                "f_roll": 0.013,
                "c_w_a": 0.70,
                "c_z_a_f": 0.0,
                "c_z_a_r": 0.0,
                "g": 9.81, "rho_air": 1.225, "drs_factor": 0.0,
            },
            "engine": {
                "topology": "AWD",
                "pow_max": 180e3,
                "pow_diff": 18e3,
                "n_begin": 4200.0, "n_max": 5800.0, "n_end": 6500.0,
                "be_max": 32.0,
                "pow_e_motor": 10e3, "eta_e_motor": 0.9, "eta_e_motor_re": 0.15,
                "eta_etc_re": 0.10, "vel_min_e_motor": 27.777, "torque_e_motor_max": 50.0,
            },
            "gearbox": {
                "i_trans": [0.078, 0.125, 0.165, 0.205, 0.250, 0.295, 0.345, 0.410],
                "n_shift": [6200.0, 6200.0, 6200.0, 6200.0, 6200.0, 6200.0, 6200.0, 6800.0],
                "e_i": [1.14, 1.10, 1.08, 1.07, 1.07, 1.06, 1.06, 1.06],
                "eta_g": 0.93,
            },
            "tires": {
                "f": {"circ_ref": 2.08, "fz_0": 5000.0, "mux": 1.02, "muy": 0.98,
                      "dmux_dfz": -3.5e-5, "dmuy_dfz": -3.5e-5},
                "r": {"circ_ref": 2.08, "fz_0": 5000.0, "mux": 1.07, "muy": 1.02,
                      "dmux_dfz": -3.5e-5, "dmuy_dfz": -3.5e-5},
                "tire_model_exp": 1.7,
            },
        },
    },
    "F": {  # Fastback — sports car (e.g. Porsche 911, BMW M4)
        "name": "Fastback",
        "frontal_area": 2.05,
        "veh_pars": {
            "powertrain_type": "hybrid",
            "general": {
                "lf": 1.35, "lr": 1.40, "h_cog": 0.46,
                "sf": 1.58, "sr": 1.60,
                "m": 1350.0,
                "f_roll": 0.010,
                "c_w_a": 0.56,
                "c_z_a_f": 0.0,
                "c_z_a_r": 0.0,
                "g": 9.81, "rho_air": 1.225, "drs_factor": 0.0,
            },
            "engine": {
                "topology": "RWD",
                "pow_max": 280e3,
                "pow_diff": 25e3,
                "n_begin": 5000.0, "n_max": 6800.0, "n_end": 7500.0,
                "be_max": 28.0,
                "pow_e_motor": 10e3, "eta_e_motor": 0.9, "eta_e_motor_re": 0.15,
                "eta_etc_re": 0.10, "vel_min_e_motor": 27.777, "torque_e_motor_max": 50.0,
            },
            "gearbox": {
                "i_trans": [0.065, 0.105, 0.140, 0.180, 0.220, 0.265, 0.310, 0.370],
                "n_shift": [7000.0, 7000.0, 7000.0, 7000.0, 7000.0, 7000.0, 7000.0, 7800.0],
                "e_i": [1.15, 1.10, 1.08, 1.07, 1.07, 1.06, 1.06, 1.06],
                "eta_g": 0.95,
            },
            "tires": {
                "f": {"circ_ref": 2.00, "fz_0": 4000.0, "mux": 1.20, "muy": 1.15,
                      "dmux_dfz": -4.0e-5, "dmuy_dfz": -4.0e-5},
                "r": {"circ_ref": 2.04, "fz_0": 4200.0, "mux": 1.30, "muy": 1.25,
                      "dmux_dfz": -4.0e-5, "dmuy_dfz": -4.0e-5},
                "tire_model_exp": 1.8,
            },
        },
    },
}


# -------------------------------------------------------------------------------------
# Frontal Area Lookup
# -------------------------------------------------------------------------------------

FRONTAL_AREAS_CACHE = None

def load_frontal_areas():
    global FRONTAL_AREAS_CACHE
    if FRONTAL_AREAS_CACHE is not None:
        return FRONTAL_AREAS_CACHE
        
    areas = {}
    csv_path = os.path.join(SCRIPT_DIR, "DrivAerNetPlusPlus_CarDesign_Areas.csv")
    if os.path.exists(csv_path):
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    exp_id = row.get("Car Design")
                    area_val = row.get("Frontal Area (m²)")
                    if exp_id and area_val:
                        areas[exp_id] = float(area_val)
                except:
                    pass
    FRONTAL_AREAS_CACHE = areas
    return areas

def params_to_aero_coeffs(params, body_code="N", underbody="S", wheels="WWC"):
    """Convert geometric parameters to Cd/Cl values using actual Inverse Distance Weighting (K-Nearest Neighbors) from the dataset."""
    data = load_drivaernet_data()
    frontal_areas = load_frontal_areas()
    
    # Filter for the selected Body Type (N, E, or F)
    relevant = [row for row in data if row["Experiment"].startswith(body_code + "_")]
    if not relevant:
        relevant = data
        
    distances = []
    
    # Normalize each parameter by its dataset std so all parameters contribute equally
    for row in relevant:
        dist = 0.0
        for param_def in PARAM_DEFS:
            key = param_def["key"]
            try:
                design_val = float(row.get(key, 0))
                user_val = params.get(key, design_val)
                norm = PARAM_STDS.get(key, 50.0)
                dist += ((design_val - user_val) / norm) ** 2
            except (ValueError, TypeError):
                continue
        distances.append((math.sqrt(dist), row))

    distances.sort(key=lambda x: x[0])
    
    # Interpolate using Inverse Distance Weighting on the Top 7 nearest designs
    cd_num, cl_f_num, cl_r_num, area_num = 0.0, 0.0, 0.0, 0.0
    weight_sum = 0.0
    
    default_area = BODY_TYPE_SPECS.get(body_code, BODY_TYPE_SPECS["N"])["frontal_area"]
    
    for dist, row in distances[:7]:
        w = 1.0 / (dist + 1e-5)  # Epsilon to prevent division by zero
        cd_num += float(row["Average Cd"]) * w
        cl_f_num += float(row["Average Cl_f"]) * w
        cl_r_num += float(row["Average Cl_r"]) * w
        
        # Pull mathematically perfect Frontal Area from CSV if possible
        exp_id = row["Experiment"]
        actual_area = frontal_areas.get(exp_id, default_area)
        area_num += actual_area * w
        
        weight_sum += w
        
    final_cd = cd_num / weight_sum + UNDERBODY_CD_DELTA.get(underbody, 0.0) + WHEELS_CD_DELTA.get(wheels, 0.0)
    final_cl_f = cl_f_num / weight_sum
    final_cl_r = cl_r_num / weight_sum
    final_area = area_num / weight_sum

    # --- Local sensitivity from the 64 nearest neighbours ---
    # 64 ≈ √4165 — enough points for a stable per-parameter regression while
    # staying local enough to reflect the current slider position and interactions.
    # The sign is preserved: positive = increasing this param raises Cd (slower),
    # negative = increasing this param lowers Cd (faster).
    top64 = distances[:64]
    weights64 = [1.0 / (d + 1e-5) for d, _ in top64]
    w_sum64 = sum(weights64)
    w_cd64  = [float(row["Average Cd"]) for _, row in top64]
    mu_cd64 = sum(wt * c for wt, c in zip(weights64, w_cd64)) / w_sum64

    local_sensitivity = {}
    for param_def in PARAM_DEFS:
        key = param_def["key"]
        w_pk = [float(row.get(key, 0)) for _, row in top64]
        mu_pk = sum(wt * v for wt, v in zip(weights64, w_pk)) / w_sum64
        cov = sum(weights64[i] * (w_pk[i] - mu_pk) * (w_cd64[i] - mu_cd64)
                  for i in range(len(top64))) / w_sum64
        var = sum(weights64[i] * (w_pk[i] - mu_pk) ** 2
                  for i in range(len(top64))) / w_sum64
        slope = cov / (var + 1e-9)   # dCd/d(param) — signed
        lo, hi = PARAM_RANGES.get(key, (-100, 100))
        # Signed: positive = bad (more drag), negative = good (less drag)
        local_sensitivity[key] = round(slope * (hi - lo), 5)

    # --- Prediction confidence ---
    # Based on distance to nearest CFD design in normalised parameter space.
    # Scale: sqrt(23) ≈ 4.8 = distance if every param is 1 std-dev off.
    # score 0-100: 100 = exact match to a real design, 0 = very far away.
    dist_nearest = distances[0][0] if distances else 9999.0
    dist_mean64  = sum(d for d, _ in top64) / len(top64)
    confidence_score = max(0, min(100, round((1.0 - dist_nearest / 6.0) * 100)))
    if confidence_score >= 65:
        confidence_level = "high"
    elif confidence_score >= 35:
        confidence_level = "medium"
    else:
        confidence_level = "low"

    return {
        "c_w_a": max(0.1, final_cd) * final_area,
        "c_z_a_f": final_cl_f * final_area,
        "c_z_a_r": final_cl_r * final_area,
        "cd": round(final_cd, 4),
        "cl_f": round(final_cl_f, 4),
        "cl_r": round(final_cl_r, 4),
        "frontal_area": round(final_area, 4),
        "local_sensitivity": local_sensitivity,
        "confidence_score": confidence_score,
        "confidence_level": confidence_level,
        "dist_nearest": round(dist_nearest, 3),
        "dist_mean64": round(dist_mean64, 3),
    }


def generate_ini_file(body_code, params, underbody="S", wheels="WWC"):
    """Generate a temporary .ini file with body-type-specific mechanical properties
    and aero coefficients derived from geometric parameters."""
    import copy
    spec = BODY_TYPE_SPECS.get(body_code, BODY_TYPE_SPECS["N"])
    veh_pars = copy.deepcopy(spec["veh_pars"])

    # Convert geometric params + categorical options to aero coefficients
    aero = params_to_aero_coeffs(params, body_code, underbody, wheels)
    
    veh_pars["general"]["c_w_a"] = round(aero["c_w_a"], 4)
    veh_pars["general"]["c_z_a_f"] = round(aero["c_z_a_f"], 4)
    veh_pars["general"]["c_z_a_r"] = round(aero["c_z_a_r"], 4)

    # Create temp file in vehicles dir
    filename = f"_tmp_{uuid.uuid4().hex[:8]}.ini"
    filepath = os.path.join(VEHICLES_DIR, filename)

    content = f"# Auto-generated by AeroDynaSim v2\n[VEH_PARS]\nveh_pars={json.dumps(veh_pars)}\n"
    with open(filepath, "w") as f:
        f.write(content)

    return filename, filepath, aero


def run_single_simulation(vehicle_file, track_name, series):
    """Run lap time simulation and return results."""
    import main_laptimesim

    track_opts = {
        "trackname": track_name,
        "flip_track": False,
        "mu_weather": 1.0,
        "interp_stepsize_des": 5.0,
        "curv_filt_width": 10.0,
        "use_drs1": False,
        "use_drs2": False,
        "use_pit": False,
    }

    solver_opts = {
        "vehicle": vehicle_file,
        "series": series,
        "limit_braking_weak_side": "FA",
        "v_start": 80.0 / 3.6,
        "find_v_start": True,
        "max_no_em_iters": 5,
        "es_diff_max": 1.0,
    }

    driver_opts = {
        "vel_subtr_corner": 0.5,
        "vel_lim_glob": None,
        "yellow_s1": False,
        "yellow_s2": False,
        "yellow_s3": False,
        "yellow_throttle": 0.3,
        "initial_energy": 4.0e6,
        "em_strategy": "FCFB",
        "use_recuperation": True,
        "use_lift_coast": False,
        "lift_coast_dist": 10.0,
    }

    sa_opts = {"use_sa": False, "sa_type": "mass", "range_1": [1300.0, 1700.0, 5], "range_2": None}
    debug_opts = {
        "use_plot": False, "use_debug_plots": False,
        "use_plot_comparison_tph": False, "use_print": False, "use_print_result": False
    }

    lap = main_laptimesim.main(
        track_opts=track_opts, solver_opts=solver_opts,
        driver_opts=driver_opts, sa_opts=sa_opts, debug_opts=debug_opts,
    )

    # Extract velocity profile and coordinates (subsample for frontend)
    dists = lap.trackobj.dists_cl[:-1].tolist()
    vels = (lap.vel_cl[:-1] * 3.6).tolist()  # km/h
    x_coords = lap.trackobj.raceline[:, 0].tolist()
    y_coords = lap.trackobj.raceline[:, 1].tolist()

    step = max(1, len(dists) // 300)
    dists_sub = dists[::step]
    vels_sub = vels[::step]
    x_sub = x_coords[::step]
    y_sub = y_coords[::step]

    print(f"[LAP] raw t_cl[-1]={lap.t_cl[-1]:.3f}s, max_vel={float(np.max(lap.vel_cl))*3.6:.1f} km/h")

    return {
        "lap_time": round(lap.t_cl[-1], 3),
        "max_speed": round(float(np.max(lap.vel_cl)) * 3.6, 1),
        "min_speed": round(float(np.min(lap.vel_cl[1:])) * 3.6, 1),
        "energy_kJ": round(lap.e_cons_cl[-1] / 1000.0, 2),
        "vel_profile": {
            "distances": dists_sub, 
            "speeds": vels_sub,
            "x": x_sub,
            "y": y_sub
        },
    }


# -------------------------------------------------------------------------------------
# API ROUTES
# -------------------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/templates")
def api_templates():
    return jsonify(load_car_templates())


@app.route("/api/param_defs")
def api_param_defs():
    """Return parameter definitions with actual dataset ranges for the UI."""
    result = []
    for pd in PARAM_DEFS:
        key = pd["key"]
        lo, hi = PARAM_RANGES.get(key, (-100, 100))
        result.append({**pd, "min": lo, "max": hi})
    return jsonify(result)


@app.route("/api/tracks")
def api_tracks():
    return jsonify(load_tracks())


@app.route("/api/track/<name>")
def api_track_data(name):
    coords = load_track_coords(name, simplified=False)
    return jsonify({"name": name, "coords": coords})


@app.route("/api/stl/<body_code>")
def serve_stl(body_code):
    """Serve the STL mesh for a given body type (N, E, or F)."""
    stl_path = STL_MESH_MAP.get(body_code.upper())
    if not stl_path or not os.path.exists(stl_path):
        return jsonify({"error": f"No STL found for body type '{body_code}'"}), 404
    directory = os.path.dirname(stl_path)
    filename  = os.path.basename(stl_path)
    return send_from_directory(directory, filename)


@app.route("/api/local_sensitivity", methods=["POST"])
def api_local_sensitivity():
    """Return per-parameter Cd sensitivity and lap-time delta at the current position.

    Sensitivity source priority:
      1. Gradient Boosting (GB) model — smooth, non-linear, trained on all 4,165 designs
      2. KNN weighted regression     — local 64-neighbour fallback

    New response keys (backward-compatible additions):
      sensitivity_seconds  — {param_key: delta_seconds} using last lap time
      sensitivity_source   — "gradient_boosting" or "knn"
    """
    data      = request.get_json()
    body_code = data.get("body_code", "N").upper()
    params    = data.get("params", {})
    underbody = data.get("underbody", "S")
    wheels    = data.get("wheels", "WWC")
    lap_time  = data.get("lap_time", None)   # optional — passed after first simulation

    # KNN always runs: needed for confidence score, Cd/Cl values, and fallback sensitivity
    aero = params_to_aero_coeffs(params, body_code, underbody, wheels)

    # Choose best available sensitivity
    if GB_AVAILABLE:
        gb_sens = gb_sensitivity(params, body_code)
    else:
        gb_sens = None

    if gb_sens is not None:
        final_sensitivity = gb_sens
        source = "gradient_boosting"
    else:
        final_sensitivity = aero["local_sensitivity"]
        source = "knn"

    sens_seconds = sensitivity_to_seconds(final_sensitivity, aero["cd"], lap_time)

    return jsonify({
        "cd":                  aero["cd"],
        "local_sensitivity":   final_sensitivity,
        "sensitivity_seconds": sens_seconds,
        "sensitivity_source":  source,
        "confidence_score":    aero["confidence_score"],
        "confidence_level":    aero["confidence_level"],
        "dist_nearest":        aero["dist_nearest"],
        "dist_mean64":         aero["dist_mean64"],
    })


@app.route("/api/suggestions", methods=["POST"])
def api_suggestions():
    """Return top parameter suggestions ranked by estimated lap time improvement.

    Expects JSON: {
        "params":    {...23 geometric params...},
        "body_code": "N",
        "underbody": "S",
        "wheels":    "WWC",
        "lap_time":  92.456,   # optional — uses 90.0 default
        "cd":        0.285,    # optional — computed via KNN if absent
        "track":     "Shanghai" # optional — informational only
    }

    Returns: {
        "suggestions": [
            {
                "param_key":     "B_Diffusor_Angle",
                "param_name":    "Diffusor Angle",
                "direction":     "increase",   # or "decrease"
                "delta_cd":      -0.0041,
                "delta_seconds": -0.58,
                "current_value": 10.62,
                "unit":          "°",
                "category":      "Exterior"
            }, ...
        ],
        "lap_time_used":     92.456,
        "sensitivity_source":"gradient_boosting"
    }
    """
    data      = request.get_json()
    params    = data.get("params", {})
    body_code = data.get("body_code", "N").upper()
    underbody = data.get("underbody", "S")
    wheels    = data.get("wheels", "WWC")
    lap_time  = data.get("lap_time", None)
    cd        = data.get("cd", None)

    # Get Cd if not supplied
    if not cd or cd <= 0:
        aero = params_to_aero_coeffs(params, body_code, underbody, wheels)
        cd   = aero["cd"]

    # Get best available sensitivity
    if GB_AVAILABLE:
        sens = gb_sensitivity(params, body_code)
        source = "gradient_boosting"
    else:
        sens = None

    if sens is None:
        aero_full = params_to_aero_coeffs(params, body_code, underbody, wheels)
        sens   = aero_full["local_sensitivity"]
        source = "knn"

    sens_seconds = sensitivity_to_seconds(sens, cd, lap_time)
    used_lap_time = lap_time if (lap_time and lap_time > 0) else 90.0

    # Build suggestion list — only improvements (delta_seconds < 0)
    # Build a lookup for param metadata
    param_meta = {p["key"]: p for p in PARAM_DEFS}

    suggestions = []
    for key, delta_sec in sens_seconds.items():
        delta_cd = sens.get(key, 0.0)
        if delta_sec >= 0:
            continue   # This direction is slower — skip

        meta = param_meta.get(key, {})
        # direction: which way to move the slider to achieve the gain
        # delta_cd < 0 means increasing the param lowers Cd → direction = "increase"
        # delta_cd > 0 means decreasing the param lowers Cd → direction = "decrease"
        direction = "increase" if delta_cd < 0 else "decrease"

        suggestions.append({
            "param_key":     key,
            "param_name":    meta.get("name", key),
            "direction":     direction,
            "delta_cd":      round(delta_cd, 5),
            "delta_seconds": delta_sec,
            "current_value": round(float(params.get(key, 0)), 3),
            "unit":          meta.get("unit", ""),
            "category":      meta.get("category", ""),
        })

    # Sort by most time saved (most negative first), cap at 8
    suggestions.sort(key=lambda s: s["delta_seconds"])
    suggestions = suggestions[:8]

    return jsonify({
        "suggestions":      suggestions,
        "lap_time_used":    used_lap_time,
        "sensitivity_source": source,
    })


@app.route("/api/closest_mesh", methods=["POST"])
def api_closest_mesh():
    """Return the nearest matching STL URL based on geometric params via KNN."""
    payload = request.get_json()
    body_code = payload.get("body_code", "N").upper()
    params    = payload.get("params", {})
    underbody = payload.get("underbody", "S")
    wheels    = payload.get("wheels", "WWC")

    # For 3D visuals always use smooth underbody + closed wheels (S/WWC) —
    # underbody and wheels affect Cd output only, not the mesh shown.
    closest = find_closest_design(params, body_code, underbody='S', wheels='WWC')
    experiment_id = closest.get("experiment_id")

    if not experiment_id or experiment_id == "default":
        return jsonify({"body_code": body_code, "has_stl": False, "error": "No mesh matched"})

    folder   = experiment_folder(experiment_id)
    stl_path = os.path.join(SCRIPT_DIR, "ns", folder, f"{experiment_id}.stl")
    has_stl  = os.path.exists(stl_path)

    return jsonify({
        "body_code": body_code,
        "has_stl":   has_stl,
        "stl_url":   f"/api/mesh_decimated/{experiment_id}" if has_stl else None
    })

@app.route("/api/stl_by_name/<experiment_id>")
def serve_stl_by_name(experiment_id):
    """Serve a specific STL file by exact experiment name (full resolution)."""
    folder = experiment_folder(experiment_id)
    directory = os.path.join(SCRIPT_DIR, "ns", folder)
    filename = f"{experiment_id}.stl"
    if not os.path.exists(os.path.join(directory, filename)):
        return jsonify({"error": "STL not found"}), 404
    return send_from_directory(directory, filename)


# Decimated mesh cache directory
DECIMATED_DIR = os.path.join(SCRIPT_DIR, "ns_decimated")
DECIMATE_FACE_COUNT = 20_000

_decimate_in_progress = set()   # experiment IDs currently being decimated

def _decimate_worker(experiment_id, src_path, cache_dir, cache_path):
    """Background thread: decimate one STL and save to cache."""
    try:
        import trimesh
        os.makedirs(cache_dir, exist_ok=True)
        tmp_path = cache_path + ".tmp"
        mesh = trimesh.load(src_path, force='mesh')
        decimated = mesh.simplify_quadric_decimation(face_count=DECIMATE_FACE_COUNT)
        decimated.export(tmp_path)
        os.replace(tmp_path, cache_path)   # atomic rename
        print(f"[mesh] decimated {experiment_id} → {os.path.getsize(cache_path)//1024}KB")
    except Exception as e:
        print(f"[mesh] decimation failed for {experiment_id}: {e}")
    finally:
        _decimate_in_progress.discard(experiment_id)


@app.route("/api/mesh_decimated/<experiment_id>")
def serve_mesh_decimated(experiment_id):
    """
    Serve a decimated (20k face) STL for the 3D viewer.
    If not yet cached, kicks off a background thread and returns 202 so the
    client can retry — Flask never blocks for 5+ seconds.
    """
    import threading
    folder   = experiment_folder(experiment_id)
    src_path = os.path.join(SCRIPT_DIR, "ns", folder, f"{experiment_id}.stl")
    if not os.path.exists(src_path):
        return jsonify({"error": "Source STL not found"}), 404

    cache_dir  = os.path.join(DECIMATED_DIR, folder)
    cache_path = os.path.join(cache_dir, f"{experiment_id}.stl")

    if os.path.exists(cache_path):
        return send_from_directory(cache_dir, f"{experiment_id}.stl")

    # Not cached yet — start background decimation if not already running
    if experiment_id not in _decimate_in_progress:
        _decimate_in_progress.add(experiment_id)
        t = threading.Thread(target=_decimate_worker,
                             args=(experiment_id, src_path, cache_dir, cache_path),
                             daemon=True)
        t.start()

    return jsonify({"status": "decimating", "retry_ms": 4000}), 202


@app.route("/api/drivaernet")
def api_drivaernet():
    """Return summary stats of the DrivAerNet catalog."""
    designs = load_drivaernet_summary()
    cds = [d["cd"] for d in designs]
    cl_fs = [d["cl_f"] for d in designs]
    cl_rs = [d["cl_r"] for d in designs]
    return jsonify({
        "count": len(designs),
        "cd_range": [min(cds), max(cds)],
        "cl_f_range": [min(cl_fs), max(cl_fs)],
        "cl_r_range": [min(cl_rs), max(cl_rs)],
        "sample": designs[:20],
    })


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    """
    Run lap time simulation for multiple presets with geometric parameters.
    Expects JSON: {
        "body_code": "N",
        "track": "Shanghai",
        "presets": [
            {"name": "Stock", "params": {...23 geometric params...}},
            {"name": "Modified", "params": {...23 geometric params...}},
        ]
    }
    """
    data = request.get_json()
    body_code = data.get("body_code", "N")
    track = data.get("track", "Shanghai")
    presets = data.get("presets", [])

    print(f"[SIMULATE] body={body_code}, track={track}, presets={len(presets)}")

    results = []
    temp_files = []
    series = "F1"  # Use F1 series (hybrid powertrain compatible)

    for preset in presets:
        name = preset.get("name", "Unnamed")
        params = preset.get("params", {})
        underbody = preset.get("underbody", "S")
        wheels = preset.get("wheels", "WWC")

        filename, filepath, aero = generate_ini_file(body_code, params, underbody, wheels)
        temp_files.append(filepath)

        try:
            sim_result = run_single_simulation(filename, track, series)

            results.append({
                "name": name,
                "cd": aero["cd"],
                "cl_f": aero["cl_f"],
                "cl_r": aero["cl_r"],
                "underbody": underbody,
                "wheels": wheels,
                "status": "ok",
                **sim_result,
            })
        except Exception as e:
            import traceback
            print(f"[SIM ERROR] preset={name}: {type(e).__name__}: {e}")
            traceback.print_exc()
            results.append({
                "name": name,
                "status": "error",
                "error": str(e),
                "lap_time": 9999,
            })

    # Cleanup temp files
    for fp in temp_files:
        try:
            os.remove(fp)
        except OSError:
            pass

    # Sort by lap time and compute deltas
    results.sort(key=lambda r: r.get("lap_time", 9999))
    if results and results[0].get("status") == "ok":
        best = results[0]["lap_time"]
        for r in results:
            if r.get("status") == "ok":
                r["delta"] = round(r["lap_time"] - best, 3)

    # Find stock result for improvement calculation
    stock_result = next((r for r in results if r["name"] == "Stock"), None)
    if stock_result and stock_result.get("status") == "ok":
        stock_time = stock_result["lap_time"]
        for r in results:
            if r.get("status") == "ok":
                r["improvement_vs_stock"] = round(stock_time - r["lap_time"], 3)

    # Load track coords for visualization
    track_coords = load_track_coords(track, simplified=False)

    return jsonify({
        "track": track,
        "track_coords": track_coords,
        "results": results,
        "best": results[0]["name"] if results else None,
    })


# -------------------------------------------------------------------------------------
# RUN — Native Desktop App
# -------------------------------------------------------------------------------------

if __name__ == "__main__":
    import threading
    import time

    print("=" * 60)
    print("  AeroDynaSim v2 — Real Car Customization")
    print("  Launching desktop app...")
    print("=" * 60)

    # Start Flask in a background thread
    def start_flask():
        app.run(debug=False, port=8888, use_reloader=False)

    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # Give Flask a moment to start
    time.sleep(1.5)

    # Launch native desktop window via PyWebView (WebKit — no browser needed)
    try:
        import webview

        window = webview.create_window(
            "AeroDynaSim v2",
            "http://127.0.0.1:8888",
            width=1440,
            height=920,
            resizable=True,
            min_size=(1024, 720),
        )

        # gui='cocoa' forces the native macOS WebKit renderer (offline, no Chrome)
        webview.start(gui='cocoa', debug=False)

    except Exception as exc:
        print(f"[WINDOW] PyWebView failed: {exc}")
        print("[WINDOW] Flask is still running at http://127.0.0.1:8888")
        # Keep Flask alive if window fails
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
