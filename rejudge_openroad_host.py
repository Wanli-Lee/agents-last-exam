#!/usr/bin/env python3
"""Host-side rejudge for engineering/openroad_sky130_ibex_pnr_signoff.

WHY THIS EXISTS
---------------
This task's verifier (`scripts/verify_submission.py`) grades a submission by
RE-RUNNING the full OpenROAD RTL-to-GDSII flow under Docker at grade time
(`docker run openroad/orfs@sha256:... make run`, ~2h) and scoring the freshly
regenerated DEF/DRC/LVS/timing artifacts. The score literally does not exist
until that Docker flow executes.

The ALE local-Docker provider runs every task's `evaluate()` *inside* a kasm
container that has NO docker daemon (no CLI, no /var/run/docker.sock), so the
in-container verifier can never run the flow — it always scores 0. (Confirmed:
every local run of this task scored 0.0.) The paper grades this task on a GCE VM
that supports docker-in-docker.

This script runs the task's OWN unmodified verifier ON THE HOST (which has a
working docker daemon + network access to pull the pinned orfs image), against a
previously-saved run's output/. It does not fork the grading logic — it invokes
`verify_submission.py` verbatim, the same command the in-container evaluate()
builds, just where docker actually works. This is the honest way to obtain a real
score for this task without a GCE VM.

USAGE
-----
    python rejudge_openroad_host.py \
        --saved-output <path-to>/v0/<ts>/output \
        [--proxy http://127.0.0.1:7890]   # if orfs image needs a proxy to pull
        [--reference-dir <hf_data>/reference/.../base/reference]
        [--work-dir /dev/shm/openroad_rejudge]
        [--skip-reseed]                   # skip the 2nd docker run (G9), ~halves time

Prints the verifier JSON payload (score / normalized_score / passed / gates) to
stdout, mirroring what evaluate() would have logged.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
TASK_DIR = REPO / "tasks" / "engineering" / "openroad_sky130_ibex_pnr_signoff"
VERIFIER = TASK_DIR / "scripts" / "verify_submission.py"
DEFAULT_REFERENCE = (
    REPO.parent
    / "hf_data" / "reference" / "tasks" / "engineering"
    / "openroad_sky130_ibex_pnr_signoff" / "base" / "reference"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--saved-output", required=True, type=Path,
                    help="The saved run's output/ dir (must contain config.mk + JOURNAL.md).")
    ap.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE,
                    help="Reference dir with frozen_hashes.json, reference_metrics.json, starter_project.zip.")
    ap.add_argument("--work-dir", type=Path, default=None,
                    help="Scratch dir for the graded flow (default: a tempdir under /dev/shm).")
    ap.add_argument("--proxy", default=None,
                    help="HTTP(S) proxy for docker to pull the orfs image, e.g. http://127.0.0.1:7890.")
    ap.add_argument("--skip-reseed", action="store_true",
                    help="Pass --skip-reseed to the verifier (skips the 2nd docker run / G9).")
    args = ap.parse_args()

    sub = args.saved_output.resolve()
    ref = args.reference_dir.resolve()
    if not (sub / "config.mk").exists() or not (sub / "JOURNAL.md").exists():
        print(json.dumps({"error": f"saved output missing config.mk/JOURNAL.md: {sub}",
                          "score": 0.0, "normalized_score": 0.0, "passed": False}))
        return 1
    for req in ("frozen_hashes.json", "reference_metrics.json", "starter_project.zip"):
        if not (ref / req).exists():
            print(json.dumps({"error": f"reference missing {req} in {ref}",
                              "score": 0.0, "normalized_score": 0.0, "passed": False}))
            return 1
    if not VERIFIER.exists():
        print(json.dumps({"error": f"verifier not found: {VERIFIER}"}))
        return 1

    work = (args.work_dir.resolve() if args.work_dir
            else Path(tempfile.mkdtemp(prefix="openroad_rejudge_", dir="/dev/shm")))
    work.mkdir(parents=True, exist_ok=True)

    # The task's verifier hardcodes `sudo -n docker ...` whenever it isn't running
    # as root (verify_submission.py: `if os.geteuid() != 0: command += ["sudo","-n"]`).
    # On a host where the invoking user is in the `docker` group, docker needs no
    # sudo — but `sudo -n docker` still fails ("a password is required"). Rather
    # than edit the task file, drop a transparent `sudo` shim on PATH that strips
    # the `sudo [-n]` prefix and execs the rest directly. The verifier runs
    # unmodified; docker just runs without sudo.
    shim_dir = work / ".sudo_shim"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "sudo"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "# transparent no-op sudo: drop a leading -n/flags, exec the real command\n"
        'args=(); for a in "$@"; do case "$a" in -n|-A|-E|-H|-S) ;; *) args+=("$a");; esac; done\n'
        'exec "${args[@]}"\n'
    )
    shim.chmod(0o755)

    # docker needs the proxy in its client env to pull the orfs image; the flow
    # itself runs offline once the image is local.
    env = dict(os.environ)
    env["PATH"] = f"{shim_dir}:{env.get('PATH','')}"
    if args.proxy:
        for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
            env[k] = args.proxy
        # never proxy the docker unix socket / localhost
        env["no_proxy"] = env.get("no_proxy", "") + ",127.0.0.1,localhost,/var/run/docker.sock"

    cmd = [
        sys.executable, str(VERIFIER),
        "--submission-dir", str(sub),
        "--reference-dir", str(ref),
        "--work-dir", str(work),
    ]
    if args.skip_reseed:
        cmd.append("--skip-reseed")

    print(f"[rejudge_openroad_host] running verifier on host (docker flow ~2h):\n  {' '.join(cmd)}",
          file=sys.stderr, flush=True)
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.stderr.strip():
        print(proc.stderr[-4000:], file=sys.stderr)
    # the verifier prints its JSON payload as the last JSON line of stdout
    out = proc.stdout.strip()
    print(out)
    # surface a clean exit code: 0 if we got a parseable payload
    for line in reversed([l for l in out.splitlines() if l.strip()]):
        try:
            json.loads(line)
            return 0
        except json.JSONDecodeError:
            continue
    return proc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
