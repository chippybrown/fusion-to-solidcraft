"""
    Additive feature translators for Fusion 360 -> Build123D export.

    Written by Ran Peleg, Visionware Solutions Pty Ltd
    ran@visionware.com.au
    Provided as-is, without warranty of any kind under Apache-2.0 license
"""

from __future__ import annotations

import keyword
import math
import os
import re
import traceback
from typing import Iterable, List, Optional, Tuple

import adsk.core
import adsk.fusion

import Utils

class AdditiveFeatures:
    def _mode_expr(self, operation) -> str:
            if operation == adsk.fusion.FeatureOperations.CutFeatureOperation:
                return "Mode.SUBTRACT"
            if operation == adsk.fusion.FeatureOperations.IntersectFeatureOperation:
                return "Mode.INTERSECT"
            return "Mode.ADD"

    def _taper_degrees(self, parameter) -> float:
            if parameter is None:
                return 0.0
            return math.degrees(parameter.value)

    def _distance_extent_amount(self, extent) -> Optional[Tuple[float, str, str, bool]]:
            distance_extent = adsk.fusion.DistanceExtentDefinition.cast(extent)
            if distance_extent:
                parameter = adsk.fusion.ModelParameter.cast(distance_extent.distance)
                if parameter:
                    expr, comment, is_var = self._param_expr(parameter, "length")
                    return Utils._param_value_mm(parameter), expr, comment, is_var
            return None

    def _to_entity_extent_args(
            self,
            extent,
            reverse_direction: bool = False,
            sketch_origin=None,
            sketch_normal=None,
        ) -> Optional[Tuple[str, str]]:
            to_entity_extent = adsk.fusion.ToEntityExtentDefinition.cast(extent)
            if not to_entity_extent:
                return None

            notes = []
            direction_hint = Utils._safe_getattr(to_entity_extent, "directionHint", None)
            if direction_hint is not None and sketch_normal is not None:
                try:
                    if direction_hint.dotProduct(sketch_normal) < 0:
                        reverse_direction = not reverse_direction
                        notes.append("Fusion direction hint reversed extrusion direction")
                except Exception:
                    notes.append("Fusion direction hint could not be read")

            is_minimum = bool(Utils._safe_getattr(to_entity_extent, "isMinimumSolution", True))
            if reverse_direction:
                until = "Until.PREVIOUS" if is_minimum else "Until.FIRST"
            else:
                until = "Until.NEXT" if is_minimum else "Until.LAST"

            args = [f"until={until}"]

            entity = Utils._safe_getattr(to_entity_extent, "entity", None)
            entity_name = Utils._safe_getattr(entity, "name", None)
            if entity is None:
                entity_type = "unknown entity"
            else:
                entity_type = Utils._safe_getattr(entity, "objectType", None) or type(entity).__name__

            numeric_amount = self._to_entity_extent_amount(to_entity_extent, sketch_origin, sketch_normal, reverse_direction)
            if entity_name:
                notes.append(f"Fusion To Object target: {entity_name} ({entity_type})")
            else:
                notes.append(f"Fusion To Object target: {entity_type}")

            if not is_minimum:
                notes.append("far solution")
            if Utils._safe_getattr(to_entity_extent, "isChained", False):
                notes.append("Fusion chained target faces")

            offset = adsk.fusion.ModelParameter.cast(Utils._safe_getattr(to_entity_extent, "offset", None))
            if offset:
                offset_amount = Utils._param_value_mm(offset)
                if abs(offset_amount) > 1e-9:
                    if numeric_amount is None:
                        notes.append(f"Fusion To Object offset {Utils._fmt(offset_amount)} mm not applied")
                        self.unsupported.append(
                            "A To Object extrude offset was not translated; Build123D extrude(until=...) "
                            "does not directly support Fusion's target offset."
                        )
                    else:
                        notes.append(f"Fusion To Object offset {Utils._fmt(offset_amount)} mm applied")

            if direction_hint is not None and sketch_normal is None:
                notes.append("Fusion direction hint not applied")

            if numeric_amount is not None:
                return f"amount={Utils._fmt(numeric_amount)}", "  # " + "; ".join(notes + ["computed from Fusion To Object target"])

            return ", ".join(args), "  # " + "; ".join(notes)

    def _to_entity_extent_amount(self, to_entity_extent, sketch_origin, sketch_normal, reverse_direction: bool) -> Optional[float]:
            if sketch_origin is None or sketch_normal is None:
                return None

            entity = Utils._safe_getattr(to_entity_extent, "entity", None)
            if entity is None:
                return None

            target_direction = sketch_normal.copy()
            if reverse_direction:
                target_direction.scaleBy(-1)
            target_point = self._target_point_for_to_entity(
                entity,
                target_direction,
                bool(Utils._safe_getattr(to_entity_extent, "isMinimumSolution", True)),
            )
            if target_point is None:
                return None

            vector = adsk.core.Vector3D.create(
                target_point.x - sketch_origin.x,
                target_point.y - sketch_origin.y,
                target_point.z - sketch_origin.z,
            )
            amount = vector.dotProduct(sketch_normal) * Utils.MM_PER_FUSION_UNIT
            if reverse_direction and amount > 0:
                amount = -amount

            offset = adsk.fusion.ModelParameter.cast(Utils._safe_getattr(to_entity_extent, "offset", None))
            if offset:
                amount += Utils._param_value_mm(offset)

            return amount

    def _target_point_for_to_entity(self, entity, direction, is_minimum: bool):
            point = Utils._safe_getattr(entity, "pointOnFace", None)
            if point is not None:
                return point

            geometry = Utils._safe_getattr(entity, "geometry", None)
            origin = Utils._safe_getattr(geometry, "origin", None)
            if origin is not None:
                return origin

            point = Utils._safe_getattr(entity, "geometry", None)
            if Utils._safe_getattr(point, "x", None) is not None:
                return point

            bbox = Utils._safe_getattr(entity, "boundingBox", None)
            if bbox is None:
                return None

            corners = [
                adsk.core.Point3D.create(x, y, z)
                for x in (bbox.minPoint.x, bbox.maxPoint.x)
                for y in (bbox.minPoint.y, bbox.maxPoint.y)
                for z in (bbox.minPoint.z, bbox.maxPoint.z)
            ]
            scored = []
            for corner in corners:
                scored.append((corner.x * direction.x + corner.y * direction.y + corner.z * direction.z, corner))
            scored.sort(key=lambda item: item[0])
            return scored[0][1] if is_minimum else scored[-1][1]

    def _through_all_extent_args(self, extent, reverse_direction: bool = False):
            """Fusion's 'All' extent type extrudes through every solid it meets
            in one direction. Build123D has no direct equivalent keyword, but
            until=Until.LAST already means 'stop at the farthest intersecting
            face' -- i.e. pass through everything -- which is the same target
            behavior, so it's reused here rather than baking a large literal
            distance that could still fall short of (or overshoot into) other
            geometry.
            """
            through_all_extent = adsk.fusion.ThroughAllExtentDefinition.cast(extent)
            if not through_all_extent:
                return None

            is_positive = bool(Utils._safe_getattr(through_all_extent, "isPositiveDirection", True))
            if not is_positive:
                reverse_direction = not reverse_direction

            until = "Until.FIRST" if reverse_direction else "Until.LAST"
            return f"until={until}", "  # Fusion 'All' extent (through all existing geometry)"

    def _extrude_extent_call(
            self,
            sketch_name: str,
            extent,
            taper: float,
            mode: str,
            reverse_direction: bool = False,
            sketch_origin=None,
            sketch_normal=None,
        ):
            extent_amount = self._distance_extent_amount(extent)
            if extent_amount:
                amount, expr, comment, is_var = extent_amount
                if reverse_direction:
                    amount = -amount
                    expr = f"-{expr}" if is_var else Utils._fmt(amount)
                if is_var and sketch_origin is not None and sketch_normal is not None:
                    self._register_parametric_offset_plane(
                        (
                            sketch_origin.x * Utils.MM_PER_FUSION_UNIT,
                            sketch_origin.y * Utils.MM_PER_FUSION_UNIT,
                            sketch_origin.z * Utils.MM_PER_FUSION_UNIT,
                        ),
                        (sketch_normal.x, sketch_normal.y, sketch_normal.z),
                        amount,
                        expr,
                        comment,
                    )
                return f"extrude({sketch_name}.sketch, amount={expr}, taper={Utils._fmt(taper)}, mode={mode}){comment}"

            to_entity_args = self._to_entity_extent_args(extent, reverse_direction, sketch_origin, sketch_normal)
            if to_entity_args:
                args, comment = to_entity_args
                return f"extrude({sketch_name}.sketch, {args}, taper={Utils._fmt(taper)}, mode={mode}){comment}"

            through_all_args = self._through_all_extent_args(extent, reverse_direction)
            if through_all_args:
                args, comment = through_all_args
                return f"extrude({sketch_name}.sketch, {args}, taper={Utils._fmt(taper)}, mode={mode}){comment}"

            return None

    def _export_extrude(self, extrude: adsk.fusion.ExtrudeFeature):
            profile = extrude.profile
            if profile is None:
                raise RuntimeError("Extrude profile is not parametric or is unavailable")

            self.sketch_index += 1
            sketch_name = f"profile_{self.sketch_index}"
            sketch = self._profile_sketch(profile)
            sketch_frame = Utils._sketch_frame(sketch) if sketch is not None else None
            sketch_origin = sketch_frame[0] if sketch_frame is not None else None
            sketch_normal = sketch_frame[3] if sketch_frame is not None else None
            self._export_profile_sketch(profile, sketch_name)

            mode = self._mode_expr(extrude.operation)
            taper = self._taper_degrees(getattr(extrude, "taperAngleOne", None))

            symmetric = adsk.fusion.SymmetricExtentDefinition.cast(extrude.symmetricExtent)
            if symmetric:
                distance = adsk.fusion.ModelParameter.cast(symmetric.distance)
                if distance:
                    amount = Utils._param_value_mm(distance)
                    expr, comment, is_var = self._param_expr(distance, "length")
                else:
                    amount, expr, comment, is_var = 0.0, Utils._fmt(0.0), "", False
                if getattr(symmetric, "isFullLength", False):
                    amount = amount / 2.0
                    expr = f"({expr}) / 2" if is_var else Utils._fmt(amount)
                if is_var and sketch_origin is not None and sketch_normal is not None:
                    base_origin_mm = (
                        sketch_origin.x * Utils.MM_PER_FUSION_UNIT,
                        sketch_origin.y * Utils.MM_PER_FUSION_UNIT,
                        sketch_origin.z * Utils.MM_PER_FUSION_UNIT,
                    )
                    base_normal = (sketch_normal.x, sketch_normal.y, sketch_normal.z)
                    # A symmetric extrude caps both sides of the sketch plane.
                    self._register_parametric_offset_plane(base_origin_mm, base_normal, amount, expr, comment)
                    self._register_parametric_offset_plane(base_origin_mm, base_normal, -amount, f"-({expr})", comment)
                self.writer.line(
                    f"extrude({sketch_name}.sketch, amount={expr}, both=True, taper={Utils._fmt(taper)}, mode={mode}){comment}"
                )
                self.last_extrude_replay = (
                    f"extrude({sketch_name}.sketch, amount={expr}, both=True, taper={Utils._fmt(taper)}, mode={mode})"
                )
                self.last_extrude_sketch_name = sketch_name
                self.last_feature_kind = "extrude"
                return

            extent_one_call = self._extrude_extent_call(
                sketch_name,
                extrude.extentOne,
                taper,
                mode,
                sketch_origin=sketch_origin,
                sketch_normal=sketch_normal,
            )
            if extent_one_call is None:
                self.writer.line("# TODO: unsupported extrude extent; expected Distance, To Object, or All extent.")
                self.unsupported.append(f"Extrude '{extrude.name}' has unsupported extent.")
                return

            if extrude.hasTwoExtents:
                if adsk.fusion.ThroughAllExtentDefinition.cast(extrude.extentOne) and adsk.fusion.ThroughAllExtentDefinition.cast(extrude.extentTwo):
                    self.writer.line(
                        "# Fusion 'Two Sides' extrude with 'All' extent on both sides "
                        "(through all existing geometry in both directions)."
                    )
                extent_two_call = self._extrude_extent_call(
                    sketch_name,
                    extrude.extentTwo,
                    self._taper_degrees(extrude.taperAngleTwo),
                    mode,
                    reverse_direction=True,
                    sketch_origin=sketch_origin,
                    sketch_normal=sketch_normal,
                )
                if extent_two_call:
                    self.writer.line(extent_one_call)
                    self.writer.line(extent_two_call)
                    self.last_extrude_replay = extent_one_call.split("  # ", 1)[0]
                    self.last_extrude_sketch_name = sketch_name
                    self.last_feature_kind = "extrude"
                    return
                self.unsupported.append(f"Extrude '{extrude.name}' has unsupported second extent.")

            self.writer.line(extent_one_call)
            self.last_extrude_replay = extent_one_call.split("  # ", 1)[0]
            self.last_extrude_sketch_name = sketch_name
            self.last_feature_kind = "extrude"

    def _export_revolve(self, revolve: adsk.fusion.RevolveFeature):
            profile = getattr(revolve, "profile", None)
            axis = getattr(revolve, "axis", None)
            if profile is None or axis is None:
                raise RuntimeError("Revolve profile or axis is unavailable")

            self.sketch_index += 1
            sketch_name = f"profile_{self.sketch_index}"
            self._export_profile_sketch(profile, sketch_name)

            axis_geom = getattr(axis, "worldGeometry", None) or getattr(axis, "geometry", None)
            if axis_geom is None:
                raise RuntimeError("Revolve axis geometry is unavailable")

            axis_frame = self._axis_frame_from_line_geometry(axis_geom)

            # axis_geom is a bounded Line3D (startPoint/endPoint) when the axis
            # is a sketch line, but an unbounded InfiniteLine3D (origin/
            # direction instead) when it's a ConstructionAxis or one of the
            # model's built-in X/Y/Z axes -- _axis_expr_from_line_geometry
            # handles both.
            axis_expr = self._axis_expr_from_line_geometry(axis_geom)
            if axis_expr is None:
                raise RuntimeError(f"Revolve axis geometry type {type(axis_geom).__name__} is unsupported")

            angle = 360.0
            angle_expr = Utils._fmt(angle)
            angle_comment = ""
            reflect_revolve_selectors = False
            extent = getattr(revolve, "extentDefinition", None)
            angle_extent = adsk.fusion.AngleExtentDefinition.cast(extent) if extent else None
            if angle_extent:
                angle_param = adsk.fusion.ModelParameter.cast(angle_extent.angle)
                if angle_param:
                    angle = math.degrees(angle_param.value)
                    if angle_extent.isSymmetric:
                        # Fusion sweeps this angle half to each side of the sketch
                        # plane, so the *total* swept angle is correctly doubled
                        # here -- but build123d's revolve() always sweeps
                        # revolution_arc degrees in one direction starting from
                        # the profile's current position; it has no "centered on
                        # the sketch plane" mode. So even with the right total
                        # angle, the emitted revolve is NOT centered like Fusion's
                        # -- it's rotated off by half the swept angle. Flag it
                        # rather than silently emit a mismatched shape.
                        angle *= 2.0
                        angle_expr = Utils._fmt(angle)
                        angle_comment = "  # TODO: Fusion symmetric revolve is centered on the sketch plane; this sweeps the full angle to one side only. Rotate the profile by -{:.5g} deg about the axis before revolving for an exact match.".format(angle / 2.0)
                        self.unsupported.append(
                            f"Revolve '{revolve.name}' uses a symmetric angle extent; total sweep angle was preserved but not centered on the sketch plane."
                        )
                    else:
                        angle_expr, angle_comment, _ = self._angle_expr_preserving_sign(angle_param)
                        angle_expr = self._negated_expr(angle_expr)
                        reflect_revolve_selectors = abs(angle) < 360.0 - 1e-6
            else:
                two_side_angle_extent = adsk.fusion.TwoSidesAngleExtentDefinition.cast(extent) if extent else None
                if two_side_angle_extent:
                    angle_one = adsk.fusion.ModelParameter.cast(two_side_angle_extent.angleOne)
                    angle_two = adsk.fusion.ModelParameter.cast(two_side_angle_extent.angleTwo)
                    if angle_one and angle_two:
                        # Same issue as the isSymmetric case above: Fusion sweeps
                        # angleOne one way and angleTwo the other way from the
                        # sketch plane. Summing them gives the right total angle
                        # but build123d's revolve() sweeps it entirely in one
                        # direction from the profile's position, so the result is
                        # rotated off from Fusion's by angleTwo. Flag it.
                        deg_one = math.degrees(angle_one.value)
                        deg_two = math.degrees(angle_two.value)
                        angle = deg_one + deg_two
                        angle_expr = Utils._fmt(angle)
                        angle_comment = f"  # TODO: Fusion two-sided revolve sweeps {Utils._fmt(deg_one)} deg one way and {Utils._fmt(deg_two)} deg the other from the sketch plane; this sweeps the full {Utils._fmt(angle)} deg to one side only. Rotate the profile by -{Utils._fmt(deg_two)} deg about the axis before revolving for an exact match."
                        self.unsupported.append(
                            f"Revolve '{revolve.name}' uses a two-sided angle extent; total sweep angle was preserved but not split around the sketch plane."
                        )

            if reflect_revolve_selectors and axis_frame is not None:
                self._register_revolve_selector_reflection(profile, axis_frame)

            mode = self._mode_expr(revolve.operation)
            self.writer.line(f"revolve({sketch_name}.sketch, axis={axis_expr}, revolution_arc={angle_expr}, mode={mode}){angle_comment}")

    def _world_point3d(self, point) -> Tuple[float, float, float]:
            return (
                point.x * Utils.MM_PER_FUSION_UNIT,
                point.y * Utils.MM_PER_FUSION_UNIT,
                point.z * Utils.MM_PER_FUSION_UNIT,
            )

    def _curve_world_geometry(self, curve_entity):
            """Get a path curve's geometry in world (model) space.

            Sweep path entities are commonly sketch curves (e.g. a centerline
            drawn in its own sketch) whose plain .geometry is expressed in that
            sketch's *local* 2D frame -- the same worldGeometry-vs-geometry trap
            as the revolve axis. BRepEdge entities (edges of existing solids)
            only expose .geometry, which is already world space, so that's used
            as a fallback.
            """
            # PathEntity -- what a Path yields when iterated -- is a thin
            # wrapper: PathEntity.curve is only documented as "the geometry
            # of the entity" and is NOT guaranteed to be world space (for a
            # sketch-curve-derived path entity it can carry the same local
            # sketch frame as SketchCurve.geometry does -- the same trap this
            # function already exists to avoid). PathEntity.entity gives back
            # the actual SketchCurve/BRepEdge it was derived from, so unwrap
            # to that and let the worldGeometry-vs-geometry handling below do
            # the local-to-world conversion correctly, as it already does for
            # every other curve source in this exporter.
            entity = Utils._safe_getattr(curve_entity, "entity", None)
            if entity is not None:
                curve_entity = entity

            geom = Utils._safe_getattr(curve_entity, "worldGeometry", None)
            if geom is not None:
                return geom
            return Utils._safe_getattr(curve_entity, "geometry", None)

    def _curve_world_endpoints(self, geom) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
            if isinstance(geom, (adsk.core.Line3D, adsk.core.Arc3D)):
                return self._world_point3d(geom.startPoint), self._world_point3d(geom.endPoint)
            if isinstance(geom, (adsk.core.NurbsCurve3D, adsk.core.EllipticalArc3D)):
                ok, param_start, param_end = geom.evaluator.getParameterExtents()
                if not ok:
                    return None
                ok_start, start = geom.evaluator.getPointAtParameter(param_start)
                ok_end, end = geom.evaluator.getPointAtParameter(param_end)
                if not (ok_start and ok_end):
                    return None
                return self._world_point3d(start), self._world_point3d(end)
            return None

    def _order_path_curves(self, curves):
            """Chain path curves into travel order using 3D endpoint matching.

            Returns (ordered [(curve, reverse), ...], is_closed). Falls back to
            Fusion's original collection order (with is_closed=False) if the
            curves can't be read or don't form a single unambiguous chain --
            better to emit something reviewable than to guess at connectivity.
            """
            segments = []
            for curve in curves:
                geom = self._curve_world_geometry(curve)
                endpoints = self._curve_world_endpoints(geom)
                if endpoints is None:
                    return [(c, False) for c in curves], False
                segments.append((curve, endpoints[0], endpoints[1]))

            def same_point(a, b) -> bool:
                return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3))) < 1e-4

            curve, start, end = segments.pop(0)
            ordered = [(curve, False)]
            first_point = start
            last_point = end

            while segments:
                for index, (seg_curve, seg_start, seg_end) in enumerate(segments):
                    if same_point(seg_start, last_point):
                        ordered.append((seg_curve, False))
                        last_point = seg_end
                        segments.pop(index)
                        break
                    if same_point(seg_end, last_point):
                        ordered.append((seg_curve, True))
                        last_point = seg_start
                        segments.pop(index)
                        break
                else:
                    return [(c, False) for c in curves], False

            return ordered, same_point(first_point, last_point)

    def _sample_curve_world(self, geom, count: int = 9) -> List[Tuple[float, float, float]]:
            ok, start_param, end_param = geom.evaluator.getParameterExtents()
            if not ok:
                raise RuntimeError("Unable to read curve parameter range")
            points: List[Tuple[float, float, float]] = []
            for index in range(count):
                param = start_param + (end_param - start_param) * index / (count - 1)
                ok, point = geom.evaluator.getPointAtParameter(param)
                if not ok:
                    raise RuntimeError("Unable to sample curve point")
                points.append(self._world_point3d(point))
            return points

    def _export_path_curve(
            self,
            curve_entity,
            reverse: bool = False,
            edge_name: Optional[str] = None,
            start_expr: Optional[str] = None,
            end_expr: Optional[str] = None,
        ) -> Tuple[float, float, float]:
            geom = self._curve_world_geometry(curve_entity)
            if geom is None:
                raise RuntimeError("Sweep path curve geometry was unreadable")

            prefix = f"{edge_name} = " if edge_name else ""

            if isinstance(geom, adsk.core.Line3D):
                start = self._world_point3d(geom.startPoint)
                end = self._world_point3d(geom.endPoint)
                if reverse:
                    start, end = end, start
                start_arg = start_expr or Utils._fmt_tuple(start)
                end_arg = end_expr or Utils._fmt_tuple(end)
                self.writer.line(f"{prefix}Line({start_arg}, {end_arg})")
                return end

            if isinstance(geom, adsk.core.Arc3D):
                start_pt, mid_pt, end_pt = Utils.arc3d_to_three_point_arc(geom)
                start = self._world_point3d(start_pt)
                mid = self._world_point3d(mid_pt)
                end = self._world_point3d(end_pt)
                if reverse:
                    start, end = end, start
                start_arg = start_expr or Utils._fmt_tuple(start)
                end_arg = end_expr or Utils._fmt_tuple(end)
                rounded_start = tuple(float(Utils._fmt(v)) for v in start)
                rounded_mid = tuple(float(Utils._fmt(v)) for v in mid)
                rounded_end = tuple(float(Utils._fmt(v)) for v in end)
                if (
                    Utils._is_effectively_collinear(rounded_start[:2], rounded_mid[:2], rounded_end[:2])
                    and abs(rounded_start[2] - rounded_end[2]) < 1e-6
                    and abs(rounded_mid[2] - rounded_end[2]) < 1e-6
                ):
                    self.writer.line(f"{prefix}Line({start_arg}, {end_arg})  # Degenerate Arc")
                else:
                    self.writer.line(f"{prefix}ThreePointArc({start_arg}, {Utils._fmt_tuple(mid)}, {end_arg})")
                return end

            if isinstance(geom, (adsk.core.NurbsCurve3D, adsk.core.EllipticalArc3D)):
                points = self._sample_curve_world(geom)
                if reverse:
                    points.reverse()
                point_args = [Utils._fmt_tuple(p) for p in points]
                if start_expr:
                    point_args[0] = start_expr
                if end_expr:
                    point_args[-1] = end_expr
                self.writer.line(f"{prefix}Spline({', '.join(point_args)})")
                return points[-1]

            raise RuntimeError(f"Unsupported sweep path curve geometry: {type(geom).__name__}")

    def _export_full_circle_path(self, geom, path_name: str):
            # A full circular path has no endpoints to chain from, so it's
            # handled as its own case: split into two exact 180-degree arcs
            # (via evaluator sample points) rather than approximated as a
            # faceted polyline/spline.
            ok, param_start, param_end = geom.evaluator.getParameterExtents()
            if not ok:
                raise RuntimeError("Unable to read circular sweep path parameter range")
            quarter = (param_end - param_start) / 4.0
            sampled = []
            for i in range(4):
                ok, point = geom.evaluator.getPointAtParameter(param_start + quarter * i)
                if not ok:
                    raise RuntimeError("Unable to sample circular sweep path point")
                sampled.append(self._world_point3d(point))
            p0, p90, p180, p270 = sampled

            with self.writer.block(f"with BuildLine() as {path_name}:"):
                self.writer.line(f"{path_name}_edge_1 = ThreePointArc({Utils._fmt_tuple(p0)}, {Utils._fmt_tuple(p90)}, {Utils._fmt_tuple(p180)})")
                self.writer.line(f"ThreePointArc({Utils._fmt_tuple(p180)}, {Utils._fmt_tuple(p270)}, {path_name}_edge_1 @ 0)")

    def _export_sweep_path(self, path_entities, path_name: str):
            curves = Utils._iter_fusion_collection(path_entities)
            if not curves:
                raise RuntimeError("Sweep path has no curves")

            if len(curves) == 1:
                geom = self._curve_world_geometry(curves[0])
                if isinstance(geom, adsk.core.Circle3D):
                    self._export_full_circle_path(geom, path_name)
                    return

            ordered, closed = self._order_path_curves(curves)

            with self.writer.block(f"with BuildLine() as {path_name}:"):
                first_edge_name = None
                previous_edge_name = None
                for index, (curve, reverse) in enumerate(ordered):
                    edge_name = f"{path_name}_edge_{index + 1}"
                    is_first = index == 0
                    is_last = index == len(ordered) - 1
                    start_expr = None if is_first else f"{previous_edge_name} @ 1"
                    end_expr = f"{first_edge_name} @ 0" if is_last and closed and first_edge_name else None
                    self._export_path_curve(
                        curve,
                        reverse=reverse,
                        edge_name=edge_name,
                        start_expr=start_expr,
                        end_expr=end_expr,
                    )
                    if first_edge_name is None:
                        first_edge_name = edge_name
                    previous_edge_name = edge_name

    def _export_sweep(self, sweep: adsk.fusion.SweepFeature):
            timeline = self.design.timeline
            oldPos = timeline.markerPosition

            sweep.timelineObject.rollTo(True)

            try:
                profile = getattr(sweep, "profile", None)
                path = getattr(sweep, "path", None)
                if profile is None or path is None:
                    raise RuntimeError("Sweep profile or path is unavailable")

                # adsk.fusion.Path has no `pathEntities` property -- Path
                # itself is the iterable of PathEntity objects (it exposes
                # `count`/`item`, the same duck-typed shape
                # `Utils._iter_fusion_collection` already knows how to walk).
                if path is None or Utils._safe_getattr(path, "count", 0) == 0:
                    raise RuntimeError("Sweep path curves are unavailable")

                self.sketch_index += 1
                path_name = f"path_{self.sketch_index}"
                self._export_sweep_path(path, path_name)

                self.sketch_index += 1
                sketch_name = f"profile_{self.sketch_index}"
                self._export_profile_sketch(profile, sketch_name)

                mode = self._mode_expr(sweep.operation)

                orientation = Utils._safe_getattr(sweep, "orientation", None)
                if orientation == adsk.fusion.SweepOrientationTypes.ParallelOrientationType:
                    self.writer.line(
                        "# TODO: Fusion sweep used 'parallel' profile orientation (profile keeps a fixed "
                        "orientation along the path); build123d's sweep() always reorients the profile to "
                        "follow the path, matching Fusion's default 'perpendicular' mode, so this may not match exactly."
                    )
                    self.unsupported.append(
                        f"Sweep '{sweep.name}' used parallel profile orientation, which build123d's sweep() cannot represent directly."
                    )

                twist_param = adsk.fusion.ModelParameter.cast(Utils._safe_getattr(sweep, "twistAngle", None))
                twist_value = Utils._param_value_number(twist_param)
                if abs(twist_value) > 1e-9:
                    self.writer.line(
                        f"# TODO: Fusion sweep has a twist angle of {Utils._fmt(math.degrees(twist_value))} deg, "
                        "which build123d's sweep() does not support directly."
                    )
                    self.unsupported.append(f"Sweep '{sweep.name}' has a twist angle that was not translated.")

                taper_param = adsk.fusion.ModelParameter.cast(Utils._safe_getattr(sweep, "taperAngle", None))
                taper_value = Utils._param_value_number(taper_param)
                if abs(taper_value) > 1e-9:
                    self.writer.line(
                        f"# TODO: Fusion sweep has a taper angle of {Utils._fmt(math.degrees(taper_value))} deg, "
                        "which build123d's sweep() does not support directly."
                    )
                    self.unsupported.append(f"Sweep '{sweep.name}' has a taper angle that was not translated.")

                guide_rail = Utils._safe_getattr(sweep, "guideRail", None) or Utils._safe_getattr(sweep, "guideSurface", None)
                if guide_rail:
                    self.writer.line(
                        "# TODO: Fusion sweep uses a guide rail/surface to vary the profile along the path; "
                        "build123d's sweep() has no equivalent, so the emitted call is a plain constant-profile sweep."
                    )
                    self.unsupported.append(f"Sweep '{sweep.name}' uses a guide rail/surface, which was not translated.")

                self.writer.line(f"sweep({sketch_name}.sketch, path={path_name}.line, mode={mode})")
            except Exception as e:
                raise Exception(f"Failed to export sweep: {e}")
            finally:
                timeline.markerPosition = oldPos

    def _loft_section_world_point(self, entity) -> Optional[Tuple[float, float, float]]:
            """Read a loft section's point-type entity (SketchPoint, ConstructionPoint,
            or BRepVertex) as a world-space (x, y, z) tuple in mm, or None if *entity*
            isn't a point-like entity or its geometry can't be read as one.

            Prefers worldGeometry over geometry for the same reason the revolve axis
            and sweep path do (see _export_revolve / _curve_world_geometry): a
            SketchPoint's plain .geometry is expressed in its parent sketch's local
            2D frame, not world space, while ConstructionPoint/BRepVertex only
            expose .geometry, which is already world space.
            """
            try:
                point = Utils._safe_getattr(entity, "worldGeometry", None) or Utils._safe_getattr(entity, "geometry", None)
                if point is None:
                    return None
                return (
                    point.x * Utils.MM_PER_FUSION_UNIT,
                    point.y * Utils.MM_PER_FUSION_UNIT,
                    point.z * Utils.MM_PER_FUSION_UNIT,
                )
            except Exception:
                return None

    def _export_loft(self, loft_feature: adsk.fusion.LoftFeature):
            timeline = self.design.timeline
            oldPos = timeline.markerPosition

            loft_feature.timelineObject.rollTo(True)

            try:
                sections = Utils._iter_fusion_collection(Utils._safe_getattr(loft_feature, "loftSections", None))
                if len(sections) < 2:
                    raise RuntimeError("Loft has fewer than two sections")

                # build123d's loft() has no rail/centerline input -- it only blends
                # directly between the given sections -- so a rail-guided loft is
                # flagged rather than silently emitting a shape that only
                # approximates Fusion's.
                centerline_or_rails = Utils._iter_fusion_collection(Utils._safe_getattr(loft_feature, "centerLineOrRails", None))
                if centerline_or_rails:
                    self.writer.line(
                        "# TODO: Fusion loft uses a centerline/rail to guide the shape between sections; "
                        "build123d's loft() has no equivalent, so the emitted call only lofts through the plain sections."
                    )
                    self.unsupported.append(
                        f"Loft '{loft_feature.name}' uses a centerline/rail, which was not translated."
                    )

                section_exprs: List[str] = []
                skipped_indices: List[int] = []

                for index, section in enumerate(sections):
                    entity = Utils._safe_getattr(section, "entity", None)
                    profiles = Utils.get_profiles_list(entity) if entity is not None else []

                    if profiles:
                        self.sketch_index += 1
                        sketch_name = f"profile_{self.sketch_index}"
                        self._export_profile_sketch(entity, sketch_name)
                        section_exprs.append(f"{sketch_name}.sketch")
                        continue

                    # Fusion allows a loft to start/end on a single point (e.g. a
                    # sharp tip) instead of a profile. build123d's loft() supports
                    # this directly as long as the point is the first and/or last
                    # section, so emit a plain Vertex rather than a BuildSketch.
                    point = self._loft_section_world_point(entity) if entity is not None else None
                    if point is not None:
                        section_exprs.append(f"Vertex{Utils._fmt_tuple(point)}")
                        continue

                    skipped_indices.append(index + 1)

                if skipped_indices:
                    self.writer.line(
                        "# TODO: Fusion loft section(s) {} use an entity type (e.g. an existing face or edge) "
                        "that this exporter could not translate to a sketch profile or point; they were skipped.".format(
                            ", ".join(str(i) for i in skipped_indices)
                        )
                    )
                    self.unsupported.append(
                        "Loft '{}' had unsupported section(s) at position(s) {}.".format(
                            loft_feature.name, ", ".join(str(i) for i in skipped_indices)
                        )
                    )

                if len(section_exprs) < 2:
                    self.writer.line("# TODO: loft has fewer than two translatable sections; skipped.")
                    self.unsupported.append(f"Loft '{loft_feature.name}' had fewer than two translatable sections.")
                    return

                # isClosed (closed loft, blending the last section back into the
                # first) has no equivalent in build123d's loft(); this is a
                # best-effort getattr since LoftFeature may not expose it on every
                # Fusion version, in which case it's silently treated as open.
                if bool(Utils._safe_getattr(loft_feature, "isClosed", False)):
                    self.writer.line(
                        "# TODO: Fusion loft uses the 'Closed Loft' option (blends back into the first section); "
                        "build123d's loft() has no closed option, so the emitted call only lofts through the given sections."
                    )
                    self.unsupported.append(
                        f"Loft '{loft_feature.name}' uses the closed-loft option, which was not translated."
                    )

                mode = self._mode_expr(loft_feature.operation)
                sections_expr = "[" + ", ".join(section_exprs) + "]"
                self.writer.line(f"loft({sections_expr}, mode={mode})")
            except Exception as e:
                raise Exception(f"Failed to export loft: {e}")
            finally:
                timeline.markerPosition = oldPos
