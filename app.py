"""Alvea PMV — horarios por tienda bajo la reforma de 40 horas (Autoservicio MX, ficticio).

Rediseño 24-sep-2026 (v2 de la interfaz). Principios:
  1. Cada rol ve SOLO lo que usa: el gerente ve su horario, su tienda y sus
     avisos; el admin/HQ agrega el resumen de la red, historial y usuarios.
  2. Una sola "semana activa" compartida por todas las vistas. Arranca HOY.
  3. El régimen legal (48 h en 2026 -> 40 h en 2030) sale de la fecha de la
     semana; nadie tiene que escoger un "año de régimen".
  4. Nada se calcula con un botón escondido: abrir una semana la calcula.
  5. Un día se lee como lo arma un gerente: 4 turnos fijos y quién está en
     cada uno. Cambiar a alguien = persona -> turno. Nada de arrastrar.

Correr local:  streamlit run app.py   (ver README.md)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

from jornada40 import (auditoria, calendario, costos_ahorro, datos_sinteticos, demanda_personal,
                        escenario_base, notificaciones, optimizador, reglas, usuarios, vista_red)

# Streamlit Cloud recarga app.py en cada deploy, pero puede dejar en memoria la
# versión anterior de los módulos de jornada40 (pasó el 24-sep-2026: interfaz
# nueva con optimizador viejo). Si la versión del modelo no coincide, se
# recargan todos los módulos del paquete.
def _asegurar_modulos_al_dia(version: str) -> None:
    import importlib
    import sys
    if getattr(optimizador, "VERSION_MODELO", None) == version:
        return
    for nombre in sorted([m for m in sys.modules if m.startswith("jornada40.")]):
        importlib.reload(sys.modules[nombre])
    st.cache_data.clear()


st.set_page_config(page_title="Alvea", page_icon=":material/calendar_month:", layout="wide",
                   initial_sidebar_state="auto")

DATA_DIR = Path("data")
TIEMPO_LIMITE_SEG = 10.0
# Súbelo cada vez que cambie el modelo (optimizador, demanda, calibración): forma parte de
# la llave de la caché, así un despliegue nuevo nunca sirve horarios calculados con el
# modelo anterior (pasó el 24-sep-2026: la caché de Streamlit Cloud sobrevivió al deploy).
VERSION_MODELO = "2026-09-24-agregado-por-area-b"
_asegurar_modulos_al_dia(VERSION_MODELO)
ZONA_HORARIA = ZoneInfo("America/Mexico_City")
FIN_HORIZONTE = date(2030, 12, 31)   # última fecha de la reducción escalonada (40 h)

# Colores de turno: primeros 4 tonos de la paleta categórica validada
# (skill dataviz, references/palette.md), en orden fijo. Siempre van con
# su nombre en texto al lado -- el color nunca es la única señal.
COLOR_TURNO = {"Apertura": "#2a78d6", "Intermedio": "#eb6834",
               "Refuerzo pico": "#1baf7a", "Cierre": "#eda100"}
# Color por área (slots 5-8 de la misma paleta validada, distintos de los de turno).
# Siempre acompañado del nombre del área en texto.
ROL_COLOR = {"cajas": "#e87ba4", "piso_reposicion": "#008300", "perecederos": "#4a3aa7", "almacen": "#e34948"}
ROL_ETIQUETA = {"cajas": "Cajas", "piso_reposicion": "Piso", "perecederos": "Perecederos",
                "almacen": "Almacén"}
DIAS_LARGOS = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
MESES_CORTOS = ["", "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def hoy() -> date:
    return datetime.now(ZONA_HORARIA).date()


SEMANA_MIN = calendario.semana_de(hoy())[0]
SEMANA_MAX = calendario.semana_de(FIN_HORIZONTE)[0]


def anio_regimen(domingo: date) -> int:
    """Año cuyas reglas aplican a la semana. Se toma el del SÁBADO: si la
    semana cruza de año (p. ej. 27-dic al 2-ene), aplica ya el tope nuevo,
    que siempre es el más estricto -- así el horario nunca queda fuera de ley."""
    return (domingo + timedelta(days=6)).year


def horas_regimen(domingo: date) -> int:
    return int(reglas.regla_vigente("jornada_ordinaria_semanal_horas", date(anio_regimen(domingo), 1, 1)))


def fmt_rango_semana(domingo: date) -> str:
    sab = domingo + timedelta(days=6)
    if domingo.month == sab.month:
        return f"{domingo.day}–{sab.day} {MESES_CORTOS[sab.month]} {sab.year}"
    return f"{domingo.day} {MESES_CORTOS[domingo.month]} – {sab.day} {MESES_CORTOS[sab.month]} {sab.year}"


def fmt_dia(f: date) -> str:
    return f"{DIAS_LARGOS[(f.weekday() + 1) % 7]} {f.day} de {calendario.NOMBRES_MES[f.month].lower()}"


def mxn(v: float) -> str:
    return f"${v:,.0f}"


# ---------------------------------------------------------------------------
# Datos (sintéticos por semana, o los que suba HQ)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def datos_fijos() -> dict[str, pd.DataFrame]:
    tiendas = datos_sinteticos.generar_tiendas(seed=42)
    return {"tiendas": tiendas, "plantilla": datos_sinteticos.generar_plantilla(tiendas, seed=42)}


@st.cache_data(show_spinner=False, max_entries=60)
def datos_semana_ejemplo(domingo: date) -> dict[str, pd.DataFrame]:
    f = datos_fijos()
    return datos_sinteticos.generar_semana(f["tiendas"], f["plantilla"], domingo, seed=42)


def _normalizar_fechas(df: pd.DataFrame) -> pd.DataFrame:
    if "fecha" in df.columns:
        df = df.copy()
        df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
    return df


def datos_semana(domingo: date) -> dict[str, pd.DataFrame]:
    """Las 5 tablas para la semana. Si HQ subió archivos propios, esos ganan."""
    subidos = st.session_state.get("datos_subidos", {})
    fijos = datos_fijos()
    base = {"tiendas": subidos.get("tiendas", fijos["tiendas"]),
            "plantilla": subidos.get("plantilla", fijos["plantilla"])}
    sabado = domingo + timedelta(days=6)
    ejemplo = None
    for n in ("trafico", "ventas", "ausentismo"):
        if n in subidos:
            df = _normalizar_fechas(subidos[n])
            base[n] = df[(df["fecha"] >= domingo) & (df["fecha"] <= sabado)]
        else:
            ejemplo = ejemplo or datos_semana_ejemplo(domingo)
            base[n] = _normalizar_fechas(ejemplo[n])
    return base


@st.cache_data(show_spinner=False, max_entries=400)
def calcular_semana_tienda(tienda_id: str, domingo: date, version_datos: int,
                           version_modelo: str = VERSION_MODELO) -> dict:
    """Base (cómo se programa hoy) + propuesta del optimizador + techo, 1 tienda, 1 semana."""
    anio = anio_regimen(domingo)
    d = datos_semana(domingo)
    tiendas_t = d["tiendas"].loc[d["tiendas"]["tienda_id"] == tienda_id]
    plantilla_t = d["plantilla"].loc[d["plantilla"]["tienda_id"] == tienda_id]
    trafico_t = d["trafico"].loc[d["trafico"]["tienda_id"] == tienda_id]
    ventas_t = d["ventas"].loc[d["ventas"]["tienda_id"] == tienda_id]
    ausentismo_t = d["ausentismo"].loc[d["ausentismo"]["empleado_id"].isin(set(plantilla_t["empleado_id"]))]

    demanda = demanda_personal.marcar_franjas_pico(
        demanda_personal.calcular_demanda_tienda(tienda_id, trafico_t, ventas_t, tiendas_t))
    base = escenario_base.calcular_horario_base_tienda(
        tienda_id, anio, plantilla_t, ausentismo_t, demanda, fecha_inicio=domingo)
    propuesta = optimizador.resolver_tienda(
        tienda_id, anio, plantilla_t, demanda, ausentismo_t,
        tiempo_limite_seg=TIEMPO_LIMITE_SEG, fecha_inicio=domingo)
    techo = optimizador.resolver_techo_teorico(
        tienda_id, anio, plantilla_t, demanda, ausentismo_t,
        tiempo_limite_seg=TIEMPO_LIMITE_SEG, fecha_inicio=domingo)
    reporte = costos_ahorro.generar_reporte_cfo(tienda_id, base, propuesta, techo, anio)
    reporte.update({"status": propuesta["status"], "propuesta": propuesta, "base": base,
                    "demanda": demanda, "fecha_inicio": domingo, "anio": anio,
                    "plantilla": plantilla_t, "ausentismo": ausentismo_t})
    return reporte


@st.cache_resource
def registro_calculadas() -> set:
    """(tienda, semana, versión de datos) ya calculadas en este servidor. Compartido entre
    sesiones: si HQ prepara las 50 tiendas antes de la demo, todos las ven al instante."""
    return set()


def marcar_calculada(tienda_id: str, domingo: date) -> None:
    registro_calculadas().add((tienda_id, domingo, version_datos(), VERSION_MODELO))
    st.session_state.setdefault("_semanas_vistas", set()).add((tienda_id, domingo))


def esta_calculada(tienda_id: str, domingo: date) -> bool:
    return (tienda_id, domingo, version_datos(), VERSION_MODELO) in registro_calculadas()


def version_datos() -> int:
    return int(st.session_state.get("version_datos", 0))


# ---------------------------------------------------------------------------
# Usuarios, sesión y permisos
# ---------------------------------------------------------------------------

_ESQUEMA_USUARIOS_VERSION = 3
_RUTA_ESTADO_USUARIOS = DATA_DIR / "usuarios_estado.csv"


@st.cache_data(show_spinner=False)
def _cargar_usuarios(_tiendas: pd.DataFrame, _version: int = _ESQUEMA_USUARIOS_VERSION) -> pd.DataFrame:
    return usuarios.generar_usuarios(_tiendas, seed=42)


def _cargar_estado_usuarios() -> tuple[dict[str, bool], dict[str, str]]:
    if not _RUTA_ESTADO_USUARIOS.exists():
        return {}, {}
    try:
        estado = pd.read_csv(_RUTA_ESTADO_USUARIOS)
        activos = dict(zip(estado["usuario"], estado["activo"]))
        correos = dict(zip(estado["usuario"], estado["email"].fillna(""))) if "email" in estado.columns else {}
        return activos, correos
    except Exception:
        return {}, {}


def _guardar_estado_usuarios(usuarios_df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    usuarios_df[["usuario", "activo", "email"]].to_csv(_RUTA_ESTADO_USUARIOS, index=False)


def usuarios_con_estado() -> pd.DataFrame:
    """Base + overrides de activo/email guardados en disco (compartidos entre sesiones)."""
    base = _cargar_usuarios(datos_fijos()["tiendas"]).copy()
    base["email"] = ""
    activos, correos = _cargar_estado_usuarios()
    if activos:
        base["activo"] = [bool(activos.get(u, a)) for u, a in zip(base["usuario"], base["activo"])]
    if correos:
        base["email"] = base["usuario"].map(correos).fillna("")
    return base


def alcance_de(auth_: dict) -> tuple[str, str | None]:
    if auth_["rol"] == "manager":
        return "tienda", auth_["tienda_id"]
    if auth_["rol"] == "admin":
        return "zona", auth_["zona_id"]
    return "red", None


def registrar(tipo: str, detalle: str = "", alcance: tuple[str, str | None] | None = None) -> None:
    a = st.session_state["auth"]
    tipo_alc, valor_alc = alcance or alcance_de(a)
    auditoria.registrar_evento(DATA_DIR, a["usuario"], a["rol"], tipo_alc, valor_alc, tipo, detalle=detalle)


def tiendas_visibles(auth_: dict) -> pd.DataFrame:
    tiendas = datos_fijos()["tiendas"]
    if auth_["rol"] == "manager":
        return tiendas[tiendas["tienda_id"] == auth_["tienda_id"]]
    if auth_["rol"] == "admin":
        return usuarios.tiendas_de_zona(auth_["zona_id"], tiendas)
    return tiendas


# ---------------------------------------------------------------------------
# Estilo
# ---------------------------------------------------------------------------

CSS = """
<style>
:root {
  --ink: #1d1d1f; --ink-2: #6e6e73; --ink-3: #8e8e93;
  --line: #e5e5ea; --line-2: #d2d2d7; --fill: #f5f5f7; --surface: #ffffff;
  --accent: #0071e3; --accent-soft: #eaf3ff;
  --good: #1f8a3b; --warn: #b25e00; --bad: #c9252c;
}
html, body, [class*="css"], .stApp { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Segoe UI", sans-serif; }
.stApp { background: #fbfbfd; color: var(--ink); }
[data-testid="stToolbar"], footer, #MainMenu, [data-testid="stDecoration"],
[data-testid="InputInstructions"] { display: none !important; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1180px; }
h1, h2, h3 { letter-spacing: -0.02em; color: var(--ink); }

/* ---------- barra lateral ---------- */
section[data-testid="stSidebar"] { background: #f7f7f9; border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding-top: 0.5rem; }
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] { height: 2.2rem; }
section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] { gap: 0.2rem; }
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.sb-grupo) { margin-bottom: 6px; overflow: visible; }
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"]:has(.sb-grupo) { margin-bottom: 0 !important; }
.sb-grupo { display: block; min-height: 28px; box-sizing: border-box; }
/* cargador de archivos en español */
[data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
[data-testid="stFileUploaderDropzone"] button { font-size: 0 !important; }
[data-testid="stFileUploaderDropzone"] button::after { content: "Elegir CSV"; font-size: 13.5px; }
.sb-marca { font-size: 19px; font-weight: 700; letter-spacing: -0.02em; padding: 2px 10px 0; }
.sb-sub { font-size: 12px; color: var(--ink-2); padding: 0 10px 18px; }
.sb-grupo { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase;
            color: var(--ink-3); padding: 16px 10px 6px; line-height: 1; }
div[class*="st-key-nav_"] button {
  width: 100%; justify-content: flex-start; border: none; background: transparent; box-shadow: none;
  border-radius: 8px; padding: 7px 10px; min-height: 0; color: var(--ink); }
div[class*="st-key-nav_"] button p { font-size: 14px; }
div[class*="st-key-nav_"] button, div[class*="st-key-nav_"] button > div { justify-content: flex-start !important; text-align: left; }
div[class*="st-key-nav_"] button:hover { background: #ececf0; color: var(--ink); }
div[class*="st-key-nav_"] button:focus:not(:active) { color: var(--ink); border: none; box-shadow: none; }
.sb-usuario { display: flex; gap: 10px; align-items: center; padding: 12px 10px; margin: 18px 0 6px;
              border-top: 1px solid var(--line); }
.sb-avatar { width: 32px; height: 32px; border-radius: 999px; background: var(--ink); color: #fff;
             font-size: 12px; font-weight: 600; display: flex; align-items: center; justify-content: center; flex: 0 0 32px; }
.sb-nombre { font-size: 13px; font-weight: 600; line-height: 1.2; }
.sb-ambito { font-size: 11.5px; color: var(--ink-2); }
div[class*="st-key-sb_salir"] button {
  width: 100%; border-radius: 8px; border: 1px solid var(--line-2); background: #fff;
  font-size: 13px; min-height: 0; padding: 6px 10px; color: var(--ink); }

/* ---------- encabezado de página ---------- */
.pg-titulo { font-size: 28px; font-weight: 700; letter-spacing: -0.025em; margin: 0; line-height: 1.15; }
.pg-contexto { font-size: 13.5px; color: var(--ink-2); margin: 4px 0 18px; }
.pill { display: inline-block; font-size: 12px; font-weight: 600; padding: 3px 9px; border-radius: 999px;
        background: var(--fill); color: var(--ink); border: 1px solid var(--line); margin-left: 6px; }
.pill-azul { background: var(--accent-soft); color: var(--accent); border-color: transparent; }

/* ---------- tarjetas de métricas ---------- */
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 4px 0 20px; }
.tile { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; }
.tile-l { font-size: 12.5px; color: var(--ink-2); }
.tile-v { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; margin-top: 2px; font-variant-numeric: tabular-nums; }
.tile-s { font-size: 12px; color: var(--ink-2); margin-top: 2px; }
.tile-hero { background: var(--ink); border-color: var(--ink); }
.tile-hero .tile-l, .tile-hero .tile-s { color: #c7c7cc; }
.tile-hero .tile-v { color: #fff; }
.bien { color: var(--good) !important; } .mal { color: var(--bad) !important; } .ojo { color: var(--warn) !important; }

/* ---------- barra de navegación de fechas ---------- */
div[class*="st-key-navf_"] button {
  border-radius: 999px; border: 1px solid var(--line-2); background: #fff; min-height: 0;
  padding: 5px 14px; color: var(--ink); box-shadow: none; }
div[class*="st-key-navf_"] button:hover { border-color: var(--accent); color: var(--accent); }
.nav-titulo { font-size: 20px; font-weight: 650; letter-spacing: -0.01em; white-space: nowrap; }
.nav-titulo .pill { vertical-align: 3px; }

/* ---------- calendario: mes ---------- */
.cal-dow { text-align: center; font-size: 11px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase;
           color: var(--ink-3); padding-bottom: 4px; }
div[class*="st-key-mes_"] button {
  width: 100%; aspect-ratio: 1.35; min-height: 3.2rem; border-radius: 12px; border: 1px solid var(--line);
  background: #fff; color: var(--ink); font-size: 15px; font-weight: 500; box-shadow: none;
  align-items: flex-start; justify-content: flex-start; padding: 8px 11px; }
div[class*="st-key-mes_"] button:hover:not(:disabled) { border-color: var(--accent); background: #f7fbff; color: var(--ink); }
div[class*="st-key-mes_"] button:disabled { background: transparent; border-color: transparent; color: #c7c7cc; }
div[class*="st-key-mes_"][class*="-hoy"] button { border: 2px solid var(--accent); color: var(--accent); font-weight: 700; }
div[class*="st-key-mes_"][class*="-sel"] button { background: var(--accent-soft); }
div[class*="st-key-mes_"] button > div { justify-content: flex-start !important; }
div[class*="st-key-mes_"] button p { white-space: pre-line; text-align: left; line-height: 1.35; margin: 0; }
div[class*="st-key-mes_"] button { aspect-ratio: auto !important; min-height: 5.6rem !important; height: auto;
  align-items: flex-start !important; }
div[class*="st-key-mes_"] button p { line-height: 1.5 !important; }
div[class*="st-key-mes_"] button p br + br { display: none; }
div[class*="st-key-mes_"] button > div, div[class*="st-key-mes_"] button [data-testid="stMarkdownContainer"] {
  width: 100%; justify-content: flex-start !important; text-align: left; }
div[class*="st-key-mes_"][class*="-ok"] button, div[class*="st-key-mes_"][class*="-falta"] button,
div[class*="st-key-mes_"][class*="-caro"] button { box-shadow: inset 0 -4px 0 #1baf7a; }
div[class*="st-key-mes_"][class*="-falta"] button { box-shadow: inset 0 -4px 0 #eb6834; }
div[class*="st-key-mes_"][class*="-caro"] button { box-shadow: inset 0 -4px 0 #eda100; }
div[class*="st-key-mes_"] button p { font-size: 12px; color: var(--ink-2); }
div[class*="st-key-mes_"] button p strong { font-size: 15px; color: var(--ink); }
.cal-vacia { min-height: 5.6rem; }

/* ---------- calendario: semana ---------- */
div[class*="st-key-sem_"] button {
  width: 100%; border: none; background: transparent; box-shadow: none; padding: 2px 0 6px; min-height: 0;
  color: var(--ink); }
div[class*="st-key-sem_"] button p { font-size: 13px; font-weight: 600; }
div[class*="st-key-sem_"] button:hover { color: var(--accent); }
div[class*="st-key-sem_"][class*="-hoy"] button { color: var(--accent); }
.sem-col { border: 1px solid var(--line); border-radius: 12px; background: #fff; padding: 8px; }
.sem-turno { display: flex; align-items: center; justify-content: space-between; font-size: 12px; padding: 5px 6px;
             border-radius: 7px; background: var(--fill); margin-bottom: 5px; }
.sem-turno b { font-variant-numeric: tabular-nums; }
.sem-turno .h { color: var(--ink-2); font-size: 11px; }
.punto { display: inline-block; width: 8px; height: 8px; border-radius: 999px; margin-right: 6px; flex: 0 0 8px; }
.sem-pie { font-size: 11.5px; color: var(--ink-2); text-align: center; padding-top: 2px; }
.sem-ahorro { font-size: 13px; font-weight: 650; text-align: center; padding-top: 4px; font-variant-numeric: tabular-nums; }

/* ---------- calendario: día ---------- */
.turno-card { background: #fff; border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
.turno-cab { padding: 10px 12px 8px; border-bottom: 1px solid var(--line); }
.turno-nombre { font-size: 14px; font-weight: 650; display: flex; align-items: center; }
.turno-horas { font-size: 12px; color: var(--ink-2); margin-top: 1px; }
.turno-lista { padding: 6px 12px 10px; max-height: 420px; overflow-y: auto; }
.persona { display: flex; justify-content: space-between; gap: 6px; font-size: 13px; padding: 4px 0;
           border-bottom: 1px solid #f2f2f5; }
.persona:last-child { border-bottom: none; }
.persona .rol { font-size: 11px; color: var(--ink-2); white-space: nowrap; }
.persona.cambio { background: #fff8e6; margin: 0 -12px; padding: 4px 12px; }
.persona.sel { background: var(--accent-soft); margin: 0 -12px; padding: 4px 12px; box-shadow: inset 3px 0 0 var(--accent); font-weight: 600; }
.persona .pn { display: flex; align-items: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.estado-sel { font-size: 13.5px; margin-top: 8px; display: flex; align-items: center; }
.leyenda { font-size: 12px; color: var(--ink-2); }
.aviso { border-radius: 12px; padding: 12px 14px; font-size: 13.5px; margin: 6px 0 14px; border: 1px solid var(--line); background: #fff; }
.aviso b { font-weight: 650; }
.aviso-bien { border-left: 4px solid var(--good); }
.aviso-ojo { border-left: 4px solid var(--warn); }
.aviso-mal { border-left: 4px solid var(--bad); }
.seccion { font-size: 15px; font-weight: 650; margin: 18px 0 8px; }
div[data-testid="stExpander"] { border-radius: 12px; border-color: var(--line); background: #fff; }
div[class*="st-key-panel_cambio"] { background: #fff; border-radius: 14px !important; border-color: var(--line) !important;
  margin-bottom: 16px; }
div[class*="st-key-panel_cambio"] .aviso { margin-bottom: 0; }
div[class*="st-key-panel_calcular"] { background: #fff; border-radius: 14px !important; border-color: var(--line) !important; }
@media (max-width: 640px) {
  div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-navf_hoy"]) { flex-wrap: wrap !important; gap: 8px !important; }
  div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-navf_hoy"]) > div[data-testid="stColumn"] {
    width: auto !important; flex: 0 0 auto !important; min-width: 0 !important; }
  .nav-titulo { font-size: 17px; white-space: normal; margin-bottom: 8px; }
  .pg-titulo { font-size: 24px; }
}
</style>
"""

CSS_LOGIN = """
<style>
section[data-testid="stSidebar"], header[data-testid="stHeader"] { display: none; }
.block-container { max-width: 400px; padding-top: 14vh; }
div[data-testid="stForm"] { border: 1px solid var(--line); border-radius: 18px; background: #fff; padding: 28px 26px 18px; }
.lg-marca { font-size: 30px; font-weight: 700; letter-spacing: -0.03em; text-align: center; margin-bottom: 22px; }
.lg-sub { font-size: 14px; color: var(--ink-2); text-align: center; margin-bottom: 22px; }
.lg-pie { font-size: 12px; color: var(--ink-3); text-align: center; margin-top: 14px; }
</style>
"""


def encabezado(titulo: str, contexto: str = "") -> None:
    st.markdown(f"<div class='pg-titulo'>{titulo}</div><div class='pg-contexto'>{contexto}</div>",
                unsafe_allow_html=True)


def tiles(items: list[tuple]) -> None:
    """items: (etiqueta, valor, subtítulo, clase_valor, hero)."""
    html = "".join(
        f"<div class='tile{' tile-hero' if len(it) > 4 and it[4] else ''}'>"
        f"<div class='tile-l'>{it[0]}</div>"
        f"<div class='tile-v {it[3] if len(it) > 3 and it[3] else ''}'>{it[1]}</div>"
        f"<div class='tile-s'>{it[2] if len(it) > 2 else ''}</div></div>"
        for it in items
    )
    st.markdown(f"<div class='tiles'>{html}</div>", unsafe_allow_html=True)


def aviso(texto: str, tipo: str = "bien") -> None:
    st.markdown(f"<div class='aviso aviso-{tipo}'>{texto}</div>", unsafe_allow_html=True)


def pill_regimen(domingo: date) -> str:
    return f"<span class='pill pill-azul'>Jornada {horas_regimen(domingo)} h · {anio_regimen(domingo)}</span>"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

st.markdown(CSS, unsafe_allow_html=True)

if "auth" not in st.session_state:
    st.markdown(CSS_LOGIN, unsafe_allow_html=True)
    st.markdown("<div class='lg-marca'>Alvea</div>", unsafe_allow_html=True)
    with st.form("form_login"):
        usuario_txt = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        enviado = st.form_submit_button("Entrar", type="primary", width="stretch")
    if enviado:
        fila = usuarios.buscar_usuario(usuario_txt, usuarios_con_estado())
        if fila is None:
            st.error("No encontramos ese usuario.")
        elif not fila["activo"]:
            st.error("Esta cuenta está desactivada. Pide a HQ que la reactive.")
        elif password != usuarios.password_login():
            st.error("Contraseña incorrecta.")
        else:
            st.session_state["auth"] = {"rol": fila["rol"], "tienda_id": fila["tienda_id"],
                                        "zona_id": fila["zona_id"], "usuario": fila["usuario"]}
            registrar("sesion_iniciada")
            st.rerun()
    st.stop()

auth_real = st.session_state["auth"]
usuarios_df = usuarios_con_estado()
_fila_actual = usuarios.buscar_usuario(auth_real["usuario"], usuarios_df)
if _fila_actual is None or not _fila_actual["activo"]:
    del st.session_state["auth"]
    st.error("Esta cuenta fue desactivada. Pide a HQ que la reactive.")
    st.stop()

tiendas_df = datos_fijos()["tiendas"]

# ---------------------------------------------------------------------------
# Estado compartido: semana activa, vista del calendario
# ---------------------------------------------------------------------------

st.session_state.setdefault("semana", SEMANA_MIN)
st.session_state.setdefault("dia", max(hoy(), SEMANA_MIN))
st.session_state.setdefault("cal_vista", "Semana")
st.session_state.setdefault("ediciones", {})


def ir_a_fecha(f: date) -> None:
    f = min(max(f, SEMANA_MIN), FIN_HORIZONTE)
    st.session_state["dia"] = f
    st.session_state["semana"] = calendario.semana_de(f)[0]


# ---------------------------------------------------------------------------
# Barra lateral: navegación arriba, persona y salida abajo
# ---------------------------------------------------------------------------

auth = auth_real
PAGINAS = {  # etiqueta -> ícono
    "Resumen": "insights", "Horario": "calendar_month", "Tienda": "storefront",
    "Avisos": "notifications", "Historial": "history", "Usuarios": "group",
    "Reglas legales": "gavel", "Datos": "upload_file",
}

with st.sidebar:
    st.markdown("<div class='sb-marca'>Alvea</div><div class='sb-sub'>Autoservicio MX</div>",
                unsafe_allow_html=True)

    if auth_real["rol"] == "super_admin":
        opciones = (["Toda la red"] + [f"Zona {i['nombre']}" for i in usuarios.ZONAS.values()]
                    + [f"Tienda {t}" for t in tiendas_df["tienda_id"]])
        ver_como = st.selectbox("Ver como", opciones, key="ver_como",
                                help="Muestra la app como la vería otro perfil. Tus permisos no cambian.")
        if ver_como.startswith("Zona "):
            zid = next(z for z, i in usuarios.ZONAS.items() if i["nombre"] == ver_como[5:])
            auth = {**auth_real, "rol": "admin", "zona_id": zid}
        elif ver_como.startswith("Tienda "):
            auth = {**auth_real, "rol": "manager", "tienda_id": ver_como[7:]}

    if auth["rol"] == "manager":
        grupos = {"": ["Horario", "Tienda", "Avisos"]}
    else:
        grupos = {"Operación": ["Resumen", "Horario", "Tienda"], "Control": ["Avisos", "Historial", "Usuarios"]}
        if auth_real["rol"] == "super_admin":
            grupos["HQ"] = ["Reglas legales", "Datos"]
    paginas = [p for ps in grupos.values() for p in ps]
    st.session_state.setdefault("pagina", paginas[0])
    if st.session_state["pagina"] not in paginas:
        st.session_state["pagina"] = paginas[0]

    n_avisos = len(notificaciones.no_leidas_para(DATA_DIR, auth_real))
    for grupo, ps in grupos.items():
        if grupo:
            st.markdown(f"<div class='sb-grupo'>{grupo}</div>", unsafe_allow_html=True)
        for p in ps:
            etiqueta = "Mi tienda" if (p == "Tienda" and auth["rol"] == "manager") else p
            if p == "Avisos" and n_avisos:
                etiqueta = f"Avisos · {n_avisos}"
            if st.button(etiqueta, key=f"nav_{p.replace(' ', '_')}", icon=f":material/{PAGINAS[p]}:",
                         width="stretch"):
                st.session_state["pagina"] = p
                st.rerun()
    pagina = st.session_state["pagina"]
    st.markdown(
        f"<style>div[class*='st-key-nav_{pagina.replace(' ', '_')}'] button"
        "{background:#e6e6eb !important;font-weight:600;}</style>", unsafe_allow_html=True)

    if auth_real["rol"] == "super_admin":
        nombre, ambito, ini = "Super Admin", "HQ · toda la red", "SA"
    elif auth_real["rol"] == "admin":
        zn = usuarios.ZONAS[auth_real["zona_id"]]["nombre"]
        nombre, ambito, ini = f"Admin {zn}", f"Zona {zn}", auth_real["zona_id"]
    else:
        nombre, ambito, ini = f"Gerente {auth_real['tienda_id']}", "Tu tienda", "G"
    st.markdown(f"<div class='sb-usuario'><div class='sb-avatar'>{ini}</div><div>"
                f"<div class='sb-nombre'>{nombre}</div><div class='sb-ambito'>{ambito}</div></div></div>",
                unsafe_allow_html=True)
    with st.popover("Mi correo", icon=":material/mail:", width="stretch"):
        st.caption("Aquí te llegan los avisos urgentes de tu cuenta.")
        correo = st.text_input("Correo", value=_fila_actual.get("email") or "", key="mi_correo",
                               placeholder="nombre@empresa.mx", label_visibility="collapsed")
        if st.button("Guardar", key="sb_correo", type="primary"):
            usuarios_df.loc[usuarios_df["usuario"] == auth_real["usuario"], "email"] = correo.strip()
            _guardar_estado_usuarios(usuarios_df)
            registrar("correo_actualizado")
            st.toast("Correo guardado.", icon=":material/check_circle:")
    if st.button("Cerrar sesión", key="sb_salir", icon=":material/logout:", width="stretch"):
        registrar("sesion_cerrada")
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

if st.session_state.get("_pagina_auditada") != pagina:
    registrar("pagina_visitada", pagina)
    st.session_state["_pagina_auditada"] = pagina

visibles = tiendas_visibles(auth)


def selector_tienda(clave: str) -> str:
    """Gerente: su tienda, sin control. Admin/HQ: un selector compacto."""
    if auth["rol"] == "manager":
        return auth["tienda_id"]
    ids = list(visibles["tienda_id"])
    previa = st.session_state.get("tienda_sel")
    idx = ids.index(previa) if previa in ids else 0
    t = st.selectbox("Tienda", ids, index=idx, key=clave, label_visibility="collapsed",
                     format_func=lambda x: f"Tienda {x} · {visibles.set_index('tienda_id').loc[x, 'cluster_id']}")
    st.session_state["tienda_sel"] = t
    return t


def barra_fechas(titulo: str, paso: str, clave: str, extra=None) -> None:
    """[Hoy] [‹] [›]  Título  ...  (extra a la derecha). paso: 'mes' | 'semana' | 'dia'."""
    c_hoy, c_prev, c_next, c_tit, c_extra = st.columns([0.8, 0.45, 0.45, 4.2, 2.6], vertical_alignment="center")
    if c_hoy.button("Hoy", key=f"navf_hoy_{clave}"):
        ir_a_fecha(hoy())
        st.rerun()
    base = st.session_state["dia"]
    if paso == "mes":
        a, m = st.session_state.get("mes_vista", (base.year, base.month))
        ant, sig = calendario.mes_anterior(a, m), calendario.mes_siguiente(a, m)
        puede_ant = date(*ant, 1) >= date(SEMANA_MIN.year, SEMANA_MIN.month, 1)
        puede_sig = date(*sig, 1) <= FIN_HORIZONTE
        if c_prev.button("", icon=":material/chevron_left:", key=f"navf_prev_{clave}", disabled=not puede_ant):
            st.session_state["mes_vista"] = ant
            st.rerun()
        if c_next.button("", icon=":material/chevron_right:", key=f"navf_next_{clave}", disabled=not puede_sig):
            st.session_state["mes_vista"] = sig
            st.rerun()
    else:
        delta = timedelta(days=7 if paso == "semana" else 1)
        if c_prev.button("", icon=":material/chevron_left:", key=f"navf_prev_{clave}",
                         disabled=(base - delta) < calendario.semana_de(SEMANA_MIN)[0]):
            ir_a_fecha(base - delta)
            st.rerun()
        if c_next.button("", icon=":material/chevron_right:", key=f"navf_next_{clave}",
                         disabled=(base + delta) > FIN_HORIZONTE):
            ir_a_fecha(base + delta)
            st.rerun()
    c_tit.markdown(f"<div class='nav-titulo'>{titulo}</div>", unsafe_allow_html=True)
    if extra:
        with c_extra:
            extra()


def obtener_semana(tienda_id: str, domingo: date) -> dict:
    with st.spinner(f"Armando el horario de la semana {fmt_rango_semana(domingo)}…"):
        return calcular_semana_tienda(tienda_id, domingo, version_datos())


# ---------------------------------------------------------------------------
# Ediciones manuales (persona -> turno) sobre la propuesta
# ---------------------------------------------------------------------------

def turnos_vigentes(rep: dict, tienda_id: str) -> pd.DataFrame:
    """Turnos de la propuesta con los cambios manuales de esta semana aplicados."""
    turnos = rep["propuesta"]["turnos_df"].copy()
    catalogo = {t["turno"]: t for t in rep["propuesta"]["catalogo_turnos"]}
    for emp, fecha, turno_nuevo in st.session_state["ediciones"].get((tienda_id, rep["fecha_inicio"]), []):
        turnos = turnos[~((turnos["empleado_id"] == emp) & (turnos["fecha"] == fecha))]
        if turno_nuevo:
            t = catalogo[turno_nuevo]
            turnos = pd.concat([turnos, pd.DataFrame([{
                "empleado_id": emp, "fecha": fecha, "turno": turno_nuevo,
                "hora_inicio": t["inicio"], "hora_fin": t["fin"], "hora_pausa": t["pausa"]}])],
                ignore_index=True)
    return turnos


def validar_legal(turnos: pd.DataFrame, emp: str, anio: int) -> str | None:
    fref = date(anio, 1, 1)
    max_dias = int(reglas.regla_vigente("dias_trabajo_maximo_antes_descanso", fref))
    tope = (reglas.regla_vigente("jornada_ordinaria_semanal_horas", fref)
            + reglas.regla_vigente("extra_tope_doble_semanal_horas", fref)
            + reglas.regla_vigente("extra_tope_triple_semanal_horas", fref))
    t = turnos[turnos["empleado_id"] == emp]
    if len(t) > max_dias:
        return f"quedaría trabajando {len(t)} días; la ley pide 1 día de descanso por cada 6 (art. 69)."
    horas = int((t["hora_fin"] - t["hora_inicio"]).sum())
    if horas > tope:
        return f"quedaría con {horas} h en la semana; el máximo legal con horas extra es {tope:g} h."
    return None


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

def pagina_horario() -> None:
    tienda_id = None
    vista = st.session_state["cal_vista"]
    dia = st.session_state["dia"]
    semana = st.session_state["semana"]

    cab_izq, cab_der = st.columns([3, 2], vertical_alignment="bottom")
    with cab_izq:
        encabezado("Horario", "Quién trabaja, en qué turno, cada día.")
    with cab_der:
        if auth["rol"] != "manager":
            tienda_id = selector_tienda("hor_tienda")
    if tienda_id is None:
        tienda_id = auth["tienda_id"]

    def selector_vista():
        v = st.segmented_control("Vista", ["Mes", "Semana", "Día"], default=vista,
                                 key=f"seg_vista_{vista}", label_visibility="collapsed")
        if v and v != vista:
            st.session_state["cal_vista"] = v
            if v == "Mes":
                st.session_state["mes_vista"] = (dia.year, dia.month)
            st.rerun()

    if vista == "Mes":
        a, m = st.session_state.get("mes_vista", (dia.year, dia.month))
        barra_fechas(f"{calendario.NOMBRES_MES[m]} {a}", "mes", "mes", selector_vista)
        vista_mes(tienda_id, a, m)
    elif vista == "Semana":
        barra_fechas(f"{fmt_rango_semana(semana)} {pill_regimen(semana)}", "semana", "sem", selector_vista)
        vista_semana(tienda_id, semana)
    else:
        barra_fechas(f"{fmt_dia(dia)} {pill_regimen(semana)}", "dia", "dia", selector_vista)
        vista_dia(tienda_id, dia)


def vista_mes(tienda_id: str, anio: int, mes: int) -> None:
    calculadas = {k[1] for k in registro_calculadas()
                  if k[0] == tienda_id and k[2:] == (version_datos(), VERSION_MODELO)}
    resumen: dict = {}
    for dom in {calendario.semana_de(f)[0] for fila in calendario.matriz_mes(anio, mes) for f in fila if f}:
        if dom in calculadas:
            rep = calcular_semana_tienda(tienda_id, dom, version_datos())
            if rep["status"] != "INFEASIBLE":
                for r in resumen_diario(rep, turnos_vigentes(rep, tienda_id)).itertuples(index=False):
                    resumen[r.fecha] = r
    cols = st.columns(7)
    for c, n in zip(cols, calendario.DIAS_SEMANA_ABREV):
        c.markdown(f"<div class='cal-dow'>{n}</div>", unsafe_allow_html=True)
    for fila in calendario.matriz_mes(anio, mes):
        cols = st.columns(7)
        for c, f in zip(cols, fila):
            if f is None:
                c.markdown("<div class='cal-vacia'></div>", unsafe_allow_html=True)
                continue
            fuera = f < SEMANA_MIN or f > FIN_HORIZONTE
            suf = "-hoy" if f == hoy() else ("-sel" if f == st.session_state["dia"] else "")
            r = resumen.get(f)
            if r is not None and not fuera:
                estado = "-falta" if r.pico_sin else ("-ok" if r.ahorro >= 0 else "-caro")
                etiqueta = f"**{f.day}**  \n{r.personas} personas  \nahorro {milesk(r.ahorro)}"
            else:
                estado, etiqueta = "", str(f.day)
            if c.button(etiqueta, key=f"mes_{f.isoformat()}{suf}{estado}", disabled=fuera, width="stretch"):
                ir_a_fecha(f)
                st.session_state["cal_vista"] = "Día"
                st.rerun()
    st.markdown(
        "<div class='leyenda' style='margin-top:10px'>"
        "<span class='punto' style='background:#1baf7a'></span>con ahorro y pico cubierto&nbsp;&nbsp;&nbsp;"
        "<span class='punto' style='background:#eb6834'></span>falta gente en hora pico&nbsp;&nbsp;&nbsp;"
        "<span class='punto' style='background:#d2d2d7'></span>sin calcular (toca el día)</div>",
        unsafe_allow_html=True)


def costo_por_persona(rep: dict, turnos: pd.DataFrame) -> dict:
    """Costo semanal por persona del horario vigente, pagando en orden legal."""
    fref = date(rep["anio"], 1, 1)
    tope = reglas.regla_vigente("jornada_ordinaria_semanal_horas", fref)
    t_dbl = reglas.regla_vigente("extra_tope_doble_semanal_horas", fref)
    m_dbl = reglas.regla_vigente("pago_extra_doble_multiplicador", fref)
    m_tpl = reglas.regla_vigente("pago_extra_triple_multiplicador", fref)
    sal = dict(zip(rep["plantilla"]["empleado_id"], rep["plantilla"]["salario_diario_mxn"]))
    h = (turnos["hora_fin"] - turnos["hora_inicio"]).groupby(turnos["empleado_id"]).sum()
    out = {}
    for e, hh in h.items():
        vh = sal[e] / (tope / 6)
        o = min(hh, tope); dbl = min(max(0, hh - tope), t_dbl); tpl = max(0, hh - tope - t_dbl)
        out[e] = o * vh + dbl * vh * m_dbl + tpl * vh * m_tpl
    return out


def resumen_diario(rep: dict, turnos: pd.DataFrame) -> pd.DataFrame:
    """Por día: personas, costo con Alvea, costo con el rol fijo de hoy, ahorro y horas pico sin
    cubrir. Los costos semanales se reparten por día según las horas trabajadas cada día, así
    que la suma de los 7 días cuadra exacto con el total de la semana."""
    semana = rep["fecha_inicio"]
    dias = [semana + timedelta(days=i) for i in range(7)]
    # Alvea
    cp = costo_por_persona(rep, turnos)
    t = turnos.assign(h=turnos["hora_fin"] - turnos["hora_inicio"])
    h_sem = t.groupby("empleado_id")["h"].transform("sum")
    t["costo"] = t["empleado_id"].map(cp) * t["h"] / h_sem
    alvea = t.groupby("fecha")["costo"].sum()
    personas = t.groupby("fecha")["empleado_id"].nunique()
    # Rol fijo (base)
    base = rep["base"]
    cu = base["cuadrillas"]
    cu = cu[cu["turno"] != "descanso"].assign(h=lambda x: x["hora_fin"] - x["hora_inicio"])
    cu["fecha"] = pd.to_datetime(cu["fecha"]).dt.date
    rh = base["resultado_horas"].copy()
    rh["fecha"] = pd.to_datetime(rh["fecha"]).dt.date
    h_base = cu.groupby("fecha")["h"].sum().add(
        rh.groupby("fecha")[["horas_extra_doble", "horas_extra_triple"]].sum().sum(axis=1), fill_value=0)
    base_dia = h_base / h_base.sum() * rep["ahorro_semanal"]["costo_base_mxn"] if h_base.sum() else h_base
    faltas = faltantes_pico(rep, turnos)
    filas = []
    for d in dias:
        a, b = float(alvea.get(d, 0.0)), float(base_dia.get(d, 0.0))
        filas.append({"fecha": d, "personas": int(personas.get(d, 0)), "alvea": a, "base": b, "ahorro": b - a,
                      "pico_sin": sum(sum(v.values()) for k, v in faltas.items() if k[0] == d)})
    return pd.DataFrame(filas)


def milesk(v: float) -> str:
    return f"${v/1000:,.1f}k" if abs(v) >= 1000 else f"${v:,.0f}"


def faltantes_pico(rep: dict, turnos: pd.DataFrame) -> dict:
    """{(fecha, hora): {rol: personas que faltan}} en horas pico, calculado sobre el
    horario VIGENTE (con cambios manuales) y POR ÁREA -- igual que la cifra de
    "Horas pico sin cubrir", para que tarjeta y gráfica siempre cuadren."""
    rol_de = dict(zip(rep["plantilla"]["empleado_id"], rep["plantilla"]["rol"]))
    cob: dict = {}
    for r in turnos.itertuples(index=False):
        for h in range(int(r.hora_inicio), int(r.hora_fin)):
            if h != int(r.hora_pausa):
                k = (r.fecha, h, rol_de.get(r.empleado_id))
                cob[k] = cob.get(k, 0) + 1
    dem = rep["demanda"]
    out: dict = {}
    for r in dem[dem["es_pico"]].itertuples(index=False):
        falta = int(r.personas_requeridas) - cob.get((r.fecha, int(r.hora), r.rol), 0)
        if falta > 0:
            out.setdefault((r.fecha, int(r.hora)), {})[r.rol] = falta
    return out


def horas_extra_vigentes(rep: dict, turnos: pd.DataFrame) -> int:
    tope = reglas.regla_vigente("jornada_ordinaria_semanal_horas", date(rep["anio"], 1, 1))
    h = (turnos["hora_fin"] - turnos["hora_inicio"]).groupby(turnos["empleado_id"]).sum()
    return int((h - tope).clip(lower=0).sum())


def tiles_semana(rep: dict, turnos: pd.DataFrame, rd: pd.DataFrame) -> None:
    """Beneficio arriba (ahorro vs. rol fijo de hoy) y la operación que lo respalda."""
    base, alvea = rd["base"].sum(), rd["alvea"].sum()
    ahorro = base - alvea
    extra = horas_extra_vigentes(rep, turnos)
    b = rep["base"]
    extra_base = int(b.get("horas_extra_doble_totales", 0) + b.get("horas_extra_triple_totales", 0))
    sin_cubrir = int(rd["pico_sin"].sum())
    tiles([
        ("Ahorro de la semana", mxn(ahorro), f"{ahorro / base:.1%} menos que el rol fijo" if base else "", "", True),
        ("Rol fijo de hoy", mxn(base), "costo de la semana"),
        ("Con Alvea", mxn(alvea), "costo de la semana"),
        ("Horas extra", f"{extra:,}", f"rol fijo: {extra_base:,}", "ojo" if extra else ""),
        ("Horas pico sin cubrir", f"{sin_cubrir:,}", "por área" if sin_cubrir else "cobertura completa",
         "mal" if sin_cubrir else "bien"),
    ])


def tiles_dinero(rep: dict) -> None:
    """Mi tienda = dinero de la semana, desglosado como lo pide el reto:
    horas extra evitadas y sobrestaffing evitado."""
    ah = rep["ahorro_semanal"]
    tiles([
        ("Ahorro de la semana", mxn(ah["ahorro_total_mxn"]), f"{ah['ahorro_pct']:.1%} vs. el rol fijo de hoy",
         "", True),
        ("Rol fijo de hoy", mxn(ah["costo_base_mxn"]), "costo de la semana"),
        ("Con Alvea", mxn(ah["costo_propuesta_mxn"]), "costo de la semana"),
        ("Horas extra evitadas", mxn(ah["costo_extra_evitado_mxn"]),
         f"{ah['horas_extra_doble_evitadas'] + ah['horas_extra_triple_evitadas']:,.0f} h"),
        ("Sobrestaffing evitado", mxn(ah["costo_sobrestaffing_evitado_mxn"]),
         f"{ah['horas_sobrestaffing_evitadas']:,.0f} h de gente de más"),
    ])


def vista_semana(tienda_id: str, semana: date) -> None:
    rep = obtener_semana(tienda_id, semana)
    marcar_calculada(tienda_id, semana)
    if rep["status"] == "INFEASIBLE":
        aviso("<b>No hay un horario legal posible esta semana</b> con la plantilla actual.", "mal")
        return
    turnos = turnos_vigentes(rep, tienda_id)
    rd = resumen_diario(rep, turnos).set_index("fecha")
    tiles_semana(rep, turnos, rd)
    catalogo = rep["propuesta"]["catalogo_turnos"]
    cols = st.columns(7, gap="small")
    for i, c in enumerate(cols):
        f = semana + timedelta(days=i)
        with c:
            suf = "-hoy" if f == hoy() else ""
            if st.button(f"{calendario.DIAS_SEMANA_ABREV[i]} {f.day}", key=f"sem_{f.isoformat()}{suf}"):
                ir_a_fecha(f)
                st.session_state["cal_vista"] = "Día"
                st.rerun()
            t_dia = turnos[turnos["fecha"] == f]
            filas = "".join(
                f"<div class='sem-turno'><span style='display:flex;align-items:center'>"
                f"<span class='punto' style='background:{COLOR_TURNO.get(t['turno'], '#8e8e93')}'></span>"
                f"<span><span>{t['turno']}</span><br><span class='h'>{t['inicio']}–{t['fin']} h</span></span></span>"
                f"<b>{int((t_dia['turno'] == t['turno']).sum())}</b></div>"
                for t in catalogo
            )
            r = rd.loc[f]
            color = "mal" if r["pico_sin"] else ("bien" if r["ahorro"] >= 0 else "ojo")
            st.markdown(f"<div class='sem-col'>{filas}<div class='sem-pie'>{int(r['personas'])} personas</div>"
                        f"<div class='sem-ahorro {color}'>ahorro {milesk(r['ahorro'])}</div>"
                        f"<div class='sem-pie'>rol fijo {milesk(r['base'])}</div></div>", unsafe_allow_html=True)


def grafica_cobertura(rep: dict, turnos_dia: pd.DataFrame, f: date, faltas: dict) -> None:
    dem = rep["demanda"]
    dem = dem[dem["fecha"] == f].groupby("hora", as_index=False)["personas_requeridas"].sum()
    dem = dem[dem["personas_requeridas"] > 0]
    if dem.empty:
        return
    horas = range(int(dem["hora"].min()), int(dem["hora"].max()) + 1)
    cob = {h: 0 for h in horas}
    for r in turnos_dia.itertuples(index=False):
        for h in range(int(r.hora_inicio), int(r.hora_fin)):
            if h != int(r.hora_pausa) and h in cob:
                cob[h] += 1
    df = pd.DataFrame({"hora": list(horas)})
    df["Trabajando"] = df["hora"].map(cob)
    df["Necesarias"] = df["hora"].map(dict(zip(dem["hora"], dem["personas_requeridas"]))).fillna(0)
    df["Hora"] = df["hora"].map(lambda h: f"{h}:00")
    df["Falta"] = df["hora"].map(lambda h: ", ".join(
        f"{n} {ROL_ETIQUETA.get(r, r)}" for r, n in faltas.get((f, h), {}).items()) or "—")
    df["Estado"] = df["Falta"].map(lambda x: "Falta gente en pico" if x != "—" else "Cubierta")
    base = alt.Chart(df).encode(x=alt.X("Hora:N", sort=None, title=None,
                                        axis=alt.Axis(labelAngle=0, labelColor="#6e6e73", tickSize=0,
                                                      domainColor="#e5e5ea")))
    barras = base.mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=18).encode(
        y=alt.Y("Trabajando:Q", title=None, axis=alt.Axis(gridColor="#f0f0f3", labelColor="#6e6e73",
                                                         domain=False, tickSize=0)),
        color=alt.Color("Estado:N", scale=alt.Scale(domain=["Cubierta", "Falta gente en pico"],
                                                     range=["#2a78d6", "#eb6834"]), legend=None),
        tooltip=[alt.Tooltip("Hora:N"), alt.Tooltip("Trabajando:Q", title="Trabajando"),
                 alt.Tooltip("Necesarias:Q", title="Necesarias"), alt.Tooltip("Falta:N", title="Falta")])
    linea = base.mark_line(color="#1d1d1f", strokeWidth=2, interpolate="step-after", strokeDash=[4, 3]).encode(
        y="Necesarias:Q")
    hay_faltas = (df["Falta"] != "—").any()
    st.markdown("<div class='seccion'>Cobertura por hora</div>"
                "<div class='leyenda'><span class='punto' style='background:#2a78d6'></span>Personas trabajando"
                + ("&nbsp;&nbsp;&nbsp;<span class='punto' style='background:#eb6834'></span>Falta gente de algún "
                   "área en hora pico (pasa el cursor para ver cuál)" if hay_faltas else "")
                + "&nbsp;&nbsp;&nbsp;<span style='display:inline-block;width:14px;border-top:2px dashed #1d1d1f;"
                "vertical-align:middle;margin-right:6px'></span>Personas necesarias</div>",
                unsafe_allow_html=True)
    st.altair_chart((barras + linea).properties(height=190).configure_view(strokeWidth=0), width="stretch")


def vista_dia(tienda_id: str, f: date) -> None:
    semana = calendario.semana_de(f)[0]
    rep = obtener_semana(tienda_id, semana)
    marcar_calculada(tienda_id, semana)
    if rep["status"] == "INFEASIBLE":
        aviso("<b>No hay un horario legal posible esta semana</b> con la plantilla actual.", "mal")
        return
    clave = (tienda_id, semana)
    ediciones = st.session_state["ediciones"].setdefault(clave, [])
    turnos = turnos_vigentes(rep, tienda_id)
    t_dia = turnos[turnos["fecha"] == f]
    plantilla = rep["plantilla"]
    nombre = dict(zip(plantilla["empleado_id"], plantilla.get("nombre", plantilla["empleado_id"])))
    rol = dict(zip(plantilla["empleado_id"], plantilla["rol"]))
    ausentes = set(rep["ausentismo"].loc[(rep["ausentismo"]["fecha"] == f) & rep["ausentismo"]["ausente"],
                                         "empleado_id"])
    editados_hoy = {e for e, fe, _ in ediciones if fe == f}

    catalogo = rep["propuesta"]["catalogo_turnos"]
    faltas_dia = {k: v for k, v in faltantes_pico(rep, turnos).items() if k[0] == f}
    sin_cubrir_dia = sum(sum(v.values()) for v in faltas_dia.values())
    rdia = resumen_diario(rep, turnos).set_index("fecha").loc[f]
    tiles([
        ("Ahorro del día", mxn(rdia["ahorro"]), f"rol fijo {mxn(rdia['base'])} · Alvea {mxn(rdia['alvea'])}", "", True),
        ("Personas trabajando", f"{t_dia['empleado_id'].nunique()}", f"de {len(plantilla)} en plantilla"),
        ("Descansan", f"{len(plantilla) - t_dia['empleado_id'].nunique() - len(ausentes)}", "día libre de ley"),
        ("Ausencias", f"{len(ausentes)}", "faltas previstas", "ojo" if ausentes else ""),
        ("Horas pico sin cubrir", f"{sin_cubrir_dia}", "hoy, por área" if sin_cubrir_dia else "cobertura completa",
         "mal" if sin_cubrir_dia else "bien"),
    ])

    # --- cambiar a alguien de turno (solo gerente): acción + resultado juntos, arriba ---
    sel = None
    if auth["rol"] == "manager":
        sel = _panel_cambio(rep, tienda_id, clave, f, t_dia, plantilla, nombre, rol, ausentes, catalogo)
    else:
        st.markdown("<div class='leyenda' style='margin:-6px 0 14px'>Vista de lectura: los cambios de turno "
                    "los hace el gerente de la tienda.</div>", unsafe_allow_html=True)

    def fila(e: str, extra: str = "") -> str:
        clases = "persona" + (" cambio" if e in editados_hoy else "") + (" sel" if e == sel else "")
        return (f"<div class='{clases}'><span class='pn'><span class='punto' style='background:"
                f"{ROL_COLOR.get(rol.get(e), '#8e8e93')}'></span>{nombre.get(e, e)}</span>"
                f"<span class='rol' title='{ROL_ETIQUETA.get(rol.get(e), '')}'>{extra}</span></div>")

    st.markdown("<div class='leyenda' style='margin:0 0 8px'>" + "&nbsp;&nbsp;".join(
        f"<span class='punto' style='background:{ROL_COLOR[r]}'></span>{ROL_ETIQUETA[r]}" for r in ROL_COLOR)
        + "</div>", unsafe_allow_html=True)

    # --- 4 columnas, una por turno ---
    cols = st.columns(len(catalogo), gap="small")
    for c, t in zip(cols, catalogo):
        del_turno = t_dia[t_dia["turno"] == t["turno"]]
        info = {r.empleado_id: r for r in del_turno.itertuples(index=False)}
        gente = sorted(info, key=lambda e: (rol.get(e, ""), nombre.get(e, e)))
        filas = "".join(
            fila(e, f"{int(info[e].hora_pausa)}:00"
                    + (" · +2 h" if int(info[e].hora_fin) - int(info[e].hora_inicio) > 8 else ""))
            for e in gente
        ) or "<div class='leyenda' style='padding:6px 0'>Nadie en este turno</div>"
        c.markdown(
            f"<div class='turno-card'><div class='turno-cab' style='border-top:4px solid {COLOR_TURNO.get(t['turno'])}'>"
            f"<div class='turno-nombre'>{t['turno']}<span style='margin-left:auto;font-variant-numeric:tabular-nums'>"
            f"{len(gente)}</span></div>"
            f"<div class='turno-horas'>{t['inicio']}:00 – {t['fin']}:00 · hora = descanso</div></div>"
            f"<div class='turno-lista'>{filas}</div></div>", unsafe_allow_html=True)

    # --- quién no trabaja hoy ---
    trabajan = set(t_dia["empleado_id"])
    descansan = sorted((e for e in plantilla["empleado_id"] if e not in trabajan and e not in ausentes),
                       key=lambda e: (rol.get(e, ""), nombre.get(e, e)))
    faltan = sorted(ausentes, key=lambda e: (rol.get(e, ""), nombre.get(e, e)))
    abierto = sel is not None and (sel in descansan or sel in faltan)
    with st.expander(f"Descansan ({len(descansan)}) · Ausencias ({len(faltan)})", expanded=abierto):
        d1, d2 = st.columns(2)
        d1.markdown("<div class='turno-lista' style='max-height:none;padding:0'>"
                    + "".join(fila(e) for e in descansan) + "</div>", unsafe_allow_html=True)
        d2.markdown("<div class='turno-lista' style='max-height:none;padding:0'>"
                    + ("".join(fila(e, "ausencia") for e in faltan) or "<div class='leyenda'>Nadie</div>")
                    + "</div>", unsafe_allow_html=True)

    grafica_cobertura(rep, t_dia, f, faltas_dia)


def _panel_cambio(rep, tienda_id, clave, f, t_dia, plantilla, nombre, rol, ausentes, catalogo) -> str | None:
    """Panel de cambio. Regresa a la persona seleccionada (para resaltarla en las columnas)."""
    ediciones = st.session_state["ediciones"].setdefault(clave, [])
    with st.container(border=True, key="panel_cambio"):
        st.markdown("<div class='seccion' style='margin-top:0'>Cambiar a alguien de turno</div>",
                    unsafe_allow_html=True)
        turno_de = dict(zip(t_dia["empleado_id"], t_dia["turno"]))
        horas_de = {r.empleado_id: (int(r.hora_inicio), int(r.hora_fin)) for r in t_dia.itertuples(index=False)}
        candidatos = sorted(plantilla["empleado_id"], key=lambda e: nombre.get(e, e))
        c1, c2, c3 = st.columns([3, 2, 1], vertical_alignment="bottom")
        emp = c1.selectbox("Persona", candidatos, index=None, placeholder="Busca por nombre…",
                           key=f"cmb_emp_{f}_{len(ediciones)}",
                           format_func=lambda e: f"{nombre.get(e, e)} · {ROL_ETIQUETA.get(rol.get(e), '')}")
        if emp in ausentes:
            estado, actual = "ausencia (falta prevista)", None
        elif emp in turno_de:
            ini, fin = horas_de[emp]
            estado, actual = f"{turno_de[emp]} ({ini}:00–{fin}:00)", turno_de[emp]
        else:
            estado, actual = "descansa", "Descanso"
        opciones = [t["turno"] for t in catalogo] + ["Descanso"]
        nuevo = c2.selectbox("Mover a", [o for o in opciones if o != actual], index=None,
                             placeholder="Elige turno", key=f"cmb_turno_{f}_{emp}_{len(ediciones)}",
                             disabled=emp is None or emp in ausentes)
        if emp:
            st.markdown(f"<div class='estado-sel'><span class='punto' style='background:"
                        f"{ROL_COLOR.get(rol.get(emp), '#8e8e93')}'></span><b>{nombre.get(emp, emp)}</b>"
                        f"&nbsp;· hoy:&nbsp;<b>{estado}</b>"
                        + (" — no se puede mover" if emp in ausentes else "") + "</div>",
                        unsafe_allow_html=True)
        if c3.button("Cambiar", type="primary", disabled=not (emp and nuevo), key=f"cmb_ok_{f}", width="stretch"):
            st.session_state["ediciones"][clave] = ediciones + [(emp, f, None if nuevo == "Descanso" else nuevo)]
            problema = validar_legal(turnos_vigentes(rep, tienda_id), emp, rep["anio"])
            if problema:
                st.session_state["ediciones"][clave] = ediciones
                st.session_state[f"error_{clave}"] = f"No se puede: {nombre.get(emp, emp)} {problema}"
            else:
                st.session_state.pop(f"error_{clave}", None)
                calif = _calificar(rep, tienda_id, clave)
                registrar("turno_reasignado", f"{nombre.get(emp, emp)} ({emp}) → {nuevo}, {f.isoformat()}",
                          alcance=("tienda", tienda_id))
                if calif["calificacion"] in ("No recomendado", "Costoso", "Caro"):
                    zona = usuarios.zona_de_cluster(tiendas_df.set_index("tienda_id").loc[tienda_id, "cluster_id"])
                    notificaciones.crear_notificacion(
                        DATA_DIR, "zona", zona, "turno_calificado",
                        "critico" if calif["calificacion"] == "No recomendado" else "advertencia",
                        f"Tienda {tienda_id} · {fmt_dia(f)}: el gerente movió a {nombre.get(emp, emp)} a "
                        f"{nuevo}. {calif['calificacion']}: {calif['mensaje']}")
            st.rerun()

        error = st.session_state.get(f"error_{clave}")
        calif = st.session_state.get(f"calif_{clave}")
        if error:
            aviso(error, "mal")
        elif calif and ediciones:
            tipo = {"Neutral": "bien", "Aceptable": "ojo", "Caro": "ojo"}.get(calif["calificacion"], "mal")
            c_msg, c_btn = st.columns([5, 1], vertical_alignment="center")
            with c_msg:
                aviso(f"<b>{calif['calificacion']}.</b> {calif['mensaje']} "
                      f"<span style='color:#6e6e73'>· {len(ediciones)} cambio(s) esta semana</span>", tipo)
            if c_btn.button("Deshacer", icon=":material/undo:", key="deshacer", width="stretch"):
                ediciones.pop()
                st.session_state.pop(f"calif_{clave}", None)
                if ediciones:
                    _calificar(rep, tienda_id, clave)
                st.rerun()
    return emp


def _calificar(rep: dict, tienda_id: str, clave: tuple) -> dict:
    original = optimizador.turnos_a_horario(rep["propuesta"]["turnos_df"])
    editado = optimizador.turnos_a_horario(turnos_vigentes(rep, tienda_id))
    calif = costos_ahorro.calificar_edicion_manual(original, editado, rep["plantilla"], rep["demanda"], rep["anio"])
    st.session_state[f"calif_{clave}"] = calif
    registrar("turno_calificado", f"{calif['calificacion']} ({mxn(calif['delta_costo_mxn'])})",
              alcance=("tienda", tienda_id))
    return calif


def pagina_tienda() -> None:
    semana = st.session_state["semana"]
    cab_izq, cab_der = st.columns([3, 2], vertical_alignment="bottom")
    with cab_izq:
        encabezado("Mi tienda" if auth["rol"] == "manager" else "Tienda",
                   "Cuánto cuesta la semana y cuánto se ahorra frente al rol fijo de hoy.")
    with cab_der:
        tienda_id = selector_tienda("tda_tienda")
    barra_fechas(f"{fmt_rango_semana(semana)} {pill_regimen(semana)}", "semana", "tda")
    rep = obtener_semana(tienda_id, semana)
    marcar_calculada(tienda_id, semana)
    if rep["status"] == "INFEASIBLE":
        aviso("<b>No hay un horario legal posible esta semana</b> con la plantilla actual.", "mal")
        return
    ah, br = rep["ahorro_semanal"], rep["brecha_vs_techo"]
    turnos = turnos_vigentes(rep, tienda_id)
    tiles_dinero(rep)
    if ah["cumple_minimo_8pct"]:
        aviso(f"<b>Cumple la meta.</b> Ahorra {ah['ahorro_pct']:.1%} esta semana; la meta mínima es 8%.", "bien")
    else:
        aviso(f"<b>Debajo de la meta.</b> Ahorra {ah['ahorro_pct']:.1%} (meta mínima 8%). "
              f"En años con jornada más corta la plantilla actual alcanza para menos horas; "
              f"lo que falta se cubre con horas extra.", "ojo")

    st.markdown("<div class='seccion'>De dónde sale el ahorro</div>", unsafe_allow_html=True)
    base_rep = rep["base"]
    filas = pd.DataFrame([
        {"Concepto": "Horas ordinarias", "Rol fijo de hoy": base_rep.get("horas_ordinarias_totales", 0),
         "Con Alvea": rep["propuesta"]["horas_ordinarias"]},
        {"Concepto": "Horas extra dobles", "Rol fijo de hoy": base_rep.get("horas_extra_doble_totales", 0),
         "Con Alvea": rep["propuesta"]["horas_extra_doble"]},
        {"Concepto": "Horas extra triples", "Rol fijo de hoy": base_rep.get("horas_extra_triple_totales", 0),
         "Con Alvea": rep["propuesta"]["horas_extra_triple"]},
        {"Concepto": "Horas de más (sobrestaffing)",
         "Rol fijo de hoy": round(costos_ahorro._normalizar(base_rep)["horas_sobrestaffing"]),
         "Con Alvea": rep["propuesta"].get("horas_sobrestaffing") or 0},
        {"Concepto": "Costo de la semana (MXN)", "Rol fijo de hoy": round(ah["costo_base_mxn"]),
         "Con Alvea": round(ah["costo_propuesta_mxn"])},
    ])
    st.dataframe(filas, hide_index=True, width="stretch",
                 column_config={"Rol fijo de hoy": st.column_config.NumberColumn(format="%,d"),
                                "Con Alvea": st.column_config.NumberColumn(format="%,d")})

    plantilla = rep["plantilla"]
    export = turnos.merge(plantilla[["empleado_id", "nombre", "rol"]], on="empleado_id", how="left") \
        .sort_values(["fecha", "hora_inicio", "nombre"])[
        ["fecha", "turno", "hora_inicio", "hora_fin", "hora_pausa", "empleado_id", "nombre", "rol"]]
    export["rol"] = export["rol"].map(ROL_ETIQUETA).fillna(export["rol"])
    export.columns = ["Fecha", "Turno", "Entra", "Sale", "Descanso", "ID", "Nombre", "Área"]
    reporte_txt = (
        f"Alvea — Tienda {tienda_id}\nSemana {fmt_rango_semana(semana)} · jornada {horas_regimen(semana)} h "
        f"({anio_regimen(semana)})\n\n{rep['resumen_ejecutivo']}\n\n"
        f"Costo rol fijo de hoy: {mxn(ah['costo_base_mxn'])} MXN\nCosto con Alvea: {mxn(ah['costo_propuesta_mxn'])} MXN\n"
        f"Ahorro: {mxn(ah['ahorro_total_mxn'])} MXN ({ah['ahorro_pct']:.1%})\n"
        f"Captura del ahorro máximo teórico: {br.get('pct_del_techo_capturado', 0):.0%}\n")
    d1, d2, _ = st.columns([1, 1, 2])
    d1.download_button("Horario (CSV)", export.to_csv(index=False).encode("utf-8"),
                       f"horario_{tienda_id}_{semana.isoformat()}.csv", "text/csv",
                       icon=":material/download:", width="stretch")
    d2.download_button("Reporte (TXT)", reporte_txt.encode("utf-8"),
                       f"reporte_{tienda_id}_{semana.isoformat()}.txt", "text/plain",
                       icon=":material/download:", width="stretch")
    with st.expander("Cómo se calcula"):
        st.markdown(
            "- **Rol fijo de hoy**: 80 personas, 3 turnos rotativos fijos; donde falta gente se alarga el "
            "turno con horas extra.\n"
            "- **Con Alvea**: cada día cada persona entra a uno de 4 turnos fijos de 8 h (o descansa). "
            "El optimizador elige la combinación más barata que cumple la ley y cubre la demanda por hora.\n"
            "- **Reglas**: jornada semanal del año de esa semana, 1 día de descanso por cada 6, horas extra "
            "dobles/triples con sus topes, descanso de media hora dentro del turno.\n"
            "- **Supuesto de calibración**: la plantilla actual opera al 60% de su capacidad en una semana "
            "promedio. Se ajusta con datos reales.")


def pagina_resumen() -> None:
    semana = st.session_state["semana"]
    alcance = ("toda la red" if auth["rol"] == "super_admin"
               else f"zona {usuarios.ZONAS[auth['zona_id']]['nombre']}")
    encabezado("Resumen", f"Ahorro de la semana en {alcance} · {len(visibles)} tiendas.")
    barra_fechas(f"{fmt_rango_semana(semana)} {pill_regimen(semana)}", "semana", "res")
    ids = list(visibles["tienda_id"])
    listas = [t for t in ids if esta_calculada(t, semana)]
    faltan = [t for t in ids if t not in listas]
    if faltan:
        with st.container(border=True, key="panel_calcular"):
            c1, c2 = st.columns([3, 1], vertical_alignment="center")
            titulo = ("Calcula el ahorro de esta semana" if not listas
                      else f"Faltan {len(faltan)} de {len(ids)} tiendas")
            c1.markdown(f"<div style='font-weight:650;font-size:15px'>{titulo}</div>"
                        f"<div class='leyenda'>{len(listas)} de {len(ids)} tiendas listas. Cada tienda tarda unos "
                        f"segundos; lo calculado queda disponible para todos.</div>", unsafe_allow_html=True)
            calcular = c2.button(f"Calcular {len(faltan)} tiendas", type="primary", width="stretch")
        if calcular:
            barra = st.progress(0.0)
            for i, t in enumerate(faltan):
                barra.progress(i / len(faltan), text=f"Tienda {t} ({i + 1} de {len(faltan)})")
                calcular_semana_tienda(t, semana, version_datos())
                marcar_calculada(t, semana)
            registrar("red_calculada", f"{len(faltan)} tiendas, semana {semana.isoformat()}")
            st.rerun()
    if not listas:
        return
    resultados = {t: calcular_semana_tienda(t, semana, version_datos()) for t in listas}
    cons = vista_red.consolidar_resultados(resultados, tiendas_df)
    rk = cons["ranking_tiendas"]
    n_ok = int(rk["cumple_minimo_8pct"].sum())
    tiles([
        ("Ahorro de la semana", mxn(cons["ahorro_total_red_mxn"]), f"{cons['ahorro_pct_red']:.1%} del costo actual",
         "", True),
        ("Tiendas en meta (≥ 8%)", f"{n_ok} de {len(rk)}", "", "bien" if n_ok == len(rk) else "ojo"),
        ("Tiendas sin horario legal", f"{len(cons['tiendas_infeasible'])}", "",
         "mal" if cons["tiendas_infeasible"] else "bien"),
    ])
    rk = rk.sort_values("ahorro_pct", ascending=False).copy()
    rk["Tienda"] = rk["tienda_id"]
    rk["Estado"] = rk["cumple_minimo_8pct"].map({True: "En meta", False: "Debajo de 8%"})
    barras = alt.Chart(rk).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, size=16).encode(
        y=alt.Y("Tienda:N", sort=None, title=None, axis=alt.Axis(labelColor="#6e6e73", tickSize=0, domain=False,
                                                                 labelOverlap=False, labelPadding=8)),
        x=alt.X("ahorro_pct:Q", title=None, axis=alt.Axis(format=".0%", gridColor="#f0f0f3", labelColor="#6e6e73",
                                                            domain=False, tickSize=0, tickCount=5)),
        color=alt.Color("Estado:N", scale=alt.Scale(domain=["En meta", "Debajo de 8%"],
                                                     range=["#2a78d6", "#eb6834"]),
                        legend=alt.Legend(orient="top", title=None, labelColor="#1d1d1f")),
        tooltip=[alt.Tooltip("Tienda:N"), alt.Tooltip("cluster_id:N", title="Clúster"),
                 alt.Tooltip("ahorro_pct:Q", title="Ahorro", format=".1%"),
                 alt.Tooltip("ahorro_mxn:Q", title="MXN", format="$,.0f")])
    meta = alt.Chart(pd.DataFrame({"x": [0.08]})).mark_rule(color="#1d1d1f", strokeDash=[4, 3]).encode(x="x:Q")
    st.markdown("<div class='seccion'>Ahorro por tienda</div>", unsafe_allow_html=True)
    st.altair_chart((barras + meta).properties(height=max(160, 28 * len(rk))).configure_view(strokeWidth=0),
                    width="stretch")
    st.caption("Línea punteada = meta mínima de 8%.")
    with st.expander("Ver tabla"):
        st.dataframe(rk[["tienda_id", "cluster_id", "formato", "ahorro_mxn", "ahorro_pct", "Estado"]],
                     hide_index=True, width="stretch",
                     column_config={"tienda_id": "Tienda", "cluster_id": "Clúster", "formato": "Formato",
                                    "ahorro_mxn": st.column_config.NumberColumn("Ahorro (MXN)", format="$%,.0f"),
                                    "ahorro_pct": st.column_config.NumberColumn("Ahorro", format="percent")})


def pagina_avisos() -> None:
    encabezado("Avisos", "Lo que necesita tu atención. Se generan solos.")
    todas = notificaciones.visible_para(notificaciones.cargar_notificaciones(DATA_DIR), auth_real)
    leidas = notificaciones.cargar_leidas(DATA_DIR)
    ids_leidas = set(leidas.loc[leidas["usuario"] == auth_real["usuario"], "id"]) if not leidas.empty else set()
    if todas.empty:
        aviso("<b>Todo en orden.</b> No tienes avisos.", "bien")
        return
    pendientes = [i for i in todas["id"] if i not in ids_leidas]
    if pendientes and st.button(f"Marcar {len(pendientes)} como leídos", icon=":material/done_all:"):
        notificaciones.marcar_leidas(DATA_DIR, pendientes, auth_real["usuario"])
        st.rerun()
    tipo = {"info": "bien", "advertencia": "ojo", "critico": "mal"}
    for _, n in todas.iterrows():
        no_leida = n["id"] not in ids_leidas
        cuando = str(n["timestamp"])[:16].replace("T", " ")
        c1, c2 = st.columns([8, 1], vertical_alignment="center")
        with c1:
            aviso(f"{'<b>' if no_leida else ''}{n['mensaje']}{'</b>' if no_leida else ''}"
                  f"<div class='leyenda' style='margin-top:3px'>{cuando}"
                  f"{' · también por correo' if n.get('correo_enviado') else ''}</div>",
                  tipo.get(n["severidad"], "bien"))
        if no_leida and c2.button("Leído", key=f"leido_{n['id']}"):
            notificaciones.marcar_leidas(DATA_DIR, [n["id"]], auth_real["usuario"])
            st.rerun()


def pagina_historial() -> None:
    encabezado("Historial", "Quién hizo qué y cuándo, dentro de tu alcance.")
    df = auditoria.visible_para(auditoria.cargar_auditoria(DATA_DIR), auth, set(visibles["tienda_id"]))
    df = df[df["tipo_evento"] != "pagina_visitada"] if not df.empty else df
    if df.empty:
        aviso("Todavía no hay movimientos.", "bien")
        return
    c1, c2, _ = st.columns([2, 2, 3])
    tipo = c1.selectbox("Qué", ["Todo"] + sorted(df["tipo_evento"].unique()),
                        format_func=lambda t: t if t == "Todo" else auditoria.TIPOS_EVENTO.get(t, t))
    quien = c2.selectbox("Quién", ["Todos"] + sorted(df["usuario"].unique()))
    if tipo != "Todo":
        df = df[df["tipo_evento"] == tipo]
    if quien != "Todos":
        df = df[df["usuario"] == quien]
    df = df.sort_values("timestamp", ascending=False).copy()
    df["Qué pasó"] = df["tipo_evento"].map(lambda t: auditoria.TIPOS_EVENTO.get(t, t))
    df["Cuándo"] = df["timestamp"].astype(str).str[:16].str.replace("T", " ")
    df["detalle"] = df["detalle"].fillna("").astype(str).replace({"None": "", "nan": ""})
    st.dataframe(df[["Cuándo", "usuario", "Qué pasó", "alcance_valor", "detalle"]], hide_index=True,
                 width="stretch", column_config={"usuario": "Quién", "alcance_valor": "Dónde",
                                                 "detalle": "Detalle"})
    st.download_button("Descargar (CSV)", df.to_csv(index=False).encode("utf-8"), "historial.csv", "text/csv",
                       icon=":material/download:")


def pagina_usuarios() -> None:
    encabezado("Usuarios", "Una cuenta por tienda. Desactívala para bloquear el acceso.")
    permitidas = set(tiendas_visibles(auth)["tienda_id"])
    ger = usuarios_df[(usuarios_df["rol"] == "manager") & usuarios_df["tienda_id"].isin(permitidas)]
    vista = ger[["usuario", "tienda_id", "activo", "email"]]
    editado = st.data_editor(
        vista, hide_index=True, width="stretch", disabled=["usuario", "tienda_id"], key="editor_usuarios",
        column_config={"usuario": "Usuario", "tienda_id": "Tienda",
                       "activo": st.column_config.CheckboxColumn("Activo"),
                       "email": st.column_config.TextColumn("Correo")})
    cambios = int(((editado["activo"] != vista["activo"]) | (editado["email"] != vista["email"])).sum())
    if st.button(f"Guardar {cambios} cambio(s)" if cambios else "Sin cambios", type="primary",
                 disabled=not cambios):
        antes = dict(zip(vista["usuario"], vista["activo"]))
        usuarios_df.loc[editado.index, "activo"] = editado["activo"]
        usuarios_df.loc[editado.index, "email"] = editado["email"]
        _guardar_estado_usuarios(usuarios_df)
        for _, r in editado.iterrows():
            if antes.get(r["usuario"]) == r["activo"]:
                continue
            tipo_ev = "cuenta_reactivada" if r["activo"] else "cuenta_desactivada"
            registrar(tipo_ev, f"{r['usuario']} por {auth_real['usuario']}", alcance=("tienda", r["tienda_id"]))
            notificaciones.crear_notificacion(
                DATA_DIR, "usuario", r["usuario"], tipo_ev, "info" if r["activo"] else "critico",
                f"Tu cuenta ({r['usuario']}) fue {'reactivada' if r['activo'] else 'desactivada'}.",
                email_destino=r.get("email") or None)
        st.toast("Guardado.", icon=":material/check_circle:")
        st.rerun()
    inactivas = ger.loc[~ger["activo"].astype(bool), "tienda_id"].tolist()
    if inactivas:
        aviso(f"<b>Sin acceso:</b> {', '.join(inactivas)}. Nadie puede entrar a esas tiendas.", "ojo")


def pagina_reglas() -> None:
    encabezado("Reglas legales", "Cómo baja la jornada año con año (Decreto DOF 01-05-2026).")
    filas = []
    for a in range(anio_regimen(SEMANA_MIN), 2031):
        tabla = reglas.tabla_vigente_para_anio(a)
        filas.append({"Año": str(a), "Jornada semanal (h)": tabla["jornada_ordinaria_semanal_horas"],
                      "Extra doble (h/sem)": tabla["extra_tope_doble_semanal_horas"],
                      "Extra triple (h/sem)": tabla["extra_tope_triple_semanal_horas"],
                      "Días máx. seguidos": tabla["dias_trabajo_maximo_antes_descanso"]})
    st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")
    tabla = costos_ahorro.armar_tabla_trazabilidad()
    pend = tabla[tabla["estado"] == "pendiente_validacion_legal"]
    if not pend.empty:
        aviso(f"<b>{len(pend)} regla(s) pendientes de validar con un abogado laboral</b> "
              f"(tramo de horas extra al triple, art. 68).", "ojo")
    with st.expander("Trazabilidad completa"):
        st.dataframe(tabla, hide_index=True, width="stretch")


def pagina_datos() -> None:
    encabezado("Datos", "Usa tus propios archivos.")
    f = datos_fijos()
    ej = datos_semana_ejemplo(SEMANA_MIN)
    ejemplos = {"tiendas": f["tiendas"], "plantilla": f["plantilla"], "trafico": ej["trafico"],
                "ventas": ej["ventas"], "ausentismo": ej["ausentismo"]}
    nombres = {"tiendas": "Tiendas", "plantilla": "Plantilla", "trafico": "Tráfico por hora",
               "ventas": "Ventas por hora", "ausentismo": "Ausentismo"}
    st.markdown("<div class='seccion'>1 · Descarga el formato</div>", unsafe_allow_html=True)
    cols = st.columns(5)
    for c, (k, df) in zip(cols, ejemplos.items()):
        c.download_button(nombres[k], df.to_csv(index=False).encode("utf-8"), f"{k}_formato.csv", "text/csv",
                          icon=":material/download:", width="stretch", help=", ".join(df.columns))
    st.markdown("<div class='seccion'>2 · Sube tus archivos</div>", unsafe_allow_html=True)
    subidos = {}
    cols = st.columns(5)
    for c, k in zip(cols, ejemplos):
        a = c.file_uploader(nombres[k], type=["csv"], key=f"up_{k}")
        if a is not None:
            try:
                subidos[k] = pd.read_csv(a)
            except Exception as e:
                c.error(f"No se pudo leer: {e}")
    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("Usar mis archivos", type="primary", disabled=not subidos, width="stretch"):
        st.session_state.setdefault("datos_subidos", {}).update(subidos)
        st.session_state["version_datos"] = version_datos() + 1
        st.session_state["_semanas_vistas"] = set()
        registrar("datos_cargados", ", ".join(subidos))
        st.rerun()
    if st.session_state.get("datos_subidos") and c2.button("Volver al ejemplo", width="stretch"):
        st.session_state["datos_subidos"] = {}
        st.session_state["version_datos"] = version_datos() + 1
        st.session_state["_semanas_vistas"] = set()
        registrar("datos_restablecidos")
        st.rerun()
    en_uso = st.session_state.get("datos_subidos")
    aviso(f"<b>En uso:</b> tus archivos de {', '.join(nombres[k].lower() for k in en_uso)}; el resto, ejemplo." if en_uso
          else "<b>En uso:</b> datos de ejemplo.", "bien")


RUTAS = {"Resumen": pagina_resumen, "Horario": pagina_horario, "Tienda": pagina_tienda,
         "Avisos": pagina_avisos, "Historial": pagina_historial, "Usuarios": pagina_usuarios,
         "Reglas legales": pagina_reglas, "Datos": pagina_datos}
RUTAS[pagina]()
