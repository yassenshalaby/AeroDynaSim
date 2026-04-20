#!/usr/bin/env python3
"""
Aerodynamic Car Preset → Lap Time Simulation Pipeline

Connects DrivAerNet aerodynamic data with the lap time simulator to compare
different car aerodynamic configurations on a race track.

Usage:
    python aero_laptime_pipeline.py [options]

Examples:
    # Run with 5 presets spanning the Cd range on Shanghai
    python aero_laptime_pipeline.py --num_presets 5

    # Run with specific DrivAerNet experiment IDs
    python aero_laptime_pipeline.py --experiments E_S_WWC_WM_005 E_S_WWC_WM_100 E_S_WWC_WM_200

    # Use a different track and template
    python aero_laptime_pipeline.py --num_presets 3 --track Monza --template F1_Shanghai.ini --series F1
"""

import os
import sys
import csv
import json
import argparse
import re
import copy
import numpy as np
import configparser

# -------------------------------------------------------------------------------------
# PATHS
# -------------------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DRIVAERNET_CSV = os.path.join(SCRIPT_DIR, "DrivAerNet-main", "ParametricModels",
                              "DrivAerNet_ParametricData.csv")
LAPTIME_DIR = os.path.join(SCRIPT_DIR, "laptime-simulation-master")
VEHICLES_DIR = os.path.join(LAPTIME_DIR, "laptimesim", "input", "vehicles")
RESULTS_CSV = os.path.join(SCRIPT_DIR, "aero_laptime_results.csv")

# Workaround: mock 'quadprog' module which has a binary incompatibility with Python 3.14.
# quadprog is only used by trajectory_planning_helpers.opt_min_curv (trajectory optimization),
# which is NOT called during lap time simulation, so a stub is safe.
import types
_quadprog_mock = types.ModuleType("quadprog")
_quadprog_mock.solve_qp = lambda *args, **kwargs: None
sys.modules["quadprog"] = _quadprog_mock

# Add the lap time simulator to the Python path
sys.path.insert(0, LAPTIME_DIR)


# -------------------------------------------------------------------------------------
# 1. LOAD DRIVAERNET DATA
# -------------------------------------------------------------------------------------

def load_drivaernet_data(csv_path: str) -> list:
    """Load the DrivAerNet parametric CSV and return list of dicts."""
    data = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    print(f"[INFO] Loaded {len(data)} car designs from DrivAerNet")
    return data


# -------------------------------------------------------------------------------------
# 2. SELECT PRESETS
# -------------------------------------------------------------------------------------

def select_presets_by_ids(data: list, experiment_ids: list) -> list:
    """Select specific car designs by their experiment IDs."""
    lookup = {row["Experiment"]: row for row in data}
    selected = []
    for eid in experiment_ids:
        if eid in lookup:
            selected.append(lookup[eid])
        else:
            print(f"[WARNING] Experiment ID '{eid}' not found in dataset, skipping.")
    return selected


def select_presets_spanning_cd(data: list, num_presets: int) -> list:
    """Select N presets that span the Cd range (min to max, evenly spaced)."""
    # Sort by Cd
    sorted_data = sorted(data, key=lambda x: float(x["Average Cd"]))

    if num_presets >= len(sorted_data):
        return sorted_data

    # Pick evenly spaced indices
    indices = np.linspace(0, len(sorted_data) - 1, num_presets, dtype=int)
    selected = [sorted_data[i] for i in indices]
    return selected


def select_presets_random(data: list, num_presets: int, seed: int = 42) -> list:
    """Select N random presets."""
    rng = np.random.default_rng(seed)
    indices = rng.choice(len(data), size=min(num_presets, len(data)), replace=False)
    return [data[i] for i in sorted(indices)]


# -------------------------------------------------------------------------------------
# 3. MAP AERO COEFFICIENTS TO SIMULATOR PARAMETERS
# -------------------------------------------------------------------------------------

def map_aero_to_sim_params(design: dict, frontal_area: float) -> dict:
    """
    Convert DrivAerNet aero coefficients to lap time simulator parameters.

    DrivAerNet sign convention:
      - Cd is always positive (drag)
      - Cl negative = downforce, Cl positive = lift

    Simulator convention:
      - c_w_a = Cd × A  (drag area, always positive)
      - c_z_a_f/r = downforce × area (positive = pushes car down)

    For designs with net lift (positive Cl), we set downforce to 0.
    """
    cd = float(design["Average Cd"])
    cl_f = float(design["Average Cl_f"])
    cl_r = float(design["Average Cl_r"])

    c_w_a = cd * frontal_area

    # Negative Cl = downforce → take abs; Positive Cl = lift → set to 0
    c_z_a_f = abs(cl_f) * frontal_area if cl_f < 0 else 0.0
    c_z_a_r = abs(cl_r) * frontal_area if cl_r < 0 else 0.0

    return {
        "c_w_a": round(c_w_a, 4),
        "c_z_a_f": round(c_z_a_f, 4),
        "c_z_a_r": round(c_z_a_r, 4),
        "cd": round(cd, 6),
        "cl_f": round(cl_f, 6),
        "cl_r": round(cl_r, 6),
    }


