"""
    Edge selection utilities for Build123D Python script generation.

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

class Selectors:
    def _edge_anchor_point(self, edge):
            """A point that's genuinely ON *edge*, at (approximately) its
            parametric midpoint, in world space -- used as the "find this edge
            again" anchor for the edges().sort_by_distance(...) selectors
            emitted for fillets/chamfers (see _edge_midpoint_exprs).

            Deliberately doesn't rely on Utils.edge_mid_point for this: for a
            *closed* edge (a full-circle rim -- the edge around a cylindrical
            boss or a drilled hole, both extremely common fillet/chamfer
            targets), a naive midpoint computation can come back as the curve's
            center rather than a point on its circumference. A full circle's
            parameter range is periodic (0 to 2*pi, where both ends are the same
            point), so evaluating at the parametric midpoint lands diametrically
            opposite the start point -- genuinely on the circle -- which is
            exactly what evaluator.getPointAtParameter((start+end)/2) below
            gives for any curve type, closed or not. A center-point anchor is
            uniformly equidistant from the whole rim, so the emitted selector
            ends up picking whatever *other* edge in the model happens to be
            closer than that radius -- essentially arbitrary with respect to
            the actual target edge.
            """
            try:
                geom = Utils._safe_getattr(edge, "geometry", None)
                evaluator = Utils._safe_getattr(geom, "evaluator", None)
                if evaluator is not None:
                    ok, start_param, end_param = evaluator.getParameterExtents()
                    if ok:
                        ok_point, point = evaluator.getPointAtParameter((start_param + end_param) / 2.0)
                        if ok_point:
                            return point
            except Exception:
                pass

            # Fall back to a Fusion-guaranteed point on the edge (may land near
            # an endpoint rather than the middle, but is still always genuinely
            # on the curve) if the evaluator path above didn't work.
            point_on_edge = Utils._safe_getattr(edge, "pointOnEdge", None)
            if point_on_edge is not None:
                return point_on_edge

            return Utils.edge_mid_point(edge)

    def _edge_midpoint_exprs(self, edges) -> List[str]:
            midpoints = []
            for edge in Utils._iter_fusion_collection(edges):
                p = self._edge_anchor_point(edge)
                if p:
                    midpoints.append(
                        Utils._fmt_tuple(
                            (
                                p.x * Utils.MM_PER_FUSION_UNIT,
                                p.y * Utils.MM_PER_FUSION_UNIT,
                                p.z * Utils.MM_PER_FUSION_UNIT,
                            )
                        )
                    )
            return midpoints

    def _edge_geom_filter_expr(self, edge) -> str:
            """Return a Build123D edge selector narrowed by known geometry type."""

            geom = Utils._safe_getattr(edge, "geometry", None)
            curve_type = Utils._safe_getattr(geom, "curveType", None)
            if curve_type in (
                getattr(adsk.core.Curve3DTypes, "Circle3DCurveType", None),
                getattr(adsk.core.Curve3DTypes, "Arc3DCurveType", None),
            ):
                return "edges().filter_by(GeomType.CIRCLE)"
            return "edges()"

    def _edge_selector_terms(self, edges) -> List[str]:
            selectors = []
            for edge in Utils._iter_fusion_collection(edges):
                p = self._edge_anchor_point(edge)
                if p:
                    selector_point = self._selector_anchor_for_edge(edge, p)
                    midpoint = Utils._fmt_tuple(
                        (
                            selector_point[0] * Utils.MM_PER_FUSION_UNIT,
                            selector_point[1] * Utils.MM_PER_FUSION_UNIT,
                            selector_point[2] * Utils.MM_PER_FUSION_UNIT,
                        )
                    )
                    selectors.append(f"{self._edge_geom_filter_expr(edge)}.sort_by_distance({midpoint})[0]")
            return selectors

    def _selector_anchor_for_edge(self, edge, point) -> Tuple[float, float, float]:
            """Map Fusion edge anchor points into generated Build123D space."""

            anchor = (point.x, point.y, point.z)
            geom = Utils._safe_getattr(edge, "geometry", None)
            center = Utils._safe_getattr(geom, "center", None)
            if center is None:
                return anchor

            center_tuple = (center.x, center.y, center.z)
            for reflection in reversed(self._revolve_selector_reflections):
                if not self._point_on_axis(center_tuple, reflection["axis_origin"], reflection["axis_dir"]):
                    continue
                return self._reflect_point_across_plane(anchor, reflection["plane_origin"], reflection["plane_normal"])

            return anchor

    def _point_on_axis(
            self,
            point: Tuple[float, float, float],
            origin: Tuple[float, float, float],
            direction: Tuple[float, float, float],
            tolerance: float = 1e-6,
        ) -> bool:
            vx = point[0] - origin[0]
            vy = point[1] - origin[1]
            vz = point[2] - origin[2]
            cross = (
                vy * direction[2] - vz * direction[1],
                vz * direction[0] - vx * direction[2],
                vx * direction[1] - vy * direction[0],
            )
            return math.sqrt(cross[0] * cross[0] + cross[1] * cross[1] + cross[2] * cross[2]) <= tolerance

    def _reflect_point_across_plane(
            self,
            point: Tuple[float, float, float],
            origin: Tuple[float, float, float],
            normal: Tuple[float, float, float],
        ) -> Tuple[float, float, float]:
            vx = point[0] - origin[0]
            vy = point[1] - origin[1]
            vz = point[2] - origin[2]
            distance = vx * normal[0] + vy * normal[1] + vz * normal[2]
            return (
                point[0] - 2.0 * distance * normal[0],
                point[1] - 2.0 * distance * normal[1],
                point[2] - 2.0 * distance * normal[2],
            )

    def _edge_selector_expr(self, edges):
            try:
                selectors = self._edge_selector_terms(edges)
            except Exception:
                selectors = []

            if not selectors:
                return "# Original Fusion edge set; replace selector if needed.", "edges()"

            if len(selectors) == 1:
                return None, selectors[0]

            return None, "[" + ", ".join(selectors) + "]"

    def _face_centroid_exprs(self, entities) -> List[str]:
            centroids = []
            for entity in Utils._iter_fusion_collection(entities):
                if entity.objectType == adsk.fusion.BRepFace.classType():
                    p = entity.centroid
                    centroids.append(
                        Utils._fmt_tuple(
                            (
                                p.x * Utils.MM_PER_FUSION_UNIT,
                                p.y * Utils.MM_PER_FUSION_UNIT,
                                p.z * Utils.MM_PER_FUSION_UNIT,
                            )
                        )
                    )
            return centroids

    def _face_selector_expr(self, entities) -> Tuple[str, str]:
            try:
                centroids = self._face_centroid_exprs(entities)
            except Exception:
                centroids = []

            if not centroids:
                return "# Fusion shell did not expose removable face inputs; generated shell has no openings.", "None"

            comment = "# Original Fusion shell opening face centroids: " + ", ".join(centroids)
            if len(centroids) == 1:
                return comment, f"faces().sort_by_distance({centroids[0]})[0]"

            selectors = [f"faces().sort_by_distance({centroid})[0]" for centroid in centroids]
            return comment, "[" + ", ".join(selectors) + "]"
