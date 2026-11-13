"""ShipStab desktop GUI (Chapter 1: hull modeler). Pure tkinter - no extra
GUI dependencies, so it packages into a single Windows .exe with PyInstaller."""
from __future__ import annotations

import os
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

from . import views
from .generators import box_barge, wigley
from .importers import hull_from_dxf_sections, read_offset_csv

APP_TITLE = "ShipStab - Hull Modeler"
DELIMS = {"comma ( , )": ",", "semicolon ( ; )": ";", "tab": "\t"}


class CsvOptions(tk.Toplevel):
    """Modal dialog with the offset-table import options."""

    def __init__(self, parent, filename):
        super().__init__(parent)
        self.title("Import offset table")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        f = ttk.Frame(self, padding=12)
        f.grid()
        ttk.Label(f, text=os.path.basename(filename), font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self.layout = tk.StringVar(value="stations_rows")
        self.delim = tk.StringVar(value="comma ( , )")
        self.mode = tk.StringVar(value="x")
        self.x0 = tk.StringVar(value="0")
        self.sp = tk.StringVar(value="1")
        self.scale = tk.StringVar(value="1")

        def row(r, label, widget):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", padx=(0, 10), pady=3)
            widget.grid(row=r, column=1, sticky="ew", pady=3)

        row(1, "Table layout", ttk.Combobox(f, textvariable=self.layout, state="readonly", width=22,
                                            values=["stations_rows", "waterlines_rows"]))
        row(2, "Delimiter", ttk.Combobox(f, textvariable=self.delim, state="readonly", width=22,
                                         values=list(DELIMS)))
        row(3, "Station column holds", ttk.Combobox(f, textvariable=self.mode, state="readonly", width=22,
                                                    values=["x", "number"]))
        row(4, "x of station 0 (if numbers)", ttk.Entry(f, textvariable=self.x0, width=24))
        row(5, "Station spacing (if numbers)", ttk.Entry(f, textvariable=self.sp, width=24))
        row(6, "Unit scale (mm -> m = 0.001)", ttk.Entry(f, textvariable=self.scale, width=24))
        ttk.Label(f, foreground="#555", justify="left",
                  text="Cells = half-breadths. Blank / '-' / NA = waterline does not\n"
                       "cut the hull at that station.").grid(row=7, column=0, columnspan=2, sticky="w", pady=8)
        bb = ttk.Frame(f)
        bb.grid(row=8, column=0, columnspan=2, sticky="e")
        ttk.Button(bb, text="Import", command=self._ok).pack(side="left", padx=4)
        ttk.Button(bb, text="Cancel", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_window(self)

    def _ok(self):
        try:
            self.result = dict(layout=self.layout.get(), delimiter=DELIMS[self.delim.get()],
                               station_mode=self.mode.get(), station_x0=float(self.x0.get()),
                               station_spacing=float(self.sp.get()), scale=float(self.scale.get()))
        except ValueError:
            messagebox.showerror("Invalid value", "x0, spacing and scale must be numbers.", parent=self)
            return
        self.destroy()


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1150x720")
        self.hull = None
        self.mesh = None
        self.yaw, self.pitch = -35.0, 25.0
        self._drag = None
        self._build_menu()
        self._build_ui()
        self.status.set("Ready. Import data with the buttons on the left.")

    # ------------------------------------------------------------------ UI
    def _build_menu(self):
        m = tk.Menu(self.root)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="Import offset table (CSV)...", command=self.import_csv)
        fm.add_command(label="Import DXF station curves...", command=self.import_dxf)
        fm.add_separator()
        fm.add_command(label="Export OBJ...", command=lambda: self.export("obj"))
        fm.add_command(label="Export STL...", command=lambda: self.export("stl"))
        fm.add_separator()
        fm.add_command(label="Exit", command=self.root.destroy)
        m.add_cascade(label="File", menu=fm)
        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="About", command=lambda: messagebox.showinfo(
            "About", "ShipStab - hull modeler (chapter 1)\nOffset-table and DXF import, mesh model, "
                     "OBJ/STL export.\nStability chapters to follow."))
        m.add_cascade(label="Help", menu=hm)
        self.root.config(menu=m)

    def _build_ui(self):
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)
        side = ttk.Frame(main, padding=10)
        side.pack(side="left", fill="y")

        def section(text):
            ttk.Label(side, text=text, font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(10, 3))

        def button(text, cmd, state="normal"):
            b = ttk.Button(side, text=text, command=cmd, width=32, state=state)
            b.pack(pady=2)
            return b

        section("Import hull data")
        button("Offset table (CSV)...", self.import_csv)
        button("DXF station curves...", self.import_dxf)
        button("Vector PDF lines plan...", lambda: self.not_yet("Vector PDF lines plan"))
        button("Raster lines plan (image)...", lambda: self.not_yet("Raster lines plan"))
        section("Example hulls")
        button("Wigley hull (L100 B10 T6.25)", lambda: self.load_hull(wigley(100, 10, 6.25)))
        button("Box barge (100 x 20 x 8)", lambda: self.load_hull(box_barge(100, 20, 8)))
        section("Export")
        self.btn_obj = button("Mesh to OBJ...", lambda: self.export("obj"), "disabled")
        self.btn_stl = button("Mesh to STL...", lambda: self.export("stl"), "disabled")

        self.nb = ttk.Notebook(main)
        self.nb.pack(side="left", fill="both", expand=True, padx=(0, 6), pady=6)
        self.canvases = {}
        for key, title in (("3d", "3D wireframe"), ("body", "Body plan"),
                           ("profile", "Profile"), ("plan", "Half-breadth plan")):
            fr = ttk.Frame(self.nb)
            self.nb.add(fr, text=title)
            if key == "3d":
                bar = ttk.Frame(fr)
                bar.pack(fill="x")
                for t, (yw, pt) in (("Isometric", (-35, 25)), ("Side", (0, 0)),
                                    ("Top", (0, 90)), ("Front", (90, 0))):
                    ttk.Button(bar, text=t, command=lambda a=yw, b=pt: self.set_view(a, b)).pack(side="left", padx=2, pady=2)
                ttk.Label(bar, text="  drag with left mouse button to rotate").pack(side="left")
            c = tk.Canvas(fr, bg="white", highlightthickness=0)
            c.pack(fill="both", expand=True)
            c.bind("<Configure>", lambda e: self.redraw())
            self.canvases[key] = c
        c3 = self.canvases["3d"]
        c3.bind("<ButtonPress-1>", lambda e: setattr(self, "_drag", (e.x, e.y)))
        c3.bind("<B1-Motion>", self._rotate)
        rep = ttk.Frame(self.nb)
        self.nb.add(rep, text="Report")
        self.text = tk.Text(rep, font=("Courier New", 10), wrap="none")
        self.text.pack(fill="both", expand=True)
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self.redraw())

        self.status = tk.StringVar()
        ttk.Label(self.root, textvariable=self.status, relief="sunken", anchor="w", padding=3).pack(
            side="bottom", fill="x")

    # --------------------------------------------------------------- actions
    def not_yet(self, what):
        messagebox.showinfo("Not implemented yet",
                            f"{what} import is the next milestone.\n\nPlanned workflow: calibrate the view "
                            "from two known points, classify the curves (station / waterline / buttock), "
                            "review the consistency report, then build the hull.")

    def import_csv(self):
        fn = filedialog.askopenfilename(title="Select offset table",
                                        filetypes=[("Offset tables", "*.csv *.txt *.tsv"), ("All files", "*.*")])
        if not fn:
            return
        dlg = CsvOptions(self.root, fn)
        if dlg.result is None:
            return
        try:
            hull = read_offset_csv(fn, name=os.path.splitext(os.path.basename(fn))[0], **dlg.result)
        except Exception as e:
            self.fail("Could not read the offset table", e)
            return
        self.load_hull(hull)

    def import_dxf(self):
        fn = filedialog.askopenfilename(title="Select DXF with 3D station curves",
                                        filetypes=[("DXF drawings", "*.dxf"), ("All files", "*.*")])
        if not fn:
            return
        layer = self.ask_string("DXF layer", "Name of the layer holding the station curves:", "STATIONS")
        if not layer:
            return
        try:
            hull = hull_from_dxf_sections(fn, layer=layer, name=os.path.splitext(os.path.basename(fn))[0])
        except ImportError:
            messagebox.showerror("ezdxf missing", "DXF import needs the 'ezdxf' package, which is not "
                                                  "included in this build.")
            return
        except Exception as e:
            self.fail("Could not read the DXF file", e)
            return
        self.load_hull(hull)

    def ask_string(self, title, prompt, default):
        from tkinter import simpledialog
        return simpledialog.askstring(title, prompt, initialvalue=default, parent=self.root)

    def load_hull(self, hull):
        try:
            mesh = hull.build_mesh()
        except Exception as e:
            self.fail("Could not build the hull model", e)
            return
        self.hull, self.mesh = hull, mesh
        for b in (self.btn_obj, self.btn_stl):
            b.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", views.report(hull, mesh))
        self.redraw()
        warn = "" if mesh.is_watertight() else "  WARNING: mesh not watertight"
        self.status.set(f"Loaded '{hull.name}': {len(hull.sections)} sections.{warn}")
        if hull.check() or not mesh.is_watertight():
            self.nb.select(self.nb.index("end") - 1)  # show the report with the warnings

    def export(self, kind):
        if self.mesh is None:
            return
        fn = filedialog.asksaveasfilename(defaultextension=f".{kind}", initialfile=f"{self.hull.name}.{kind}",
                                          filetypes=[(kind.upper(), f"*.{kind}")])
        if not fn:
            return
        try:
            (self.mesh.to_obj if kind == "obj" else self.mesh.to_stl)(fn)
        except Exception as e:
            self.fail("Export failed", e)
            return
        self.status.set(f"Exported {fn}")

    def fail(self, title, exc):
        traceback.print_exc()
        messagebox.showerror(title, f"{type(exc).__name__}: {exc}")
        self.status.set(title)

    # --------------------------------------------------------------- drawing
    def set_view(self, yaw, pitch):
        self.yaw, self.pitch = yaw, pitch
        self.redraw()

    def _rotate(self, e):
        if self._drag:
            dx, dy = e.x - self._drag[0], e.y - self._drag[1]
            self.yaw += dx * 0.5
            self.pitch = max(-90, min(90, self.pitch + dy * 0.5))
            self._drag = (e.x, e.y)
            self.redraw()

    def redraw(self):
        if self.hull is None:
            return
        tab = self.nb.index(self.nb.select())
        key = ["3d", "body", "profile", "plan"][tab] if tab < 4 else None
        if key is None:
            return
        c = self.canvases[key]
        w, h = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        c.delete("all")
        try:
            if key == "3d":
                lines = views.project(views.wireframe(self.hull), self.yaw, self.pitch)
                colors = "#1f4e79"
            elif key == "body":
                lines = views.body_plan(self.hull)
                colors = "#1f4e79"
            elif key == "profile":
                lines = views.profile(self.hull)
                colors = "#1f4e79"
            else:
                lines = views.plan(self.hull)
                colors = "#1f4e79"
            for L in views.fit(lines, w, h):
                c.create_line(*L.ravel().tolist(), fill=colors)
        except Exception as e:
            c.create_text(10, 10, anchor="nw", text=f"Draw error: {e}", fill="red")

    def run(self):
        self.root.mainloop()


def main():
    App().run()


if __name__ == "__main__":
    main()
