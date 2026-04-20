"""
Pre-decimates all STL files in ns/ to ns_decimated/ at 20,000 faces.
Run once in the background — takes 30-90 min depending on machine speed.
Safe to interrupt and resume: already-cached files are skipped.
"""
import os, sys, time

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SRC_ROOT     = os.path.join(SCRIPT_DIR, "ns")
DST_ROOT     = os.path.join(SCRIPT_DIR, "ns_decimated")
FACE_TARGET  = 20_000

def run():
    try:
        import trimesh
    except ImportError:
        print("trimesh not found — install it first"); sys.exit(1)

    # Priority order: N first (most used), then F, then E (already partially done)
    all_folders = [d for d in os.listdir(SRC_ROOT)
                   if os.path.isdir(os.path.join(SRC_ROOT, d))]
    priority = ["N_S_WWC_WM", "F_S_WWC_WM", "E_S_WWC_WM"]
    folders = priority + [f for f in sorted(all_folders) if f not in priority]

    total_done = total_skip = total_err = 0
    t0 = time.time()

    for folder in folders:
        src_dir = os.path.join(SRC_ROOT, folder)
        dst_dir = os.path.join(DST_ROOT, folder)
        os.makedirs(dst_dir, exist_ok=True)

        stl_files = [f for f in os.listdir(src_dir) if f.endswith(".stl")]
        print(f"\n[{folder}] {len(stl_files)} files …")

        for fname in sorted(stl_files):
            src_path = os.path.join(src_dir, fname)
            dst_path = os.path.join(dst_dir, fname)

            # Skip if already cached at small enough size
            if os.path.exists(dst_path):
                size_mb = os.path.getsize(dst_path) / 1e6
                if size_mb < 2.0:           # already ≤20k faces
                    total_skip += 1
                    continue

            t1 = time.time()
            try:
                mesh = trimesh.load(src_path, force='mesh')
                decimated = mesh.simplify_quadric_decimation(face_count=FACE_TARGET)
                decimated.export(dst_path)
                elapsed = time.time() - t1
                size_mb = os.path.getsize(dst_path) / 1e6
                print(f"  ✓ {fname}  {size_mb:.1f}MB  {elapsed:.1f}s")
                total_done += 1
            except Exception as e:
                print(f"  ✗ {fname}  ERROR: {e}")
                total_err += 1

    total_time = time.time() - t0
    print(f"\nDone — processed={total_done}, skipped={total_skip}, errors={total_err}")
    print(f"Total time: {total_time/60:.1f} min")

if __name__ == "__main__":
    run()