# -------------------------------------------------------------------------------------
# 4. GENERATE VEHICLE .INI FILES
# -------------------------------------------------------------------------------------

def load_template_ini(template_path: str) -> str:
    """Load the template .ini file as raw text."""
    with open(template_path, "r") as f:
        return f.read()


def generate_preset_ini(template_text: str, aero_params: dict, preset_name: str,
                        output_dir: str) -> str:
    """
    Generate a new .ini file by replacing aero parameters in the template.
    Returns the path to the created file.
    """
    # Parse the template to get the veh_pars dict
    parser = configparser.ConfigParser()
    parser.read_string(template_text)
    veh_pars = json.loads(parser.get('VEH_PARS', 'veh_pars'))

    # Override aero parameters
    veh_pars["general"]["c_w_a"] = aero_params["c_w_a"]
    veh_pars["general"]["c_z_a_f"] = aero_params["c_z_a_f"]
    veh_pars["general"]["c_z_a_r"] = aero_params["c_z_a_r"]

    # Reconstruct the .ini content
    # We need to format the dict nicely, matching the original style
    ini_content = generate_ini_content(veh_pars)

    # Write to file
    filename = f"{preset_name}.ini"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w") as f:
        f.write(ini_content)

    return filepath


def generate_ini_content(veh_pars: dict) -> str:
    """Generate .ini file content from a veh_pars dict, matching original format."""
    # Build a nicely formatted Python dict string that configparser can read
    lines = []
    lines.append("# " + "-" * 118)
    lines.append("[VEH_PARS]")
    lines.append("")
    lines.append("# Auto-generated by aero_laptime_pipeline.py")
    lines.append("# Only c_w_a, c_z_a_f, c_z_a_r differ from the base template")
    lines.append("")

    # Serialize veh_pars as a Python literal (JSON-compatible)
    veh_pars_str = json.dumps(veh_pars, indent=10)
    lines.append(f"veh_pars={veh_pars_str}")
    lines.append("")

    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------------------------
# 5. RUN LAP TIME SIMULATION
# -------------------------------------------------------------------------------------

def run_simulation(vehicle_file: str, track_name: str, series: str) -> dict:
    """
    Run the lap time simulation for a given vehicle file and track.
    Returns a dict with lap_time, energy_consumption, etc.
    """
    import main_laptimesim

    # Determine DRS settings based on series
    use_drs = series == "F1"

    track_opts = {
        "trackname": track_name,
        "flip_track": False,
        "mu_weather": 1.0,
        "interp_stepsize_des": 5.0,
        "curv_filt_width": 10.0,
        "use_drs1": use_drs,
        "use_drs2": use_drs,
        "use_pit": False,
    }

    solver_opts = {
        "vehicle": vehicle_file,
        "series": series,
        "limit_braking_weak_side": "FA",
        "v_start": 100.0 / 3.6,
        "find_v_start": True,
        "max_no_em_iters": 5,
        "es_diff_max": 1.0,
    }

    # Driver opts - use appropriate energy for the series
    if series == "FE":
        initial_energy = 4.58e6
        em_strategy = "FCFB"
        vel_lim_glob = None
    else:
        initial_energy = 4.0e6
        em_strategy = "FCFB"
        vel_lim_glob = None

    driver_opts = {
        "vel_subtr_corner": 0.5,
        "vel_lim_glob": vel_lim_glob,
        "yellow_s1": False,
        "yellow_s2": False,
        "yellow_s3": False,
        "yellow_throttle": 0.3,
        "initial_energy": initial_energy,
        "em_strategy": em_strategy,
        "use_recuperation": True,
        "use_lift_coast": False,
        "lift_coast_dist": 10.0,
    }

    sa_opts = {
        "use_sa": False,
        "sa_type": "mass",
        "range_1": [733.0, 833.0, 5],
        "range_2": None,
    }

    debug_opts = {
        "use_plot": False,
        "use_debug_plots": False,
        "use_plot_comparison_tph": False,
        "use_print": False,
        "use_print_result": False,
    }

    try:
        lap = main_laptimesim.main(
            track_opts=track_opts,
            solver_opts=solver_opts,
            driver_opts=driver_opts,
            sa_opts=sa_opts,
            debug_opts=debug_opts,
        )

        lap_time = lap.t_cl[-1]
        max_vel = np.max(lap.vel_cl) * 3.6  # km/h
        e_cons = lap.e_cons_cl[-1] / 1000.0  # kJ

        return {
            "lap_time_s": round(lap_time, 3),
            "max_speed_kmh": round(max_vel, 1),
            "energy_kJ": round(e_cons, 2),
            "status": "OK",
        }

    except Exception as e:
        return {
            "lap_time_s": float("inf"),
            "max_speed_kmh": 0.0,
            "energy_kJ": 0.0,
            "status": f"ERROR: {str(e)}",
        }


