import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shipstab import wigley

h = wigley(L=100, B=10, T=6.25, n_stations=21, n_waterlines=11)
print("issues:", h.check())
m = h.build_mesh()
print(f"watertight={m.is_watertight()}  V={m.volume():.2f} m3 (exact {4/9*100*10*6.25:.2f})")
print("centroid:", m.centroid().round(4), " bounds:", [b.round(2) for b in m.bounds()])
m.to_obj("wigley.obj"); m.to_stl("wigley.stl")
print("wrote wigley.obj / wigley.stl")
