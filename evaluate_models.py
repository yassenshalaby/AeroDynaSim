"""
AeroDynaSim — ML Model Accuracy Evaluation
==========================================
Run with:
    arch -arm64 .venv/bin/python evaluate_models.py

Uses the OFFICIAL DrivAerNet++ train/val/test splits so results are
directly comparable to the paper's reported benchmarks.

  Train : 3,051 designs  (official split intersected with parametric CSV)
  Val   :   555 designs
  Test  :   559 designs  ← accuracy numbers reported against this

Models evaluated:
  1. KNN  (k=7, inverse-distance weighted) — aerodynamic lookup
  2. Gradient Boosting (HistGBR)           — per-parameter sensitivity
"""

import csv
import os
import math
import pickle
import numpy as np

# ── Paths ────────────────────────────────────────────────────────────────────
BASE        = os.path.dirname(os.path.abspath(__file__))
CSV_PATH    = os.path.join(BASE, "DrivAerNet-main", "ParametricModels",
                           "DrivAerNet_ParametricData.csv")
SPLITS_DIR  = os.path.join(BASE, "DrivAerNet-main", "train_val_test_splits")
MODELS_DIR  = os.path.join(BASE, "models")

# ── Parameters ───────────────────────────────────────────────────────────────
# MUST match the order in app.py PARAM_DEFS exactly — cached pkl models depend on this
PARAM_KEYS = [
    "A_Car_Length", "A_Car_Width", "A_Car_Roof_Height", "A_Car_Green_House_Angle",
    "B_Ramp_Angle", "B_Diffusor_Angle", "B_Trunklid_Angle",
    "G_Trunklid_Curvature", "G_Trunklid_Length",
    "E_Fenders_Arch_Offset",
    "D_Rear_Window_Inclination", "D_Rear_Window_Length",
    "D_Winscreen_Inclination", "D_Winscreen_Length",
    "E_A_B_C_Pillar_Thickness",
    "C_Side_Mirrors_Rotation", "C_Side_Mirrors_Translate_X", "C_Side_Mirrors_Translate_Z",
    "H_Front_Bumper_Curvature", "H_Front_Bumper_Length",
    "F_Door_Handles_Thickness", "F_Door_Handles_X_Position", "F_Door_Handles_Z_Position",
]
LENGTH_PARAMS = {
    "A_Car_Length", "A_Car_Width", "A_Car_Roof_Height",
    "C_Side_Mirrors_Translate_X", "C_Side_Mirrors_Translate_Z",
    "D_Winscreen_Length", "D_Rear_Window_Length",
    "E_Fenders_Arch_Offset", "F_Door_Handles_Z_Position", "F_Door_Handles_X_Position",
    "G_Trunklid_Length", "H_Front_Bumper_Length",
}

# ── Load official splits ─────────────────────────────────────────────────────
def load_split_ids(name):
    path = os.path.join(SPLITS_DIR, f"{name}_design_ids.txt")
    with open(path) as f:
        return set(line.strip() for line in f if line.strip())

# ── Load CSV filtered to a set of IDs ───────────────────────────────────────
def load_data(id_set=None):
    """Returns list of (x_vec, cd) tuples, optionally filtered to id_set."""
    rows = []
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            exp = row.get("Experiment", "")
            if id_set is not None and exp not in id_set:
                continue
            try:
                x = [float(row[k]) for k in PARAM_KEYS]
                cd = float(row["Average Cd"])
                rows.append((exp, x, cd))
            except (ValueError, KeyError):
                continue
    return rows

# ── Also load Cl_f and Cl_r ─────────────────────────────────────────────────
def load_data_multi(id_set=None):
    """Returns list of (exp_id, x_vec, cd, cl_f, cl_r)."""
    rows = []
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            exp = row.get("Experiment", "")
            if id_set is not None and exp not in id_set:
                continue
            try:
                x   = [float(row[k]) for k in PARAM_KEYS]
                cd  = float(row["Average Cd"])
                clf = float(row["Average Cl_f"])
                clr = float(row["Average Cl_r"])
                rows.append((exp, x, cd, clf, clr))
            except (ValueError, KeyError):
                continue
    return rows

# ── KNN normalisation ────────────────────────────────────────────────────────
def normalise(x):
    return [v / 100.0 if PARAM_KEYS[i] in LENGTH_PARAMS else v
            for i, v in enumerate(x)]

def euclidean(a, b):
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))

# ── Metrics ──────────────────────────────────────────────────────────────────
def metrics(y_true, y_pred, label=""):
    n = len(y_true)
    mae  = sum(abs(a - b) for a, b in zip(y_true, y_pred)) / n
    mse  = sum((a - b) ** 2 for a, b in zip(y_true, y_pred)) / n
    rmse = math.sqrt(mse)
    mean_t = sum(y_true) / n
    ss_res = sum((a - b) ** 2 for a, b in zip(y_true, y_pred))
    ss_tot = sum((a - mean_t) ** 2 for a in y_true)
    r2     = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    max_e  = max(abs(a - b) for a, b in zip(y_true, y_pred))
    return dict(label=label, R2=r2, MAE=mae, RMSE=rmse, MaxErr=max_e, N=n)

