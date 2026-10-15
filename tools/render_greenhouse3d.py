"""3D preview: greenhouse cross-section. Real geometry 50x30x4.
Warm air inside, soil heat below, frost outside. Output PNG for README/app.
Run: python tools/render_greenhouse3d.py
"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

L, W, H = 50.0, 30.0, 4.0

fig = plt.figure(figsize=(10, 6), dpi=150)
ax = fig.add_subplot(111, projection='3d')
ax.set_title('Teplitsa 0.15 ha - night cross-section (-11C out / +18C in)', fontsize=11)

x0, x1, y0, y1, z0, z1 = 0, L, 0, W, 0, H
walls = [
    [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
    [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],
    [(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)],
    [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
    [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
]
ax.add_collection3d(Poly3DCollection(
    walls, facecolors=(0.55, 0.75, 1.0, 0.18),
    edgecolors=(0.2, 0.35, 0.6, 0.9), linewidths=1.0))

xg = np.linspace(4, L - 4, 9)
yg = np.linspace(4, W - 4, 6)
XG, YG = np.meshgrid(xg, yg)
ZG = np.full_like(XG, 1.9)
ax.scatter(XG.ravel(), YG.ravel(), ZG.ravel(), c='orange', s=26, alpha=0.85, label='warm air +18C')

xs = np.linspace(2, L - 2, 12)
ys = np.linspace(2, W - 2, 8)
XS, YS = np.meshgrid(xs, ys)
ZS = np.full_like(XS, 0.25)
ax.scatter(XS.ravel(), YS.ravel(), ZS.ravel(), c='saddlebrown', s=10, alpha=0.7, label='soil heat')

xo = np.array([-6] * 12)
yo = np.linspace(0, W, 12)
zo = np.linspace(0, H + 2, 12)
ax.scatter(xo, yo, zo, c='deepskyblue', s=22, alpha=0.9, label='frost -11C')
ax.plot([x0, x0], [y0, y1], [z0, z1], color='deepskyblue', linewidth=2)

ax.set_xlim(-10, L + 4)
ax.set_ylim(-4, W + 4)
ax.set_zlim(0, H + 4)
ax.set_xlabel('length 50 m')
ax.set_ylabel('width 30 m')
ax.set_zlabel('height 4 m')
ax.view_init(elev=18, azim=-62)
ax.legend(loc='upper left', fontsize=8)
fig.tight_layout()
fig.savefig('assets/greenhouse3d.png', bbox_inches='tight')
print('saved assets/greenhouse3d.png')
