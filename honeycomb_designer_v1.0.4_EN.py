"""Honeycomb Designer - lightweight Tkinter preview and Fusion 360 exporter.
Uses only the Python standard library. Run: py honeycomb_designer.py
"""
import json
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import sys
import webbrowser

# ==========================================
# APPLICATION DESCRIPTION
# ==========================================

APP_NAME = "Honeycomb Designer for Autodesk Fusion"
APP_VERSION = "1.0.4"
APP_TITLE = f"{APP_NAME} v{APP_VERSION}"
APP_LAST_UPDATED = "05-Nov-2026"
APP_AUTHOR = "Matus Kolcun (SK)"
APP_WEBSITE = "https://www.printables.com/@matus158_2682280/models"
APP_CREATED_WITH = "ChatGPT, Perplexity and Gemini"
APP_DESCRIPTION = (
    "Program for generating a honeycomb pattern, with a preview function "
    "and the ability to export to a Python script for Autodesk Fusion."
)

# ==========================================

DEFAULTS = {
    'PLATE_LENGTH': 220.0,
    'PLATE_WIDTH': 120.0,
    'PLATE_THICKNESS': 20.0,
    'SIDE_ANGLE_DEG': 1.0,
    'WALL': 1.5,
    'MARGIN': 2.0,
    'BAND_GAP': 2.0,
    'BANDS': [[6.0, 4], [8.0, 5], [10.0, 4]],
    'OUTPUT_PNG': 'preview_honeycomb.png',
    'SHOW_3D_VIEW': False,
}
MAX_HOLES = 1500


def hex_vertices(cx, cy, size):
    r = size / math.sqrt(3.0)
    return [(cx + r * math.cos(math.radians(90 + k * 60)),
             cy + r * math.sin(math.radians(90 + k * 60))) for k in range(6)]


def compute_layout(cfg):
    L, H, T = [float(cfg[k]) for k in ('PLATE_LENGTH', 'PLATE_WIDTH', 'PLATE_THICKNESS')]
    angle = float(cfg['SIDE_ANGLE_DEG'])
    wall, margin, gap = [float(cfg[k]) for k in ('WALL', 'MARGIN', 'BAND_GAP')]
    if not all(map(math.isfinite, (L, H, T, angle, wall, margin, gap))):
        raise ValueError('All values must be finite numbers.')
    if min(L, H, T, wall) <= 0 or margin < 0 or gap < 0:
        raise ValueError('Plate dimensions and WALL must be > 0; MARGIN and BAND_GAP must be >= 0.')
    if abs(angle) >= 80:
        raise ValueError('The angle must be greater than -80 and less than 80 degrees.')
    tan = math.tan(math.radians(angle))
    top = L - 2 * H * tan
    if top <= 0:
        raise ValueError('The top plate length is zero or negative. Reduce the angle.')
    bands = cfg['BANDS']
    if not bands:
        raise ValueError('Add at least one cell band.')
    groups = []
    for size, rows in bands:
        size = float(size)
        if not math.isfinite(size) or size <= 0 or type(rows) is not int or rows < 1:
            raise ValueError('Each band requires a size > 0 and an integer row count >= 1.')
        radius = size / math.sqrt(3)
        pitch_x = size + wall
        pitch_y = pitch_x * math.sqrt(3) / 2
        height = 2 * radius + (rows - 1) * pitch_y
        groups.append((size, rows, radius, pitch_x, pitch_y, height))
    needed = sum(g[5] for g in groups) + gap * (len(groups) - 1)
    available = H - 2 * margin
    if needed > available + 1e-8:
        raise ValueError('The bands require {:.2f} mm, but only {:.2f} mm is available. '
                         'Reduce the number of rows or gaps, or enlarge the plate.'.format(needed, available))
    outline = [(0, 0), (L, 0), (L - H * tan, H), (H * tan, H)]
    side_margin = margin * math.sqrt(1 + tan * tan)
    def fits(poly):
        return all(margin - 1e-7 <= y <= H - margin + 1e-7 and
                   y * tan + side_margin - 1e-7 <= x <= L - y * tan - side_margin + 1e-7
                   for x, y in poly)
    # Build the bands in a local coordinate system, then center their combined
    # bounding box in the usable plate area. The fit test still clips each hexagon
    # against the slanted outline and the requested margin.
    band_top = needed
    local_holes, summary = [], []
    for group_index, (size, rows, radius, px, py, height) in enumerate(groups):
        count = 0
        for row in range(rows):
            cy = band_top - radius - row * py
            stagger = px / 2 if row % 2 else 0
            k = 0
            while True:
                cx = margin + size / 2 + stagger + k * px
                if cx - size / 2 > L + 1:
                    break
                local_holes.append((cx, cy, size))
                count += 1
                if len(local_holes) > MAX_HOLES:
                    raise ValueError('Too many holes (limit {}).'.format(MAX_HOLES))
                k += 1
        if count == 0:
            raise ValueError('No holes fit in the {:.1f} mm band.'.format(size))
        summary.append((size, rows, count))
        if group_index < len(groups) - 1:
            band_top -= height + gap

    # Vertically center the requested band stack within the usable Y interval.
    y_shift = margin + (available - needed) / 2 - (needed / 2)
    # The local stack spans [0, needed], so its centered bottom is margin+(available-needed)/2.
    y_shift = margin + (available - needed) / 2

    # Horizontally center the repeating hex pattern. Determine its full extents
    # first, then shift its center to the center of the plate's usable X span.
    if not local_holes:
        raise ValueError('No holes were generated.')
    min_x = min(cx - size / 2 for cx, cy, size in local_holes)
    max_x = max(cx + size / 2 for cx, cy, size in local_holes)
    usable_center_x = L / 2
    pattern_center_x = (min_x + max_x) / 2
    x_shift = usable_center_x - pattern_center_x

    # Keep the pattern exactly symmetric about the plate center. For each
    # candidate opening, test it together with its mirrored counterpart; this
    # avoids a one-sided clipped edge shifting the overall grid off-center.
    
    # ---------------------------------------------------------
    # Centering the grid horizontally and vertically
    # ---------------------------------------------------------

    holes = []

    for cx, cy, size in local_holes:
        px = cx + x_shift
        py = cy + y_shift

        if fits(hex_vertices(px, py, size)):
            holes.append((px, py, size))

    if not holes:
        raise ValueError(
            'After centering, no holes fit within the outline. '
            'Adjust the margin or band parameters.'
        )

    # Actual bounding box of the remaining holes
    min_x = min(cx - size / 2 for cx, cy, size in holes)
    max_x = max(cx + size / 2 for cx, cy, size in holes)

    min_y = min(cy - size / math.sqrt(3.0) for cx, cy, size in holes)
    max_y = max(cy + size / math.sqrt(3.0) for cx, cy, size in holes)

    grid_center_x = (min_x + max_x) / 2
    grid_center_y = (min_y + max_y) / 2

    dx = L / 2 - grid_center_x
    dy = H / 2 - grid_center_y

    shifted_holes = [
        (cx + dx, cy + dy, size)
        for cx, cy, size in holes
    ]

    # Shift only if all holes remain within the allowed area
    if all(
        fits(hex_vertices(cx, cy, size))
        for cx, cy, size in shifted_holes
    ):
        holes = shifted_holes
    
    
    return {'outline': outline, 'holes': holes, 'summary': summary,
            'top': top, 'needed': needed, 'thickness': T, 'length': L, 'width': H}