def print_row(m):
    print(f"  {m['label']:<36}  R²={m['R2']:.4f}  MAE={m['MAE']:.5f}  "
          f"RMSE={m['RMSE']:.5f}  MaxErr={m['MaxErr']:.5f}  (n={m['N']})")

# ═══════════════════════════════════════════════════════════════════════════════
# 1. KNN  — evaluated per body type on official test split
# ═══════════════════════════════════════════════════════════════════════════════
def eval_knn(train_data, test_data):
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  KNN  (k=7, inverse-distance weighted)  — official test set  ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print("  Retrieves Cd by searching the training set at query time.")
    print("  Train: 3,051 designs  |  Test: 559 designs  (official splits)\n")

    for body in ["N", "E", "F"]:
        tr = [(x, cd) for _, x, cd in train_data if _[0] == body]
        te = [(x, cd) for _, x, cd in test_data  if _[0] == body]
        if not tr or not te:
            continue

        train_X = [normalise(x) for x, _ in tr]
        train_y = [y for _, y in tr]

        y_true, y_pred = [], []
        for x_raw, cd_true in te:
            xn    = normalise(x_raw)
            dists = sorted((euclidean(xn, tx), ty)
                           for tx, ty in zip(train_X, train_y))[:7]
            w_sum = sum(1.0 / (d + 1e-9) for d, _ in dists)
            pred  = sum((1.0 / (d + 1e-9)) * y for d, y in dists) / w_sum
            y_true.append(cd_true)
            y_pred.append(pred)

        print_row(metrics(y_true, y_pred, f"KNN (k=7) — body {body}"))

    # All body types combined
    tr_all = [(x, cd) for _, x, cd in train_data]
    te_all = [(x, cd) for _, x, cd in test_data]
    train_X = [normalise(x) for x, _ in tr_all]
    train_y = [y for _, y in tr_all]
    y_true, y_pred = [], []
    for x_raw, cd_true in te_all:
        xn    = normalise(x_raw)
        dists = sorted((euclidean(xn, tx), ty)
                       for tx, ty in zip(train_X, train_y))[:7]
        w_sum = sum(1.0 / (d + 1e-9) for d, _ in dists)
        pred  = sum((1.0 / (d + 1e-9)) * y for d, y in dists) / w_sum
        y_true.append(cd_true)
        y_pred.append(pred)
    print_row(metrics(y_true, y_pred, "KNN (k=7) — ALL bodies"))
    print()

# ═══════════════════════════════════════════════════════════════════════════════
# 2. Gradient Boosting — per-body and combined, official splits
# ═══════════════════════════════════════════════════════════════════════════════
def eval_gb(train_data, val_data, test_data):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.metrics import r2_score, mean_absolute_error, mean_squared_error

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Gradient Boosting (HistGBR) — official train/val/test split ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print("  Learns a smooth nonlinear function: 23 params → Cd.")
    print("  Train: 3,051  |  Val: 555  |  Test: 559  (official splits)\n")

    results = []
    for body in ["N", "E", "F"]:
        tr = [(x, cd) for _, x, cd in train_data if _[0] == body]
        va = [(x, cd) for _, x, cd in val_data   if _[0] == body]
        te = [(x, cd) for _, x, cd in test_data  if _[0] == body]
        if not tr or not te:
            continue

        X_tr = np.array([x for x, _ in tr]);  y_tr = np.array([y for _, y in tr])
        X_va = np.array([x for x, _ in va]);  y_va = np.array([y for _, y in va])
        X_te = np.array([x for x, _ in te]);  y_te = np.array([y for _, y in te])

        model = HistGradientBoostingRegressor(
            max_iter=400, max_depth=6, learning_rate=0.05,
            min_samples_leaf=10, l2_regularization=0.1, random_state=42
        )
        model.fit(X_tr, y_tr)

        r2_tr = r2_score(y_tr, model.predict(X_tr))
        r2_va = r2_score(y_va, model.predict(X_va))
        r2_te = r2_score(y_te, model.predict(X_te))
        mae   = mean_absolute_error(y_te, model.predict(X_te))
        rmse  = math.sqrt(mean_squared_error(y_te, model.predict(X_te)))
        max_e = float(np.max(np.abs(y_te - model.predict(X_te))))

        print(f"  GB — body {body:<3}  "
              f"R²(train)={r2_tr:.4f}  R²(val)={r2_va:.4f}  R²(test)={r2_te:.4f}  "
              f"MAE={mae:.5f}  RMSE={rmse:.5f}  MaxErr={max_e:.5f}  (n_test={len(y_te)})")
        results.append((body, r2_te))

    # Combined model — all bodies, body type as extra feature
    print()
    BODY_MAP = {"N": 0, "E": 1, "F": 2}

    def add_body(data):
        return (
            np.array([[*x, BODY_MAP.get(eid[0], 0)] for eid, x, cd in data]),
            np.array([cd for _, _, cd in data])
        )

    X_tr, y_tr = add_body(train_data)
    X_va, y_va = add_body(val_data)
    X_te, y_te = add_body(test_data)

    combined = HistGradientBoostingRegressor(
        max_iter=400, max_depth=6, learning_rate=0.05,
        min_samples_leaf=10, l2_regularization=0.1, random_state=42
    )
    combined.fit(X_tr, y_tr)

    r2_tr = r2_score(y_tr, combined.predict(X_tr))
    r2_va = r2_score(y_va, combined.predict(X_va))
    r2_te = r2_score(y_te, combined.predict(X_te))
    mae   = mean_absolute_error(y_te, combined.predict(X_te))
    rmse  = math.sqrt(mean_squared_error(y_te, combined.predict(X_te)))
    max_e = float(np.max(np.abs(y_te - combined.predict(X_te))))

    print(f"  GB — COMBINED (all bodies + body feature)")
    print(f"               R²(train)={r2_tr:.4f}  R²(val)={r2_va:.4f}  "
          f"R²(test)={r2_te:.4f}  MAE={mae:.5f}  RMSE={rmse:.5f}  "
          f"MaxErr={max_e:.5f}  (n_test={len(y_te)})")
    print()

