"""3D preview: greenhouse cross-section, Apple-style minimalism.
Real geometry 50x30x4. Warm air inside, soil heat below, frost outside, screen curtain.
Output PNG for README/app.
Run: python tools/render_greenhouse3d.py
"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection

L, W, H = 50.0, 30.0, 4.0

fig = plt.figure(figsize=(13, 7.2), dpi=200)
ax = fig.add_subplot(111, projection='3d')
fig.patch.set_facecolor('#0E0E10')
ax.set_facecolor('#0E0E10')
ax.set_title('Теплица 0.15 га — ночной разрез (−11°C снаружи / +18°C внутри)',
             fontsize=14, color='#FFFFFF', pad=20)

x0, x1, y0, y1, z0, z1 = 0, L, 0, W, 0, H
# Пленка — полупрозрачная, тёмная, с тонкими краями
walls = [
    [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],  # передняя
    [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],  # задняя
    [(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)],  # левая
    [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],  # правая
]
ax.add_collection3d(Poly3DCollection(
    walls, facecolors=(0.9, 0.92, 1.0, 0.08),
    edgecolors=(0.3, 0.35, 0.5, 0.5), linewidths=1.2))

# Крыша — экран-шторка (тёмная полоса под потолком)
screen_z = z1 - 0.35
ax.add_collection3d(Poly3DCollection(
    [[(x0, y0, screen_z), (x1, y0, screen_z), (x1, y1, screen_z), (x0, y1, screen_z)]],
    facecolors=(0.15, 0.15, 0.17, 0.85),
    edgecolors=(0.45, 0.45, 0.5, 0.9), linewidths=1.4))
ax.text(L/2, W/2, screen_z + 0.3, 'экран — шторка (U×0.6)', color='#FF9E6B',
        fontsize=10, ha='center', fontweight='bold')

# Тёплый воздух — оранжевые точки, светятся
xg = np.linspace(6, L - 6, 11)
yg = np.linspace(6, W - 6, 7)
XG, YG = np.meshgrid(xg, yg)
ZG = np.full_like(XG, 2.2)
ax.scatter(XG.ravel(), YG.ravel(), ZG.ravel(), c='#FF9E6B', s=34, alpha=0.85,
           label='тёплый воздух +18°C')

# Почва — тёмно-коричневая, плотнее
xs = np.linspace(3, L - 3, 15)
ys = np.linspace(3, W - 3, 10)
XS, YS = np.meshgrid(xs, ys)
ZS = np.full_like(XS, 0.22)
ax.scatter(XS.ravel(), YS.ravel(), ZS.ravel(), c='#8B5A2B', s=16, alpha=0.75,
           label='тепло почвы')

# Мороз снаружи — левая стена, голубой градиент
xo = np.array([-5] * 14)
yo = np.linspace(0, W, 14)
zo = np.linspace(0, H + 2, 14)
ax.scatter(xo, yo, zo, c='#22D3EE', s=30, alpha=0.95, label='мороз −11°C')
ax.plot([x0, x0], [y0, y1], [z0, z1], color='#22D3EE', linewidth=2.5, alpha=0.9)
ax.text(-6, W/2, H/2, '−11°C', color='#22D3EE', fontsize=11,
        ha='center', va='center', fontweight='bold', rotation=90)

# Стрелка теплового потока (из почвы вверх)
ax.quiver(L*0.55, W*0.5, 0.5, 0, 0, 2.5, color='#FF9E6B', arrow_length_ratio=0.3, linewidth=2)

ax.set_xlim(-11, L + 3)
ax.set_ylim(-3, W + 3)
ax.set_zlim(0, H + 2)
ax.set_xlabel('длина 50 м', color='#FFFFFF', fontsize=10, labelpad=8)
ax.set_ylabel('ширина 30 м', color='#FFFFFF', fontsize=10, labelpad=8)
ax.set_zlabel('высота 4 м', color='#FFFFFF', fontsize=10, labelpad=8)
ax.tick_params(colors='#6E7278', labelsize=8)
ax.view_init(elev=20, azim=-58)
ax.legend(loc='upper left', fontsize=9, frameon=False, labelcolor='#FFFFFF')
fig.tight_layout()
fig.savefig('assets/greenhouse3d.png', bbox_inches='tight', facecolor='#0A0C16')
print('saved assets/greenhouse3d.png')
