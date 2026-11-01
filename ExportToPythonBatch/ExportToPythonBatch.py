"""
    Batch wrapper for ExportToPython (LITTLEFOOT).
    Asks for a folder path inside the active project (default: the project root, e.g. My Projects),
    opens each Fusion design in it, exports it with ExportToPython's exporter to
    Documents/Fusion exports/<project>/<folder>/<Design>.py, and closes it without saving.
    Skips designs whose .py already exists, unless you answer Yes to "Re-export designs that already
    have a Python file?" -- then existing .py (and STEP-fallback .step) files are overwritten, so the
    sketch-only export (SKETCH_ONLY) is included. Bathroom Mirrors.py / .step are never overwritten.
    A new export is written to a temporary file first and only replaces the old one when it succeeds.
    Writes _batch_export_log.txt in the output folder; each OK line shows sketches=N (the number of
    sketch-only sketches exported) and the log ends with a summary of designs that have them.
    While each opened design is still open and active (after the export attempt, whether it worked, fell back
    to STEP, or failed), six plain viewport pictures are saved next to the .py as <Design>_<view>.png
    (views iso, top, front, back, left, right; 1600x1200; fit view; visibility unchanged; no rendering), and the
    original camera is restored. Designs skipped without being opened get no pictures. With "No" to the
    overwrite question an existing .png is kept. A picture failure never fails the export; each design gets a
    "PNG ok" / "PNG failed: ..." log line and the SUMMARY counts them. Bathroom Mirrors is never pictured.
    Also while the design is open, the full format set next to the .py: <Design>.step (always, also for
    parametric designs), <Design>.obj, <Design>.3mf (opens in Windows 3D Viewer), <Design>.stl (one combined
    binary STL of the root component, high refinement) and <Design>.f3d (Fusion archive, full-fidelity backup).
    Each format has its own try/except, a "FORMAT ok/failed/skipped" log line and a SUMMARY count; a format
    failure never fails the export; with "No" to the overwrite question an existing file is kept.
    Scope prompt: 1 = the design you have open (default; it is used as it is, never re-opened or closed),
    2 = every design in that design's folder (asks about subfolders), 3 = all of the project (My Projects).
    With no saved design open only 3 is offered.
    Every output keeps the design's full folder path from the project root
    (Fusion exports/<project>/<folder>/<subfolder>/...), whatever folder the run starts from.
    Does not change ExportToPython itself.
"""
import os, sys, traceback
import adsk.core, adsk.fusion

_here = os.path.dirname(os.path.abspath(__file__))
_etp = os.path.join(os.path.dirname(_here), "ExportToPython")
if _etp not in sys.path:
    sys.path.append(_etp)

import ExportToPython as etp
from exporter import ParametricBuild123DExporter


def _find_folder(root, path):
    folder = root
    for part in [p for p in path.replace("\\", "/").split("/") if p.strip()]:
        nxt = None
        for i in range(folder.dataFolders.count):
            f = folder.dataFolders.item(i)
            if f.name.strip().lower() == part.strip().lower():
                nxt = f
                break
        if nxt is None:
            return None
        folder = nxt
    return folder


PNG_VIEWS = (("iso", "IsoTopRightViewOrientation"), ("top", "TopViewOrientation"),
             ("front", "FrontViewOrientation"), ("back", "BackViewOrientation"),
             ("left", "LeftViewOrientation"), ("right", "RightViewOrientation"))


