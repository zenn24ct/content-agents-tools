#!/usr/bin/env python
"""Prepare a custom asset for the material-agent pipeline.

Does two chores automatically so a new asset needs no hand-editing:

  1. Skeletal-mesh guard - OVRTX crashes deterministically on UsdSkel
     (skinning). If the input USD has any active SkelRoot/Skeleton, its
     skinning is baked at the start frame into a static mesh written next to
     the source (`<name>_static.usd`), and that path is used instead.

  2. Config generation - copies the repo's unified_example.yaml and overrides
     only project name/session/description, input.usd_path,
     input.reference_images and materials.path (all absolute), writing
     apps/material_agent/configs/<name>.yaml.

Prints the results as KEY=VALUE lines for the shell wrapper to read:
    EFFECTIVE_USD=<abs path actually rendered>
    CONFIG=<abs path of generated config>
    SESSION=<session id / output subdir name>
    BAKED=1|0
"""
import argparse
import glob
import os
import sys

import yaml
from pxr import Usd, UsdGeom, UsdSkel, Vt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MATERIALS = os.path.join(
    REPO, "apps/material_agent/data/materials/material_libs_default/materials.yaml"
)
TEMPLATE = os.path.join(REPO, "apps/material_agent/configs/unified_example.yaml")
CONFIGS_DIR = os.path.join(REPO, "apps/material_agent/configs")

SKEL_PROPS = (
    "primvars:skel:jointIndices", "primvars:skel:jointWeights",
    "primvars:skel:geomBindTransform", "primvars:skel:joints",
    "skel:skeleton", "skel:animationSource", "skel:blendShapes",
    "skel:blendShapeTargets",
)
REF_EXTS = ("*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG", "*.JPEG")


def has_active_skel(stage):
    for prim in stage.Traverse():
        if prim.GetTypeName() in ("SkelRoot", "Skeleton", "SkelAnimation") and prim.IsActive():
            return True
    return False


def bake_static(src, dst):
    """Freeze UsdSkel skinning at the start frame into a static mesh."""
    st = Usd.Stage.Open(src)
    t = Usd.TimeCode(st.GetStartTimeCode() or 0.0)

    baked = {}
    cache = UsdSkel.Cache()
    for prim in st.Traverse():
        if prim.IsA(UsdSkel.Root):
            root = UsdSkel.Root(prim)
            cache.Populate(root, Usd.PrimDefaultPredicate)
            for binding in cache.ComputeSkelBindings(root, Usd.PrimDefaultPredicate):
                skel_query = cache.GetSkelQuery(binding.GetSkeleton())
                xf = skel_query.ComputeSkinningTransforms(t)
                for sq in binding.GetSkinningTargets():
                    mprim = sq.GetPrim()
                    pts = UsdGeom.Mesh(mprim).GetPointsAttr().Get(t)
                    if not pts:
                        continue
                    pts = Vt.Vec3fArray(pts)
                    if sq.ComputeSkinnedPoints(xf, pts, t):
                        baked[mprim.GetPath()] = pts

    out = Usd.Stage.Open(st.Flatten())

    # Collect paths first: deactivating a Skeleton expires its descendants, so
    # holding prim handles across the edits would blow up mid-traversal.
    mesh_paths, skelroot_paths, deactivate_paths = [], [], []
    for prim in out.Traverse():
        tn = prim.GetTypeName()
        if prim.IsA(UsdGeom.Mesh):
            mesh_paths.append(prim.GetPath())
        if tn == "SkelRoot":
            skelroot_paths.append(prim.GetPath())
        elif tn in ("Skeleton", "SkelAnimation"):
            deactivate_paths.append(prim.GetPath())

    for path in mesh_paths:
        prim = out.GetPrimAtPath(path)
        mesh = UsdGeom.Mesh(prim)
        pa = mesh.GetPointsAttr()
        pa.Clear()
        if path in baked:
            pa.Set(baked[path])
        pts = pa.Get()
        if pts:
            ext = UsdGeom.PointBased(prim).ComputeExtent(pts)
            if ext:
                mesh.GetExtentAttr().Set(ext)
        for p in SKEL_PROPS:
            if prim.HasProperty(p):
                prim.RemoveProperty(p)

    for path in skelroot_paths:
        out.GetPrimAtPath(path).SetTypeName("Xform")

    # Deepest first so a parent's deactivation never invalidates a pending child.
    for path in sorted(deactivate_paths, key=lambda p: len(p.pathString), reverse=True):
        prim = out.GetPrimAtPath(path)
        if prim:
            prim.SetActive(False)

    out.SetStartTimeCode(0.0)
    out.SetEndTimeCode(0.0)
    out.GetRootLayer().Export(dst)


