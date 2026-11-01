"""
    Fusion 360 to Build123D exporter entry point

    Written by Ran Peleg, Visionware Solutions Pty Ltd
    ran@visionware.com.au
    Provided as-is, without warranty of any kind under Apache-2.0 license

    Local change (LITTLEFOOT): no save dialog. Output goes to
    Documents/Fusion exports/<project>/<folder>/<DesignName>.py
"""

import os
import re
import sys
import traceback

addin_folder = os.path.dirname(os.path.abspath(__file__))
if addin_folder not in sys.path:
    sys.path.append(addin_folder)

import adsk.core
import adsk.fusion

from exporter import export_active_design


def _documents_folder():
    """Return the user's Documents folder (handles OneDrive-redirected Documents)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def _safe(name, fallback):
    """Make a name safe for a Windows file or folder name."""
    name = re.sub(r'[<>:"/\\|?*]', "_", name or "").strip().rstrip(".")
    return name or fallback


def _design_name(doc_name):
    """Fusion document name without its ' v12' version suffix."""
    return re.sub(r"\s+v\d+$", "", doc_name or "").strip()


def _data_location(doc):
    """Return (project name or None, [sub-folder names below the project root])."""
    project_name, folders = None, []
    try:
        data_file = doc.dataFile
        if data_file:
            try:
                project_name = data_file.parentProject.name
            except Exception:
                pass
            try:
                folder = data_file.parentFolder
                while folder and not folder.isRoot:
                    folders.insert(0, folder.name)
                    folder = folder.parentFolder
            except Exception:
                pass
    except Exception:
        pass
    return project_name, folders


def _output_path(design_name, project_name, folders):
    parts = [_documents_folder(), "Fusion exports", _safe(project_name, "Unsaved")]
    parts += [_safe(f, "_") for f in folders]
    out_dir = os.path.join(*parts)
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, _safe(design_name, "FusionDesign") + ".py")


def _prepend_location_header(script_path, design_name, project_name, folders):
    """Write the Fusion design/project/folder as comments at the top of the generated script."""
    header = (
        f"# Fusion design: {design_name}\n"
        f"# Fusion project: {project_name or 'Unsaved / unknown'}\n"
        f"# Fusion folder: {'/'.join(folders) if folders else '(project root)'}\n\n"
    )
    with open(script_path, "r", encoding="utf-8") as fh:
        body = fh.read()
    with open(script_path, "w", encoding="utf-8") as fh:
        fh.write(header + body)


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface

    try:
        doc = app.activeDocument
        if doc is None:
            ui.messageBox("No active design to export.")
            return
        design_name = _design_name(doc.name)
        project_name, folders = _data_location(doc)
        output_path = _output_path(design_name, project_name, folders)

        script_path, unsupported = export_active_design(output_path)
        _prepend_location_header(script_path, design_name, project_name, folders)
        note = ""
        if unsupported:
            note = f"\n\nReview {len(unsupported)} export note(s) at the bottom of the generated script."
        ui.messageBox(f"Parametric Build123D export completed:\n\n{script_path}{note}")
    except Exception:
        ui.messageBox("Build123D export failed:\n{}".format(traceback.format_exc()))