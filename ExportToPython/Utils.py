"""
    Utility functions and helper classes for the Build123D Fusion exporter.

    Written by Ran Peleg, Visionware Solutions Pty Ltd
    ran@visionware.com.au
    Provided as-is, without warranty of any kind under Apache-2.0 license
"""

from __future__ import annotations

import math
import re
from typing import Iterable, List, Optional, Tuple

import adsk.core
import adsk.fusion


MM_PER_FUSION_UNIT = 10.0
_ARC_COLLINEARITY_TOL_MM = 1e-9
_TEXT_BBOX_TOLERANCE_MM = 0.05

# Lookup table for mapping Fusion materials "diffuse color" property
_DIFFUSE_COLOR_PROPERTY_IDS = (
    "opaque_albedo",       # Generic / plastic / paint appearances
    "generic_diffuse",     # Older "Generic" shader naming
    "layered_diffuse",     # Layered / metallic / pearlescent car paint
    "metal_f0",            # Metals (reflectance color at normal incidence)
    "wood_early_color",    # Wood
    "transparent_color",   # Glass / liquids
)


def clip_to_zero(x):
    return 0 if abs(x) < 1e-5 else x


def arc3d_to_three_point_arc(arc):
    ok, param_start, param_end = arc.evaluator.getParameterExtents()
    if not ok:
        raise ValueError("Failed to evaluate midpoint of Arc3D")

    ok, mid = arc.evaluator.getPointAtParameter((param_start + param_end) / 2.0)
    if not ok:
        raise ValueError("Failed to evaluate midpoint of Arc3D")

    return arc.startPoint, mid, arc.endPoint


def _is_effectively_collinear(p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float]) -> bool:
    (x1, y1), (x2, y2), (x3, y3) = p1, p2, p3
    dx, dy = x3 - x1, y3 - y1
    chord_len = math.hypot(dx, dy)
    if chord_len < _ARC_COLLINEARITY_TOL_MM:
        # start and end are (essentially) the same point -- not the "rounding
        # flattened a tiny arc" case this guards against, so leave the
        # ThreePointArc call as-is rather than emit a zero-length Line.
        return False
    cross = dx * (y2 - y1) - dy * (x2 - x1)
    return abs(cross) / chord_len <= _ARC_COLLINEARITY_TOL_MM


def _is_fusion_collection(value) -> bool:
    return value is not None and hasattr(value, "count") and hasattr(value, "item")


def _safe_cast(caster, value):
    if value is None:
        return None
    try:
        return caster(value)
    except Exception:
        return None


def _safe_getattr(value, name, default=None):
    try:
        return getattr(value, name, default)
    except Exception:
        return default


def _as_profile(value):
    if _is_fusion_collection(value):
        return None

    profile = _safe_cast(adsk.fusion.Profile.cast, value)
    if profile:
        return profile

    if _safe_getattr(value, "objectType") == adsk.fusion.Profile.classType():
        return value

    if _safe_getattr(value, "profileLoops", None) is not None and _safe_getattr(value, "parentSketch", None) is not None:
        return value

    return None


def get_profiles_list(profile_input):
    profiles = []

    if _is_fusion_collection(profile_input):
        items = _iter_fusion_collection(profile_input)
    else:
        items = [profile_input]

    for item in items:
        profile = _as_profile(item)
        if profile:
            profiles.append(profile)
    return profiles


def _as_sketch_text(value):
    if _is_fusion_collection(value):
        return None

    sketch_text = _safe_cast(adsk.fusion.SketchText.cast, value)
    if sketch_text:
        return sketch_text

    if _safe_getattr(value, "objectType") == adsk.fusion.SketchText.classType():
        return value

    return None


def get_sketch_texts_list(text_input):
    texts = []

    if _is_fusion_collection(text_input):
        items = _iter_fusion_collection(text_input)
    else:
        items = [text_input]

    for item in items:
        sketch_text = _as_sketch_text(item)
        if sketch_text:
            texts.append(sketch_text)
    return texts


def edge_mid_point(edge: adsk.fusion.BRepEdge) -> Optional[adsk.core.Point3D]:
    geom = edge.geometry

    if geom.curveType == adsk.core.Curve3DTypes.Circle3DCurveType:
        circle = adsk.core.Circle3D.cast(geom)
        if circle:
            return circle.center
    if geom.curveType == adsk.core.Curve3DTypes.Arc3DCurveType:
        arc = adsk.core.Arc3D.cast(geom)
        if arc:
            return arc.center

    evaluator = geom.evaluator
    ok, param_min, param_max = evaluator.getParameterExtents()
    if not ok:
        return None

    ok, total_length = evaluator.getLengthAtParameter(param_min, param_max)
    if not ok:
        return None

    ok, mid_param = evaluator.getParameterAtLength(param_min, total_length * 0.5)
    if not ok:
        return None

    ok, point = evaluator.getPointAtParameter(mid_param)
    if not ok:
        return None

    return point


def _safe_var_name(name: str) -> str:
    var_name = re.sub(r"\W+", "_", name or "fusion_model").strip("_").lower()
    if not var_name:
        var_name = "fusion_model"
    if var_name[0].isdigit():
        var_name = f"model_{var_name}"
    return var_name


def _fmt(value: float) -> str:
    return "{:.9g}".format(clip_to_zero(value))


def _fmt_tuple(values: Iterable[float]) -> str:
    return "(" + ", ".join(_fmt(v) for v in values) + ")"


def _param_value_mm(parameter) -> float:
    return parameter.value * MM_PER_FUSION_UNIT