# ═══════════════════════════════════════════════════════════════════════════════
# 3. Verify cached app models (the exact pkl files the running app uses)
# ═══════════════════════════════════════════════════════════════════════════════
def verify_cached(test_data):
    from sklearn.metrics import r2_score, mean_absolute_error

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Cached App Models (pkl) — tested on official test split     ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print("  These are the exact models loaded by the running app.\n")

    for body in ["N", "E", "F"]:
        pkl = os.path.join(MODELS_DIR, f"gb_cd_{body}.pkl")
        if not os.path.exists(pkl):
            print(f"  body={body}  [NO PKL FOUND — run the app once to generate]")
            continue
        with open(pkl, "rb") as f:
            model = pickle.load(f)
        te = [(x, cd) for _, x, cd in test_data if _[0] == body]
        if not te:
            continue
        X_te = np.array([x for x, _ in te])
        y_te = np.array([cd for _, cd in te])
        y_pr = model.predict(X_te)
        r2   = r2_score(y_te, y_pr)
        mae  = mean_absolute_error(y_te, y_pr)
        rmse = math.sqrt(float(np.mean((y_te - y_pr) ** 2)))
        max_e = float(np.max(np.abs(y_te - y_pr)))
        print(f"  Cached GB — body {body:<3}  R²(test)={r2:.4f}  "
              f"MAE={mae:.5f}  RMSE={rmse:.5f}  MaxErr={max_e:.5f}  (n={len(y_te)})")
    print()

# ═══════════════════════════════════════════════════════════════════════════════
# 4. Legend
# ═══════════════════════════════════════════════════════════════════════════════
def print_legend():
    print("─" * 70)
    print("LEGEND")
    print("  R²(test)   — accuracy on designs the model never saw during training")
    print("               1.0 = perfect  |  0.0 = no better than guessing the mean")
    print("  MAE        — average prediction error in Cd units")
    print("  RMSE       — root mean square error (penalises large outliers more)")
    print("  MaxErr     — worst single prediction error in the test set")
    print("  body N/E/F — Notchback / Estateback / Fastback")
    print()
    print("  Cd range in dataset: ~0.20 – 0.40")
    print("  MAE of 0.010 = average error of 0.010 drag coefficient units")
    print("─" * 70)
    print()
    print("  Splits used: official DrivAerNet++ train/val/test from GitHub")
    print("  Train: 3,051 designs  |  Val: 555  |  Test: 559")
    print("  Source: github.com/Mohamedelrefaie/DrivAerNet")

# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print()
    print("=" * 70)
    print("  AeroDynaSim — ML Accuracy Report (Official DrivAerNet++ Splits)")
    print("=" * 70)

    print("\nLoading official splits...", end=" ", flush=True)
    train_ids = load_split_ids("train")
    val_ids   = load_split_ids("val")
    test_ids  = load_split_ids("test")
    print("done")

    print("Loading dataset...", end=" ", flush=True)
    train_data = load_data(train_ids)
    val_data   = load_data(val_ids)
    test_data  = load_data(test_ids)
    print(f"done  (train={len(train_data)}, val={len(val_data)}, test={len(test_data)})\n")

    eval_knn(train_data, test_data)
    eval_gb(train_data, val_data, test_data)
    verify_cached(test_data)
    print_legend()
