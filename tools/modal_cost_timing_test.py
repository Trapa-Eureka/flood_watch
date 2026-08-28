"""Week 2-4: measure real Modal cost/cold-start numbers for Prithvi inference,
to replace spec.md's "이벤트당 몇 달러 수준으로 추정(실측 예정)" placeholder.

Separates what Week 2-2's test conflated into one number:
  cold total = container spin-up + model load (no GPU compute) + first inference

...into its two components, using the cheap loaded_at() probe (Week 2-4
addition to modal_app.py, no GPU compute, just returns a timestamp) to detect
whether a call landed on a fresh container or reused a warm one:

  A) loaded_at()  -> forces a fresh container (cold: image pull already cached
     from Week 2-2 + container spin-up + model load onto GPU). No inference.
  B) run()        -> first real inference, should land on the now-warm
     container from (A).
  C) loaded_at()  -> confirms (B) reused (A)'s container (same timestamp) —
     otherwise the whole warm/cold split below would be invalid.
  D) run()        -> second inference on the same warm container — steady-
     state per-request time with zero cold-start cost.

GPU pricing (Nvidia T4, fetched live from https://modal.com/pricing on
2026-08-29): $0.000164/sec. This test does not query Modal's own billing
dashboard (no browser session logged into the user's Modal account is
available here) — cost is computed analytically from measured wall-clock
GPU-seconds x the published rate, which is the same math Modal's own billing
does for a GPU-attached function.

Usage:
  python -m tools.modal_cost_timing_test
"""
import sys
import time
from pathlib import Path

import modal

sys.path.insert(0, ".")
from pipeline import config
from pipeline.inference.modal_app import PrithviInference, app

T4_RATE_PER_SEC = 0.000164  # https://modal.com/pricing, fetched live 2026-08-29

COMPOSITE_PATH = config.DATA_OUTPUT_DIR / "S2A_MSIL2A_20241102T021841_N0511_R003_T51PUS_20241102T150159_composite.tif"


def timed(label, fn):
    t0 = time.time()
    result = fn()
    elapsed = time.time() - t0
    print(f"  [{elapsed:6.1f}s] {label}")
    return result, elapsed


def main():
    composite_bytes = COMPOSITE_PATH.read_bytes()
    print(f"Composite: {COMPOSITE_PATH.name} ({len(composite_bytes)/1e6:.1f}MB)\n")

    inference = PrithviInference()

    print("A) loaded_at() -- forces a fresh container, no GPU inference compute")
    loaded_at_1, t_cold_overhead = timed("cold container spin-up + model load", lambda: inference.loaded_at.remote())

    print("\nB) run() — first real inference, should land on the now-warm container from (A)")
    _, t_first_inference = timed("first inference (on warm container)", lambda: inference.run.remote(composite_bytes, input_indices=[0, 1, 2, 3, 4, 5]))

    print("\nC) loaded_at() — confirm (B) reused (A)'s container")
    loaded_at_2, t_probe = timed("probe (should be near-instant if warm)", lambda: inference.loaded_at.remote())
    same_container = loaded_at_1 == loaded_at_2
    print(f"  loaded_at match: {loaded_at_1} == {loaded_at_2} -> {'SAME container (warm reuse confirmed)' if same_container else 'DIFFERENT container (unexpected!)'}")

    print("\nD) run() — second inference on the same warm container (steady-state)")
    _, t_second_inference = timed("second inference (warm, steady-state)", lambda: inference.run.remote(composite_bytes, input_indices=[0, 1, 2, 3, 4, 5]))

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"cold container overhead (spin-up + model load, no inference): {t_cold_overhead:.1f}s")
    print(f"first inference (on now-warm container):                      {t_first_inference:.1f}s")
    print(f"warm-container inference (steady-state, run #2):              {t_second_inference:.1f}s")
    if not same_container:
        print("WARNING: container was NOT reused between calls — numbers above may not reflect true warm state")

    cold_event_total = t_cold_overhead + t_first_inference
    warm_event_total = t_second_inference

    print(f"\nEstimated full event cost (worst case — cold container + first inference):")
    print(f"  {cold_event_total:.1f}s x ${T4_RATE_PER_SEC}/s (T4) = ${cold_event_total * T4_RATE_PER_SEC:.4f}")
    print(f"Estimated per-event cost if container already warm (burst of events):")
    print(f"  {warm_event_total:.1f}s x ${T4_RATE_PER_SEC}/s (T4) = ${warm_event_total * T4_RATE_PER_SEC:.4f}")
    print(f"\n(CPU/memory attached to the GPU container may add a small additional amount not counted here —")
    print(f" GPU time dominates for this GPU-bound workload, but this isn't a full bill reconciliation.)")
    print(f"\n(Note: one-time image BUILD cost — 144.8s per Week 2-2's first deploy — is a deploy-time cost,")
    print(f" not a per-event cost, and isn't included above.)")


if __name__ == "__main__":
    # Calling .remote() from a plain script (not the `modal run` CLI wrapper)
    # needs an active app context — this is the documented way to do that.
    with modal.enable_output(), app.run():
        main()
