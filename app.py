"""Теплица 0.15 га — ночной автопилот. 3 экрана, Apple-минимализм."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st
import pandas as pd
from config import (DEMO_GREENHOUSE, T_TARGET_C, GAS_TARIFF_TG_M3, YIELD_KG_M2,
                    PRICE_TG_KG, T_CRIT_CUCUMBER, T_CRIT_TOMATO, BOILER_KW_MAX,
                    TARAZ_LAT, TARAZ_LON)
from weather import forecast_with_spread
from optimizer import optimize_night
from dynamics import simulate_no_heat
from freeze import dew_point_magnus, disease_flag
from decision import decide_ev, decide_price
from ai_assistant import (verbalize_v2, anomaly_guard, price_verdict,
                          extract_farm_state)


# ==================== ВИЗУАЛЬНЫЕ ХЕЛПЕРЫ (бизнес-логику не трогают) ====================
_CARD_CSS = """
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, "SF Pro Display", "Inter", system-ui, sans-serif;
       background: transparent; }
.row { display: flex; gap: 14px; }
.mcard { flex: 1; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08);
  border-radius: 20px; padding: 20px 24px;
  transition: transform .3s cubic-bezier(.16,1,.3,1), box-shadow .3s cubic-bezier(.16,1,.3,1),
              border-color .3s cubic-bezier(.16,1,.3,1); }
.mcard:hover { transform: translateY(-4px); border-color: rgba(255,255,255,.15);
  box-shadow: 0 26px 60px rgba(0,0,0,.55), 0 0 44px var(--acc); }
.label { font-size: .78rem; color: #6E6E73; text-transform: uppercase;
  letter-spacing: .08em; margin-bottom: 8px; }
.value { font-size: 2.15rem; font-weight: 700; color: #FFFFFF;
  font-variant-numeric: tabular-nums; letter-spacing: -.02em; line-height: 1.12; }
