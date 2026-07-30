#!/usr/bin/env python
"""Extend the material library with new OpenPBR materials from a recipe.

Each existing material in materials_libs_v2.usd is an OpenPBR/MaterialX network
whose look is driven entirely by the Material prim's interface inputs
(inputs:base_color, inputs:base_metalness, inputs:specular_roughness, ...).
So a new material is produced by copying a template Material prim verbatim
(preserving the whole shader network -> guaranteed to render) and overriding
just those interface inputs.

Recipe (YAML):

    # optional named templates -> existing prim in the base library
    templates:
      metal: Stainless_Steel
      dielectric: Plastic_Red
      glass: Glass_Clear

    materials:
      - name: "Wood Oak"
        description: "Warm medium-brown natural oak wood, matte with visible grain"
        template: dielectric          # template alias or an existing prim name
        inputs:                       # OpenPBR interface inputs to override
          base_color: [0.26, 0.13, 0.05]
          base_metalness: 0.0
          specular_roughness: 0.5
          transmission_weight: 0.0
          subsurface_weight: 0.0

Outputs into --out-dir:
    <lib-name>.usda   (base 74 materials + the new ones, combined)
    materials.yaml    (existing descriptions + the new entries)
"""
import argparse
import os
import re
import sys

import yaml
from pxr import Gf, Sdf, Usd, UsdShade

LOOKS = "/World/Looks"
# inputs whose value is a color3f (everything else in a recipe is treated float)
COLOR_INPUTS = {
    "base_color", "specular_color", "transmission_color", "transmission_scatter",
    "subsurface_color", "subsurface_radius_scale", "coat_color", "fuzz_color",
    "emission_color",
}
DEFAULT_TEMPLATES = {
    "metal": "Stainless_Steel",
    "dielectric": "Plastic_Red",
    "glass": "Glass_Clear",
    "rubber": "Rubber_Black_Matte",
}


def sanitize(name):
    s = re.sub(r"[^0-9A-Za-z_]", "_", name)
    if s and s[0].isdigit():
        s = "_" + s
    return s


def set_input(mat, key, value):
    inp = mat.GetInput(key)
    if key in COLOR_INPUTS or (isinstance(value, (list, tuple)) and len(value) == 3):
        val = Gf.Vec3f(*[float(x) for x in value])
        tname = Sdf.ValueTypeNames.Color3f
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        val = Gf.Vec2f(*[float(x) for x in value])
        tname = Sdf.ValueTypeNames.Float2
    elif isinstance(value, bool):
        val, tname = bool(value), Sdf.ValueTypeNames.Bool
    else:
        val, tname = float(value), Sdf.ValueTypeNames.Float
    if not inp:
        inp = mat.CreateInput(key, tname)
    inp.Set(val)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-lib", required=True, help="existing materials_libs_v2.usd")
    ap.add_argument("--base-yaml", required=True, help="existing materials.yaml (for descriptions)")
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--lib-name", default="materials_libs_extended")
    args = ap.parse_args()

    with open(args.recipe) as f:
        recipe = yaml.safe_load(f)
    templates = dict(DEFAULT_TEMPLATES)
    templates.update(recipe.get("templates") or {})

    stage = Usd.Stage.Open(args.base_lib)  # edited in memory only; never Save()
    layer = stage.GetRootLayer()

    existing = {p.GetName() for p in stage.Traverse() if p.IsA(UsdShade.Material)}
    added = []
    for entry in recipe["materials"]:
        name = entry["name"]
        prim_name = sanitize(name)
        tmpl_name = templates.get(entry.get("template", "dielectric"),
                                  entry.get("template", "dielectric"))
        if tmpl_name not in existing:
            sys.exit(f"ERROR: template '{tmpl_name}' not in base library")
        src = Sdf.Path(f"{LOOKS}/{tmpl_name}")
        dst = Sdf.Path(f"{LOOKS}/{prim_name}")
        if stage.GetPrimAtPath(dst):
            sys.exit(f"ERROR: prim already exists: {dst} (name collision for '{name}')")
        if not Sdf.CopySpec(layer, src, layer, dst):
            sys.exit(f"ERROR: CopySpec failed {src} -> {dst}")
        mat = UsdShade.Material(stage.GetPrimAtPath(dst))
        for key, value in (entry.get("inputs") or {}).items():
            set_input(mat, key, value)
        added.append((name, prim_name, entry.get("description", "")))
        print(f"  + {name}  (template={tmpl_name})", file=sys.stderr)

    os.makedirs(args.out_dir, exist_ok=True)
    out_usd = os.path.join(args.out_dir, f"{args.lib_name}.usda")
    layer.Export(out_usd)

    # merge materials.yaml: keep existing entries, append new
    with open(args.base_yaml) as f:
        base = yaml.safe_load(f)
    entries = list(base.get("entries") or [])
    for name, prim_name, desc in added:
        entries.append({
            "name": name,
            "description": desc,
            "binding": f"{LOOKS}/{prim_name}",
        })
    out_yaml = os.path.join(args.out_dir, "materials.yaml")
    with open(out_yaml, "w") as f:
        yaml.safe_dump(
            {"library_path": f"{args.lib_name}.usda", "entries": entries},
            f, sort_keys=False, allow_unicode=True, width=100000,
        )

    print(f"LIB={out_usd}")
    print(f"YAML={out_yaml}")
    print(f"ADDED={len(added)}")
    print(f"TOTAL={len(entries)}")


if __name__ == "__main__":
    main()
