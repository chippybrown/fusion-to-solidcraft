"""
    Geometry and construction plane utilities for Build123D Python script generation.

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

class Geometry:
    def _plane_expr(self, sketch: adsk.fusion.Sketch) -> Tuple[str, str]:
            reference_plane = Utils._safe_getattr(sketch, "referencePlane", None)
            construction_plane = Utils._safe_cast(adsk.fusion.ConstructionPlane.cast, reference_plane)
            if construction_plane is not None:
                parametric = self._offset_plane_expr(construction_plane)
                if parametric is not None:
                    return parametric

            origin, x_dir, _, normal = Utils._sketch_frame(sketch)
            origin_mm = (origin.x * Utils.MM_PER_FUSION_UNIT, origin.y * Utils.MM_PER_FUSION_UNIT, origin.z * Utils.MM_PER_FUSION_UNIT)
            return self._frame_to_plane_expr(origin_mm, x_dir, normal)

    def _plane_entity_frame(self, plane_entity):
            """Resolve `plane_entity` (a ConstructionPlane, planar BRepFace, or raw
            Fusion Plane geometry) to a numeric (origin, x_dir, normal) frame in
            Fusion's native (cm) units, or None if it can't be resolved. This is
            always fully evaluated -- it carries no link back to any parameter
            that may have positioned the plane.
            """
            geometry = Utils._safe_getattr(plane_entity, "geometry", None)
            if geometry is None:
                geometry = plane_entity

            origin = (
                Utils._safe_getattr(geometry, "origin", None)
                or Utils._safe_getattr(geometry, "rootPoint", None)
                or Utils._safe_getattr(geometry, "basePoint", None)
            )
            normal = Utils._safe_getattr(geometry, "normal", None)
            x_dir = (
                Utils._safe_getattr(geometry, "uDirection", None)
                or Utils._safe_getattr(geometry, "xDirection", None)
                or Utils._safe_getattr(geometry, "xAxis", None)
            )

            if normal is None and Utils._safe_getattr(plane_entity, "objectType", None) == adsk.fusion.BRepFace.classType():
                evaluator = Utils._safe_getattr(plane_entity, "evaluator", None)
                point = Utils._safe_getattr(plane_entity, "pointOnFace", None)
                if evaluator is not None and point is not None:
                    ok, normal_at_point = evaluator.getNormalAtPoint(point)
                    if ok:
                        normal = normal_at_point
                        origin = point if origin is None else origin

            if origin is None or normal is None:
                return None

            normal = Utils._unit_vector_from_tuple(Utils._vector_tuple(normal))
            if normal is None:
                return None

            if x_dir is not None:
                x_dir = Utils._unit_vector_from_tuple(Utils._vector_tuple(x_dir))
            if x_dir is None:
                x_dir = Utils._fallback_plane_x_dir(normal)
            if x_dir is None:
                return None

            return origin, x_dir, normal

    def _construction_plane_offset_definition(self, construction_plane):
            """If `construction_plane` was built with the Offset Plane tool,
            return (base_planar_entity, offset_ModelParameter); otherwise None.

            Offset is the one construction-plane definition that exposes its
            driving distance as a ModelParameter the same way extrude/fillet/
            chamfer dimensions do (see ConstructionPlaneOffsetDefinition.offset
            in the Fusion API). Other definition types (at-angle, midplane,
            tangent, three-point, etc.) don't reduce to a single linear
            parameter this way, so they still fall back to the plain numeric
            plane translation below.
            """
            definition = Utils._safe_getattr(construction_plane, "definition", None)
            offset_definition = Utils._safe_cast(adsk.fusion.ConstructionPlaneOffsetDefinition.cast, definition)
            if offset_definition is None:
                return None

            base_entity = Utils._safe_getattr(offset_definition, "planarEntity", None)
            model_parameter = Utils._safe_cast(
                adsk.fusion.ModelParameter.cast, Utils._safe_getattr(offset_definition, "offset", None)
            )
            if base_entity is None or model_parameter is None:
                return None
            return base_entity, model_parameter

    def _axis_offset_expr(
            self, base_term: str, normal_component: float, offset_expr: str, residual: float = 0.0
        ) -> str:

            terms = []

            if abs(normal_component) >= 1e-9:
                if abs(normal_component - 1.0) < 1e-9:
                    terms.append(offset_expr)
                elif abs(normal_component + 1.0) < 1e-9:
                    terms.append(f"-({offset_expr})")
                else:
                    terms.append(f"({offset_expr}) * {Utils._fmt(normal_component)}")

            if abs(residual) >= 1e-9:
                residual_fmt = Utils._fmt(residual)
                if residual_fmt.startswith("-"):
                    terms.append(f"- {residual_fmt[1:]}" if terms else residual_fmt)
                else:
                    terms.append(f"+ {residual_fmt}" if terms else residual_fmt)

            if not terms:
                return base_term

            combined = terms[0]
            for term in terms[1:]:
                combined = f"{combined} {term}" if term.startswith(("+", "-")) else f"{combined} + {term}"

            if base_term == Utils._fmt(0.0):
                return combined
            return f"{base_term} + {combined}"

    def _base_origin_terms(
            self, origin_mm: Tuple[float, float, float], normal: Tuple[float, float, float]
        ) -> Tuple[str, str, str]:
            """Express `origin_mm` as source text for use as the base of a new
            parametric offset plane, chaining through any previously-registered
            parametric plane (see _register_parametric_offset_plane) that this
            exact point already lies on. Without this, stacking a second
            parametric offset on top of a first (e.g. two extrudes that each
            reuse the same Fusion user parameter) would flatten the first
            stage's already-symbolic origin back down to today's plain number
            before appending the second offset on top of it.
            """
            match = self._lookup_parametric_plane_origin(origin_mm, normal)
            if match is not None:
                origin_exprs, _comment = match
                return origin_exprs
            return tuple(Utils._fmt(v) for v in origin_mm)

    def _register_parametric_offset_plane(
            self,
            base_origin_mm: Tuple[float, float, float],
            base_normal: Tuple[float, float, float],
            amount_mm: float,
            offset_expr: str,
            comment: str,
        ):
            """Record that the plane offset `amount_mm` (mm) along `base_normal`
            from `base_origin_mm` -- typically an extrude's cap face -- is
            described by the live expression `offset_expr`. Any later sketch or
            mirror plane found lying exactly on this plane.
            """
            base_origin_expr = self._base_origin_terms(base_origin_mm, base_normal)
            self._parametric_planes.append(
                {
                    "base_origin_mm": base_origin_mm,
                    "base_origin_expr": base_origin_expr,
                    "base_normal": base_normal,
                    "amount_mm": amount_mm,
                    "offset_expr": offset_expr,
                    "comment": comment,
                }
            )

    # Tolerance (mm) for matching a candidate plane's numeric
    # position against a registered parametric plane
    _PLANE_MATCH_TOL_MM = 1e-4

    def _lookup_parametric_plane_origin(
            self, origin_mm: Tuple[float, float, float], normal: Tuple[float, float, float]
        ) -> Optional[Tuple[Tuple[str, str, str], str]]:
            for entry in reversed(self._parametric_planes):
                base_origin_mm = entry["base_origin_mm"]
                base_origin_expr = entry["base_origin_expr"]
                base_normal = entry["base_normal"]

                dot_normals = sum(a * b for a, b in zip(base_normal, normal))
                if abs(abs(dot_normals) - 1.0) > 1e-6:
                    continue  # not parallel to this registered plane

                displacement = tuple(o - b for o, b in zip(origin_mm, base_origin_mm))
                along = sum(d * n for d, n in zip(displacement, base_normal))
                if abs(along - entry["amount_mm"]) > self._PLANE_MATCH_TOL_MM:
                    continue  # parallel, but not offset by the registered amount

                # Whatever part of the displacement isn't along the registered
                # normal (e.g. a hole's in-plane position on the offset face)
                # is a fixed numeric offset -- it doesn't move when the
                # parametric distance driving the along-normal offset changes,
                # so it must be preserved per-axis rather than dropped.
                residual = tuple(
                    d - n * entry["amount_mm"] for d, n in zip(displacement, base_normal)
                )

                origin_exprs = tuple(
                    self._axis_offset_expr(
                        base_origin_expr[i], base_normal[i], entry["offset_expr"], residual[i]
                    )
                    for i in range(3)
                )
                return origin_exprs, entry["comment"]
            return None

    def _frame_to_plane_expr(self, origin_mm: Tuple[float, float, float], x_dir, normal) -> Tuple[str, str]:
            """Build a Plane(...) expression for a numeric (origin_mm, x_dir,
            normal) frame, substituting a registered parametric origin (see
            _register_parametric_offset_plane) when this exact plane was
            produced by a prior extrude whose distance traces back to a
            registered Fusion user parameter.
            """
            match = self._lookup_parametric_plane_origin(origin_mm, (normal.x, normal.y, normal.z))
            if match is not None:
                origin_exprs, comment = match
            else:
                origin_exprs = tuple(Utils._fmt(v) for v in origin_mm)
                comment = ""

            expr = "Plane(origin=({}, {}, {}), x_dir={}, z_dir={})".format(
                origin_exprs[0], origin_exprs[1], origin_exprs[2],
                Utils._fmt_tuple((x_dir.x, x_dir.y, x_dir.z)),
                Utils._fmt_tuple((normal.x, normal.y, normal.z)),
            )
            return expr, comment

    def _offset_plane_expr(self, construction_plane) -> Optional[Tuple[str, str]]:
            """If `construction_plane` is an Offset Plane whose distance traces
            back to a registered Fusion user parameter, return (expr, comment)
            with the plane's origin written in terms of that parameter's script
            variable -- so editing the variable at the top of the generated
            script moves the plane the same way editing the parameter does in
            Fusion, instead of always baking in today's numeric position.

            Returns None for every other case (a non-offset plane definition,
            or an offset that isn't a registered user-parameter variable), so
            the caller falls back to the existing fully-numeric translation.
            Chained offsets (an offset plane built from another parametric
            offset, e.g. an earlier extrude's cap face) resolve the base
            plane's own position through _base_origin_terms too, so this
            offset composes into a single expression with the earlier one
            instead of flattening it back to a plain number.
            """
            result = self._construction_plane_offset_definition(construction_plane)
            if result is None:
                return None
            base_entity, offset_parameter = result

            offset_expr, offset_comment, is_var = self._param_expr(offset_parameter, "length")
            if not is_var:
                return None

            base_frame = self._plane_entity_frame(base_entity)
            if base_frame is None:
                return None
            base_origin, x_dir, normal = base_frame

            base_origin_mm = (
                base_origin.x * Utils.MM_PER_FUSION_UNIT,
                base_origin.y * Utils.MM_PER_FUSION_UNIT,
                base_origin.z * Utils.MM_PER_FUSION_UNIT,
            )
            normal_components = (normal.x, normal.y, normal.z)
            base_origin_terms = self._base_origin_terms(base_origin_mm, normal_components)
            origin_exprs = tuple(
                self._axis_offset_expr(base_term, comp, offset_expr)
                for base_term, comp in zip(base_origin_terms, normal_components)
            )

            expr = "Plane(origin=({}, {}, {}), x_dir={}, z_dir={})".format(
                origin_exprs[0], origin_exprs[1], origin_exprs[2],
                Utils._fmt_tuple((x_dir.x, x_dir.y, x_dir.z)),
                Utils._fmt_tuple((normal.x, normal.y, normal.z)),
            )
            return expr, offset_comment

    def _plane_entity_expr(self, plane_entity) -> Tuple[Optional[str], str]:
            construction_plane = Utils._safe_cast(adsk.fusion.ConstructionPlane.cast, plane_entity)
            if construction_plane is not None:
                parametric = self._offset_plane_expr(construction_plane)
                if parametric is not None:
                    return parametric

            frame = self._plane_entity_frame(plane_entity)
            if frame is None:
                return None, ""
            origin, x_dir, normal = frame
            origin_mm = (origin.x * Utils.MM_PER_FUSION_UNIT, origin.y * Utils.MM_PER_FUSION_UNIT, origin.z * Utils.MM_PER_FUSION_UNIT)
            return self._frame_to_plane_expr(origin_mm, x_dir, normal)