def report_lines(cfg, result):
    """Text included in the GUI overview and exported PNG."""
    lines = [
        'Plate length - X: {:.2f} mm | Top plate length: {:.2f} mm | Plate width - Y: {:.2f} mm | Thickness: {:.2f} mm'.format(
            result['length'], result['top'], result['width'], result['thickness']),
        'Side angle: {:.2f} degrees | Wall: {:.2f} mm | Margin: {:.2f} mm | Band gap: {:.2f} mm'.format(
            cfg['SIDE_ANGLE_DEG'], cfg['WALL'], cfg['MARGIN'], cfg['BAND_GAP']),
        'Total holes: {} | Band height: {:.2f} mm'.format(len(result['holes']), result['needed']),
        'Bands (top to bottom): ' + '  |  '.join('{:g} mm: {} rows, {} holes'.format(size, rows, count)
                                        for size, rows, count in result['summary']),
    ]
    return lines


def project_3d(point, z, scale, ox, oy, thickness):
    """Simple isometric projection used for the lightweight 3D preview."""
    x, y = point
    return (ox + (x - 0.5 * 220) * scale * 0.88 + (y - 60) * scale * 0.34,
            oy + (x - 110) * scale * 0.28 - (y - 60) * scale * 0.62 - z * scale * 0.9)