.value.heat { background: linear-gradient(92deg,#FF6B35,#FFB627);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.value.hold { background: linear-gradient(92deg,#2E7CF6,#5AC8FA);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.value.sell { background: linear-gradient(92deg,#C77DFF,#FF9CEE);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
"""


def _metric_cards_html(cards, acc_a):
    """Ряд стеклянных карточек со счётчиками чисел (count-up через rAF).
    cards: [{label, value|text, dec, suffix, cls}] — чисто отображение."""
    parts = []
    for c in cards:
        if "text" in c:
            val = f'<div class="value {c.get("cls", "")}">{c["text"]}</div>'
        else:
            val = (f'<div class="value"><span data-count="{c["value"]}"'
                   f' data-dec="{c.get("dec", 0)}">0</span>{c.get("suffix", "")}</div>')
        parts.append(f'<div class="mcard"><div class="label">{c["label"]}</div>{val}</div>')
    js = """
const countUp = el => {
  const target = parseFloat(el.dataset.count);
  const dec = parseInt(el.dataset.dec || "0", 10);
  const dur = 1200, t0 = performance.now();
  const tick = t => {
    const p = Math.min((t - t0) / dur, 1);
    const e = 1 - Math.pow(1 - p, 3);
    el.textContent = (target * e).toLocaleString("ru-RU",
      {minimumFractionDigits: dec, maximumFractionDigits: dec});
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
};
document.querySelectorAll("[data-count]").forEach(countUp);
"""
    return ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
            + _CARD_CSS.replace("var(--acc)", acc_a)
            + '</style></head><body><div class="row">'
            + "".join(parts) + '</div><script>' + js + '</script></body></html>')


def _greenhouse3d_html(action):
    """Low-poly 3D-разрез теплицы (Three.js, CDN). Котёл светится под цвет
    решения: heat=оранжевый, иначе синий. Fallback без WebGL — сообщение."""
    acc = "#FF6B35" if action == "heat" else "#2E7CF6"
    return """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body { margin:0; height:100%; background:transparent; overflow:hidden;
  font-family: -apple-system, system-ui, sans-serif; }
#scene { width:100%; height:100%; }
#fallback { display:none; color:#A1A1A6; font-size:14px; text-align:center; padding-top:180px; }
</style></head><body>
<div id="scene"></div>
<div id="fallback">WebGL недоступен — статичный рендер ниже (expander)</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
(function () {
  var ACC = "ACC_HEX";
  var host = document.getElementById("scene");
  var renderer;
  try {
    renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
  } catch (e) {
    document.getElementById("fallback").style.display = "block";
    host.style.display = "none";
    return;
  }
  renderer.setSize(host.clientWidth, host.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  host.appendChild(renderer.domElement);

  var scene = new THREE.Scene();
  var camera = new THREE.PerspectiveCamera(36, host.clientWidth / host.clientHeight, 0.1, 100);
  camera.position.set(13, 7.5, 15);
  camera.lookAt(0, 2.0, 0);

  var group = new THREE.Group();
  scene.add(group);
  var L = 10, W = 6, H = 2.6;

  var soil = new THREE.Mesh(new THREE.BoxGeometry(L, 0.6, W),
    new THREE.MeshStandardMaterial({color: 0x4a3423, roughness: 1}));
  soil.position.y = -0.3; soil.receiveShadow = true; group.add(soil);

  var filmMat = new THREE.MeshStandardMaterial({color: 0xbfe3ff, transparent: true,
    opacity: 0.12, side: THREE.DoubleSide, roughness: 0.25});
  var walls = new THREE.Mesh(new THREE.BoxGeometry(L, H, W), filmMat);
  walls.position.y = H / 2; group.add(walls);
  var edges = new THREE.LineSegments(new THREE.EdgesGeometry(walls.geometry),
    new THREE.LineBasicMaterial({color: 0x9adcf5, transparent: true, opacity: 0.55}));
  edges.position.copy(walls.position); group.add(edges);

  var rise = 1.4, slope = Math.atan2(rise, W / 2), slopeLen = Math.hypot(rise, W / 2);
  [1, -1].forEach(function (s) {
    var m = new THREE.Mesh(new THREE.PlaneGeometry(L, slopeLen), filmMat);
    m.rotation.x = -Math.PI / 2 + s * slope;
    m.position.set(0, H + rise / 2, s * W / 4);
    group.add(m);
    var e = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry),
      new THREE.LineBasicMaterial({color: 0x9adcf5, transparent: true, opacity: 0.5}));
    e.rotation.copy(m.rotation); e.position.copy(m.position); group.add(e);
  });

  var cropMat = new THREE.MeshStandardMaterial({color: 0x3f8f4a, roughness: 0.9});
  for (var r = -1; r <= 1; r++) {
    for (var i = 0; i < 8; i++) {
      var c = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.7, 0.5), cropMat);
      c.position.set(-L / 2 + 0.8 + i * (L - 1.6) / 7, 0.35, r * 1.5);
      c.castShadow = true; group.add(c);
    }
  }

  var boilerMat = new THREE.MeshStandardMaterial({color: 0x30343f,
    emissive: new THREE.Color(ACC), emissiveIntensity: 0.9, roughness: 0.5});
  var boiler = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.65, 1.3, 16), boilerMat);
  boiler.position.set(-L / 2 + 1.2, 0.65, W / 2 - 1.2);
  boiler.castShadow = true; group.add(boiler);
  var glowLight = new THREE.PointLight(new THREE.Color(ACC), 1.4, 12);
  glowLight.position.copy(boiler.position); glowLight.position.y += 1;
  group.add(glowLight);

  var ground = new THREE.Mesh(new THREE.CircleGeometry(16, 48),
    new THREE.MeshStandardMaterial({color: 0x0f1117, roughness: 1}));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -0.6;
  ground.receiveShadow = true; scene.add(ground);

  scene.add(new THREE.AmbientLight(0x8899bb, 0.55));
  var key = new THREE.DirectionalLight(new THREE.Color(ACC), 1.05);
  key.position.set(8, 12, 6); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.left = -12; key.shadow.camera.right = 12;
  key.shadow.camera.top = 12; key.shadow.camera.bottom = -12;
  scene.add(key);
  var fill = new THREE.DirectionalLight(0x9adcf5, 0.25);
  fill.position.set(-8, 6, -6); scene.add(fill);

  var t0 = performance.now();
  (function animate(now) {
    requestAnimationFrame(animate);
    var t = (now - t0) / 1000;
    group.rotation.y = 0.55 + Math.sin(t * 0.25) * 0.4;
    group.position.y = Math.sin(t * 0.8) * 0.08;
    boilerMat.emissiveIntensity = 0.9 + 0.5 * Math.sin(t * 2.2);
    glowLight.intensity = 1.2 + 0.5 * Math.sin(t * 2.2);
    renderer.render(scene, camera);
  })(t0);

  window.addEventListener("resize", function () {
    camera.aspect = host.clientWidth / host.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(host.clientWidth, host.clientHeight);
  });
})();
</script></body></html>""".replace("ACC_HEX", acc)


st.set_page_config(page_title="Теплица 0.15 га — автопилот", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
:root {
    --ease: cubic-bezier(.16,1,.3,1);
    --text-1:#F5F5F7; --text-2:#A1A1A6; --text-3:#6E6E73;
    --acc-a:#FF6B35; --acc-b:#FFB627;
}
@keyframes fadeUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
@keyframes glowPulse { 0%,100% { text-shadow: 0 0 18px rgba(255,107,53,.40); } 50% { text-shadow: 0 0 40px rgba(255,107,53,.90); } }
@keyframes haloPulse { 0%,100% { opacity:.35; } 50% { opacity:.6; } }
.stApp {
    background:
        radial-gradient(900px 520px at 88% -8%, rgba(255,107,53,.10), transparent 60%),
        radial-gradient(820px 520px at -12% 18%, rgba(46,124,246,.09), transparent 60%),
        #0A0A0C;
    background-attachment: fixed;
    color: var(--text-1);
    font-family: -apple-system, "SF Pro Display", "Inter", system-ui, sans-serif;
}
.stApp::before {
    content:""; position:fixed; inset:0; z-index:9999; pointer-events:none; opacity:.03;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}
.hero-title {
    font-size: clamp(2.2rem, 5vw, 3.4rem); font-weight: 700; letter-spacing: -0.03em; margin-bottom: 2px;
    background: linear-gradient(92deg, #FFB08A 0%, #FFD9A8 35%, #9BE8D8 70%, #8AB8FF 100%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
    animation: fadeUp .8s var(--ease) both;
}
.hero-sub { font-size: 1.05rem; color: var(--text-2); margin: 2px 0 20px 0; animation: fadeUp .8s var(--ease) .12s both; }
.metric-card {
    background: rgba(255,255,255,.04);
    backdrop-filter: blur(20px) saturate(180%); -webkit-backdrop-filter: blur(20px) saturate(180%);
    border: 1px solid rgba(255,255,255,.08);
    border-radius: 20px; padding: 20px 24px;
    box-shadow: 0 18px 44px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.06);
    transition: transform .3s var(--ease), box-shadow .3s var(--ease), border-color .3s var(--ease);
    animation: fadeUp .6s var(--ease) both;
}
.metric-card:hover {
    transform: translateY(-4px);
    border-color: rgba(255,255,255,.15);
    box-shadow: 0 26px 60px rgba(0,0,0,.55), 0 0 44px var(--acc-a);
}
.metric-card .label { font-size: .78rem; color: var(--text-3); text-transform: uppercase; letter-spacing: .08em; margin-bottom: 8px; }
.metric-card .value { font-size: 2.15rem; font-weight: 700; color: #FFFFFF; line-height: 1.12; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
.metric-card .sub { font-size: .95rem; color: var(--text-2); margin-top: 8px; line-height: 1.45; }
.action-heat { background: linear-gradient(92deg,#FF6B35,#FFB627); -webkit-background-clip: text; background-clip: text; color: transparent; animation: glowPulse 3.2s ease-in-out infinite; }
.action-hold { background: linear-gradient(92deg,#2E7CF6,#5AC8FA); -webkit-background-clip: text; background-clip: text; color: transparent; }
.action-sell { background: linear-gradient(92deg,#C77DFF,#FF9CEE); -webkit-background-clip: text; background-clip: text; color: transparent; }
.action-warn { background: linear-gradient(92deg,#FFD166,#FF9F68); -webkit-background-clip: text; background-clip: text; color: transparent; font-weight: 650; }
.decision-box {
    position: relative;
    background: rgba(255,255,255,.05);
    backdrop-filter: blur(20px) saturate(180%); -webkit-backdrop-filter: blur(20px) saturate(180%);
    border: 1px solid rgba(255,255,255,.09);
    border-radius: 24px; padding: 28px 32px; margin-top: 24px;
    box-shadow: 0 22px 56px rgba(0,0,0,.5);
    animation: fadeUp .6s var(--ease) both;
}
.decision-box::after {
    content:""; position:absolute; inset:-1px; border-radius:25px; pointer-events:none;
    box-shadow: 0 0 70px var(--acc-a);
    animation: haloPulse 3s ease-in-out infinite;
}
.decision-box h2 { font-size: 1.6rem; margin: 0 0 12px 0; color: #FFFFFF; }
.decision-box .big { font-size: 3.2rem; font-weight: 700; line-height: 1.05;
    background: linear-gradient(92deg,var(--acc-a),var(--acc-b)); -webkit-background-clip: text; background-clip: text; color: transparent; }
.decision-box .sub { font-size: 1.02rem; color: var(--text-2); margin-top: 10px; line-height: 1.5; }
.stTabs [data-baseweb="tab-list"] { gap: 2px; background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.08);
    border-radius: 14px; padding: 4px; width: fit-content; max-width: 100%; }
.stTabs [data-baseweb="tab"] {
    background: transparent; border: none; border-radius: 11px;
    color: var(--text-3); font-weight: 550; padding: 8px 22px;
    transition: all .3s var(--ease);
}
.stTabs [data-baseweb="tab"]:hover { color: var(--text-1); }
.stTabs [aria-selected="true"] {
    background: rgba(255,255,255,.14); color: #FFFFFF; border-color: transparent;
    box-shadow: 0 2px 12px rgba(0,0,0,.35);
}
div.stButton > button {
    background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.12);
    border-radius: 980px; color: var(--text-1); font-weight: 550;
    transition: all .2s var(--ease);
}
div.stButton > button:hover { background: rgba(255,255,255,.10); border-color: rgba(255,255,255,.22); transform: scale(1.02); }
div.stButton > button:active { transform: scale(.98); }
div[data-testid="stImage"] img { border-radius: 20px; box-shadow: 0 24px 60px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.08); }
section[data-testid="stSidebar"] { background: rgba(10,10,12,.72); border-right: 1px solid rgba(255,255,255,.07); }
[data-testid="stNumberInput"] input, [data-testid="stTextInput"] input {
    background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.10);
    border-radius: 10px; color: var(--text-1);
}
[data-baseweb="select"] > div {
    background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.10);
    border-radius: 10px; color: var(--text-1);
}
.stAlert { border-radius: 16px; border: 1px solid rgba(255,255,255,.08); background: rgba(255,255,255,.04); }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="hero-title">Теплица 0.15 га — ночной автопилот</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-sub">Ночь: погода → тепло → деньги → решение. Неделя: ML-прогноз цены → ждать или везти. Логистика: куда везти и на чём.</div>', unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div class="section-title" style="margin-top:0">Паспорт теплицы</div>', unsafe_allow_html=True)
    st.markdown("#### Участок")
    lat = st.number_input("Широта, °", value=TARAZ_LAT, step=0.01, format="%.2f",
                          help="Точка участка — погода берётся именно для неё, не «средняя по Таразу»")
    lon = st.number_input("Долгота, °", value=TARAZ_LON, step=0.01, format="%.2f")
    st.markdown("#### Теплица")
    L = st.number_input("Длина, м", value=DEMO_GREENHOUSE["length"])
    W = st.number_input("Ширина, м", value=DEMO_GREENHOUSE["width"])
    H = st.number_input("Высота, м", value=DEMO_GREENHOUSE["height"])
    mat = st.selectbox("Материал", ["film", "polycarbonate", "glass"], index=0)
    crop = st.selectbox("Культура", ["cucumber", "tomato"], index=0)
    t_in = st.number_input("Целевая T внутри, °C", value=T_TARGET_C)
    st.markdown("#### Котёл и топливо")
    fuel = st.selectbox("Топливо", ["gas", "coal"], index=0)
    tariff = st.number_input("Тариф газа, тг/м3", value=GAS_TARIFF_TG_M3, step=0.5)
    st.caption("Дефолт 35 — население. Теплица часто коммерческий потребитель "
               "(~58–70 тг/м³) — сверься со своим счётом, разница в разы меняет затраты.")
    coal_q = st.selectbox("Качество угля", ["good", "poor"], index=1)
    foul = st.slider("Состояние котла", 0.5, 1.0, 0.7)
    boiler = st.number_input("Мощность котла, кВт", value=BOILER_KW_MAX, step=5.0,
                             help="С шильдика. Занижение даёт ложный «НЕ ТЯНЕТ», завышение — скрывает реальный риск.")
    readiness = st.slider("Готовность культуры", 0.0, 1.0, 0.85)
    st.markdown("#### Урожай и сбор")
    yld = st.number_input("Урожайность, кг/м²", value=YIELD_KG_M2, step=0.5)
    harvest_kg = st.number_input("Сбор, кг/день", value=300.0, step=10.0, min_value=0.0)
    shelf_days = st.number_input("Срок хранения, дней", value=5.0, step=1.0, min_value=1.0)
    marketable = st.slider("Товарный вид, %", 50, 100, 90)
    price_manual = st.number_input("Цена реализации, тг/кг (0 — авто БНС)",
                                   value=0.0, step=10.0, min_value=0.0,
                                   help="0 = берём последнюю цену БНС по культуре из своих данных")
    from datetime import date as _date, timedelta as _timedelta
    plant_date = st.date_input("Дата посадки", value=_date.today() - _timedelta(days=45))
    harvest_date = st.date_input("Ожидаемая дата сбора", value=_date.today() + _timedelta(days=21))
    st.markdown("#### Контроль")
    fact_gas = st.number_input("Фактический газ за ночь, м³ (0 — не мерил)",
                               value=0.0, step=1.0, min_value=0.0)
    farmer_text = st.text_input("Слова фермера (топливо/котёл/культура)", "")
    st.caption("Калибровка: модель станет «своей» после 7 ночей (tвнутр/tснаружи/газ/ветер) "
               "и 5 ночей датчика почвы — пока считаются с табличными U/N.")

# «Уши»: слова фермера переопределяют паспорт (LLM или keyword-фолбэк)
if farmer_text.strip():
    farm_params, farm_meta = extract_farm_state(farmer_text)
    crop = farm_params.get("crop") or crop
    fuel = farm_params.get("fuel") or fuel
    coal_q = farm_params.get("coal_quality") or coal_q
    if farm_params.get("fouling") is not None:
        foul = float(farm_params["fouling"])
    if farm_params.get("readiness") is not None:
        readiness = float(farm_params["readiness"])
    with st.sidebar:
        st.caption(f"Распознано ({farm_meta.get('source')}): {farm_params}")

t_crit = T_CRIT_CUCUMBER if crop == "cucumber" else T_CRIT_TOMATO

# Даты посадки/сбора: окно, к которому привязывается недельный прогноз цены
_days_to_harvest = (harvest_date - _date.today()).days
_veg_days = (_date.today() - plant_date).days
with st.sidebar:
    st.caption(f"Вегетация: день {_veg_days} от посадки · сбор через {_days_to_harvest} дн "
               f"· прогноз цены только на 7 дней вперёд")


def _last_bns_price(crop_name):
    """Последняя цена БНС по культуре из своих данных (месячная, иначе недельная).
    Возвращает (цена, дата) или (None, None)."""
    for p in ("data/prices_monthly.csv", "data/prices_weekly.csv"):
        try:
            df = pd.read_csv(p)
            df = df[df["crop"] == crop_name].dropna(subset=["taraz_price"])
            if len(df):
                return float(df.iloc[-1]["taraz_price"]), str(df.iloc[-1].get("date", "?"))
        except Exception:
            continue
    return None, None


# Цена для EV: ручная, иначе последняя БНС, иначе дефолт — не хардкод «отдельно»
if price_manual > 0:
    price_tg_kg, price_note = float(price_manual), "цена вручную"
else:
    _bns_p, _bns_d = _last_bns_price(crop)
    if _bns_p:
        price_tg_kg = _bns_p
        price_note = f"авто БНС от {_bns_d}: {_bns_p:.0f} тг/кг"
    else:
        price_tg_kg, price_note = float(PRICE_TG_KG), f"нет данных БНС — дефолт {PRICE_TG_KG:.0f} тг/кг"
with st.sidebar:
    st.caption(f"Цена расчёта: {price_tg_kg:.0f} тг/кг ({price_note})")

# ============ ОБЩИЙ РАСЧЁТ (один раз на ререндер, переиспользуется вкладками) ============
# 1) НОЧЬ
try:
    fc = forecast_with_spread(lat=lat, lon=lon)  # точка участка, не «средняя по Таразу»
    base_rows = fc["base"]
    weather_note = (f"погода: ансамбль open-meteo ({lat:.2f}, {lon:.2f})" if fc["source"] == "ensemble"
                    else f"погода: open-meteo ({lat:.2f}, {lon:.2f})")
except Exception as e:
    weather_note = f"нет сети — демо-ночь −5°C ({type(e).__name__})"
    base_rows = [{"T": -5.0, "wind": 3.0, "RH": 85.0,
                  "time": f"2024-03-14T{h:02d}:00"} for h in (18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5)]
res = optimize_night(base_rows, L, W, H, mat, t_in, crop, fuel,
                     coal_q, foul, boiler, L * W,
                     yld, price_tg_kg, tariff)
best = res["best"]
d = decide_ev(best["cost_tg"], best["p_freeze"], best["loss_tg"],
              0.0, 0, readiness, v_gas_m3=best["fuel_qty"],
              profile=best["name"], p_noheat=res["p_noheat"])
ACTION_RU_CARD = {"heat": "ТОПИТЬ", "sell_early": "ПРОДАВАТЬ", "hold": "ДЕРЖАТЬ"}

# Динамические акценты интерфейса: цвет следует за реальным решением модели
_ACC = {"heat": ("#FF6B35", "#FFB627"), "hold": ("#2E7CF6", "#5AC8FA"),
        "sell_early": ("#C77DFF", "#FF9CEE")}
_acc_a, _acc_b = _ACC.get(d["action"], _ACC["hold"])
st.markdown(f"""
<style>
:root {{ --acc-a: {_acc_a}; --acc-b: {_acc_b}; }}
</style>
""", unsafe_allow_html=True)

# 2) НЕДЕЛЯ (ML: месячная модель приоритет, иначе недельная)
ml_info, ml_df, ml_ds = None, None, "нет данных"
ml_pump = {"p_dump": 0.0, "days": 0, "pred": None, "base": 0.0,
           "mean": 0.0, "imp": 0.0, "risk": None}
try:
    from price_risk import load_dataset, train_ridge, dump_risk_from_model
    for csv_path, label in (("data/prices_monthly.csv", "месячная (2022-2026)"),
                            (None, "недельная (2026)")):
        try:
            cand = load_dataset(csv_path=csv_path, crop=crop)
            cand_info = train_ridge(cand)
            ml_info, ml_df, ml_ds = cand_info, cand, label
            if cand_info.get("status") == "ok":
                break
        except FileNotFoundError:
            continue
    if ml_info is not None:
        ml_pump["base"] = float(ml_df.iloc[-1]["taraz_price"])
        ml_pump["mean"] = float(ml_df.iloc[-1]["mean_price"])
        if "import_m" in ml_df.columns and not pd.isna(ml_df.iloc[-1]["import_m"]):
            ml_pump["imp"] = float(ml_df.iloc[-1]["import_m"])
        if ml_info.get("status") == "ok" and ml_info.get("pred_next"):
            ml_pump["pred"] = float(ml_info["pred_next"])
            rr = dump_risk_from_model(ml_pump["pred"], ml_pump["base"])
            ml_pump["p_dump"], ml_pump["days"] = rr["p_dump"], rr["days_to_dump"]
            ml_pump["risk"] = rr
except Exception:
    pass
week_dp = decide_price(ml_pump["base"], ml_pump["mean"], ml_pump["imp"],
                       ml_pump["p_dump"], ml_pump["days"], readiness)

# 3) ЛОГИСТИКА (дефолтная машина для сводки; параметры — во вкладке)
log_top = None
try:
    from logistics import rank_cities
    ldef = rank_cities(crop=crop)  # кэш после первого вызова
    log_top = ldef["rows"][0] if ldef["rows"] else None
except Exception:
    pass

tab1, tab2, tab3, tab4 = st.tabs(["Ночь: топить?", "Неделя: продавать?",
                                  "История", "Куда везти"])

# ============ ГЕРОЙ: быстрая сводка + 3D-разрез ============
st.markdown("## Сегодня")
h1, h2 = st.columns([3, 2], gap="large")
with h1:
    night_cls = "action-heat" if d["action"] == "heat" else "action-hold"
    ok_week = ml_info is not None and ml_info.get("status") == "ok" and ml_pump["pred"]
    week_val = "СОБРАТЬ РАНЬШЕ" if week_dp["sell_early"] else "ЖДАТЬ"
    revenue_day = (ml_pump['pred'] * harvest_kg * marketable / 100.0) if ok_week else 0.0
    harvest_sync = (f"сбор через {_days_to_harvest} дн ({harvest_date})"
                    if 0 <= _days_to_harvest <= 7
                    else (f"⚠ сбор через {_days_to_harvest} дн — вне горизонта прогноза 7 дн"
                          if _days_to_harvest > 7 else "сбор идёт сейчас"))
    week_line = (f"прогноз {ml_pump['pred']:,.0f} тг vs сейчас {ml_pump['base']:,.0f} тг "
                 f"({ml_ds}) · {harvest_sync} · выручка за день ≈ {revenue_day:,.0f} тг"
                 if ok_week
                 else "модель experimental — вердикт по цене не подаём (честно)")
    log_line = (f"{log_top['city']}: +{log_top['margin_kg']:.0f} тг/кг, {log_top['km']} км "
                f"(для дефолтной машины 22 л/100км)" if log_top else "нет региональных данных")
    boiler_warn = (' <span class="action-warn">· ⚠ котёл не тянет</span>'
                   if "НЕ ТЯНЕТ" in str(best.get("boiler", "")) else "")
    ev_line = (f"без котла риск {res['p_noheat']} (EV {res['p_noheat'] * best['loss_max_tg']:,.0f} тг) "
               f"→ с профилем {best['p_freeze']} (EV {best['ev_loss_tg']:,.0f} тг)")
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Ночь — {weather_note}</div>
        <div class="value {night_cls}">{ACTION_RU_CARD.get(d['action'], d['action'])}</div>
        <div class="sub">профиль {best['name']} · {best['fuel_qty']} {best['fuel_unit']} · {best['cost_tg']:,.0f} тг (газ){boiler_warn}</div>
        <div class="sub">{ev_line}</div>
    </div>
    <div style="height:12px"></div>
    <div class="metric-card">
        <div class="label">Неделя — цена огурца</div>
        <div class="value">{'<span class="action-sell">' if week_dp['sell_early'] else '<span class="action-hold">'}{week_val}</span></div>
        <div class="sub">{week_line}</div>
    </div>
    <div style="height:12px"></div>
    <div class="metric-card">
        <div class="label">Куда везти</div>
        <div class="value">{log_top['city'] if log_top else '—'}</div>
        <div class="sub">{log_line}</div>
    </div>
    """, unsafe_allow_html=True)
