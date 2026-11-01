r"""py_to_solidcraft.py - convert Fusion-exported build123d .py files (and .step/.stp files) into SolidCraft designs (.sc).

Requirements
  - Windows, plain Python 3.10+ (standard library only; build123d is NOT needed):
        %USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe
  - SolidCraft (solidcraft-cli.exe), default: C:\Program Files\SolidCraft\solidcraft-cli.exe

Usage (exact command lines, run in PowerShell or cmd)
  Convert everything (default root, recursive):
    & "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe" "%USERPROFILE%\Documents\Fusion exports\_tools\py_to_solidcraft.py"
  Re-convert everything, overwriting existing outputs:
    & "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe" "%USERPROFILE%\Documents\Fusion exports\_tools\py_to_solidcraft.py" --force
  Only one folder:
    & "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe" "%USERPROFILE%\Documents\Fusion exports\_tools\py_to_solidcraft.py" --root "%USERPROFILE%\Documents\Fusion exports\My Projects\House\Cabinets"
  Only the exports that contain sketch-only geometry (SKETCH_ONLY entries), overwriting their outputs:
    & "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe" "%USERPROFILE%\Documents\Fusion exports\_tools\py_to_solidcraft.py" --force --only-with-sketches
  Other options: --only "Door Pull" (file names containing this), --out <folder> (other output root),
                 --timeout <s> (seconds per file; default automatic: 90 s simple, scaled for assemblies, cap 3600 s), --cli <path to solidcraft-cli.exe>,
                 --only-with-sketches (only .py files with SKETCH_ONLY entries; STEP files are skipped)
  Best .sc per design: the .sc is built from the .py; when that fails, or gives an empty design / 0 bodies, the
      design's own .step (same folder, same name) is converted instead (source: py / step-fallback / step-only,
      recorded in the report, the index status and the helper).  A .step next to a .py is never converted on its own.
  Raw haul (Fusion exports\My Projects\<tree>\, next to the .py): SolidCraft pictures <name>_solidcraft_<view>.png
      (solidcraft-cli snapshot, 1600x1200; only after a successful save with bodies; a skipped up-to-date .sc only gets
      missing ones), <name>_fusion.glb (from the Fusion .3mf/.obj/.stl), <name>_solidcraft.glb (from the .sc) and
      <name>_viewer.html (rotatable side-by-side 3D view, self-contained, opens from file:// in any browser).
      The SolidCraft tree (Documents\SolidCraft\My Projects\<tree>\) gets only <name>.sc.
                   --views iso,top,front,back,left,right   (default; names: iso, front, back, top, bottom, left, right)
                   --no-snapshots / --no-viewer
      Picture, GLB and viewer failures are warnings only.
  Inside each .sc: the design's own component is named after the Fusion design, and the design description
      (File > Properties) holds the paths to the Fusion .3mf, the viewer, the .f3d and the helper index (text only).
      Exports from the updated ExportToPython also carry FUSION_ASSEMBLY: then components, placements (world
      transforms), grounding, as-built joints and rigid groups are rebuilt in SolidCraft (never fails the file).
  Helper:  %USERPROFILE%\Documents\Fusion exports\index.html, rebuilt for the whole tree after every run
      (statuses kept in _tools\index_status.json; only the files just converted are updated);
                   --index-only                            (only rebuild the helper)
  Log:    %USERPROFILE%\Documents\Fusion exports\_tools\py_to_solidcraft.log         (flushed after every file)
  Report: %USERPROFILE%\Documents\Fusion exports\_tools\py_to_solidcraft_report.json  (rewritten after every file)

Folders
  Default root : %USERPROFILE%\Documents\Fusion exports\My Projects   (walked recursively)
  Output       : %USERPROFILE%\Documents\SolidCraft\My Projects\<same relative path>\<name>.sc
  --root <folder>: inside Fusion exports\My Projects -> output still mirrors into Documents\SolidCraft\My Projects;
      any other folder -> <folder>\SolidCraft\<relative path>.  --out overrides the output root.
  Skipped: folders _tools, venv/.venv (any folder with pyvenv.cfg), __pycache__, any folder with "SolidCraft"
      in its name; Bathroom Mirrors.py/.step (converted by hand - its Bathroom Mirrors.sc lives in
      Documents\SolidCraft\My Projects\House\Cabinets and is never overwritten or moved, even with --force);
      any input whose output .sc already exists and is newer, unless --force.
  Older .sc files found next to a .py (never Bathroom Mirrors.sc) are moved into the output tree.
  STEP files: every .step/.stp in the scanned tree is converted in the same pass with
        solidcraft-cli run <file>.step --save <out>.sc        (same per-file timeout, geometry only)
      to <output>\<same relative path>\<basename>.sc, with the same skip/--force rules.  If X.py and X.step are in
      the same folder, X.py is converted and X.step is skipped.  (ExportToPythonBatch writes <Design>.step instead of
      a .py for non-parametric / direct-modeling designs.)
  The .py and .step files are only read.  Intermediate .solidcraft.json scripts go to a temp folder only.

How it works
  Each file is converted in its own child process with a hard timeout (default 90 s); on timeout the whole
  process tree is killed, the file is logged as FAILED (timeout) and the batch moves on.
  The child runs the .py against a small stub of the build123d API that records the operations (sketches,
  extrude, revolve, hole, mirror, fillet, chamfer, shell, sweep, colours) and writes a parametric SolidCraft
  command script (Fusion feature names, user parameters, parameter-driven distances, appearance.assign), the
  same way as the hand-made Bathroom Mirrors example.  It is checked and saved only with
        solidcraft-cli run <Name>.solidcraft.json --save <Name>.sc --param-check warn [--results]
  (no long-lived MCP session).  When SolidCraft refuses a command, the script is regenerated with the next
  fallback for that feature (or without it, logged as an error) and run again, within the time limit.

Sketch-only geometry (Fusion sketches / curves / text that no feature uses)
  Newer exports end with a plain-data list SKETCH_ONLY (and SKETCH_ONLY_COUNT): one dict per Fusion sketch with
  its plane (world origin, x_dir, y_dir, z_dir in mm) and its unused curves (line, arc, circle, ellipse, spline),
  sketch texts (text, font, height, centre, angle, bold/italic) and standalone points, in sketch-local mm.
  After the solid features have been converted and saved, they are added in a second step on top of that design:
        solidcraft-cli run <Name>.sketches.json --in out.sc --save out2.sc --param-check off
  as named sketches (sketch.create on the same plane, with the Fusion sketch name; " (unused geometry)" is added
  when the Fusion sketch also has curves that features use) -- never bodies or cuts, so the bodies stay exactly
  as converted.  Curves: sketch.line / sketch.arc.three_point / sketch.circle.center / sketch.ellipse /
  sketch.spline.fit_point (splines are sampled from the exact Fusion curve) / sketch.point.  Text: sketch.text
  with the Fusion font name, height, angle, bold/italic, centred on the Fusion text box.  Text is recreated
  from the font name, so it may not match Fusion's rendering exactly; a font SolidCraft does not have is
  replaced by SolidCraft's built-in font (logged as a warning); text that is still refused is left out (logged).
  Sketches that were hidden in Fusion are hidden (browser.visibility).  A refused curve/text is retried with
  its fallback or left out; a refused sketch is left out; any failure or running out of time in this step keeps
  the design without the sketch-only sketches.  Sketch problems never fail the file; they are logged as
  "left out: sketch-only ...".  The log line of each file shows sketches=<placed>/<in the export>.
"""
import argparse, ast, json, math, os, re, subprocess, sys, tempfile, time, traceback, types, shutil

HOME = os.path.expanduser('~')
EXPORTS = os.path.join(HOME, 'Documents', 'Fusion exports')
DEFAULT_ROOT = os.path.join(EXPORTS, 'My Projects')
DEFAULT_OUT = os.path.join(HOME, 'Documents', 'SolidCraft', 'My Projects')
TOOLS = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CLI = r'C:\Program Files\SolidCraft\solidcraft-cli.exe'
SKIP_DIRS = {'_tools', 'venv', '.venv', '__pycache__'}
SKIP_FILES = {'bathroom mirrors.py'}
TOL = 1e-6
SNAP_VIEWS = ('iso', 'top', 'front', 'back', 'left', 'right')
SNAP_W, SNAP_H = 1600, 1200
INDEX_PATH = os.path.join(EXPORTS, 'index.html')

# ----------------------------------------------------------------------------- units / exprs
def r6(v):
    v = round(float(v), 6)
    return 0.0 if v == 0 else v

def fmt_len(mm):
    mm = abs(float(mm))
    inch = mm / 25.4
    if abs(inch * 64 - round(inch * 64)) < 1e-6:
        return '%s in' % _g(round(inch, 6))
    return '%s mm' % _g(round(mm, 6))

def _g(v):
    s = ('%.6f' % v).rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s

_UNITF = {'in': 25.4, 'mm': 1.0, 'cm': 10.0, 'm': 1000.0, 'ft': 304.8}

def convert_literals(e):
    """Fusion feet/inch notations -> 'x in'."""
    e = e.strip()
    def ftin(m):
        ft = float(m.group(1)); whole = float(m.group(2) or 0)
        frac = float(m.group(3)) / float(m.group(4)) if m.group(3) else 0.0
        return '%s in' % _g(ft * 12 + whole + frac)
    e = re.sub(r"(\d+(?:\.\d+)?)\s*'\s*-?\s*(?:(\d+(?:\.\d+)?)\s+)?(?:(\d+)\s*/\s*(\d+))?\s*\"", ftin, e)
    e = re.sub(r"(?:(\d+(?:\.\d+)?)\s+)?(\d+)\s*/\s*(\d+)\s*\"",
               lambda m: '%s in' % _g(float(m.group(1) or 0) + float(m.group(2)) / float(m.group(3))), e)
    e = re.sub(r"(\d+(?:\.\d+)?|\.\d+)\s*\"", lambda m: '%s in' % _g(float(m.group(1))), e)
    e = re.sub(r"(\d+(?:\.\d+)?|\.\d+)\s*'", lambda m: '%s in' % _g(float(m.group(1)) * 12), e)
    return re.sub(r'\s+', ' ', e).strip()

def eval_mm(e, values):
    """Evaluate a (converted) expression in mm; None if it can't be checked."""
    if re.search(r'[A-Za-z_]\w*\s*\(', e):
        return None
    s = re.sub(r'(\d+(?:\.\d+)?|\.\d+)\s*(in|mm|cm|ft|m)\b', lambda m: '(%s*%r)' % (m.group(1), _UNITF[m.group(2)]), e)
    names = set(re.findall(r'[A-Za-z_]\w*', s))
    if any(n not in values for n in names):
        return None
    try:
        return float(eval(s, {'__builtins__': {}}, dict(values)))
    except Exception:
        return None

def refs_in(e):
    s = re.sub(r'(\d+(?:\.\d+)?|\.\d+)\s*(in|mm|cm|ft|m|deg)\b', '0', e)
    return set(re.findall(r'[A-Za-z_]\w*', s))

class Sym(float):
    """A float that remembers the parameter expression it came from (length dimension)."""
    def __new__(cls, v, expr, dim=1, atom=False):
        o = float.__new__(cls, v); o.expr = expr; o.dim = dim; o.atom = atom; return o
    def _p(self):
        return self.expr if self.atom else '(%s)' % self.expr
    @staticmethod
    def _o(x, dim):
        if isinstance(x, Sym): return x._p(), x.dim
        return (fmt_len(x) if x >= 0 else '-' + fmt_len(x)) if dim == 1 else _g(float(x)), None
    def _add(self, o, sign, rev=False):
        v = float(self) + sign * float(o) if not rev else float(o) + sign * float(self)
        a = self.expr if not rev else Sym._o(o, self.dim)[0]
        if isinstance(o, Sym):
            if o.dim != self.dim: return v
            b = o._p() if sign < 0 else o.expr
        else:
            b = Sym._o(o, self.dim)[0]
        if rev: b = self._p() if sign < 0 else self.expr
        return Sym(v, '%s %s %s' % (a, '+' if sign > 0 else '-', b), self.dim)
    def __add__(self, o): return self._add(o, 1) if isinstance(o, (int, float)) else NotImplemented
    def __radd__(self, o): return self._add(o, 1, True) if isinstance(o, (int, float)) else NotImplemented
    def __sub__(self, o): return self._add(o, -1) if isinstance(o, (int, float)) else NotImplemented
    def __rsub__(self, o): return self._add(o, -1, True) if isinstance(o, (int, float)) else NotImplemented
    def __mul__(self, o):
        if not isinstance(o, (int, float)): return NotImplemented
        v = float(self) * float(o)
        if isinstance(o, Sym): return Sym(v, '%s * %s' % (self._p(), o._p()), self.dim + o.dim)
        if o == 1: return self
        return Sym(v, '%s * %s' % (self._p(), _g(float(o))), self.dim)
    __rmul__ = __mul__
    def __truediv__(self, o):
        if not isinstance(o, (int, float)): return NotImplemented
        v = float(self) / float(o)
        if isinstance(o, Sym): return Sym(v, '%s / %s' % (self._p(), o._p()), self.dim - o.dim)
        return Sym(v, '%s / %s' % (self._p(), _g(float(o))), self.dim)
    def __neg__(self):
        if self.expr.startswith('-') and re.fullmatch(r'-[A-Za-z_]\w*', self.expr):
            return Sym(-float(self), self.expr[1:], self.dim, True)
        return Sym(-float(self), '-' + self._p(), self.dim)
    def __pos__(self): return self
    def __abs__(self): return -self if float(self) < 0 else self

def length_expr(v, comment=None):
    """Positive length (absolute value) as an expression string."""
    if isinstance(v, Sym) and v.dim == 1:
        s = abs(v)
        return s.expr if isinstance(s, Sym) else fmt_len(s)
    if comment:
        m = re.search(r'Fusion expression:\s*(.+?)\s*$', comment)
        if m:
            raw = m.group(1).split(';')[0].strip()
            conv = convert_literals(raw)
            for cand in (conv, conv[1:].strip() if conv.startswith('-') else None):
                if not cand: continue
                ev = eval_mm(cand, PARAM_VALUES)
                if ev is not None and abs(ev - abs(float(v))) < 1e-4 * max(1.0, abs(float(v))):
                    return cand
    return fmt_len(v)

PARAM_VALUES = {}

# ----------------------------------------------------------------------------- vector helpers
def vsub(a, b): return [a[i] - b[i] for i in range(3)]
def vadd(a, b): return [a[i] + b[i] for i in range(3)]
def vdot(a, b): return sum(float(a[i]) * float(b[i]) for i in range(3))
def vcross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def vnorm(a):
    n = math.sqrt(sum(float(x) * float(x) for x in a)) or 1.0
    return [float(x) / n for x in a]
def mmul(A, B): return [[sum(A[i][k] * B[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

# ----------------------------------------------------------------------------- build123d stub
class Rec:
    def __init__(self, path):
        self.path = path; self.ops = []; self.parts = []; self.part_stack = []
        self.sketch = None; self.line = None; self.locs = []; self.nsk = 0
    def line_no(self):
        f = sys._getframe(1)
        while f is not None:
            if os.path.abspath(f.f_code.co_filename) == self.path: return f.f_lineno
            f = f.f_back
        return 0
REC = None

class Enum:
    def __init__(self, name): self.name = name
    def __repr__(self): return self.name
class _NS:
    def __init__(self, *names):
        for n in names: setattr(self, n, Enum(n))
Mode = _NS('ADD', 'SUBTRACT', 'INTERSECT', 'REPLACE', 'PRIVATE')
Until = _NS('FIRST', 'LAST', 'NEXT', 'PREVIOUS')
GeomType = _NS('CIRCLE', 'LINE', 'PLANE', 'CYLINDER', 'BSPLINE')
Align = _NS('CENTER', 'MIN', 'MAX', 'NONE')
class Axis:
    """build123d Axis: Axis.X / Axis.Y / Axis.Z or Axis(origin=(..), direction=(..))."""
    def __init__(self, origin=(0, 0, 0), direction=(0, 0, 1), *a, **k):
        if isinstance(origin, Plane) or isinstance(origin, Location): raise NotImplementedError('Axis from a plane/location')
        self.origin = [r6(x) for x in origin]; self.direction = [r6(x) for x in vnorm(direction)]
        self.name = None

class Plane:
    def __init__(self, origin=(0, 0, 0), x_dir=(1, 0, 0), z_dir=(0, 0, 1)):
        self.origin = list(origin); self.x = vnorm(x_dir); self.z = vnorm(z_dir)
        self.y = vnorm(vcross(self.z, self.x))
    def to_world(self, p):
        return [r6(float(self.origin[i]) + float(p[0]) * self.x[i] + float(p[1]) * self.y[i]) for i in range(3)]
for _n, _o, _x, _z in [('XY', (0,0,0), (1,0,0), (0,0,1)), ('XZ', (0,0,0), (1,0,0), (0,-1,0)), ('YZ', (0,0,0), (0,1,0), (1,0,0))]:
    setattr(Plane, _n, Plane(_o, _x, _z))

class Location:
    def __init__(self, a=None, *rest):
        if isinstance(a, Plane):
            M = [[a.x[i], a.y[i], a.z[i], float(a.origin[i])] for i in range(3)]
        elif isinstance(a, Location):
            M = [r[:] for r in a.M[:3]]
        elif a is None:
            M = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]
        else:
            t = list(a) + [0] * (3 - len(a))
            M = [[1, 0, 0, float(t[0])], [0, 1, 0, float(t[1])], [0, 0, 1, float(t[2])]]
            if rest: raise NotImplementedError('Location with rotation')
        self.M = M + [[0, 0, 0, 1]]
    def __mul__(self, o):
        L = Location(); L.M = mmul(self.M, o.M); return L
    @property
    def origin(self): return [r6(self.M[i][3]) for i in range(3)]
    @property
    def zdir(self): return [self.M[i][2] for i in range(3)]
    @property
    def xdir(self): return [self.M[i][0] for i in range(3)]

Axis.X = Axis((0, 0, 0), (1, 0, 0)); Axis.X.name = 'X'
Axis.Y = Axis((0, 0, 0), (0, 1, 0)); Axis.Y.name = 'Y'
Axis.Z = Axis((0, 0, 0), (0, 0, 1)); Axis.Z.name = 'Z'

class Locations:
    def __init__(self, *pts):
        self.pts = []
        for p in pts:
            if isinstance(p, (list,)) and p and not isinstance(p[0], (int, float)): self.pts.extend(p)
            else: self.pts.append(p)
    def __enter__(self):
        REC.locs.append(self); return self
    def __exit__(self, *a):
        REC.locs.pop()

def _sketch_positions():
    pos = [(0.0, 0.0)]
    for L in REC.locs:
        new = []
        for b in pos:
            for p in L.pts:
                if isinstance(p, (Plane, Location)): raise NotImplementedError('3D Locations inside a sketch')
                new.append((b[0] + p[0], b[1] + p[1]))
        pos = new
    return pos

def _world_locations():
    locs = [Location()]
    for L in REC.locs:
        new = []
        for b in locs:
            for p in L.pts:
                q = Location(p) if isinstance(p, Plane) else (p if isinstance(p, Location) else Location(tuple(p)))
                new.append(b * q)
        locs = new
    return locs

def P(p):
    if isinstance(p, Vec): return p.t
    return tuple(r6(x) for x in p)

class Vec:
    def __init__(self, t): self.t = tuple(r6(x) for x in t)
    def __getitem__(self, i): return self.t[i]
    def __len__(self): return len(self.t)
    def __iter__(self): return iter(self.t)

class Curve:
    def __init__(self, kind, pts, **kw):
        self.kind = kind; self.pts = [P(p) for p in pts]; self.kw = kw
        if REC.line is not None: REC.line.curves.append(self)
    def __matmul__(self, t):
        if self.kind == 'circle': return Vec(self.pts[0])
        if t <= 0: return Vec(self.pts[0])
        if t >= 1: return Vec(self.pts[-1])
        a, b = self.pts[0], self.pts[-1]
        return Vec(tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a))))