def draw_preview(canvas, cfg, result):
    """Draw a 2D or schematic 3D preview using Tk Canvas only."""
    canvas.delete('all')
    canvas.update_idletasks()
    width = max(canvas.winfo_width(), 700)
    height = max(canvas.winfo_height(), 500)
    outline, holes = result['outline'], result['holes']
    L, H, thickness = result['length'], result['width'], result['thickness']
    show_3d = bool(cfg.get('SHOW_3D_VIEW', False))
    report_h = 112
    view_top, view_bottom = 38, height - report_h - 24
    view_h = max(180, view_bottom - view_top)

    def fit_2d(points, box):
        x0, y0, x1, y1 = box
        sx = (x1 - x0) / (L + 20)
        sy = (y1 - y0) / (H + 20)
        scale = min(sx, sy)
        ox = x0 + ((x1 - x0) - (L + 20) * scale) / 2 + 10 * scale
        oy = y0 + ((y1 - y0) - (H + 20) * scale) / 2 + 10 * scale
        return lambda x, y: (ox + x * scale, oy + (H - y) * scale), scale

    if show_3d:
        canvas.create_text(width * .25, 18, text='3D PREVIEW (SCHEMATIC)', fill='#263441',
                           font=('Segoe UI', 11, 'bold'))
        canvas.create_text(width * .75, 18, text='TOP VIEW', fill='#263441',
                           font=('Segoe UI', 11, 'bold'))
        # 3D view uses the actual model dimensions, with a fixed isometric projection.
        scale = min((width * .43) / (L * .9 + H * .34), view_h / (L * .28 + H * .62 + thickness * .9))
        ox, oy = width * .25, view_top + view_h * .60
        def iso(x, y, z=0):
            return (ox + (x - L/2) * scale * .88 + (y - H/2) * scale * .34,
                    oy + (x - L/2) * scale * .28 - (y - H/2) * scale * .62 - z * scale * .9)
        bottom = [iso(x, y, 0) for x, y in outline]
        top = [iso(x, y, thickness) for x, y in outline]
        for i in range(4):
            j = (i + 1) % 4
            canvas.create_polygon(*(v for pt in (bottom[i], bottom[j], top[j], top[i]) for v in pt),
                                  fill='#aab6c3', outline='#536373', width=1)
        canvas.create_polygon(*(v for pt in top for v in pt), fill='#dce4eb', outline='#536373', width=1.2)
        for cx, cy, size in holes:
            vv = hex_vertices(cx, cy, size)
            pts = [iso(x, y, thickness + .15) for x, y in vv]
            canvas.create_polygon(*(v for pt in pts for v in pt), fill='#263441', outline='#263441')
            lower = [iso(x, y, thickness * .25) for x, y in vv]
            for i in range(6):
                j = (i + 1) % 6
                canvas.create_polygon(*pts[i], *pts[j], *lower[j], *lower[i],
                                      fill='#65727e', outline='#465360', width=.4)
        mapper, _ = fit_2d(outline, (width * .53 + 15, view_top + 8, width - 20, view_bottom - 8))
    else:
        canvas.create_text(width / 2, 18, text='TOP VIEW - HOLE LAYOUT',
                           fill='#263441', font=('Segoe UI', 11, 'bold'))
        mapper, _ = fit_2d(outline, (28, view_top + 8, width - 28, view_bottom - 8))

    poly = [mapper(x, y) for x, y in outline]
    canvas.create_polygon(*(v for pt in poly for v in pt), fill='#dce4eb', outline='#425565', width=2)
    for cx, cy, size in holes:
        pts = [mapper(x, y) for x, y in hex_vertices(cx, cy, size)]
        canvas.create_polygon(*(v for pt in pts for v in pt), fill='#263441', outline='#263441', width=1)

    # Numeric dimensions and side angle are shown directly beside the preview.
    canvas.create_text(width / 2, view_bottom + 4,
                       text='X = {:.2f} mm'.format(L), fill='#536373',
                       font=('Segoe UI', 9, 'bold'))
    canvas.create_text(12, (view_top + view_bottom) / 2,
                       text='Y = {:.2f} mm'.format(H), fill='#536373',
                       font=('Segoe UI', 9, 'bold'), angle=90)
    canvas.create_text(18, view_top + 8,
                       text='Angle: {:.2f}°'.format(float(cfg['SIDE_ANGLE_DEG'])),
                       fill='#536373', font=('Segoe UI', 9, 'bold'), anchor='nw')
    lines = report_lines(cfg, result)
    panel_y = height - report_h + 5
    canvas.create_rectangle(12, panel_y, width - 12, height - 10,
                            fill='#eef2f6', outline='#d5dde6')
    canvas.create_text(24, panel_y + 10, text='MODEL PARAMETERS', anchor='nw',
                       fill='#263441', font=('Segoe UI', 9, 'bold'))
    canvas.create_text(24, panel_y + 30, text='\n'.join(lines), anchor='nw',
                       fill='#263441', font=('Consolas', 8), width=width - 55, justify='left')