with h2:
    st.iframe(_greenhouse3d_html(d["action"]), height=420)
    with st.expander("Статичный рендер (если 3D не поддерживается)"):
        st.image("assets/greenhouse3d.png")
    st.caption("Теплица 0.15 га в разрезе: ночью холод снаружи, тепло — котёл + почва. "
               "Котёл светится под цвет решения (оранжевый — топить, синий — держать).")

with tab1:
    _cls_map = {"heat": "heat", "hold": "hold", "sell_early": "sell"}
    st.iframe(_metric_cards_html([
        {"label": "Топливо", "value": best["fuel_qty"], "dec": 1,
         "suffix": f" {best['fuel_unit']}"},
        {"label": "Затраты, тг", "value": best["cost_tg"], "dec": 0},
        {"label": "Риск заморозка", "value": best["p_freeze"], "dec": 3},
        {"label": "Решение", "text": ACTION_RU_CARD[d["action"]],
         "cls": _cls_map.get(d["action"], "")},
    ], _acc_a), height=150)

    ev_txt = f"{d['ev_loss_tg']:,.0f}"
    cost_txt = f"{best['cost_tg']:,.0f}"
    saving_txt = f"{res['saving_tg']:,.0f}"
    pstar_txt = f"{d['p_star']:.3f}"
    action_label = {"heat": "ТОПИТЬ", "sell_early": "ПРОДАВАТЬ", "hold": "ДЕРЖАТЬ"}[d["action"]]
    action_class = "action-heat" if d["action"] == "heat" else ("action-hold" if d["action"] == "hold" else "action-sell")

    st.markdown(f"""
    <div class="decision-box">
        <h2>{action_label} — профиль <span style="color:#FF8A5B">{best['name']}</span></h2>
        <div class="big">{ev_txt}</div>
        <div class="sub">Экономия EV {ev_txt} тг против затрат {cost_txt} тг = газ {best['fuel_qty']} {best['fuel_unit']} × {tariff} тг (p*={pstar_txt}). Экономия профиля: {saving_txt} тг/ночь. Цена: {price_tg_kg:.0f} тг/кг.</div>
        <div class="sub" style="margin-top:10px">Котел: {best['boiler']}. Старт: {best['start_at']}. Причина: {d['reason']}</div>
    </div>
    """, unsafe_allow_html=True)

    rhs = [r.get("RH", 80) for r in base_rows]
    td = dew_point_magnus(min(r["T"] for r in base_rows), max(rhs))
    try:
        prof_noheat = simulate_no_heat(base_rows, L, W, H, mat, t_in_start=t_in)
        t_in_series = [r["T_in"] for r in prof_noheat]
    except Exception:
        t_in_series = [t_in] * len(rhs)
    dz = disease_flag(rhs, t_in_series)
    st.caption(f"Роса ~{td}°C. Гниль: {'ДА — проветрить' if dz['risk'] else 'нет'}. Tcrit {t_crit}°C.")

    if fact_gas > 0:
        ag = anomaly_guard(float(fact_gas), float(best["fuel_qty"]), best["p_freeze"])
        if ag["flag"]:
            st.warning(ag["note"])
        else:
            st.success(f"Факт {fact_gas} м³ — в пределах модели (±30%).")
    else:
        st.caption("Фактический газ не введён — «сторожилка» не проверяет модель.")

    with st.expander("Все 3 профиля"):
        st.dataframe(pd.DataFrame(res["options"]), width='stretch')

    text, used = verbalize_v2(d, options=res["options"], farmer_text="")
    st.markdown('<div class="section-title">Решение текстом</div>', unsafe_allow_html=True)
    st.write(text)
    st.caption("LLM" if used else "Шаблон без LLM")