def find_refs(usd_dir):
    """Auto-discover reference images near the asset (thumbnails/ first)."""
    found = []
    for sub in ("thumbnails", "thumbnail", "."):
        base = os.path.join(usd_dir, sub)
        for pat in REF_EXTS:
            found += glob.glob(os.path.join(base, pat))
        if found:
            break
    return sorted(set(os.path.abspath(f) for f in found))


def write_config(name, usd_path, refs, materials, out_path):
    with open(TEMPLATE) as f:
        cfg = yaml.safe_load(f)
    cfg["project"]["name"] = name
    cfg["project"]["session_id"] = name
    cfg["project"]["description"] = f"Custom asset '{name}' material assignment"
    cfg["input"]["usd_path"] = usd_path
    cfg["input"]["reference_images"] = refs
    cfg["materials"]["path"] = materials
    with open(out_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True, width=100000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--usd", required=True, help="USD file (or dir containing one)")
    ap.add_argument("--ref", action="append", default=[], help="reference image (repeatable)")
    ap.add_argument("--materials", default=DEFAULT_MATERIALS)
    ap.add_argument("--no-static", action="store_true", help="skip skeletal baking")
    ap.add_argument("--force", action="store_true", help="overwrite existing config")
    args = ap.parse_args()

    usd = os.path.abspath(args.usd)
    if os.path.isdir(usd):
        cands = []
        for pat in ("*.usd", "*.usdc", "*.usda", "*.usdz"):
            cands += glob.glob(os.path.join(usd, pat))
        cands = [c for c in cands if "_static" not in os.path.basename(c)]
        if len(cands) != 1:
            sys.exit(f"ERROR: expected exactly one USD in {usd}, found {cands}")
        usd = cands[0]
    if not os.path.isfile(usd):
        sys.exit(f"ERROR: USD not found: {usd}")

    usd_dir = os.path.dirname(usd)
    materials = os.path.abspath(args.materials)
    if not os.path.isfile(materials):
        sys.exit(f"ERROR: materials manifest not found: {materials}")

    # 1. skeletal guard
    baked = 0
    effective = usd
    if not args.no_static:
        try:
            stage = Usd.Stage.Open(usd)
            if has_active_skel(stage):
                dst = os.path.join(usd_dir, f"{args.name}_static.usd")
                print(f">> UsdSkel detected -> baking static mesh: {dst}", file=sys.stderr)
                bake_static(usd, dst)
                effective = dst
                baked = 1
            else:
                print(">> no active UsdSkel; using source USD as-is", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            sys.exit(f"ERROR: skeletal check/bake failed: {e}")

    # 2. reference images
    refs = [os.path.abspath(r) for r in args.ref]
    missing = [r for r in refs if not os.path.isfile(r)]
    if missing:
        sys.exit(f"ERROR: reference image(s) not found: {missing}")
    if not refs:
        refs = find_refs(usd_dir)
        if refs:
            print(f">> auto-found {len(refs)} reference image(s)", file=sys.stderr)
        else:
            print(">> WARNING: no reference images found; material matching will be weak",
                  file=sys.stderr)

    # 3. config
    out_path = os.path.join(CONFIGS_DIR, f"{args.name}.yaml")
    if os.path.exists(out_path) and not args.force:
        sys.exit(f"ERROR: config exists: {out_path} (use --force to overwrite)")
    write_config(args.name, effective, refs, materials, out_path)

    print(f"EFFECTIVE_USD={effective}")
    print(f"CONFIG={out_path}")
    print(f"SESSION={args.name}")
    print(f"BAKED={baked}")


if __name__ == "__main__":
    main()