# Export uses explicit, pre-calculated geometry. Preview and Fusion therefore use identical positions.
FUSION_TEMPLATE = r'''# Auto-generated by Honeycomb Designer. All dimensions in mm.
# Run inside Autodesk Fusion 360: Utilities -> Scripts and Add-Ins.
import adsk.core
import adsk.fusion
import traceback

MODEL_DATA = __MODEL_DATA__

def pt(x, y):
    return adsk.core.Point3D.create(x / 10.0, y / 10.0, 0)

def hex_vertices(cx, cy, size):
    import math
    r = size / math.sqrt(3.0)
    return [(cx + r * math.cos(math.radians(90 + k * 60)),
             cy + r * math.sin(math.radians(90 + k * 60))) for k in range(6)]

def polygon(sketch, points):
    lines = sketch.sketchCurves.sketchLines
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        lines.addByTwoPoints(pt(*p), pt(*q))

def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('Open Fusion Design document first.')
            return
        root = design.rootComponent  # works also in Part documents
        plane = root.xYConstructionPlane
        ext = root.features.extrudeFeatures
        sk = root.sketches.add(plane)
        sk.name = 'Honeycomb - plate contour'
        polygon(sk, MODEL_DATA['outline'])
        base = ext.createInput(sk.profiles.item(0),
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        base.setDistanceExtent(False,
            adsk.core.ValueInput.createByReal(MODEL_DATA['thickness']/10.0))
        feature = ext.add(base)
        feature.name = 'Honeycomb plate'
        body = feature.bodies.item(0)
        body.name = 'Honeycomb panel'
        skh = root.sketches.add(plane)
        skh.name = 'Honeycomb - openings'
        skh.isComputeDeferred = True
        try:
            for cx, cy, size in MODEL_DATA['holes']:
                polygon(skh, hex_vertices(cx, cy, size))
        finally:
            skh.isComputeDeferred = False
        # Identify all closed hex profiles by their (cm2) area.
        import math
        areas = [math.sqrt(3.0)/2.0*s*s/100.0 for s in MODEL_DATA['sizes']]
        selected = adsk.core.ObjectCollection.create()
        for i in range(skh.profiles.count):
            p = skh.profiles.item(i)
            area = p.areaProperties().area
            if any(abs(area-a) <= max(1e-4, a*0.015) for a in areas):
                selected.add(p)
        if selected.count != len(MODEL_DATA['holes']):
            raise RuntimeError('Expected {} profiles, got {}. Check sketch.'.format(
                len(MODEL_DATA['holes']), selected.count))
        # Cut from XY plane upwards into the new body.
        cut = ext.createInput(selected,
            adsk.fusion.FeatureOperations.CutFeatureOperation)
        cut.setDistanceExtent(False,
            adsk.core.ValueInput.createByReal((MODEL_DATA['thickness']+0.2)/10.0))
        cut.participantBodies = [body]
        ext.add(cut).name = 'Honeycomb through holes'
        sk.isVisible = False
        skh.isVisible = False
        app.activeViewport.fit()
        ui.messageBox('Created {} through holes.\nBottom {:.2f} mm; top {:.2f} mm.'.format(
            len(MODEL_DATA['holes']), MODEL_DATA['length'], MODEL_DATA['top']))
    except Exception:
        msg=traceback.format_exc()
        if ui is None:
            print(msg)
        else:
            ui.messageBox('Honeycomb error:\n'+msg)

def stop(context):
    pass
'''


def make_fusion_script(cfg, result):
    data = {'outline': result['outline'], 'holes': result['holes'],
            'sizes': [float(b[0]) for b in cfg['BANDS']],
            'thickness': result['thickness'], 'length': result['length'], 'top': result['top']}
    return FUSION_TEMPLATE.replace('__MODEL_DATA__', repr(data))


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)


def user_settings_path():
    """Persistent per-user settings, independent of the current working directory."""
    if os.name == 'nt':
        base = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
    else:
        base = os.environ.get('XDG_CONFIG_HOME') or str(Path.home() / '.config')
    folder = Path(base) / 'HoneycombDesigner'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / 'settings.json'