def Line(a, b, *rest): return Curve('line', [a, b])
def ThreePointArc(a, b, c): return Curve('arc', [a, b, c])
def Spline(*pts, **kw):
    if len(pts) == 1 and isinstance(pts[0], (list, tuple)) and pts[0] and isinstance(pts[0][0], (list, tuple, Vec)): pts = pts[0]
    if kw.get('tangents'): raise NotImplementedError('Spline tangents')
    return Curve('spline', list(pts))
def Polyline(*pts, close=False):
    pts = [P(p) for p in pts]
    if close and pts[0] != pts[-1]: pts = pts + [pts[0]]
    out = [Curve('line', [pts[i], pts[i + 1]]) for i in range(len(pts) - 1)]
    return out

class BuildLine:
    def __init__(self, *a, **k):
        if a or k: raise NotImplementedError('BuildLine with arguments')
        self.curves = []; self.ln = REC.line_no()
    def __enter__(self):
        self.prev = REC.line; REC.line = self; return self
    def __exit__(self, *a):
        REC.line = self.prev
    @property
    def line(self): return self

class Shape:
    def __init__(self, mode, curves, rect=None):
        self.mode = mode.name if isinstance(mode, Enum) else 'ADD'; self.curves = curves; self.rect = rect

def _add_shape(sh):
    if REC.sketch is None: raise NotImplementedError('2D shape outside BuildSketch')
    REC.sketch.shapes.append(sh)

def Rectangle(width, height, rotation=0, align=None, mode=Mode.ADD):
    if align not in (None,) and not (isinstance(align, (tuple, list)) and all(getattr(x, 'name', '') == 'CENTER' for x in align)) and getattr(align, 'name', 'CENTER') != 'CENTER':
        raise NotImplementedError('Rectangle align')
    rot = float(rotation) % 360
    saved = REC.line; REC.line = None
    for (cx, cy) in _sketch_positions():
        if abs(rot % 90) < 1e-9:
            hw, hh = (float(width) / 2, float(height) / 2) if abs(rot % 180) < 1e-9 else (float(height) / 2, float(width) / 2)
            c = [(cx - hw, cy - hh), (cx + hw, cy - hh), (cx + hw, cy + hh), (cx - hw, cy + hh)]
            rect = (P(c[0]), P(c[2]))
        else:
            a = math.radians(rot); ca, sa = math.cos(a), math.sin(a)
            c = [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in
                 [(-width / 2, -height / 2), (width / 2, -height / 2), (width / 2, height / 2), (-width / 2, height / 2)]]
            rect = None
        cs = [Curve('line', [c[i], c[(i + 1) % 4]]) for i in range(4)]
        _add_shape(Shape(mode, cs, rect))
    REC.line = saved

def Circle(radius, align=None, mode=Mode.ADD):
    saved = REC.line; REC.line = None
    for (cx, cy) in _sketch_positions():
        _add_shape(Shape(mode, [Curve('circle', [(cx, cy)], r=r6(radius))]))
    REC.line = saved

def make_face(edges=None, mode=Mode.ADD):
    if isinstance(edges, BuildLine): cs = list(edges.curves)
    elif edges is None: cs = list(REC.line.curves) if REC.line else []
    else: cs = list(edges)
    _add_shape(Shape(mode, cs))

class SketchRef:
    def __init__(self, bs, delta=None): self.bs = bs; self.delta = delta
    def moved(self, loc):
        d = loc.origin if isinstance(loc, Location) else list(loc)
        if self.delta: d = vadd(d, self.delta)
        return SketchRef(self.bs, d)

class BuildSketch:
    def __init__(self, plane=None, *a, **k):
        if a or k: raise NotImplementedError('BuildSketch extra args')
        if isinstance(plane, Location): raise NotImplementedError('BuildSketch on Location')
        self.plane = plane or Plane.XY; self.shapes = []; self.ln = REC.line_no(); self.name = None
        self.idx = REC.nsk; REC.nsk += 1
    def __enter__(self):
        self.prev_locs = REC.locs; REC.locs = []
        REC.sketch = self; return self
    def __exit__(self, *a):
        REC.sketch = None; REC.locs = self.prev_locs
    @property
    def sketch(self): return SketchRef(self)

class PartRef:
    def __init__(self, bp): self.bp = bp; self.color = None

class BuildPart:
    def __init__(self, *a, **k):
        if a or k: raise NotImplementedError('BuildPart with arguments')
        self.ln = REC.line_no(); self.var = None; self._part = PartRef(self)
    def __enter__(self):
        REC.parts.append(self); REC.part_stack.append(self)
        REC.ops.append(('part', self, self.ln)); return self
    def __exit__(self, *a):
        REC.part_stack.pop()
    @property
    def part(self): return self._part

def _cur_part():
    if not REC.part_stack: raise NotImplementedError('operation outside BuildPart')
    return REC.part_stack[-1]

def extrude(to_extrude=None, amount=None, dir=None, until=None, target=None, both=False, taper=0, clean=True, mode=Mode.ADD):
    if dir is not None or target is not None: raise NotImplementedError('extrude dir/target')
    if not isinstance(to_extrude, SketchRef): raise NotImplementedError('extrude of non-sketch')
    REC.ops.append(('extrude', dict(sk=to_extrude, amount=amount, until=until, both=both, taper=taper, mode=mode.name, part=_cur_part()), REC.line_no()))

def sweep(sections=None, path=None, multisection=False, is_frenet=False, transition=None, normal=None, binormal=None, clean=True, mode=Mode.ADD):
    if not isinstance(sections, SketchRef) or not isinstance(path, BuildLine) or multisection or normal or binormal:
        raise NotImplementedError('sweep variant')
    REC.ops.append(('sweep', dict(sk=sections, path=path, frenet=is_frenet, mode=mode.name, part=_cur_part()), REC.line_no()))

def revolve(profiles=None, axis=None, revolution_arc=360.0, clean=True, mode=Mode.ADD):
    if not isinstance(profiles, SketchRef): raise NotImplementedError('revolve of non-sketch')
    if axis is None: axis = Axis.Z
    if not isinstance(axis, Axis): raise NotImplementedError('revolve axis type')
    REC.ops.append(('revolve', dict(sk=profiles, axis=axis, arc=revolution_arc, mode=mode.name, part=_cur_part()), REC.line_no()))

class Pick:
    def __init__(self, pt): self.pt = [r6(x) for x in pt]
class ShapeList:
    def __init__(self, kind): self.kind = kind
    def filter_by(self, *a, **k): return self
    def sort_by_distance(self, pt, *a, **k): return [Pick(pt)]
def edges(*a, **k): return ShapeList('edge')
def faces(*a, **k): return ShapeList('face')

def _picks(objs):
    if isinstance(objs, Pick): return [objs.pt]
    out = []
    for o in objs:
        if not isinstance(o, Pick): raise NotImplementedError('fillet/chamfer on non-picked object')
        out.append(o.pt)
    return out

def fillet(objects, radius):
    REC.ops.append(('fillet', dict(edges=_picks(objects), radius=radius, part=_cur_part()), REC.line_no()))
def chamfer(objects, length, length2=None, angle=None, reference=None):
    if angle is not None or reference is not None: raise NotImplementedError('chamfer angle/reference')
    REC.ops.append(('chamfer', dict(edges=_picks(objects), length=length, length2=length2, part=_cur_part()), REC.line_no()))
def offset(objects=None, amount=0, openings=None, kind=None, side=None, closed=True, min_edge_length=None, mode=Mode.REPLACE):
    if objects is not None: raise NotImplementedError('offset of explicit objects')
    REC.ops.append(('shell', dict(faces=_picks(openings or []), amount=amount, part=_cur_part()), REC.line_no()))
def mirror(objects=None, about=None, mode=Mode.ADD):
    if objects is not None or about is None or mode.name != 'ADD': raise NotImplementedError('mirror variant')
    if REC.sketch is not None: raise NotImplementedError('mirror inside sketch')
    REC.ops.append(('mirror', dict(plane=about, part=_cur_part()), REC.line_no()))

def Hole(radius, depth=None, mode=Mode.SUBTRACT):
    part = _cur_part()
    for loc in _world_locations():
        REC.ops.append(('hole', dict(radius=radius, depth=depth, loc=loc, part=part), REC.line_no()))

class Color:
    def __init__(self, *a, **k): self.rgb = a

def _unsupported(name):
    def f(*a, **k): raise NotImplementedError('build123d %s() is not supported by the converter' % name)
    return f

def make_stub():
    m = types.ModuleType('build123d')
    names = dict(Mode=Mode, Until=Until, GeomType=GeomType, Align=Align, Axis=Axis, Plane=Plane, Location=Location,
                 Locations=Locations, Line=Line, ThreePointArc=ThreePointArc, Spline=Spline, Polyline=Polyline,
                 BuildLine=BuildLine, BuildSketch=BuildSketch, BuildPart=BuildPart, Rectangle=Rectangle, Circle=Circle,
                 make_face=make_face, extrude=extrude, sweep=sweep, revolve=revolve, edges=edges, faces=faces, fillet=fillet,
                 chamfer=chamfer, offset=offset, mirror=mirror, Hole=Hole, Color=Color, Vector=Vec)
    for n in ['loft', 'Box', 'Cylinder', 'Sphere', 'Text', 'RegularPolygon', 'SlotCenterToCenter', 'Ellipse',
              'JernArc', 'TangentArc', 'RadiusArc', 'CenterArc', 'Bezier', 'PolarLine', 'Helix', 'add', 'split', 'scale',
              'export_step', 'export_stl', 'CounterBoreHole', 'CounterSinkHole', 'Torus', 'Cone', 'Wedge', 'section',
              'project', 'thicken', 'make_hull', 'Trapezoid', 'SlotOverall', 'FilletPolyline', 'PolarLocations', 'GridLocations']:
        names[n] = _unsupported(n)
    for k, v in names.items(): setattr(m, k, v)
    m.__all__ = list(names)
    return m

# ----------------------------------------------------------------------------- source parsing
def parse_source(src):
    lines = src.splitlines()
    head = {}
    for l in lines[:3]:
        m = re.match(r'#\s*Fusion (design|project|folder):\s*(.*)', l)
        if m: head[m.group(1)] = m.group(2).strip()
    params = []
    for l in lines:
        m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(-?[\d.eE+-]+)\s*#\s*Fusion parameter '([^']+)'\s*=\s*(.*)$", l)
        if m: params.append(dict(var=m.group(1), value=float(m.group(2)), name=m.group(3), fexpr=m.group(4).strip()))
    notes = []
    if '# Export notes:' in src:
        tail = src.split('# Export notes:', 1)[1]
        notes = [re.sub(r'^#\s*-\s*', '', l).strip() for l in tail.splitlines() if l.strip().startswith('# -')]
    apps = {}
    for m in re.finditer(r"# Fusion appearance for '(\w+)': (.+?) \(property '(\w+)'\)\s*\n\s*\1\.part\.color = Color\(([^)]*)\)", src):
        apps[m.group(1)] = dict(name=m.group(2).strip(), prop=m.group(3), rgb=[float(x) for x in m.group(4).split(',')])
    return lines, head, params, notes, apps

def feature_name_at(lines, ln, stop_ln):
    for i in range(ln - 1, max(stop_ln - 1, 0) - 1, -1):
        m = re.match(r'\s*#\s*\d+:\s*(.+?)\s*$', lines[i - 1] if i >= 1 else '')
        if m: return m.group(1)
    return None

def body_name_at(lines, ln):
    for i in range(ln - 1, max(ln - 4, 0), -1):
        m = re.match(r'\s*#\s*Body:\s*(.+?)\s*$', lines[i - 1])
        if m: return m.group(1)
    return None

def component_at(lines, ln):
    for i in range(ln - 1, max(ln - 4, 0), -1):
        m = re.match(r'\s*#\s*Component:\s*(.+?)\s*$', lines[i - 1])
        if m: return m.group(1)
    return None

def var_at(lines, ln, kind):
    m = re.search(r'with\s+%s\(.*\)\s+as\s+(\w+)\s*:' % kind, lines[ln - 1])
    return m.group(1) if m else None

def trailing_comment(lines, ln):
    l = lines[ln - 1]
    i = l.find('#')
    return l[i + 1:].strip() if i >= 0 else ''

# ----------------------------------------------------------------------------- sketch geometry
def arc_center(a, b, c):
    ax, ay = a; bx, by = b; cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12: return None
    ux = ((ax*ax+ay*ay)*(by-cy) + (bx*bx+by*by)*(cy-ay) + (cx*cx+cy*cy)*(ay-by)) / d
    uy = ((ax*ax+ay*ay)*(cx-bx) + (bx*bx+by*by)*(ax-cx) + (cx*cx+cy*cy)*(bx-ax)) / d
    return ux, uy

def sample_curve(c):
    if c.kind == 'line': return [c.pts[0], c.pts[1]]
    if c.kind == 'spline': return list(c.pts)
    if c.kind == 'circle':
        (x, y), r = c.pts[0], c.kw['r']
        return [(x + r * math.cos(2 * math.pi * i / 48), y + r * math.sin(2 * math.pi * i / 48)) for i in range(49)]
    a, b, e = c.pts
    cen = arc_center(a, b, e)
    if cen is None: return [a, e]
    r = math.hypot(a[0] - cen[0], a[1] - cen[1])
    t0 = math.atan2(a[1] - cen[1], a[0] - cen[0]); tm = math.atan2(b[1] - cen[1], b[0] - cen[0]); t1 = math.atan2(e[1] - cen[1], e[0] - cen[0])
    def ccw(s, t): return (t - s) % (2 * math.pi)
    sweep_ = ccw(t0, t1)
    if ccw(t0, tm) > sweep_: sweep_ = sweep_ - 2 * math.pi
    n = 24
    return [(cen[0] + r * math.cos(t0 + sweep_ * i / n), cen[1] + r * math.sin(t0 + sweep_ * i / n)) for i in range(n + 1)]

def close(p, q, tol=1e-5): return abs(p[0] - q[0]) < tol and abs(p[1] - q[1]) < tol

def loop_polygon(curves):
    segs = [sample_curve(c) for c in curves]
    if len(segs) == 1: return segs[0]
    poly = list(segs[0]); rest = segs[1:]
    # orient first segment so its end meets one of the others
    if not any(close(poly[-1], s[0]) or close(poly[-1], s[-1]) for s in rest): poly.reverse()
    while rest:
        for i, s in enumerate(rest):
            if close(poly[-1], s[0]): poly.extend(s[1:]); rest.pop(i); break
            if close(poly[-1], s[-1]): poly.extend(list(reversed(s))[1:]); rest.pop(i); break
        else:
            for s in rest: poly.extend(s)
            break
    return poly

def seg3(p, a, b):
    d = [b[i] - a[i] for i in range(3)]; L = sum(x * x for x in d)
    t = 0 if L == 0 else max(0, min(1, sum((p[i] - a[i]) * d[i] for i in range(3)) / L))
    return math.dist(p, [a[i] + t * d[i] for i in range(3)])

def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]; L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)