def _param_value_number(parameter, default: float = 0.0) -> float:
    return parameter.value if parameter is not None else default


def _param_value_degrees(parameter, default: float = 360.0) -> float:
    return math.degrees(parameter.value) if parameter is not None else default


def _parameter_comment(parameter) -> str:
    expression = getattr(parameter, "expression", "")
    if expression:
        return f"  # Fusion expression: {expression}"
    return ""


def _iter_fusion_collection(collection):
    if collection is None:
        return []

    if hasattr(collection, "count") and hasattr(collection, "item"):
        return [collection.item(index) for index in range(collection.count)]

    try:
        return list(collection)
    except TypeError:
        pass

    if hasattr(collection, "objectType"):
        return [collection]

    return []


def _entity_bbox_mm(entity):
    """Return an entity's sketch-space bounding box in mm, or None if unavailable.

    Works for anything exposing a Fusion boundingBox property in sketch space
    (Profile, SketchText, ...), which is what lets us associate profile geometry
    with the SketchText entity that produced it.
    """
    try:
        bbox = getattr(entity, "boundingBox", None)
        if bbox is None:
            return None
        return (
            (bbox.minPoint.x * MM_PER_FUSION_UNIT, bbox.minPoint.y * MM_PER_FUSION_UNIT),
            (bbox.maxPoint.x * MM_PER_FUSION_UNIT, bbox.maxPoint.y * MM_PER_FUSION_UNIT),
        )
    except Exception:
        return None


def _bbox_contains(outer, inner, tolerance: float = _TEXT_BBOX_TOLERANCE_MM) -> bool:
    (ox0, oy0), (ox1, oy1) = outer
    (ix0, iy0), (ix1, iy1) = inner
    return (
        ix0 >= ox0 - tolerance
        and iy0 >= oy0 - tolerance
        and ix1 <= ox1 + tolerance
        and iy1 <= oy1 + tolerance
    )


def _axis_from_points(start, end) -> str:
    origin = _fmt_tuple((start.x * MM_PER_FUSION_UNIT, start.y * MM_PER_FUSION_UNIT, start.z * MM_PER_FUSION_UNIT))
    dx = end.x - start.x
    dy = end.y - start.y
    dz = end.z - start.z
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length > 1e-9:
        dx /= length
        dy /= length
        dz /= length
    direction = _fmt_tuple((dx, dy, dz))
    return f"Axis(origin={origin}, direction={direction})"


def _vector_tuple(vector) -> Tuple[float, float, float]:
    return (vector.x, vector.y, vector.z)


def _unit_vector_from_tuple(values: Tuple[float, float, float]):
    vector = adsk.core.Vector3D.create(values[0], values[1], values[2])
    if vector.length < 1e-9:
        return None
    vector.normalize()
    return vector


def _fallback_plane_x_dir(normal):
    reference = adsk.core.Vector3D.create(0, 0, 1)
    if abs(normal.dotProduct(reference)) > 0.95:
        reference = adsk.core.Vector3D.create(0, 1, 0)

    x_dir = reference.crossProduct(normal)
    if x_dir.length < 1e-9:
        return None
    x_dir.normalize()
    return x_dir


def _sketch_frame(sketch: adsk.fusion.Sketch):
    transform = sketch.transform.copy()

    origin = adsk.core.Point3D.create(0, 0, 0)
    x_point = adsk.core.Point3D.create(1, 0, 0)
    y_point = adsk.core.Point3D.create(0, 1, 0)
    origin.transformBy(transform)
    x_point.transformBy(transform)
    y_point.transformBy(transform)

    x_dir = adsk.core.Vector3D.create(
        x_point.x - origin.x,
        x_point.y - origin.y,
        x_point.z - origin.z,
    )
    y_dir = adsk.core.Vector3D.create(
        y_point.x - origin.x,
        y_point.y - origin.y,
        y_point.z - origin.z,
    )
    x_dir.normalize()
    y_dir.normalize()

    normal = x_dir.crossProduct(y_dir)
    normal.normalize()
    return origin, x_dir, y_dir, normal


class SketchMapper:
    """Map Fusion sketch/profile geometry into build123d local sketch coordinates."""

    def __init__(self, sketch: adsk.fusion.Sketch):
        self.sketch = sketch
        self.origin, self.x_dir, self.y_dir, self.normal = _sketch_frame(sketch)

    def local_point2d(self, point) -> Tuple[float, float]:
        return (point.x * MM_PER_FUSION_UNIT, point.y * MM_PER_FUSION_UNIT)

    def world_point2d(self, point) -> Tuple[float, float]:
        vec = adsk.core.Vector3D.create(
            point.x - self.origin.x,
            point.y - self.origin.y,
            point.z - self.origin.z,
        )
        return (
            vec.dotProduct(self.x_dir) * MM_PER_FUSION_UNIT,
            vec.dotProduct(self.y_dir) * MM_PER_FUSION_UNIT,
        )

    def value(self, value: float) -> float:
        return value * MM_PER_FUSION_UNIT


class CodeWriter:
    """Helper class for writing indented Python code to a list of lines."""

    def __init__(self):
        self.lines: List[str] = []
        self.level = 0

    def line(self, text: str = ""):
        self.lines.append(("    " * self.level) + text if text else "")

    def block(self, text: str):
        class Block:
            def __init__(self, writer, header):
                self.writer = writer
                self.header = header

            def __enter__(self):
                self.writer.line(self.header)
                self.writer.level += 1

            def __exit__(self, exc_type, exc, tb):
                self.writer.level -= 1

        return Block(self, text)

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"
