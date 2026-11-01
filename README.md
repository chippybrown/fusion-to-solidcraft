# Fusion 360 to SolidCraft

Fusion 360 scripts and a converter that export a design to a build123d Python file, then turn those exports into SolidCraft designs. The Download section below gets the files as a ZIP. A GitHub account is not required.

## Download

1. On this repository page, click **Code**.
2. Click **Download ZIP**.
3. Unzip the archive.

No GitHub account is needed.

## Fusion 360 -> SolidCraft scripts

ExportToPython + ExportToPythonBatch (Fusion scripts) and py_to_solidcraft (converter).

### Install the Fusion scripts (Windows)

1. Copy both folders, `ExportToPython` and `ExportToPythonBatch`, side by side into
   `%APPDATA%\Autodesk\Autodesk Fusion 360\API\Scripts\`
   Keep them together, because the batch script uses ExportToPython.
2. In Fusion: **Utilities > Add-Ins > Scripts and Add-Ins**. Both scripts appear in the list.
   You can also use the **+** button and pick each folder.

ExportToPython exports the open design to a build123d `.py` file in
`Documents\Fusion exports\<project>\<folders>\`.

### ExportToPythonBatch

- Open (or select) a saved design first, then run the script. It asks for the export scope:
    1. only the design you have open (the default)
    2. every design in that design's folder (it then asks whether to include subfolders)
    3. the whole project

  It then asks whether to overwrite files that already exist.
- For each design it writes these files into `Documents\Fusion exports\<project>\<folder path>\`:
    - `<Design>.py`, `.step`, `.obj`, `.3mf`, `.stl`, `.f3d`
    - six pictures: `<Design>_iso/top/front/back/left/right.png`

  The `.py` includes the assembly data (part placements, joints).
- Designs it opened itself are closed without saving. The design you had open stays open.

### Converter: py_to_solidcraft

Needs Python 3.10+ and SolidCraft installed; it uses `C:\Program Files\SolidCraft\solidcraft-cli.exe`.

1. Copy the `_tools` folder (`py_to_solidcraft.py` plus `viewer\`) to `Documents\Fusion exports\_tools\`.
2. Run:

   ```text
   python "%USERPROFILE%\Documents\Fusion exports\_tools\py_to_solidcraft.py"
   ```

   Useful options:

   - `--only "name"` — convert only designs whose name contains this text
   - `--force` — redo designs whose `.sc` already exists
   - `--timeout <s>` — fixed time limit per file
   - `--no-snapshots` — skip the pictures
   - `--no-viewer` — skip the 3D viewer page

3. Output:
   - `Documents\SolidCraft\My Projects\<same folders>\<Design>.sc`
     If a `.py` fails or gives no bodies, the converter uses the `.step` instead.
   - In the export folder:
       - `<Design>_solidcraft_<view>.png` pictures
       - `<Design>_viewer.html`: Fusion and SolidCraft side by side in 3D.
         It opens straight from disk in any browser.
   - `Documents\Fusion exports\index.html`: an overview of all designs.
- Time limit: automatic. Simple designs get 90 s. Assemblies and big designs get more time,
  scaled by their parts and features, up to 3600 s. A large cabinet assembly can take about
  25 minutes. Each file's time limit is written to the log.
- Placement fix: Fusion sometimes exports a part's sketches already in their assembled
  position. The converter detects this and moves those sketches back into the part's
  own space before placing the part. Assemblies no longer come out "exploded".

## Credit

ExportToPython is by Ran Peleg (Apache 2.0 license, see [ExportToPython/LICENSE](ExportToPython/LICENSE));
keep its license and credits. This copy has local changes: assembly data and
component names in the export.