def interior_point(polys):
    edges_ = [(poly[i], poly[i + 1]) for poly in polys for i in range(len(poly) - 1)]
    for poly in polys:
        if not close(poly[0], poly[-1]): edges_.append((poly[-1], poly[0]))
    xs = [p[0] for p in polys[0]]; ys = [p[1] for p in polys[0]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    best, bestc = None, -1
    N = 41
    for axis in (0, 1):
        lo, hi = (y0, y1) if axis == 0 else (x0, x1)
        for k in range(1, N + 1):
            v = lo + (hi - lo) * (k + 0.0137) / (N + 1)
            cr = []
            for a, b in edges_:
                av, bv = (a[1], b[1]) if axis == 0 else (a[0], b[0])
                if (av <= v) != (bv <= v):
                    t = (v - av) / (bv - av)
                    cr.append((a[0] + t * (b[0] - a[0])) if axis == 0 else (a[1] + t * (b[1] - a[1])))
            cr.sort()
            for j in range(0, len(cr) - 1, 2):
                m = (cr[j] + cr[j + 1]) / 2
                p = (m, v) if axis == 0 else (v, m)
                c = min(seg_dist(p, a, b) for a, b in edges_)
                if c > bestc: best, bestc = p, c
    return best, bestc

def split_lines(all_lines):
    """Split every line at endpoints of other lines that lie inside it; return {line_key: [subsegments]}"""
    pts = set()
    for a, b in all_lines: pts.add(a); pts.add(b)
    out = {}
    for a, b in all_lines:
        dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
        if L2 == 0: out[(a, b)] = []; continue
        cuts = []
        for p in pts:
            if p == a or p == b: continue
            t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2
            if 1e-9 < t < 1 - 1e-9 and seg_dist(p, a, b) < 1e-6: cuts.append((t, p))
        cuts.sort()
        seq = [a] + [p for _, p in cuts] + [b]
        out[(a, b)] = [(seq[i], seq[i + 1]) for i in range(len(seq) - 1)]
    return out

def lkey(a, b): return (a, b) if a <= b else (b, a)

def ckey(c):
    if c.kind == 'circle': return ('circle', c.pts[0], c.kw['r'])
    if c.kind == 'arc':
        s = sample_curve(c); mid = s[len(s) // 2]
        e = tuple(sorted([c.pts[0], c.pts[2]]))
        return ('arc', e, (round(mid[0], 4), round(mid[1], 4)))
    pts = tuple(c.pts)
    return ('spline', min(pts, pts[::-1]))


# ----------------------------------------------------------------------------- converter (offline)
WOODS = [('walnut', '#5C4033'), ('mahogany', '#6B2F1E'), ('cherry', '#8B4A2B'), ('oak', '#B8865B'), ('maple', '#D9B47A'),
         ('pine', '#E3C08D'), ('birch', '#E8D3A9'), ('plywood', '#D2B48C'), ('ash', '#D8C3A0'), ('wood', '#A0703C')]

def appearance_params(app):
    name = re.sub(r'^3D\s+', '', app['name'])
    rgb = [max(0, min(255, int(round(v * 255)))) for v in app['rgb'][:3]]
    color = '#%02X%02X%02X' % tuple(rgb)
    low = name.lower()
    if app['prop'] == 'surface_albedo' and color == '#FFFFFF':
        for k, c in WOODS:
            if k in low: color = c; name += ' (approx. color)'; break
    p = {'color': color, 'name': name}
    if app['prop'] == 'metal_f0' or any(k in low for k in ('steel', 'chrome', 'aluminum', 'brass', 'nickel', 'mirror', 'metal', 'iron', 'copper', 'bronze')):
        rough = 0.05 if 'mirror' in low else 0.1 if ('polish' in low or 'chrome' in low) else 0.35 if 'satin' in low else 0.45 if 'brush' in low else 0.3
        p['pbr'] = {'metallic': 1, 'roughness': rough, 'dielectric_ior': 1.5}
    return p

def phash(command, params):
    return command + '|' + json.dumps(params, sort_keys=True)

class SketchDropped(Exception): pass

def new_feedback():
    # level: key -> how many variants were refused; msg0/msg: first/last refusal; res: key -> (phash, result)
    return {'level': {}, 'msg0': {}, 'msg': {}, 'res': {}}

# ----------------------------------------------------------------------------- assembly-context sketches
# ExportToPython writes some sketches "in assembly context": Fusion hands it the sketch as an occurrence
# proxy, so the Plane(...) frame is already in world space (occurrence transform applied) and each 2D point
# is the first two coordinates of T * (u, v, 0) instead of the sketch's own (u, v).  Those bodies come out
# neither in component space nor correctly in world space, and placing the occurrence moves them a second
# time.  The "# Fusion profile: ... bbox=" comments carry the true sketch-space box, which lets us tell the
# two cases apart per sketch and map assembly-context sketches back into component space.
_BBOX_RE = re.compile(r'#\s*Fusion profile:.*bbox=\(\(\s*([-\d.eE+]+),\s*([-\d.eE+]+)\),\s*\(\s*([-\d.eE+]+),\s*([-\d.eE+]+)\)\)')

class OccCtx:
    """Occurrence transform T (row-major 4x4, mm) with the helpers needed to undo it."""
    def __init__(self, T):
        self.T = [float(x) for x in T]
        self.R = [[self.T[0], self.T[1], self.T[2]], [self.T[4], self.T[5], self.T[6]], [self.T[8], self.T[9], self.T[10]]]
        self.t = [self.T[3], self.T[7], self.T[11]]
        a, b, c, d = self.R[0][0], self.R[0][1], self.R[1][0], self.R[1][1]
        self.det2 = a * d - b * c
    def ok2d(self): return abs(self.det2) > 1e-6
    def unmap2d(self, p):
        x, y = float(p[0]) - self.t[0], float(p[1]) - self.t[1]
        a, b, c, d = self.R[0][0], self.R[0][1], self.R[1][0], self.R[1][1]
        return (r6((d * x - b * y) / self.det2), r6((-c * x + a * y) / self.det2))
    def vec(self, v): return [r6(sum(self.R[k][i] * float(v[k]) for k in range(3))) for i in range(3)]
    def point(self, p): return self.vec([float(p[i]) - self.t[i] for i in range(3)])

def _sketch_bbox_comment(lines, ln):
    """Union of the '# Fusion profile ... bbox' comments inside the BuildSketch block starting at line ln."""
    if not lines or ln < 1 or ln > len(lines): return None
    head = lines[ln - 1]; ind = len(head) - len(head.lstrip())
    box = None
    for l in lines[ln:ln + 4000]:
        if l.strip() and (len(l) - len(l.lstrip())) <= ind: break
        m = _BBOX_RE.search(l)
        if not m: continue
        x0, y0, x1, y1 = [float(m.group(k)) for k in range(1, 5)]
        box = [x0, y0, x1, y1] if box is None else [min(box[0], x0), min(box[1], y0), max(box[2], x1), max(box[3], y1)]
    return box

def _pts_bbox(pts):
    if not pts: return None
    return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]

def _bbox_err(a, b):
    return max(abs(a[i] - b[i]) for i in range(4)) if a and b else None

def _map_curve(c, f):
    n = Curve.__new__(Curve)
    n.kind = c.kind; n.kw = dict(c.kw)
    n.pts = [tuple(f(p)) + tuple(p[2:]) for p in c.pts]
    return n

def _map_shape(sh, f, axis_aligned):
    n = Shape.__new__(Shape)
    n.mode = sh.mode; n.curves = [_map_curve(c, f) for c in sh.curves]; n.rect = None
    if sh.rect and axis_aligned:
        a, b = f(sh.rect[0]), f(sh.rect[1])
        n.rect = (P((min(a[0], b[0]), min(a[1], b[1]))), P((max(a[0], b[0]), max(a[1], b[1]))))
    return n

class Converter:
    """Builds the SolidCraft command list without talking to SolidCraft.  Body names are predicted;
    results of earlier `solidcraft-cli run --results` passes (feedback) replace predictions where known."""
    def __init__(self, py, fb):
        self.py = os.path.abspath(py); self.fb = fb
        self.cmds = []; self.warnings = []; self.errors = []; self.names = set()
        self.pieces = {}; self.sk_names = {}; self.used_params = set()

    def uniq(self, n):
        base, k = n, 2
        while n in self.names: n = '%s (%d)' % (base, k); k += 1
        self.names.add(n); return n

    # -- emission
    def emit(self, command, params, key, lkey=None):
        c = {'command': command, 'params': params, 'key': key, 'lkey': lkey or key, 'solid': False}
        self.cmds.append(c)
        r = self.fb['res'].get(key)
        res = r[1] if r and r[0] == phash(command, params) else None
        c['actual'] = res is not None
        return c, res

    def simple(self, command, variants, key, what, lkey=None, fatal_msg=None):
        """variants: [(label, params)]; returns (cmd, result) or None if every variant was refused."""
        lvl = self.fb['level'].get(lkey or key, 0)
        if lvl >= len(variants):
            m = '%s%s refused by SolidCraft, left out: %s' % (command, ' (%s)' % what if what else '', self.fb['msg'].get(lkey or key, '')[:240])
            (self.errors if fatal_msg is None else self.errors).append(m)
            return None
        label, prm = variants[lvl]
        if lvl: self.warnings.append('%s: first attempt refused (%s); used %s' % (what or command, self.fb['msg0'].get(lkey or key, '')[:160], label))
        return self.emit(command, prm, key, lkey)

    def ladder_variants(self, prm, steps):
        out = [('as exported', prm)]
        cur = prm
        for label, fix in steps:
            p2 = json.loads(json.dumps(cur)); fix(p2)
            if p2 == cur: continue
            out.append((label, p2)); cur = p2
        return out

    def solid(self, command, prm, steps, key, part, feat):
        r = self.simple(command, self.ladder_variants(prm, steps), key, feat)
        if r is None: return None
        c, res = r
        c['solid'] = True
        self.apply(c, res, part, prm)
        return c

    def apply(self, c, res, part, prm):
        if isinstance(res, dict) and isinstance(res.get('bodies'), list):
            others = set()
            for p, s in self.pieces.items():
                if p is not part: others |= s
            self.pieces[part] = set(res['bodies']) - others
        elif c['params'].get('operation') == 'new':
            self.pieces[part] = set(self.pieces.get(part, set())) | {c['params'].get('body_name')}
        allb = set()
        for s in self.pieces.values(): allb |= s
        c['pred_all'] = sorted(allb)

    def note_params(self, *vals):
        for v in vals:
            if isinstance(v, str):
                for r in refs_in(v):
                    if r in PARAM_VALUES: self.used_params.add(r)

    # -- main
    def convert(self):
        global REC, PARAM_VALUES
        src = open(self.py, encoding='utf-8').read()
        lines, head, params, notes, apps = parse_source(src)
        self.notes = notes
        self.design = head.get('design') or os.path.splitext(os.path.basename(self.py))[0]
        PARAM_VALUES = {}
        plist = []
        for p in params:
            fx = p['fexpr']; conv = convert_literals(fx)
            if 'deg' in conv:
                plist.append(dict(p, expr=conv, unit='deg', sym=False)); continue
            plist.append(dict(p, expr=conv, unit='mm', sym=True))
        values = {p['name']: p['value'] for p in plist}
        for p in plist:
            if p['unit'] == 'deg': continue
            ev = eval_mm(p['expr'], values)
            if ev is not None and abs(ev - p['value']) < 1e-4 * max(1, abs(p['value'])):
                continue
            if re.fullmatch(r'-?\d+(\.\d+)?', p['expr']):
                p['unit'] = ''; p['sym'] = False
                continue
            self.warnings.append("parameter %s: Fusion expression '%s' kept as its value %s" % (p['name'], p['fexpr'], fmt_len(p['value'])))
            p['expr'] = fmt_len(p['value'])
        PARAM_VALUES = {p['name']: p['value'] for p in plist if p['unit'] == 'mm'}
        ordered, done = [], set()
        pending = list(plist)
        while pending:
            progressed = False
            for p in list(pending):
                deps = refs_in(p['expr']) & set(x['name'] for x in plist)
                if deps <= done:
                    ordered.append(p); done.add(p['name']); pending.remove(p); progressed = True
            if not progressed:
                for p in pending:
                    p['expr'] = fmt_len(p['value']) if p['unit'] == 'mm' else _g(p['value'])
                    ordered.append(p); done.add(p['name'])
                pending = []
        self.param_list = ordered
        REC = Rec(self.py)
        stub = make_stub()
        sys.modules['build123d'] = stub
        sys.modules.setdefault('ocp_vscode', types.SimpleNamespace(show=lambda *a, **k: None))
        ns = {'__name__': 'fusion_export', '__file__': self.py, '__builtins__': __builtins__}
        code = compile(src, self.py, 'exec')
        exec(code, ns)
        self.assembly = ns.get('FUSION_ASSEMBLY')
        self.occ_ctx = {}; self.part_ctx = {}; self.sk_ctx = {}; self.ctx_notes = []
        try:
            for o in (self.assembly or {}).get('occurrences') or []:
                T = o.get('transform')
                if o.get('component') and isinstance(T, (list, tuple)) and len(T) == 16 and not _is_identity(T):
                    self.occ_ctx.setdefault(o['component'], []).append(OccCtx(T))
        except Exception as e:
            self.occ_ctx = {}; self.warnings.append('assembly-context check skipped (%s)' % e)
        self.sketch_only, so_problem = read_sketch_only(ns.get('SKETCH_ONLY'))
        if so_problem: self.errors.append('sketch-only data partly unreadable (%s)' % so_problem)
        for p in ordered:
            if p['sym'] and p['var'] in ns: ns[p['var']] = Sym(p['value'], p['name'], 1, True)
        fn = [v for k, v in ns.items() if k.startswith('build_') and isinstance(v, types.FunctionType) and v.__code__.co_filename == self.py]
        if not fn: raise NotImplementedError('no build_*() function found')
        self.empty = False
        try:
            fn[0]()
        except NameError:
            if not REC.parts:
                self.empty = True
                self.warnings.append('the export contains no geometry (empty build function)')
            else:
                raise
        self.lines = lines; self.apps = apps
        self.param_cmds = []
        for p in ordered:
            prm = {'name': p['name'], 'expression': p['expr'], 'comment': 'From Fusion'}
            if p['unit'] == '': prm['unit'] = ''
            vals = fmt_len(p['value']) if p['unit'] == 'mm' else _g(p['value']) + (' deg' if p['unit'] == 'deg' else '')
            variants = [('as exported', prm)]
            if vals != prm['expression']:
                p2 = dict(prm, expression=vals); variants.append(('its value %s' % vals, p2))
            r = self.simple('parameters.add', variants, 'param:' + p['name'], p['name'])
            if r: self.param_cmds.append(r[0])
        self.emit_ops()
        if getattr(self, 'ctx_notes', None):
            comps = sorted(set(str(c) for c, _, _ in self.ctx_notes))
            nh = sum(1 for _, _, h in self.ctx_notes if h == 'plane origin')
            self.warnings.append('%d sketch(es) were exported in assembly context (world coordinates) and were mapped back into their component before placing occurrences%s: %s'
                                 % (len(self.ctx_notes), (' (%d decided by plane origin only)' % nh) if nh else '', ', '.join(comps)))
        for c in self.param_cmds:
            if c['params']['name'] not in self.used_params:
                c['params']['comment'] = 'From Fusion (unused by features)'
        self.emit_appearances()
        return self.cmds

    def emit_ops(self):
        part_names = {}
        cur_part_ln = 0
        for i, (kind, d, ln) in enumerate(REC.ops):
            if kind == 'part':
                bp = d
                bp.var = var_at(self.lines, ln, 'BuildPart') or 'body'
                bn = body_name_at(self.lines, ln) or 'Body1'
                bp.body = self.uniq_body(bn, part_names)
                bp.component = component_at(self.lines, ln)
                self.pieces[bp] = set(); cur_part_ln = ln
                continue
            feat = feature_name_at(self.lines, ln, cur_part_ln) or kind.capitalize()
            try:
                getattr(self, 'op_' + kind)(d, ln, 'op%d' % i, feat)
            except SketchDropped as e:
                self.errors.append('%s (line %d) left out: its sketch was refused (%s)' % (feat, ln, e))
            except Exception as e:
                self.errors.append('%s (line %d) failed in converter: %s' % (feat, ln, e))

    def body_components(self):
        out = {}
        for bp, bodies in self.pieces.items():
            for b in bodies: out[b] = getattr(bp, 'component', None)
        return out

    def param_report(self):
        return [dict(name=p['name'], expression=p['fexpr'], value=p['value'], wired=p['name'] in self.used_params)
                for p in getattr(self, 'param_list', [])]

    def uniq_body(self, bn, used):
        if bn not in used: used[bn] = 1; return bn
        used[bn] += 1
        n = '%s_%d' % (bn, used[bn])
        while n in used: used[bn] += 1; n = '%s_%d' % (bn, used[bn])
        used[n] = 1
        return n

    def target_args(self, part, op):
        if op == 'new': return {'operation': 'new', 'body_name': part.body}
        return {'operation': op, 'targets': sorted(self.pieces[part])}


    def sketch_context(self, bs, part):
        """OccCtx when sketch bs was exported in assembly (world) context, else None. Cached per sketch."""
        if bs.idx in self.sk_ctx: return self.sk_ctx[bs.idx]
        ctx, how = None, ''
        cands = self.occ_ctx.get(getattr(part, 'component', None)) or []
        if cands:
            pts = [p[:2] for sh in bs.shapes for c in sh.curves for p in sample_curve(c)]
            want = _sketch_bbox_comment(getattr(self, 'lines', None), bs.ln)
            have = _pts_bbox(pts)
            e_id = _bbox_err(have, want)
            best = None
            if e_id is not None:
                for oc in cands:
                    if not oc.ok2d(): continue
                    e = _bbox_err(_pts_bbox([oc.unmap2d(p) for p in pts]), want)
                    if best is None or e < best[0]: best = (e, oc)
            if best is not None:
                size = max(1.0, want[2] - want[0], want[3] - want[1])
                tol = 0.05 + 1e-3 * size
                if best[0] <= tol and e_id > tol: ctx, how = best[1], '2D offset'
                elif e_id <= tol and best[0] > tol: ctx, how = None, ''
                elif e_id > tol and best[0] > tol: best = None
            if best is None or (e_id is not None and e_id <= 0.05 + 1e-3 * max(1.0, want[2] - want[0], want[3] - want[1]) and best[0] <= 0.05 + 1e-3 * max(1.0, want[2] - want[0], want[3] - want[1])):
                # No 2D evidence either way (occurrence moves only along the sketch normal, or no bbox comment):
                # the plane origin decides -- an assembly-context frame carries the occurrence offset.
                o = [float(x) for x in bs.plane.origin]
                n0 = math.sqrt(sum(x * x for x in o)); pick = None
                for oc in cands:
                    n1 = math.sqrt(sum(x * x for x in oc.point(o)))
                    if n1 < n0 - 1e-3 and (pick is None or n1 < pick[0]): pick = (n1, oc)
                if pick: ctx, how = pick[1], 'plane origin'
        self.sk_ctx[bs.idx] = ctx
        if ctx is not None: self.ctx_notes.append((getattr(part, 'component', None), bs.ln, how))
        return ctx

    def _ctx_point(self, part, p):
        oc = self.part_ctx.get(part)
        return oc.point(p) if oc else [r6(float(x)) for x in p]

    def _ctx_vec(self, part, v):
        oc = self.part_ctx.get(part)
        return oc.vec(v) if oc else [r6(float(x)) for x in v]

    def make_sketch(self, skref, feat, part=None):
        bs = skref.bs
        key = (bs.idx, tuple(skref.delta) if skref.delta else None)
        if key in self.sk_names: return self.sk_names[key], bs.picks
        sk = 'sk%d%s' % (bs.idx, ('@' + ','.join(_g(x) for x in skref.delta)) if skref.delta else '')
        ck = sk + ':create'
        if self.fb['level'].get(ck, 0) > 0:
            raise SketchDropped(self.fb['msg'].get(ck, '')[:200])
        pl = bs.plane
        origin = [r6(x) for x in pl.origin]
        if skref.delta: origin = [r6(origin[i] + skref.delta[i]) for i in range(3)]
        xd, yd, shapes = [r6(x) for x in pl.x], [r6(x) for x in pl.y], bs.shapes
        oc = None
        if part is not None:
            try:
                oc = self.sketch_context(bs, part)
            except Exception as e:
                self.warnings.append('assembly-context check failed for sketch at line %d (%s)' % (bs.ln, e)); oc = None
            self.part_ctx[part] = oc
        if oc is not None:
            origin, xd, yd = oc.point(origin), oc.vec(pl.x), oc.vec(pl.y)
            A = oc.R
            aligned = all(abs(A[i][j]) < 1e-6 or abs(abs(A[i][j]) - 1) < 1e-6 for i in range(2) for j in range(2))
            shapes = [_map_shape(sh, oc.unmap2d, aligned) for sh in bs.shapes]
        name = self.uniq('%s Sketch' % feat)
        self.emit('sketch.create', {'plane': {'origin': origin, 'x_dir': xd, 'y_dir': yd}, 'name': name}, ck)
        picks = self.draw_shapes(shapes, sk)
        self.emit('sketch.finish', {}, sk + ':finish', lkey=ck)
        bs.sk_origin = origin
        bs.picks = picks
        self.sk_names[key] = name
        return name, picks

    def draw_shapes(self, shapes, sk):
        n = [0]
        def curve(command, prm):
            n[0] += 1
            self.simple(command, [('as exported', prm)], '%s:c%d' % (sk, n[0]), 'sketch curve in %s' % sk)
        groups = []
        for sh in shapes:
            if sh.mode == 'ADD' or not groups: groups.append([sh])
            else: groups[-1].append(sh)
        all_lines = []
        for sh in shapes:
            for c in sh.curves:
                if c.kind == 'line' and c.pts[0] != c.pts[1]: all_lines.append((c.pts[0][:2], c.pts[1][:2]))
        splits = split_lines(all_lines)
        emitted = set()
        for sh in shapes:
            if sh.rect and all(len(splits[(c.pts[0][:2], c.pts[1][:2])]) == 1 for c in sh.curves) \
                    and not any(lkey(c.pts[0][:2], c.pts[1][:2]) in emitted for c in sh.curves):
                curve('sketch.rectangle.two_point', {'p0': list(sh.rect[0]), 'p1': list(sh.rect[1])})
                for c in sh.curves: emitted.add(lkey(c.pts[0][:2], c.pts[1][:2]))
                continue
            chain = []
            def flush():
                if len(chain) >= 2: curve('sketch.line', {'points': [list(p) for p in chain]})
                chain.clear()
            for c in sh.curves:
                if c.kind == 'line':
                    if c.pts[0] == c.pts[1]: continue
                    for a, b in splits[(c.pts[0][:2], c.pts[1][:2])]:
                        k = lkey(a, b)
                        if k in emitted: flush(); continue
                        emitted.add(k)
                        if chain and chain[-1] == a: chain.append(b)
                        else: flush(); chain.extend([a, b])
                    continue
                flush()
                k = ckey(c)
                if k in emitted: continue
                emitted.add(k)
                if c.kind == 'circle':
                    curve('sketch.circle.center', {'center': list(c.pts[0][:2]), 'radius': c.kw['r']})
                elif c.kind == 'arc':
                    curve('sketch.arc.three_point', {'start': list(c.pts[0][:2]), 'through': list(c.pts[1][:2]), 'end': list(c.pts[2][:2])})
                else:
                    curve('sketch.spline.fit_point', {'points': [list(p[:2]) for p in c.pts]})
            flush()
        picks = []
        for g in groups:
            if g[0].mode != 'ADD': continue
            polys = [loop_polygon(sh.curves) for sh in g if sh.curves]
            if not polys: continue
            pt, clr = interior_point(polys)
            if pt is None: self.warnings.append('could not find a point inside a profile'); continue
            picks.append({'point': [r6(pt[0]), r6(pt[1])]})
        return picks

    def _op_kind(self, part, mode, feat):
        op = {'ADD': 'join', 'SUBTRACT': 'cut', 'INTERSECT': 'intersect'}.get(mode)
        if op is None: raise NotImplementedError('mode %s' % mode)
        if op == 'join' and not self.pieces[part]: op = 'new'
        if op in ('cut', 'intersect') and not self.pieces[part]:
            self.errors.append('%s: %s with no body to act on (skipped)' % (feat, op)); return None
        return op

    def op_extrude(self, d, ln, key, feat):
        part = d['part']; cm = trailing_comment(self.lines, ln)
        op = self._op_kind(part, d['mode'], feat)
        if op is None: return
        sk, picks = self.make_sketch(d['sk'], feat, d['part'])
        if not picks: self.errors.append('%s: sketch has no profiles' % feat); return
        prm = {'sketch': sk, 'profiles': picks, 'exact_regions': True}
        if d['until'] is not None:
            prm['through_all'] = True
            prm['direction'] = 'negative' if 'reversed extrusion direction' in cm else 'positive'
            self.warnings.append('%s: Fusion To-Object/All extent mapped to through-all (%s)' % (feat, prm['direction']))
        else:
            amt = d['amount']
            if amt is None: raise NotImplementedError('extrude without amount')
            if d['both']:
                prm['direction'] = 'symmetric'
                prm['distance'] = (amt * 2).expr if isinstance(amt, Sym) and amt.dim == 1 else fmt_len(2 * float(amt))
                if isinstance(amt, Sym) and float(amt) < 0: prm['distance'] = abs(amt * 2).expr
            else:
                prm['direction'] = 'negative' if float(amt) < 0 else 'positive'
                prm['distance'] = length_expr(amt, cm)
        if d['taper']: prm['taper'] = '%s deg' % _g(float(d['taper']))
        prm['name'] = self.uniq(feat)
        prm.update(self.target_args(part, op))
        self.note_params(prm.get('distance'))
        self.solid('solid.extrude', prm, [
            ('profile points (not exact regions)', lambda p: p.pop('exact_regions', None)),
            ('default profiles (all regions, nested loops as holes)', lambda p: p.pop('profiles', None))], key, part, feat)

    def op_revolve(self, d, ln, key, feat):
        part = d['part']
        op = self._op_kind(part, d['mode'], feat)
        if op is None: return
        sk, picks = self.make_sketch(d['sk'], feat, d['part'])
        if not picks: self.errors.append('%s: sketch has no profiles' % feat); return
        ax = d['axis']; arc = float(d['arc'])
        dirv = list(ax.direction) if arc >= 0 else [r6(-x) for x in ax.direction]
        prm = {'sketch': sk, 'profiles': picks, 'axis': {'origin': self._ctx_point(part, ax.origin), 'dir': self._ctx_vec(part, dirv)}, 'angle': '%s deg' % _g(abs(arc))}
        prm['name'] = self.uniq(feat)
        prm.update(self.target_args(part, op))
        self.solid('solid.revolve', prm, [
            ('default profiles', lambda p: p.pop('profiles', None)),
            ('legacy axis convention', lambda p: p.__setitem__('convention', 'legacy_axis_start'))], key, part, feat)

    def op_sweep(self, d, ln, key, feat):
        part = d['part']
        sk, picks = self.make_sketch(d['sk'], feat, d['part'])
        cs = d['path'].curves
        pts = [p for c in cs for p in c.pts]
        if any(len(p) != 3 for p in pts): raise NotImplementedError('2D sweep path')
        if self.part_ctx.get(part) is not None:
            cs = [_map_curve(c, lambda p: tuple(self._ctx_point(part, p))) for c in cs]
            pts = [p for c in cs for p in c.pts]
        for ax in (2, 1, 0):
            if all(abs(p[ax] - pts[0][ax]) < 1e-6 for p in pts): break
        else: raise NotImplementedError('non-planar sweep path')
        o = [0.0, 0.0, 0.0]; o[ax] = pts[0][ax]
        xd, yd = {2: ([1, 0, 0], [0, 1, 0]), 1: ([1, 0, 0], [0, 0, 1]), 0: ([0, 1, 0], [0, 0, 1])}[ax]
        loc = lambda p: [r6(vdot(vsub(p, o), xd)), r6(vdot(vsub(p, o), yd))]
        pname = self.uniq('%s Path' % feat)
        pk = key + ':path'
        if self.fb['level'].get(pk + ':create', 0) > 0: raise SketchDropped(self.fb['msg'].get(pk + ':create', ''))
        self.emit('sketch.create', {'plane': {'origin': o, 'x_dir': xd, 'y_dir': yd}, 'name': pname}, pk + ':create')
        ids = []; cnt = {'l': 0, 'a': 0, 's': 0}
        for i, c in enumerate(cs):
            if c.kind == 'line': cmd, prm, t = 'sketch.line', {'points': [loc(c.pts[0]), loc(c.pts[1])]}, 'l'
            elif c.kind == 'arc': cmd, prm, t = 'sketch.arc.three_point', {'start': loc(c.pts[0]), 'through': loc(c.pts[1]), 'end': loc(c.pts[2])}, 'a'
            elif c.kind == 'spline': cmd, prm, t = 'sketch.spline.fit_point', {'points': [loc(p) for p in c.pts]}, 's'
            else: raise NotImplementedError('path curve %s' % c.kind)
            if self.fb['level'].get('%s:c%d' % (pk, i), 0) > 0: raise SketchDropped('path curve refused: ' + self.fb['msg'].get('%s:c%d' % (pk, i), ''))
            _, res = self.emit(cmd, prm, '%s:c%d' % (pk, i), lkey=pk + ':create')
            cnt[t] += 1
            got = (res or {}).get('created', {}).get('curves') if isinstance(res, dict) else None
            ids += got if got else ['%s%d' % (t, cnt[t])]
        self.emit('sketch.finish', {}, pk + ':finish', lkey=pk + ':create')
        op = 'join' if self.pieces[part] else 'new'
        prm = {'sketch': sk, 'path_sketch': pname, 'path': ids, 'name': self.uniq(feat)}
        if picks: prm['profiles'] = picks
        prm.update(self.target_args(part, op))
        self.solid('solid.sweep', prm, [('default profiles', lambda p: p.pop('profiles', None))], key, part, feat)

    def op_hole(self, d, ln, key, feat):
        part = d['part']
        if not self.pieces[part]: self.errors.append('%s: hole with no body (skipped)' % feat); return
        loc = d['loc']; r = d['radius']
        if isinstance(r, Sym) and r.dim == 1:
            m = re.fullmatch(r'\((.+)\) / 2|(.+) / 2', r.expr)
            dia = (m.group(1) or m.group(2)) if m else (r * 2).expr
        else:
            dia = fmt_len(2 * float(r))
        prm = {'position': self._ctx_point(part, loc.origin), 'direction': self._ctx_vec(part, [-x for x in loc.zdir]), 'diameter': dia,
               'name': self.uniq(feat), 'targets': sorted(self.pieces[part])}
        if d['depth'] is not None: prm['depth'] = length_expr(d['depth'], None)
        self.note_params(dia, prm.get('depth'))
        self.solid('solid.hole', prm, [], key, part, feat)

    def op_mirror(self, d, ln, key, feat):
        part = d['part']; pl = d['plane']
        if not self.pieces[part]: self.errors.append('%s: mirror with nothing to mirror' % feat); return
        origin = [(o.expr if isinstance(o, Sym) and o.dim == 1 else r6(o)) for o in pl.origin]
        normal = [r6(x) for x in pl.z]
        if self.part_ctx.get(part) is not None:
            origin = self._ctx_point(part, [float(o) for o in pl.origin]); normal = self._ctx_vec(part, pl.z)
        prm = {'bodies': sorted(self.pieces[part]), 'combine': True,
               'plane': {'origin': origin, 'normal': normal}, 'name': self.uniq(feat)}
        self.note_params(*[o for o in origin if isinstance(o, str)])
        self.solid('solid.mirror', prm, [('combine: false (mirror kept as separate bodies)', lambda p: p.__setitem__('combine', False))], key, part, feat)

    def _edge_feature(self, cmd, prm, part, key, feat):
        if not self.pieces[part]: self.errors.append('%s: no body' % feat); return
        if len(self.pieces[part]) == 1: prm['body'] = next(iter(self.pieces[part]))
        if self.part_ctx.get(part) is not None:
            for k in ('edges', 'faces'):
                if isinstance(prm.get(k), list): prm[k] = [self._ctx_point(part, p) for p in prm[k]]
        prm['name'] = self.uniq(feat)
        steps = []
        if cmd == 'solid.fillet':
            steps.append(('fit: reduce (radius reduced where it does not fit)', lambda p: p.__setitem__('fit', 'reduce')))
        self.solid(cmd, prm, steps, key, part, feat)

    def op_fillet(self, d, ln, key, feat):
        rad = length_expr(d['radius'], trailing_comment(self.lines, ln)); self.note_params(rad)
        self._edge_feature('solid.fillet', {'edges': d['edges'], 'radius': rad}, d['part'], key, feat)

    def op_chamfer(self, d, ln, key, feat):
        prm = {'edges': d['edges'], 'distance': length_expr(d['length'], trailing_comment(self.lines, ln))}
        if d['length2'] is not None: prm['distance2'] = length_expr(d['length2'])
        self.note_params(prm['distance'], prm.get('distance2'))
        self._edge_feature('solid.chamfer', prm, d['part'], key, feat)

    def op_shell(self, d, ln, key, feat):
        amt = d['amount']
        prm = {'faces': d['faces'], 'thickness': length_expr(amt, trailing_comment(self.lines, ln)),
               'direction': 'inside' if float(amt) < 0 else 'outside'}
        ctx = '\n'.join(self.lines[max(0, ln - 4):ln])
        if 'tangent-chain' in ctx: prm['tangent_chain'] = True
        self.note_params(prm['thickness'])
        self._edge_feature('solid.shell', prm, d['part'], key, feat)

    def emit_appearances(self):
        groups = {}
        for bp in REC.parts:
            app = self.apps.get(bp.var)
            if not app or not self.pieces.get(bp): continue
            p = appearance_params(app)
            k = json.dumps(p, sort_keys=True)
            groups.setdefault(k, (p, []))[1].extend(sorted(self.pieces[bp]))
        for i, (k, (p, bodies)) in enumerate(groups.items()):
            prm = {'bodies': bodies}; prm.update(p)
            self.simple('appearance.assign', [('as exported', prm)], 'app:%s' % p['name'], 'appearance ' + p['name'])

# ----------------------------------------------------------------------------- sketch-only sketches
def _pt2(p):
    return [r6(float(p[0])), r6(float(p[1]))]

def read_sketch_only(data):
    """Validate the export's SKETCH_ONLY list; returns (entries, problem or None).  Bad entries are dropped."""
    if data is None: return [], None
    if not isinstance(data, (list, tuple)): return [], 'SKETCH_ONLY is not a list'
    out, bad = [], 0
    for e in data:
        try:
            pl = e['plane']
            plane = {'origin': [r6(float(x)) for x in pl['origin']][:3], 'x_dir': [r6(float(x)) for x in pl['x_dir']][:3],
                     'y_dir': [r6(float(x)) for x in pl['y_dir']][:3]}
            if len(plane['origin']) != 3 or len(plane['x_dir']) != 3 or len(plane['y_dir']) != 3: raise ValueError('plane')
            out.append({'name': str(e.get('name') or 'Sketch'), 'partial': bool(e.get('partial')), 'visible': e.get('visible', True) is not False,
                        'component': str(e.get('component') or ''), 'plane': plane, 'curves': list(e.get('curves') or []),
                        'texts': list(e.get('texts') or []), 'points': list(e.get('points') or [])})
        except Exception:
            bad += 1
    return out, ('%d malformed SKETCH_ONLY entr%s skipped' % (bad, 'y' if bad == 1 else 'ies')) if bad else None

TEXT_LINE_FACTOR = 1.6   # assumed line distance / text height for multi-line text

def text_params(t):
    """sketch.text parameters for one Fusion sketch text (centred on its text box)."""
    txt = str(t.get('text') or '')
    h = float(t.get('height') or 5.0)
    ang = float(t.get('rotation') or 0.0)
    cx, cy = (float(t['center'][0]), float(t['center'][1])) if t.get('center') else (0.0, 0.0)
    n = txt.count('\n') + 1
    # first baseline: half a capital height below the box centre, raised by half the extra lines
    off = -h / 2.0 + (n - 1) * TEXT_LINE_FACTOR * h / 2.0
    a = math.radians(ang)
    at = [r6(cx - off * math.sin(a)), r6(cy + off * math.cos(a))]
    p = {'text': txt, 'at': at, 'height': r6(h), 'align': 'center'}
    if abs(ang) > 1e-9: p['angle'] = r6(ang)
    return p, n

def _ellipse_samples(c, n=48):
    cx, cy = float(c['center'][0]), float(c['center'][1]); A = float(c['major_radius']); B = float(c['minor_radius'])
    rot = math.radians(float(c.get('rotation') or 0.0)); out = []
    for i in range(n):
        t = 2 * math.pi * i / n; ex, ey = A * math.cos(t), B * math.sin(t)
        out.append([r6(cx + ex * math.cos(rot) - ey * math.sin(rot)), r6(cy + ex * math.sin(rot) + ey * math.cos(rot))])
    return out

def _curve_variants(c):
    """[(label, command, params)] for one SKETCH_ONLY curve, best first."""
    k = c.get('type')
    if k == 'line':
        return [('as exported', 'sketch.line', {'points': [_pt2(p) for p in c['points'][:2]]})]
    if k == 'arc':
        a, b, e = [_pt2(p) for p in c['points'][:3]]
        if arc_center(tuple(a), tuple(b), tuple(e)) is None:
            return [('straight (degenerate arc)', 'sketch.line', {'points': [a, e]})]
        return [('as exported', 'sketch.arc.three_point', {'start': a, 'through': b, 'end': e})]
    if k == 'circle':
        return [('as exported', 'sketch.circle.center', {'center': _pt2(c['center']), 'radius': r6(float(c['radius']))})]
    if k == 'ellipse':
        samp = _ellipse_samples(c)
        return [('as exported', 'sketch.ellipse', {'center': _pt2(c['center']), 'major': _pt2(c['major_point']), 'minor_radius': r6(float(c['minor_radius']))}),
                ('fit-point spline through 48 points of the ellipse', 'sketch.spline.fit_point', {'points': samp, 'periodic': True}),
                ('48-segment polyline approximation of the ellipse', 'sketch.line', {'points': samp + [samp[0]]})]
    if k == 'spline':
        pts = [_pt2(p) for p in c['points']]
        if len(pts) > 500: pts = [pts[int(round(i * (len(pts) - 1) / 499.0))] for i in range(500)]
        if len(pts) < 2: raise ValueError('spline with fewer than 2 points')
        closed = bool(c.get('closed'))
        v = []
        if closed and len(pts) >= 3:
            v.append(('as exported (closed)', 'sketch.spline.fit_point', {'points': pts, 'periodic': True}))
            v.append(('open fit-point spline closed on its first point', 'sketch.spline.fit_point', {'points': pts + [pts[0]]}))
            v.append(('polyline approximation', 'sketch.line', {'points': pts + [pts[0]]}))
        else:
            v.append(('as exported', 'sketch.spline.fit_point', {'points': pts}))
            v.append(('polyline approximation', 'sketch.line', {'points': pts}))
        return v
    raise ValueError('unknown curve type %r' % k)

def sketch_only_cmds(entries, fb, taken):
    """Command list (with repair keys, as Converter.emit makes them) for the sketch-only sketches.
    Returns (cmds, errors, warnings, placed sketch names)."""
    cmds, errors, warnings, placed = [], [], [], []
    names = set(taken)
    def uniq(n):
        base, k = n, 2
        while n in names: n = '%s (%d)' % (base, k); k += 1
        names.add(n); return n
    def add(command, params, key, lkey=None):
        cmds.append({'command': command, 'params': params, 'key': key, 'lkey': lkey or key, 'solid': False, 'actual': False})
    def pick(variants, key, what):
        lvl = fb['level'].get(key, 0)
        if lvl >= len(variants):
            errors.append('sketch-only %s refused by SolidCraft, left out: %s' % (what, fb['msg'].get(key, '')[:200])); return None
        if lvl: warnings.append('sketch-only %s: first attempt refused (%s); used %s' % (what, fb['msg0'].get(key, '')[:160], variants[lvl][0]))
        return variants[lvl]
    for i, e in enumerate(entries):
        base = 'so%d' % i
        disp = e['name'] + (' (unused geometry)' if e['partial'] else '')
        ck = base + ':create'
        if fb['level'].get(ck, 0) > 0:
            errors.append("sketch-only sketch '%s' left out: SolidCraft refused it (%s)" % (disp, fb['msg'].get(ck, '')[:200])); continue
        try:
            name = uniq(disp)
            body = []   # (command, params, key) inside the sketch
            # curves: consecutive connected lines are drawn as one polyline
            chain, chain_keys = [], []
            def flush():
                if len(chain) >= 2:
                    key = '%s:l%d' % (base, len(body))
                    v = pick([('as exported', 'sketch.line', {'points': [list(p) for p in chain]})], key, "lines in '%s'" % name)
                    if v: body.append((v[1], v[2], key))
                chain.clear()
            for j, c in enumerate(e['curves']):
                try:
                    variants = _curve_variants(c)
                except Exception as ex:
                    flush(); errors.append("sketch-only curve %d in '%s' left out: %s" % (j + 1, name, ex)); continue
                if c.get('type') == 'line' and len(variants) == 1 and variants[0][1] == 'sketch.line':
                    a, b = variants[0][2]['points']
                    if a == b: continue
                    if chain and chain[-1] == a and len(chain) < 200: chain.append(b)
                    else: flush(); chain.extend([a, b])
                    continue
                flush()
                key = '%s:c%d' % (base, j)
                v = pick(variants, key, "%s in '%s'" % (c.get('type'), name))
                if v: body.append((v[1], v[2], key))
            flush()
            for j, t in enumerate(e['texts']):
                try:
                    tp, nlines = text_params(t)
                except Exception as ex:
                    errors.append("sketch-only text %d in '%s' left out: %s" % (j + 1, name, ex)); continue
                if not tp['text'].strip(): continue
                label = "text %r in '%s'" % (tp['text'][:40], name)
                font = str(t.get('font') or '').strip()
                v1 = dict(tp)
                if font: v1['font'] = font
                if t.get('bold'): v1['bold'] = True
                if t.get('italic'): v1['italic'] = True
                variants = [('as exported', v1)]
                v2 = dict(v1); v2.pop('bold', None); v2.pop('italic', None)
                if v2 != v1: variants.append(('font without bold/italic', v2))
                if font: variants.append(("SolidCraft's built-in font (font %r not available)" % font, dict(tp)))
                key = '%s:t%d' % (base, j)
                v = pick([(lab, 'sketch.text', prm) for lab, prm in variants], key, label)
                if v:
                    body.append((v[1], v[2], key))
                    notes = []
                    if nlines > 1: notes.append('multi-line: line spacing approximated')
                    if t.get('on_path'): notes.append('Fusion text on a path: placed straight at its centre')
                    if t.get('flip_h') or t.get('flip_v'): notes.append('Fusion text was flipped (mirrored); not replicated')
                    if t.get('underline'): notes.append('underline not replicated')
                    if notes: warnings.append('sketch-only %s: %s' % (label, '; '.join(notes)))
            for j, p in enumerate(e['points']):
                key = '%s:p%d' % (base, j)
                v = pick([('as exported', 'sketch.point', {'point': _pt2(p)})], key, "point in '%s'" % name)
                if v: body.append((v[1], v[2], key))
            if not body:
                errors.append("sketch-only sketch '%s' left out: none of its curves/text could be placed" % disp); continue
            add('sketch.create', {'plane': e['plane'], 'name': name}, ck)
            for command, params, key in body: add(command, params, key)
            add('sketch.finish', {}, base + ':finish', lkey=ck)
            if not e['visible']:
                hk = base + ':hide'
                if fb['level'].get(hk, 0) == 0: add('browser.visibility', {'visible': False, 'items': [name]}, hk)
                else: warnings.append("sketch-only sketch '%s' is hidden in Fusion but could not be hidden (%s)" % (name, fb['msg'].get(hk, '')[:120]))
            placed.append(name)
        except Exception as ex:
            errors.append("sketch-only sketch '%s' left out: converter error %s: %s" % (disp, type(ex).__name__, ex))
    return cmds, errors, warnings, placed

def add_sketch_only(entries, taken, cli, work, sc_tmp, t_end):
    """Second step of convert_one: put the sketch-only sketches on top of the converted design (sc_tmp).
    Never raises; sc_tmp is only replaced when the whole step succeeded.  Returns (placed names, errors, warnings, runs)."""
    if not entries: return [], [], [], 0
    fb = new_feedback(); runs = 0; last_err = []
    js = os.path.join(work, 'sketches.solidcraft.json'); sc2 = os.path.join(work, 'out_sketches.sc')
    try:
        for _ in range(60):
            cmds, errors, warnings, placed = sketch_only_cmds(entries, fb, taken)
            last_err = errors
            if not cmds:
                return [], errors, warnings, runs
            if t_end - time.time() < 5:
                return [], errors + ['sketch-only sketches left out: not enough time left in the per-file limit'], warnings, runs
            write_script(js, cmds)
            if os.path.exists(sc2): os.remove(sc2)
            rc, so, se = run_cli(cli, ['run', js, '--in', sc_tmp, '--save', sc2, '--param-check', 'off'], t_end); runs += 1
            if rc == 0 and os.path.exists(sc2):
                shutil.copyfile(sc2, sc_tmp)
                return placed, errors, warnings, runs
            m = STEP_RE.search(se) or STEP_RE.search(so)
            if not m or not (1 <= int(m.group(1)) <= len(cmds)):
                tail = ((se or so).strip().splitlines() or ['exit %s' % rc])[-1][:240]
                return [], errors + ['sketch-only sketches left out: solidcraft-cli failed (%s)' % tail], warnings, runs
            bad = cmds[int(m.group(1)) - 1]; msg = m.group(3).strip(); k = bad['lkey']
            fb['level'][k] = fb['level'].get(k, 0) + 1
            fb['msg0'].setdefault(k, '%s: %s' % (bad['command'], msg)); fb['msg'][k] = msg
        return [], last_err + ['sketch-only sketches left out: gave up after 60 repair passes'], [], runs
    except TimeoutError:
        return [], last_err + ['sketch-only sketches left out: time limit reached'], [], runs
    except Exception as ex:
        return [], last_err + ['sketch-only sketches left out: %s: %s' % (type(ex).__name__, ex)], [], runs

# ----------------------------------------------------------------------------- subprocess helpers
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
NEWGRP = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)

