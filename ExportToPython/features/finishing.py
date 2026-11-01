"""
    Objects details finishing translators for Fusion 360 -> Build123D export.

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

class Finishing:
    def _thickness_value(self, parameter) -> Tuple[float, str, str, bool]:
            model_parameter = adsk.fusion.ModelParameter.cast(parameter)
            if model_parameter is None:
                return 0.0, Utils._fmt(0.0), "", False
            expr, comment, is_var = self._param_expr(model_parameter, "length")
            return Utils._param_value_mm(model_parameter), expr, comment, is_var

    def _shell_offset_amount(self, shell_feature: adsk.fusion.ShellFeature) -> Tuple[float, str, str]:
            inside, inside_expr, inside_comment, inside_is_var = self._thickness_value(shell_feature.insideThickness)
            outside, outside_expr, outside_comment, outside_is_var = self._thickness_value(shell_feature.outsideThickness)
            inside_is_set = abs(inside) > 1e-9
            outside_is_set = abs(outside) > 1e-9

            def negate(value: float, expr: str, is_var: bool) -> str:
                return f"-{expr}" if is_var else Utils._fmt(-value)

            if inside_is_set and outside_is_set:
                self.unsupported.append(
                    f"Shell '{shell_feature.name}' has both inside and outside thickness; Build123D offset was emitted as internal shell only."
                )
                return -inside, negate(inside, inside_expr, inside_is_var), f"{inside_comment}  # Fusion also had outside thickness {Utils._fmt(outside)}"
            if inside_is_set:
                return -inside, negate(inside, inside_expr, inside_is_var), inside_comment
            if outside_is_set:
                return outside, outside_expr, outside_comment
            return 0.0, Utils._fmt(0.0), ""

    def _best_diffuse_color_property(self, appearance):
            """Find the appearance property that best represents its flat diffuse/base color.

            Iterates every ColorProperty on the appearance, skips ones driven by a
            connected texture (no single flat color to read), then prefers a match
            against Utils._DIFFUSE_COLOR_PROPERTY_IDS, then a property literally named
            "Color", then whatever untextured color property was found first.
            """
            try:
                props = Utils._iter_fusion_collection(appearance.appearanceProperties)
            except Exception:
                return None

            color_props = []
            for prop in props:
                color_prop = Utils._safe_cast(adsk.core.ColorProperty.cast, prop)
                if color_prop is None:
                    continue
                if Utils._safe_getattr(color_prop, "hasConnectedTexture", False):
                    continue
                color_props.append(color_prop)

            if not color_props:
                return None

            by_id = {Utils._safe_getattr(prop, "id", ""): prop for prop in color_props}
            for candidate_id in Utils._DIFFUSE_COLOR_PROPERTY_IDS:
                if candidate_id in by_id:
                    return by_id[candidate_id]

            for prop in color_props:
                if Utils._safe_getattr(prop, "name", "") == "Color":
                    return prop

            return color_props[0]

    def _export_part_color(
            self, body_groups: List[List[Tuple[int, object]]], body_vars: List[str]
        ):
            """Best-effort export of each body's display color from its Fusion appearance.

            Fusion appearances are rendering assets, not plain colors -- many (wood
            grain, brushed metal, procedural patterns, etc.) have no single RGB
            value to translate, and the ones that do store it under different
            property IDs depending on the appearance's shader template (see
            Utils._DIFFUSE_COLOR_PROPERTY_IDS). Opacity has no consistently-named
            property across appearance types either, so it's read on a
            best-effort basis and defaults to fully opaque.

            Runs once per body group (see _partition_entities_by_body), so a
            multi-body design gets its own `<body_var>.part.color = ...` line per
            BuildPart instead of only ever reading the first body in the design,
            as this did before bodies were split into their own groups.
            """
            for group, body_var in zip(body_groups, body_vars):
                body = self._first_body_for_group(group)
                if body is None:
                    continue

                appearance = Utils._safe_getattr(body, "appearance") or Utils._safe_getattr(self.design.rootComponent, "appearance")
                if appearance is None:
                    continue

                color_prop = self._best_diffuse_color_property(appearance)
                if color_prop is None or color_prop.value is None:
                    self.writer.line(
                        f"# TODO: Fusion appearance '{appearance.name}' has no plain RGB color property to translate."
                    )
                    self.unsupported.append(f"Appearance '{appearance.name}' could not be translated to a Build123D Color.")
                    continue

                color = color_prop.value

                property_label = Utils._safe_getattr(color_prop, "id", "") or Utils._safe_getattr(color_prop, "name", "Color")
                self.writer.line(f"# Fusion appearance for '{body_var}': {appearance.name} (property '{property_label}')")
                self.writer.line(
                    f"{body_var}.part.color = "
                    f"Color({Utils._fmt(color.red / 255.0)}, {Utils._fmt(color.green / 255.0)}, {Utils._fmt(color.blue / 255.0)})"
                )

    def _export_fillet(self, fillet_feature: adsk.fusion.FilletFeature):
            timeline = self.design.timeline
            oldPos = timeline.markerPosition

            fillet_feature.timelineObject.rollTo(True)

            try:
                for edge_set in fillet_feature.edgeSets:
                    if edge_set.objectType == adsk.fusion.ConstantRadiusFilletEdgeSet.classType():
                        radius = adsk.fusion.ModelParameter.cast(edge_set.radius)
                        comment, selector = self._edge_selector_expr(edge_set.edges)

                        if comment is not None:
                            self.writer.line(comment)

                        radius_expr, radius_comment, _ = self._param_expr(radius, "length")
                        self.writer.line(f"fillet({selector}, radius={radius_expr}){radius_comment}")
                    else:
                        self.writer.line("# TODO: variable/chord-length fillet requires manual Build123D selector and operation mapping.")
                        self.unsupported.append(f"Fillet '{fillet_feature.name}' contains non-constant edge set.")
            except Exception as e:
                raise Exception(f"Failed to export fillet: {e}")
            finally:
                timeline.markerPosition = oldPos

    def _export_chamfer(self, chamfer_feature: adsk.fusion.ChamferFeature):
            timeline = self.design.timeline
            oldPos = timeline.markerPosition

            chamfer_feature.timelineObject.rollTo(True)

            try:
                edge_sets = getattr(chamfer_feature, "edgeSets", None) or getattr(chamfer_feature, "chamferEdgeSets", None)
                if not edge_sets:
                    self.writer.line("# TODO: chamfer edge sets are unavailable through this Fusion API object.")
                    self.unsupported.append(f"Chamfer '{chamfer_feature.name}' has unavailable edge sets.")
                    return

                for edge_set in edge_sets:
                    distance = None
                    for attr in ("distance", "distanceOne"):
                        if hasattr(edge_set, attr):
                            distance = adsk.fusion.ModelParameter.cast(getattr(edge_set, attr))
                            if distance:
                                break
                    if distance:
                        comment, selector = self._edge_selector_expr(edge_set.edges)

                        if comment is not None:
                            self.writer.line(comment)

                        distance_expr, distance_comment, _ = self._param_expr(distance, "length")
                        self.writer.line(f"_fusion_chamfer({selector}, length={distance_expr}){distance_comment}")
                    else:
                        self.writer.line("# TODO: two-distance/equal-distance chamfer needs manual mapping.")
                        self.unsupported.append(f"Chamfer '{chamfer_feature.name}' has unsupported distance definition.")
            except Exception as e:
                raise Exception(f"Failed to export chamfer: {e}")
            finally:
                timeline.markerPosition = oldPos

    def _export_shell(self, shell_feature: adsk.fusion.ShellFeature):
            timeline = self.design.timeline
            oldPos = timeline.markerPosition

            shell_feature.timelineObject.rollTo(True)

            try:
                amount, amount_expr, comment = self._shell_offset_amount(shell_feature)
                input_entities = shell_feature.inputEntities
                selector_comment, openings = self._face_selector_expr(input_entities)

                self.writer.line(selector_comment)
                if abs(amount) <= 1e-9:
                    self.writer.line("# TODO: shell has zero or unavailable thickness.")
                    self.unsupported.append(f"Shell '{shell_feature.name}' has zero or unavailable thickness.")
                    return

                if getattr(shell_feature, "isTangentChain", False):
                    self.writer.line("# Fusion shell used tangent-chain face selection.")

                if openings == "None":
                    self.writer.line(f"offset(amount={amount_expr}){comment}")
                else:
                    self.writer.line(f"offset(amount={amount_expr}, openings={openings}){comment}")
            except Exception as e:
                raise Exception(f"Failed to export shell: {e}")
            finally:
                timeline.markerPosition = oldPos

    def _radius_expr(self, diameter_parameter) -> Tuple[str, str]:
            """Resolve a Fusion *diameter* ModelParameter (holeDiameter,
            counterboreDiameter, countersinkDiameter) into a Build123D
            *radius* expression -- Fusion dimensions holes by diameter,
            Build123D's Hole/CounterBoreHole/CounterSinkHole take a radius.
            A live parameter stays live (halved as source text, e.g.
            "(Clearance_M6) / 2") rather than being baked into today's
            numeric radius.
            """
            if diameter_parameter is None:
                return Utils._fmt(0.0), ""
            parameter = adsk.fusion.ModelParameter.cast(diameter_parameter) or diameter_parameter
            diameter_expr, comment, is_var = self._param_expr(parameter, "length")
            if is_var:
                return f"({diameter_expr}) / 2", comment
            return Utils._fmt(Utils._param_value_mm(parameter) / 2.0), comment