with tab2:
    st.markdown('<div class="section-title">Ценовой риск — Ridge (ML)</div>', unsafe_allow_html=True)
    st.caption("p_dump — индекс 0-1, не вероятность (калибровка Platt в планах). Обучение: месячные цены Тараза 2022-2026.")
    if ml_info is not None:
        st.write(f"Модель: {ml_ds} | строк: {ml_info.get('n')}, статус: {ml_info.get('status')}, "
                 f"MAE {ml_info.get('mae')} vs лаг {ml_info.get('mae_lag')}, "
                 f"прогноз: {ml_info.get('pred_next')}")
        if ml_pump.get("risk"):
            st.write(ml_pump["risk"])
        else:
            st.caption("Ни одна модель не побила базлайн — индекс риска не считается (честно).")
    else:
        st.caption("Датасеты цен не найдены (prices_monthly/weekly.csv).")

    # недельное решение: только sell_early/hold, «топить» на этом экране невозможно
    dp = week_dp
    action_label2 = {"sell_early": "СОБРАТЬ РАНЬШЕ", "hold": "ЖДАТЬ"}[dp["action"]]
    action_class2 = "action-sell" if dp["sell_early"] else "action-hold"
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Совет по рынку</div>
        <div class="value {action_class2}">{action_label2}</div>
        <div class="sub">{dp['reason']}</div>
    </div>
    """, unsafe_allow_html=True)

    pv = price_verdict(ml_pump["base"], ml_pump["mean"], ml_pump["imp"],
                       ml_pump["p_dump"], ml_pump["days"], readiness)
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Импорт / рынок</div>
        <div class="value">{pv['text']}</div>
        <div class="sub">Дней до просадки: {pv['days_to_dump']}</div>
    </div>
    """, unsafe_allow_html=True)