def kill_tree(p):
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True, timeout=30, creationflags=NOWIN)
    except Exception:
        pass
    try: p.kill()
    except Exception: pass
    try: p.wait(10)
    except Exception: pass

def run_cli(cli, args, t_end):
    """solidcraft-cli with a hard deadline; the process tree is killed when it runs over."""
    left = t_end - time.time()
    if left <= 1: raise TimeoutError('time limit reached')
    p = subprocess.Popen([cli] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                         creationflags=NOWIN | NEWGRP)
    try:
        so, se = p.communicate(timeout=left)
    except subprocess.TimeoutExpired:
        kill_tree(p)
        raise TimeoutError('solidcraft-cli %s did not finish within the time limit' % args[0])
    return p.returncode, so.decode('utf-8', 'replace'), se.decode('utf-8', 'replace')

def write_script(path, cmds):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'commands': [{'command': c['command'], 'params': c['params']} for c in cmds]}, f, indent=2)

def load_results(path, n):
    try:
        d = json.load(open(path, encoding='utf-8-sig'))
    except Exception:
        return None
    if isinstance(d, dict): d = d.get('results', d.get('steps'))
    if not isinstance(d, list) or len(d) != n: return None
    return d

def record(cmds, results, fb):
    """Store results as feedback; True when a predicted body list was wrong."""
    mism = False
    for c, r in zip(cmds, results):
        fb['res'][c['key']] = (phash(c['command'], c['params']), r)
        if c.get('solid') and isinstance(r, dict) and isinstance(r.get('bodies'), list):
            if sorted(r['bodies']) != c.get('pred_all'): mism = True
    return mism

