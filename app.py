"""Alvea PMV — horarios por tienda bajo la reforma de 40 horas (Autoservicio MX, ficticio).

Rediseño 24-sep-2026 (v2 de la interfaz). Principios:
  1. Cada rol ve SOLO lo que usa: el gerente ve su horario, su tienda y sus
     avisos; el admin/HQ agrega el resumen de la red, historial y usuarios.
  2. Una sola "semana activa" compartida por todas las vistas. Arranca HOY.
  3. El régimen legal (48 h en 2026 -> 40 h en 2030) sale de la fecha de la
     semana; nadie tiene que escoger un "año de régimen".
  4. Nada se calcula con un botón escondido: abrir una semana la calcula.
  5. Un día se lee como lo arma un gerente: 4 turnos fijos y quién está en
     cada uno. Cambiar a alguien = persona -> turno (se aplica al elegirlo). Nada de arrastrar.

Correr local:  streamlit run app.py   (ver README.md)
"""
from __future__ import annotations

import math
import re

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

from jornada40 import (archivos, auditoria, calendario, costos_ahorro, cuentas, demanda_personal,
                        escenario_base, nomina, notificaciones, optimizador, persistencia, precalculado, reglas, usuarios, vista_red)
from jornada40 import semana as semana_calc

# Streamlit Cloud recarga app.py en cada deploy, pero puede dejar en memoria la
# versión anterior de los módulos de jornada40 (pasó el 24-sep-2026: interfaz
# nueva con optimizador viejo). Si la versión del modelo no coincide, se
# recargan todos los módulos del paquete.
def _asegurar_modulos_al_dia(version: str) -> None:
    import importlib
    import sys
    if (getattr(optimizador, "VERSION_MODELO", None) == version and hasattr(archivos, "usar_espacio")
            and hasattr(costos_ahorro, "nomina") and hasattr(semana_calc, "nomina")):
        return
    for nombre in sorted([m for m in sys.modules if m.startswith("jornada40.")]):
        importlib.reload(sys.modules[nombre])
    st.cache_data.clear()


st.set_page_config(page_title="Alvea", page_icon=":material/calendar_month:", layout="wide",
                   initial_sidebar_state="auto")

DATA_RAIZ = Path("data")
DATA_DIR = DATA_RAIZ          # con una cuenta propia pasa a data/espacios/<id> (se fija tras el login)
TIEMPO_LIMITE_SEG = 10.0
# Súbelo cada vez que cambie el modelo (optimizador, demanda, calibración): forma parte de
# la llave de la caché, así un despliegue nuevo nunca sirve horarios calculados con el
# modelo anterior (pasó el 24-sep-2026: la caché de Streamlit Cloud sobrevivió al deploy).
VERSION_MODELO = "2026-09-25-determinista"
VERSION_COSTOS = "2026-10-01-cobertura-total"   # cambia el costo, no el horario: los precalculados siguen sirviendo
_asegurar_modulos_al_dia(VERSION_MODELO)
archivos.usar_espacio(None)   # cada corrida arranca en la demo compartida
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
    return f"${v:,.0f}" if v >= 0 else f"−${-v:,.0f}"


def pct(v: float) -> str:
    """Porcentaje truncado a un decimal: 7.97 % se ve 7.9 %, nunca "8.0 %" debajo de la meta."""
    return f"{math.floor(v * 1000) / 10:.1f}%"


def puente_ahorro(ah: dict) -> list[tuple[str, float]]:
    """Partidas del ahorro que suman EXACTO el ahorro total.

    El sueldo de tiempo completo se paga igual con o sin Alvea (nomina.py), así que el
    ahorro en dinero es la hora extra que deja de pagarse. La partida de extra es una
    estimación (horas × valor hora promedio); lo que no explica va en "Otros ajustes"
    para que el desglose cuadre y nada quede escondido.
    """
    extra = ah["costo_extra_evitado_mxn"]
    penal = ah.get("penalizacion_subdotacion_no_cubierta_mxn", 0.0) or 0.0
    partidas = [("Horas extra evitadas", extra),
                ("Otros ajustes (valor hora por persona y redondeos)", ah["ahorro_total_mxn"] - extra + penal)]
    if penal:
        partidas.append(("Penalización por demanda sin cubrir", -penal))
    return partidas


# ---------------------------------------------------------------------------
# Datos: archivos (ver jornada40/archivos.py)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, max_entries=8)
def _catalogos(firma: tuple) -> dict[str, pd.DataFrame]:
    return {"tiendas": archivos.leer("tiendas"), "plantilla": archivos.leer("plantilla")}


def datos_fijos() -> dict[str, pd.DataFrame]:
    """Tiendas y plantilla vigentes (de los archivos)."""
    return _catalogos(archivos.firma(SEMANA_MIN)[:2])


@st.cache_data(show_spinner=False, max_entries=60)
def _leer_semana(domingo: date, firma: tuple) -> dict[str, pd.DataFrame]:
    return archivos.leer_semana(domingo)


def datos_semana(domingo: date) -> dict[str, pd.DataFrame]:
    """Los 5 archivos de esa semana (se vuelven a leer solo si alguno cambió)."""
    return _leer_semana(domingo, archivos.firma(domingo))


@st.cache_data(show_spinner=False, max_entries=60)
def _huellas(domingo: date, firma: tuple) -> dict[str, str]:
    d = datos_semana(domingo)
    return {t: archivos.huella(d, t) for t in d["tiendas"]["tienda_id"]}


def huella_de(tienda_id: str, domingo: date) -> str:
    return _huellas(domingo, archivos.firma(domingo)).get(tienda_id, "")


@st.cache_data(show_spinner=False, max_entries=400)
def calcular_semana_tienda(tienda_id: str, domingo: date, huella: str,
                           version_modelo: str = VERSION_MODELO, version_costos: str = VERSION_COSTOS) -> dict:
    """Base (cómo se programa hoy) + propuesta del optimizador + techo, 1 tienda, 1 semana.
    La huella identifica sus archivos: si ya se resolvió con esos mismos archivos, se abre al instante."""
    reporte, _, _ = semana_calc.calcular(tienda_id, domingo, datos_semana(domingo), TIEMPO_LIMITE_SEG,
                                         version_modelo, huella=huella)
    return reporte


@st.cache_resource
def intentos_fallidos() -> dict:
    """usuario -> lista de horas de intentos fallidos (compartido entre sesiones)."""
    return {}


MAX_INTENTOS, VENTANA_BLOQUEO = 5, timedelta(minutes=5)


def bloqueado_hasta(usuario: str) -> datetime | None:
    ahora = datetime.now()
    recientes = [t for t in intentos_fallidos().get(usuario, []) if ahora - t < VENTANA_BLOQUEO]
    intentos_fallidos()[usuario] = recientes
    return recientes[0] + VENTANA_BLOQUEO if len(recientes) >= MAX_INTENTOS else None


@st.cache_resource
def registro_calculadas() -> set:
    """(tienda, semana, versión de datos) ya calculadas en este servidor. Compartido entre
    sesiones: si HQ prepara las 50 tiendas antes de la demo, todos las ven al instante."""
    return set()


def marcar_calculada(tienda_id: str, domingo: date) -> None:
    registro_calculadas().add((tienda_id, domingo, huella_de(tienda_id, domingo), VERSION_MODELO))


def esta_calculada(tienda_id: str, domingo: date) -> bool:
    h = huella_de(tienda_id, domingo)
    return bool(h) and ((tienda_id, domingo, h, VERSION_MODELO) in registro_calculadas()
                        or precalculado.existe(VERSION_MODELO, tienda_id, domingo, h))


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
    persistencia.subir(_RUTA_ESTADO_USUARIOS)


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
  --ink: #1d1d1f; --ink-2: #5f5f64; --ink-3: #6b6b70;
  --line: #e5e5ea; --line-2: #d2d2d7; --fill: #f5f5f7; --surface: #ffffff;
  --accent: #0071e3; --accent-soft: #eaf3ff; --accent-ink: #0060c2;
  --good: #1a7a34; --warn: #9a5200; --bad: #c9252c;
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
[data-testid="stFileUploaderDropzone"] button[data-testid="stBaseButton-secondary"] { font-size: 0 !important; }
[data-testid="stFileUploaderDropzone"] button[data-testid="stBaseButton-secondary"] [data-testid="stMarkdownContainer"] { display: none !important; }
[data-testid="stFileUploaderDropzone"] button[data-testid="stBaseButton-secondary"]::after { content: "Elegir archivos"; font-size: 13.5px; }
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
.pill-azul { background: var(--accent-soft); color: var(--accent-ink); border-color: transparent; }

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
[class*="st-key-anio_"] button[data-testid="stPopoverButton"] {
  background: var(--accent-soft) !important; color: var(--accent-ink) !important; border: none !important;
  border-radius: 999px !important; min-height: 0 !important; padding: 3px 10px !important; }
[class*="st-key-anio_"] button[data-testid="stPopoverButton"] p { font-size: 12px !important; font-weight: 600 !important; }

/* ---------- calendario: mes ---------- */
.cal-dow { text-align: center; font-size: 11px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase;
           color: var(--ink-3); padding-bottom: 4px; }
