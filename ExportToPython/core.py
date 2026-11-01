"""
    Core exporter functionality for Build123D Python script generation.

    Written by Ran Peleg, Visionware Solutions Pty Ltd
    ran@visionware.com.au
    Provided as-is, without warranty of any kind under Apache-2.0 license
"""

from __future__ import annotations

import keyword
import math
import os
import re
from typing import Iterable, List, Optional, Tuple

import adsk.core
import adsk.fusion

import Utils


class _BodyUnionFind:
    """Minimal union-find used to partition timeline entities by Fusion body."""

    def __init__(self):
        self._parent: dict = {}

    def find(self, key):
        self._parent.setdefault(key, key)
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, key_a, key_b):
        root_a, root_b = self.find(key_a), self.find(key_b)
        if root_a != root_b:
            self._parent[root_a] = root_b

class ExporterCore:
    def export(self):
            document = adsk.core.Application.get().activeDocument
            model_name = document.name if document else os.path.splitext(os.path.basename(self.script_path))[0]
            model_var = Utils._safe_var_name(model_name)
            self.model_var = model_var
            self.current_body_var = model_var
            build_function_name = f"build_{model_var}"

            exportable_entities = self._collect_exportable_entities()
            self._uses_chamfer = self._entities_include_chamfer(exportable_entities)

            self._write_header()
            self._register_user_parameters()
            self._write_parameter_variables()

            body_groups = self._partition_entities_by_body(exportable_entities)
            body_vars = self._assign_body_vars(body_groups, model_var, build_function_name)
            self._remember_body_vars(body_groups, body_vars)

            self.writer.line()
            self.writer.line()
            with self.writer.block(f"def {build_function_name}():"):
                if not body_groups:
                    self.writer.line("pass")

                for group, body_var in zip(body_groups, body_vars):
                    display_name = self._body_display_name(group)
                    self.current_body_var = body_var

                    self.writer.line()
                    if len(body_groups) > 1:
                        # Only annotate which Fusion body a block corresponds to
                        # once there's more than one -- for the common single-body
                        # case this stays silent, matching the pre-multi-body output.
                        self.writer.line(f"# Body: {display_name or body_var}")
                        _comp_name = self._group_component_name(group)
                        if _comp_name:
                            self.writer.line(f"# Component: {_comp_name}")

                    with self.writer.block(f"with BuildPart() as {body_var}:"):
                        if not group:
                            self.writer.line("pass")

                        exported_features_count = 0
                        for _timeline_index, entity in group:
                            self._export_entity(exported_features_count + 1, entity)
                            exported_features_count += 1

                self.writer.line()
                self._export_part_color(body_groups, body_vars)
                self.writer.line()
                if len(body_vars) <= 1:
                    single_var = body_vars[0] if body_vars else model_var
                    self.writer.line(f"return {single_var}.part")
                else:
                    parts_expr = ", ".join(f"{var}.part" for var in body_vars)
                    self.writer.line(f"return [{parts_expr}]")

            # Sketch-only Fusion geometry (unused sketches / curves / text):
            # module-level data + a separate viewer function, never part of
            # the BuildPart blocks above (LITTLEFOOT local change).
            self._write_sketch_only_section()

            # Assembly data (occurrence placements, joints, ...): plain module-level
            # data for converters, never used by build_*() (LITTLEFOOT local change).
            self._write_assembly_section()

            self.writer.line()
            self.writer.line()
            self.writer.line('if __name__ == "__main__":')
            self.writer.level += 1
            if len(body_vars) <= 1:
                self.writer.line(f"part = {build_function_name}()")
                self.writer.line()
                self.writer.line('from ocp_vscode import show')
                self.writer.line('show(part)')
                self.writer.line()
                self.writer.line('# Export to STL and show file using PyVista')
                self.writer.line('#export_stl(part, "part.stl")')
                self.writer.line("#import pyvista as pv")
                self.writer.line('#mesh = pv.read("part.stl")')
                self.writer.line('#plotter = pv.Plotter()')
                self.writer.line('#plotter.add_mesh(mesh)')
                self.writer.line('#plotter.show()')
            else:
                self.writer.line(f"parts = {build_function_name}()  # one Part per Fusion body")
                self.writer.line()
                self.writer.line('from ocp_vscode import show')
                self.writer.line('show(*parts)')
                self.writer.line()
                self.writer.line('# Export each body to its own STL and show the combined result using PyVista')
                self.writer.line('#for i, body_part in enumerate(parts):')
                self.writer.line('#    export_stl(body_part, f"part_{i}.stl")')
                self.writer.line("#import pyvista as pv")
                self.writer.line('#plotter = pv.Plotter()')
                self.writer.line('#for i in range(len(parts)):')
                self.writer.line('#    plotter.add_mesh(pv.read(f"part_{i}.stl"))')
                self.writer.line('#plotter.show()')
            self.writer.level -= 1

            if self.unsupported:
                self.writer.line()
                self.writer.line("# Export notes:")
                for note in self.unsupported:
                    self.writer.line(f"# - {note}")

            with open(self.script_path, "w", encoding="utf-8", newline="\n") as out_file:
                out_file.write(self.writer.text())

    # ------------------------------------------------------------------ assembly data (LITTLEFOOT)
    def _group_component_name(self, group) -> Optional[str]:
            try:
                body = self._first_body_for_group(group)
                comp = Utils._safe_getattr(body, "parentComponent", None) if body is not None else None
                name = Utils._safe_getattr(comp, "name", None)
                return str(name).replace("\n", " ") if name else None
            except Exception:
                return None

    def _write_assembly_section(self):
            try:
                data = self._collect_assembly()
            except Exception as e:
                self.unsupported.append(f"assembly data not exported: {e}")
                return
            try:
                import pprint
                text = "FUSION_ASSEMBLY = " + pprint.pformat(data, width=110, sort_dicts=False)
                compile(text, "<FUSION_ASSEMBLY>", "exec")
            except Exception as e:
                self.unsupported.append(f"assembly data not exported: {e}")
                return
            self.writer.line()
            self.writer.line()
            self.writer.line("# Fusion assembly data: every occurrence with its world transform (row-major 4x4,")
            self.writer.line("# translation in mm), joints, as-built joints, joint origins, rigid groups and the timeline's")
            self.writer.line("# snapshots / motion links. Body geometry above is in its component's own coordinates.")
            self.writer.line("# Plain data for converters; build_*() does not use it.")
            for ln in text.splitlines():
                self.writer.line(ln)

    def _collect_assembly(self) -> dict:
            design = self.design
            root = design.rootComponent

            def g(fn, default=None):
                try:
                    return fn()
                except Exception:
                    return default

            def mat(m):
                a = g(lambda: [float(x) for x in m.asArray()])
                if not a or len(a) != 16:
                    return None
                for k in (3, 7, 11):
                    a[k] *= 10.0
                return [round(x, 6) for x in a]

            def pt(p):
                return g(lambda: [round(p.x * 10.0, 6), round(p.y * 10.0, 6), round(p.z * 10.0, 6)])

            def vec(v):
                return g(lambda: [round(v.x, 6), round(v.y, 6), round(v.z, 6)])

            def occ_path(o):
                if o is None:
                    return None
                return g(lambda: o.fullPathName) or g(lambda: o.name)

            def expr(p):
                return g(lambda: p.expression) if p is not None else None

            def geometry(geo):
                if geo is None:
                    return None
                jo = g(lambda: adsk.fusion.JointOrigin.cast(geo))
                if jo:
                    d = {"joint_origin": g(lambda: jo.name)}
                    geo2 = g(lambda: jo.geometry)
                    if geo2 is not None:
                        d.update(geometry(geo2) or {})
                    return d
                return {"origin": pt(g(lambda: geo.origin)), "z": vec(g(lambda: geo.primaryAxisVector)),
                        "x": vec(g(lambda: geo.secondaryAxisVector)), "y": vec(g(lambda: geo.thirdAxisVector))}

            jtypes = {0: "rigid", 1: "revolute", 2: "slider", 3: "cylindrical", 4: "pin_slot", 5: "planar", 6: "ball"}

            occurrences = []
            for o in Utils._iter_fusion_collection(g(lambda: root.allOccurrences)) or []:
                comp = g(lambda: o.component)
                occurrences.append({
                    "path": occ_path(o), "name": g(lambda: o.name), "component": g(lambda: comp.name),
                    "transform": mat(g(lambda: o.transform2)),
                    "visible": g(lambda: bool(o.isLightBulbOn and o.isVisible), True),
                    "grounded": g(lambda: bool(o.isGrounded), False),
                    "bodies": [g(lambda: b.name) for b in (Utils._iter_fusion_collection(g(lambda: comp.bRepBodies)) or [])],
                })

            def joint_entry(j, as_built=False):
                motion = g(lambda: j.jointMotion)
                d = {"name": g(lambda: j.name), "type": jtypes.get(g(lambda: motion.jointType), str(g(lambda: motion.jointType))),
                     "as_built": as_built,
                     "occurrence_one": occ_path(g(lambda: j.occurrenceOne)), "occurrence_two": occ_path(g(lambda: j.occurrenceTwo)),
                     "suppressed": g(lambda: bool(j.isSuppressed), False),
                     "component": g(lambda: j.parentComponent.name)}
                if as_built:
                    d["geometry"] = geometry(g(lambda: j.geometry))
                else:
                    d["geometry_one"] = geometry(g(lambda: j.geometryOrOriginOne))
                    d["geometry_two"] = geometry(g(lambda: j.geometryOrOriginTwo))
                    d["offset"] = expr(g(lambda: j.offset))
                    d["angle"] = expr(g(lambda: j.angle))
                    d["flipped"] = g(lambda: bool(j.isFlipped))
                d["rotation"] = expr(g(lambda: motion.rotationValue)) if g(lambda: motion.rotationValue) is not None else None
                d["slide"] = g(lambda: round(float(motion.slideValue) * 10.0, 6))
                return d

            joints = [joint_entry(j) for j in (Utils._iter_fusion_collection(g(lambda: root.allJoints)) or [])]
            joints += [joint_entry(j, True) for j in (Utils._iter_fusion_collection(g(lambda: root.allAsBuiltJoints)) or [])]
            origins = []
            for jo in Utils._iter_fusion_collection(g(lambda: root.allJointOrigins)) or []:
                d = {"name": g(lambda: jo.name), "component": g(lambda: jo.parentComponent.name)}
                d.update(geometry(g(lambda: jo.geometry)) or {})
                origins.append(d)
            groups = []
            for rg in Utils._iter_fusion_collection(g(lambda: root.allRigidGroups)) or []:
                groups.append({"name": g(lambda: rg.name), "occurrences": [occ_path(o) for o in (Utils._iter_fusion_collection(g(lambda: rg.occurrences)) or [])]})
            timeline = []
            tl = g(lambda: design.timeline)
            for i in range(g(lambda: tl.count, 0) or 0):
                item = g(lambda: tl.item(i))
                ent = g(lambda: item.entity)
                ot = g(lambda: ent.objectType, "") or ""
                if any(k in ot for k in ("Joint", "Snapshot", "MotionLink", "RigidGroup")):
                    timeline.append({"index": i, "name": g(lambda: item.name), "type": ot.split("::")[-1],
                                     "component": g(lambda: ent.parentComponent.name),
                                     "suppressed": g(lambda: bool(item.isSuppressed), False)})
            return {"version": 1, "units": "mm", "body_coordinates": "component",
                    "root_component": g(lambda: root.name), "root_bodies": [g(lambda: b.name) for b in (Utils._iter_fusion_collection(g(lambda: root.bRepBodies)) or [])],
                    "occurrences": occurrences, "joints": joints, "joint_origins": origins,
                    "rigid_groups": groups, "timeline": timeline}

    def _collect_exportable_entities(self) -> List[Tuple[int, object]]:
            """Walk the timeline once and return the (index, entity) pairs that
            actually get exported -- same filtering export() always applied
            (skip unresolved/suppressed timeline items, bare sketches and
            construction planes) -- so _partition_entities_by_body can see the
            whole feature list before any code is written. This has to happen
            as its own pass: which body a late feature belongs to (e.g. a Join
            far down the timeline) can retroactively merge two body groups that
            were already accumulating separately, so grouping needs the full
            list up front rather than being decided feature-by-feature.
            """
            timeline = self.design.timeline
            exportable: List[Tuple[int, object]] = []
            for index in range(timeline.count):
                exportable.extend(self._collect_from_timeline_object(index, timeline.item(index)))
            return exportable

    def _collect_from_timeline_object(self, index: int, timeline_obj) -> List[Tuple[int, object]]:
            """Return the (index, entity) pairs one top-level timeline slot
            contributes -- ordinarily zero or one, but a *timeline group*
            (features the user collapsed into a folder in the timeline UI)
            occupies a single top-level slot while wrapping a whole run of its
            own child TimelineObjects, each with its own geometry-producing
            entity. Those groups are expanded here rather than skipped,
            recursing in case a group itself contains a nested group, so their
            contents still get exported in their original relative order.
            """
            if Utils._safe_getattr(timeline_obj, "isGroup", False):
                group = Utils._safe_cast(adsk.fusion.TimelineGroup.cast, timeline_obj) or timeline_obj
                collected: List[Tuple[int, object]] = []
                for child_index in range(Utils._safe_getattr(group, "count", 0) or 0):
                    child = group.item(child_index)
                    child_position = Utils._safe_getattr(child, "index", index)
                    collected.extend(self._collect_from_timeline_object(child_position, child))
                return collected

            try:
                entity = timeline_obj.entity
            except RuntimeError as e:
                name = Utils._safe_getattr(timeline_obj, "name", f"timeline item {index}")
                self.unsupported.append(f"{name}: skipped, {e}")
                return []
            if entity is None:
                return []

            if Utils._safe_getattr(timeline_obj, "isSuppressed", False):
                # A suppressed feature contributes no geometry to Fusion's
                # current computed model (it's greyed out in the timeline),
                # so re-creating it here would produce a script that
                # doesn't match what the design actually looks like.
                return []

            if entity.objectType == adsk.fusion.Sketch.classType() or entity.objectType == adsk.fusion.ConstructionPlane.classType():
                # Ignore pure sketches and planes as they are used by other features and don't create geometry themselves
                return []

            if entity.objectType == adsk.fusion.Occurrence.classType() or entity.objectType == adsk.fusion.Component.classType():
                # Ignore component/occurrence timeline entries (e.g. "new component" creation) --
                # they don't themselves create exportable body geometry, and any bodies inside
                # them get picked up via their own feature entries elsewhere in the timeline.
                return []

            return [(index, entity)]

    def _entities_include_chamfer(self, entities: List[Tuple[int, object]]) -> bool:
            for _index, entity in entities:
                if Utils._safe_getattr(entity, "objectType", None) == adsk.fusion.ChamferFeature.classType():
                    return True
            return False

    def _body_tokens_for_entity(self, entity) -> List[str]:
            """Return the entityTokens of every BRepBody `entity` produces or
            touches, used to decide which export group (see
            _partition_entities_by_body) it belongs to. Most timeline feature
            types expose this directly via `.bodies`; a few (some HoleFeature
            cases) don't, so this falls back to reading it off `.faces[i].body`.
            """
            tokens: List[str] = []
            for body in Utils._iter_fusion_collection(Utils._safe_getattr(entity, "bodies", None)) or []:
                token = Utils._safe_getattr(body, "entityToken", None)
                if token and token not in tokens:
                    tokens.append(token)
            if tokens:
                return tokens

            for face in Utils._iter_fusion_collection(Utils._safe_getattr(entity, "faces", None)) or []:
                body = Utils._safe_getattr(face, "body", None)
                token = Utils._safe_getattr(body, "entityToken", None)
                if token and token not in tokens:
                    tokens.append(token)
            return tokens

    def _partition_entities_by_body(
            self, entities: List[Tuple[int, object]]
        ) -> List[List[Tuple[int, object]]]:
            """Group exported timeline entities by the independent Fusion body
            they belong to, so each body gets its own `with BuildPart() as ...:`
            block in the generated script instead of every feature being
            flattened into one implicit union (which is exactly right when the
            design has a single body, but silently fuses unrelated bodies
            together otherwise).

            Grouping uses a union-find (_BodyUnionFind) over BRepBody
            entityTokens: two bodies become one group the moment any single
            feature touches both (a Join operation, or a fillet/pattern/mirror
            applied across bodies at once), since from that point on they really
            are one part. A feature whose bodies can't be determined at all
            (_body_tokens_for_entity comes back empty) is folded into whichever
            group the immediately preceding timeline feature belongs to, since
            in practice these operate on "whatever's currently being built".
            Groups are returned in first-appearance timeline order, and each
            group's own entities keep their original relative timeline order.
            """
            entity_tokens: List[Tuple[Tuple[int, object], List[str]]] = []
            union_find = _BodyUnionFind()
            for item in entities:
                _index, entity = item
                tokens = self._body_tokens_for_entity(entity)
                entity_tokens.append((item, tokens))
                for token in tokens[1:]:
                    union_find.union(tokens[0], token)

            groups: List[List[Tuple[int, object]]] = []
            group_by_root: dict = {}
            fallback_root = None

            for item, tokens in entity_tokens:
                if tokens:
                    root = union_find.find(tokens[0])
                    fallback_root = root
                else:
                    root = fallback_root if fallback_root is not None else "__unknown_body__"

                bucket = group_by_root.get(root)
                if bucket is None:
                    bucket = []
                    group_by_root[root] = bucket
                    groups.append(bucket)
                bucket.append(item)

            return groups

    def _body_display_name(self, group: List[Tuple[int, object]]) -> Optional[str]:
            """Fusion display name (e.g. 'Bracket') of the body a group of
            timeline entities corresponds to, for the `# Body: ...` comment and
            as a preferred BuildPart variable name -- or None if it can't be
            determined, in which case a generic name is used instead."""
            body = self._first_body_for_group(group)
            return Utils._safe_getattr(body, "name", None) if body is not None else None

    def _first_body_for_group(self, group: List[Tuple[int, object]]):
            for _index, entity in group:
                for body in Utils._iter_fusion_collection(Utils._safe_getattr(entity, "bodies", None)) or []:
                    return body
            for _index, entity in group:
                for face in Utils._iter_fusion_collection(Utils._safe_getattr(entity, "faces", None)) or []:
                    body = Utils._safe_getattr(face, "body", None)
                    if body is not None:
                        return body
            return None

    def _assign_body_vars(
            self, body_groups: List[List[Tuple[int, object]]], model_var: str, build_function_name: str
        ) -> List[str]:
            """Pick a unique Python variable name for each body group's
            BuildPart. A single-body design keeps using `model_var` exactly as
            before this multi-body split existed, so existing single-body
            exports are unaffected. With multiple bodies, each block prefers the
            body's own Fusion name (sanitized) and falls back to
            `{model_var}_bodyN`.
            """
            if len(body_groups) <= 1:
                return [model_var] if body_groups else []

            reserved = {"part", "self", build_function_name} | set(self.parameter_vars.values())
            body_vars: List[str] = []
            for group_index, group in enumerate(body_groups):
                display_name = self._body_display_name(group)
                candidate = Utils._safe_var_name(display_name) if display_name else None
                if not candidate:
                    candidate = f"{model_var}_body{group_index + 1}"

                base_candidate = candidate
                suffix = 2
                while candidate in reserved or candidate in body_vars:
                    candidate = f"{base_candidate}_{suffix}"
                    suffix += 1

                body_vars.append(candidate)
            return body_vars

    def _remember_body_vars(self, body_groups: List[List[Tuple[int, object]]], body_vars: List[str]):
            """Cache the generated BuildPart variable for each Fusion body token.

            Copy/paste body features create a new body from a previously built
            source body, so their export needs a stable way to refer back to the
            source body's BuildPart block.
            """
            self._body_var_by_token = {}
            for group, body_var in zip(body_groups, body_vars):
                for _index, entity in group:
                    for body in Utils._iter_fusion_collection(Utils._safe_getattr(entity, "bodies", None)) or []:
                        token = Utils._safe_getattr(body, "entityToken", None)
                        if token:
                            self._body_var_by_token[token] = body_var

    def _write_header(self):
            self.writer.line('"""Parametric Build123D model exported from Autodesk Fusion 360.')
            self.writer.line()
            self.writer.line("This file is generated from Fusion timeline features where they can be")
            self.writer.line("mapped to native Build123D operators. Sketch text is")
            self.writer.line("re-created with Text() rather than as raw glyph outline curves; the")
            self.writer.line("rendered result depends on the named font being available on this")
            self.writer.line("system and may differ slightly from Fusion's own font rendering.")
            self.writer.line()
            self.writer.line("Fusion sketch geometry that no feature uses (engraving text, initials,")
            self.writer.line("signature curves, reference lines) is listed in SKETCH_ONLY near the end")
            self.writer.line("of this file; it is kept for reference and does not change the part.")
            self.writer.line('"""')
            self.writer.line()
            self.writer.line("from build123d import *")
            if self._uses_chamfer:
                self.writer.line()
                self.writer.line()
                self.writer.line("def _fusion_chamfer(objects, length, length2=None, reference=None):")
                self.writer.level += 1
                self.writer.line("try:")
                self.writer.level += 1
                self.writer.line("return chamfer(objects, length=length, length2=length2, reference=reference)")
                self.writer.level -= 1
                self.writer.line("except ValueError as exc:")
                self.writer.level += 1
                self.writer.line('if "Failed creating a chamfer" not in str(exc):')
                self.writer.level += 1
                self.writer.line("raise")
                self.writer.level -= 1
                self.writer.line("epsilon = max(1e-6, abs(length) * 1e-6)")
                self.writer.line("safe_length = max(0.0, length - epsilon)")
                self.writer.line("safe_length2 = None if length2 is None else max(0.0, length2 - epsilon)")
                self.writer.line("return chamfer(objects, length=safe_length, length2=safe_length2, reference=reference)")
                self.writer.level -= 1
                self.writer.level -= 1
            self.writer.line()

    def _is_fusion_type(self, object_type: str, class_name: str) -> bool:
            cls = getattr(adsk.fusion, class_name, None)
            if cls is None:
                return False
            try:
                return object_type == cls.classType()
            except Exception:
                return False

    def _export_entity(self, entity_index: int, entity):
            name = getattr(entity, "name", "Unnamed")
            object_type = entity.objectType
            self.writer.line()
            self.writer.line(f"# {entity_index}: {name}")

            sketch_only_snapshot = None
            try:
                sketch_only_snapshot = self._sketch_only_snapshot()
            except Exception:
                pass
            exported_ok = True
            try:
                if self._is_fusion_type(object_type, "BoxFeature"):
                    self._export_box_primitive(entity)
                elif self._is_fusion_type(object_type, "CylinderFeature"):
                    self._export_cylinder_primitive(entity)
                elif self._is_fusion_type(object_type, "SphereFeature"):
                    self._export_sphere_primitive(entity)
                elif self._is_fusion_type(object_type, "TorusFeature"):
                    self._export_torus_primitive(entity)
                elif object_type == adsk.fusion.ExtrudeFeature.classType():
                    self._export_extrude(entity)
                elif object_type == adsk.fusion.RevolveFeature.classType():
                    self._export_revolve(entity)
                elif object_type == adsk.fusion.SweepFeature.classType():
                    self._export_sweep(entity)
                elif object_type == adsk.fusion.FilletFeature.classType():
                    self._export_fillet(entity)
                elif object_type == adsk.fusion.ChamferFeature.classType():
                    self._export_chamfer(entity)
                elif object_type == adsk.fusion.ShellFeature.classType():
                    self._export_shell(entity)
                elif object_type == adsk.fusion.HoleFeature.classType():
                    self._export_hole(entity)
                elif object_type == adsk.fusion.MirrorFeature.classType():
                    self._export_mirror(entity)
                elif object_type == adsk.fusion.RectangularPatternFeature.classType():
                    self._export_rectangular_pattern(entity)
                elif object_type == adsk.fusion.CircularPatternFeature.classType():
                    self._export_circular_pattern(entity)
                elif object_type == adsk.fusion.LoftFeature.classType():
                    self._export_loft(entity)
                elif object_type == adsk.fusion.MoveFeature.classType():
                    self._export_move(entity)
                elif self._is_fusion_type(object_type, "CopyPasteBody"):
                    self._export_copy_paste_body(entity)
                elif object_type == adsk.fusion.ScaleFeature.classType():
                    self._export_scale(entity)
                else:
                    exported_ok = False
                    self.writer.line("# TODO: unsupported Fusion timeline feature.")
                    self.unsupported.append(f"Unsupported feature '{name}' ({object_type}).")
            except Exception as exc:
                exported_ok = False
                self.writer.line(f"# TODO: export failed for this feature: {exc}")
                self.unsupported.append(f"Feature '{name}' failed to export: {exc}")

            # Sketch-only bookkeeping: the sketch geometry of a feature that was
            # exported is "used"; for one that wasn't, forget anything it marked
            # so its sketch is carried through as sketch-only geometry instead.
            try:
                if exported_ok:
                    self._mark_feature_inputs_consumed(entity)
                else:
                    self._sketch_only_restore(sketch_only_snapshot)
            except Exception:
                pass

    def _primitive_first_body(self, feature):
            bodies = Utils._safe_getattr(feature, "bodies", None)
            if bodies is None or bodies.count == 0:
                return None
            return bodies.item(0)