with tab3:
    st.markdown('<div class="section-title">Контрфакт 13–15.03.2024 (−11°C)</div>', unsafe_allow_html=True)
    try:
        hist = pd.read_csv("data/taraz_2024-03-13_15_real.csv")
        st.line_chart(hist.set_index("time")[["T"]], width='stretch')
        hrs = hist["time"].astype(str).str[11:13].astype(int)
        night = hist[(hrs >= 18) | (hrs <= 6)].to_dict("records")
        night = [{"T": float(r["T"]), "wind": float(r.get("wind", 3)), "time": str(r["time"])} for r in night]
        hres = optimize_night(night, L, W, H, mat, t_in, crop, fuel,
                              coal_q, foul, boiler, L * W, yld, price_tg_kg, tariff)
        st.dataframe(pd.DataFrame(hres["options"]), width='stretch')
        st.success(f"best={hres['best']['name']}: {hres['best']['fuel_qty']} {hres['best']['fuel_unit']} / {hres['best']['cost_tg']:,.0f} тг")
    except Exception as e:
        st.error(f"Нет истории: {e}")

with tab4:
    st.markdown('<div class="section-title">Логистика: куда везти (твоя машина)</div>',
                unsafe_allow_html=True)
    st.caption("Введи параметры своего транспорта — посчитает чистую маржу по 19 городам "
               "и построит маршрут. Допущения: дорога = прямая×1.25, 70 км/ч, возврат порожняком.")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        log_cons = st.number_input("Расход, л/100 км", value=22.0, step=0.5, min_value=5.0)
    with c2:
        log_cap = st.number_input("Вместимость, тонн",
                                  value=max(round(harvest_kg / 1000.0, 1), 0.3),
                                  step=0.5, min_value=0.3)
    with c3:
        log_fuel = st.number_input("Цена топлива, тг/л", value=280.0, step=5.0)
    with c4:
        log_drv = st.number_input("Водитель, тг/сутки", value=15000.0, step=1000.0)
    c5, c6 = st.columns(2)
    with c5:
        log_ref = st.checkbox("Рефрижератор (+2.5 л/ч)", value=True)
    with c6:
        log_days = st.slider("Суток на рейс", 1, 7, 3)
    try:
        from logistics import rank_cities, greedy_route
        lout = rank_cities(crop=crop, capacity_kg=log_cap * 1000.0,
                           consum_l100=log_cons, fuel_price=log_fuel,
                           ref=log_ref, driver_pay_per_day=log_drv)
        m = lout["month"]
        st.write(f"Цены: {m[1]:02d}.{m[0]} | цена дома (Тараз): {lout['home']:.0f} тг/кг | "
                 f"машина: {log_cons} л/100км, {log_cap} т, реф={'да' if log_ref else 'нет'}")
        df_log = pd.DataFrame(lout["rows"]).rename(columns={
            "city": "Город", "price": "Цена_тгкг", "km": "Дорога_км",
            "trip_tg": "Рейс_туда+обратно_тг", "cost_kg": "Себестоимость_тгкг",
            "margin_kg": "Маржа_тгкг", "margin_trip_tg": "Маржа_за_рейс_тг"})
        st.dataframe(df_log, width='stretch', hide_index=True)
        route = greedy_route(lout["rows"], log_days, capacity_kg=log_cap * 1000.0,
                             cargo_kg=min(log_cap * 1000.0, harvest_kg * log_days))
        if route["legs"]:
            path = " → ".join(["Тараз"] + [x["city"] for x in route["legs"]] + ["Тараз"])
            shelf_warn = (' <span style="color:#FFD166">⚠ дольше срока хранения — '
                          f"учти {shelf_days:.0f} дн</span>"
                          if route["days_used"] > shelf_days else "")
            st.markdown(f"""
            <div class="metric-card">
                <div class="label">Лучший маршрут на {log_days} суток</div>
                <div class="value">{path}</div>
                <div class="sub">{route['total_km']} км, ~{route['days_used']} суток в пути, груз
                {route['cargo_used_kg']:,.0f} из {route['cargo_total_kg']:,.0f} кг,
                маржа ≈ {route['margin_tg']:,.0f} тг (груз один на весь маршрут,
                возврат порожняком — консервативно){shelf_warn}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning("При таких расходах ни один город не даёт положительной маржи — держать дома.")
    except Exception as e:
        st.error(f"Логистика: {type(e).__name__}: {e}")

