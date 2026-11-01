"""
    Basic primitive features translators for Fusion 360 -> Build123D export.

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

class Primitives:
    def _export_box_primitive(self, feature):
            """Box: derive dimensions/orientation from one rectangular face plus
            its opposite parallel face, mirroring the reference exporter.
            """
            timeline = self.design.timeline
            oldPos = timeline.markerPosition
            feature.timelineObject.rollTo(True)

            try:
                feature.timelineObject.rollTo(False)
                body = self._primitive_first_body(feature)
                created_faces = Utils._iter_fusion_collection(Utils._safe_getattr(feature, "faces", None))
                all_faces = [body.faces.item(i) for i in range(body.faces.count)] if body is not None else []

                def _planar(face):
                    return Utils._safe_cast(adsk.core.Plane.cast, Utils._safe_getattr(face, "geometry", None))

                face0 = plane0 = None
                for face in (created_faces or all_faces):
                    plane = _planar(face)
                    if plane is not None and face.edges.count == 4:
                        face0, plane0 = face, plane
                        break

                if face0 is None:
                    feature.timelineObject.rollTo(True)
                    self.writer.line("# TODO: could not find a clean rectangular face on this box primitive.")
                    self.unsupported.append(f"Box '{feature.name}' geometry did not match a simple box.")
                    return

                face_edges = Utils._iter_fusion_collection(Utils._safe_getattr(face0, "edges", None))
                corner_vertex = face_edges[0].startVertex
                corner_point = corner_vertex.geometry

                def _far_point(edge) -> Optional[adsk.core.Point3D]:
                    for vertex in (edge.startVertex, edge.endVertex):
                        p = vertex.geometry
                        if p.distanceTo(corner_point) > 1e-9:
                            return p
                    return None

                incident = [
                    edge
                    for edge in face_edges
                    if any(
                        vertex.geometry.distanceTo(corner_point) <= 1e-9
                        for vertex in (edge.startVertex, edge.endVertex)
                    )
                ]

                in_plane_vectors = []
                for edge in incident:
                    far = _far_point(edge)
                    if far is not None:
                        in_plane_vectors.append(
                            adsk.core.Vector3D.create(
                                far.x - corner_point.x,
                                far.y - corner_point.y,
                                far.z - corner_point.z,
                            )
                        )

                normal = plane0.normal
                normal_unit = Utils._unit_vector_from_tuple(Utils._vector_tuple(normal))

                offset_point = None
                for face in all_faces:
                    if face is face0:
                        continue
                    plane = _planar(face)
                    if plane is None or normal_unit is None:
                        continue
                    candidate_normal = Utils._unit_vector_from_tuple(Utils._vector_tuple(plane.normal))
                    if candidate_normal is None:
                        continue
                    if abs(candidate_normal.dotProduct(normal_unit)) < 0.999:
                        continue
                    signed_dist = (
                        (plane.origin.x - corner_point.x) * normal_unit.x
                        + (plane.origin.y - corner_point.y) * normal_unit.y
                        + (plane.origin.z - corner_point.z) * normal_unit.z
                    )
                    if abs(signed_dist) > 1e-6 and (
                        offset_point is None or abs(signed_dist) > abs(offset_point)
                    ):
                        offset_point = signed_dist

                operation = Utils._safe_getattr(feature, "operation", None)
                feature.timelineObject.rollTo(True)

                if len(in_plane_vectors) != 2 or normal_unit is None or offset_point is None:
                    self.writer.line("# TODO: box primitive geometry did not resolve to 3 clean dimensions.")
                    self.unsupported.append(f"Box '{feature.name}' geometry did not match a simple box.")
                    return

                in_plane_vectors.sort(key=lambda v: v.length)
                lx_mm = in_plane_vectors[0].length * Utils.MM_PER_FUSION_UNIT
                ly_mm = in_plane_vectors[1].length * Utils.MM_PER_FUSION_UNIT
                lz_mm = abs(offset_point) * Utils.MM_PER_FUSION_UNIT

                x_dir = in_plane_vectors[0].copy()
                x_dir.normalize()
                z_dir = adsk.core.Vector3D.create(normal_unit.x, normal_unit.y, normal_unit.z)
                if offset_point < 0:
                    z_dir = adsk.core.Vector3D.create(-z_dir.x, -z_dir.y, -z_dir.z)

                y_check = z_dir.crossProduct(x_dir)
                if y_check.dotProduct(in_plane_vectors[1]) < 0:
                    x_dir = adsk.core.Vector3D.create(-x_dir.x, -x_dir.y, -x_dir.z)

                origin_mm = (
                    corner_point.x * Utils.MM_PER_FUSION_UNIT,
                    corner_point.y * Utils.MM_PER_FUSION_UNIT,
                    corner_point.z * Utils.MM_PER_FUSION_UNIT,
                )
                plane_expr, plane_comment = self._frame_to_plane_expr(origin_mm, x_dir, z_dir)
                mode = self._mode_expr(operation)

                self.writer.line(f"with Locations({plane_expr}):{plane_comment}")
                self.writer.level += 1
                self.writer.line(
                    f"Box({Utils._fmt(lx_mm)}, {Utils._fmt(ly_mm)}, {Utils._fmt(lz_mm)}, "
                    f"align=(Align.MIN, Align.MIN, Align.MIN), mode={mode})"
                )
                self.writer.level -= 1
            except Exception as e:
                raise Exception(f"Failed to export box primitive: {e}")
            finally:
                timeline.markerPosition = oldPos

    def _export_cylinder_primitive(self, feature):
            """Cylinder: radius from the lateral cylindrical face; height and
            base position from the two circular cap edges.
            """
            timeline = self.design.timeline
            oldPos = timeline.markerPosition
            feature.timelineObject.rollTo(True)

            try:
                feature.timelineObject.rollTo(False)
                body = self._primitive_first_body(feature)
                cyl_face, cylinder = None, None
                if body is not None:
                    for i in range(body.faces.count):
                        face = body.faces.item(i)
                        candidate = Utils._safe_cast(adsk.core.Cylinder.cast, Utils._safe_getattr(face, "geometry", None))
                        if candidate is not None:
                            cyl_face, cylinder = face, candidate
                            break

                centers: List[adsk.core.Point3D] = []
                if cyl_face is not None:
                    for i in range(cyl_face.edges.count):
                        geom = Utils._safe_cast(
                            adsk.core.Circle3D.cast,
                            Utils._safe_getattr(cyl_face.edges.item(i), "geometry", None),
                        )
                        if geom is not None:
                            centers.append(geom.center)

                axis_tuple = Utils._vector_tuple(cylinder.axis) if cylinder is not None else None
                radius = cylinder.radius if cylinder is not None else None
                operation = Utils._safe_getattr(feature, "operation", None)
                feature.timelineObject.rollTo(True)

                if cylinder is None or radius is None or len(centers) < 2:
                    self.writer.line("# TODO: cylinder primitive geometry could not be read back.")
                    self.unsupported.append(f"Cylinder '{feature.name}' geometry did not match a simple cylinder.")
                    return

                axis = Utils._unit_vector_from_tuple(axis_tuple)
                base, top = centers[0], centers[1]
                along = adsk.core.Vector3D.create(top.x - base.x, top.y - base.y, top.z - base.z)
                if axis is not None and along.dotProduct(axis) < 0:
                    base, top = top, base

                z_dir = Utils._unit_vector_from_tuple((top.x - base.x, top.y - base.y, top.z - base.z))
                if z_dir is None:
                    self.writer.line("# TODO: cylinder primitive has coincident cap edges; direction unavailable.")
                    self.unsupported.append(f"Cylinder '{feature.name}' has a degenerate axis.")
                    return
                x_dir = Utils._fallback_plane_x_dir(z_dir)
                if x_dir is None:
                    self.writer.line("# TODO: could not derive a workplane orientation for this cylinder.")
                    self.unsupported.append(f"Cylinder '{feature.name}' axis is parallel to the fallback reference axis.")
                    return

                height_mm = base.distanceTo(top) * Utils.MM_PER_FUSION_UNIT
                radius_mm = radius * Utils.MM_PER_FUSION_UNIT
                origin_mm = (
                    base.x * Utils.MM_PER_FUSION_UNIT,
                    base.y * Utils.MM_PER_FUSION_UNIT,
                    base.z * Utils.MM_PER_FUSION_UNIT,
                )
                plane_expr, plane_comment = self._frame_to_plane_expr(origin_mm, x_dir, z_dir)
                mode = self._mode_expr(operation)

                self.writer.line(f"with Locations({plane_expr}):{plane_comment}")
                self.writer.level += 1
                self.writer.line(
                    f"Cylinder(radius={Utils._fmt(radius_mm)}, height={Utils._fmt(height_mm)}, "
                    f"align=(Align.CENTER, Align.CENTER, Align.MIN), mode={mode})"
                )
                self.writer.level -= 1
            except Exception as e:
                raise Exception(f"Failed to export cylinder primitive: {e}")
            finally:
                timeline.markerPosition = oldPos

    def _export_sphere_primitive(self, feature):
            timeline = self.design.timeline
            oldPos = timeline.markerPosition
            feature.timelineObject.rollTo(True)

            try:
                feature.timelineObject.rollTo(False)
                body = self._primitive_first_body(feature)
                sphere_geom = None
                if body is not None:
                    for i in range(body.faces.count):
                        candidate = Utils._safe_cast(
                            adsk.core.Sphere.cast,
                            Utils._safe_getattr(body.faces.item(i), "geometry", None),
                        )
                        if candidate is not None:
                            sphere_geom = candidate
                            break

                center = None
                radius = None
                if sphere_geom is not None:
                    center = Utils._safe_getattr(sphere_geom, "origin", None) or Utils._safe_getattr(sphere_geom, "center", None)
                    radius = Utils._safe_getattr(sphere_geom, "radius", None)

                operation = Utils._safe_getattr(feature, "operation", None)
                feature.timelineObject.rollTo(True)

                if center is None or radius is None:
                    self.writer.line("# TODO: sphere primitive geometry could not be read back.")
                    self.unsupported.append(f"Sphere '{feature.name}' geometry did not match a simple sphere.")
                    return

                radius_mm = radius * Utils.MM_PER_FUSION_UNIT
                origin_mm = (
                    center.x * Utils.MM_PER_FUSION_UNIT,
                    center.y * Utils.MM_PER_FUSION_UNIT,
                    center.z * Utils.MM_PER_FUSION_UNIT,
                )
                plane_expr, plane_comment = self._frame_to_plane_expr(
                    origin_mm,
                    adsk.core.Vector3D.create(1, 0, 0),
                    adsk.core.Vector3D.create(0, 0, 1),
                )
                mode = self._mode_expr(operation)

                self.writer.line(f"with Locations({plane_expr}):{plane_comment}")
                self.writer.level += 1
                self.writer.line(f"Sphere(radius={Utils._fmt(radius_mm)}, mode={mode})")
                self.writer.level -= 1
            except Exception as e:
                raise Exception(f"Failed to export sphere primitive: {e}")
            finally:
                timeline.markerPosition = oldPos

    def _export_torus_primitive(self, feature):
            timeline = self.design.timeline
            oldPos = timeline.markerPosition
            feature.timelineObject.rollTo(True)

            try:
                feature.timelineObject.rollTo(False)
                body = self._primitive_first_body(feature)
                torus_geom = None
                if body is not None:
                    for i in range(body.faces.count):
                        candidate = Utils._safe_cast(
                            adsk.core.Torus.cast,
                            Utils._safe_getattr(body.faces.item(i), "geometry", None),
                        )
                        if candidate is not None:
                            torus_geom = candidate
                            break

                center = axis_tuple = major_radius = minor_radius = None
                if torus_geom is not None:
                    center = Utils._safe_getattr(torus_geom, "origin", None) or Utils._safe_getattr(torus_geom, "center", None)
                    axis = Utils._safe_getattr(torus_geom, "axis", None) or Utils._safe_getattr(torus_geom, "normal", None)
                    axis_tuple = Utils._vector_tuple(axis) if axis is not None else None
                    major_radius = Utils._safe_getattr(torus_geom, "majorRadius", None)
                    minor_radius = Utils._safe_getattr(torus_geom, "minorRadius", None)

                operation = Utils._safe_getattr(feature, "operation", None)
                feature.timelineObject.rollTo(True)

                if center is None or axis_tuple is None or major_radius is None or minor_radius is None:
                    self.writer.line("# TODO: torus primitive geometry could not be read back.")
                    self.unsupported.append(f"Torus '{feature.name}' geometry did not match a simple torus.")
                    return

                z_dir = Utils._unit_vector_from_tuple(axis_tuple)
                if z_dir is None:
                    self.writer.line("# TODO: torus primitive has a degenerate axis.")
                    self.unsupported.append(f"Torus '{feature.name}' has a degenerate axis.")
                    return
                x_dir = Utils._fallback_plane_x_dir(z_dir)
                if x_dir is None:
                    self.writer.line("# TODO: could not derive a workplane orientation for this torus.")
                    self.unsupported.append(f"Torus '{feature.name}' axis is parallel to the fallback reference axis.")
                    return

                origin_mm = (
                    center.x * Utils.MM_PER_FUSION_UNIT,
                    center.y * Utils.MM_PER_FUSION_UNIT,
                    center.z * Utils.MM_PER_FUSION_UNIT,
                )
                plane_expr, plane_comment = self._frame_to_plane_expr(origin_mm, x_dir, z_dir)
                mode = self._mode_expr(operation)

                self.writer.line(f"with Locations({plane_expr}):{plane_comment}")
                self.writer.level += 1
                self.writer.line(
                    f"Torus(major_radius={Utils._fmt(major_radius * Utils.MM_PER_FUSION_UNIT)}, "
                    f"minor_radius={Utils._fmt(minor_radius * Utils.MM_PER_FUSION_UNIT)}, mode={mode})"
                )
                self.writer.level -= 1
            except Exception as e:
                raise Exception(f"Failed to export torus primitive: {e}")
            finally:
                timeline.markerPosition = oldPos
