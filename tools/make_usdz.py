#!/usr/bin/env python
"""Package a pipeline-output USD into a single self-contained .usdz.

The material/texture agents write `output.usd` as a thin layer over the
optimized input, and when the source asset was a .usdz its textures are still
referenced as archive-internal paths (``@0/foo.png@``). Those cannot be
resolved once the layer is flattened on its own, so the usdz writer drops them
and fails. This script unpacks the original .usdz next to the working copy so
the texture paths resolve, then flattens and bundles everything into one file.

    python tools/make_usdz.py <input.usd> <output.usdz> [--source-usdz orig.usdz] [--arkit]

--arkit produces an ARKit/Quick Look compatible package.
"""
import argparse
import os
import shutil
import sys
import tempfile
import zipfile

from pxr import Ar, Usd, UsdUtils


def unpack_source(src_usdz, workdir):
    """Extract the original .usdz so archive-relative texture paths resolve."""
    with zipfile.ZipFile(src_usdz) as z:
        z.extractall(workdir)
    return workdir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="pipeline output .usd")
    ap.add_argument("dst", help="output .usdz")
    ap.add_argument("--source-usdz", help="original .usdz the asset came from")
    ap.add_argument("--arkit", action="store_true")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    dst = os.path.abspath(args.dst)
    if not os.path.isfile(src):
        sys.exit(f"ERROR: not found: {src}")
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)

    tmp = tempfile.mkdtemp(prefix="usdz_pack_")
    try:
        # Flatten into the temp dir; if the asset originated from a .usdz,
        # unpack it there first so its `0/*.png` textures sit alongside.
        if args.source_usdz and os.path.isfile(args.source_usdz):
            unpack_source(os.path.abspath(args.source_usdz), tmp)

        flat_path = os.path.join(tmp, "flat.usdc")
        stage = Usd.Stage.Open(src)
        stage.Flatten().Export(flat_path)

        # Resolve relative asset paths against the unpacked directory.
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            if args.arkit:
                ok = UsdUtils.CreateNewARKitUsdzPackage(flat_path, dst)
            else:
                ok = UsdUtils.CreateNewUsdzPackage(flat_path, dst)
        finally:
            os.chdir(cwd)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not ok or not os.path.exists(dst):
        sys.exit("ERROR: usdz packaging failed")

    print(f"OK {dst} ({os.path.getsize(dst)/1024/1024:.1f} MB)")


if __name__ == "__main__":
    main()
