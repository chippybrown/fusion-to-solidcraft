"""
    Sketch and profile utilities for Build123D Python script generation.

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

class Sketches:
    def _profile_sketch(self, profile_input) -> Optional[adsk.fusion.Sketch]:
            direct_sketch = Utils._safe_getattr(profile_input, "parentSketch", None) or Utils._safe_getattr(profile_input, "parent", None)
            if Utils._safe_cast(adsk.fusion.Sketch.cast, direct_sketch):
                return direct_sketch

            for profile in Utils.get_profiles_list(profile_input):
                sketch = Utils._safe_getattr(profile, "parentSketch", None) or Utils._safe_getattr(profile, "parent", None)
                if Utils._safe_cast(adsk.fusion.Sketch.cast, sketch):
                    return sketch
            for sketch_text in Utils.get_sketch_texts_list(profile_input):
                sketch = Utils._safe_getattr(sketch_text, "parentSketch", None) or Utils._safe_getattr(sketch_text, "parent", None)
                if Utils._safe_cast(adsk.fusion.Sketch.cast, sketch):
                    return sketch
            return None

    def _export_profile_sketch(self, profile_input, sketch_name: str) -> str:
            sketch = self._profile_sketch(profile_input)
            if sketch is None:
                raise RuntimeError("Only sketch profiles can be translated to BuildSketch")

            mapper = Utils.SketchMapper(sketch)
            plane_expr, plane_comment = self._plane_expr(sketch)
            profiles = list(Utils.get_profiles_list(profile_input))
            direct_texts = Utils.get_sketch_texts_list(profile_input)
            text_matches = self._match_profiles_to_sketch_text(sketch, profiles)

            # Sketch-only export: everything this feature builds from is "used".
            try:
                self._mark_sketch_inputs_consumed(profiles)
                for _text in direct_texts:
                    self._remember_consumed_sketch_entity(_text)
                for _match in text_matches.values():
                    self._remember_consumed_sketch_entity(_match[0])
            except Exception:
                pass

            with self.writer.block(f"with BuildSketch({plane_expr}) as {sketch_name}:{plane_comment}"):
                emitted_texts = set()
                output_index = 0
                skipped_profile_errors = []

                for sketch_text in direct_texts:
                    emitted_texts.add(id(sketch_text))
                    output_index += 1
                    if output_index > 1:
                        self.writer.line(f"# Profile {output_index}")
                    self._export_sketch_text(sketch_text, mapper)

                for profile in profiles:
                    match = text_matches.get(id(profile))

                    if match is None:
                        output_index += 1
                        if output_index > 1:
                            self.writer.line(f"# Profile {output_index}")
                        try:
                            self._write_profile_summary(profile)
                            self._export_profile(profile, mapper)
                        except Exception as exc:
                            self.writer.line(f"# TODO: skipped unreadable profile: {exc}")
                            output_index -= 1
                            skipped_profile_errors.append(str(exc))
                        continue

                    sketch_text, is_multiline = match

                    if not is_multiline:
                        # Along-path/fit-on-path text can't be re-created as a clean
                        # Text() call without also reconstructing its path, so fall
                        # back to exporting the glyph outline curves as usual.
                        if id(sketch_text) not in emitted_texts:
                            emitted_texts.add(id(sketch_text))
                            self.writer.line(
                                "# Fusion sketch text below follows a path (along-path/fit-on-path);"
                            )
                            self.writer.line(
                                "# exported as raw glyph outline curves instead of Text(path=...)."
                            )
                            self.unsupported.append(
                                "Sketch text using along-path/fit-on-path positioning was exported as "
                                "raw glyph curves; consider rebuilding it with build123d's Text(path=...)."
                            )
                        output_index += 1
                        if output_index > 1:
                            self.writer.line(f"# Profile {output_index}")
                        try:
                            self._write_profile_summary(profile)
                            self._export_profile(profile, mapper)
                        except Exception as exc:
                            self.writer.line(f"# TODO: skipped unreadable profile: {exc}")
                            output_index -= 1
                            skipped_profile_errors.append(str(exc))
                        continue

                    if id(sketch_text) in emitted_texts:
                        # Another profile (e.g. a different character) from the same
                        # SketchText already emitted the Text() call for this object.
                        continue

                    emitted_texts.add(id(sketch_text))
                    output_index += 1
                    if output_index > 1:
                        self.writer.line(f"# Profile {output_index}")
                    self._export_sketch_text(sketch_text, mapper)

                if output_index == 0 and skipped_profile_errors:
                    fallback_texts = Utils.get_sketch_texts_list(Utils._safe_getattr(sketch, "sketchTexts", None))
                    for sketch_text in fallback_texts:
                        if id(sketch_text) in emitted_texts:
                            continue
                        emitted_texts.add(id(sketch_text))
                        self._remember_consumed_sketch_entity(sketch_text)
                        output_index += 1
                        if output_index == 1:
                            self.writer.line("# Fallback: Fusion text profile curves were unreadable; emitted SketchText directly.")
                        self._export_sketch_text(sketch_text, mapper)

                if skipped_profile_errors:
                    unique_errors = sorted(set(skipped_profile_errors))
                    self.unsupported.append(
                        "One or more sketch profiles could not be read from Fusion and were skipped: "
                        + "; ".join(unique_errors[:3])
                    )

                if output_index == 0:
                    self.writer.line("pass")
                    self.unsupported.append(
                        f"Sketch '{Utils._safe_getattr(sketch, 'name', sketch_name)}' produced no readable profiles or text."
                    )

            return sketch_name

    def _match_profiles_to_sketch_text(self, sketch: adsk.fusion.Sketch, profiles):
            """
            Fusion doesn't expose a direct link from a glyph outline curve back to the
            SketchText entity that generated it, so this uses bounding-box containment
            as a heuristic: if a profile's bounding box sits fully inside a text
            object's bounding box (within a small tolerance), it's treated as (part
            of) that text's rendered outline. This is conservative by design -- a
            profile that isn't contained in any text's bounding box is left alone and
            exported as ordinary curves, so unrelated sketch geometry is never
            silently dropped, only ever falls back to the previous behavior.
            """
            try:
                texts = Utils.get_sketch_texts_list(Utils._safe_getattr(sketch, "sketchTexts", None))
                if not texts:
                    return {}

                candidates = []
                for sketch_text in texts:
                    bbox = Utils._entity_bbox_mm(sketch_text)
                    if bbox is None:
                        continue
                    definition = Utils._safe_getattr(sketch_text, "definition", None)
                    multiline = Utils._safe_cast(adsk.fusion.MultiLineTextDefinition.cast, definition)
                    candidates.append((sketch_text, bbox, multiline is not None))

                matches = {}
                for profile in profiles:
                    profile_bbox = Utils._entity_bbox_mm(profile)
                    if profile_bbox is None:
                        continue
                    for sketch_text, text_bbox, is_multiline in candidates:
                        if Utils._bbox_contains(text_bbox, profile_bbox):
                            matches[id(profile)] = (sketch_text, is_multiline)
                            break

                return matches
            except Exception:
                return {}

    def _text_font_style_expr(self, sketch_text, text_value: str) -> Tuple[str, Optional[str]]:
            try:
                style = getattr(sketch_text, "textStyle", 0) or 0
                bold_bit = getattr(adsk.fusion.SketchTextStyles, "BoldSketchTextStyle", 1)
                italic_bit = getattr(adsk.fusion.SketchTextStyles, "ItalicSketchTextStyle", 2)
                underline_bit = getattr(adsk.fusion.SketchTextStyles, "UnderlineSketchTextStyle", 4)

                is_bold = bool(style & bold_bit)
                is_italic = bool(style & italic_bit)
                is_underline = bool(style & underline_bit)
            except Exception:
                is_bold = is_italic = is_underline = False

            if is_bold and is_italic:
                expr = "FontStyle.BOLDITALIC"
            elif is_bold:
                expr = "FontStyle.BOLD"
            elif is_italic:
                expr = "FontStyle.ITALIC"
            else:
                expr = "FontStyle.REGULAR"

            note = None
            if is_underline:
                note = (
                    f"Sketch text '{text_value}' uses underline styling, which build123d's Text() "
                    "has no equivalent for; underline was omitted."
                )
            return expr, note

    def _multiline_text_rotation(self, sketch_text) -> Tuple[float, Optional[str]]:
            try:
                definition = Utils._safe_getattr(sketch_text, "definition", None)
                multiline = Utils._safe_cast(adsk.fusion.MultiLineTextDefinition.cast, definition) if definition else None
                if multiline is None:
                    return 0.0, None

                lines = Utils._iter_fusion_collection(Utils._safe_getattr(multiline, "rectangleLines", None))
                if not lines:
                    return 0.0, None

                line = lines[0]
                start = line.startSketchPoint.geometry
                end = line.endSketchPoint.geometry
                dx = end.x - start.x
                dy = end.y - start.y
                if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                    return 0.0, None

                return math.degrees(math.atan2(dy, dx)), None
            except Exception:
                return 0.0, (
                    "Could not determine rotation for a sketch text object from its text-box edges; "
                    "rotation was left at 0 degrees, verify orientation."
                )

    def _export_sketch_text(self, sketch_text: adsk.fusion.SketchText, mapper: Utils.SketchMapper):
            text_param = Utils._safe_cast(adsk.fusion.ModelParameter.cast, Utils._safe_getattr(sketch_text, "textParameter", None))
            text_value = Utils._safe_getattr(text_param, "textValue", None) if text_param else None
            if not text_value:
                text_value = Utils._safe_getattr(sketch_text, "text", None) or ""

            height_param = Utils._safe_cast(adsk.fusion.ModelParameter.cast, Utils._safe_getattr(sketch_text, "heightParameter", None))
            if height_param is not None:
                font_size_expr, height_comment, _ = self._param_expr(height_param, "length")
            else:
                legacy_height = Utils._safe_getattr(sketch_text, "height", None)
                if legacy_height:
                    font_size_expr = Utils._fmt(legacy_height * Utils.MM_PER_FUSION_UNIT)
                    height_comment = ""
                else:
                    font_size_expr = Utils._fmt(5.0)
                    height_comment = "  # Fusion text height was unavailable; defaulted to 5 mm."
                    self.unsupported.append(
                        f"Sketch text '{text_value}' had no readable height; defaulted font_size to 5 mm."
                    )

            font_name = Utils._safe_getattr(sketch_text, "fontName", None) or "Arial"

            style_expr, style_note = self._text_font_style_expr(sketch_text, text_value)
            if style_note:
                self.unsupported.append(style_note)

            bbox = Utils._entity_bbox_mm(sketch_text)
            if bbox is not None:
                (x0, y0), (x1, y1) = bbox
                center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
            else:
                center = (0.0, 0.0)
                self.unsupported.append(
                    f"Sketch text '{text_value}' had no readable bounding box; placed at sketch origin."
                )

            rotation_deg, rotation_note = self._multiline_text_rotation(sketch_text)
            if rotation_note:
                self.unsupported.append(rotation_note)

            self.writer.line(
                f"# Fusion sketch text {text_value!r}; re-created natively instead of as glyph outline curves."
            )
            self.writer.line(
                "# Positioned at the text's bounding-box center; per-line justification is not replicated."
            )
            self.writer.line(f"with Locations({Utils._fmt_tuple(center)}):")
            self.writer.level += 1

            args = [
                repr(text_value),
                font_size_expr,
                f"font={font_name!r}",
                f"font_style={style_expr}",
                "align=(Align.CENTER, Align.CENTER)",
            ]
            if abs(rotation_deg) > 1e-9:
                args.append(f"rotation={Utils._fmt(rotation_deg)}")

            self.writer.line(f"Text({', '.join(args)}){height_comment}")
            self.writer.level -= 1

    def _export_profile(self, profile: adsk.fusion.Profile, mapper: Utils.SketchMapper):
            loops = Utils._iter_fusion_collection(Utils._safe_getattr(profile, "profileLoops", None))
            if not loops:
                raise RuntimeError("Fusion profile loops were unreadable")

            loops = sorted(loops, key=lambda loop: not Utils._safe_getattr(loop, "isOuter", False))
            for loop in loops:
                mode = "Mode.ADD" if Utils._safe_getattr(loop, "isOuter", False) else "Mode.SUBTRACT"
                self._export_loop(loop, mapper, mode)

    def _write_profile_summary(self, profile: adsk.fusion.Profile):
            loops = Utils._iter_fusion_collection(Utils._safe_getattr(profile, "profileLoops", None))
            curve_count = 0
            for loop in loops:
                curve_count += len(Utils._iter_fusion_collection(Utils._safe_getattr(loop, "profileCurves", None)))

            bbox = Utils._entity_bbox_mm(profile)
            if bbox is None:
                self.writer.line(f"# Fusion profile: {len(loops)} loop(s), {curve_count} curve(s)")
                return

            (x0, y0), (x1, y1) = bbox
            self.writer.line(
                "# Fusion profile: "
                f"{len(loops)} loop(s), {curve_count} curve(s), "
                f"bbox=({Utils._fmt_tuple((x0, y0))}, {Utils._fmt_tuple((x1, y1))})"
            )

    def _export_loop(self, loop: adsk.fusion.ProfileLoop, mapper: Utils.SketchMapper, mode: str):
            curves = Utils._iter_fusion_collection(Utils._safe_getattr(loop, "profileCurves", None))
            if not curves:
                raise RuntimeError("Fusion profile curves were unreadable")

            if len(curves) == 1:
                geom = self._sketch_curve_geometry(curves[0])
                sketch_entity = Utils._safe_getattr(curves[0], "sketchEntity", None)

                if isinstance(geom, adsk.core.Circle3D):
                    center = Utils._fmt_tuple(mapper.local_point2d(geom.center))
                    radius_expr = Utils._fmt(mapper.value(geom.radius))
                    if sketch_entity is not None:
                        radius_var = self._circle_radius_dimension_var(mapper.sketch, sketch_entity)
                        if radius_var:
                            radius_expr = radius_var
                    self.writer.line(f"with Locations({center}):")
                    self.writer.level += 1
                    self.writer.line(f"Circle({radius_expr}, mode={mode})")
                    self.writer.level -= 1
                    return
                if isinstance(geom, adsk.core.Ellipse3D):
                    center_pt = mapper.local_point2d(geom.center)
                    center = Utils._fmt_tuple(center_pt)
                    major_expr = Utils._fmt(mapper.value(geom.majorRadius))
                    minor_expr = Utils._fmt(mapper.value(geom.minorRadius))
                    if sketch_entity is not None:
                        major_var, minor_var = self._ellipse_radius_dimension_vars(mapper.sketch, sketch_entity)
                        if major_var:
                            major_expr = major_var
                        if minor_var:
                            minor_expr = minor_var

                    # geom.majorAxis carries the ellipse's actual orientation within
                    # the sketch; without reading it every ellipse would be exported
                    # axis-aligned regardless of how it's really rotated. Derive the
                    # in-plane rotation the same way rectangle/slot rotation is
                    # derived elsewhere in this file: map a second point out along
                    # the major axis through the mapper (so it picks up the sketch's
                    # own local frame, not raw 3D world coordinates) and read the
                    # angle back off the two mapped 2D points.
                    axis_point = geom.center.copy()
                    axis_offset = geom.majorAxis.copy()
                    axis_offset.scaleBy(geom.majorRadius)
                    axis_point.translateBy(axis_offset)
                    axis_pt_2d = mapper.local_point2d(axis_point)
                    rotation = math.degrees(math.atan2(axis_pt_2d[1] - center_pt[1], axis_pt_2d[0] - center_pt[0]))

                    self.writer.line(f"with Locations({center}):")
                    self.writer.level += 1
                    if abs(rotation) < 1e-6:
                        self.writer.line(f"Ellipse({major_expr}, {minor_expr}, mode={mode})")
                    else:
                        self.writer.line(
                            f"Ellipse({major_expr}, {minor_expr}, rotation={Utils._fmt(rotation)}, mode={mode})"
                        )
                    self.writer.level -= 1
                    return

            if len(curves) == 4:
                slot = self._slot_from_curves(curves, mapper)
                if slot is not None:
                    center, separation, height, rotation, line_entity, arc_entity = slot
                    separation_expr = Utils._fmt(separation)
                    height_expr = Utils._fmt(height)

                    if line_entity is not None:
                        separation_var = self._line_length_dimension_var(mapper.sketch, line_entity)
                        if separation_var:
                            separation_expr = separation_var
                    if arc_entity is not None:
                        radius_var = self._circle_radius_dimension_var(mapper.sketch, arc_entity)
                        if radius_var:
                            height_expr = f"{radius_var} * 2"

                    self.writer.line(f"with Locations({Utils._fmt_tuple(center)}):")
                    self.writer.level += 1
                    if abs(rotation) < 1e-6:
                        self.writer.line(f"SlotCenterToCenter({separation_expr}, {height_expr}, mode={mode})")
                    else:
                        self.writer.line(
                            f"SlotCenterToCenter({separation_expr}, {height_expr}, rotation={Utils._fmt(rotation)}, mode={mode})"
                        )
                    self.writer.level -= 1
                    return

            line_loop_result = self._line_loop_points(curves, mapper)
            line_loop_points = line_loop_result[0] if line_loop_result else None
            line_loop_edge_curves = line_loop_result[1] if line_loop_result else None

            if line_loop_points:
                rectangle = self._rectangle_from_points(line_loop_points)
                if rectangle is not None:
                    center, width, height, rotation = rectangle
                    width_expr = Utils._fmt(width)
                    height_expr = Utils._fmt(height)

                    if line_loop_edge_curves and len(line_loop_edge_curves) == 4:
                        width_edge = Utils._safe_getattr(line_loop_edge_curves[0], "sketchEntity", None)
                        height_edge = Utils._safe_getattr(line_loop_edge_curves[1], "sketchEntity", None)
                        opposite_width_edge = Utils._safe_getattr(line_loop_edge_curves[2], "sketchEntity", None)
                        opposite_height_edge = Utils._safe_getattr(line_loop_edge_curves[3], "sketchEntity", None)

                        if width_edge is not None:
                            width_var = self._line_length_dimension_var(mapper.sketch, width_edge, opposite_width_edge)
                            if width_var:
                                width_expr = width_var
                        if height_edge is not None:
                            height_var = self._line_length_dimension_var(mapper.sketch, height_edge, opposite_height_edge)
                            if height_var:
                                height_expr = height_var

                    self.writer.line(f"with Locations({Utils._fmt_tuple(center)}):")
                    self.writer.level += 1
                    if abs(rotation) < 1e-6:
                        self.writer.line(f"Rectangle({width_expr}, {height_expr}, mode={mode})")
                    else:
                        self.writer.line(
                            f"Rectangle({width_expr}, {height_expr}, rotation={Utils._fmt(rotation)}, mode={mode})"
                        )
                    self.writer.level -= 1
                    return

            self.loop_index += 1
            loop_name = f"loop_{self.loop_index}"

            ordered_curves = None if line_loop_points else self._ordered_loop_curves(curves, mapper)

            with self.writer.block(f"with BuildLine() as {loop_name}:"):
                if line_loop_points:
                    self.writer.line(f"Polyline({', '.join(Utils._fmt_tuple(point) for point in line_loop_points)}, close=True)")
                elif ordered_curves:
                    self._export_chained_loop_curves(ordered_curves, mapper, loop_name)
                else:
                    # Last resort: curves couldn't be chain-ordered by
                    # connectivity. Fusion's own `profileCurves` order is
                    # normally already connected, so emit them in that order --
                    # but each curve's start/end is otherwise formatted from its
                    # *own* geometry independently, and adjoining Fusion edges
                    # can report the "same" shared vertex with a tiny (sub-1e-4mm)
                    # floating point discrepancy. That's enough for OCCT to reject 
                    # the wire as not closed. Force
                    # textual identity instead: pin each curve's start to the
                    # exact text already emitted for the previous curve's end,
                    # and close the final curve's end back onto the first
                    # curve's own start.
                    first_pt = None
                    if curves:
                        first_endpoints = self._curve_endpoints(curves[0], mapper)
                        if first_endpoints is not None:
                            first_pt = first_endpoints[0]

                    last_pt = None
                    for index, curve in enumerate(curves):
                        is_last = index == len(curves) - 1
                        start_expr = Utils._fmt_tuple(last_pt) if last_pt is not None else None
                        end_expr = Utils._fmt_tuple(first_pt) if is_last and first_pt is not None else None
                        last_pt = self._export_profile_curve(
                            curve, mapper, last_pt, start_expr=start_expr, end_expr=end_expr
                        )

            self.writer.line(f"make_face({loop_name}.line, mode={mode})")

    def _export_chained_loop_curves(self, ordered_curves, mapper: Utils.SketchMapper, loop_name: str):
            first_edge_name = None
            previous_edge_name = None

            for index, (curve, reverse) in enumerate(ordered_curves):
                edge_name = f"{loop_name}_edge_{index + 1}"
                is_first = index == 0
                is_last = index == len(ordered_curves) - 1
                start_expr = None if is_first else f"{previous_edge_name} @ 1"
                end_expr = f"{first_edge_name} @ 0" if is_last and first_edge_name else None

                self._export_profile_curve(
                    curve,
                    mapper,
                    reverse=reverse,
                    edge_name=edge_name,
                    start_expr=start_expr,
                    end_expr=end_expr,
                )

                if first_edge_name is None:
                    first_edge_name = edge_name
                previous_edge_name = edge_name

    def _curve_endpoints(self, curve, mapper: Utils.SketchMapper):
            geom = self._sketch_curve_geometry(curve)
            if isinstance(geom, adsk.core.Line3D):
                return mapper.local_point2d(geom.startPoint), mapper.local_point2d(geom.endPoint)
            if isinstance(geom, adsk.core.Arc3D):
                return mapper.local_point2d(geom.startPoint), mapper.local_point2d(geom.endPoint)
            if isinstance(geom, (adsk.core.NurbsCurve3D, adsk.core.EllipticalArc3D)):
                points = self._sample_curve(geom, mapper)
                return points[0], points[-1]
            return None

    def _ordered_loop_curves(self, curves, mapper: Utils.SketchMapper):
            curve_segments = []
            for curve in curves:
                endpoints = self._curve_endpoints(curve, mapper)
                if endpoints is None:
                    return None
                curve_segments.append((curve, endpoints[0], endpoints[1]))

            if len(curve_segments) < 2:
                return None

            tol = 1e-4

            def dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
                return math.hypot(a[0] - b[0], a[1] - b[1])

            curve, start, end = curve_segments.pop(0)
            ordered = [(curve, False)]
            first = start
            last = end

            while curve_segments:
                # Pick the closest candidate endpoint within tolerance, not the
                # first one found in list order. Loops that pass close to
                # themselves (a near-zero-length edge, a cusp, two nearly
                # coincident vertices) can have several candidates within `tol`
                # of `last`; taking the first match found can thread the chain
                # onto the wrong curve, eventually stranding it (or worse,
                # silently mis-ordering it). Closest-first keeps the walk on the
                # actual connected edge in these cases.
                best_index = None
                best_dist = None
                best_reverse = False
                for index, (curve, start, end) in enumerate(curve_segments):
                    d_start = dist(start, last)
                    if d_start < tol and (best_dist is None or d_start < best_dist):
                        best_index, best_dist, best_reverse = index, d_start, False
                    d_end = dist(end, last)
                    if d_end < tol and (best_dist is None or d_end < best_dist):
                        best_index, best_dist, best_reverse = index, d_end, True

                if best_index is None:
                    return None

                curve, start, end = curve_segments.pop(best_index)
                if best_reverse:
                    ordered.append((curve, True))
                    last = start
                else:
                    ordered.append((curve, False))
                    last = end

            return ordered if dist(first, last) < tol else None

    def _line_loop_points(
            self, curves, mapper: Utils.SketchMapper
        ) -> Optional[Tuple[List[Tuple[float, float]], List[object]]]:
            """Order a closed loop of straight profile curves into points.

            Returns (points, edge_curves) where edge_curves[i] is the original
            profile curve connecting points[i] to points[(i + 1) % len(points)] --
            used by rectangle detection to trace each edge back to the Fusion
            SketchLine (and any dimension driving its length) that produced it.
            """
            segments = []
            for curve in curves:
                geom = self._sketch_curve_geometry(curve)
                if not isinstance(geom, adsk.core.Line3D):
                    return None
                segments.append((mapper.local_point2d(geom.startPoint), mapper.local_point2d(geom.endPoint), curve))

            if len(segments) < 3:
                return None

            def same_point(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
                return math.hypot(a[0] - b[0], a[1] - b[1]) < 1e-4

            start, end, first_curve = segments.pop(0)
            points = [start, end]
            edge_curves = [first_curve]
            while segments:
                last = points[-1]
                for index, (seg_start, seg_end, seg_curve) in enumerate(segments):
                    if same_point(seg_start, last):
                        points.append(seg_end)
                        edge_curves.append(seg_curve)
                        segments.pop(index)
                        break
                    if same_point(seg_end, last):
                        points.append(seg_start)
                        edge_curves.append(seg_curve)
                        segments.pop(index)
                        break
                else:
                    return None

            if not same_point(points[0], points[-1]):
                return None

            return points[:-1], edge_curves

    def _rectangle_from_points(
            self, points: List[Tuple[float, float]], tol: float = 1e-4
        ) -> Optional[Tuple[Tuple[float, float], float, float, float]]:
            """Detect whether a closed 4-point polygon is an (optionally rotated)
            rectangle. Returns (center, width, height, rotation_degrees) or None.
            """
            if len(points) != 4:
                return None

            def sub(a: Tuple[float, float], b: Tuple[float, float]) -> Tuple[float, float]:
                return (a[0] - b[0], a[1] - b[1])

            def dot(a: Tuple[float, float], b: Tuple[float, float]) -> float:
                return a[0] * b[0] + a[1] * b[1]

            def length(a: Tuple[float, float]) -> float:
                return math.hypot(a[0], a[1])

            p0, p1, p2, p3 = points
            edges = (sub(p1, p0), sub(p2, p1), sub(p3, p2), sub(p0, p3))
            edge_lengths = [length(edge) for edge in edges]

            if any(edge_len < tol for edge_len in edge_lengths):
                return None

            # Consecutive edges must be perpendicular.
            for a, b, la, lb in zip(edges, edges[1:] + edges[:1], edge_lengths, edge_lengths[1:] + edge_lengths[:1]):
                cos_angle = dot(a, b) / (la * lb)
                if abs(cos_angle) > 1e-3:
                    return None

            # Opposite sides must be (nearly) equal length.
            width, height = edge_lengths[0], edge_lengths[1]
            if abs(edge_lengths[0] - edge_lengths[2]) > max(tol, 1e-4 * width):
                return None
            if abs(edge_lengths[1] - edge_lengths[3]) > max(tol, 1e-4 * height):
                return None

            center = (
                sum(p[0] for p in points) / 4.0,
                sum(p[1] for p in points) / 4.0,
            )
            rotation = math.degrees(math.atan2(edges[0][1], edges[0][0]))

            return center, width, height, rotation

    @staticmethod
    def _is_semicircle(arc_geom, tol_degrees: float = 1.0) -> bool:
            """True if an Arc3D sweeps (within tolerance) exactly half a circle,
            i.e. it is one rounded end of a Fusion slot profile.
            """
            center = arc_geom.center
            start = arc_geom.startPoint
            end = arc_geom.endPoint
            v1 = (start.x - center.x, start.y - center.y)
            v2 = (end.x - center.x, end.y - center.y)
            cross = v1[0] * v2[1] - v1[1] * v2[0]
            dot = v1[0] * v2[0] + v1[1] * v2[1]
            sweep = abs(math.degrees(math.atan2(cross, dot)))
            return abs(sweep - 180.0) <= tol_degrees

    def _slot_from_curves(
            self, curves, mapper: Utils.SketchMapper, tol: float = 1e-4
        ) -> Optional[Tuple[Tuple[float, float], float, float, float, object, object]]:
            """Detect whether a closed 4-curve loop (two straight edges and two
            semicircular arcs) is a Fusion slot profile. Returns
            (center, center_separation, height, rotation_degrees, line_entity,
            arc_entity) -- where line_entity/arc_entity are the underlying Fusion
            sketch entities used for dimension-variable lookup -- or None.
            """
            if len(curves) != 4:
                return None

            ordered = self._ordered_loop_curves(curves, mapper)
            if ordered is None:
                return None

            geoms = [self._sketch_curve_geometry(curve) for curve, _ in ordered]
            kinds = []
            for geom in geoms:
                if isinstance(geom, adsk.core.Line3D):
                    kinds.append("line")
                elif isinstance(geom, adsk.core.Arc3D):
                    kinds.append("arc")
                else:
                    return None

            # Must alternate line/arc around the loop (in either phase).
            if kinds not in (["line", "arc", "line", "arc"], ["arc", "line", "arc", "line"]):
                return None

            if kinds[0] == "arc":
                ordered = ordered[1:] + ordered[:1]

            line1_curve = ordered[0][0]
            arc1_curve = ordered[1][0]
            line2_curve = ordered[2][0]
            arc2_curve = ordered[3][0]

            line1_geom = self._sketch_curve_geometry(line1_curve)
            line2_geom = self._sketch_curve_geometry(line2_curve)
            arc1_geom = self._sketch_curve_geometry(arc1_curve)
            arc2_geom = self._sketch_curve_geometry(arc2_curve)

            line1_start = mapper.local_point2d(line1_geom.startPoint)
            line1_end = mapper.local_point2d(line1_geom.endPoint)
            line2_start = mapper.local_point2d(line2_geom.startPoint)
            line2_end = mapper.local_point2d(line2_geom.endPoint)

            len1 = math.hypot(line1_end[0] - line1_start[0], line1_end[1] - line1_start[1])
            len2 = math.hypot(line2_end[0] - line2_start[0], line2_end[1] - line2_start[1])
            if len1 < tol or len2 < tol:
                return None
            if abs(len1 - len2) > max(tol, 1e-4 * len1):
                return None

            radius1 = mapper.value(arc1_geom.radius)
            radius2 = mapper.value(arc2_geom.radius)
            if radius1 < tol or radius2 < tol:
                return None
            if abs(radius1 - radius2) > max(tol, 1e-4 * radius1):
                return None

            if not (self._is_semicircle(arc1_geom) and self._is_semicircle(arc2_geom)):
                return None

            center1 = mapper.local_point2d(arc1_geom.center)
            center2 = mapper.local_point2d(arc2_geom.center)
            center_separation = math.hypot(center2[0] - center1[0], center2[1] - center1[1])
            if center_separation < tol:
                return None

            # The straight edges must run parallel to the axis joining the two
            # arc centers (the slot's long axis), not across it.
            axis = (
                (center2[0] - center1[0]) / center_separation,
                (center2[1] - center1[1]) / center_separation,
            )
            line1_dir = ((line1_end[0] - line1_start[0]) / len1, (line1_end[1] - line1_start[1]) / len1)
            alignment = abs(line1_dir[0] * axis[0] + line1_dir[1] * axis[1])
            if abs(alignment - 1.0) > 1e-3:
                return None

            height = radius1 + radius2  # == 2 * radius, averaged across both ends
            center = ((center1[0] + center2[0]) / 2.0, (center1[1] + center2[1]) / 2.0)
            rotation = math.degrees(math.atan2(axis[1], axis[0]))

            line_entity = Utils._safe_getattr(line1_curve, "sketchEntity", None)
            arc_entity = Utils._safe_getattr(arc1_curve, "sketchEntity", None)

            return center, center_separation, height, rotation, line_entity, arc_entity

    def _export_profile_curve(
            self,
            profile_curve,
            mapper: Utils.SketchMapper,
            last_point: Optional[Tuple[float, float]] = None,
            reverse: bool = False,
            edge_name: Optional[str] = None,
            start_expr: Optional[str] = None,
            end_expr: Optional[str] = None,
        ) -> Tuple[float, float]:
            geom = self._sketch_curve_geometry(profile_curve)
            if geom is None:
                raise RuntimeError("Fusion profile curve geometry was unreadable")

            if isinstance(geom, adsk.core.Line3D):
                start = mapper.local_point2d(geom.startPoint)
                end = mapper.local_point2d(geom.endPoint)
                if reverse:
                    start, end = end, start

                # If this is not the first segment and the start doesn't match where we left off, flip it
                if last_point is not None:
                    dist_start = math.hypot(start[0] - last_point[0], start[1] - last_point[1])
                    dist_end = math.hypot(end[0] - last_point[0], end[1] - last_point[1])
                    if dist_end < dist_start:
                        start, end = end, start

                start_arg = start_expr or Utils._fmt_tuple(start)
                end_arg = end_expr or Utils._fmt_tuple(end)
                prefix = f"{edge_name} = " if edge_name else ""
                self.writer.line(f"{prefix}Line({start_arg}, {end_arg})")
                return end

            elif isinstance(geom, adsk.core.Arc3D):
                start, mid, end = Utils.arc3d_to_three_point_arc(geom)
                start_pt = mapper.local_point2d(start)
                mid_pt = mapper.local_point2d(mid)
                end_pt = mapper.local_point2d(end)
                if reverse:
                    start_pt, end_pt = end_pt, start_pt

                if last_point is not None:
                    dist_start = math.hypot(start_pt[0] - last_point[0], start_pt[1] - last_point[1])
                    dist_end = math.hypot(end_pt[0] - last_point[0], end_pt[1] - last_point[1])
                    if dist_end < dist_start:
                        start_pt, end_pt = end_pt, start_pt

                rounded_start = (float(Utils._fmt(start_pt[0])), float(Utils._fmt(start_pt[1])))
                rounded_mid = (float(Utils._fmt(mid_pt[0])), float(Utils._fmt(mid_pt[1])))
                rounded_end = (float(Utils._fmt(end_pt[0])), float(Utils._fmt(end_pt[1])))

                start_arg = start_expr or Utils._fmt_tuple(start_pt)
                end_arg = end_expr or Utils._fmt_tuple(end_pt)
                prefix = f"{edge_name} = " if edge_name else ""
                if Utils._is_effectively_collinear(rounded_start, rounded_mid, rounded_end):
                    self.writer.line(f"{prefix}Line({start_arg}, {end_arg})  # Degenerate Arc")
                else:
                    self.writer.line(f"{prefix}ThreePointArc({start_arg}, {Utils._fmt_tuple(mid_pt)}, {end_arg})")
                return end_pt

            elif isinstance(geom, (adsk.core.NurbsCurve3D, adsk.core.EllipticalArc3D)):
                points = self._sample_curve(geom, mapper)
                if reverse:
                    points.reverse()
                if last_point is not None:
                    dist_start = math.hypot(points[0][0] - last_point[0], points[0][1] - last_point[1])
                    dist_end = math.hypot(points[-1][0] - last_point[0], points[-1][1] - last_point[1])
                    if dist_end < dist_start:
                        points.reverse()

                point_args = [Utils._fmt_tuple(p) for p in points]
                if start_expr:
                    point_args[0] = start_expr
                if end_expr:
                    point_args[-1] = end_expr
                prefix = f"{edge_name} = " if edge_name else ""
                self.writer.line(f"{prefix}Spline({', '.join(point_args)})")
                return points[-1]
            else:
                raise RuntimeError(f"Unsupported profile curve geometry: {type(geom).__name__}")

    def _sketch_curve_geometry(self, profile_curve):
            geometry = Utils._safe_getattr(profile_curve, "geometry", None)
            if geometry:
                return geometry

            sketch_entity = Utils._safe_getattr(profile_curve, "sketchEntity", None)
            return Utils._safe_getattr(sketch_entity, "geometry", None) if sketch_entity else None

    def _sample_curve(self, geom, mapper: Utils.SketchMapper, count: int = 9) -> List[Tuple[float, float]]:
            ok, start_param, end_param = geom.evaluator.getParameterExtents()
            if not ok:
                raise RuntimeError("Unable to read curve parameter range")
            points: List[Tuple[float, float]] = []
            for index in range(count):
                param = start_param + (end_param - start_param) * index / (count - 1)
                ok, point = geom.evaluator.getPointAtParameter(param)
                if not ok:
                    raise RuntimeError("Unable to sample curve point")
                points.append(mapper.local_point2d(point))
            return points

    # ------------------------------------------------------------------
    # Sketch-only geometry (LITTLEFOOT local change)
    #
    # Fusion sketches -- or the parts of sketches -- that no exported
    # feature consumes (engraving text, initials, signature curves, a
    # keyhole reference line, ...) used to be dropped entirely. They are
    # now collected after the timeline features and written as a separate,
    # clearly marked section: a plain-data SKETCH_ONLY list (for downstream
    # converters) plus a sketch_only_geometry() function that re-creates
    # them with build123d for viewing. Neither touches the BuildPart blocks,
    # so the part returned by build_<model>() is unchanged.
    # ------------------------------------------------------------------

    SKETCH_ONLY_INCLUDE_PARTIAL = True    # also emit unused curves/text of sketches that features use
    SKETCH_ONLY_INCLUDE_POINTS = True     # standalone sketch points (not connected to any curve)
    SKETCH_ONLY_SPLINE_SAMPLES = 33       # minimum samples per spline / elliptical arc / conic

    def _sketch_only_state(self):
            state = getattr(self, "_sketch_only_consumed", None)
            if state is None or "groups" not in state:
                state = {"tokens": set(), "groups": []}
                self._sketch_only_consumed = state
            return state

    def _sketch_only_snapshot(self):
            state = self._sketch_only_state()
            return (
                set(state["tokens"]),
                len(state["groups"]),
                [{key: len(value) for key, value in group["by_type"].items()} for group in state["groups"]],
            )

    def _sketch_only_restore(self, snapshot):
            if snapshot is None:
                return
            state = self._sketch_only_state()
            tokens, group_count, lengths = snapshot
            state["tokens"] = tokens
            del state["groups"][group_count:]
            for group, group_lengths in zip(state["groups"], lengths):
                for key in list(group["by_type"].keys()):
                    keep = group_lengths.get(key, 0)
                    if keep <= 0:
                        del group["by_type"][key]
                    else:
                        del group["by_type"][key][keep:]

    def _sketch_only_group(self, sketch, create: bool = False):
            """Consumed entities are grouped by their parent sketch so the
            (slower) equality fallback below only compares within one sketch."""
            state = self._sketch_only_state()
            token = Utils._safe_getattr(sketch, "entityToken", None) if sketch is not None else None
            for group in state["groups"]:
                if token and group["token"] == token:
                    return group
            for group in state["groups"]:
                try:
                    if sketch is not None and group["sketch"] is not None and group["sketch"] == sketch:
                        return group
                except Exception:
                    continue
            if sketch is None:
                for group in state["groups"]:
                    if group["sketch"] is None:
                        return group
            if not create:
                return None
            group = {"sketch": sketch, "token": token, "by_type": {}}
            state["groups"].append(group)
            return group

    def _remember_consumed_sketch_entity(self, entity):
            if entity is None:
                return
            state = self._sketch_only_state()
            token = Utils._safe_getattr(entity, "entityToken", None)
            if token:
                state["tokens"].add(token)
            object_type = Utils._safe_getattr(entity, "objectType", "") or ""
            group = self._sketch_only_group(Utils._safe_getattr(entity, "parentSketch", None), create=True)
            group["by_type"].setdefault(object_type, []).append(entity)

    def _is_consumed_sketch_entity(self, entity, group=None) -> bool:
            """True when an exported feature uses `entity`. Entity tokens are the
            fast path; Fusion object equality (==) within the same sketch is the
            fallback, since a token string is not guaranteed to be identical for
            every reference to the same entity."""
            state = self._sketch_only_state()
            token = Utils._safe_getattr(entity, "entityToken", None)
            if token and token in state["tokens"]:
                return True
            if group is None:
                group = self._sketch_only_group(Utils._safe_getattr(entity, "parentSketch", None))
            if group is None:
                return False
            object_type = Utils._safe_getattr(entity, "objectType", "") or ""
            for other in group["by_type"].get(object_type, ()):
                try:
                    if other == entity:
                        return True
                except Exception:
                    continue
            return False

    def _mark_sketch_inputs_consumed(self, value, depth: int = 0):
            """Remember every sketch curve / text / point that `value` (a
            Profile, a collection of profiles, a Path, loft sections, a
            sketch line used as an axis, ...) is built from, so the
            sketch-only pass leaves it out."""
            if value is None or depth > 5:
                return
            try:
                if Utils._is_fusion_collection(value) or isinstance(value, (list, tuple)):
                    items = Utils._iter_fusion_collection(value) if not isinstance(value, (list, tuple)) else list(value)
                else:
                    items = [value]
            except Exception:
                return

            sketch_type = adsk.fusion.Sketch.classType()
            for item in items:
                try:
                    object_type = Utils._safe_getattr(item, "objectType", "") or ""
                    loops = Utils._safe_getattr(item, "profileLoops", None)
                    if loops is not None:
                        for loop in Utils._iter_fusion_collection(loops):
                            for profile_curve in Utils._iter_fusion_collection(Utils._safe_getattr(loop, "profileCurves", None)):
                                self._remember_consumed_sketch_entity(Utils._safe_getattr(profile_curve, "sketchEntity", None))
                        continue
                    if object_type.startswith("adsk::fusion::Sketch") and object_type != sketch_type:
                        self._remember_consumed_sketch_entity(item)
                        continue
                    inner = Utils._safe_getattr(item, "entity", None)
                    if inner is not None:
                        self._mark_sketch_inputs_consumed(inner, depth + 1)
                except Exception:
                    continue

    def _mark_feature_inputs_consumed(self, feature):
            """Called after a timeline feature exported successfully."""
            for attr in ("profile", "profiles", "path", "guideRail", "loftSections", "centerLineOrRails",
                         "axis", "sketchPoints", "holePositionDefinition"):
                value = Utils._safe_getattr(feature, attr, None)
                if value is None:
                    continue
                if attr == "holePositionDefinition":
                    value = Utils._safe_getattr(value, "sketchPoints", None) or Utils._safe_getattr(value, "sketchPoint", None)
                self._mark_sketch_inputs_consumed(value)

    # -- collection -------------------------------------------------------

    def _sketch_only_iter_sketches(self):
            seen_components = []
            components = Utils._iter_fusion_collection(Utils._safe_getattr(self.design, "allComponents", None))
            if not components:
                root = Utils._safe_getattr(self.design, "rootComponent", None)
                components = [root] if root is not None else []
            for component in components:
                if component is None:
                    continue
                for sketch in Utils._iter_fusion_collection(Utils._safe_getattr(component, "sketches", None)):
                    yield component, sketch

    def _sketch_only_frame(self, sketch):
            origin, x_dir, y_dir, normal = Utils._sketch_frame(sketch)
            mm = Utils.MM_PER_FUSION_UNIT
            return {
                "origin": (origin.x * mm, origin.y * mm, origin.z * mm),
                "x_dir": (x_dir.x, x_dir.y, x_dir.z),
                "y_dir": (y_dir.x, y_dir.y, y_dir.z),
                "z_dir": (normal.x, normal.y, normal.z),
            }

    def _sketch_only_sample(self, geom, mapper, count: int) -> List[Tuple[float, float]]:
            ok, start_param, end_param = geom.evaluator.getParameterExtents()
            if not ok:
                raise RuntimeError("unable to read curve parameter range")
            points: List[Tuple[float, float]] = []
            for index in range(count):
                param = start_param + (end_param - start_param) * index / (count - 1)
                ok, point = geom.evaluator.getPointAtParameter(param)
                if not ok:
                    raise RuntimeError("unable to sample curve point")
                points.append(mapper.local_point2d(point))
            return points

    @staticmethod
    def _sketch_only_planar(geom) -> bool:
            for name in ("startPoint", "endPoint", "center"):
                point = Utils._safe_getattr(geom, name, None)
                if point is not None and abs(Utils._safe_getattr(point, "z", 0.0) or 0.0) > 1e-6:
                    return False
            return True

    def _sketch_only_curve_data(self, curve, mapper) -> Optional[dict]:
            geom = Utils._safe_getattr(curve, "geometry", None)
            if geom is None:
                raise RuntimeError("curve geometry unreadable")
            if not self._sketch_only_planar(geom):
                raise RuntimeError("curve does not lie in the sketch plane (3D sketch curve)")
            object_type = Utils._safe_getattr(curve, "objectType", "") or ""
            kind = object_type.split("::")[-1]

            if isinstance(geom, adsk.core.Line3D):
                start = mapper.local_point2d(geom.startPoint)
                end = mapper.local_point2d(geom.endPoint)
                if math.hypot(end[0] - start[0], end[1] - start[1]) < 1e-9:
                    return None
                return {"type": "line", "points": [start, end]}
            if isinstance(geom, adsk.core.Arc3D):
                start, mid, end = Utils.arc3d_to_three_point_arc(geom)
                return {"type": "arc", "points": [mapper.local_point2d(start), mapper.local_point2d(mid), mapper.local_point2d(end)]}
            if isinstance(geom, adsk.core.Circle3D):
                return {"type": "circle", "center": mapper.local_point2d(geom.center), "radius": mapper.value(geom.radius)}
            if isinstance(geom, adsk.core.Ellipse3D):
                center = mapper.local_point2d(geom.center)
                axis_point = geom.center.copy()
                axis_offset = geom.majorAxis.copy()
                axis_offset.scaleBy(geom.majorRadius)
                axis_point.translateBy(axis_offset)
                major_point = mapper.local_point2d(axis_point)
                rotation = math.degrees(math.atan2(major_point[1] - center[1], major_point[0] - center[0]))
                return {
                    "type": "ellipse",
                    "center": center,
                    "major_radius": mapper.value(geom.majorRadius),
                    "minor_radius": mapper.value(geom.minorRadius),
                    "rotation": rotation,
                    "major_point": major_point,
                }
            if isinstance(geom, (adsk.core.NurbsCurve3D, adsk.core.EllipticalArc3D)):
                count = int(self.SKETCH_ONLY_SPLINE_SAMPLES)
                fit_points = []
                fit_collection = Utils._safe_getattr(curve, "fitPoints", None)
                for sketch_point in Utils._iter_fusion_collection(fit_collection):
                    point_geom = Utils._safe_getattr(sketch_point, "geometry", None)
                    if point_geom is not None:
                        fit_points.append(mapper.local_point2d(point_geom))
                if fit_points:
                    count = max(count, 8 * (len(fit_points) - 1) + 1)
                count = max(3, min(count, 201))
                points = self._sketch_only_sample(geom, mapper, count)
                closed = math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1]) < 1e-6
                if closed:
                    points = points[:-1]
                data = {"type": "spline", "source": kind, "closed": closed, "points": points}
                if fit_points:
                    data["fit_points"] = fit_points
                if isinstance(geom, adsk.core.NurbsCurve3D):
                    degree = Utils._safe_getattr(geom, "degree", None)
                    if degree is not None:
                        data["degree"] = int(degree)
                return data
            raise RuntimeError(f"unsupported sketch curve geometry {type(geom).__name__}")

    def _sketch_only_text_data(self, sketch_text) -> dict:
            text_param = Utils._safe_cast(adsk.fusion.ModelParameter.cast, Utils._safe_getattr(sketch_text, "textParameter", None))
            text_value = Utils._safe_getattr(text_param, "textValue", None) if text_param else None
            if not text_value:
                text_value = Utils._safe_getattr(sketch_text, "text", None) or ""

            height_mm = None
            height_param = Utils._safe_cast(adsk.fusion.ModelParameter.cast, Utils._safe_getattr(sketch_text, "heightParameter", None))
            if height_param is not None:
                height_mm = Utils._safe_getattr(height_param, "value", None)
                height_mm = height_mm * Utils.MM_PER_FUSION_UNIT if height_mm is not None else None
            if not height_mm:
                legacy = Utils._safe_getattr(sketch_text, "height", None)
                height_mm = legacy * Utils.MM_PER_FUSION_UNIT if legacy else 5.0

            try:
                style = getattr(sketch_text, "textStyle", 0) or 0
                bold = bool(style & getattr(adsk.fusion.SketchTextStyles, "BoldSketchTextStyle", 1))
                italic = bool(style & getattr(adsk.fusion.SketchTextStyles, "ItalicSketchTextStyle", 2))
                underline = bool(style & getattr(adsk.fusion.SketchTextStyles, "UnderlineSketchTextStyle", 4))
            except Exception:
                bold = italic = underline = False

            bbox = Utils._entity_bbox_mm(sketch_text)
            if bbox is not None:
                (x0, y0), (x1, y1) = bbox
                center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
            else:
                center = (0.0, 0.0)

            rotation_deg, _note = self._multiline_text_rotation(sketch_text)
            definition = Utils._safe_getattr(sketch_text, "definition", None)
            multiline = Utils._safe_cast(adsk.fusion.MultiLineTextDefinition.cast, definition) if definition else None
            data = {
                "text": text_value,
                "font": Utils._safe_getattr(sketch_text, "fontName", None) or "Arial",
                "height": height_mm,
                "bold": bold,
                "italic": italic,
                "underline": underline,
                "center": center,
                "rotation": rotation_deg,
                "bbox": bbox,
                "on_path": definition is not None and multiline is None,
                "flip_h": bool(Utils._safe_getattr(sketch_text, "isHorizontalFlip", False)),
                "flip_v": bool(Utils._safe_getattr(sketch_text, "isVerticalFlip", False)),
            }
            return data

    def _sketch_only_collect(self) -> List[dict]:
            """Return one dict per Fusion sketch that has geometry no exported
            feature consumes. Never raises: problems become export notes."""
            results: List[dict] = []
            used_vars = set()
            sketch_type_name = "Sketch"
            for component, sketch in self._sketch_only_iter_sketches():
                sketch_name = Utils._safe_getattr(sketch, "name", None) or sketch_type_name
                try:
                    timeline_obj = Utils._safe_getattr(sketch, "timelineObject", None)
                    if timeline_obj is not None and (
                        Utils._safe_getattr(timeline_obj, "isSuppressed", False)
                        or Utils._safe_getattr(timeline_obj, "isRolledBack", False)
                    ):
                        continue

                    mapper = Utils.SketchMapper(sketch)
                    group = self._sketch_only_group(sketch)
                    if group is None:
                        group = {"sketch": sketch, "token": None, "by_type": {}}   # nothing in this sketch is used
                    curves: List[dict] = []
                    texts: List[dict] = []
                    points: List[Tuple[float, float]] = []
                    skipped: List[str] = []
                    total_curves = 0
                    consumed_any = False

                    for curve in Utils._iter_fusion_collection(Utils._safe_getattr(sketch, "sketchCurves", None)):
                        total_curves += 1
                        if Utils._safe_getattr(curve, "isConstruction", False):
                            continue
                        if Utils._safe_getattr(curve, "isCenterLine", False):
                            continue
                        if Utils._safe_getattr(curve, "isReference", False):
                            continue   # projected / included model geometry
                        if self._is_consumed_sketch_entity(curve, group):
                            consumed_any = True
                            continue
                        try:
                            data = self._sketch_only_curve_data(curve, mapper)
                            if data is not None:
                                curves.append(data)
                        except Exception as exc:
                            skipped.append(str(exc))

                    for sketch_text in Utils.get_sketch_texts_list(Utils._safe_getattr(sketch, "sketchTexts", None)):
                        if self._is_consumed_sketch_entity(sketch_text, group):
                            consumed_any = True
                            continue
                        try:
                            texts.append(self._sketch_only_text_data(sketch_text))
                        except Exception as exc:
                            skipped.append(f"text: {exc}")

                    if self.SKETCH_ONLY_INCLUDE_POINTS:
                        origin_point = Utils._safe_getattr(sketch, "originPoint", None)
                        for sketch_point in Utils._iter_fusion_collection(Utils._safe_getattr(sketch, "sketchPoints", None)):
                            try:
                                if Utils._safe_getattr(sketch_point, "isReference", False):
                                    continue
                                if origin_point is not None and sketch_point == origin_point:
                                    continue
                                connected = Utils._safe_getattr(sketch_point, "connectedEntities", None)
                                if connected is not None and Utils._safe_getattr(connected, "count", 0):
                                    continue
                                if self._is_consumed_sketch_entity(sketch_point, group):
                                    consumed_any = True
                                    continue
                                geom = Utils._safe_getattr(sketch_point, "geometry", None)
                                if geom is None or abs(Utils._safe_getattr(geom, "z", 0.0) or 0.0) > 1e-6:
                                    continue
                                points.append(mapper.local_point2d(geom))
                            except Exception:
                                continue

                    if skipped:
                        unique = sorted(set(skipped))
                        self.unsupported.append(
                            f"Sketch-only: {len(skipped)} curve(s) of sketch '{sketch_name}' could not be exported: "
                            + "; ".join(unique[:3])
                        )

                    if not curves and not texts and not points:
                        continue
                    if consumed_any and not self.SKETCH_ONLY_INCLUDE_PARTIAL:
                        continue

                    base_var = "sketch_" + Utils._safe_var_name(sketch_name)
                    var = base_var
                    suffix = 2
                    while var in used_vars:
                        var = f"{base_var}_{suffix}"
                        suffix += 1
                    used_vars.add(var)

                    results.append({
                        "name": sketch_name,
                        "var": var,
                        "component": Utils._safe_getattr(component, "name", "") or "",
                        "visible": bool(Utils._safe_getattr(sketch, "isVisible", True)),
                        "partial": bool(consumed_any),
                        "plane": self._sketch_only_frame(sketch),
                        "curves": curves,
                        "texts": texts,
                        "points": points,
                    })
                except Exception as exc:
                    self.unsupported.append(f"Sketch-only export of sketch '{sketch_name}' failed: {exc}")
            return results

    # -- writing ----------------------------------------------------------

    @staticmethod
    def _so_pt(point) -> str:
            return Utils._fmt_tuple(point)

    @staticmethod
    def _so_bool(value) -> str:
            return "True" if value else "False"

    def _so_curve_literal(self, curve: dict) -> str:
            kind = curve["type"]
            if kind in ("line", "arc"):
                pts = ", ".join(self._so_pt(p) for p in curve["points"])
                return f'{{"type": "{kind}", "points": [{pts}]}}'
            if kind == "circle":
                return f'{{"type": "circle", "center": {self._so_pt(curve["center"])}, "radius": {Utils._fmt(curve["radius"])}}}'
            if kind == "ellipse":
                return (
                    f'{{"type": "ellipse", "center": {self._so_pt(curve["center"])}, '
                    f'"major_radius": {Utils._fmt(curve["major_radius"])}, "minor_radius": {Utils._fmt(curve["minor_radius"])}, '
                    f'"rotation": {Utils._fmt(curve["rotation"])}, "major_point": {self._so_pt(curve["major_point"])}}}'
                )
            pts = ", ".join(self._so_pt(p) for p in curve["points"])
            extra = ""
            if curve.get("degree") is not None:
                extra += f', "degree": {int(curve["degree"])}'
            if curve.get("fit_points"):
                extra += ', "fit_points": [' + ", ".join(self._so_pt(p) for p in curve["fit_points"]) + "]"
            return (
                f'{{"type": "spline", "source": {curve.get("source", "")!r}, "closed": {self._so_bool(curve.get("closed"))}'
                f'{extra}, "points": [{pts}]}}'
            )

    def _so_text_literal(self, text: dict) -> str:
            bbox = text.get("bbox")
            bbox_expr = "None" if bbox is None else f"({self._so_pt(bbox[0])}, {self._so_pt(bbox[1])})"
            return (
                f'{{"text": {text["text"]!r}, "font": {text["font"]!r}, "height": {Utils._fmt(text["height"])}, '
                f'"bold": {self._so_bool(text["bold"])}, "italic": {self._so_bool(text["italic"])}, '
                f'"underline": {self._so_bool(text["underline"])}, "center": {self._so_pt(text["center"])}, '
                f'"rotation": {Utils._fmt(text["rotation"])}, "bbox": {bbox_expr}, '
                f'"on_path": {self._so_bool(text["on_path"])}, "flip_h": {self._so_bool(text["flip_h"])}, '
                f'"flip_v": {self._so_bool(text["flip_v"])}}}'
            )

    def _write_sketch_only_section(self) -> int:
            """Write SKETCH_ONLY / SKETCH_ONLY_COUNT and sketch_only_geometry()
            at module level. Returns how many sketch-only sketches were written.
            Never raises (a failure leaves an empty SKETCH_ONLY and a note)."""
            try:
                entries = self._sketch_only_collect()
            except Exception as exc:
                entries = []
                self.unsupported.append(f"Sketch-only export failed: {exc}")

            self.sketch_only_count = len(entries)
            self.sketch_only_names = [entry["name"] for entry in entries]
            w = self.writer

            w.line()
            w.line()
            w.line("# " + "-" * 75)
            w.line("# Sketch-only geometry")
            w.line("# Fusion sketches (or the parts of sketches) that no exported feature uses:")
            w.line("# engraving text, initials, signature curves, reference lines, ... They are")
            w.line("# kept here so they are not lost, but they never ADD to or SUBTRACT from the")
            w.line("# part: the build function above returns exactly the same part as before.")
            w.line("# SKETCH_ONLY is plain data for converters: one dict per sketch with its plane")
            w.line("# (world origin/x_dir/y_dir/z_dir, mm) and curves/text/points in sketch-local mm.")
            w.line("# Construction, centerline and projected curves are left out. 'partial' = the")
            w.line("# Fusion sketch also has curves used by features (only the unused ones are here).")
            w.line("# Text is recreated from its font name and may not match Fusion's rendering.")
            w.line("# " + "-" * 75)
            w.line(f"SKETCH_ONLY_COUNT = {len(entries)}")
            if not entries:
                w.line("SKETCH_ONLY = []")
            else:
                w.line("SKETCH_ONLY = [")
                w.level += 1
                for entry in entries:
                    plane = entry["plane"]
                    w.line("{")
                    w.level += 1
                    w.line(f'"name": {entry["name"]!r},')
                    w.line(f'"var": {entry["var"]!r},')
                    w.line(f'"component": {entry["component"]!r},')
                    w.line(f'"visible": {self._so_bool(entry["visible"])},')
                    w.line(f'"partial": {self._so_bool(entry["partial"])},')
                    w.line(
                        f'"plane": {{"origin": {self._so_pt(plane["origin"])}, "x_dir": {self._so_pt(plane["x_dir"])}, '
                        f'"y_dir": {self._so_pt(plane["y_dir"])}, "z_dir": {self._so_pt(plane["z_dir"])}}},'
                    )
                    if entry["curves"]:
                        w.line('"curves": [')
                        w.level += 1
                        for curve in entry["curves"]:
                            w.line(self._so_curve_literal(curve) + ",")
                        w.level -= 1
                        w.line("],")
                    else:
                        w.line('"curves": [],')
                    if entry["texts"]:
                        w.line('"texts": [')
                        w.level += 1
                        for text in entry["texts"]:
                            w.line(self._so_text_literal(text) + ",")
                        w.level -= 1
                        w.line("],")
                    else:
                        w.line('"texts": [],')
                    w.line('"points": [' + ", ".join(self._so_pt(p) for p in entry["points"]) + "],")
                    w.level -= 1
                    w.line("},")
                w.level -= 1
                w.line("]")

            w.line()
            w.line()
            with w.block("def sketch_only_geometry():"):
                w.line('"""Re-create the SKETCH_ONLY sketches with build123d, for viewing only.')
                w.line()
                w.line("Returns {SKETCH_ONLY 'var' name: (BuildSketch with the text or None,")
                w.line("BuildLine with the curves or None)}. Not called by the build function and")
                w.line("never combined with the part.")
                w.line('"""')
                w.line("sketches = {}")
                for entry in entries:
                    self._write_sketch_only_block(entry)
                w.line("return sketches")
            return len(entries)

    def _write_sketch_only_block(self, entry: dict):
            w = self.writer
            plane = entry["plane"]
            var = entry["var"]
            w.line()
            w.line(
                f"# Sketch-only: Fusion sketch {entry['name']!r}"
                + (f" (component {entry['component']!r})" if entry["component"] else "")
                + f": {len(entry['curves'])} curve(s), {len(entry['texts'])} text(s), {len(entry['points'])} point(s)"
                + (" -- unused part of a sketch that features also use" if entry["partial"] else "")
            )
            w.line(
                f"{var}_plane = Plane(origin={self._so_pt(plane['origin'])}, x_dir={self._so_pt(plane['x_dir'])}, "
                f"z_dir={self._so_pt(plane['z_dir'])})"
            )
            text_var = "None"
            line_var = "None"
            if entry["texts"]:
                text_var = var
                with w.block(f"with BuildSketch({var}_plane, mode=Mode.PRIVATE) as {var}:"):
                    for text in entry["texts"]:
                        style = "FontStyle.REGULAR"
                        if text["bold"] and text["italic"]:
                            style = "FontStyle.BOLDITALIC"
                        elif text["bold"]:
                            style = "FontStyle.BOLD"
                        elif text["italic"]:
                            style = "FontStyle.ITALIC"
                        w.line(f"# Fusion sketch text {text['text']!r} (font {text['font']!r}); placed at its bounding-box center.")
                        w.line(f"with Locations({self._so_pt(text['center'])}):")
                        w.level += 1
                        args = [
                            repr(text["text"]),
                            Utils._fmt(text["height"]),
                            f"font={text['font']!r}",
                            f"font_style={style}",
                            "align=(Align.CENTER, Align.CENTER)",
                        ]
                        if abs(text["rotation"]) > 1e-9:
                            args.append(f"rotation={Utils._fmt(text['rotation'])}")
                        w.line(f"Text({', '.join(args)})")
                        w.level -= 1
            if entry["curves"]:
                line_var = f"{var}_curves"
                with w.block(f"with BuildLine({var}_plane, mode=Mode.PRIVATE) as {line_var}:"):
                    for curve in entry["curves"]:
                        kind = curve["type"]
                        if kind == "line":
                            w.line(f"Line({self._so_pt(curve['points'][0])}, {self._so_pt(curve['points'][1])})")
                        elif kind == "arc":
                            pts = curve["points"]
                            if Utils._is_effectively_collinear(pts[0], pts[1], pts[2]):
                                w.line(f"Line({self._so_pt(pts[0])}, {self._so_pt(pts[2])})  # degenerate arc")
                            else:
                                w.line(f"ThreePointArc({', '.join(self._so_pt(p) for p in pts)})")
                        elif kind == "circle":
                            w.line(f"CenterArc({self._so_pt(curve['center'])}, {Utils._fmt(curve['radius'])}, 0, 360)")
                        elif kind == "ellipse":
                            # Sampled periodic spline: EllipticalCenterArc's signature differs
                            # between build123d versions. SKETCH_ONLY keeps the exact ellipse.
                            cx, cy = curve["center"]
                            a, b = curve["major_radius"], curve["minor_radius"]
                            rot = math.radians(curve["rotation"])
                            samples = []
                            for index in range(48):
                                t = 2.0 * math.pi * index / 48
                                ex, ey = a * math.cos(t), b * math.sin(t)
                                samples.append((cx + ex * math.cos(rot) - ey * math.sin(rot), cy + ex * math.sin(rot) + ey * math.cos(rot)))
                            w.line(f"Spline({', '.join(self._so_pt(p) for p in samples)}, periodic=True)  # ellipse")
                        else:
                            pts = ", ".join(self._so_pt(p) for p in curve["points"])
                            periodic = ", periodic=True" if curve.get("closed") else ""
                            w.line(f"Spline({pts}{periodic})")
            if entry["points"]:
                w.line("# standalone sketch points: " + ", ".join(self._so_pt(p) for p in entry["points"]))
            w.line(f"sketches[{var!r}] = ({text_var}, {line_var})")