# -------------------------------------------------------------------------------------
# 6. RESULTS REPORTING
# -------------------------------------------------------------------------------------

def print_results_table(results: list):
    """Print a formatted comparison table sorted by lap time."""
    # Sort by lap time
    sorted_results = sorted(results, key=lambda x: x["lap_time_s"])

    print("\n" + "=" * 110)
    print("  AERODYNAMIC PRESET LAP TIME COMPARISON")
    print("=" * 110)
    print(f"  {'Rank':<5} {'Preset':<30} {'Cd':>8} {'Cl_f':>8} {'Cl_r':>8} "
          f"{'Lap Time':>10} {'Max Speed':>10} {'Status':>10}")
    print("-" * 110)

    for i, r in enumerate(sorted_results):
        lap_str = f"{r['lap_time_s']:.3f}s" if r["lap_time_s"] < float("inf") else "N/A"
        spd_str = f"{r['max_speed_kmh']:.1f}" if r["max_speed_kmh"] > 0 else "N/A"

        print(f"  {i+1:<5} {r['preset_name']:<30} {r['cd']:>8.4f} {r['cl_f']:>8.4f} "
              f"{r['cl_r']:>8.4f} {lap_str:>10} {spd_str:>10} {r['status']:>10}")

    print("=" * 110)

    # Print delta from best
    if len(sorted_results) >= 2 and sorted_results[0]["lap_time_s"] < float("inf"):
        best = sorted_results[0]["lap_time_s"]
        print(f"\n  Best lap: {sorted_results[0]['preset_name']} — {best:.3f}s")
        print(f"  Deltas from best:")
        for i, r in enumerate(sorted_results[1:], start=2):
            if r["lap_time_s"] < float("inf"):
                delta = r["lap_time_s"] - best
                print(f"    #{i} {r['preset_name']}: +{delta:.3f}s")
    print()


def save_results_csv(results: list, output_path: str):
    """Save results to a CSV file."""
    sorted_results = sorted(results, key=lambda x: x["lap_time_s"])

    fieldnames = ["rank", "preset_name", "experiment_id", "cd", "cl_f", "cl_r",
                  "c_w_a", "c_z_a_f", "c_z_a_r", "lap_time_s", "max_speed_kmh",
                  "energy_kJ", "status"]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, r in enumerate(sorted_results):
            writer.writerow({
                "rank": i + 1,
                "preset_name": r["preset_name"],
                "experiment_id": r["experiment_id"],
                "cd": r["cd"],
                "cl_f": r["cl_f"],
                "cl_r": r["cl_r"],
                "c_w_a": r["c_w_a"],
                "c_z_a_f": r["c_z_a_f"],
                "c_z_a_r": r["c_z_a_r"],
                "lap_time_s": r["lap_time_s"],
                "max_speed_kmh": r["max_speed_kmh"],
                "energy_kJ": r["energy_kJ"],
                "status": r["status"],
            })

    print(f"[INFO] Results saved to: {output_path}")