class Designer(tk.Tk):
    FIELD_NAMES = [
        ('PLATE_LENGTH','Plate length - X (mm)'), ('PLATE_WIDTH','Plate width - Y (mm)'),
        ('PLATE_THICKNESS','Plate thickness (mm)'), ('SIDE_ANGLE_DEG','Side angle (deg.)'),
        ('WALL','Wall between holes (mm)'), ('MARGIN','Margin (mm)'),
        ('BAND_GAP','Gap between bands (mm)'),
    ]

    def __init__(self):
        super().__init__()
        self.title(f'{APP_TITLE}')
        try:
            self.app_icon = tk.PhotoImage(file=resource_path("honeycomb.png"))
            self.iconphoto(True, self.app_icon)
        except tk.TclError:
            pass
        self.geometry('1350x820')
        self.minsize(1040, 650)
        self.configure(bg='#f5f7f9')
        self.settings_file = user_settings_path()
        startup_cfg = self._read_startup_settings()
        self.vars = {
            k: tk.StringVar(value=str(startup_cfg.get(k, DEFAULTS[k])))
            for k, _ in self.FIELD_NAMES
        }
        self.filename = tk.StringVar(value=startup_cfg.get('OUTPUT_PNG', DEFAULTS['OUTPUT_PNG']))
        self.show_3d = tk.BooleanVar(value=bool(startup_cfg.get('SHOW_3D_VIEW', DEFAULTS['SHOW_3D_VIEW'])))
        self.auto = tk.BooleanVar(value=bool(startup_cfg.get('AUTO_UPDATE', False)))
        self.band_rows = []
        self.last_cfg = None
        self.last_result = None
        self.timer = None
        self._configure_styles()
        self.build_ui()
        for size, rows in startup_cfg.get('BANDS', DEFAULTS['BANDS']):
            self.add_band(size, rows)
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.update_preview()

    def _read_startup_settings(self):
        """Read last-used settings; ignore missing/corrupt/obsolete files safely."""
        try:
            cfg = json.loads(self.settings_file.read_text(encoding='utf-8'))
            # Validate geometry and band data before applying saved values.
            candidate = dict(DEFAULTS)
            candidate.update({k: cfg[k] for k, _ in self.FIELD_NAMES if k in cfg})
            raw_bands = cfg.get('BANDS', DEFAULTS['BANDS'])
            candidate['BANDS'] = [
                (float(str(size).replace(',', '.')), int(rows))
                for size, rows in raw_bands
            ]
            candidate['OUTPUT_PNG'] = cfg.get('OUTPUT_PNG', DEFAULTS['OUTPUT_PNG'])
            candidate['SHOW_3D_VIEW'] = cfg.get('SHOW_3D_VIEW', DEFAULTS['SHOW_3D_VIEW'])
            candidate['AUTO_UPDATE'] = cfg.get('AUTO_UPDATE', False)
            compute_layout(candidate)
            return candidate
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return dict(DEFAULTS)

    def _on_close(self):
        try:
            self._write_settings(self.settings_file)
        except Exception as exc:
            self._show_error('Save settings', 'Could not save the latest settings:\\n{}'.format(exc))
            return
        self.destroy()

    def _write_settings(self, path):
        # Keep the last entered values even if the current geometry is temporarily invalid.
        payload = {
            **{key: self.vars[key].get() for key, _ in self.FIELD_NAMES},
            'BANDS': [[size.get(), rows.get()] for _, size, rows in self.band_rows],
            'OUTPUT_PNG': self.filename.get(),
            'SHOW_3D_VIEW': self.show_3d.get(),
            'AUTO_UPDATE': self.auto.get(),
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    def _configure_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        style.configure('Error.TLabel', foreground='#c62828')
        style.configure('Preview.TButton', background='#D2FC6F', foreground='#203820',
                        bordercolor='#b8d4b8', lightcolor='#edf7ed', darkcolor='#c9dfc9',
                        padding=(8, 5), font=('Segoe UI', 9, 'bold'))
        style.map('Preview.TButton',
                  background=[('active', '#F5FFC9'), ('pressed', '#d6ead6')],
                  foreground=[('disabled', '#829182')])

    def _set_status(self, text, is_error=False):
        self.status.set(text)
        self.status_label.configure(style='Error.TLabel' if is_error else 'TLabel')

    def _show_error(self, title, message):
        # A custom Tk dialog makes the error text red; native messagebox text color is OS-controlled.
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.resizable(True, True)
        dialog.configure(padx=18, pady=14)
        dialog.columnconfigure(0, weight=1)
        tk.Label(dialog, text=str(message), fg='#c62828', justify='left',
                 anchor='w', wraplength=560).grid(row=0, column=0, sticky='ew')
        ttk.Button(dialog, text='OK', command=dialog.destroy).grid(
            row=1, column=0, sticky='e', pady=(14, 0))
        dialog.bind('<Return>', lambda _event: dialog.destroy())
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)
        dialog.grab_set()
        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dialog.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry('+{}+{}'.format(max(0, x), max(0, y)))
        dialog.wait_window()
        

    def show_info(self):
        info_window = tk.Toplevel(self)
        info_window.title('About the application')
        info_window.transient(self)
        info_window.resizable(False, False)
        info_window.configure(padx=20, pady=16, bg='#f5f7f9')

        try:
            icon = tk.PhotoImage(file=resource_path('honeycomb.png'))
            info_window.iconphoto(True, icon)
            self._info_icon = icon

            tk.Label(
                info_window,
                image=icon,
                bg='#f5f7f9'
            ).pack(pady=(0, 10), anchor='center')

        except Exception:
            icon = None

        # Application name and version
        tk.Label(
            info_window,
            text=f"{APP_NAME}\nVersion: v{APP_VERSION}",
            font=('Segoe UI', 12, 'bold'),
            fg='#263441',
            bg='#f5f7f9',
            justify='left'
        ).pack(anchor='w', pady=(0, 12))

        # Application details
        details = (
            f"Last updated: {APP_LAST_UPDATED}\n"
            f"Author: {APP_AUTHOR}"
        )

        tk.Label(
            info_window,
            text=details,
            font=('Segoe UI', 10),
            fg='#3d4b58',
            bg='#f5f7f9',
            justify='left',
            anchor='w',
            wraplength=430
        ).pack(anchor='w')

        # Other projects - clickable URL
        link_frame = tk.Frame(info_window, bg='#f5f7f9')
        link_frame.pack(anchor='w', pady=(2, 0))

        tk.Label(
            link_frame,
            text="My other projects: ",
            font=('Segoe UI', 10),
            fg='#3d4b58',
            bg='#f5f7f9'
        ).pack(side='left')

        link = tk.Label(
            link_frame,
            text=APP_WEBSITE,
            fg='#1565c0',
            bg='#f5f7f9',
            cursor='hand2',
            font=('Segoe UI', 10, 'underline')
        )
        link.pack(side='left')
        link.bind(
            '<Button-1>',
            lambda e: webbrowser.open(APP_WEBSITE)
        )

        # Additional information and description
        details_bottom = (
            f"Created with: {APP_CREATED_WITH}\n\n"
            f"Description:\n{APP_DESCRIPTION}"
        )

        tk.Label(
            info_window,
            text=details_bottom,
            font=('Segoe UI', 10),
            fg='#3d4b58',
            bg='#f5f7f9',
            justify='left',
            anchor='w',
            wraplength=430
        ).pack(anchor='w', pady=(2, 0))

        # Close button
        ttk.Button(
            info_window,
            text='Close',
            command=info_window.destroy
        ).pack(pady=(16, 0))

        # Center the window relative to the main application
        info_window.update_idletasks()
        x = self.winfo_rootx() + (
            self.winfo_width() - info_window.winfo_width()
        ) // 2
        y = self.winfo_rooty() + (
            self.winfo_height() - info_window.winfo_height()
        ) // 2

        info_window.geometry(
            f'+{max(0, x)}+{max(0, y)}'
        )

    def build_ui(self):
        panel = ttk.Frame(self, padding=12)
        panel.pack(side='left', fill='y')
        ttk.Label(panel, text='Plate parameters', font=('Segoe UI', 14, 'bold')).pack(anchor='w', pady=(0, 10))
        for key, label in self.FIELD_NAMES:
            row = ttk.Frame(panel)
            row.pack(fill='x', pady=3)
            ttk.Label(row, text=label, width=28).pack(side='left')
            ttk.Entry(row, textvariable=self.vars[key], width=13).pack(side='right')
        ttk.Separator(panel).pack(fill='x', pady=14)
        ttk.Label(panel, text='Hole bands (top to bottom)', font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        self.bands_frame = ttk.Frame(panel)
        self.bands_frame.pack(fill='x', pady=7)
        ttk.Button(panel, text='+ Add band', command=lambda: self.add_band(12.0, 2)).pack(fill='x', pady=3)
        ttk.Separator(panel).pack(fill='x', pady=10)
        ttk.Checkbutton(panel, text='Show 3D view', variable=self.show_3d,
                        command=self.update_preview).pack(anchor='w')
        ttk.Checkbutton(panel, text='Automatically update preview', variable=self.auto).pack(anchor='w', pady=4)
        row = ttk.Frame(panel)
        row.pack(fill='x', pady=5)
        ttk.Label(row, text='PNG filename:').pack(side='left')
        ttk.Entry(row, textvariable=self.filename, width=24).pack(side='right')
        ttk.Button(panel, text='Preview', style='Preview.TButton',
                   command=self.update_preview).pack(fill='x', pady=(12, 4))
        ttk.Button(panel, text='Export preview as PNG', command=self.save_png).pack(fill='x', pady=4)
        ttk.Button(panel, text='Generate Autodesk Fusion script', command=self.export_fusion).pack(fill='x', pady=4)
        ttk.Button(panel, text='Save JSON settings', command=self.save_settings).pack(fill='x', pady=4)
        ttk.Button(panel, text='Load JSON settings', command=self.load_settings).pack(fill='x', pady=4)
        self.info = tk.StringVar(value='')
        self.info_label = ttk.Label(panel, textvariable=self.info, wraplength=295, justify='left')
        self.info_label.pack(anchor='w', pady=14)
        right = ttk.Frame(self, padding=(0, 12, 12, 12))
        right.pack(side='right', fill='both', expand=True)

        top_bar = ttk.Frame(right)
        top_bar.pack(fill='x', pady=(0, 6))
    
        info_button = tk.Button(
            top_bar,
            text=' i ',
            command=self.show_info,
            bg='#1e88e5',
            fg='white',
            activebackground='#1565c0',
            activeforeground='white',
            relief='flat',
            bd=0,
            font=('Segoe UI', 9, 'bold'),
            width=2,
            cursor='hand2'
            )
        info_button.pack(side='right')
        self.preview = tk.Canvas(right, bg='#fafbfc', highlightthickness=1, highlightbackground='#d5dde6')
        self.preview.pack(fill='both', expand=True)
        self.preview.bind('<Configure>', lambda _event: self._redraw_cached())
        self.status = tk.StringVar(value='')
        self.status_label = ttk.Label(right, textvariable=self.status, wraplength=800)
        self.status_label.pack(anchor='w', pady=4)
        for var in list(self.vars.values()):
            var.trace_add('write', lambda *_: self.queue_update())

    def add_band(self, size, count):
        row = ttk.Frame(self.bands_frame)
        row.pack(fill='x', pady=2)
#        ttk.Label(row, text='mm', width=3).pack(side='left')
        ttk.Label(row, text='mm', width=4, anchor='w').pack(side='left')
        sz = tk.StringVar(value=str(size))
        ttk.Entry(row, textvariable=sz, width=9).pack(side='left', padx=(5, 3))
        ttk.Label(row, text='rows').pack(side='left', padx=5)
        rows = tk.StringVar(value=str(count))
        ttk.Entry(row, textvariable=rows, width=6).pack(side='left', padx=3)
        entry = (row, sz, rows)
        ttk.Button(row, text='X', width=3, command=lambda: self.delete_band(entry)).pack(side='right')
        self.band_rows.append(entry)
        sz.trace_add('write', lambda *_: self.queue_update())
        rows.trace_add('write', lambda *_: self.queue_update())
        self.queue_update()

    def delete_band(self, entry):
        self.band_rows.remove(entry)
        entry[0].destroy()
        self.queue_update()

    def queue_update(self):
        if not hasattr(self, 'auto') or not self.auto.get():
            return
        if self.timer:
            self.after_cancel(self.timer)
        self.timer = self.after(500, self.update_preview)

    def get_cfg(self):
        cfg = {key: float(self.vars[key].get().replace(',', '.')) for key, _ in self.FIELD_NAMES}
        cfg['BANDS'] = [(float(size.get().replace(',', '.')), int(rows.get()))
                        for _, size, rows in self.band_rows]
        cfg['OUTPUT_PNG'] = self.filename.get().strip()
        cfg['SHOW_3D_VIEW'] = self.show_3d.get()
        return cfg

    def validate_and_render(self):
        cfg = self.get_cfg()
        result = compute_layout(cfg)
        self.last_cfg, self.last_result = cfg, result
        draw_preview(self.preview, cfg, result)
        return cfg, result

    def _redraw_cached(self):
        if self.last_cfg is not None and self.last_result is not None:
            draw_preview(self.preview, self.last_cfg, self.last_result)

    def update_preview(self):
        self.timer = None
        try:
            cfg, res = self.get_cfg(), None
            res = compute_layout(cfg)
            self.last_cfg, self.last_result = cfg, res
            draw_preview(self.preview, cfg, res)
            summary = ' | '.join('{:g} mm: {} rows, {} holes'.format(s, r, n)
                                 for s, r, n in res['summary'])
            self.info.set('Total: {} holes\nTop plate length: {:.2f} mm\nBand height: {:.2f} mm'.format(
                len(res['holes']), res['top'], res['needed']))
            self._set_status(summary)
            self.info_label.configure(style='TLabel')
        except Exception as e:
            self._set_status('ERROR: ' + str(e), is_error=True)
            self.info.set('Invalid parameters. The last valid preview is preserved.')
            self.info_label.configure(style='Error.TLabel')

    def save_png(self):
        """Save the preview as PNG using Tk's native photo image support."""
        try:
            cfg, res = self.get_cfg(), None
            res = compute_layout(cfg)
            path = filedialog.asksaveasfilename(title='Save preview', defaultextension='.png',
                initialfile=cfg['OUTPUT_PNG'] or 'preview_honeycomb.png',
                filetypes=[('PNG image', '*.png')])
            if not path:
                return
            # Render the current canvas to PostScript is not a PNG conversion. Instead,
            # build a native Tk photo image and draw the model polygons into it.
            self._save_geometry_png(path, cfg, res)
            self._set_status('Preview saved: ' + path)
        except Exception as e:
            self._show_error('Error', str(e))

    def _save_geometry_png(self, path, cfg, result):
        # Tk PhotoImage supports PNG writing on standard modern Windows Tk builds.
        w, h = 1400, 900
        img = tk.PhotoImage(width=w, height=h)
        img.put('#ffffff', to=(0, 0, w, h))
        L, H = result['length'], result['width']
        pad_x, pad_y = 70, 70
        scale = min((w - 2 * pad_x) / L, (h - 300) / H)
        ox = (w - L * scale) / 2
        oy = 70 + (h - 300 - H * scale) / 2
        def xy(x, y):
            return (int(ox + x * scale), int(oy + (H - y) * scale))
        def polygon(points, color):
            pts = [xy(x, y) for x, y in points]
            min_y = max(0, min(y for _, y in pts)); max_y = min(h - 1, max(y for _, y in pts))
            for yy in range(min_y, max_y + 1):
                intersections = []
                for i, (x1, y1) in enumerate(pts):
                    x2, y2 = pts[(i + 1) % len(pts)]
                    if y1 == y2:
                        continue
                    if min(y1, y2) <= yy < max(y1, y2):
                        intersections.append(x1 + (yy - y1) * (x2 - x1) / (y2 - y1))
                intersections.sort()
                for i in range(0, len(intersections) - 1, 2):
                    x1 = max(0, int(intersections[i])); x2 = min(w - 1, int(intersections[i + 1]))
                    if x2 >= x1:
                        img.put(color, to=(x1, yy, x2 + 1, yy + 1))
        polygon(result['outline'], '#dce4eb')
        for cx, cy, size in result['holes']:
            polygon(hex_vertices(cx, cy, size), '#263441')

        # Tiny built-in 5x7 font keeps PNG export independent of Pillow/Matplotlib.
        glyphs = {
            'A':('01110','10001','10001','11111','10001','10001','10001'),
            'B':('11110','10001','10001','11110','10001','10001','11110'),
            'C':('01111','10000','10000','10000','10000','10000','01111'),
            'D':('11110','10001','10001','10001','10001','10001','11110'),
            'E':('11111','10000','10000','11110','10000','10000','11111'),
            'F':('11111','10000','10000','11110','10000','10000','10000'),
            'G':('01111','10000','10000','10111','10001','10001','01111'),
            'H':('10001','10001','10001','11111','10001','10001','10001'),
            'I':('11111','00100','00100','00100','00100','00100','11111'),
            'J':('00111','00010','00010','00010','10010','10010','01100'),
            'K':('10001','10010','10100','11000','10100','10010','10001'),
            'L':('10000','10000','10000','10000','10000','10000','11111'),
            'M':('10001','11011','10101','10101','10001','10001','10001'),
            'N':('10001','11001','10101','10011','10001','10001','10001'),
            'O':('01110','10001','10001','10001','10001','10001','01110'),
            'P':('11110','10001','10001','11110','10000','10000','10000'),
            'Q':('01110','10001','10001','10001','10101','10010','01101'),
            'R':('11110','10001','10001','11110','10100','10010','10001'),
            'S':('01111','10000','10000','01110','00001','00001','11110'),
            'T':('11111','00100','00100','00100','00100','00100','00100'),
            'U':('10001','10001','10001','10001','10001','10001','01110'),
            'V':('10001','10001','10001','10001','10001','01010','00100'),
            'W':('10001','10001','10001','10101','10101','10101','01010'),
            'X':('10001','10001','01010','00100','01010','10001','10001'),
            'Y':('10001','10001','01010','00100','00100','00100','00100'),
            'Z':('11111','00001','00010','00100','01000','10000','11111'),
            '0':('01110','10001','10011','10101','11001','10001','01110'),
            '1':('00100','01100','00100','00100','00100','00100','01110'),
            '2':('01110','10001','00001','00010','00100','01000','11111'),
            '3':('11110','00001','00001','01110','00001','00001','11110'),
            '4':('00010','00110','01010','10010','11111','00010','00010'),
            '5':('11111','10000','10000','11110','00001','00001','11110'),
            '6':('01110','10000','10000','11110','10001','10001','01110'),
            '7':('11111','00001','00010','00100','01000','01000','01000'),
            '8':('01110','10001','10001','01110','10001','10001','01110'),
            '9':('01110','10001','10001','01111','00001','00001','01110'),
            '.':('00000','00000','00000','00000','00000','00110','00110'),
            ',':('00000','00000','00000','00000','00110','00100','01000'),
            ':':('00000','00110','00110','00000','00110','00110','00000'),
            '|':('00100','00100','00100','00100','00100','00100','00100'),
            '-':('00000','00000','00000','11111','00000','00000','00000'),
            '+':('00000','00100','00100','11111','00100','00100','00000'),
            '(':('00010','00100','01000','01000','01000','00100','00010'),
            ')':('01000','00100','00010','00010','00010','00100','01000'),
            ' ':('00000',)*7,
        }
        def bitmap_text(text, x, y, color='#263441', scale_px=2):
            cursor = x
            for char in text.upper():
                pattern = glyphs.get(char, glyphs[' '])
                for gy, row_bits in enumerate(pattern):
                    for gx, bit in enumerate(row_bits):
                        if bit == '1':
                            x1 = cursor + gx * scale_px
                            y1 = y + gy * scale_px
                            img.put(color, to=(x1, y1, x1 + scale_px, y1 + scale_px))
                cursor += 6 * scale_px
        bitmap_text('MODEL PARAMETERS', 55, 690, scale_px=2)
        for index, line in enumerate(report_lines(cfg, result)):
            bitmap_text(line, 55, 715 + index * 34, scale_px=2)
        img.write(path, format='png')

    def export_fusion(self):
        try:
            cfg, res = self.get_cfg(), None
            res = compute_layout(cfg)
            path = filedialog.asksaveasfilename(title='Save Fusion script', defaultextension='.py',
                initialfile='fusion_honeycomb_generated.py', filetypes=[('Python', '*.py')])
            if path:
                Path(path).write_text(make_fusion_script(cfg, res), encoding='utf-8')
                self._set_status('Fusion script saved: ' + path)
                messagebox.showinfo('Export complete',
                    'The Fusion script has been saved. Open it in Autodesk Fusion via Utilities > Scripts and Add-Ins.\n'
                    'It contains {} precisely calculated holes.'.format(len(res['holes'])))
        except Exception as e:
            self._show_error('Error', str(e))

    def save_settings(self):
        try:
            cfg = self.get_cfg()
            compute_layout(cfg)
            path = filedialog.asksaveasfilename(title='Save settings', defaultextension='.json',
                initialfile='honeycomb_settings.json', filetypes=[('JSON', '*.json')])
            if path:
                self._write_settings(Path(path))
        except Exception as e:
            self._show_error('Error', str(e))

    def load_settings(self):
        path = filedialog.askopenfilename(title='Load settings', filetypes=[('JSON', '*.json')])
        if not path:
            return
        try:
            cfg = json.loads(Path(path).read_text(encoding='utf-8'))
            cfg['BANDS'] = [
                (float(str(size).replace(',', '.')), int(rows))
                for size, rows in cfg['BANDS']
            ]
            compute_layout(cfg)
            for key, _ in self.FIELD_NAMES:
                self.vars[key].set(str(cfg[key]))
            for entry in self.band_rows[:]:
                self.delete_band(entry)
            for size, count in cfg['BANDS']:
                self.add_band(size, count)
            self.filename.set(cfg.get('OUTPUT_PNG', 'preview_honeycomb.png'))
            self.show_3d.set(bool(cfg.get('SHOW_3D_VIEW', False)))
            self.auto.set(bool(cfg.get('AUTO_UPDATE', False)))
            self.update_preview()
        except Exception as e:
            self._show_error('Error', str(e))


if __name__=='__main__':
    Designer().mainloop()