STEP_RE = re.compile(r'step (\d+) \(([^)]*)\):\s*(.*)')

def convert_one(py, cli, work, seconds):
    """Child-process work: returns the report entry; out.sc is left in work."""
    t_end = time.time() + seconds
    name = os.path.splitext(os.path.basename(py))[0]
    js = os.path.join(work, name + '.solidcraft.json')
    resj = os.path.join(work, 'results.json')
    sc_tmp = os.path.join(work, 'out.sc')
    fb = new_feedback()
    passes = 0; runs = 0
    while True:
        passes += 1
        if passes > 80: raise RuntimeError('gave up after 80 repair passes')
        c = Converter(py, fb)
        cmds = c.convert()
        write_script(js, cmds)
        for f in (sc_tmp, resj):
            if os.path.exists(f): os.remove(f)
        rc, so, se = run_cli(cli, ['run', js, '--save', sc_tmp, '--param-check', 'warn', '--results', '--json-out', resj], t_end); runs += 1
        if rc == 0 and os.path.exists(sc_tmp):
            res = load_results(resj, len(cmds))
            if res is not None and record(cmds, res, fb):
                continue
            n_geom = sum(1 for x in cmds if x['command'].startswith('solid.'))
            if not c.empty and n_geom == 0:
                raise RuntimeError('no geometry feature could be converted (%s)' % ('; '.join(c.errors[:3]) or 'nothing recorded'))
            bodies = None
            if res is not None:
                for r in res:
                    if isinstance(r, dict) and isinstance(r.get('bodies'), list): bodies = r['bodies']
            pc = [l.strip() for l in se.splitlines() if l.strip() and 'param' in l.lower()]
            # second step: sketch-only sketches on top of the saved design (never fails the file)
            so_found = len(c.sketch_only or [])
            placed, so_err, so_warn, so_runs = add_sketch_only(c.sketch_only or [], c.names, cli, work, sc_tmp, t_end)
            runs += so_runs
            fin = finish_design(cli, work, sc_tmp, t_end, c.design, py, c.assembly, c.body_components())
            runs += fin['runs']
            st = 'converted' + (' (empty design: parameters only)' if c.empty and not placed else ' (empty design: sketches only)' if c.empty else '')
            return dict(status=st, method='parametric JSON (solidcraft-cli run --save)', body_count=len(bodies) if bodies is not None else (0 if c.empty else None),
                        bodies=bodies, errors=c.errors + so_err + fin['errors'], warnings=c.warnings + pc[:20] + so_warn + fin['warnings'],
                        unsupported=c.notes, passes=passes, runs=runs,
                        sketch_only_found=so_found, sketch_only_placed=len(placed), sketch_only_names=placed,
                        sc_bodies=fin['sc_bodies'], sc_components=fin['sc_components'], assembly=fin['assembly'],
                        py_bodies=len(REC.parts), params=c.param_report())
        m = STEP_RE.search(se) or STEP_RE.search(so)
        if not m:
            raise RuntimeError('solidcraft-cli run failed: ' + ((se or so).strip().splitlines() or ['(no output)'])[-1][:300])
        n = int(m.group(1)); msg = m.group(3).strip()
        if not (1 <= n <= len(cmds)):
            raise RuntimeError('solidcraft-cli run failed: ' + m.group(0)[:300])
        bad = cmds[n - 1]
        prefix = cmds[:n - 1]
        if any(x.get('solid') and not x['actual'] for x in prefix):
            pj = os.path.join(work, 'prefix.solidcraft.json'); write_script(pj, prefix)
            if os.path.exists(resj): os.remove(resj)
            rc2, _, _ = run_cli(cli, ['run', pj, '--results', '--json-out', resj, '--param-check', 'off'], t_end); runs += 1
            if rc2 == 0:
                res = load_results(resj, len(prefix))
                if res is not None and record(prefix, res, fb):
                    continue      # body names were mispredicted: regenerate before blaming the command
        k = bad['lkey']
        fb['level'][k] = fb['level'].get(k, 0) + 1
        fb['msg0'].setdefault(k, '%s: %s' % (bad['command'], msg)); fb['msg'][k] = msg

def convert_step(step, cli, work, seconds):
    """Child-process work for a .step/.stp file: geometry import via solidcraft-cli run <file> --save."""
    t_end = time.time() + seconds
    sc_tmp = os.path.join(work, 'out.sc')
    rc, so, se = run_cli(cli, ['run', step, '--save', sc_tmp], t_end)
    if rc != 0 or not os.path.exists(sc_tmp):
        raise RuntimeError('STEP import failed: ' + ((se or so).strip().splitlines() or ['exit %s' % rc])[-1][:300])
    fin = finish_design(cli, work, sc_tmp, t_end, os.path.splitext(os.path.basename(step))[0], step)
    return dict(status='converted', method='STEP import (solidcraft-cli run <file> --save; geometry only)', body_count=fin['sc_bodies'],
                errors=fin['errors'], warnings=fin['warnings'], unsupported=[], passes=1, runs=1 + fin['runs'],
                sc_bodies=fin['sc_bodies'], sc_components=fin['sc_components'])

def child_main(a):
    work = a.work
    out = os.path.join(work, 'result.json')
    try:
        if a.child.lower().endswith(STEP_EXT):
            entry = convert_step(a.child, a.cli, work, a.seconds)
        else:
            entry = convert_one(a.child, a.cli, work, a.seconds)
    except TimeoutError as e:
        entry = dict(status='FAILED', reason='timeout (%s)' % e, errors=['timeout: %s' % e])
    except Exception as e:
        traceback.print_exc()
        entry = dict(status='FAILED', reason='%s: %s' % (type(e).__name__, e), errors=['conversion failed: %s: %s' % (type(e).__name__, e)])
    with open(out, 'w', encoding='utf-8') as f: json.dump(entry, f, indent=2)
    return 0

# ----------------------------------------------------------------------------- snapshots (pictures)
def parse_views(s):
    out = []
    for v in (s or '').split(','):
        v = v.strip()
        if v and v.lower() not in [x.lower() for x in out]: out.append(v)
    return out or ['iso']

def _view_part(v):
    return re.sub(r'[\\/:*?"<>|]+', '_', v)

def raw_base(inp):
    """Raw-haul base path of a design: <Fusion exports tree folder>\\<name> (no extension)."""
    return os.path.splitext(os.path.abspath(inp))[0]

def snapshot_paths(base, views):
    """[(view, png)] for SolidCraft pictures in the raw-haul folder: <name>_solidcraft.png for one view,
    <name>_solidcraft_<view>.png for several (Fusion's own pictures are <name>_<view>.png)."""
    if len(views) == 1: return [(views[0], base + '_solidcraft.png')]
    return [(v, '%s_solidcraft_%s.png' % (base, _view_part(v))) for v in views]

def take_snapshots(sc, base, views, cli, seconds, only_missing=False, tmpdir=None):
    """solidcraft-cli snapshot for every view, all within `seconds` (process tree killed on timeout).
    Each picture goes to a temp file first.  Never raises; returns [{view, png, status, error?}]."""
    out = []
    if os.path.basename(sc).lower() == 'bathroom mirrors.sc': return out
    t_end = time.time() + seconds
    tmpdir = tmpdir or tempfile.gettempdir()
    for v, png in snapshot_paths(base, views):
        if only_missing and os.path.exists(png):
            out.append(dict(view=v, png=png, status='skipped (exists)')); continue
        tmp = os.path.join(tmpdir, 'snap_%d_%s.png' % (os.getpid(), _view_part(v)))
        try:
            if os.path.exists(tmp): os.remove(tmp)
            rc, so, se = run_cli(cli, ['snapshot', '--in', sc, '--out', tmp, '--view', v,
                                       '--width', str(SNAP_W), '--height', str(SNAP_H)], t_end)
            if rc != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
                raise RuntimeError('solidcraft-cli snapshot failed: ' + one_line(((se or so).strip().splitlines() or ['exit %s' % rc])[-1]))
            shutil.copyfile(tmp, png)
            out.append(dict(view=v, png=png, status='ok'))
        except Exception as e:
            out.append(dict(view=v, png=png, status='failed', error=one_line('%s: %s' % (type(e).__name__, e))))
        finally:
            try:
                if os.path.exists(tmp): os.remove(tmp)
            except Exception: pass
    return out

# ----------------------------------------------------------------------------- meshes, GLB, 3D viewer
from array import array as _array
_UNIT3MF = {'micron': 0.001, 'millimeter': 1.0, 'centimeter': 10.0, 'inch': 25.4, 'foot': 304.8, 'meter': 1000.0}

def _hexcol(c):
    try:
        c = (c or '').strip().lstrip('#')
        if len(c) >= 6:
            return [int(c[0:2], 16) / 255.0, int(c[2:4], 16) / 255.0, int(c[4:6], 16) / 255.0]
    except Exception: pass
    return None

def _m3(t):
    """3MF transform attribute -> 4x3 rows (row-vector convention)."""
    if not t: return None
    v = [float(x) for x in t.split()]
    if len(v) != 12: return None
    return [v[0:3], v[3:6], v[6:9], v[9:12]]