# -------------------------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Connect DrivAerNet aerodynamics with lap time simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Selection mode
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--experiments", nargs="+", type=str,
                       help="Specific DrivAerNet experiment IDs to use")
    group.add_argument("--num_presets", type=int, default=5,
                       help="Number of presets to auto-select spanning the Cd range (default: 5)")
    group.add_argument("--random", type=int, default=None, metavar="N",
                       help="Select N random presets")

    # Simulation settings
    parser.add_argument("--track", type=str, default="Shanghai",
                        help="Track name (default: Shanghai)")
    parser.add_argument("--template", type=str, default="F1_Shanghai.ini",
                        help="Base vehicle template .ini file (default: F1_Shanghai.ini)")
    parser.add_argument("--series", type=str, default="F1", choices=["F1", "FE"],
                        help="Racing series (default: F1)")
    parser.add_argument("--frontal_area", type=float, default=2.16,
                        help="Frontal area in m² for coefficient conversion (default: 2.16)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output CSV path (default: grad/aero_laptime_results.csv)")

    args = parser.parse_args()

    print("=" * 70)
    print("  DrivAerNet → Lap Time Simulator Pipeline")
    print("=" * 70)

    # ---------------------------------------------------------------------------------
    # Step 1: Load DrivAerNet data
    # ---------------------------------------------------------------------------------
    print("\n[STEP 1] Loading DrivAerNet aerodynamic data...")
    data = load_drivaernet_data(DRIVAERNET_CSV)

    # ---------------------------------------------------------------------------------
    # Step 2: Select presets
    # ---------------------------------------------------------------------------------
    print("\n[STEP 2] Selecting car design presets...")
    if args.experiments:
        presets = select_presets_by_ids(data, args.experiments)
        mode_desc = f"specific IDs: {args.experiments}"
    elif args.random is not None:
        presets = select_presets_random(data, args.random)
        mode_desc = f"{args.random} random presets"
    else:
        presets = select_presets_spanning_cd(data, args.num_presets)
        mode_desc = f"{args.num_presets} presets spanning Cd range"

    if not presets:
        print("[ERROR] No valid presets selected. Exiting.")
        sys.exit(1)

    print(f"  Selection mode: {mode_desc}")
    print(f"  Selected {len(presets)} presets:")
    for p in presets:
        print(f"    - {p['Experiment']}: Cd={float(p['Average Cd']):.4f}, "
              f"Cl_f={float(p['Average Cl_f']):.4f}, Cl_r={float(p['Average Cl_r']):.4f}")

    # ---------------------------------------------------------------------------------
    # Step 3: Map aero coefficients and generate .ini files
    # ---------------------------------------------------------------------------------
    print(f"\n[STEP 3] Generating vehicle preset files (frontal area = {args.frontal_area} m²)...")

    template_path = os.path.join(VEHICLES_DIR, args.template)
    if not os.path.exists(template_path):
        print(f"[ERROR] Template file not found: {template_path}")
        sys.exit(1)

    template_text = load_template_ini(template_path)
    preset_files = []

    for i, design in enumerate(presets):
        exp_id = design["Experiment"]
        aero = map_aero_to_sim_params(design, args.frontal_area)
        preset_name = f"Preset_{i+1:03d}_{exp_id}"

        filepath = generate_preset_ini(template_text, aero, preset_name, VEHICLES_DIR)
        preset_files.append({
            "preset_name": preset_name,
            "experiment_id": exp_id,
            "filepath": filepath,
            "filename": os.path.basename(filepath),
            "aero": aero,
        })
        print(f"  Created: {os.path.basename(filepath)} "
              f"(c_w_a={aero['c_w_a']:.4f}, c_z_a_f={aero['c_z_a_f']:.4f}, "
              f"c_z_a_r={aero['c_z_a_r']:.4f})")

    # ---------------------------------------------------------------------------------
    # Step 4: Run simulations
    # ---------------------------------------------------------------------------------
    print(f"\n[STEP 4] Running lap time simulations on {args.track}...")
    print(f"  Series: {args.series} | Template: {args.template}")

    results = []
    for j, pf in enumerate(preset_files):
        print(f"\n  [{j+1}/{len(preset_files)}] Simulating {pf['preset_name']}...")

        sim_result = run_simulation(
            vehicle_file=pf["filename"],
            track_name=args.track,
            series=args.series,
        )

        result = {
            "preset_name": pf["preset_name"],
            "experiment_id": pf["experiment_id"],
            **pf["aero"],
            **sim_result,
        }
        results.append(result)

        if sim_result["status"] == "OK":
            print(f"    → Lap time: {sim_result['lap_time_s']:.3f}s | "
                  f"Max speed: {sim_result['max_speed_kmh']:.1f} km/h")
        else:
            print(f"    → {sim_result['status']}")

    # ---------------------------------------------------------------------------------
    # Step 5: Report results
    # ---------------------------------------------------------------------------------
    print_results_table(results)

    output_path = args.output if args.output else RESULTS_CSV
    save_results_csv(results, output_path)

    # ---------------------------------------------------------------------------------
    # Cleanup: remove generated preset files
    # ---------------------------------------------------------------------------------
    print("[INFO] Generated .ini preset files are kept in:")
    print(f"  {VEHICLES_DIR}")
    print("  You can delete them manually when no longer needed.")
    print("\n[DONE] Pipeline complete!")


if __name__ == "__main__":
    main()
