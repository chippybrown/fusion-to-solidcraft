"""
    Objects transformations translators for Fusion 360 -> Build123D export.

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

class Transforms:
    def _export_mirror(self, mirror_feature: adsk.fusion.MirrorFeature):
            timeline = self.design.timeline
            oldPos = timeline.markerPosition

            mirror_feature.timelineObject.rollTo(True)

            try:
                mirror_plane = Utils._safe_getattr(mirror_feature, "mirrorPlane", None)
                plane_expr, plane_comment = self._plane_entity_expr(mirror_plane)
                if plane_expr is None:
                    self.writer.line("# TODO: mirror plane could not be translated to a Build123D Plane.")
                    self.unsupported.append(f"Mirror '{mirror_feature.name}' has an unreadable mirror plane.")
                    return

                input_entities = Utils._iter_fusion_collection(Utils._safe_getattr(mirror_feature, "inputEntities", None))
                if input_entities:
                    descriptions = []
                    for entity in input_entities:
                        entity_name = Utils._safe_getattr(entity, "name", None)
                        entity_type = Utils._safe_getattr(entity, "objectType", None) or type(entity).__name__
                        descriptions.append(f"{entity_name} ({entity_type})" if entity_name else entity_type)
                    self.writer.line("# Fusion mirror input entities: " + ", ".join(descriptions[:4]))
                    if len(descriptions) > 4:
                        remaining = len(descriptions) - 4
                        self.writer.line(f"# ... plus {remaining} more mirrored input entit{'y' if remaining == 1 else 'ies'}.")
                else:
                    self.writer.line("# Fusion mirror input entities were unavailable; mirroring current BuildPart state.")

                self.writer.line(f"mirror(about={plane_expr}, mode=Mode.ADD){plane_comment}")
            except Exception as e:
                raise Exception(f"Failed to export mirror: {e}")
            finally:
                timeline.markerPosition = oldPos

    def _export_move(self, move_feature: adsk.fusion.MoveFeature):
            """Export a Fusion Move/Copy feature.

            Build123D's BuildPart has no dedicated "move the current part"
            operation the way it has mirror()/fillet()/etc., so this is
            approximated the same way patterns approximate their source (see
            _write_pattern_input_summary): the feature's net transform --
            read from MoveFeature.transform rather than decoded from its
            (several, mutually exclusive) TranslateXYZ/Rotate/PointToPoint/
            FreeForm definition types -- is applied to the whole current
            BuildPart state via add(..., mode=Mode.REPLACE), which re-adds
            the moved solid in place of the original.
            """
            timeline = self.design.timeline
            oldPos = timeline.markerPosition

            move_feature.timelineObject.rollTo(True)

            try:
                transform = Utils._safe_getattr(move_feature, "transform", None)
                if transform is None:
                    self.writer.line("# TODO: move transform was unavailable.")
                    self.unsupported.append(f"Move '{move_feature.name}' has no readable transform.")
                    return
                coordinate_system = transform.getAsCoordinateSystem()
                if not coordinate_system:
                    self.writer.line("# TODO: move transform could not be decomposed into a coordinate system.")
                    self.unsupported.append(f"Move '{move_feature.name}' has an unreadable transform.")
                    return
                origin, x_axis, y_axis, z_axis = coordinate_system

                origin_mm = (
                    origin.x * Utils.MM_PER_FUSION_UNIT,
                    origin.y * Utils.MM_PER_FUSION_UNIT,
                    origin.z * Utils.MM_PER_FUSION_UNIT,
                )
                plane_expr = "Plane(origin={}, x_dir={}, z_dir={})".format(
                    Utils._fmt_tuple(origin_mm),
                    Utils._fmt_tuple((x_axis.x, x_axis.y, x_axis.z)),
                    Utils._fmt_tuple((z_axis.x, z_axis.y, z_axis.z)),
                )

                input_entities = Utils._iter_fusion_collection(Utils._safe_getattr(move_feature, "inputEntities", None))
                if input_entities:
                    descriptions = []
                    for entity in input_entities:
                        entity_name = Utils._safe_getattr(entity, "name", None)
                        entity_type = Utils._safe_getattr(entity, "objectType", None) or type(entity).__name__
                        descriptions.append(f"{entity_name} ({entity_type})" if entity_name else entity_type)
                    self.writer.line("# Fusion move input entities: " + ", ".join(descriptions[:4]))
                    if len(descriptions) > 4:
                        remaining = len(descriptions) - 4
                        self.writer.line(f"# ... plus {remaining} more moved input entit{'y' if remaining == 1 else 'ies'}.")
                    self.writer.line(
                        "# Move approximated as transforming the whole current BuildPart state; "
                        "if the input entities above are only some of the bodies built so far, "
                        "this will over-move the ones not listed."
                    )
                else:
                    self.writer.line("# Fusion move input entities were unavailable; moving current BuildPart state.")

                self.writer.line(f"add({self.current_body_var}.part.moved(Location({plane_expr})), mode=Mode.REPLACE)")
            except Exception as e:
                raise Exception(f"Failed to export move: {e}")
            finally:
                timeline.markerPosition = oldPos

    def _export_copy_paste_body(self, copy_paste_feature):
            """Export a Fusion Copy/Paste Body feature.

            Fusion exposes body copy/paste as its own timeline feature
            (CopyPasteBody). The pasted body normally has no new sketch or
            primitive definition to replay, so the best Build123D equivalent is
            to add the previously exported source body's Part into this body's
            BuildPart block.
            """
            timeline = self.design.timeline
            oldPos = timeline.markerPosition

            copy_paste_feature.timelineObject.rollTo(True)

            try:
                source_bodies = Utils._iter_fusion_collection(Utils._safe_getattr(copy_paste_feature, "sourceBody", None))
                if not source_bodies:
                    self.writer.line("# TODO: copy/paste source body was unavailable.")
                    self.unsupported.append(f"Copy/paste body '{copy_paste_feature.name}' has no readable source body.")
                    return

                descriptions = []
                source_vars: List[str] = []
                for body in source_bodies:
                    body_name = Utils._safe_getattr(body, "name", None)
                    token = Utils._safe_getattr(body, "entityToken", None)
                    source_var = self._body_var_by_token.get(token) if token else None
                    if source_var is None and token:
                        resolved_body = Utils._safe_getattr(self.design, "findEntityByToken", lambda _token: None)(token)
                        resolved_token = Utils._safe_getattr(resolved_body, "entityToken", None)
                        source_var = self._body_var_by_token.get(resolved_token) if resolved_token else None
                    if source_var and source_var not in source_vars:
                        source_vars.append(source_var)
                    descriptions.append(body_name or "unnamed body")

                self.writer.line("# Fusion copy/paste source bodies: " + ", ".join(descriptions[:4]))
                if len(descriptions) > 4:
                    remaining = len(descriptions) - 4
                    self.writer.line(f"# ... plus {remaining} more copied source bod{'y' if remaining == 1 else 'ies'}.")

                if not source_vars:
                    self.writer.line("# TODO: copied source body could not be matched to an exported BuildPart.")
                    self.unsupported.append(
                        f"Copy/paste body '{copy_paste_feature.name}' source could not be matched to a generated body variable."
                    )
                    return

                for source_var in source_vars:
                    self.writer.line(f"add({source_var}.part, mode=Mode.ADD)")
            except Exception as e:
                raise Exception(f"Failed to export copy/paste body: {e}")
            finally:
                timeline.markerPosition = oldPos

    def _export_scale(self, scale_feature: adsk.fusion.ScaleFeature):
            """Export a Fusion Scale feature using build123d's own scale()
            operation, which -- like mirror() -- operates on the current
            BuildPart state implicitly when no explicit objects are passed.
            """
            timeline = self.design.timeline
            oldPos = timeline.markerPosition

            scale_feature.timelineObject.rollTo(True)

            try:
                is_uniform = bool(Utils._safe_getattr(scale_feature, "isUniform", True))
                comment = ""

                if is_uniform:
                    factor_param = Utils._safe_getattr(scale_feature, "scaleFactor", None)
                    if factor_param is not None:
                        by_expr, comment, _is_var = self._param_expr(factor_param, "number")
                    else:
                        by_expr = Utils._fmt(1.0)
                else:
                    axis_exprs = []
                    for prop_name in ("xScale", "yScale", "zScale"):
                        axis_param = Utils._safe_getattr(scale_feature, prop_name, None)
                        if axis_param is None:
                            axis_exprs.append(Utils._fmt(1.0))
                            continue
                        axis_expr, axis_comment, _is_var = self._param_expr(axis_param, "number")
                        axis_exprs.append(axis_expr)
                        comment = comment or axis_comment
                    by_expr = f"({axis_exprs[0]}, {axis_exprs[1]}, {axis_exprs[2]})"

                point_entity = Utils._safe_getattr(scale_feature, "point", None)
                about_point = self._loft_section_world_point(point_entity) if point_entity is not None else None
                about_arg = f", about={Utils._fmt_tuple(about_point)}" if about_point is not None else ""
                if about_point is None:
                    self.writer.line(
                        "# Fusion scale base point was unavailable; scaling about the current part's own position."
                    )

                input_entities = Utils._iter_fusion_collection(Utils._safe_getattr(scale_feature, "inputEntities", None))
                if input_entities:
                    descriptions = []
                    for entity in input_entities:
                        entity_name = Utils._safe_getattr(entity, "name", None)
                        entity_type = Utils._safe_getattr(entity, "objectType", None) or type(entity).__name__
                        descriptions.append(f"{entity_name} ({entity_type})" if entity_name else entity_type)
                    self.writer.line("# Fusion scale input entities: " + ", ".join(descriptions[:4]))
                    if len(descriptions) > 4:
                        remaining = len(descriptions) - 4
                        self.writer.line(f"# ... plus {remaining} more scaled input entit{'y' if remaining == 1 else 'ies'}.")
                    self.writer.line(
                        "# Scale approximated as scaling the whole current BuildPart state; "
                        "if the input entities above are only some of the bodies built so far, "
                        "this will over-scale the ones not listed."
                    )
                else:
                    self.writer.line("# Fusion scale input entities were unavailable; scaling current BuildPart state.")

                self.writer.line(f"scale(by={by_expr}{about_arg}, mode=Mode.REPLACE){comment}")
            except Exception as e:
                raise Exception(f"Failed to export scale: {e}")
            finally:
                timeline.markerPosition = oldPos

    def _pattern_source_name(self) -> str:
            self.pattern_index += 1
            source_name = f"pattern_source_{self.pattern_index}"
            self.writer.line(f"{source_name} = {self.current_body_var}.part")
            return source_name

    def _write_pattern_input_summary(self, pattern_feature) -> bool:
            input_entities = Utils._iter_fusion_collection(Utils._safe_getattr(pattern_feature, "inputEntities", None))
            if not input_entities:
                if self.last_feature_kind is not None:
                    self.writer.line(
                        f"# Fusion pattern input entities were unavailable; replaying previous {self.last_feature_kind} operation."
                    )
                    return False
                self.writer.line("# Fusion pattern input entities were unavailable; patterning current BuildPart state.")
                return True

            descriptions = []
            for entity in input_entities:
                entity_name = Utils._safe_getattr(entity, "name", None)
                entity_type = Utils._safe_getattr(entity, "objectType", None) or type(entity).__name__
                descriptions.append(f"{entity_name} ({entity_type})" if entity_name else entity_type)
            self.writer.line("# Fusion pattern input entities: " + ", ".join(descriptions[:4]))
            if len(descriptions) > 4:
                remaining = len(descriptions) - 4
                self.writer.line(f"# ... plus {remaining} more patterned input entit{'y' if remaining == 1 else 'ies'}.")
            self.writer.line("# Pattern source approximated as the current BuildPart state at this timeline step.")
            return True

    def _replay_last_feature_translated(self, delta_expr: str):
            if self.last_feature_kind == "hole":
                self.writer.line(f"with Locations(Location({delta_expr}) * Location({self.last_hole_plane_expr})):")
                self.writer.level += 1
                for line in self.last_hole_call_lines:
                    self.writer.line(line)
                self.writer.level -= 1
                return

            replay_call = self.last_extrude_replay
            if self.last_extrude_sketch_name:
                replay_call = replay_call.replace(
                    f"{self.last_extrude_sketch_name}.sketch",
                    f"{self.last_extrude_sketch_name}.sketch.moved(Location({delta_expr}))",
                    1,
                )
            self.writer.line(replay_call)

    def _replay_last_feature_rotated(self, axis_expr: str, angle_expr: str):
            if self.last_feature_kind == "hole":
                self.writer.line(f"_pattern_axis_loc = ({axis_expr}).location")
                self.writer.line(
                    "_pattern_rot_loc = _pattern_axis_loc * "
                    f"Location((0, 0, 0), (0, 0, {angle_expr})) * _pattern_axis_loc.inverse()"
                )
                self.writer.line(f"with Locations(_pattern_rot_loc * Location({self.last_hole_plane_expr})):")
                self.writer.level += 1
                for line in self.last_hole_call_lines:
                    self.writer.line(line)
                self.writer.level -= 1
                return

            replay_call = self.last_extrude_replay
            if self.last_extrude_sketch_name:
                replay_call = replay_call.replace(
                    f"{self.last_extrude_sketch_name}.sketch",
                    f"{self.last_extrude_sketch_name}.sketch.rotate({axis_expr}, {angle_expr})",
                    1,
                )
            self.writer.line(replay_call)

    def _quantity_from_parameter(self, parameter, default: int = 1) -> int:
            try:
                return max(1, int(round(Utils._param_value_number(adsk.fusion.ModelParameter.cast(parameter), default))))
            except Exception:
                return default

    def _distance_from_parameter(self, parameter) -> float:
            model_parameter = adsk.fusion.ModelParameter.cast(parameter)
            return Utils._param_value_mm(model_parameter) if model_parameter else 0.0

    def _axis_frame_from_line_geometry(
            self, geometry
        ) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
            start = Utils._safe_getattr(geometry, "startPoint", None)
            end = Utils._safe_getattr(geometry, "endPoint", None)
            if start is not None and end is not None:
                dx = end.x - start.x
                dy = end.y - start.y
                dz = end.z - start.z
                length = math.sqrt(dx * dx + dy * dy + dz * dz)
                if length <= 1e-9:
                    return None
                return (start.x, start.y, start.z), (dx / length, dy / length, dz / length)

            origin = Utils._safe_getattr(geometry, "origin", None) or Utils._safe_getattr(geometry, "rootPoint", None)
            direction = Utils._safe_getattr(geometry, "direction", None)
            if origin is not None and direction is not None:
                unit = Utils._unit_vector_from_tuple(Utils._vector_tuple(direction))
                if unit is None:
                    return None
                return (origin.x, origin.y, origin.z), (unit.x, unit.y, unit.z)

            return None

    def _register_revolve_selector_reflection(
            self,
            profile,
            axis_frame: Tuple[Tuple[float, float, float], Tuple[float, float, float]],
        ):
            sketch = self._profile_sketch(profile)
            if sketch is None:
                return

            plane_origin, _x_dir, _y_dir, normal = Utils._sketch_frame(sketch)
            axis_origin, axis_dir = axis_frame
            if abs(axis_dir[0] * normal.x + axis_dir[1] * normal.y + axis_dir[2] * normal.z) > 1e-6:
                return

            self._revolve_selector_reflections.append(
                {
                    "axis_origin": axis_origin,
                    "axis_dir": axis_dir,
                    "plane_origin": (plane_origin.x, plane_origin.y, plane_origin.z),
                    "plane_normal": (normal.x, normal.y, normal.z),
                }
            )

    def _axis_expr_from_line_geometry(self, geometry) -> Optional[str]:
            """Build an ``Axis(...)`` expression from a Fusion line-like geometry
            object. Handles both shapes Fusion hands back for an axis input:
            a bounded ``Line3D``/``Line3D``-alike (has startPoint/endPoint,
            e.g. a sketch line) and an unbounded ``InfiniteLine3D`` (has
            origin/direction instead, e.g. a ConstructionAxis or one of the
            model's built-in X/Y/Z axes). Returns None if *geometry* matches
            neither shape.
            """
            start = Utils._safe_getattr(geometry, "startPoint", None)
            end = Utils._safe_getattr(geometry, "endPoint", None)
            if start is not None and end is not None:
                return Utils._axis_from_points(start, end)

            origin = Utils._safe_getattr(geometry, "origin", None) or Utils._safe_getattr(geometry, "rootPoint", None)
            direction = Utils._safe_getattr(geometry, "direction", None)
            if origin is not None and direction is not None:
                direction = Utils._unit_vector_from_tuple(Utils._vector_tuple(direction))
                if direction is None:
                    return None
                return "Axis(origin={}, direction={})".format(
                    Utils._fmt_tuple(
                        (
                            origin.x * Utils.MM_PER_FUSION_UNIT,
                            origin.y * Utils.MM_PER_FUSION_UNIT,
                            origin.z * Utils.MM_PER_FUSION_UNIT,
                        )
                    ),
                    Utils._fmt_tuple((direction.x, direction.y, direction.z)),
                )

            return None

    def _axis_expr_from_origin_direction(self, origin, direction) -> Optional[str]:
            if origin is None or direction is None:
                return None
            direction = Utils._unit_vector_from_tuple(Utils._vector_tuple(direction))
            if direction is None:
                return None
            return "Axis(origin={}, direction={})".format(
                Utils._fmt_tuple(
                    (
                        origin.x * Utils.MM_PER_FUSION_UNIT,
                        origin.y * Utils.MM_PER_FUSION_UNIT,
                        origin.z * Utils.MM_PER_FUSION_UNIT,
                    )
                ),
                Utils._fmt_tuple((direction.x, direction.y, direction.z)),
            )

    def _axis_expr_from_geometry(self, geometry) -> Optional[str]:
            line_axis = self._axis_expr_from_line_geometry(geometry)
            if line_axis is not None:
                return line_axis

            cylinder = Utils._safe_cast(adsk.core.Cylinder.cast, geometry)
            if cylinder is not None:
                return self._axis_expr_from_origin_direction(cylinder.origin, cylinder.axis)

            cone = Utils._safe_cast(adsk.core.Cone.cast, geometry)
            if cone is not None:
                origin = Utils._safe_getattr(cone, "origin", None) or Utils._safe_getattr(cone, "apex", None)
                return self._axis_expr_from_origin_direction(origin, Utils._safe_getattr(cone, "axis", None))

            torus = Utils._safe_cast(adsk.core.Torus.cast, geometry)
            if torus is not None:
                origin = Utils._safe_getattr(torus, "origin", None) or Utils._safe_getattr(torus, "center", None)
                axis = Utils._safe_getattr(torus, "axis", None) or Utils._safe_getattr(torus, "normal", None)
                return self._axis_expr_from_origin_direction(origin, axis)

            circle = Utils._safe_cast(adsk.core.Circle3D.cast, geometry)
            if circle is not None:
                return self._axis_expr_from_origin_direction(circle.center, circle.normal)

            arc = Utils._safe_cast(adsk.core.Arc3D.cast, geometry)
            if arc is not None:
                return self._axis_expr_from_origin_direction(arc.center, arc.normal)

            plane = Utils._safe_cast(adsk.core.Plane.cast, geometry)
            if plane is not None:
                return self._axis_expr_from_origin_direction(plane.origin, plane.normal)

            return None

    def _pattern_axis_expr(self, axis_entity) -> Optional[str]:
            # Prefer worldGeometry for the same reason the revolve axis does
            # (see _export_revolve): a sketch line used as a pattern axis is
            # local to its own sketch frame under plain .geometry, while
            # worldGeometry (when the entity type has it) is already in world
            # space. ConstructionAxis and the built-in X/Y/Z axes only ever
            # expose .geometry, which is already world space.
            candidates = [axis_entity]
            geometry = Utils._safe_getattr(axis_entity, "worldGeometry", None) or Utils._safe_getattr(axis_entity, "geometry", None)
            if geometry is not None:
                candidates.insert(0, geometry)

            for candidate in candidates:
                axis_expr = self._axis_expr_from_geometry(candidate)
                if axis_expr is not None:
                    return axis_expr

                # BRep faces/edges often expose their analytic geometry through
                # .geometry, but some wrapper objects only yield it after direct
                # access above has failed.
                nested_geometry = Utils._safe_getattr(candidate, "geometry", None)
                if nested_geometry is not None and nested_geometry is not candidate:
                    axis_expr = self._axis_expr_from_geometry(nested_geometry)
                    if axis_expr is not None:
                        return axis_expr

            return None

    def _rectangular_pattern_offsets(self, count: int, distance: float, is_symmetric: bool, distance_type) -> List[float]:
            if count <= 1:
                return [0.0]

            extent_type = getattr(adsk.fusion.PatternDistanceType, "ExtentPatternDistanceType", None)
            spacing = distance / (count - 1) if distance_type == extent_type and count > 1 else distance
            if is_symmetric:
                center = (count - 1) / 2.0
                return [(index - center) * spacing for index in range(count)]
            return [index * spacing for index in range(count)]

    def _export_rectangular_pattern(self, pattern_feature: adsk.fusion.RectangularPatternFeature):
            use_part_snapshot = self._write_pattern_input_summary(pattern_feature)

            direction_one = Utils._safe_getattr(pattern_feature, "directionOne", None)
            if direction_one is None:
                self.writer.line("# TODO: rectangular pattern direction one was unavailable.")
                self.unsupported.append(f"Rectangular pattern '{pattern_feature.name}' has no readable first direction.")
                return
            direction_one = Utils._unit_vector_from_tuple(Utils._vector_tuple(direction_one))
            if direction_one is None:
                self.writer.line("# TODO: rectangular pattern direction one was invalid.")
                self.unsupported.append(f"Rectangular pattern '{pattern_feature.name}' has an invalid first direction.")
                return

            direction_two = Utils._safe_getattr(pattern_feature, "directionTwo", None)
            if direction_two is not None:
                direction_two = Utils._unit_vector_from_tuple(Utils._vector_tuple(direction_two))

            count_one = self._quantity_from_parameter(Utils._safe_getattr(pattern_feature, "quantityOne", None))
            count_two = self._quantity_from_parameter(Utils._safe_getattr(pattern_feature, "quantityTwo", None))
            distance_one = self._distance_from_parameter(Utils._safe_getattr(pattern_feature, "distanceOne", None))
            distance_two = self._distance_from_parameter(Utils._safe_getattr(pattern_feature, "distanceTwo", None))
            distance_type = Utils._safe_getattr(pattern_feature, "patternDistanceType", None)

            offsets_one = self._rectangular_pattern_offsets(
                count_one,
                distance_one,
                bool(Utils._safe_getattr(pattern_feature, "isSymmetricInDirectionOne", False)),
                distance_type,
            )
            offsets_two = self._rectangular_pattern_offsets(
                count_two,
                distance_two,
                bool(Utils._safe_getattr(pattern_feature, "isSymmetricInDirectionTwo", False)),
                distance_type,
            )

            # Prefer replaying the actual source feature (extrude or hole) over
            # duplicating a snapshot of the whole accumulated part -- same
            # preference _export_circular_pattern applies below, and for the
            # same reason: rotating/translating a whole-part snapshot duplicates
            # every prior feature, not just the one being patterned.
            if use_part_snapshot and not self.last_feature_kind:
                self.writer.line(
                    "# Rectangular pattern source operation replay is unavailable; patterning current BuildPart state instead."
                )
                self.unsupported.append(
                    f"Rectangular pattern '{pattern_feature.name}' fell back to translating the current whole-part snapshot "
                    "because its source operation could not be replayed; this duplicates the entire part at each pattern "
                    "position rather than just the intended feature."
                )
            else:
                use_part_snapshot = False

            source_name = self._pattern_source_name() if use_part_snapshot else None
            self.writer.line(
                f"for _pattern_offset_1 in {[float(Utils._fmt(offset)) for offset in offsets_one]!r}:"
            )
            self.writer.level += 1
            self.writer.line(
                f"for _pattern_offset_2 in {[float(Utils._fmt(offset)) for offset in offsets_two]!r}:"
            )
            self.writer.level += 1
            self.writer.line("if abs(_pattern_offset_1) < 1e-9 and abs(_pattern_offset_2) < 1e-9:")
            self.writer.level += 1
            self.writer.line("continue")
            self.writer.level -= 1

            dir_one_tuple = (direction_one.x, direction_one.y, direction_one.z)
            if direction_two is None:
                dir_two_tuple = (0.0, 0.0, 0.0)
                self.unsupported.append(
                    f"Rectangular pattern '{pattern_feature.name}' had no second direction; exported as one-direction pattern."
                )
            else:
                dir_two_tuple = (direction_two.x, direction_two.y, direction_two.z)

            self.writer.line(
                "_pattern_delta = ("
                f"_pattern_offset_1 * {Utils._fmt_tuple(dir_one_tuple)}[0] + _pattern_offset_2 * {Utils._fmt_tuple(dir_two_tuple)}[0], "
                f"_pattern_offset_1 * {Utils._fmt_tuple(dir_one_tuple)}[1] + _pattern_offset_2 * {Utils._fmt_tuple(dir_two_tuple)}[1], "
                f"_pattern_offset_1 * {Utils._fmt_tuple(dir_one_tuple)}[2] + _pattern_offset_2 * {Utils._fmt_tuple(dir_two_tuple)}[2]"
                ")"
            )
            if source_name:
                self.writer.line(f"add({source_name}.moved(Location(_pattern_delta)), mode=Mode.ADD)")
            else:
                self._replay_last_feature_translated("_pattern_delta")
            self.writer.level -= 2

            suppressed = Utils._safe_getattr(pattern_feature, "suppressedElementsIds", None)
            if suppressed:
                self.writer.line("# TODO: Fusion suppressed rectangular pattern elements were not translated.")
                self.unsupported.append(f"Rectangular pattern '{pattern_feature.name}' has suppressed elements.")

    def _circular_pattern_angles(self, count: int, total_angle: float, is_symmetric: bool) -> List[float]:
            if count <= 1:
                return [0.0]

            full_circle = abs(abs(total_angle) - 360.0) < 1e-6
            step = total_angle / count if full_circle else total_angle / (count - 1)
            if is_symmetric:
                center = (count - 1) / 2.0
                return [(index - center) * step for index in range(count)]
            return [index * step for index in range(count)]

    def _export_circular_pattern(self, pattern_feature: adsk.fusion.CircularPatternFeature):
            use_part_snapshot = self._write_pattern_input_summary(pattern_feature)

            axis_expr = self._pattern_axis_expr(Utils._safe_getattr(pattern_feature, "axis", None) or Utils._safe_getattr(pattern_feature, "axisEntity", None))
            if axis_expr is None:
                self.writer.line("# TODO: circular pattern axis could not be translated to a Build123D Axis.")
                self.unsupported.append(f"Circular pattern '{pattern_feature.name}' has an unreadable axis.")
                return

            quantity = self._quantity_from_parameter(Utils._safe_getattr(pattern_feature, "quantity", None))
            total_angle = Utils._param_value_degrees(
                adsk.fusion.ModelParameter.cast(Utils._safe_getattr(pattern_feature, "totalAngle", None)),
                360.0,
            )
            angles = self._circular_pattern_angles(quantity, total_angle, bool(Utils._safe_getattr(pattern_feature, "isSymmetric", False)))

            # Prefer replaying the source feature (extrude or hole, whichever was
            # exported most recently -- see last_feature_kind) rotated about the
            # pattern axis. Rotating a snapshot of the whole accumulated part (the
            # fallback below) duplicates every prior feature, not just the one
            # being patterned -- that's what previously made the entire part
            # appear to rotate/duplicate instead of just the patterned feature.
            if use_part_snapshot and not self.last_feature_kind:
                self.writer.line("# Circular pattern source operation replay is unavailable; patterning current BuildPart state instead.")
                self.unsupported.append(
                    f"Circular pattern '{pattern_feature.name}' fell back to rotating the current whole-part snapshot because "
                    "its source operation could not be replayed; this duplicates the entire part at each pattern angle rather "
                    "than just the intended feature."
                )
            else:
                use_part_snapshot = False

            source_name = self._pattern_source_name() if use_part_snapshot else None
            self.writer.line(f"for _pattern_angle in {[float(Utils._fmt(angle)) for angle in angles]!r}:")
            self.writer.level += 1
            self.writer.line("if abs(_pattern_angle) < 1e-9:")
            self.writer.level += 1
            self.writer.line("continue")
            self.writer.level -= 1
            if source_name:
                self.writer.line(f"add({source_name}.rotate({axis_expr}, _pattern_angle), mode=Mode.ADD)")
            else:
                self._replay_last_feature_rotated(axis_expr, "_pattern_angle")
            self.writer.level -= 1

            suppressed = Utils._safe_getattr(pattern_feature, "suppressedElementsIds", None)
            if suppressed:
                self.writer.line("# TODO: Fusion suppressed circular pattern elements were not translated.")
                self.unsupported.append(f"Circular pattern '{pattern_feature.name}' has suppressed elements.")