def _save_view_pictures(app, doc, base, overwrite):
    """Six fitted viewport pictures <base>_<view>.png of the active design; returns (saved, skipped, errors).
    Never raises.  The camera is restored afterwards."""
    saved, skipped, errors = [], [], []
    vp, orig = None, None
    try:
        if app.activeDocument != doc:
            doc.activate()
            adsk.doEvents()
        vp = app.activeViewport
        orig = vp.camera
        os.makedirs(os.path.dirname(base), exist_ok=True)
    except Exception as e:
        return saved, skipped, [f"setup: {e}"]
    for view, orient in PNG_VIEWS:
        png = f"{base}_{view}.png"
        tmp = f"{base}_{view}.tmp.png"
        try:
            if os.path.exists(png) and not overwrite:
                skipped.append(png)
                continue
            if os.path.exists(tmp):
                os.remove(tmp)
            cam = vp.camera
            cam.viewOrientation = getattr(adsk.core.ViewOrientations, orient)
            cam.isFitView = True
            vp.camera = cam
            adsk.doEvents()
            vp.fit()
            adsk.doEvents()
            if not vp.saveAsImageFile(tmp, 1600, 1200) or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
                raise RuntimeError("saveAsImageFile returned no image")
            os.replace(tmp, png)
            saved.append(png)
        except Exception as e:
            errors.append(f"{view}: {e}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
    try:
        if orig is not None:
            orig.isFitView = False
            vp.camera = orig
            adsk.doEvents()
    except Exception:
        pass
    return saved, skipped, errors


EXPORT_FORMATS = ("step", "obj", "3mf", "stl", "f3d")


def _export_formats(doc, base, overwrite, skip=()):
    """Write <base>.<ext> for every format in EXPORT_FORMATS (except `skip`).
    Returns [(ext, status 'ok'|'skipped'|'failed', path, error)].  Never raises."""
    results = []
    try:
        design = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
        if design is None:
            raise RuntimeError("no design data")
        em = design.exportManager
        root = design.rootComponent
        os.makedirs(os.path.dirname(base), exist_ok=True)
    except Exception as e:
        return [(ext, "failed", None, f"setup: {e}") for ext in EXPORT_FORMATS if ext not in skip]
    high = getattr(getattr(adsk.fusion, "MeshRefinementSettings", None), "MeshRefinementHigh", None)
    for ext in EXPORT_FORMATS:
        if ext in skip:
            continue
        out, tmp = f"{base}.{ext}", f"{base}.tmp.{ext}"
        try:
            if os.path.exists(out) and not overwrite:
                results.append((ext, "skipped", out, None)); continue
            if os.path.exists(tmp):
                os.remove(tmp)
            if ext == "step":
                opts = em.createSTEPExportOptions(tmp, root)
            elif ext == "obj":
                opts = em.createOBJExportOptions(root, tmp)
            elif ext == "3mf":
                opts = em.createC3MFExportOptions(root, tmp)
            elif ext == "stl":
                opts = em.createSTLExportOptions(root, tmp)
                try:
                    opts.isBinaryFormat = True
                    opts.isOneFilePerBody = False
                except Exception:
                    pass
            else:
                opts = em.createFusionArchiveExportOptions(tmp, root)
            if high is not None and ext in ("obj", "3mf", "stl"):
                try:
                    opts.meshRefinement = high
                except Exception:
                    pass
            if not em.execute(opts) or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
                raise RuntimeError("export returned no file")
            os.replace(tmp, out)
            results.append((ext, "ok", out, None))
        except Exception as e:
            results.append((ext, "failed", out, str(e)))
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
    return results


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        project = app.data.activeProject
        if project is None:
            ui.messageBox("Open a project in the Data Panel first.")
            return
        # The open design (if it is a saved design) decides scopes 1 and 2.
        active_df = None
        try:
            _ad = app.activeDocument
            _df = _ad.dataFile if _ad is not None else None
            if _df is not None and (_df.fileExtension or "").lower() == "f3d" \
                    and adsk.fusion.Design.cast(_ad.products.itemByProductType("DesignProductType")) is not None:
                active_df = _df
        except Exception:
            active_df = None
        if active_df is not None:
            try:
                project = active_df.parentProject or project
            except Exception:
                pass
            ret = ui.inputBox("Export scope:\n"
                              f"1 = the design you have open ({active_df.name})\n"
                              "2 = every design in that design's folder\n"
                              f"3 = all of {project.name}", "Batch export to Python", "1")
            if isinstance(ret, (list, tuple)):
                scope, cancelled = ret[0], ret[1]
            else:
                scope, cancelled = ret, False
            if cancelled:
                return
            scope = (scope or "1").strip() or "1"
            if scope not in ("1", "2", "3"):
                ui.messageBox(f"Please enter 1, 2 or 3 (you entered '{scope}').")
                return
        else:
            if ui.messageBox("No saved Fusion design is open (or it has not been saved yet), so only scope 3 is available:\n\n"
                             f"3 = export all of {project.name}\n\n"
                             "To export one design or one folder, open a saved design first and run this again.\n\n"
                             f"Export all of {project.name} now?", "Batch export to Python",
                             adsk.core.MessageBoxButtonTypes.YesNoButtonType) != adsk.core.DialogResults.DialogYes:
                return
            scope = "3"

        def _folder_chain(fo):
            names = []
            while fo is not None and not fo.isRoot:
                names.insert(0, fo.name)
                fo = fo.parentFolder
            return names

        if scope == "1":
            folder = active_df.parentFolder
            recurse = False
        elif scope == "2":
            folder = active_df.parentFolder
        else:
            folder = project.rootFolder
            recurse = True
        path = "/".join(_folder_chain(folder))

        open_ids = {}
        for i in range(app.documents.count):
            d = app.documents.item(i)
            try:
                if d.dataFile:
                    open_ids[d.dataFile.id] = d
            except Exception:
                pass

        if scope == "2":
            recurse = ui.messageBox("Also export designs in all subfolders?\n\nClick Yes (recommended) to export every design in every subfolder.\nClick No for only the designs directly in this folder.", "Batch export to Python",
                                    adsk.core.MessageBoxButtonTypes.YesNoButtonType) == adsk.core.DialogResults.DialogYes

        overwrite = ui.messageBox("Re-export designs that already have a Python file?\n\n"
                                  "Yes = overwrite them so new sketch export is included.\n"
                                  "No = skip designs whose .py (or .step) already exists.\n\n"
                                  "(Bathroom Mirrors is never overwritten.)", "Batch export to Python",
                                  adsk.core.MessageBoxButtonTypes.YesNoButtonType) == adsk.core.DialogResults.DialogYes

        def _collect(fo):
            out = [fo.dataFiles.item(i) for i in range(fo.dataFiles.count)]
            if recurse:
                for i in range(fo.dataFolders.count):
                    out += _collect(fo.dataFolders.item(i))
            return out

        if scope == "1":
            files = [active_df]
        else:
            files = _collect(folder)
        files = [f for f in files if (f.fileExtension or "").lower() == "f3d"]
        used, log, made, skipped, failed = set(), [], [], [], []
        with_sketches, overwritten = [], []
        png_ok, png_failed, png_skipped, png_designs_failed = [], [], [], []
        fmt_counts = {ext: {"ok": 0, "skipped": 0, "failed": 0} for ext in EXPORT_FORMATS}
        log.append(f"Batch export {'(overwrite existing: yes)' if overwrite else '(overwrite existing: no)'}"
                   + {"1": f"  (scope 1: {active_df.name if active_df else ''})", "2": f"  (scope 2: folder {path or '(root)'}"
                      + (", with subfolders)" if recurse else ")"), "3": f"  (scope 3: all of {project.name})"}[scope])

        progress = ui.createProgressDialog()
        progress.isCancelButtonShown = True
        progress.show("Batch export to Python", "%v of %m", 0, max(len(files), 1), 0)

        for n, df in enumerate(files):
            if progress.wasCancelled:
                log.append("Cancelled by user.")
                break
            progress.progressValue = n
            progress.message = f"{df.name} (%v of %m)"
            adsk.doEvents()
            doc, opened_here, out, design, step_out = None, False, None, None, None
            step_done = False
            try:
                design_name = etp._design_name(df.name)
                project_name, folders = project.name, []
                f = df.parentFolder
                while f and not f.isRoot:
                    folders.insert(0, f.name)
                    f = f.parentFolder
                out = etp._output_path(design_name, project_name, folders)
                base, k = out[:-3], 2
                while out.lower() in used:
                    out = f"{base} ({k}).py"; k += 1
                used.add(out.lower())
                step_out = out[:-3] + ".step"
                _exists = os.path.exists(out) or os.path.exists(step_out)
                if _exists and os.path.basename(out).lower() == "bathroom mirrors.py":
                    _ex = out if os.path.exists(out) else step_out
                    skipped.append(os.path.basename(_ex)); log.append(f"SKIP (Bathroom Mirrors, never overwritten) {_ex}")
                    continue
                if _exists and not overwrite:
                    _ex = out if os.path.exists(out) else step_out
                    skipped.append(os.path.basename(_ex)); log.append(f"SKIP (exists) {_ex}")
                    continue
                if df.id in open_ids:
                    doc = open_ids[df.id]; doc.activate()
                else:
                    doc = app.documents.open(df, True); opened_here = True
                adsk.doEvents()
                # Use the Design product even if the file was saved in the Manufacture
                # workspace; CAM setups are ignored, only the design timeline is exported.
                design = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
                if design is None:
                    raise RuntimeError("no design data in this file")
                # Export to a temporary file first; it replaces <Design>.py only when the
                # whole export succeeded, so a failed re-export never loses the old file.
                tmp_out = os.path.abspath(out) + ".tmp"
                exp = ParametricBuild123DExporter(design, tmp_out)
                exp.export()
                etp._prepend_location_header(tmp_out, design_name, project_name, folders)
                script_path, unsupported = os.path.abspath(out), exp.unsupported
                was_there = os.path.exists(script_path)
                os.replace(tmp_out, script_path)
                n_sk = int(getattr(exp, "sketch_only_count", 0) or 0)
                made.append(os.path.basename(script_path))
                if was_there:
                    overwritten.append(os.path.basename(script_path))
                if n_sk:
                    with_sketches.append((script_path, n_sk, list(getattr(exp, "sketch_only_names", []) or [])))
                log.append(f"OK {script_path}  sketches={n_sk}" + ("  (overwritten)" if was_there else "")
                           + (f"  ({len(unsupported)} export notes)" if unsupported else ""))
            except Exception as _err:
                # Direct-modeling (no history) designs: export a STEP file instead.
                try:
                    if out and os.path.exists(out + ".tmp"):
                        os.remove(out + ".tmp")
                except Exception:
                    pass
                if "not a parametric design" in str(_err) and design is not None and out:
                    try:
                        os.makedirs(os.path.dirname(step_out), exist_ok=True)
                        step_tmp = step_out[:-5] + ".tmp.step"
                        if os.path.exists(step_tmp):
                            os.remove(step_tmp)
                        em = design.exportManager
                        opts = em.createSTEPExportOptions(step_tmp, design.rootComponent)
                        if em.execute(opts) and os.path.exists(step_tmp):
                            step_was_there = os.path.exists(step_out)
                            os.replace(step_tmp, step_out)
                            step_done = True
                            # A direct-modeling design has no .py; drop a stale one (never Bathroom Mirrors).
                            if os.path.exists(out) and os.path.basename(out).lower() != "bathroom mirrors.py":
                                os.remove(out)
                            made.append(os.path.basename(step_out))
                            if step_was_there:
                                overwritten.append(os.path.basename(step_out))
                            log.append(f"STEP {step_out}  (not a parametric design, exported as STEP)"
                                       + ("  (overwritten)" if step_was_there else ""))
                            continue
                        raise RuntimeError("STEP export returned no file")
                    except Exception:
                        log.append(f"FAIL (STEP fallback) {df.name}\n{traceback.format_exc()}")
                failed.append(df.name)
                # Exports go to <Design>.py.tmp first, so a failed attempt leaves any
                # existing <Design>.py untouched (only the temporary file is removed).
                try:
                    if out and os.path.exists(out + ".tmp"):
                        os.remove(out + ".tmp")
                except Exception:
                    pass
                log.append(f"FAIL {df.name}\n{traceback.format_exc()}")
            finally:
                # Full format set while the design is still open (never Bathroom Mirrors).
                if doc is not None and out and os.path.basename(out).lower() != "bathroom mirrors.py":
                    try:
                        _fr = _export_formats(doc, os.path.abspath(out[:-3]), overwrite, ("step",) if step_done else ())
                    except Exception as _ferr:
                        _fr = [(ext, "failed", None, str(_ferr)) for ext in EXPORT_FORMATS]
                    for _ext, _st, _fp, _fe in _fr:
                        fmt_counts[_ext][_st] += 1
                        if _st == "ok":
                            log.append(f"{_ext.upper()} ok {_fp}")
                        elif _st == "skipped":
                            log.append(f"{_ext.upper()} skipped (exists) {_fp}")
                        else:
                            log.append(f"{_ext.upper()} failed: {_fe}  ({df.name})")
                # Viewport pictures while the design is still open and active (never Bathroom Mirrors).
                if doc is not None and out and os.path.basename(out).lower() != "bathroom mirrors.py":
                    try:
                        _s, _k, _e = _save_view_pictures(app, doc, os.path.abspath(out[:-3]), overwrite)
                        png_ok += _s; png_skipped += _k; png_failed += _e
                        if _e:
                            png_designs_failed.append(df.name)
                            log.append(f"PNG failed: {'; '.join(_e)}  ({len(_s)} saved, {len(_k)} kept)  {out[:-3]}_<view>.png")
                        else:
                            log.append(f"PNG ok ({len(_s)} saved" + (f", {len(_k)} existing kept" if _k else "") + f")  {out[:-3]}_<view>.png")
                    except Exception as _perr:
                        png_designs_failed.append(df.name)
                        log.append(f"PNG failed: {_perr}  ({df.name})")
                if doc is not None and opened_here:
                    try:
                        doc.close(False)
                    except Exception:
                        pass
                adsk.doEvents()

        progress.hide()
        out_dir = os.path.join(etp._documents_folder(), "Fusion exports",
                               etp._safe(project.name, "Unsaved"),
                               *[etp._safe(p, "_") for p in path.replace("\\", "/").split("/") if p.strip()])
        os.makedirs(out_dir, exist_ok=True)
        n_py_made = len([m for m in made if m.lower().endswith(".py")])
        log.append("")
        log.append(f"SUMMARY: {len(made)} exported ({len(overwritten)} overwritten), {len(skipped)} skipped, "
                   f"{len(failed)} failed; {len(with_sketches)} of {n_py_made} exported .py designs have "
                   f"sketch-only sketches ({sum(n for _, n, _ in with_sketches)} sketches in total); "
                   f"PNG: {len(png_ok)} saved, {len(png_skipped)} kept (exist), {len(png_failed)} failed "
                   f"({len(png_designs_failed)} designs with picture failures); "
                   + "; ".join(f"{e.upper()}: {c['ok']} saved, {c['skipped']} kept, {c['failed']} failed" for e, c in fmt_counts.items()))
        for _p, _n, _names in with_sketches:
            log.append(f"  sketches={_n}  {_p}" + (f"  [{', '.join(_names[:12])}{', ...' if len(_names) > 12 else ''}]" if _names else ""))
        with open(os.path.join(out_dir, "_batch_export_log.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(log))
        ui.messageBox(f"Batch export finished.\n\nCreated: {len(made)}" + (f" ({len(overwritten)} overwritten)" if overwritten else "") +
                      f"\nSkipped: {len(skipped)}\n"
                      f"Failed: {len(failed)}" + (("\n  " + "\n  ".join(failed)) if failed else "") +
                      f"\nDesigns with sketch-only sketches: {len(with_sketches)}" +
                      f"\nPictures (.png): {len(png_ok)} saved, {len(png_skipped)} kept, {len(png_failed)} failed" +
                      "".join(f"\n.{e}: {c['ok']} saved, {c['skipped']} kept, {c['failed']} failed" for e, c in fmt_counts.items()) +
                      f"\n\nLog: {out_dir}\\_batch_export_log.txt")
    except Exception:
        ui.messageBox("Batch export failed:\n{}".format(traceback.format_exc()))
