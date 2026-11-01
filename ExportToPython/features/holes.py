"""
    Hole feature translators for Fusion 360 -> Build123D export.

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

class Holes:
    def _hole_depth_expr(self, hole_feature: adsk.fusion.HoleFeature) -> Tuple[bool, Optional[str], str]:
            """Resolve a hole's extentDefinition into a Build123D `depth=`
            value. Returns (resolved, depth_expr, comment):
            - A Distance extent resolves to (True, <expr>, <comment>).
            - A Through-All extent resolves to (True, None, <comment>) --
              Build123D's Hole family already cuts through the entire part
              when depth is omitted, so no explicit argument is needed.
            - Anything else (extentDefinition unavailable, or an extent type
              Fusion's docs don't expect a hole to have) resolves to
              (False, None, "") so the caller can fall back to through-all
              while clearly flagging it as a guess rather than a translation.
            """
            extent = Utils._safe_getattr(hole_feature, "extentDefinition", None)
            if extent is None:
                return False, None, ""

            extent_amount = self._distance_extent_amount(extent)
            if extent_amount:
                _amount, expr, comment, _is_var = extent_amount
                return True, expr, comment

            through_all = Utils._safe_cast(adsk.fusion.ThroughAllExtentDefinition.cast, extent)
            if through_all:
                return True, None, "  # Fusion 'All' extent (hole drilled through all material)"

            return False, None, ""

    def _hole_call_expr(
            self, hole_feature: adsk.fusion.HoleFeature, depth_expr: Optional[str]
        ) -> Tuple[str, List[str]]:
            """Build the Hole / CounterBoreHole / CounterSinkHole call text for
            a HoleFeature, based on its holeType, plus any dimension comments
            (Fusion expressions for non-shared parameters) that should be
            written just above the call.
            """
            lead_comments: List[str] = []
            radius_expr, radius_comment = self._radius_expr(Utils._safe_getattr(hole_feature, "holeDiameter", None))
            if radius_comment:
                lead_comments.append(radius_comment)

            depth_kw = f", depth={depth_expr}" if depth_expr is not None else ""

            hole_type = Utils._safe_getattr(hole_feature, "holeType", None)
            counterbore_type = Utils._safe_getattr(adsk.fusion.HoleTypes, "CounterboreHoleType", None)
            countersink_type = Utils._safe_getattr(adsk.fusion.HoleTypes, "CountersinkHoleType", None)

            if hole_type is not None and counterbore_type is not None and hole_type == counterbore_type:
                cb_radius_expr, cb_radius_comment = self._radius_expr(
                    Utils._safe_getattr(hole_feature, "counterboreDiameter", None)
                )
                cb_depth_param = Utils._safe_cast(
                    adsk.fusion.ModelParameter.cast, Utils._safe_getattr(hole_feature, "counterboreDepth", None)
                )
                cb_depth_expr, cb_depth_comment, _is_var = self._param_expr(cb_depth_param, "length")
                if cb_radius_comment:
                    lead_comments.append(cb_radius_comment)
                if cb_depth_comment:
                    lead_comments.append(cb_depth_comment)
                call = (
                    f"CounterBoreHole(radius={radius_expr}, counter_bore_radius={cb_radius_expr}, "
                    f"counter_bore_depth={cb_depth_expr}{depth_kw})"
                )
            elif hole_type is not None and countersink_type is not None and hole_type == countersink_type:
                cs_radius_expr, cs_radius_comment = self._radius_expr(
                    Utils._safe_getattr(hole_feature, "countersinkDiameter", None)
                )
                cs_angle_param = Utils._safe_cast(
                    adsk.fusion.ModelParameter.cast, Utils._safe_getattr(hole_feature, "countersinkAngle", None)
                )
                cs_angle_expr, cs_angle_comment, _is_var = self._param_expr(cs_angle_param, "angle")
                if cs_radius_comment:
                    lead_comments.append(cs_radius_comment)
                if cs_angle_comment:
                    lead_comments.append(cs_angle_comment)
                call = (
                    f"CounterSinkHole(radius={radius_expr}, counter_sink_radius={cs_radius_expr}, "
                    f"counter_sink_angle={cs_angle_expr}{depth_kw})"
                )
            else:
                call = f"Hole(radius={radius_expr}{depth_kw})"

            return call, lead_comments

    def _note_hole_tap_type(self, hole_feature: adsk.fusion.HoleFeature):
            """Best-effort: flag (but don't attempt to model) thread/tap info
            on the hole, since Build123D's Hole family cuts a plain
            cylindrical hole and has no thread-modeling equivalent.
            """
            try:
                tap_type = Utils._safe_getattr(hole_feature, "holeTapType", None)
                simple_tap_type = Utils._safe_getattr(adsk.fusion.HoleTapTypes, "SimpleHoleTapType", None)
                if tap_type is not None and simple_tap_type is not None and tap_type != simple_tap_type:
                    self.writer.line(
                        "# Fusion hole has thread/tap info that Build123D's Hole primitive does not model."
                    )
                    self.unsupported.append(f"Hole '{hole_feature.name}' thread/tap info was not translated.")
            except Exception:
                pass

    def _hole_world_position_and_axis(
            self, hole_feature: adsk.fusion.HoleFeature
        ) -> Optional[Tuple[adsk.core.Point3D, adsk.core.Vector3D]]:
            """Return (entry_point, axis_direction) for a hole in the design's
            root-component space, read back off the faces the hole actually
            cut.

            HoleFeature.position is *not* a root-component-space point -- like
            SketchEntity.geometry vs. .worldGeometry elsewhere in the Fusion
            API, it's expressed relative to whatever positioned the hole (a
            sketch point, an edge, a face), not the model's global frame.
            """
            side_faces = Utils._safe_getattr(hole_feature, "sideFaces", None)
            if side_faces is None or side_faces.count == 0:
                return None

            side_face = side_faces.item(0)
            cylinder = Utils._safe_cast(adsk.core.Cylinder.cast, Utils._safe_getattr(side_face, "geometry", None))
            if cylinder is None:
                return None

            axis = Utils._safe_getattr(cylinder, "axis", None)
            if axis is None:
                return None

            candidate_faces = Utils._safe_getattr(hole_feature, "faces", None) or side_faces

            circle_centers: List[adsk.core.Point3D] = []
            for i in range(candidate_faces.count):
                edges = Utils._safe_getattr(candidate_faces.item(i), "edges", None)
                if edges is None:
                    continue
                for j in range(edges.count):
                    geom = Utils._safe_cast(adsk.core.Circle3D.cast, Utils._safe_getattr(edges.item(j), "geometry", None))
                    if geom is not None:
                        circle_centers.append(geom.center)

            if not circle_centers:
                # Degenerate (e.g. no clean circular boundary found) -- fall
                # back to the cylinder surface's own reference point.
                return cylinder.origin, axis

            # The entry point is whichever circular edge is furthest against
            # the hole's own drilling direction.
            drill_direction = Utils._safe_getattr(hole_feature, "direction", None)
            if drill_direction is not None:
                entry_point = min(
                    circle_centers,
                    key=lambda p: (
                        p.x * drill_direction.x + p.y * drill_direction.y + p.z * drill_direction.z
                    ),
                )
            else:
                entry_point = circle_centers[0]

            return entry_point, axis

    def _export_hole(self, hole_feature: adsk.fusion.HoleFeature):
            """Export a Fusion HoleFeature as a Build123D Hole / CounterBoreHole
            / CounterSinkHole operation.

            Unlike extrude, a hole isn't built from a profile sketch -- its
            position and orientation are read back off the cylindrical face it
            cut (see _hole_world_position_and_axis) rather than from
            HoleFeature.position, which is not expressed in the design's
            root-component space. Build123D's Hole family cuts along the
            *local -Z* of the current workplane, so the workplane built here
            uses z_dir = -axis, i.e. the plane's +Z points out of the material
            -- the same outward-facing convention every sketch plane in this
            script already follows.
            """
            timeline = self.design.timeline
            oldPos = timeline.markerPosition
            hole_feature.timelineObject.rollTo(True)

            try:
                # The hole's cut geometry only exists once the timeline has
                # advanced past it, so step forward just long enough to read
                # the resulting cylindrical face back, then return to the
                # "before" position the parametric reads below expect (same
                # convention every other feature export in this file uses).
                hole_feature.timelineObject.rollTo(False)
                frame = self._hole_world_position_and_axis(hole_feature)
                hole_feature.timelineObject.rollTo(True)

                if frame is None:
                    self.writer.line("# TODO: hole position/direction unavailable through this Fusion API object.")
                    self.unsupported.append(f"Hole '{hole_feature.name}' has unavailable position/direction.")
                    return
                position, axis = frame

                normal = Utils._unit_vector_from_tuple((-axis.x, -axis.y, -axis.z))
                if normal is None:
                    self.writer.line("# TODO: hole direction vector could not be normalized.")
                    self.unsupported.append(f"Hole '{hole_feature.name}' has a degenerate direction vector.")
                    return

                x_dir = Utils._fallback_plane_x_dir(normal)
                if x_dir is None:
                    self.writer.line("# TODO: could not derive a workplane orientation for this hole.")
                    self.unsupported.append(
                        f"Hole '{hole_feature.name}' direction is parallel to the fallback reference axis."
                    )
                    return

                origin_mm = (
                    position.x * Utils.MM_PER_FUSION_UNIT,
                    position.y * Utils.MM_PER_FUSION_UNIT,
                    position.z * Utils.MM_PER_FUSION_UNIT,
                )
                plane_expr, plane_comment = self._frame_to_plane_expr(origin_mm, x_dir, normal)

                depth_ok, depth_expr, depth_comment = self._hole_depth_expr(hole_feature)
                if not depth_ok:
                    self.unsupported.append(
                        f"Hole '{hole_feature.name}' has an unsupported extent definition; depth defaulted to through-all."
                    )
                    depth_comment = "  # TODO: unsupported extent definition; depth defaulted to through-all (verify manually)."

                call_expr, lead_comments = self._hole_call_expr(hole_feature, depth_expr)
                if depth_comment:
                    lead_comments.append(depth_comment)

                self._note_hole_tap_type(hole_feature)

                self.writer.line(f"with Locations({plane_expr}):{plane_comment}")
                self.writer.level += 1
                for comment in lead_comments:
                    self.writer.line(comment)
                self.writer.line(call_expr)
                self.writer.level -= 1

                # Record enough to replay this exact hole (its placement plane
                # plus the Hole/CounterBoreHole/CounterSinkHole call) at a
                # transformed location -- see _replay_last_feature_translated /
                # _replay_last_feature_rotated. A HoleFeature has no profile
                # sketch to move the way an extrude does, so it needs this
                # separate replay path rather than reusing last_extrude_replay.
                self.last_feature_kind = "hole"
                self.last_hole_plane_expr = plane_expr
                self.last_hole_call_lines = list(lead_comments) + [call_expr]
            except Exception as e:
                raise Exception(f"Failed to export hole: {e}")
            finally:
                timeline.markerPosition = oldPos
