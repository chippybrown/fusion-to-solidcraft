"""
    Main Build123D exporter facade.

    Written by Ran Peleg, Visionware Solutions Pty Ltd
    ran@visionware.com.au
    Provided as-is, without warranty of any kind under Apache-2.0 license
"""

from __future__ import annotations

import os
import adsk.core
import adsk.fusion

import Utils

from core import ExporterCore
from parameters import Parameters
from features.primitives import Primitives
from geometry import Geometry
from sketches import Sketches
from features.additive import AdditiveFeatures
from features.transforms import Transforms
from selection_utils import Selectors
from features.finishing import Finishing
from features.holes import Holes


class ParametricBuild123DExporter(
    ExporterCore,
    Parameters,
    Primitives,
    Geometry,
    Sketches,
    AdditiveFeatures,
    Transforms,
    Selectors,
    Finishing,
    Holes
):
    """Export a Fusion design to a Build123D Python script."""

    LENGTH_UNITS = {"mm", "cm", "m", "in", "ft", "ft-and-in", "mil", ""}
    ANGLE_UNITS = {"deg", "rad"}    

    def __init__(self, design: adsk.fusion.Design, script_path: str):
            self.design = design
            self.script_path = script_path
            self.writer = Utils.CodeWriter()
            self.model_var = "fusion_model"
            # Variable name of whichever BuildPart block is currently open (see
            # export() / _partition_entities_by_body). For a single-body design
            # this stays equal to self.model_var throughout, same as before this
            # multi-body split existed. Features that approximate themselves as
            # "operate on the current BuildPart state" (_export_move,
            # _export_scale, _pattern_source_name) read this instead of
            # self.model_var so they stay scoped to their own body's block.
            self.current_body_var = self.model_var
            self.sketch_index = 0
            self.loop_index = 0
            self.pattern_index = 0
            self.last_extrude_replay: Optional[str] = None
            self.last_extrude_sketch_name: Optional[str] = None
            # Which kind of feature last_extrude_replay / last_hole_* refer to --
            # "extrude" or "hole" -- so pattern export (see _replay_last_feature_*)
            # knows which replay mechanism to use. HoleFeature isn't built from a
            # profile sketch the way extrude/revolve/sweep are, so it needs its
            # own replay state (a Locations() plane + the Hole/CounterBoreHole/
            # CounterSinkHole call) distinct from last_extrude_replay.
            self.last_feature_kind: Optional[str] = None
            self.last_hole_plane_expr: Optional[str] = None
            self.last_hole_call_lines: List[str] = []
            self.unsupported: List[str] = []

            self.parameter_vars: dict = {}
            self.parameter_kinds: dict = {}
            self.parameter_values: dict = {}
            self._revolve_selector_reflections: List[dict] = []
            self._body_var_by_token: dict = {}

            self._parametric_planes: List[dict] = []

            # Cache of sketch.sketchDimensions per sketch (keyed by id(sketch)),
            # used by _entity_dimension_var / _line_length_dimension_var below to
            # avoid re-walking the dimensions collection for every circle/edge in
            # the same sketch.
            self._sketch_dimension_cache: dict = {}
            self._uses_chamfer = False

            # Sketch-only export (see Sketches._write_sketch_only_section):
            # sketch curves/text/points used by exported features, and the
            # resulting count/names for callers such as ExportToPythonBatch.
            self._sketch_only_consumed = {"tokens": set(), "groups": []}
            self.sketch_only_count = 0
            self.sketch_only_names: List[str] = []


def export_active_design(script_path: str) -> Tuple[str, List[str]]:
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        raise RuntimeError("No active Fusion 360 design")

    script_path = os.path.abspath(script_path)
    exporter = ParametricBuild123DExporter(design, script_path)
    exporter.export()
    return script_path, exporter.unsupported