def _mmul3(a, b):
    """apply a then b (row vectors)."""
    if a is None: return b
    if b is None: return a
    r = [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    t = [sum(a[3][k] * b[k][j] for k in range(3)) + b[3][j] for j in range(3)]
    return r + [t]

def read_3mf(path):
    """Meshes of a 3MF file (build items, components and production-extension parts), in mm:
    [{name, color, pos: array('f'), idx: array('I')}]."""
    import zipfile, xml.etree.ElementTree as ET
    PNS = '{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}path'
    z = zipfile.ZipFile(path)
    names = z.namelist()
    lower = {n.lower(): n for n in names}
    models = {}
    def load(p):
        key = p.lstrip('/').lower()
        if key in models: return models[key]
        t = ET.fromstring(z.read(lower[key]))
        objs, mats = {}, {}
        for el in t.iter():
            tag = el.tag.split('}')[-1]
            if tag in ('basematerials', 'colorgroup'):
                mats[el.get('id')] = [_hexcol(b.get('displaycolor') or b.get('color')) for b in el]
            elif tag == 'object':
                objs[el.get('id')] = el
        models[key] = (objs, mats, _UNIT3MF.get(t.get('unit', 'millimeter'), 1.0))
        return models[key]
    root_key = '3d/3dmodel.model' if '3d/3dmodel.model' in lower else next(n for n in lower if n.endswith('.model'))
    out = []
    def color_of(el, mats):
        pid = el.get('pid'); pi = el.get('pindex')
        if pid in mats and mats[pid]:
            try: return mats[pid][int(pi or 0)]
            except Exception: return mats[pid][0]
        return None
    def emit(key, oid, M, depth=0):
        if depth > 16: return
        objs, mats, scale = load(key)
        el = objs.get(oid)
        if el is None: return
        mesh = comps = None
        for ch in el:
            tag = ch.tag.split('}')[-1]
            if tag == 'mesh': mesh = ch
            elif tag == 'components': comps = ch
        if mesh is not None:
            pos = _array('f'); idx = _array('I'); col = color_of(el, mats)
            verts = None; tris = None
            for ch in mesh:
                tag = ch.tag.split('}')[-1]
                if tag == 'vertices': verts = ch
                elif tag == 'triangles': tris = ch
            if verts is None or tris is None: return
            for v in verts:
                x, y, zz = float(v.get('x')) * scale, float(v.get('y')) * scale, float(v.get('z')) * scale
                if M is not None:
                    x, y, zz = (x * M[0][0] + y * M[1][0] + zz * M[2][0] + M[3][0] * scale,
                                x * M[0][1] + y * M[1][1] + zz * M[2][1] + M[3][1] * scale,
                                x * M[0][2] + y * M[1][2] + zz * M[2][2] + M[3][2] * scale)
                pos.extend((x, y, zz))
            for tr in tris:
                idx.extend((int(tr.get('v1')), int(tr.get('v2')), int(tr.get('v3'))))
                if col is None and tr.get('pid') in mats:
                    try: col = mats[tr.get('pid')][int(tr.get('p1') or 0)]
                    except Exception: pass
            out.append(dict(name=el.get('name') or ('object %s' % oid), color=col, pos=pos, idx=idx))
        if comps is not None:
            for c in comps:
                emit((c.get(PNS) or key), c.get('objectid'), _mmul3(_m3(c.get('transform')), M), depth + 1)
    objs, mats, scale = load(root_key)
    rt = ET.fromstring(z.read(lower[root_key]))
    for it in rt.iter():
        if it.tag.split('}')[-1] == 'item':
            emit(it.get(PNS) or root_key, it.get('objectid'), _m3(it.get('transform')))
    return out

def read_stl(path):
    import struct
    data = open(path, 'rb').read()
    pos = _array('f')
    if len(data) >= 84 and 84 + 50 * struct.unpack('<I', data[80:84])[0] == len(data):
        n = struct.unpack('<I', data[80:84])[0]
        for i in range(n):
            pos.extend(struct.unpack_from('<9f', data, 84 + 50 * i + 12))
    else:
        for m in re.finditer(rb'vertex\s+(\S+)\s+(\S+)\s+(\S+)', data):
            pos.extend(float(x) for x in m.groups())
    idx = _array('I', range(len(pos) // 3))
    return [dict(name=os.path.basename(path), color=None, pos=pos, idx=idx)]

def read_obj(path):
    pos = _array('f'); idx = _array('I'); vs = []
    for line in open(path, encoding='utf-8', errors='replace'):
        if line.startswith('v '):
            vs.append([float(x) for x in line.split()[1:4]])
        elif line.startswith('f '):
            ids = []
            for t in line.split()[1:]:
                k = int(t.split('/')[0]); ids.append(k - 1 if k > 0 else len(vs) + k)
            for j in range(1, len(ids) - 1):
                idx.extend((ids[0], ids[j], ids[j + 1]))
    for v in vs: pos.extend(v)
    return [dict(name=os.path.basename(path), color=None, pos=pos, idx=idx)]

def read_mesh(path):
    low = path.lower()
    if low.endswith('.3mf'): return read_3mf(path)
    if low.endswith('.stl'): return read_stl(path)
    if low.endswith('.obj'): return read_obj(path)
    raise ValueError('unknown mesh type')

def write_glb(meshes, path):
    """Minimal glTF 2.0 binary: one node/mesh per input mesh (positions + indices, base colour), mm, Z up."""
    import struct
    bins, views, accs, gmeshes, mats, nodes = [], [], [], [], [], []
    off = 0
    def add(b, target):
        nonlocal off
        views.append({'buffer': 0, 'byteOffset': off, 'byteLength': len(b), 'target': target})
        bins.append(b); off += len(b)
        pad = (-off) % 4
        if pad: bins.append(b'\0' * pad); off += pad
        return len(views) - 1
    for m in meshes:
        pos, idx = m['pos'], m['idx']
        n = len(pos) // 3
        if n == 0 or len(idx) == 0: continue
        if sys.byteorder != 'little':
            pos = _array('f', pos); pos.byteswap(); idx = _array('I', idx); idx.byteswap()
        mn = [min(m['pos'][k::3]) for k in range(3)]; mx = [max(m['pos'][k::3]) for k in range(3)]
        vp = add(pos.tobytes(), 34962); vi = add(idx.tobytes(), 34963)
        accs.append({'bufferView': vp, 'componentType': 5126, 'count': n, 'type': 'VEC3', 'min': mn, 'max': mx})
        accs.append({'bufferView': vi, 'componentType': 5125, 'count': len(idx), 'type': 'SCALAR'})
        c = m.get('color') or [0.72, 0.74, 0.78]
        mats.append({'pbrMetallicRoughness': {'baseColorFactor': [c[0], c[1], c[2], 1.0], 'metallicFactor': 0.0, 'roughnessFactor': 0.75}, 'doubleSided': True})
        gmeshes.append({'name': str(m.get('name') or 'mesh'), 'primitives': [{'attributes': {'POSITION': len(accs) - 2}, 'indices': len(accs) - 1, 'material': len(mats) - 1}]})
        nodes.append({'mesh': len(gmeshes) - 1, 'name': str(m.get('name') or 'mesh')})
    if not nodes: raise ValueError('no triangles')
    gl = {'asset': {'version': '2.0', 'generator': 'py_to_solidcraft'}, 'scene': 0, 'scenes': [{'nodes': list(range(len(nodes)))}],
          'nodes': nodes, 'meshes': gmeshes, 'materials': mats, 'accessors': accs, 'bufferViews': views, 'buffers': [{'byteLength': off}]}
    js = json.dumps(gl, separators=(',', ':')).encode('utf-8'); js += b' ' * ((-len(js)) % 4)
    bn = b''.join(bins)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bn)))
        f.write(struct.pack('<II', len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack('<II', len(bn), 0x004E4942)); f.write(bn)
    os.replace(tmp, path)
    return sum(len(m['idx']) // 3 for m in meshes)

def fusion_mesh_source(base):
    for ext in ('.3mf', '.obj', '.stl'):
        if os.path.exists(base + ext): return base + ext
    return None

def make_fusion_glb(base):
    """<base>_fusion.glb from the Fusion .3mf (else .obj, .stl) when that is newer.  Returns (path|None, note)."""
    src = fusion_mesh_source(base)
    glb = base + '_fusion.glb'
    if not src: return (glb if os.path.exists(glb) else None), 'no Fusion .3mf/.obj/.stl exported yet'
    if os.path.exists(glb) and os.path.getmtime(glb) >= os.path.getmtime(src): return glb, 'up to date'
    tris = write_glb(read_mesh(src), glb)
    return glb, 'from %s (%d triangles)' % (os.path.basename(src), tris)

def make_solidcraft_glb(sc, base, cli, seconds, tmpdir=None):
    """<base>_solidcraft.glb from the .sc (file.export 3mf to a temp file; the .sc is only read)."""
    glb = base + '_solidcraft.glb'
    tmpdir = tmpdir or tempfile.gettempdir()
    t3 = os.path.join(tmpdir, 'sc_mesh_%d.3mf' % os.getpid()); js = os.path.join(tmpdir, 'sc_mesh_%d.json' % os.getpid())
    try:
        with open(js, 'w', encoding='utf-8') as f:
            json.dump({'commands': [{'command': 'file.export', 'params': {'path': t3, 'format': '3mf', 'quality': 'fine'}}]}, f)
        if os.path.exists(t3): os.remove(t3)
        rc, so, se = run_cli(cli, ['run', js, '--in', sc, '--param-check', 'off'], time.time() + seconds)
        if rc != 0 or not os.path.exists(t3):
            raise RuntimeError('solidcraft-cli file.export failed: ' + one_line(((se or so).strip().splitlines() or ['exit %s' % rc])[-1]))
        tris = write_glb(read_3mf(t3), glb)
        return glb, '%d triangles' % tris
    finally:
        for f in (t3, js):
            try:
                if os.path.exists(f): os.remove(f)
            except Exception: pass

VIEWER_LIBS = ('three.min.js', 'OrbitControls.js', 'GLTFLoader.js')

def write_viewer(base, title, fusion_glb, sc_glb, out_path=None):
    """<base>_viewer.html: self-contained (classic scripts, three.js r147 + GLTFLoader + OrbitControls inlined,
    both GLBs base64-inlined); works from file:// in any modern browser, no server or CDN."""
    import base64, html as _h
    vdir = os.path.join(TOOLS, 'viewer')
    libs = []
    for n in VIEWER_LIBS:
        with open(os.path.join(vdir, n), encoding='utf-8') as f:
            libs.append('<script>\n%s\n</script>' % f.read().replace('</script', '<\\/script'))
    def b64(p):
        if not p or not os.path.exists(p): return ''
        with open(p, 'rb') as f: return base64.b64encode(f.read()).decode('ascii')
    data = json.dumps({'fusion': b64(fusion_glb), 'sc': b64(sc_glb)})
    page = VIEWER_HTML.replace('@@TITLE@@', _h.escape(title)).replace('@@LIBS@@', '\n'.join(libs)).replace('@@DATA@@', data)
    out_path = out_path or (base + '_viewer.html')
    tmp = out_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: f.write(page)
    os.replace(tmp, out_path)
    return out_path

VIEWER_HTML = r'''<!DOCTYPE html>
<html lang="en" translate="no"><head><meta charset="utf-8"><meta name="google" content="notranslate">
<title>@@TITLE@@ - 3D viewer</title>
<style>
html,body{margin:0;height:100%;overflow:hidden;font-family:Segoe UI,Arial,sans-serif;background:#eceff3}
#bar{height:42px;display:flex;align-items:center;gap:8px;padding:0 12px;background:#20242b;color:#eee;font-size:14px}
#bar button{background:#3a4150;color:#fff;border:0;border-radius:4px;padding:6px 10px;cursor:pointer}
#bar button.on{background:#2f7bd8}#bar .hint{margin-left:auto;color:#aab}
#panes{position:absolute;top:42px;bottom:0;left:0;right:0;display:flex}
.pane{flex:1;position:relative;border-left:2px solid #c8ccd2;min-width:0}.pane canvas{display:block}
.pane h3{position:absolute;margin:8px 12px;font-size:15px;z-index:2;color:#223;background:rgba(255,255,255,.7);padding:2px 8px;border-radius:4px}
.pane .msg{position:absolute;top:45%;width:100%;text-align:center;color:#667;font-size:15px;padding:0 20px;box-sizing:border-box}
</style></head><body>
<div id="bar"><b>@@TITLE@@</b>
<button data-m="both" class="on">Side by side</button><button data-m="fusion">Fusion 360 only</button><button data-m="sc">SolidCraft only</button>
<button id="wire">Wireframe</button><button id="fit">Fit view</button><span class="hint">drag: rotate &middot; right-drag: pan &middot; wheel: zoom</span></div>
<div id="panes"><div class="pane" id="p_fusion"><h3>Fusion 360 (exported mesh)</h3></div><div class="pane" id="p_sc"><h3>SolidCraft (converted .sc)</h3></div></div>
@@LIBS@@
<script>
var DATA=@@DATA@@;
window.viewerStatus={loaded:0,errors:[],panes:0};
function b64buf(s){var b=atob(s),n=b.length,u=new Uint8Array(n);for(var i=0;i<n;i++)u[i]=b.charCodeAt(i);return u.buffer;}
var panes=[],wire=false;
function Pane(id,key,missing){
  var el=document.getElementById(id);this.el=el;this.obj=null;
  if(!DATA[key]){var m=document.createElement('div');m.className='msg';m.textContent=missing;el.appendChild(m);return;}
  var r=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});r.setPixelRatio(window.devicePixelRatio||1);r.setClearColor(0xf7f8fa);
  el.appendChild(r.domElement);this.r=r;
  var s=new THREE.Scene();this.s=s;
  s.add(new THREE.HemisphereLight(0xffffff,0x8a8f99,0.85));
  var d=new THREE.DirectionalLight(0xffffff,0.75);d.position.set(1,-1.5,2);s.add(d);
  var d2=new THREE.DirectionalLight(0xffffff,0.35);d2.position.set(-1.5,1,0.5);s.add(d2);
  var c=new THREE.PerspectiveCamera(35,1,1,1e7);c.up.set(0,0,1);this.c=c;
  var ctl=new THREE.OrbitControls(c,r.domElement);ctl.enableDamping=false;this.ctl=ctl;
  var self=this;ctl.addEventListener('change',function(){self.draw();});
  window.viewerStatus.panes++;
  try{
    new THREE.GLTFLoader().parse(b64buf(DATA[key]),'',function(g){
      g.scene.traverse(function(o){if(o.isMesh){if(!o.geometry.attributes.normal)o.geometry.computeVertexNormals();
        o.material.flatShading=true;o.material.needsUpdate=true;}});
      s.add(g.scene);self.obj=g.scene;self.fit();window.viewerStatus.loaded++;},
      function(e){window.viewerStatus.errors.push(String(e&&e.message||e));});
  }catch(e){window.viewerStatus.errors.push(String(e&&e.message||e));}
}
Pane.prototype.size=function(){if(!this.r)return;var w=this.el.clientWidth,h=this.el.clientHeight;if(!w||!h)return;this.r.setSize(w,h);this.c.aspect=w/h;this.c.updateProjectionMatrix();this.draw();};
Pane.prototype.draw=function(){if(this.r)this.r.render(this.s,this.c);};
Pane.prototype.fit=function(){if(!this.obj)return;var b=new THREE.Box3().setFromObject(this.obj),ctr=b.getCenter(new THREE.Vector3()),sz=b.getSize(new THREE.Vector3()).length()||1;
  this.ctl.target.copy(ctr);this.c.position.set(ctr.x+sz*0.9,ctr.y-sz*1.1,ctr.z+sz*0.7);this.c.near=sz/1000;this.c.far=sz*100;this.c.updateProjectionMatrix();this.ctl.update();this.size();};
Pane.prototype.wire=function(on){if(!this.obj)return;this.obj.traverse(function(o){if(o.isMesh)o.material.wireframe=on;});this.draw();};
panes.push(new Pane('p_fusion','fusion','No Fusion mesh yet: run ExportToPythonBatch in Fusion (it writes the .3mf), then the converter.'));
panes.push(new Pane('p_sc','sc','No SolidCraft model: the conversion failed or has not run yet.'));
function layout(){panes.forEach(function(p){p.size();});}
window.addEventListener('resize',layout);layout();
document.querySelectorAll('#bar button[data-m]').forEach(function(b){b.onclick=function(){
  document.querySelectorAll('#bar button[data-m]').forEach(function(x){x.classList.remove('on');});b.classList.add('on');
  var m=b.getAttribute('data-m');document.getElementById('p_fusion').style.display=(m==='sc')?'none':'';document.getElementById('p_sc').style.display=(m==='fusion')?'none':'';layout();};});
document.getElementById('wire').onclick=function(){wire=!wire;this.classList.toggle('on',wire);panes.forEach(function(p){p.wire(wire);});};
document.getElementById('fit').onclick=function(){panes.forEach(function(p){p.fit();});};
</script></body></html>
'''

# ----------------------------------------------------------------------------- export analysis (gaps)
def _load_assembly_literal(src):
    """FUSION_ASSEMBLY from an export, read with ast.literal_eval (the .py is not run)."""
    import ast as _ast
    i = src.find('\nFUSION_ASSEMBLY = ')
    if i < 0: return None
    try:
        tree = _ast.parse(src)
    except Exception:
        return None
    for node in tree.body:
        if isinstance(node, _ast.Assign) and any(getattr(t, 'id', None) == 'FUSION_ASSEMBLY' for t in node.targets):
            try: return _ast.literal_eval(node.value)
            except Exception: return None
    return None

def analyze_export(path):
    """Gaps of one Fusion export (.py) from its own text: parameters, export notes, inline TODOs, sketch-only count,
    body blocks and (newer exports) FUSION_ASSEMBLY.  Never raises."""
    r = dict(params=[], joints=[], joint_origins=[], snapshots=[], motion_links=[], rigid_groups=[], failed_features=[],
             skipped_items=[], other_unsupported=[], fallbacks=[], sketch_only=0, py_bodies=0, assembly=None, components=[])
    try:
        src = open(path, encoding='utf-8', errors='replace').read()
    except Exception as e:
        r['error'] = str(e); return r
    lines, head, params, notes, apps = parse_source(src)
    for p in params:
        r['params'].append(dict(name=p['name'], var=p['var'], expression=p['fexpr'], value=p['value']))
    r['py_bodies'] = len(re.findall(r'^\s*with BuildPart\(\)', src, re.M))
    m = _SK_COUNT_RE.search(src)
    r['sketch_only'] = int(m.group(1)) if m else len(re.findall(r'^\s*#\s*Sketch-only:', src, re.M))
    # where each unsupported/failed timeline item sits (body block / component comment)
    where = {}; body = comp = None; feat = None
    for l in lines:
        mb = re.match(r'\s*#\s*Body:\s*(.+?)\s*$', l)
        if mb: body = mb.group(1); comp = None; continue
        mc = re.match(r'\s*#\s*Component:\s*(.+?)\s*$', l)
        if mc: comp = mc.group(1); continue
        mf = re.match(r'\s*#\s*\d+:\s*(.+?)\s*$', l)
        if mf: feat = mf.group(1); continue
        if feat and re.match(r'\s*#\s*TODO:', l):
            where.setdefault(feat, []).append((body or '-') + ((' / component ' + comp) if comp else ''))
            feat = None
    asm = _load_assembly_literal(src)
    r['assembly'] = bool(asm)
    asm_j = {}
    if isinstance(asm, dict):
        for j in asm.get('joints') or []:
            if isinstance(j, dict): asm_j.setdefault(j.get('name'), []).append(j)
        r['components'] = sorted(set(o.get('component') for o in asm.get('occurrences') or [] if isinstance(o, dict) and o.get('component')))
    seen = {}
    for n in notes:
        mu = re.match(r"Unsupported feature '(.+)' \(adsk::fusion::(\w+)\)\.?$", n)
        mfail = re.match(r"Feature '(.+)' failed to export:\s*(.*)$", n)
        if mu:
            name, kind = mu.group(1), mu.group(2)
            k = seen.get((name, kind), 0); seen[(name, kind)] = k + 1
            loc = (where.get(name) or [])
            d = dict(name=name, kind=kind, where=loc[k] if k < len(loc) else '')
            if kind in ('Joint', 'AsBuiltJoint'):
                d['type'] = ('as-built ' if kind == 'AsBuiltJoint' else '') + (name.split()[0].lower() if name.split() else 'joint')
                aj = asm_j.get(name) or []
                if k < len(aj):
                    d['type'] = aj[k].get('type') or d['type']
                    d['components'] = ' / '.join(str(x) for x in (aj[k].get('occurrence_one'), aj[k].get('occurrence_two')))
                r['joints'].append(d)
            elif kind == 'JointOrigin': r['joint_origins'].append(d)
            elif kind == 'Snapshot': r['snapshots'].append(d)
            elif kind == 'MotionLink': r['motion_links'].append(d)
            elif kind == 'RigidGroup': r['rigid_groups'].append(d)
            else: r['other_unsupported'].append(d)
        elif mfail:
            r['failed_features'].append(dict(name=mfail.group(1), error=mfail.group(2).strip()))
        elif 'skipped' in n:
            r['skipped_items'].append(n)
        else:
            r['other_unsupported'].append(dict(name=n, kind='note', where=''))
    for l in lines:
        if re.match(r'\s*#', l) and re.search(r'fallback|approximat', l, re.I) and 'SKETCH_ONLY' not in l:
            t = l.strip().lstrip('#').strip()
            if t not in r['fallbacks']: r['fallbacks'].append(t)
    r['fallbacks'] = r['fallbacks'][:40]
    return r

# ----------------------------------------------------------------------------- assembly (positions, components, joints)
def _is_identity(T):
    I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    return all(abs(float(a) - b) < 1e-9 for a, b in zip(T, I))

def assembly_cmds(asm, body_comp, root_name):
    """SolidCraft commands that rebuild the Fusion placements from FUSION_ASSEMBLY (newer exports only):
    one component per Fusion component that has converted bodies, one occurrence per Fusion occurrence
    (flattened under the design, at its Fusion world transform), grounding, as-built joints and rigid groups.
    Returns ([(label, command, [variant params...], key)], notes)."""
    out, notes = [], []
    if not isinstance(asm, dict): return out, notes
    if asm.get('body_coordinates') != 'component':
        notes.append('assembly data present but body coordinates are not component-local: placements not applied')
        return out, notes
    occs = [o for o in asm.get('occurrences') or [] if isinstance(o, dict) and o.get('component')]
    by_comp = {}
    for o in occs: by_comp.setdefault(o['component'], []).append(o)
    comp_bodies = {}
    for b, c in body_comp.items():
        if c: comp_bodies.setdefault(c, []).append(b)
    occ_name, moves = {}, []
    for comp, olist in by_comp.items():
        bodies = sorted(comp_bodies.get(comp, []))
        if not bodies:
            notes.append("component '%s' (%d placement(s)) has no converted bodies: not created" % (comp, len(olist))); continue
        if comp == root_name: continue
        k0 = 'asm:%s' % comp
        out.append(('component %s' % comp, 'component.create', [{'name': comp, 'parent': 0, 'activate': False, 'grounded': False}], k0 + ':create'))
        out.append(('bodies of %s' % comp, 'component.move_bodies', [{'bodies': bodies, 'component': comp}], k0 + ':bodies'))
        for k, o in enumerate(olist, 1):
            nm = '%s:%d' % (comp, k)
            if k > 1:
                out.append(('placement %s' % nm, 'occurrence.copy', [{'component': comp, 'parent': 0}], '%s:copy%d' % (k0, k)))
            occ_name[o.get('path')] = nm
            T = o.get('transform')
            if isinstance(T, list) and len(T) == 16 and not _is_identity(T):
                moves.append(('position of %s' % nm, 'occurrence.move', [{'occurrence': nm, 'space': 'world', 'matrix': [float(x) for x in T], 'move_grounded': True, 'tolerance': 1e-4}], '%s:move%d' % (k0, k)))
            if o.get('grounded'):
                moves.append(('ground %s' % nm, 'occurrence.ground', [{'occurrence': nm, 'grounded': True}], '%s:ground%d' % (k0, k)))
    out += moves      # copies first (they copy the source transform), then absolute moves from identity
    for i, j in enumerate(asm.get('joints') or []):
        if not isinstance(j, dict) or j.get('suppressed'): continue
        a, b = occ_name.get(j.get('occurrence_one')), occ_name.get(j.get('occurrence_two'))
        nm = j.get('name') or 'Joint %d' % (i + 1)
        if not a or not b or a == b:
            notes.append("joint '%s' (%s) not recreated: it involves %s" % (nm, j.get('type'), 'the design itself or a part with no converted bodies' if not (a and b) else 'one placement only'))
            continue
        jt = j.get('type') if j.get('type') in ('rigid', 'revolute', 'slider', 'cylindrical', 'pin_slot', 'planar', 'ball') else 'rigid'
        geo = j.get('geometry') or j.get('geometry_two') or j.get('geometry_one') or {}
        base = {'type': jt, 'a': a, 'b': b, 'name': nm, 'quiet': True}
        variants = []
        if jt != 'rigid' and isinstance(geo, dict) and geo.get('origin') and geo.get('z'):
            v = dict(base); v['at'] = {'occurrence': b, 'point': geo['origin'], 'z': geo['z']}; variants.append(v)
        variants.append(base)
        out.append(('joint %s' % nm, 'joint.as_built', variants, 'asm:joint%d' % i))
    for i, g in enumerate(asm.get('rigid_groups') or []):
        names = [occ_name[p] for p in (g.get('occurrences') or []) if p in occ_name]
        if len(names) >= 2:
            out.append(('rigid group %s' % g.get('name'), 'joint.rigid_group', [{'occurrences': names}], 'asm:rg%d' % i))
        else:
            notes.append("rigid group '%s' not recreated (fewer than 2 converted parts)" % g.get('name'))
    return out, notes

def finish_design(cli, work, sc_tmp, t_end, design_name, inp, asm=None, body_comp=None):
    """Last step of a conversion, on top of the saved design (never fails the file; sc_tmp is replaced only
    when the step ran): names the design's own component after the Fusion design, writes the design
    description / properties (paths to the Fusion 3D files, the viewer and the helper index; text only),
    rebuilds Fusion placements and joints when the export carries FUSION_ASSEMBLY, and counts the bodies.
    Returns dict(sc_bodies, sc_components, assembly={...}, errors, warnings, runs)."""
    base = raw_base(inp)
    desc = ('Converted from Fusion 360 export: %s\nFusion 3D view (Windows 3D Viewer): %s\nSide-by-side 3D viewer: %s\n'
            'Fusion archive (full fidelity): %s\nHelper index: %s') % (inp, base + '.3mf', base + '_viewer.html', base + '.f3d', INDEX_PATH)
    items = [('design name', 'component.rename', [{'component': 0, 'name': design_name}], 'fin:rename'),
             ('design description', 'document.metadata.set',
              [{'values': {'description': desc, 'com.littlefoot.fusion_export': {
                  'source': inp, 'model_3mf': base + '.3mf', 'viewer': base + '_viewer.html', 'f3d': base + '.f3d',
                  'step': base + '.step', 'index': INDEX_PATH}}},
               {'values': {'description': desc}}], 'fin:meta')]
    a_items, notes = assembly_cmds(asm, body_comp or {}, (asm.get('root_component') if isinstance(asm, dict) else None) or design_name) if asm else ([], [])
    items += a_items
    level, msgs = {}, {}
    res = dict(sc_bodies=None, sc_components=None, errors=[], warnings=list(notes), runs=0,
               assembly=dict(present=bool(asm), commands=len(a_items), done=[], left_out=[]))
    js = os.path.join(work, 'finish.solidcraft.json'); sc2 = os.path.join(work, (re.sub(r'[\\/:*?"<>|]+', '_', design_name).strip(' .') or 'design') + '.sc'); rj = os.path.join(work, 'finish_results.json')
    try:
        for _ in range(len(items) * 2 + 4):
            if t_end - time.time() < 4:
                res['warnings'].append('design name/description/assembly left out: not enough time left'); break
            active = [(lab, cmd, var[level.get(key, 0)], key) for lab, cmd, var, key in items if level.get(key, 0) < len(var)]
            cmds = [{'command': c, 'params': p} for _, c, p, _ in active] + [{'command': 'component.list', 'params': {'compact': True}}]
            with open(js, 'w', encoding='utf-8') as f: json.dump({'commands': cmds}, f, indent=1)
            for f in (sc2, rj):
                if os.path.exists(f): os.remove(f)
            rc, so, se = run_cli(cli, ['run', js, '--in', sc_tmp, '--save', sc2, '--param-check', 'off', '--results', '--json-out', rj], t_end); res['runs'] += 1
            if rc == 0 and os.path.exists(sc2):
                shutil.copyfile(sc2, sc_tmp)
                out = load_results(rj, len(cmds))
                if out:
                    lst = out[-1] if isinstance(out[-1], dict) else {}
                    comps = lst.get('components') or []
                    tot = 0
                    for c in comps:
                        nb = int(c.get('bodies') or 0)
                        tot += nb if c.get('parent') is None else nb * max(1, len(c.get('occurrences') or []))
                    res['sc_bodies'] = tot; res['sc_components'] = max(0, len(comps) - 1)
                res['assembly']['done'] = [lab for lab, cmd, _, key in active if key.startswith('asm:')]
                for lab, cmd, var, key in items:
                    if level.get(key, 0) >= len(var):
                        (res['assembly']['left_out'] if key.startswith('asm:') else res['errors']).append('%s left out: %s' % (lab, msgs.get(key, '')[:200]))
                return res
            m = STEP_RE.search(se) or STEP_RE.search(so)
            if not m or not (1 <= int(m.group(1)) <= len(active)):
                res['warnings'].append('design name/description/assembly left out: ' + one_line(((se or so).strip().splitlines() or ['exit %s' % rc])[-1]))
                break
            lab, cmd, p, key = active[int(m.group(1)) - 1]
            level[key] = level.get(key, 0) + 1; msgs[key] = m.group(3).strip()
    except TimeoutError:
        res['warnings'].append('design name/description/assembly left out: time limit reached')
    except Exception as e:
        res['warnings'].append('design name/description/assembly left out: %s: %s' % (type(e).__name__, e))
    return res

# ----------------------------------------------------------------------------- index.html
def _href(path, index_dir):
    import urllib.parse, pathlib
    try:
        return urllib.parse.quote(os.path.relpath(path, index_dir).replace('\\', '/'))
    except ValueError:      # other drive
        return pathlib.Path(path).as_uri()

def load_status(path):
    try:
        d = json.load(open(path, encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def build_index(root, out_root, index_path, views=SNAP_VIEWS, status=None):
    """One self-contained helper document for the whole tree under `root` (classic HTML, no scripts from
    outside): a summary table with anchors, designs needing attention first, then one section per design
    grouped by folder with six Fusion and six SolidCraft pictures, links to the 3D viewer and every file,
    and a GAPS list built from the export and the last conversion.  Links point to the files where they are."""
    import html
    esc = lambda x: html.escape(str(x), quote=True)
    index_dir = os.path.dirname(os.path.abspath(index_path))
    os.makedirs(index_dir, exist_ok=True)
    st_by = {os.path.normcase(os.path.abspath(k)): v for k, v in (status or {}).items()}
    designs = []
    for path, kind, pre_skip in find_inputs(root):
        if pre_skip: continue
        name = os.path.splitext(os.path.basename(path))[0]
        rel = os.path.relpath(os.path.dirname(path), root)
        sc = os.path.join(os.path.normpath(os.path.join(out_root, rel)), name + '.sc')
        base = raw_base(path)
        e = st_by.get(os.path.normcase(os.path.abspath(path))) or {}
        an = analyze_export(path) if kind == 'py' else dict(params=[], joints=[], joint_origins=[], snapshots=[], motion_links=[],
                 rigid_groups=[], failed_features=[], skipped_items=[], other_unsupported=[], fallbacks=[], sketch_only=0, py_bodies=None, assembly=False)
        if name.lower() == 'bathroom mirrors':
            status_txt = 'converted by hand (never touched)'
        elif e.get('status') == 'FAILED':
            status_txt = 'failed'
        elif os.path.exists(sc):
            status_txt = 'converted' if (e.get('status') or 'converted').startswith(('converted', 'skipped')) else str(e.get('status'))
        else:
            status_txt = 'failed' if e else 'not converted yet'
        source = e.get('source') or ('step-only' if kind == 'step' else ('py' if os.path.exists(sc) else '-'))
        designs.append(dict(name=name, rel=rel, kind=kind, path=path, sc=sc, base=base, e=e, an=an, status=status_txt, source=source,
                            anchor='d%d' % len(designs)))
    def flags(d):
        e, an, f = d['e'], d['an'], []
        if d['status'] in ('failed', 'not converted yet'): f.append(d['status'])
        if e.get('sc_bodies') == 0 or 'empty' in str(e.get('status', '')): f.append('empty / 0 bodies')
        if d['source'] == 'step-fallback': f.append('STEP fallback (no history)')
        if an.get('joints'): f.append('%d joints' % len(an['joints']))
        if an.get('failed_features'): f.append('%d failed features' % len(an['failed_features']))
        if an.get('other_unsupported'): f.append('%d unsupported features' % len(an['other_unsupported']))
        if an.get('fallbacks'): f.append('fillet/chamfer or other fallbacks')
        if e.get('errors'): f.append('%d conversion errors' % len(e['errors']))
        return f
    for d in designs: d['flags'] = flags(d)
    def pics(pairs, none_txt):
        h = []
        for v, p in pairs:
            if os.path.exists(p):
                u = esc(_href(p, index_dir))
                h.append('<figure><a class="t" href="%s"><img loading="lazy" src="%s" alt="%s"></a><figcaption>%s</figcaption></figure>' % (u, u, esc(v), esc(v)))
        return '<div class="g">%s</div>' % ''.join(h) if h else '<span class="none">%s</span>' % esc(none_txt)
    def link(p, label, cls=''):
        return '<a class="%s" href="%s">%s</a>' % (cls, esc(_href(p, index_dir)), esc(label)) if p and os.path.exists(p) else ''
    def table(rows, head):
        if not rows: return '<p class="none">none</p>'
        return '<table class="small"><tr>%s</tr>%s</table>' % (''.join('<th>%s</th>' % esc(h) for h in head),
               ''.join('<tr>%s</tr>' % ''.join('<td>%s</td>' % esc(c) for c in r) for r in rows))
    secs = []
    for d in sorted(designs, key=lambda d: ([x.lower() for x in d['rel'].split(os.sep)], d['name'].lower())):
        e, an, base = d['e'], d['an'], d['base']
        viewer = base + '_viewer.html'
        big = link(viewer, 'Click here to view what this looked like in Fusion 360', 'big') or link(base + '.3mf', 'Click here to view what this looked like in Fusion 360 (.3mf, Windows 3D Viewer)', 'big') \
              or '<span class="none">No Fusion 3D file yet (run ExportToPythonBatch in Fusion for this design)</span>'
        files = ' &middot; '.join(x for x in [link(base + '.3mf', '.3mf'), link(d['sc'], '.sc (SolidCraft)'), link(base + '.py', '.py'), link(base + '.step', '.step'),
                                              link(base + '.f3d', '.f3d (Fusion archive)'), link(base + '.obj', '.obj'), link(base + '.stl', '.stl'),
                                              link(base + '_fusion.glb', 'Fusion .glb'), link(base + '_solidcraft.glb', 'SolidCraft .glb')] if x)
        gaps = []
        if d['status'] != 'converted': gaps.append('Status: %s%s' % (d['status'], (' - ' + str(e.get('reason'))) if e.get('reason') else ''))
        gaps.append('Source used for the .sc: %s' % d['source'] + ((' (the .py attempt: %s)' % e['py_attempt']) if e.get('py_attempt') else ''))
        if an.get('py_bodies') is not None or e.get('sc_bodies') is not None:
            gaps.append('Bodies: %s body blocks in the .py, %s bodies in the .sc' % (an.get('py_bodies', '-'), e.get('sc_bodies', 'unknown')))
        if an.get('sketch_only') or e.get('sketch_only_found'):
            gaps.append('Sketch-only sketches: %s in the export, %s placed' % (e.get('sketch_only_found', an.get('sketch_only')), e.get('sketch_only_placed', '-')))
        if an.get('joints') or an.get('joint_origins') or an.get('snapshots') or an.get('motion_links') or an.get('rigid_groups'):
            gaps.append('Assembly not carried over by this export: %d joints, %d joint origins, %d position snapshots, %d motion links, %d rigid groups%s' % (
                len(an['joints']), len(an['joint_origins']), len(an['snapshots']), len(an['motion_links']), len(an['rigid_groups']),
                '' if an.get('assembly') else ' (the export has no placement data: parts sit at their component origins; re-export with the updated exporter)'))
        asmr = e.get('assembly') or {}
        if asmr.get('present'):
            gaps.append('Assembly rebuilt in SolidCraft: %d of %d commands (%d left out)' % (len(asmr.get('done') or []), asmr.get('commands', 0), len(asmr.get('left_out') or [])))
        for f in an.get('failed_features') or []: gaps.append('Failed to export from Fusion: %s (%s)' % (f['name'], f['error']))
        for s_ in an.get('skipped_items') or []: gaps.append('Fusion timeline item skipped: %s' % s_)
        for u in an.get('other_unsupported') or []: gaps.append('Unsupported in the export: %s' % u['name'])
        for f in an.get('fallbacks') or []: gaps.append('Fallback in the export: %s' % f)
        for x in e.get('errors') or []: gaps.append('Conversion: %s' % x)
        for x in (e.get('warnings') or [])[:30]: gaps.append('Warning: %s' % x)
        prm = e.get('params') or [dict(p, wired=None) for p in an.get('params') or []]
        wired_n = sum(1 for p in prm if p.get('wired'))
        sec = ['<section id="%s"><h3>%s <span class="st %s">%s</span> <span class="src">source: %s</span></h3>' % (
                   d['anchor'], esc(d['name']), 'bad' if d['flags'] else 'ok', esc(d['status']), esc(d['source'])),
               '<p>%s</p><p class="files">%s</p>' % (big, files),
               '<div class="cmp"><div><h4>Fusion 360</h4>%s</div><div><h4>SolidCraft</h4>%s</div></div>' % (
                   pics([(v, '%s_%s.png' % (base, v)) for v in SNAP_VIEWS], 'no Fusion picture yet'),
                   pics(snapshot_paths(base, list(views)), 'no SolidCraft picture (conversion failed)' if d['status'] != 'converted' else 'no SolidCraft picture yet')),
               '<h4>GAPS</h4><ul class="gaps">%s</ul>' % ''.join('<li>%s</li>' % esc(g) for g in gaps)]
        sec.append('<details><summary>Joints (%d)</summary>%s</details>' % (len(an.get('joints') or []), table(
            [(j['name'], j.get('type', ''), j.get('components') or 'not in this export', j.get('where', '')) for j in an.get('joints') or []],
            ('Name', 'Type', 'Components involved', 'Where in the export (body block)'))))
        sec.append('<details><summary>Joint origins (%d)</summary>%s</details>' % (len(an.get('joint_origins') or []), table(
            [(j['name'], 'joint origin', j.get('where', '')) for j in an.get('joint_origins') or []], ('Name', 'Type', 'Where in the export'))))
        sec.append('<details><summary>Position snapshots (%d)</summary>%s</details>' % (len(an.get('snapshots') or []), table(
            [(j['name'], 'snapshot (captured position)', j.get('where', '')) for j in an.get('snapshots') or []], ('Name', 'Type', 'Where in the export'))))
        sec.append('<details><summary>Motion links (%d) and rigid groups (%d)</summary>%s</details>' % (len(an.get('motion_links') or []), len(an.get('rigid_groups') or []), table(
            [(j['name'], j['kind'], j.get('where', '')) for j in (an.get('motion_links') or []) + (an.get('rigid_groups') or [])], ('Name', 'Type', 'Where in the export'))))
        sec.append('<details><summary>Failed features (%d)</summary>%s</details>' % (len(an.get('failed_features') or []), table(
            [(f['name'], f['error']) for f in an.get('failed_features') or []], ('Feature', 'Fusion error'))))
        sec.append('<details><summary>Parameters (%d, %d wired to features)</summary>%s</details>' % (len(prm), wired_n, table(
            [(p.get('name'), p.get('expression'), _g(float(p['value'])) if isinstance(p.get('value'), (int, float)) else p.get('value'),
              {True: 'yes', False: 'no (kept as a parameter)', None: 'not converted yet'}[p.get('wired')]) for p in prm],
            ('Name', 'Fusion expression', 'Value (mm / unitless)', 'Wired to a feature'))))
        sec.append('</section>')
        d['html'] = '\n'.join(sec)
    # summary
    att = [d for d in designs if d['flags']]
    summ = ['<table><tr><th>Design</th><th>Folder</th><th>Status</th><th>Source</th><th>Bodies .py / .sc</th><th>Joints</th><th>Needs attention</th></tr>']
    for d in sorted(designs, key=lambda d: (not d['flags'], [x.lower() for x in d['rel'].split(os.sep)], d['name'].lower())):
        summ.append('<tr><td><a href="#%s">%s</a></td><td>%s</td><td class="%s">%s</td><td>%s</td><td>%s / %s</td><td>%s</td><td>%s</td></tr>' % (
            d['anchor'], esc(d['name']), esc(' / '.join(d['rel'].split(os.sep)) if d['rel'] != '.' else '(root)'), 'bad' if d['status'] != 'converted' else 'ok',
            esc(d['status']), esc(d['source']), esc(d['an'].get('py_bodies', '-')), esc(d['e'].get('sc_bodies', '-')), len(d['an'].get('joints') or []),
            esc('; '.join(d['flags']) or '-')))
    summ.append('</table>')
    body = []
    last = None
    for d in sorted(designs, key=lambda d: ([x.lower() for x in d['rel'].split(os.sep)], d['name'].lower())):
        if d['rel'] != last:
            last = d['rel']
            body.append('<h2>%s</h2>' % esc('My Projects' if d['rel'] == '.' else 'My Projects / ' + ' / '.join(d['rel'].split(os.sep))))
        body.append(d['html'])
    doc = INDEX_HTML % (esc(time.strftime('%Y-%m-%d %H:%M')), esc(root), esc(out_root), len(designs), len(att),
                        '\n'.join(summ), '\n'.join(body) or '<p>No designs found.</p>')
    tmp = index_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: f.write(doc)
    os.replace(tmp, index_path)
    return len(designs)

INDEX_HTML = """<!DOCTYPE html>
<html lang="en" translate="no"><head><meta charset="utf-8"><meta name="google" content="notranslate">
<title>Fusion to SolidCraft - helper</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:16px;background:#fafafa;color:#222}
h1{font-size:20px}h2{font-size:17px;margin:28px 0 8px;border-bottom:2px solid #bbb}h3{font-size:15px;margin:0 0 6px}h4{margin:8px 0 4px;font-size:13px}
table{border-collapse:collapse;background:#fff;margin:4px 0}td,th{border:1px solid #ddd;padding:3px 6px;vertical-align:top;text-align:left;font-size:13px}
table.small td,table.small th{font-size:12px}
section{background:#fff;border:1px solid #ddd;border-radius:6px;padding:10px 12px;margin:10px 0}
.ok{color:#176b1f}.bad{color:#b00020}.st{font-size:12px;margin-left:8px}.src{font-size:12px;color:#666;margin-left:8px}
a.big{font-size:17px;font-weight:600}.files{font-size:13px}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.g{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px}
figure{margin:0;text-align:center;font-size:11px;color:#666}img{width:100%%;border:1px solid #ccc;background:#fff;cursor:zoom-in}
.none{color:#999;font-style:italic}ul.gaps{margin:4px 0 6px 18px;padding:0;font-size:13px}details{margin:3px 0;font-size:13px}
#ov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);align-items:center;justify-content:center;cursor:zoom-out;z-index:9}
#ov img{max-width:95vw;max-height:92vh;width:auto;cursor:zoom-out}#ov div{position:absolute;bottom:8px;color:#eee;font-size:13px}
</style></head><body>
<h1>Fusion 360 to SolidCraft - helper</h1>
<p>Built %s &middot; Fusion exports: %s &middot; SolidCraft designs: %s &middot; %d designs, %d need attention.
Click a picture to enlarge (Esc or click to close).</p>
<h2>Summary (designs that need attention first)</h2>
%s
%s
<div id="ov"><img alt=""><div></div></div>
<script>
var ov=document.getElementById('ov'),oi=ov.querySelector('img'),oc=ov.querySelector('div');
document.addEventListener('click',function(e){var a=e.target.closest('a.t');if(a){e.preventDefault();oi.src=a.getAttribute('href');
var s=a.closest('section');oc.textContent=(s?s.querySelector('h3').firstChild.textContent+' - ':'')+a.parentNode.querySelector('figcaption').textContent;ov.style.display='flex';}
else if(e.target.closest('#ov')){ov.style.display='none';}});
document.addEventListener('keydown',function(e){if(e.key==='Escape')ov.style.display='none';});
</script></body></html>
"""

# ----------------------------------------------------------------------------- driver
def is_export(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f: return f.readline().startswith('# Fusion design:')
    except Exception: return False

def skip_dir(dp, d):
    l = d.lower()
    return l in SKIP_DIRS or 'solidcraft' in l or os.path.exists(os.path.join(dp, d, 'pyvenv.cfg'))

STEP_EXT = ('.step', '.stp')

def find_inputs(root):
    """Yields (path, kind, skip_reason): exported .py files and .step/.stp files (a STEP whose folder also
    has an exported .py with the same base name is skipped: the .py is preferred)."""
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if not skip_dir(dp, d))
        py_names = set()
        for f in fns:
            if f.lower().endswith('.py') and is_export(os.path.join(dp, f)): py_names.add(os.path.splitext(f)[0].lower())
        for f in sorted(fns):
            p = os.path.join(dp, f); low = f.lower()
            if low.endswith('.py'):
                if os.path.splitext(f)[0].lower() in py_names: yield p, 'py', None
            elif low.endswith(STEP_EXT):
                b = os.path.splitext(f)[0]
                yield p, 'step', ('skipped (%s.py in the same folder is preferred)' % b if b.lower() in py_names else None)

_SK_COUNT_RE = re.compile(r'^SKETCH_ONLY_COUNT\s*=\s*(\d+)', re.M)
_SK_LIST_RE = re.compile(r'^SKETCH_ONLY\s*=\s*\[\s*\{', re.M)

def has_sketch_only(path):
    """True when an exported .py has at least one SKETCH_ONLY entry (read as text, not executed)."""
    try:
        with open(path, encoding='utf-8', errors='replace') as f: src = f.read()
    except Exception:
        return False
    m = _SK_COUNT_RE.search(src)
    if m: return int(m.group(1)) > 0
    return bool(_SK_LIST_RE.search(src))

def out_root_for(root):
    root = os.path.abspath(root)
    mp = os.path.abspath(DEFAULT_ROOT)
    if os.path.normcase(root) == os.path.normcase(mp): return DEFAULT_OUT
    if os.path.normcase(root).startswith(os.path.normcase(mp) + os.sep):
        return os.path.join(DEFAULT_OUT, os.path.relpath(root, mp))
    return os.path.join(root, 'SolidCraft')

def one_line(s):
    s = re.sub(r'\s+', ' ', str(s)).strip()
    return s[:220]

# ----------------------------------------------------------------------------- per-file time limit
DEFAULT_TIMEOUT = 90.0       # simple designs
ASSEMBLY_MIN_TIMEOUT = 600.0 # any design with a FUSION_ASSEMBLY block gets at least this
MAX_TIMEOUT = 3600.0         # cap for the automatic limit (an explicit --timeout is not capped)
_FEATURE_RE = re.compile(r'^\s*(?:extrude|revolve|sweep|loft|mirror|fillet|chamfer|offset|Hole)\(', re.M)

def design_size(path):
    """Cheap text scan of an exported .py (nothing is executed): bodies, sketches, features, occurrences, joints."""
    try:
        src = open(path, encoding='utf-8', errors='replace').read()
    except Exception:
        return None
    k = src.find('FUSION_ASSEMBLY')
    asm = src[k:] if k >= 0 and re.search(r'^FUSION_ASSEMBLY\s*=\s*\{', src, re.M) else ''
    return dict(bodies=len(re.findall(r'^\s*with BuildPart\(', src, re.M)),
                sketches=len(re.findall(r'^\s*with BuildSketch\(', src, re.M)),
                features=len(_FEATURE_RE.findall(src)),
                assembly=bool(asm),
                occurrences=asm.count("'transform'") + asm.count('"transform"'),
                joints=asm.count("'occurrence_one'") + asm.count('"occurrence_one"'))

def auto_timeout(path, kind):
    """(seconds, why) for one input when --timeout is not given. Simple designs keep 90 s; assemblies and big
    designs scale with their size (each SolidCraft repair pass re-runs the whole script). Capped at MAX_TIMEOUT."""
    if kind != 'py':
        try: mb = os.path.getsize(path) / 1e6
        except OSError: mb = 0.0
        t = min(MAX_TIMEOUT, max(DEFAULT_TIMEOUT, round((DEFAULT_TIMEOUT + 120.0 * mb) / 30.0) * 30.0))
        return t, 'STEP %.1f MB' % mb
    d = design_size(path)
    if not d: return DEFAULT_TIMEOUT, 'size unknown'
    why = '%d bodies, %d sketches, %d features%s' % (d['bodies'], d['sketches'], d['features'],
          (', assembly: %d occurrences, %d joints' % (d['occurrences'], d['joints'])) if d['assembly'] else '')
    if not d['assembly'] and d['bodies'] <= 5 and d['features'] <= 30 and d['sketches'] <= 30:
        return DEFAULT_TIMEOUT, why
    t = DEFAULT_TIMEOUT + 15.0 * d['features'] + 20.0 * d['bodies'] + 5.0 * d['sketches']
    if d['assembly']:
        t += 10.0 * d['occurrences'] + 5.0 * d['joints']
        t = max(t, ASSEMBLY_MIN_TIMEOUT)
    return min(MAX_TIMEOUT, max(DEFAULT_TIMEOUT, round(t / 30.0) * 30.0)), why

def main():
    ap = argparse.ArgumentParser(description='Convert Fusion-exported build123d .py files into SolidCraft .sc designs.')
    ap.add_argument('--root', default=DEFAULT_ROOT)
    ap.add_argument('--out', default=None)
    ap.add_argument('--cli', default=DEFAULT_CLI)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--only', default=None, help='only inputs whose file name (without extension) contains this text (case-insensitive)')
    ap.add_argument('--only-with-sketches', action='store_true',
                    help='only .py exports that contain sketch-only geometry (SKETCH_ONLY entries); STEP files are skipped')
    ap.add_argument('--timeout', type=float, default=None,
                    help='seconds per file (hard limit, process tree killed); default: automatic, 90 s for simple designs, '
                         'scaled up for assemblies and big designs, at most %d s' % MAX_TIMEOUT)
    ap.add_argument('--views', default=','.join(SNAP_VIEWS),
                    help='SolidCraft pictures after each saved .sc, comma separated (default iso,top,front,back,left,right)')
    ap.add_argument('--no-snapshots', action='store_true', help='no SolidCraft pictures')
    ap.add_argument('--no-viewer', action='store_true', help='no GLB files and no <Design>_viewer.html')
    ap.add_argument('--index-only', action='store_true', help='only rebuild the helper index (Fusion exports\\index.html)')
    ap.add_argument('--index-path', default=None, help=argparse.SUPPRESS)
    ap.add_argument('--child', default=None, help=argparse.SUPPRESS)
    ap.add_argument('--work', default=None, help=argparse.SUPPRESS)
    ap.add_argument('--seconds', type=float, default=80.0, help=argparse.SUPPRESS)
    global INDEX_PATH
    a = ap.parse_args()
    if a.index_path: INDEX_PATH = os.path.abspath(a.index_path)
    if a.child: return child_main(a)
    root = os.path.abspath(a.root)
    out_root = os.path.abspath(a.out) if a.out else out_root_for(root)
    views = parse_views(a.views)
    # the helper index always covers the whole tree: all of My Projects when the run is inside it
    mp = os.path.abspath(DEFAULT_ROOT)
    in_mp = os.path.normcase(root) == os.path.normcase(mp) or os.path.normcase(root).startswith(os.path.normcase(mp) + os.sep)
    idx_root = mp if (in_mp and not a.out) else root
    idx_out = DEFAULT_OUT if (in_mp and not a.out) else out_root
    status_path = os.path.join(TOOLS, 'index_status.json') if not a.index_path else os.path.splitext(INDEX_PATH)[0] + '_status.json'
    status = load_status(status_path)
    if a.index_only:
        n = build_index(idx_root, idx_out, INDEX_PATH, views, status)
        print('index: %s (%d designs)' % (INDEX_PATH, n))
        return 0

    logf = open(os.path.join(TOOLS, 'py_to_solidcraft.log'), 'w', encoding='utf-8')
    report_path = os.path.join(TOOLS, 'py_to_solidcraft_report.json')
    def log(s):
        try: print(s, flush=True)
        except Exception: pass
        logf.write(s + '\n'); logf.flush()
        try: os.fsync(logf.fileno())
        except Exception: pass
    tmpdir = tempfile.mkdtemp(prefix='py2sc_')
    log('py_to_solidcraft  %s\nroot: %s\nout:  %s\ntemp: %s\ntimeout per file: %s  force: %s  only: %s  only-with-sketches: %s  pictures: %s  viewer: %s' % (
        time.strftime('%Y-%m-%d %H:%M:%S'), root, out_root, tmpdir, ('%gs (fixed)' % a.timeout) if a.timeout is not None else 'automatic (90s simple .. %gs cap)' % MAX_TIMEOUT, a.force, a.only, a.only_with_sketches,
        'off' if a.no_snapshots else ','.join(views), 'off' if a.no_viewer else 'on'))
    report = []
    ft = [a.timeout if a.timeout is not None else DEFAULT_TIMEOUT]   # time limit of the current file
    def save_report():
        with open(report_path, 'w', encoding='utf-8') as f: json.dump(report, f, indent=2)
    def save_status(entry):
        status[entry['file']] = {k: v for k, v in entry.items() if k != 'snapshots'}
        try:
            tmp = status_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f: json.dump(status, f, indent=1)
            os.replace(tmp, status_path)
        except Exception as e:
            log('     note: index status not saved: %s' % e)
    def do_snaps(entry, sc, base, only_missing):
        r = take_snapshots(sc, base, views, a.cli, max(DEFAULT_TIMEOUT, min(ft[0], 600.0)), only_missing, tmpdir)
        entry['snapshots'] = r
        entry['snapshots_ok'] = sum(1 for x in r if x['status'] == 'ok')
        entry['snapshots_failed'] = sum(1 for x in r if x['status'] == 'failed')
        entry['snapshots_skipped'] = sum(1 for x in r if x['status'].startswith('skipped'))
        for x in r:
            if x['status'] == 'ok': log('     picture %s ok -> %s' % (x['view'], x['png']))
            elif x['status'] == 'failed':
                log('     WARNING picture %s failed: %s' % (x['view'], x['error']))
                entry.setdefault('warnings', []).append('snapshot %s failed: %s' % (x['view'], x['error']))
    def do_viewer(entry, sc, base, name, sc_fresh):
        """GLBs and <name>_viewer.html in the raw-haul folder; warnings only."""
        if a.no_viewer or name.lower() == 'bathroom mirrors': return
        fg = sg = None
        try:
            fg, note = make_fusion_glb(base); log('     Fusion GLB: %s' % (note if fg else note))
        except Exception as e:
            log('     WARNING Fusion GLB failed: %s' % one_line(e)); entry.setdefault('warnings', []).append('Fusion GLB failed: %s' % one_line(e))
        try:
            sg = base + '_solidcraft.glb'
            if sc and os.path.exists(sc) and (sc_fresh or not os.path.exists(sg) or os.path.getmtime(sg) < os.path.getmtime(sc)):
                sg, note = make_solidcraft_glb(sc, base, a.cli, max(DEFAULT_TIMEOUT, min(ft[0], 600.0)), tmpdir); log('     SolidCraft GLB: %s' % note)
            elif not os.path.exists(sg): sg = None
        except Exception as e:
            sg = None
            log('     WARNING SolidCraft GLB failed: %s' % one_line(e)); entry.setdefault('warnings', []).append('SolidCraft GLB failed: %s' % one_line(e))
        try:
            v = write_viewer(base, name, fg, sg); entry['viewer'] = v; log('     viewer -> %s' % v)
        except Exception as e:
            log('     WARNING viewer failed: %s' % one_line(e)); entry.setdefault('warnings', []).append('viewer failed: %s' % one_line(e))
    def run_child(inp, i, tag=''):
        work = os.path.join(tmpdir, '%03d%s' % (i, tag)); os.makedirs(work, exist_ok=True)
        clog = open(os.path.join(work, 'child.log'), 'w', encoding='utf-8')
        cmd = [sys.executable, os.path.abspath(__file__), '--child', inp, '--work', work, '--cli', a.cli,
               '--seconds', str(max(10.0, ft[0] - 10))]
        if a.index_path: cmd += ['--index-path', INDEX_PATH]
        p = subprocess.Popen(cmd, stdout=clog, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=NOWIN | NEWGRP)
        timed_out = False
        try:
            p.wait(timeout=ft[0])
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(p)
        clog.close()
        res = None
        rp = os.path.join(work, 'result.json')
        if not timed_out and os.path.exists(rp):
            try: res = json.load(open(rp, encoding='utf-8'))
            except Exception: res = None
        if timed_out:
            res = dict(status='FAILED', reason='timeout (over %gs, process tree killed)' % ft[0])
        elif res is None:
            tail = open(os.path.join(work, 'child.log'), encoding='utf-8', errors='replace').read().strip().splitlines()[-1:] or ['no output']
            res = dict(status='FAILED', reason='worker crashed (exit %s): %s' % (p.returncode, one_line(tail[0])))
        return res, work
    def usable(res):
        return bool(res) and str(res.get('status', '')).startswith('converted') and res.get('sc_bodies') != 0 and 'empty design' not in str(res.get('status'))
    KEYS = ('status', 'reason', 'method', 'body_count', 'bodies', 'errors', 'warnings', 'unsupported', 'passes', 'runs',
            'sketch_only_found', 'sketch_only_placed', 'sketch_only_names', 'sc_bodies', 'sc_components', 'py_bodies', 'params', 'assembly')

    inputs = list(find_inputs(root))
    n_py = sum(1 for x in inputs if x[1] == 'py'); n_step = len(inputs) - n_py
    log('found %d exported .py files and %d STEP files' % (n_py, n_step))
    for i, (py, kind, pre_skip) in enumerate(inputs, 1):
        name = os.path.splitext(os.path.basename(py))[0]
        if a.only and a.only.lower() not in name.lower(): continue
        if a.only_with_sketches and (kind != 'py' or pre_skip or not has_sketch_only(py)): continue
        rel = os.path.relpath(os.path.dirname(py), root)
        od = os.path.normpath(os.path.join(out_root, rel))
        sc = os.path.join(od, name + '.sc')
        base = raw_base(py)
        entry = dict(file=py, kind=kind, sc=sc, status=None, reason=None, method=None, body_count=None, errors=[], warnings=[], unsupported=[],
                     source=None)
        if name.lower() == 'bathroom mirrors' or os.path.basename(sc).lower() == 'bathroom mirrors.sc':
            entry['status'] = 'skipped (Bathroom Mirrors: converted by hand, left untouched)'
            report.append(entry); save_report(); log('[%d/%d] SKIP  %s (Bathroom Mirrors, never touched)' % (i, len(inputs), py)); continue
        if pre_skip:
            entry['status'] = pre_skip; report.append(entry); save_report()
            log('[%d/%d] SKIP  %s (%s)' % (i, len(inputs), py, pre_skip[9:-1])); continue
        old = os.path.join(os.path.dirname(py), name + '.sc')
        if os.path.basename(old).lower() != 'bathroom mirrors.sc' and os.path.exists(old) and os.path.normcase(os.path.abspath(old)) != os.path.normcase(os.path.abspath(sc)):
            if not os.path.exists(sc):
                os.makedirs(od, exist_ok=True); shutil.move(old, sc)
                log('[%d/%d] MOVED older %s -> %s' % (i, len(inputs), old, sc))
            else:
                log('[%d/%d] note: older %s left in place (output already exists)' % (i, len(inputs), old))
        ft[0] = a.timeout if a.timeout is not None else DEFAULT_TIMEOUT
        if os.path.exists(sc) and os.path.getmtime(sc) > os.path.getmtime(py) and not a.force:
            entry['status'] = 'skipped (up to date)'
            log('[%d/%d] SKIP  %s (.sc exists and is newer)' % (i, len(inputs), py))
            if not a.no_snapshots: do_snaps(entry, sc, base, True)
            if not a.no_viewer and not os.path.exists(base + '_viewer.html'): do_viewer(entry, sc, base, name, False)
            report.append(entry); save_report(); continue
        if a.timeout is not None: ft[0], why = a.timeout, '--timeout'
        else:
            try: ft[0], why = auto_timeout(py, kind)
            except Exception as e: ft[0], why = DEFAULT_TIMEOUT, 'size check failed: %s' % one_line(e)
        entry['timeout'] = ft[0]
        log('[%d/%d] CONVERT %s' % (i, len(inputs), py))
        log('     time limit: %gs (%s)' % (ft[0], why))
        t0 = time.time()
        res, work = run_child(py, i)
        source = 'py' if kind == 'py' else 'step-only'
        if kind == 'py' and not usable(res):
            step = next((base + x for x in ('.step', '.stp', '.STEP', '.STP') if os.path.exists(base + x)), None)
            why = res.get('reason') or ('0 bodies' if res.get('sc_bodies') == 0 else res.get('status'))
            if step:
                log('  -> .py result not usable (%s); converting %s instead' % (one_line(why), os.path.basename(step)))
                res2, work2 = run_child(step, i, 's')
                if usable(res2):
                    entry['py_attempt'] = one_line('%s: %s' % (res.get('status'), why))
                    entry['py_params'] = res.get('params')
                    res, work, source = res2, work2, 'step-fallback'
                else:
                    log('  -> STEP fallback not usable either (%s)' % one_line(res2.get('reason') or res2.get('status')))
                    entry['step_attempt'] = one_line('%s: %s' % (res2.get('status'), res2.get('reason')))
        for k in KEYS:
            if k in res: entry[k] = res[k]
        if entry.get('py_params') and not entry.get('params'): entry['params'] = entry.pop('py_params')
        entry['source'] = source
        wrote = False
        if entry['status'] and str(entry['status']).startswith('converted'):
            try:
                if os.path.basename(sc).lower() == 'bathroom mirrors.sc': raise RuntimeError('refusing to overwrite Bathroom Mirrors.sc')
                os.makedirs(od, exist_ok=True)
                shutil.copyfile(os.path.join(work, 'out.sc'), sc); wrote = True
            except Exception as e:
                entry.update(status='FAILED', reason='could not write %s: %s' % (sc, e))
        entry['seconds'] = round(time.time() - t0, 1)
        if entry['status'] == 'FAILED':
            entry['reason'] = one_line(entry.get('reason') or 'unknown')
            log('  -> FAILED (%s) (%.1fs)' % (entry['reason'], entry['seconds']))
        else:
            sk_txt = (' | sketches=%s/%s' % (entry.get('sketch_only_placed', 0), entry['sketch_only_found'])) if entry.get('sketch_only_found') else ''
            log('  -> %s | source=%s | bodies=%s%s | %d errors, %d warnings, %d unsupported notes | %s runs (%.1fs)' % (
                entry['status'], source, entry.get('sc_bodies', entry['body_count']), sk_txt, len(entry['errors']), len(entry['warnings']),
                len(entry['unsupported']), entry.get('runs'), entry['seconds']))
            for e in entry['errors'][:10]: log('     left out: ' + one_line(e))
            asmr = entry.get('assembly') or {}
            if asmr.get('present'):
                log('     assembly: %d of %d commands applied' % (len(asmr.get('done') or []), asmr.get('commands', 0)))
                for x in (asmr.get('left_out') or [])[:20]: log('     assembly left out: ' + one_line(x))
            shutil.rmtree(work, ignore_errors=True)
            if wrote and not a.no_snapshots:
                if entry.get('sc_bodies') == 0 or (entry.get('sc_bodies') is None and entry.get('body_count') == 0):
                    entry['snapshots_skipped_reason'] = '0 bodies'
                    log('     pictures skipped (0 bodies)')
                else:
                    do_snaps(entry, sc, base, False)
        if not a.no_viewer:
            do_viewer(entry, sc if os.path.exists(sc) else None, base, name, wrote)
        report.append(entry); save_report(); save_status(entry)
    ok = [e for e in report if e['status'] and e['status'].startswith('converted')]
    bad = [e for e in report if e['status'] == 'FAILED']
    sk = [e for e in report if e['status'] and e['status'].startswith('skipped')]
    log('\nDONE %s: %d found (%d .py, %d STEP), %d converted, %d failed, %d skipped' % (time.strftime('%Y-%m-%d %H:%M:%S'), len(inputs), n_py, n_step, len(ok), len(bad), len(sk)))
    if ok:
        log('sources: %d from .py, %d STEP fallback, %d STEP only' % tuple(sum(1 for e in ok if e.get('source') == s) for s in ('py', 'step-fallback', 'step-only')))
    with_sk = [e for e in ok if e.get('sketch_only_found')]
    if with_sk:
        log('sketch-only: %d converted file(s) had sketch-only sketches; %d of %d sketches placed' % (
            len(with_sk), sum(e.get('sketch_only_placed', 0) for e in with_sk), sum(e['sketch_only_found'] for e in with_sk)))
    if not a.no_snapshots:
        log('pictures: %d made, %d failed (warnings only), %d already there' % (
            sum(e.get('snapshots_ok', 0) for e in report), sum(e.get('snapshots_failed', 0) for e in report),
            sum(e.get('snapshots_skipped', 0) for e in report)))
    for e in bad: log('  FAILED %s: %s' % (os.path.relpath(e['file'], root), e['reason']))
    try:
        n = build_index(idx_root, idx_out, INDEX_PATH, views, status)
        log('index: %s (%d designs)' % (INDEX_PATH, n))
    except Exception as e:
        log('index not written: %s: %s' % (type(e).__name__, e))
    log('report: %s\noutput: %s' % (report_path, out_root))
    if not bad: shutil.rmtree(tmpdir, ignore_errors=True)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