div[class*="st-key-mes_"] button {
  width: 100%; aspect-ratio: 1.35; min-height: 3.2rem; border-radius: 12px; border: 1px solid var(--line);
  background: #fff; color: var(--ink); font-size: 15px; font-weight: 500; box-shadow: none;
  align-items: flex-start; justify-content: flex-start; padding: 8px 11px; }
div[class*="st-key-mes_"] button:hover:not(:disabled) { border-color: var(--accent); background: #f7fbff; color: var(--ink); }
div[class*="st-key-mes_"] button:disabled { background: transparent !important; border-color: transparent !important;
  box-shadow: none !important; color: #c7c7cc; }
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

@st.cache_resource
def _restaurar_datos() -> list[str]:
    """Una vez por arranque: trae de GitHub el historial, avisos, cambios, cuentas y archivos subidos."""
    return persistencia.restaurar(DATA_RAIZ)


_restaurar_datos()
st.markdown(CSS, unsafe_allow_html=True)

def entrar_con_cuenta(cta: dict, evento: str) -> None:
    """Abre la sesión de una cuenta propia en su espacio."""
    global DATA_DIR
    st.session_state["auth"] = {"rol": "super_admin", "tienda_id": None, "zona_id": None,
                                "usuario": cta["correo"], "cuenta": True, "espacio": cta["espacio"]}
    DATA_DIR = cuentas.carpeta_espacio(DATA_RAIZ, cta["espacio"])
    registrar(evento)
    st.session_state["pagina"] = "Primeros pasos" if str(cta.get("ob") or "0") != "0" else "Resumen"


if "auth" not in st.session_state:
    st.markdown(CSS_LOGIN, unsafe_allow_html=True)
    st.markdown("<div class='lg-marca' style='margin-bottom:4px'>Alvea</div>"
                "<div class='lg-sub'>Reto técnico para <span style=\"font-family:Georgia,'Times New Roman',serif\">"
                "AIvena</span> · Jornada40</div>", unsafe_allow_html=True)
    if st.session_state.get("modo_login") == "registro":
        st.markdown("<div class='lg-sub'>Crea tu cuenta. Tendrás tu propio espacio con archivos de "
                    "ejemplo para 50 tiendas; lo que subas solo cambia tu espacio.</div>", unsafe_allow_html=True)
        with st.form("form_registro"):
            r_nombre = st.text_input("Nombre")
            r_empresa = st.text_input("Empresa")
            r_correo = st.text_input("Correo", placeholder="nombre@empresa.mx")
            r_pw = st.text_input("Contraseña", type="password", help="Al menos 8 caracteres.")
            r_pw2 = st.text_input("Repite la contraseña", type="password")
            r_ok = st.checkbox("Acepto que Alvea guarde mi nombre, empresa, correo y lo que haga en mi espacio, "
                               "solo para operar la prueba. Alvea es un prototipo: la decisión legal de cada "
                               "horario es de la empresa.")
            creado = st.form_submit_button("Crear cuenta", type="primary", width="stretch")
        if creado:
            error = cuentas.validar_registro(r_correo, r_nombre, r_empresa, r_pw, r_pw2, cuentas.cargar(DATA_RAIZ))
            if not error and not r_ok:
                error = "Para seguir, acepta el aviso de privacidad."
            if error:
                st.error(error)
            else:
                entrar_con_cuenta(cuentas.crear(DATA_RAIZ, r_correo, r_nombre, r_empresa, r_pw), "cuenta_creada")
                st.session_state.pop("modo_login", None)
                st.rerun()
        if st.button("Ya tengo cuenta · Entrar", type="tertiary", width="stretch"):
            st.session_state.pop("modo_login", None)
            st.rerun()
        st.stop()
    with st.form("form_login"):
        usuario_txt = st.text_input("Usuario o correo")
        password = st.text_input("Contraseña", type="password")
        enviado = st.form_submit_button("Entrar", type="primary", width="stretch")
    if enviado:
        clave_u = usuario_txt.strip().upper()
        hasta = bloqueado_hasta(clave_u)
        es_cuenta = cuentas.es_correo(usuario_txt)
        fila = None if es_cuenta else usuarios.buscar_usuario(usuario_txt, usuarios_con_estado())
        cta = cuentas.verificar(DATA_RAIZ, usuario_txt, password) if es_cuenta and password and not hasta else None
        if not usuario_txt.strip() or not password:
            st.error("Escribe tu usuario y tu contraseña.")
        elif hasta:
            mins = max(1, int((hasta - datetime.now()).total_seconds() // 60) + 1)
            st.error(f"Demasiados intentos. Vuelve a intentar en {mins} min.")
        elif es_cuenta and cta is None or not es_cuenta and (fila is None or password != usuarios.password_login()):
            intentos_fallidos().setdefault(clave_u, []).append(datetime.now())
            st.error("Usuario o contraseña incorrectos.")
        elif es_cuenta:
            intentos_fallidos().pop(clave_u, None)
            entrar_con_cuenta(cta, "sesion_iniciada")
            st.rerun()
        elif not fila["activo"]:
            st.error("Esta cuenta está desactivada. Pide a HQ que la reactive.")
        else:
            intentos_fallidos().pop(clave_u, None)
            st.session_state["auth"] = {"rol": fila["rol"], "tienda_id": fila["tienda_id"],
                                        "zona_id": fila["zona_id"], "usuario": fila["usuario"]}
            registrar("sesion_iniciada")
            st.rerun()
    if st.button("¿Primera vez? Crea tu cuenta", type="tertiary", width="stretch"):
        st.session_state["modo_login"] = "registro"
        st.rerun()
    st.stop()

auth_real = st.session_state["auth"]
CUENTA = cuentas.buscar(DATA_RAIZ, auth_real["usuario"]) if auth_real.get("cuenta") else None
if auth_real.get("cuenta"):
    if CUENTA is None:
        del st.session_state["auth"]
        st.error("No encontramos tu cuenta. Vuelve a entrar.")
        st.stop()
    DATA_DIR = cuentas.carpeta_espacio(DATA_RAIZ, CUENTA["espacio"])
    archivos.usar_espacio(DATA_DIR / "archivos")
    usuarios_df = pd.DataFrame(columns=["usuario", "rol", "tienda_id", "zona_id", "activo", "email"])
    _fila_actual = {"email": CUENTA["correo"], "activo": True}
else:
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
def cargar_ediciones() -> dict:
    """Cambios manuales de turno guardados en disco: {(tienda, domingo): [(emp, fecha, turno|None)]}.
    Se leen en cada corrida para que el admin vea lo que el gerente cambió."""
    ruta = DATA_DIR / "ediciones.csv"
    if not ruta.exists():
        return {}
    try:
        df = pd.read_csv(ruta, dtype=str).fillna("")
    except Exception:
        return {}
    out: dict = {}
    for r in df.itertuples():
        clave = (r.tienda_id, date.fromisoformat(r.semana))
        out.setdefault(clave, []).append((r.empleado_id, date.fromisoformat(r.fecha), r.turno or None))
    return out


def guardar_ediciones(ed: dict) -> None:
    filas = [{"tienda_id": t, "semana": s.isoformat(), "empleado_id": e, "fecha": f.isoformat(), "turno": tn or ""}
             for (t, s), lista in ed.items() for e, f, tn in lista]
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(filas, columns=["tienda_id", "semana", "empleado_id", "fecha", "turno"]).to_csv(
            DATA_DIR / "ediciones.csv", index=False)
        persistencia.subir(DATA_DIR / "ediciones.csv")
    except Exception:
        pass


st.session_state["ediciones"] = cargar_ediciones()


def ir_a_fecha(f: date) -> None:
    f = min(max(f, SEMANA_MIN), FIN_HORIZONTE)
    st.session_state["dia"] = f
    st.session_state["semana"] = calendario.semana_de(f)[0]


# ---------------------------------------------------------------------------
# Barra lateral: navegación arriba, persona y salida abajo
# ---------------------------------------------------------------------------

auth = auth_real
@st.dialog("Privacidad y términos")
def dialogo_legal() -> None:
    st.markdown(
        "**Qué guardamos.** Tu usuario, el correo que tú escribas y lo que haces en la app "
        "(inicio de sesión, cambios de turno), para el Historial. Nada más.\n\n"
        "**Para qué.** Para mandarte avisos y para que tu admin vea quién cambió qué.\n\n"
        "**Cookies.** Solo las necesarias para mantener tu sesión. Sin publicidad ni analítica de terceros.\n\n"
        "**Tus datos.** Pide a HQ corregir o borrar tu correo cuando quieras.\n\n"
        "**Términos.** Alvea es un prototipo. Propone horarios con los archivos cargados; la decisión "
        "y la responsabilidad legal de cada horario son de la empresa. Una regla (horas extra al "
        "triple) está pendiente de validar con un abogado laboral.")


PAGINAS = {  # etiqueta -> ícono
    "Primeros pasos": "rocket_launch", "Resumen": "insights", "Horario": "calendar_month",
    "Avisos": "notifications", "Usuarios": "group",
    "Reglas legales": "gavel", "Datos": "upload_file",
}

with st.sidebar:
    st.markdown("<div class='sb-marca'>Alvea</div><div class='sb-sub'>Autoservicio MX</div>",
                unsafe_allow_html=True)

    if auth_real["rol"] == "super_admin" and not tiendas_df.empty:
        opciones = (["Toda la red"]
                    + ([] if CUENTA else [f"Zona {i['nombre']}" for i in usuarios.ZONAS.values()])
                    + [f"Tienda {t}" for t in tiendas_df["tienda_id"]])
        ver_como = st.selectbox("Ver como", opciones, key="ver_como",
                                help="Muestra la app como la vería otro perfil. Tus permisos no cambian.")
        if ver_como.startswith("Zona "):
            zid = next(z for z, i in usuarios.ZONAS.items() if i["nombre"] == ver_como[5:])
            auth = {**auth_real, "rol": "admin", "zona_id": zid}
        elif ver_como.startswith("Tienda "):
            auth = {**auth_real, "rol": "manager", "tienda_id": ver_como[7:]}

    if CUENTA:
        grupos = {"": ["Primeros pasos", "Resumen", "Horario", "Avisos"] if auth["rol"] != "manager"
                  else ["Primeros pasos", "Horario", "Avisos"],
                  "Tu espacio": ["Datos", "Reglas legales"]}
    elif auth["rol"] == "manager":
        grupos = {"": ["Horario", "Avisos"]}
    else:
        grupos = {"": ["Resumen", "Horario", "Avisos", "Usuarios"]}
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
            etiqueta = p
            if p == "Avisos" and n_avisos:
                etiqueta = f"Avisos · {n_avisos}"
            if p == "Primeros pasos" and CUENTA and CUENTA["ob"] != "0":
                etiqueta = f"Primeros pasos · {CUENTA['ob']} de {cuentas.PASOS_OB}"
            if st.button(etiqueta, key=f"nav_{p.replace(' ', '_')}", icon=f":material/{PAGINAS[p]}:",
                         width="stretch"):
                st.session_state["pagina"] = p
                st.rerun()
    pagina = st.session_state["pagina"]
    st.markdown(
        f"<style>div[class*='st-key-nav_{pagina.replace(' ', '_')}'] button"
        "{background:#e6e6eb !important;font-weight:600;}</style>", unsafe_allow_html=True)

    if CUENTA:
        nombre, ambito = CUENTA["nombre"], f"{CUENTA['empresa']} · tu espacio"
        ini = "".join(x[0] for x in CUENTA["nombre"].split()[:2]).upper() or "A"
    elif auth_real["rol"] == "super_admin":
        nombre, ambito, ini = "Super Admin", "HQ · toda la red", "SA"
    elif auth_real["rol"] == "admin":
        zn = usuarios.ZONAS[auth_real["zona_id"]]["nombre"]
        nombre, ambito, ini = f"Admin {zn}", f"Zona {zn}", auth_real["zona_id"]
    else:
        nombre, ambito, ini = f"Gerente {auth_real['tienda_id']}", "Tu tienda", "G"
    st.markdown(f"<div class='sb-usuario'><div class='sb-avatar'>{ini}</div><div>"
                f"<div class='sb-nombre'>{nombre}</div><div class='sb-ambito'>{ambito}</div></div></div>",
                unsafe_allow_html=True)
    if CUENTA:
        st.caption(f"Entras con {CUENTA['correo']}")
    else:
      with st.popover("Mi correo", icon=":material/mail:", width="stretch"):
        st.caption("Aquí te llegan los avisos urgentes de tu cuenta.")
        correo = st.text_input("Correo", value=_fila_actual.get("email") or "", key="mi_correo",
                               placeholder="nombre@empresa.mx", label_visibility="collapsed")
        correo_ok = not correo.strip() or re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", correo.strip())
        if correo.strip() and not correo_ok:
            st.caption(":red[Revisa el correo: falta @ o el dominio.]")
        if st.button("Guardar", key="sb_correo", type="primary", disabled=not correo_ok):
            usuarios_df.loc[usuarios_df["usuario"] == auth_real["usuario"], "email"] = correo.strip()
            _guardar_estado_usuarios(usuarios_df)
            registrar("correo_actualizado")
            st.toast("Correo guardado.", icon=":material/check_circle:")
    if st.button("Privacidad y términos", key="sb_legal", type="tertiary", width="stretch"):
        dialogo_legal()
    if st.button("Cerrar sesión", key="sb_salir", icon=":material/logout:", width="stretch"):
        registrar("sesion_cerrada")
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

if st.session_state.get("_toast"):
    st.toast(st.session_state.pop("_toast"), icon=":material/check_circle:")
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


def selector_anio(domingo: date, clave: str) -> None:
    """Pastilla "Jornada 48 h · 2026" que además deja saltar a otro año de la
    reducción (misma fecha de hoy en ese año) sin dar 200 clics en ›."""
    anio = anio_regimen(domingo)
    gen = st.session_state.get("anio_gen", 0)   # cambiar la key cierra el popover tras elegir
    with st.popover(f"Jornada {horas_regimen(domingo)} h · {anio}", key=f"anio_{clave}_g{gen}"):
        st.caption("Ir al año")
        for y in range(SEMANA_MIN.year, FIN_HORIZONTE.year + 1):
            h = horas_regimen(calendario.semana_de(date(y, 7, 1))[0])
            if st.button(f"{y} · {h} h", key=f"anio_{clave}_{y}", disabled=(y == anio), width="stretch"):
                t = hoy() if y == hoy().year else date(y, hoy().month, min(hoy().day, 28))
                ir_a_fecha(t)
                st.session_state["mes_vista"] = (t.year, t.month)
                st.session_state["anio_gen"] = gen + 1
                st.rerun()


def barra_fechas(titulo: str, paso: str, clave: str, extra=None, domingo: date | None = None) -> None:
    """[Hoy] [‹] [›]  Título [Jornada]  ...  (extra a la derecha). paso: 'mes' | 'semana' | 'dia'."""
    c_hoy, c_prev, c_next, c_tit, c_extra = st.columns([0.8, 0.45, 0.45, 4.2, 2.6], vertical_alignment="center")
    if c_hoy.button("Hoy", key=f"navf_hoy_{clave}"):
        ir_a_fecha(hoy())
        st.session_state["mes_vista"] = (hoy().year, hoy().month)
        st.rerun()
    base = st.session_state["dia"]
    if paso == "mes":
        a, m = st.session_state.get("mes_vista", (base.year, base.month))
        ant, sig = calendario.mes_anterior(a, m), calendario.mes_siguiente(a, m)
        puede_ant = date(*ant, 1) >= date(SEMANA_MIN.year, SEMANA_MIN.month, 1)
        puede_sig = date(*sig, 1) <= FIN_HORIZONTE
        if c_prev.button("", icon=":material/chevron_left:", key=f"navf_prev_{clave}", disabled=not puede_ant):
            st.session_state["mes_vista"] = ant
            ir_a_fecha(max(date(*ant, 1), hoy()))      # Semana y Día siguen al mes que se ve
            st.rerun()
        if c_next.button("", icon=":material/chevron_right:", key=f"navf_next_{clave}", disabled=not puede_sig):
            st.session_state["mes_vista"] = sig
            ir_a_fecha(max(date(*sig, 1), hoy()))
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
    with c_tit, st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f"<div class='nav-titulo'>{titulo}</div>", unsafe_allow_html=True, width="content")
        if domingo is not None:
            selector_anio(domingo, clave)
    if extra:
        with c_extra:
            extra()


def faltan_archivos(domingo: date) -> bool:
    """Si la semana no tiene archivos completos, lo dice y regresa True."""
    d = datos_semana(domingo)
    if archivos.semana_completa(d):
        return False
    faltan = [archivos.TIPOS[t]["nombre"] for t in ("tiendas", "plantilla", "trafico", "ventas") if d[t].empty]
    aviso(f"<b>Faltan archivos para la semana {fmt_rango_semana(domingo)}:</b> {', '.join(faltan)}. "
          "Súbelos en Datos.", "ojo")
    con = [x for x in archivos.semanas_con_archivos() if SEMANA_MIN <= x <= FIN_HORIZONTE]
    if con and not d["tiendas"].empty:
        cerca = min(con, key=lambda x: abs((x - domingo).days))
        if st.button(f"Ir a {fmt_rango_semana(cerca)}, que sí tiene archivos", icon=":material/arrow_forward:",
                     key=f"ir_completa_{domingo.isoformat()}"):
            ir_a_fecha(cerca)
            st.rerun()
    return True


def obtener_semana(tienda_id: str, domingo: date) -> dict:
    with st.spinner(f"Armando el horario de la semana {fmt_rango_semana(domingo)}…"):
        return calcular_semana_tienda(tienda_id, domingo, huella_de(tienda_id, domingo))


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
        barra_fechas(f"{calendario.NOMBRES_MES[m]} {a}", "mes", "mes", selector_vista,
                     calendario.semana_de(date(a, m, 15))[0])
        vista_mes(tienda_id, a, m)
    elif vista == "Semana":
        barra_fechas(f"{fmt_rango_semana(semana)}", "semana", "sem", selector_vista, semana)
        vista_semana(tienda_id, semana)
    else:
        barra_fechas(f"{fmt_dia(dia)}", "dia", "dia", selector_vista, semana)
        vista_dia(tienda_id, dia)


def vista_mes(tienda_id: str, anio: int, mes: int) -> None:
    resumen: dict = {}
    semanas = sorted(d for d in {calendario.semana_de(f)[0] for fila in calendario.matriz_mes(anio, mes) for f in fila if f}
                     if SEMANA_MIN <= d <= FIN_HORIZONTE and archivos.semana_completa(datos_semana(d)))
    pendientes = [d for d in semanas if not esta_calculada(tienda_id, d)]
    if pendientes:
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        c1.markdown(f"<div class='leyenda'>Faltan {len(pendientes)} semana{'s' if len(pendientes) != 1 else ''} de "
                    f"este mes por calcular (cerca de 1 min cada una, solo la primera vez).</div>", unsafe_allow_html=True)
        if c2.button("Calcular el mes", key=f"calc_mes_{anio}_{mes}", icon=":material/calendar_month:", width="stretch"):
            barra = st.progress(0.0)
            for i, d in enumerate(pendientes):
                barra.progress(i / len(pendientes), text=f"Semana {fmt_rango_semana(d)} ({i + 1} de {len(pendientes)})")
                calcular_semana_tienda(tienda_id, d, huella_de(tienda_id, d))
                marcar_calculada(tienda_id, d)
            st.rerun()
    for dom in semanas:
        if dom not in pendientes:
            rep = obtener_semana(tienda_id, dom)
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
        "<span class='punto' style='background:#eda100'></span>más caro que el rol fijo&nbsp;&nbsp;&nbsp;"
        "<span class='punto' style='background:#d2d2d7'></span>sin calcular (toca el día o «Calcular el mes»)</div>",
        unsafe_allow_html=True)


def costo_por_persona(rep: dict, turnos: pd.DataFrame) -> dict:
    """Costo semanal de cada persona de la plantilla con el horario vigente (ver nomina.py:
    tiempo completo cobra su semana aunque trabaje menos horas; la extra en orden legal)."""
    pagos = nomina.costo_por_empleado(nomina.horas_de_turnos(turnos), rep["plantilla"], rep["anio"])
    return {e: p["costo_mxn"] for e, p in pagos.items()}


def resumen_diario(rep: dict, turnos: pd.DataFrame) -> pd.DataFrame:
    """Por día: personas, costo con Alvea, costo con el rol fijo de hoy, ahorro y horas pico sin
    cubrir. El sueldo fijo de la semana se reparte parejo en los 7 días (se paga igual en los dos
    horarios); las horas extra y la penalización por demanda sin cubrir caen en el día en que
    ocurren. Así un día no "pierde" dinero solo por tener más gente, y la suma de los 7 días cuadra
    exacto con el ahorro de la semana."""
    semana = rep["fecha_inicio"]
    dias = [semana + timedelta(days=i) for i in range(7)]

    def repartir(total: float, pesos: dict) -> dict:
        s = sum(pesos.get(d, 0.0) for d in dias)
        return {d: (total * pesos.get(d, 0.0) / s if s else total / 7) for d in dias}

    # Alvea: sueldo parejo; la extra de cada persona en sus días de más de 8 h (o en sus días trabajados)
    pagos = nomina.costo_por_empleado(nomina.horas_de_turnos(turnos), rep["plantilla"], rep["anio"])
    t = turnos.assign(h=turnos["hora_fin"] - turnos["hora_inicio"])
    alvea = {d: sum(p["costo_ordinario_mxn"] for p in pagos.values()) / 7 for d in dias}
    for e, g in t.groupby("empleado_id"):
        ext = pagos.get(e, {}).get("costo_extra_mxn", 0.0)
        if ext:
            largos = {r.fecha: max(0, r.h - 8) for r in g.itertuples(index=False)}
            pesos = largos if sum(largos.values()) else {r.fecha: r.h for r in g.itertuples(index=False)}
            for d, v in repartir(ext, pesos).items():
                alvea[d] += v
    personas = t.groupby("fecha")["empleado_id"].nunique()
    # Rol fijo: sueldo parejo; su extra en el día en que se pagó (doble ×2, triple ×3)
    base = rep["base"]
    rh = base["resultado_horas"].copy()
    rh["fecha"] = pd.to_datetime(rh["fecha"]).dt.date
    peso_ext = (rh["horas_extra_doble"] * 2 + rh["horas_extra_triple"] * 3).groupby(rh["fecha"]).sum().to_dict()
    costo_base = rep["ahorro_semanal"]["costo_base_mxn"]
    ext_base = float(base.get("costo_extra_mxn", 0.0))
    base_ext_dia = repartir(ext_base, peso_ext)
    base_dia = {d: (costo_base - ext_base) / 7 + base_ext_dia[d] for d in dias}
    # Penalización por demanda sin cubrir: en los días en que Alvea la deja sin cubrir
    penal = rep["ahorro_semanal"].get("penalizacion_subdotacion_no_cubierta_mxn", 0.0) or 0.0
    pen_dia = repartir(penal, rep["propuesta"].get("subdotacion_por_dia") or {})
    faltas = faltantes_pico(rep, turnos)
    filas = []
    for d in dias:
        a, b = alvea[d] + pen_dia[d], base_dia[d]
        filas.append({"fecha": d, "personas": int(personas.get(d, 0)), "alvea": a, "base": b, "ahorro": b - a,
                      "pico_sin": sum(sum(v.values()) for k, v in faltas.items() if k[0] == d)})
    return pd.DataFrame(filas)


def milesk(v: float) -> str:
    signo = "−" if v < 0 else ""
    return f"{signo}${abs(v)/1000:,.1f}k" if abs(v) >= 1000 else f"{signo}${abs(v):,.0f}"


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


def tile_pico(horas: int, cuando: str = "") -> tuple:
    return ("Hora pico", "Cubierta" if not horas else f"Faltan {horas} h",
            f"todas las áreas{cuando}" if not horas else f"falta gente de alguna área{cuando}", "bien" if not horas else "mal")


def tiles_semana(rep: dict, turnos: pd.DataFrame, rd: pd.DataFrame) -> None:
    """3 cifras: cuánto ahorras (con las dos bases), si el pico está cubierto y las horas extra."""
    base, alvea = rd["base"].sum(), rd["alvea"].sum()
    ahorro = base - alvea
    pen = rep["ahorro_semanal"].get("penalizacion_subdotacion_no_cubierta_mxn", 0.0) or 0.0
    extra = horas_extra_vigentes(rep, turnos)
    b = rep["base"]
    extra_base = int(b.get("horas_extra_doble_totales", 0) + b.get("horas_extra_triple_totales", 0))
    tiles([
        ("Ahorro de la semana", mxn(ahorro),
         (f"{pct(ahorro / base)} · rol fijo {mxn(base)} → Alvea {mxn(alvea - pen)}"
          + (f" · −{mxn(pen)} por demanda sin cubrir" if pen >= 1 else "") if base else ""), "", True),
        tile_pico(int(rd["pico_sin"].sum())),
        ("Horas extra", f"{extra:,}", f"con el rol fijo serían {extra_base:,}", "ojo" if extra else "bien"),
    ])


def detalle_semana(rep: dict, tienda_id: str, semana: date, turnos: pd.DataFrame) -> None:
    """Debajo de la semana: descargas y, plegado, de dónde sale el ahorro (antes página 'Mi tienda')."""
    ah, br = rep["ahorro_semanal"], rep["brecha_vs_techo"]
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
        f"Ahorro: {mxn(ah['ahorro_total_mxn'])} MXN ({pct(ah['ahorro_pct'])})\n"
        + "".join(f"  {c}: {mxn(v)} MXN\n" for c, v in puente_ahorro(ah)) +
        f"Capacidad liberada (sueldo pagado sin programar): {rep['propuesta'].get('horas_capacidad_liberada') or 0:,.0f} h\n"
        f"Demanda sin cubrir (h): pico {rep['propuesta'].get('horas_subdotacion_pico') or 0:,} · fuera de pico "
        f"{rep['propuesta'].get('horas_subdotacion_fuera_pico') or 0:,} (rol fijo: {rep['base'].get('horas_subdotacion_total') or 0:,})\n"
        f"Captura del ahorro máximo teórico: {br.get('pct_del_techo_capturado', 0):.0%}\n")
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    d1, d2, _ = st.columns([1, 1, 2])
    d1.download_button("Horario (CSV)", export.to_csv(index=False).encode("utf-8"),
                       f"horario_{tienda_id}_{semana.isoformat()}.csv", "text/csv",
                       icon=":material/download:", width="stretch")
    d2.download_button("Reporte (TXT)", reporte_txt.encode("utf-8"),
                       f"reporte_{tienda_id}_{semana.isoformat()}.txt", "text/plain",
                       icon=":material/download:", width="stretch")
    with st.expander("De dónde sale el ahorro"):
        meta = ("<b>Cumple la meta</b> de 8%" if ah["cumple_minimo_8pct"] else "<b>Debajo de la meta</b> de 8%")
        partidas = puente_ahorro(ah)
        texto = ""
        for i, (c, v) in enumerate(partidas):
            signo = ("− " if v < 0 else "") if i == 0 else (" − " if v < 0 else " + ")
            texto += f"{signo}{mxn(abs(v))} {c[0].lower() + c[1:]}"
        aviso(f"{meta}: ahorra {mxn(ah['ahorro_total_mxn'])} ({pct(ah['ahorro_pct'])}) esta semana = {texto}.",
              "bien" if ah["cumple_minimo_8pct"] else "ojo")
        sin_cubrir = ah.get("penalizacion_subdotacion_no_cubierta_mxn", 0.0) or 0.0
        if sin_cubrir >= 1:
            pr = rep["propuesta"]
            aviso(f"<b>Demanda sin cubrir: {pr.get('horas_subdotacion_total') or 0:,} h</b> con Alvea "
                  f"(pico {pr.get('horas_subdotacion_pico') or 0:,} · fuera de pico {pr.get('horas_subdotacion_fuera_pico') or 0:,}) "
                  f"contra {rep['base'].get('horas_subdotacion_total') or 0:,} h con el rol fijo. "
                  f"Esas horas no cuentan como ahorro: se restan {mxn(sin_cubrir)} (3 veces el valor hora, "
                  "convención del PMV).", "ojo")
        cap = rep["propuesta"].get("horas_capacidad_liberada") or 0
        if cap:
            aviso(f"<b>Capacidad liberada: {cap:,.0f} h.</b> Horas de sueldo que se pagan igual pero que "
                  "no hizo falta programar. No son ahorro en dinero: son la holgura que absorbe la baja de "
                  "jornada sin contratar.", "bien")
        base_rep = rep["base"]
        filas = pd.DataFrame([
            {"Concepto": "Horas ordinarias", "Rol fijo de hoy": base_rep.get("horas_ordinarias_totales", 0),
             "Con Alvea": rep["propuesta"]["horas_ordinarias"]},
            {"Concepto": "Horas extra dobles", "Rol fijo de hoy": base_rep.get("horas_extra_doble_totales", 0),
             "Con Alvea": rep["propuesta"]["horas_extra_doble"]},
            {"Concepto": "Horas extra triples", "Rol fijo de hoy": base_rep.get("horas_extra_triple_totales", 0),
             "Con Alvea": rep["propuesta"]["horas_extra_triple"]},
            {"Concepto": "Horas de gente de más",
             "Rol fijo de hoy": round(costos_ahorro._normalizar(base_rep)["horas_sobrestaffing"]),
             "Con Alvea": rep["propuesta"].get("horas_sobrestaffing") or 0},
            {"Concepto": "Demanda sin cubrir en pico (h)",
             "Rol fijo de hoy": base_rep.get("horas_subdotacion_pico") or 0,
             "Con Alvea": rep["propuesta"].get("horas_subdotacion_pico") or 0},
            {"Concepto": "Demanda sin cubrir fuera de pico (h)",
             "Rol fijo de hoy": base_rep.get("horas_subdotacion_fuera_pico") or 0,
             "Con Alvea": rep["propuesta"].get("horas_subdotacion_fuera_pico") or 0},
            {"Concepto": "Costo de la semana (MXN)", "Rol fijo de hoy": round(ah["costo_base_mxn"]),
             "Con Alvea": round(ah["costo_propuesta_mxn"])},
        ])
        st.dataframe(filas, hide_index=True, width="stretch",
                     column_config={"Rol fijo de hoy": st.column_config.NumberColumn(format="%,d"),
                                    "Con Alvea": st.column_config.NumberColumn(format="%,d")})
        st.caption("Rol fijo de hoy: 3 turnos rotativos fijos; donde falta gente se alarga el turno con horas "
                   "extra. Con Alvea: cada persona entra cada día a uno de 4 turnos de 8 h (o descansa); se elige "
                   "la combinación más barata que cumple la ley del año y cubre la demanda de cada área por hora. "
                   "Supuesto: la plantilla actual opera al 60% de su capacidad; se recalibra con datos reales.")


def vista_semana(tienda_id: str, semana: date) -> None:
    if faltan_archivos(semana):
        return
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
    detalle_semana(rep, tienda_id, semana, turnos)


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
    st.markdown("<div class='leyenda'><span class='punto' style='background:#2a78d6'></span>Personas trabajando"
                + ("&nbsp;&nbsp;&nbsp;<span class='punto' style='background:#eb6834'></span>Falta gente de algún "
                   "área en hora pico (pasa el cursor para ver cuál)" if hay_faltas else "")
                + "&nbsp;&nbsp;&nbsp;<span style='display:inline-block;width:14px;border-top:2px dashed #1d1d1f;"
                "vertical-align:middle;margin-right:6px'></span>Personas necesarias</div>",
                unsafe_allow_html=True)
    st.altair_chart((barras + linea).properties(height=190).configure_view(strokeWidth=0), width="stretch")


def vista_dia(tienda_id: str, f: date) -> None:
    semana = calendario.semana_de(f)[0]
    if faltan_archivos(semana):
        return
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
    trabajan_n = t_dia["empleado_id"].nunique()
    tiles([
        ("Ahorro del día", mxn(rdia["ahorro"]), f"rol fijo {mxn(rdia['base'])} → Alvea {mxn(rdia['alvea'])}", "", True),
        ("Trabajan", f"{trabajan_n} de {len(plantilla)}",
         f"{len(plantilla) - trabajan_n - len(ausentes)} descansan · {len(ausentes)} faltan"),
        tile_pico(sin_cubrir_dia, " hoy"),
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
        + "&nbsp;&nbsp;·&nbsp;&nbsp;10 h = turno extendido; solo cuenta como extra si la persona pasa del tope semanal"
        + "</div>", unsafe_allow_html=True)

    # --- 4 columnas, una por turno ---
    cols = st.columns(len(catalogo), gap="small")
    for c, t in zip(cols, catalogo):
        del_turno = t_dia[t_dia["turno"] == t["turno"]]
        info = {r.empleado_id: r for r in del_turno.itertuples(index=False)}
        gente = sorted(info, key=lambda e: (rol.get(e, ""), nombre.get(e, e)))
        filas = "".join(
            fila(e, f"{int(info[e].hora_pausa)}:00"
                    + (f" · {int(info[e].hora_fin) - int(info[e].hora_inicio)} h"
                       if int(info[e].hora_fin) - int(info[e].hora_inicio) > 8 else ""))
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

    with st.expander("Cobertura por hora" + (" · falta gente" if faltas_dia else ""), expanded=bool(faltas_dia)):
        grafica_cobertura(rep, t_dia, f, faltas_dia)


def _zona_y_correo_admin(tienda_id: str) -> tuple[str, str]:
    """Zona de la tienda y correo de su admin regional (vacío si no hay)."""
    try:
        zona = usuarios.zona_de_cluster(tiendas_df.set_index("tienda_id").loc[tienda_id, "cluster_id"])
    except ValueError:   # clúster que no está en ZONAS (archivos propios de una cuenta)
        zona = "sin_zona"
    adm = usuarios_df[(usuarios_df["rol"] == "admin") & (usuarios_df["zona_id"] == zona)]
    correo = str(adm["email"].iloc[0]) if len(adm) and pd.notna(adm["email"].iloc[0]) else ""
    return zona, correo


def _avisar_deshecho(tienda_id: str, f: date, persona: str) -> None:
    """Si el cambio deshecho había generado una alerta al admin, le avisa que ya se revirtió."""
    todas = notificaciones.cargar_notificaciones(DATA_DIR)
    if todas.empty:
        return
    previas = todas[(todas["tipo"] == "turno_calificado") & (todas["tienda_id"].astype(str) == tienda_id)
                    & (todas["fecha"].astype(str).str[:10] == f.isoformat())
                    & todas["mensaje"].astype(str).str.contains(f"movió a {persona} a", regex=False)]
    if previas.empty:
        return
    zona, correo_adm = _zona_y_correo_admin(tienda_id)
    notificaciones.crear_notificacion(
        DATA_DIR, "zona", zona, "cambio_deshecho", "info",
        f"Tienda {tienda_id} · {fmt_dia(f)}: el gerente deshizo el cambio de {persona}. "
        "Ese turno vuelve al horario sugerido; la alerta anterior ya no aplica.",
        email_destino=correo_adm or None, tienda_id=tienda_id, fecha=f.isoformat())


def _panel_cambio(rep, tienda_id, clave, f, t_dia, plantilla, nombre, rol, ausentes, catalogo) -> str | None:
    """Panel de cambio. Regresa a la persona seleccionada (para resaltarla en las columnas)."""
    ediciones = st.session_state["ediciones"].setdefault(clave, [])
    with st.container(border=True, key="panel_cambio"):
        st.markdown("<div class='seccion' style='margin-top:0'>Cambiar a alguien de turno</div>",
                    unsafe_allow_html=True)
        turno_de = dict(zip(t_dia["empleado_id"], t_dia["turno"]))
        horas_de = {r.empleado_id: (int(r.hora_inicio), int(r.hora_fin)) for r in t_dia.itertuples(index=False)}
        candidatos = sorted(plantilla["empleado_id"], key=lambda e: nombre.get(e, e))
        c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
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
        intento = (emp, nuevo, f)   # se aplica al elegir el turno; "Deshacer" lo revierte
        if emp and nuevo and st.session_state.get("_ultimo_intento") != intento:
            st.session_state["_ultimo_intento"] = intento
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
                    zona, correo_adm = _zona_y_correo_admin(tienda_id)
                    notificaciones.crear_notificacion(
                        DATA_DIR, "zona", zona, "turno_calificado",
                        "critico" if calif["calificacion"] == "No recomendado" else "advertencia",
                        f"Tienda {tienda_id} · {fmt_dia(f)}: el gerente movió a {nombre.get(emp, emp)} a "
                        f"{nuevo}. {calif['calificacion']}: {calif['mensaje']}",
                        email_destino=correo_adm or None, tienda_id=tienda_id, fecha=f.isoformat())
            guardar_ediciones(st.session_state["ediciones"])
            st.rerun()

        error = st.session_state.get(f"error_{clave}")
        calif = st.session_state.get(f"calif_{clave}")
        if ediciones and not calif and not error:   # cambios guardados de otra sesión
            calif = _calificar(rep, tienda_id, clave)
        if error:
            aviso(error, "mal")
        elif calif and ediciones:
            tipo = {"Neutral": "bien", "Aceptable": "ojo", "Caro": "ojo"}.get(calif["calificacion"], "mal")
            c_msg, c_btn = st.columns([5, 1], vertical_alignment="center")
            with c_msg:
                aviso(f"<b>{calif['calificacion']}.</b> {calif['mensaje']} "
                      f"<span style='color:var(--ink-2)'>· {len(ediciones)} cambio{'s' if len(ediciones) != 1 else ''} esta semana</span>", tipo)
            if c_btn.button("Deshacer", icon=":material/undo:", key="deshacer", width="stretch"):
                ultimo = ediciones.pop()
                guardar_ediciones(st.session_state["ediciones"])
                st.session_state.pop("_ultimo_intento", None)
                registrar("cambio_deshecho", f"{nombre.get(ultimo[0], ultimo[0])} ({ultimo[0]}) · {ultimo[1]}",
                          alcance=("tienda", tienda_id))
                _avisar_deshecho(tienda_id, ultimo[1], nombre.get(ultimo[0], ultimo[0]))
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
    _d = calif["delta_costo_mxn"]
    registrar("turno_calificado", f"{calif['calificacion']} (costo {'+' if _d >= 0 else '−'}{mxn(abs(_d))})",
              alcance=("tienda", tienda_id))
    return calif


def pagina_resumen() -> None:
    semana = st.session_state["semana"]
    alcance = ("toda la red" if auth["rol"] == "super_admin"
               else f"zona {usuarios.ZONAS[auth['zona_id']]['nombre']}")
    encabezado("Resumen", f"Ahorro de la semana en {alcance} · {len(visibles)} tiendas.")
    barra_fechas(f"{fmt_rango_semana(semana)}", "semana", "res", domingo=semana)
    if faltan_archivos(semana):
        return
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
                obtener_semana(t, semana)
                marcar_calculada(t, semana)
            registrar("red_calculada", f"{len(faltan)} tiendas, semana {semana.isoformat()}")
            st.rerun()
    if not listas:
        return
    resultados = {t: obtener_semana(t, semana) for t in listas}
    cons = vista_red.consolidar_resultados(resultados, tiendas_df)
    rk = cons["ranking_tiendas"]
    n_ok = int(rk["cumple_minimo_8pct"].sum())
    tiles([
        ("Ahorro de la semana", mxn(cons["ahorro_total_red_mxn"]), f"{pct(cons['ahorro_pct_red'])} del costo actual",
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
    cap_red = sum((r["propuesta"].get("horas_capacidad_liberada") or 0) for r in resultados.values())
    sin_p = sum((r["propuesta"].get("horas_subdotacion_total") or 0) for r in resultados.values())
    sin_b = sum((r["base"].get("horas_subdotacion_total") or 0) for r in resultados.values())
    st.caption("Línea punteada = meta mínima de 8%. El ahorro es dinero que deja de salir (sobre todo horas "
               f"extra); el sueldo de tiempo completo se paga igual. Capacidad liberada en estas tiendas: "
               f"{cap_red:,.0f} h por semana, holgura para absorber la baja de jornada sin contratar. "
               f"Demanda sin cubrir: {sin_p:,} h con Alvea contra {sin_b:,} h con el rol fijo; la diferencia "
               "se resta del ahorro.")
    if getattr(precalculado, "ultimo_error", None) and auth_real["rol"] == "super_admin":
        aviso("<b>Algunos horarios guardados no se pudieron abrir</b> y se están recalculando en vivo "
              f"(más lento). Detalle técnico: {precalculado.ultimo_error}", "ojo")
    with st.expander("Ver tabla"):
        st.dataframe(rk[["tienda_id", "cluster_id", "formato", "ahorro_mxn", "ahorro_pct", "Estado"]],
                     hide_index=True, width="stretch",
                     column_config={"tienda_id": "Tienda", "cluster_id": "Clúster", "formato": "Formato",
                                    "ahorro_mxn": st.column_config.NumberColumn("Ahorro (MXN)", format="$%,.0f"),
                                    "ahorro_pct": st.column_config.NumberColumn("Ahorro", format="percent")})


def pagina_avisos() -> None:
    gestor = auth["rol"] != "manager"
    encabezado("Avisos", "Lo que necesita tu atención" + (" y quién hizo qué." if gestor else "."))
    lista_avisos()
    if gestor:
        with st.expander("Historial: quién hizo qué y cuándo"):
            bloque_historial()


def lista_avisos() -> None:
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
        c1, c2, c3 = st.columns([8, 1.1, 1], vertical_alignment="center")
        with c1:
            aviso(f"{'<b>' if no_leida else ''}{n['mensaje']}{'</b>' if no_leida else ''}"
                  f"<div class='leyenda' style='margin-top:3px'>{cuando}"
                  f"{' · también por correo' if n.get('correo_enviado') is True else ''}</div>",
                  tipo.get(n["severidad"], "bien"))
        t_id, fe = str(n.get("tienda_id") or ""), str(n.get("fecha") or "")
        if t_id not in ("", "nan") and fe not in ("", "nan") and t_id in set(visibles["tienda_id"]):
            if c2.button("Ver día", key=f"ver_{n['id']}", icon=":material/calendar_today:"):
                if no_leida:
                    notificaciones.marcar_leidas(DATA_DIR, [n["id"]], auth_real["usuario"])
                st.session_state["tienda_sel"] = st.session_state["hor_tienda"] = t_id
                ir_a_fecha(date.fromisoformat(fe[:10]))
                st.session_state["cal_vista"] = "Día"
                st.session_state["pagina"] = "Horario"
                st.rerun()
        if no_leida and c3.button("Leído", key=f"leido_{n['id']}"):
            notificaciones.marcar_leidas(DATA_DIR, [n["id"]], auth_real["usuario"])
            st.rerun()


def bloque_historial() -> None:
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
    df["alcance_valor"] = df["alcance_valor"].fillna("").astype(str).replace({"None": "", "nan": ""}).replace("", "Red")
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
    if st.button(f"Guardar {cambios} cambio{'s' if cambios != 1 else ''}" if cambios else "Sin cambios", type="primary",
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
        aviso(f"<b>{len(pend)} {'regla pendiente' if len(pend) == 1 else 'reglas pendientes'} de validar con un abogado laboral</b> "
              f"(tramo de horas extra al triple, art. 68).", "ojo")
    with st.expander("Trazabilidad completa"):
        st.dataframe(tabla, hide_index=True, width="stretch")


SET_EJEMPLO = archivos.RAIZ_REPO / "archivos_para_subir" / "semana4oct_2026_promo_cfo"
MAX_ANTES_DESPUES = 12   # tiendas que se calculan solas al aplicar: su primera semana (~1 min cada una)


def leer_subidos(subidos: list) -> list[tuple[str, str, pd.DataFrame]]:
    """Lee y reconoce cada archivo; muestra qué es. Regresa los que se pueden aplicar."""
    listos = []
    for f in subidos or []:
        try:
            df = pd.read_csv(f, compression="gzip" if f.name.endswith(".gz") else None)
        except Exception:
            aviso(f"<b>{f.name}</b>: no se pudo leer. Guárdalo como CSV (separado por comas).", "mal")
            continue
        tipo = archivos.detectar_tipo(df)
        error = archivos.validar(tipo, df) if tipo else "sus columnas no corresponden a ningún archivo"
        if error:
            aviso(f"<b>{f.name}</b>: {error}.", "mal")
            continue
        info = archivos.TIPOS[tipo]
        if info["semanal"]:
            fechas = pd.to_datetime(df["fecha"]).dt.date
            doms = sorted({archivos.domingo_de(x) for x in fechas})
            quien = df["tienda_id"].nunique() if "tienda_id" in df.columns else df["empleado_id"].nunique()
            detalle = (f"{fechas.nunique()} días · {fmt_rango_semana(doms[0])}"
                       + (f" a {fmt_rango_semana(doms[-1])}" if len(doms) > 1 else "")
                       + f" · {quien:,} {'tiendas' if 'tienda_id' in df.columns else 'personas'}")
        else:
            detalle = f"{len(df):,} filas"
        aviso(f"<b>{f.name}</b> → {info['nombre']} · {detalle}", "bien")
        listos.append((f.name, tipo, df))
    return listos


def _cifras(rep: dict, tienda_id: str) -> dict:
    a = rep["ahorro_semanal"]
    turnos = turnos_vigentes(rep, tienda_id)
    return {"ahorro": float(a["ahorro_total_mxn"]), "pct": float(a["ahorro_pct"]),
            "pico": int(resumen_diario(rep, turnos)["pico_sin"].sum())}


def _tocados(listos: list) -> list[tuple[str, date]]:
    """(tienda, semana) que tocan los archivos: las tiendas que traen y las semanas de sus fechas."""
    plantilla = datos_fijos()["plantilla"]
    tienda_de = dict(zip(plantilla["empleado_id"].astype(str), plantilla["tienda_id"].astype(str)))
    for _, tipo, df in listos:
        if tipo == "plantilla":
            tienda_de.update(zip(df["empleado_id"].astype(str), df["tienda_id"].astype(str)))
    tiendas, semanas = set(), set()
    for _, tipo, df in listos:
        if "tienda_id" in df.columns:
            tiendas |= set(df["tienda_id"].astype(str))
        elif "empleado_id" in df.columns:
            tiendas |= {tienda_de[e] for e in df["empleado_id"].astype(str) if e in tienda_de}
        if "fecha" in df.columns:
            semanas |= {archivos.domingo_de(x) for x in pd.to_datetime(df["fecha"]).dt.date}
    if not semanas:                     # solo catálogos: se ve su efecto en la semana actual
        semanas = {st.session_state["semana"]}
    semanas = {d for d in semanas if SEMANA_MIN <= d <= FIN_HORIZONTE}
    return sorted(((t, d) for t in tiendas for d in semanas), key=lambda x: (x[1], x[0]))


def aplicar_archivos(listos: list) -> None:
    """Aplica los archivos y arma el Antes/Después de lo que tocaron (solo si ya estaba calculado,
    el Antes; el Después se calcula aquí mismo, hasta MAX_ANTES_DESPUES tiendas-semana)."""
    pares = _tocados(listos)
    primeras: dict[str, date] = {}
    for t, d in pares:                       # ya vienen ordenados por semana
        primeras.setdefault(t, d)
    elegidos = set(list(primeras.items())[:MAX_ANTES_DESPUES])
    antes = {}
    for t, d in elegidos:
        if archivos.semana_completa(datos_semana(d)) and esta_calculada(t, d):
            antes[(t, d)] = _cifras(obtener_semana(t, d), t)
    orden = list(archivos.TIPOS)   # catálogos primero: el ausentismo usa la plantilla
    hechos = []
    for _, tipo, df in sorted(listos, key=lambda x: orden.index(x[1])):
        r = archivos.cruzar(tipo, df)
        semanas = r["semanas"]
        hechos.append(f"{archivos.TIPOS[tipo]['nombre']}: {r['filas']:,} filas"
                      + (f", {len(semanas)} semana{'s' if len(semanas) != 1 else ''}" if semanas else "")
                      + f" ({r['reemplazadas']:,} reemplazadas)")
    registrar("datos_cargados", "; ".join(hechos))
    existen = set(datos_fijos()["tiendas"]["tienda_id"])
    listos_calc = [(t, d) for t, d in pares if (t, d) in elegidos and t in existen
                   and archivos.semana_completa(datos_semana(d))]
    filas = []
    barra = st.progress(0.0) if listos_calc else None
    for i, (t, d) in enumerate(listos_calc):
        barra.progress(i / len(listos_calc),
                       text=f"Recalculando tienda {t}, semana {fmt_rango_semana(d)} ({i + 1} de {len(listos_calc)})")
        despues = _cifras(obtener_semana(t, d), t)
        marcar_calculada(t, d)
        filas.append({"tienda": t, "semana": d, "antes": antes.get((t, d)), "despues": despues})
    st.session_state["antes_despues"] = {"filas": filas, "hechos": hechos,
                                         "sin_calcular": len(pares) - len(filas)}


def ver_en_horario(tienda_id: str, semana: date) -> None:
    st.session_state.update({"tienda_sel": tienda_id, "hor_tienda": tienda_id, "pagina": "Horario",
                             "cal_vista": "Semana"})
    ir_a_fecha(max(semana, SEMANA_MIN))
    st.rerun()


def tabla_antes_despues(clave: str) -> None:
    ad = st.session_state.get("antes_despues")
    if not ad:
        return
    aviso("<b>Listo.</b> " + " · ".join(ad["hechos"]) + ".", "bien")
    filas = ad["filas"]
    if not filas:
        st.caption("Los archivos no tocaron semanas con archivos completos todavía. "
                   "Cuando estén Tiendas, Plantilla, Tráfico y Ventas de una semana, Alvea la calcula.")
        return
    st.markdown("<div class='seccion'>Antes y después</div>", unsafe_allow_html=True)
    tabla = pd.DataFrame([{
        "Tienda": f["tienda"], "Semana": fmt_rango_semana(f["semana"]),
        "Antes": f"{mxn(f['antes']['ahorro'])} ({pct(f['antes']['pct'])})" if f["antes"] else "—",
        "Después": f"{mxn(f['despues']['ahorro'])} ({pct(f['despues']['pct'])})",
        "Cambio": mxn(f["despues"]["ahorro"] - f["antes"]["ahorro"]).replace("$-", "−$") if f["antes"] else "nuevo",
        "Hora pico": "Cubierta" if f["despues"]["pico"] == 0 else f"Faltan {f['despues']['pico']} h",
        "Meta 8%": "Sí" if f["despues"]["pct"] >= 0.08 else "No",
    } for f in filas])
    st.dataframe(tabla, hide_index=True, width="stretch")
    st.caption("Ahorro de la semana contra el rol fijo de hoy. «Antes» sale vacío si esa tienda-semana no "
               "se había calculado.")
    if ad["sin_calcular"]:
        st.caption(f"Aquí va la primera semana de cada tienda. Las otras {ad['sin_calcular']} tiendas-semana se "
                   "calculan al abrirlas; en Horario → Mes, «Calcular el mes» llena un mes completo.")
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    opciones = {f"Tienda {f['tienda']} · {fmt_rango_semana(f['semana'])}": f for f in filas}
    elegida = c1.selectbox("Ver en Horario", list(opciones), key=f"ad_sel_{clave}")
    if c2.button("Abrir", key=f"ad_ver_{clave}", icon=":material/calendar_month:", width="stretch"):
        ver_en_horario(opciones[elegida]["tienda"], opciones[elegida]["semana"])


def subir_y_aplicar(clave: str) -> None:
    n_up = st.session_state.get("_n_upload", 0)
    subidos = st.file_uploader("Archivos", type=["csv", "gz"], accept_multiple_files=True,
                               key=f"up_{clave}_{n_up}", label_visibility="collapsed")
    listos = leer_subidos(subidos)
    if listos and st.button(f"Aplicar {len(listos)} archivo{'s' if len(listos) != 1 else ''}", type="primary",
                            key=f"aplicar_{clave}"):
        aplicar_archivos(listos)
        st.session_state["_n_upload"] = n_up + 1
        if clave == "ob":
            cuentas.fijar_paso(DATA_RAIZ, CUENTA["correo"], 3)
        st.rerun()


def descargas_formato(clave: str) -> None:
    sem = st.date_input("Semana", value=st.session_state["semana"], min_value=SEMANA_MIN,
                        max_value=FIN_HORIZONTE, format="DD/MM/YYYY", key=f"sem_desc_{clave}")
    dom = archivos.domingo_de(sem)
    cols = st.columns(5)
    for c, (tipo, info) in zip(cols, archivos.TIPOS.items()):
        df = archivos.formato(tipo, dom)
        etiqueta = info["nombre"] + (f" · {dom.day:02d}/{dom.month:02d}" if info["semanal"] else "")
        c.download_button(etiqueta, df.to_csv(index=False).encode("utf-8"),
                          f"{tipo}_{dom.isoformat()}.csv" if info["semanal"] else f"{tipo}.csv", "text/csv",
                          icon=":material/download:", width="stretch", help=", ".join(info["columnas"]),
                          key=f"desc_{clave}_{tipo}")
    if archivos.vacio() and datos_fijos()["tiendas"].empty:
        st.caption("Tu espacio está vacío: los formatos bajan solo con encabezados.")


def botones_espacio(clave: str) -> None:
    """Volver al ejemplo / Vaciar (cuentas) o Volver a los originales (demo)."""
    c1, c2, _ = st.columns([1.3, 1, 1.7])
    if CUENTA:
        cols = iter((c1, c2))
        if archivos.hay_subidos() and next(cols).button("Volver a los archivos de ejemplo",
                                                        icon=":material/restart_alt:", key=f"rest_{clave}",
                                                        width="stretch"):
            dialogo_restaurar()
        if not (archivos.vacio() and not archivos.hay_subidos_reales()) and next(cols).button(
                "Vaciar", icon=":material/delete_sweep:", key=f"vaciar_{clave}", width="stretch"):
            dialogo_vaciar()
    elif archivos.hay_subidos() and c1.button("Volver a los archivos originales", icon=":material/restart_alt:",
                                              key=f"rest_{clave}", width="stretch"):
        dialogo_restaurar()


def pagina_datos() -> None:
    encabezado("Datos", "Los archivos con los que Alvea arma los horarios. "
               + ("Lo que subas solo cambia tu espacio." if CUENTA else "Lo que subas cambia los horarios de todos."))
    st.markdown("<div class='seccion'>Archivos en uso</div>", unsafe_allow_html=True)
    if archivos.vacio():
        st.caption("Espacio vacío: solo cuentan los archivos que subas.")
    st.dataframe(archivos.inventario(), hide_index=True, width="stretch")

    st.markdown("<div class='seccion'>Subir archivos</div>", unsafe_allow_html=True)
    st.caption("Uno o varios CSV. Alvea reconoce cuál es por sus columnas y la semana por sus fechas; "
               "cada fila reemplaza solo lo mismo (misma tienda y día, mismo empleado y día) y lo demás se queda.")
    subir_y_aplicar("datos")
    tabla_antes_despues("datos")

    st.markdown("<div class='seccion'>Descargar archivos</div>", unsafe_allow_html=True)
    descargas_formato("datos")
    botones_espacio("datos")


def fijar_espacio() -> None:
    """Los diálogos se vuelven a correr solos, sin la parte de arriba del script: fija otra vez el espacio."""
    archivos.usar_espacio(DATA_DIR / "archivos" if CUENTA else None)


@st.dialog("Volver a los archivos originales")
def dialogo_restaurar() -> None:
    fijar_espacio()
    st.write(("Se quita todo lo que subiste y tu espacio vuelve a los archivos de ejemplo."
              if CUENTA else "Se quita todo lo que se ha subido y los horarios vuelven a los archivos con los que "
                             "arrancó Alvea. Cambia los horarios de todos."))
    c1, c2 = st.columns(2)
    if c1.button("Sí, quitar lo subido", type="primary", width="stretch"):
        n = archivos.restaurar_originales()
        registrar("datos_restablecidos", f"{n} archivos")
        st.session_state["antes_despues"] = None
        st.session_state["_toast"] = f"Se quitaron {n} archivos subidos."
        st.rerun()
    if c2.button("Cancelar", width="stretch"):
        st.rerun()


@st.dialog("Vaciar tu espacio")
def dialogo_vaciar() -> None:
    fijar_espacio()
    st.write("Se quitan los archivos de ejemplo y todo lo que subiste. Para ver horarios tendrás que subir "
             "Tiendas y Plantilla y, por semana, Tráfico, Ventas y Ausentismo. Empieza con 1 a 3 tiendas: "
             "cada tienda tarda cerca de 1 min por semana la primera vez.")
    c1, c2 = st.columns(2)
    if c1.button("Sí, vaciar", type="primary", width="stretch"):
        n = archivos.vaciar()
        registrar("espacio_vaciado", f"{n} archivos subidos quitados")
        st.session_state["antes_despues"] = None
        st.session_state["_toast"] = "Tu espacio quedó vacío. Sube tus archivos para empezar."
        st.rerun()
    if c2.button("Cancelar", width="stretch"):
        st.rerun()


def pagina_primeros_pasos() -> None:
    paso = int(CUENTA["ob"] or 0) or 1
    nombre = CUENTA["nombre"].split()[0]
    encabezado("Primeros pasos", f"Paso {paso} de {cuentas.PASOS_OB}")
    st.progress(paso / cuentas.PASOS_OB)

    def ir(n: int) -> None:
        cuentas.fijar_paso(DATA_RAIZ, CUENTA["correo"], n)
        registrar("primeros_pasos", f"paso {n}" if n else "terminado")
        st.rerun()

    def navegar(atras: bool = True, siguiente: str | None = "Siguiente", principal: bool = True) -> None:
        c1, _, c3 = st.columns([1, 2, 1.2])
        if atras and paso > 1 and c1.button("Atrás", icon=":material/arrow_back:", width="stretch"):
            ir(paso - 1)
        if siguiente and c3.button(siguiente, type="primary" if principal else "secondary", width="stretch"):
            ir(paso + 1)

    if paso == 1:
        st.markdown(f"### Hola, {nombre}")
        st.markdown(
            "La reforma baja la jornada de **48 h en 2026 a 40 h en 2030**. Alvea arma el horario de cada "
            "tienda cada semana para que **cueste al menos 8% menos** que el rol fijo de hoy, **sin dejar la "
            "hora pico sin gente** y siempre dentro de la ley.\n\n"
            "Tu espacio ya trae **archivos de ejemplo de 50 tiendas**, así que ves resultados desde ya. "
            "En 3 pasos más vas a subir archivos y ver cómo Alvea rehace los horarios solo.")
        tiles([("Tope legal hoy", f"{horas_regimen(SEMANA_MIN)} h", "por semana", "", True),
               ("Meta de ahorro", "≥ 8%", "contra el rol fijo", ""),
               ("En 2030", "40 h", "mismo proceso, tope menor", "")])
        navegar(siguiente="Empezar")
    elif paso == 2:
        st.markdown("### Sube archivos")
        st.markdown("Alvea usa cinco archivos: **Tiendas** y **Plantilla** (uno cada uno) y, por semana, "
                    "**Tráfico**, **Ventas** y **Ausentismo**. Elige una:")
        with st.container(border=True):
            st.markdown("**A. Prueba rápida con el set de ejemplo** · promo de fin de semana en 3 tiendas "
                        "(4–10 oct 2026): tráfico y ventas +35% el viernes y sábado, y 10 faltas más en T009. "
                        "Tarda unos 3 min.")
            c1, c2 = st.columns(2)
            if c1.button("Aplicar el set de ejemplo", type="primary", icon=":material/bolt:", width="stretch",
                         disabled=not SET_EJEMPLO.exists() or archivos.vacio()):
                listos = [(p.name, archivos.detectar_tipo(pd.read_csv(p)), pd.read_csv(p))
                          for p in sorted(SET_EJEMPLO.glob("*.csv"))]
                aplicar_archivos(listos)
                ir(3)
            import io, zipfile
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for p in sorted(SET_EJEMPLO.glob("*.csv")):
                    z.write(p, p.name)
            c2.download_button("Descargar el set (zip)", buf.getvalue(), "Alvea_set_ejemplo_4oct.zip",
                               "application/zip", icon=":material/download:", width="stretch")
            if archivos.vacio():
                st.caption("Tu espacio está vacío: el set de ejemplo necesita los archivos de ejemplo. "
                           "Usa «Volver a los archivos de ejemplo» abajo o sube los tuyos.")
        with st.container(border=True):
            st.markdown("**B. Sube tus archivos** · baja los formatos, llénalos y súbelos. Cada fila reemplaza "
                        "solo lo mismo (misma tienda y día); lo demás se queda.")
            with st.expander("Descargar formatos"):
                descargas_formato("ob")
            subir_y_aplicar("ob")
        with st.container(border=True):
            st.markdown("**C. Desde cero** · vacía tu espacio y sube solo lo tuyo. Empieza con 1 a 3 tiendas.")
            botones_espacio("ob")
        navegar(siguiente="Saltar este paso", principal=False)
    elif paso == 3:
        st.markdown("### Así lo rehízo Alvea")
        if st.session_state.get("antes_despues"):
            st.markdown("Solo se recalcularon las tiendas que tocaron tus archivos; las demás siguen igual. "
                        "Abre cualquiera en Horario para ver quién trabaja en cada turno.")
            tabla_antes_despues("ob")
        else:
            aviso("Aún no aplicas archivos en esta sesión. Regresa al paso 2 o sigue: puedes subirlos "
                  "cuando quieras en <b>Datos</b>.", "ojo")
        navegar()
    else:
        st.markdown("### Qué sigue")
        st.markdown(
            "- **Resumen**: ahorro de la semana de todas tus tiendas y cuáles llegan a la meta.\n"
            "- **Horario**: mes, semana y día de cada tienda; en Día puedes mover a alguien de turno y "
            "Alvea califica el cambio.\n"
            "- **Datos**: sube más archivos, bájalos, vuelve a los de ejemplo o vacía tu espacio.\n"
            "- **Reglas legales**: cómo baja la jornada cada año y de dónde sale cada regla.\n\n"
            "Toca **Jornada 48 h · 2026** en cualquier fecha para ver el mismo horario con el tope de otro año.")
        c1, _, c3 = st.columns([1, 2, 1.2])
        if c1.button("Atrás", icon=":material/arrow_back:", width="stretch"):
            ir(3)
        if c3.button("Ir al Resumen", type="primary", width="stretch"):
            cuentas.fijar_paso(DATA_RAIZ, CUENTA["correo"], 0)
            registrar("primeros_pasos", "terminado")
            st.session_state["pagina"] = "Resumen"
            st.rerun()


RUTAS = {"Primeros pasos": pagina_primeros_pasos, "Resumen": pagina_resumen, "Horario": pagina_horario,
         "Avisos": pagina_avisos, "Usuarios": pagina_usuarios,
         "Reglas legales": pagina_reglas, "Datos": pagina_datos}
if (CUENTA and datos_fijos()["tiendas"].empty and pagina in ("Resumen", "Horario")):
    encabezado(pagina, "")
    aviso("<b>Tu espacio está vacío.</b> Sube Tiendas y Plantilla y, por semana, Tráfico, Ventas y Ausentismo "
          "en <b>Datos</b>, o vuelve a los archivos de ejemplo.", "ojo")
    if st.button("Ir a Datos", type="primary"):
        st.session_state["pagina"] = "Datos"
        st.rerun()
else:
    RUTAS[pagina]()
