"""Interfaz Streamlit de Alvea PMV — reto técnico de ALVENA/AIvena (Autoservicio MX).

Arranca sin pasos manuales: genera el dataset sintético si no existe y
calcula bajo demanda (por tienda) el escenario base, la propuesta del
optimizador y el techo teórico, cacheando resultados en disco para no
recalcular en cada rerun. Ver README.md para correrla con Docker o local.

NOTA DE RENDIMIENTO (léela antes de la demo): cada tienda resuelve un
problema CP-SAT de ~80 empleados x 7 días x 17 horas. Con el límite de
tiempo por defecto (10s), calcular la RED COMPLETA (50 tiendas x 2 corridas
—operativa y techo—) toma varios minutos. La Vista Red deja escoger cuántas
tiendas calcular para que las primeras pruebas sean rápidas; usa 50 para la
corrida real antes de la demo (botón "Calcular red completa").
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_sortables import sort_items

from jornada40 import calendario, costos_ahorro, datos_sinteticos, demanda_personal, escenario_base, optimizador, reglas, simulacros, usuarios, vista_red

st.set_page_config(page_title="Alvea PMV — Autoservicio MX", layout="wide")

DATA_DIR = Path("data")
RESULTADOS_DIR = DATA_DIR / "resultados"
ANIO_DEFAULT = 2027
FECHA_INICIO_DEFAULT = reglas.semana_domingo_a_sabado(date(ANIO_DEFAULT, 1, 1))[0]
# El calendario (mes/semana/día del gerente) navega cualquier semana del
# año -- el dataset de ejemplo cubre el año completo (1-ene a 31-dic) para
# que cualquier semana se pueda calcular bajo demanda, no solo la primera.
FECHA_FIN_DATASET_EJEMPLO = date(ANIO_DEFAULT, 12, 31)
TIEMPO_LIMITE_SEG_DEFAULT = 10.0


# ---------------------------------------------------------------------------
# Carga y cálculo (cacheados)
# ---------------------------------------------------------------------------

ARCHIVOS_DATASET = ["tiendas", "trafico", "ventas", "plantilla", "ausentismo"]
COLUMNAS_CON_FECHA = {"trafico", "ventas", "ausentismo"}


@st.cache_data(show_spinner="Generando dataset de ejemplo (año completo, primera vez)...")
def cargar_datos_ejemplo() -> dict[str, pd.DataFrame]:
    """Dataset sintético (marca ficticia) que se usa mientras no se sube nada propio.

    Cubre el año completo (no solo una semana) para que el calendario del
    gerente pueda calcular cualquier semana bajo demanda.
    """
    if all((DATA_DIR / f"{n}.csv").exists() for n in ARCHIVOS_DATASET):
        datos = {n: pd.read_csv(DATA_DIR / f"{n}.csv", parse_dates=["fecha"] if n in
                                 COLUMNAS_CON_FECHA else None)
                 for n in ARCHIVOS_DATASET}
        # Dataset viejo (de antes del calendario) -- traía solo 7 días. Se
        # detecta por el rango de fechas y se regenera al año completo.
        rango_trafico = pd.to_datetime(datos["trafico"]["fecha"])
        # Dataset viejo (de antes de la columna "nombre") -- se detecta por
        # el esquema y se regenera; si no, los CSV cacheados en disco de una
        # corrida anterior nunca recogen columnas nuevas del generador
        # aunque se redeploye el código (el CSV en disco gana la carrera).
        _esquema_desactualizado = "nombre" not in datos["plantilla"].columns
        if rango_trafico.max() - rango_trafico.min() < pd.Timedelta(days=30) or _esquema_desactualizado:
            for archivo in ARCHIVOS_DATASET:
                (DATA_DIR / f"{archivo}.csv").unlink(missing_ok=True)
        else:
            return datos
    return datos_sinteticos.generar_dataset_completo(
        FECHA_INICIO_DEFAULT, FECHA_FIN_DATASET_EJEMPLO, seed=42, out_dir=DATA_DIR,
    )


def cargar_datos() -> dict[str, pd.DataFrame]:
    """Usa los archivos que el usuario haya subido en 'Cargar datos'; si falta
    alguno, completa con el dataset de ejemplo (nunca se detiene la app)."""
    subidos = st.session_state.get("datos_subidos", {})
    ejemplo = cargar_datos_ejemplo()
    return {n: subidos.get(n, ejemplo[n]) for n in ARCHIVOS_DATASET}


def _normalizar_fechas(df: pd.DataFrame) -> pd.DataFrame:
    if "fecha" in df.columns:
        df = df.copy()
        df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
    return df


@st.cache_data(show_spinner=False)
def calcular_resultado_tienda(
    tienda_id: str, anio: int, tiempo_limite_seg: float,
    _tiendas: pd.DataFrame, _trafico: pd.DataFrame, _ventas: pd.DataFrame,
    _plantilla: pd.DataFrame, _ausentismo: pd.DataFrame,
    fecha_inicio: date = FECHA_INICIO_DEFAULT,
) -> dict:
    """Calcula base + propuesta + techo + reporte CFO de UNA tienda, UNA semana.

    Los DataFrames llevan "_" al inicio del nombre para que Streamlit no
    intente hashear su contenido (son estáticos por sesión); el cache se
    invalida por (tienda_id, anio, tiempo_limite_seg, fecha_inicio). Usa
    "Recalcular todo" en la barra lateral si cambiaste los datos de origen.

    fecha_inicio es el domingo de la semana a calcular (domingo-sábado, ver
    reglas.semana_domingo_a_sabado) -- el dataset trae el año completo, así
    que aquí se recorta a los 7 días de esa semana antes de calcular; el
    resto del pipeline (demanda, escenario base, optimizador) sigue
    operando sobre una sola semana como siempre.
    """
    fecha_fin = fecha_inicio + timedelta(days=6)
    tiendas_t = _normalizar_fechas(_tiendas.loc[_tiendas["tienda_id"] == tienda_id])
    trafico_t = _normalizar_fechas(_trafico.loc[_trafico["tienda_id"] == tienda_id])
    trafico_t = trafico_t.loc[(trafico_t["fecha"] >= fecha_inicio) & (trafico_t["fecha"] <= fecha_fin)]
    ventas_t = _normalizar_fechas(_ventas.loc[_ventas["tienda_id"] == tienda_id])
    ventas_t = ventas_t.loc[(ventas_t["fecha"] >= fecha_inicio) & (ventas_t["fecha"] <= fecha_fin)]
    plantilla_t = _plantilla.loc[_plantilla["tienda_id"] == tienda_id]
    empleados_t = set(plantilla_t["empleado_id"])
    ausentismo_t = _normalizar_fechas(_ausentismo.loc[_ausentismo["empleado_id"].isin(empleados_t)])
    ausentismo_t = ausentismo_t.loc[(ausentismo_t["fecha"] >= fecha_inicio) & (ausentismo_t["fecha"] <= fecha_fin)]

    demanda = demanda_personal.calcular_demanda_tienda(tienda_id, trafico_t, ventas_t, tiendas_t)
    demanda = demanda_personal.marcar_franjas_pico(demanda)

    base = escenario_base.calcular_horario_base_tienda(
        tienda_id, anio, plantilla_t, ausentismo_t, demanda, fecha_inicio=fecha_inicio,
    )
    propuesta = optimizador.resolver_tienda(
        tienda_id, anio, plantilla_t, demanda, ausentismo_t,
        tiempo_limite_seg=tiempo_limite_seg, fecha_inicio=fecha_inicio,
    )
    techo = optimizador.resolver_techo_teorico(
        tienda_id, anio, plantilla_t, demanda, ausentismo_t,
        tiempo_limite_seg=tiempo_limite_seg, fecha_inicio=fecha_inicio,
    )
    reporte = costos_ahorro.generar_reporte_cfo(tienda_id, base, propuesta, techo, anio)
    reporte["status"] = propuesta["status"]
    reporte["propuesta"] = propuesta
    reporte["base"] = base
    reporte["techo"] = techo
    reporte["demanda"] = demanda
    reporte["fecha_inicio"] = fecha_inicio
    return reporte


def calcular_red(tiendas_ids: list[str], anio: int, tiempo_limite_seg: float, datos: dict,
                  fecha_inicio: date = FECHA_INICIO_DEFAULT) -> dict[str, dict]:
    resultados = {}
    barra = st.progress(0.0, text="Calculando tiendas...")
    for i, tid in enumerate(tiendas_ids):
        resultados[tid] = calcular_resultado_tienda(
            tid, anio, tiempo_limite_seg,
            datos["tiendas"], datos["trafico"], datos["ventas"], datos["plantilla"], datos["ausentismo"],
            fecha_inicio=fecha_inicio,
        )
        barra.progress((i + 1) / len(tiendas_ids), text=f"Calculando tiendas... {tid} ({i+1}/{len(tiendas_ids)})")
    barra.empty()
    return resultados


# ---------------------------------------------------------------------------
# Autenticacion (sencilla, PMV -- ver jornada40/usuarios.py) + Interfaz
# ---------------------------------------------------------------------------

datos = cargar_datos()
tiendas_df = datos["tiendas"]


# El marcador de versión fuerza a Streamlit a invalidar su caché cuando
# cambia el ESQUEMA de usuarios (jornada40/usuarios.py). st.cache_data solo
# hashea el código fuente de esta función, no el de generar_usuarios() --
# sin este marcador, un despliegue puede seguir sirviendo un DataFrame
# viejo (por eso el bug real en Streamlit Cloud: "KeyError: 'usuario'"
# después de renombrar columnas). Súbele el número cada vez que cambie el
# esquema de generar_usuarios (columnas, roles, formato del usuario, etc.).
_ESQUEMA_USUARIOS_VERSION = 3


@st.cache_data(show_spinner=False)
def _cargar_usuarios(_tiendas: pd.DataFrame, _version: int = _ESQUEMA_USUARIOS_VERSION) -> pd.DataFrame:
    return usuarios.generar_usuarios(_tiendas, seed=42)


# El flag "activo" (Gestión de usuarios) vivía SOLO en st.session_state, que
# en Streamlit es por-sesión-de-navegador: un admin que desactivaba a un
# gerente no bloqueaba nada para nadie más -- cualquier otra sesión (incluida
# la del propio gerente "desactivado") seguía viendo el dataset base con
# activo=True. Se persiste ahora en disco (compartido por todo el proceso,
# no por sesión) y se recarga en CADA rerun, no solo la primera vez.
_RUTA_ESTADO_USUARIOS = DATA_DIR / "usuarios_estado.csv"


def _cargar_estado_usuarios() -> dict[str, bool]:
    if not _RUTA_ESTADO_USUARIOS.exists():
        return {}
    try:
        estado = pd.read_csv(_RUTA_ESTADO_USUARIOS)
        return dict(zip(estado["usuario"], estado["activo"]))
    except Exception:
        return {}


def _guardar_estado_usuarios(usuarios_df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    usuarios_df[["usuario", "activo"]].to_csv(_RUTA_ESTADO_USUARIOS, index=False)


def _usuarios_con_estado(_tiendas: pd.DataFrame) -> pd.DataFrame:
    """Base de usuarios + overrides de 'activo' persistidos en disco.

    No está cacheada (la lectura del CSV es barata) para que un cambio
    guardado por CUALQUIER sesión/usuario se vea de inmediato en el
    siguiente rerun de todas las demás -- incluida la pantalla de login.
    """
    base = _cargar_usuarios(_tiendas).copy()
    overrides = _cargar_estado_usuarios()
    if overrides:
        base["activo"] = base.apply(
            lambda fila: overrides.get(fila["usuario"], fila["activo"]), axis=1,
        )
    return base


_CSS_LOGIN = """
<style>
div[data-testid="stForm"] {
    border: 1px solid rgba(140, 140, 140, 0.35);
    border-radius: 6px;
    padding: 2rem 2rem 1.25rem 2rem;
}
</style>
"""

# Cuadrícula de días estilo Apple Calendar: celdas cuadradas, blancas, con
# borde gris fino y números alineados -- reemplaza el look "botón" plano de
# Streamlit por defecto. Los selectores usan la clase `st-key-<key>` que
# Streamlit agrega desde 1.3x, así que cada tipo de botón (día del mes,
# flechas de navegación, "Ver día") se puede estilizar por separado sin
# tocar los demás widgets de la página. Solo cosmético -- el comportamiento
# (clic = navegar) es el mismo botón de siempre.
_CSS_CALENDARIO = """
<style>
/* celdas del mes (cal_dia_YYYY-MM-DD) */
div[class*="st-key-cal_dia_"] button {
    aspect-ratio: 1;
    width: 100%;
    min-height: 3.4rem;
    background: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 10px;
    color: #1d1d1f;
    font-size: 0.95rem;
    font-weight: 500;
    line-height: 1.25;
    white-space: pre-line;
    box-shadow: none;
    transition: border-color .12s ease, background .12s ease;
}
div[class*="st-key-cal_dia_"] button:hover:not(:disabled) {
    border-color: #0071e3;
    background: #f5f9ff;
}
div[class*="st-key-cal_dia_"] button:disabled {
    background: #fbfbfd;
    border-color: #e5e5ea;
    color: #6e6e73;
}
/* punto de estado bajo el número de día (reemplaza los emoji 🟢/🔵) --
   verde = semana con horario ya calculado, azul = semana sin calcular */
div[class*="st-key-cal_dia_"][class*="_est-c"] button,
div[class*="st-key-cal_dia_"][class*="_est-p"] button { position: relative; }
div[class*="st-key-cal_dia_"][class*="_est-c"] button::after,
div[class*="st-key-cal_dia_"][class*="_est-p"] button::after {
    content: ""; position: absolute; left: 50%; bottom: 10px;
    width: 6px; height: 6px; border-radius: 999px; transform: translateX(-50%);
}
div[class*="st-key-cal_dia_"][class*="_est-c"] button::after { background: #34c759; }
div[class*="st-key-cal_dia_"][class*="_est-p"] button::after { background: #0071e3; }
/* celda vacía de relleno (antes / después del mes) */
.cal-celda-vacia {
    aspect-ratio: 1;
    min-height: 3.4rem;
    border-radius: 10px;
    background: transparent;
}
/* encabezado Dom/Lun/Mar... */
.cal-encabezado-dia {
    text-align: center;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #6e6e73;
    padding-bottom: 0.35rem;
}
/* flechas de navegación de mes (redondas, discretas) */
div[class*="st-key-cal_mes_prev"] button, div[class*="st-key-cal_mes_next"] button {
    border-radius: 999px;
    border: 1px solid #d2d2d7;
    background: #ffffff;
    color: #1d1d1f;
    font-weight: 500;
}
div[class*="st-key-cal_mes_prev"] button:hover, div[class*="st-key-cal_mes_next"] button:hover {
    border-color: #0071e3;
    color: #0071e3;
}
/* botón "Ver día" dentro de la tarjeta de semana */
div[class*="st-key-cal_verdia_"] button {
    width: 100%;
    border-radius: 8px;
    border: 1px solid #d2d2d7;
    background: #f5f5f7;
    color: #1d1d1f;
    font-size: 0.82rem;
}
div[class*="st-key-cal_verdia_"] button:hover {
    border-color: #0071e3;
    color: #0071e3;
}
</style>
"""

def _pantalla_login() -> None:
    st.markdown(_CSS_LOGIN, unsafe_allow_html=True)
    _, col_mid, _ = st.columns([1, 1.2, 1])
    with col_mid:
        st.markdown("### Alvea PMV")
        with st.form("form_login", border=False):
            usuario_txt = st.text_input("Usuario", placeholder="Usuario (ej. SADMIN, ADMIN-Z1, Man001)",
                                         label_visibility="collapsed")
            password = st.text_input("Contraseña", type="password", placeholder="Contraseña",
                                      label_visibility="collapsed")
            enviado = st.form_submit_button("Entrar", type="primary", width='stretch')

            if enviado:
                # Siempre se lee el estado persistido en disco (no
                # session_state): una cuenta desactivada por un admin en
                # OTRA sesión debe bloquear el login aquí también.
                usuarios_df = _usuarios_con_estado(tiendas_df)
                fila = usuarios.buscar_usuario(usuario_txt, usuarios_df)
                if fila is None:
                    st.error("Usuario no encontrado.")
                elif not fila["activo"]:
                    st.error("Esta cuenta está desactivada. Contacta a HQ para reactivarla.")
                elif password != usuarios.password_login():
                    st.error("Contraseña incorrecta.")
                else:
                    if fila["rol"] == "super_admin":
                        nombre = "SAdmin"
                    elif fila["rol"] == "admin":
                        nombre = f"Admin · {usuarios.ZONAS[fila['zona_id']]['nombre']}"
                    else:
                        nombre = fila["tienda_id"]
                    st.session_state["auth"] = {
                        "rol": fila["rol"], "tienda_id": fila["tienda_id"], "zona_id": fila["zona_id"],
                        "usuario": fila["usuario"], "nombre": nombre,
                    }
                    st.rerun()


if "auth" not in st.session_state:
    _pantalla_login()
    st.stop()

auth_real = st.session_state["auth"]
# Se recarga en cada rerun (no setdefault) para reflejar de inmediato
# cambios de acceso guardados por otra sesión/admin -- ver
# _usuarios_con_estado.
st.session_state["usuarios_df"] = _usuarios_con_estado(tiendas_df)

# Si a la cuenta YA logueada la desactivó otro admin a mitad de sesión, se
# cierra la sesión aquí mismo -- si solo bloqueáramos el login, alguien ya
# adentro seguiría operando hasta que cerrara el navegador.
_fila_actual = usuarios.buscar_usuario(auth_real["usuario"], st.session_state["usuarios_df"])
if _fila_actual is None or not _fila_actual["activo"]:
    del st.session_state["auth"]
    st.error("Esta cuenta fue desactivada. Contacta a HQ para reactivarla.")
    st.stop()

def _tiendas_visibles(auth_: dict, tiendas: pd.DataFrame) -> pd.DataFrame:
    """Subconjunto de tiendas que puede ver/operar este perfil: su tienda
    (manager), su zona (admin regional), o todas (super admin)."""
    if auth_["rol"] == "manager":
        return tiendas[tiendas["tienda_id"] == auth_["tienda_id"]]
    if auth_["rol"] == "admin":
        return usuarios.tiendas_de_zona(auth_["zona_id"], tiendas)
    return tiendas


_CSS_SIDEBAR = """
<style>
/* Encabezado de marca */
.cal-nav-titulo { font-size: 17px; font-weight: 700; letter-spacing: -0.01em; padding: 0 8px 2px 8px; }
.cal-nav-subtitulo { font-size: 12px; color: #6e6e73; padding: 0 8px 16px 8px; }
/* Tarjeta de usuario (avatar + nombre + ámbito) */
.cal-nav-usuario {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 8px; border: 1px solid #ececec; border-radius: 10px;
    margin-bottom: 8px;
}
.cal-nav-avatar {
    width: 32px; height: 32px; border-radius: 999px; color: #ffffff;
    font-size: 12.5px; font-weight: 600; display: flex; align-items: center;
    justify-content: center; flex: 0 0 32px;
}
.cal-nav-usuario-nombre { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cal-nav-usuario-ambito { font-size: 11px; color: #6e6e73; }
/* Botón "Cerrar sesión" */
div[class*="st-key-nav_logout"] button {
    width: 100%; border-radius: 8px; border: 1px solid #d2d2d7;
    background: #ffffff; color: #1d1d1f; font-size: 12.5px; font-weight: 500;
}
div[class*="st-key-nav_logout"] button:hover { border-color: #0071e3; color: #0071e3; }
/* Encabezados de grupo (OPERACIÓN / DATOS / ADMINISTRACIÓN) */
.cal-nav-grupo {
    font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase;
    color: #6e6e73; padding: 4px 8px 6px 8px; margin-top: 10px;
}
/* Filas de navegación: mismo look para todas por defecto */
div[class*="st-key-nav_pg_"] button {
    width: 100%; justify-content: flex-start; text-align: left;
    border: none; background: transparent; border-radius: 8px;
    color: #1d1d1f; font-size: 13.5px; font-weight: 400; padding: 9px 10px;
    box-shadow: none;
}
div[class*="st-key-nav_pg_"] button:hover { background: #f5f5f7; }
div[class*="st-key-nav_pg_"] p { font-size: 13.5px; }
</style>
"""
st.sidebar.markdown(_CSS_SIDEBAR, unsafe_allow_html=True)

if auth_real["rol"] == "super_admin":
    _etiqueta_ambito = "Todas las tiendas"
    _iniciales_usuario, _color_avatar, _nombre_usuario = "SA", "#0071e3", "Super Admin"
elif auth_real["rol"] == "admin":
    _etiqueta_ambito = f"Zona {usuarios.ZONAS[auth_real['zona_id']]['nombre']}"
    _iniciales_usuario, _color_avatar, _nombre_usuario = auth_real["zona_id"][:2].upper(), "#6e6e73", auth_real["nombre"]
else:
    _etiqueta_ambito = "Gerente de tienda"
    _iniciales_usuario, _color_avatar, _nombre_usuario = auth_real["tienda_id"][:2].upper(), "#6e6e73", auth_real["tienda_id"]

st.sidebar.markdown(
    f"<div class='cal-nav-titulo'>Alvea PMV</div>"
    f"<div class='cal-nav-subtitulo'>Autoservicio MX</div>"
    f"<div class='cal-nav-usuario'>"
    f"<div class='cal-nav-avatar' style='background:{_color_avatar};'>{_iniciales_usuario}</div>"
    f"<div style='min-width:0;'>"
    f"<div class='cal-nav-usuario-nombre'>{_nombre_usuario}</div>"
    f"<div class='cal-nav-usuario-ambito'>{_etiqueta_ambito}</div>"
    f"</div></div>",
    unsafe_allow_html=True,
)
if st.sidebar.button("Cerrar sesión", key="nav_logout"):
    del st.session_state["auth"]
    st.rerun()

# Super Admin: puede "ver como" cualquier perfil sin volver a loguearse.
# auth (la variable que usa el resto de la app) queda apuntando al perfil
# simulado; auth_real (arriba) siempre es la sesion real, para gatear
# paginas que solo el super admin/admin de verdad debe tocar (Gestion de
# usuarios), sin importar que perfil este simulando ver.
auth = auth_real
if auth_real["rol"] == "super_admin":
    opciones_ver_como = (
        ["Super Admin (todo)"]
        + [f"Admin-{zid} ({info['nombre']})" for zid, info in usuarios.ZONAS.items()]
        + list(tiendas_df["tienda_id"])
    )
    ver_como = st.sidebar.selectbox("Ver como", opciones_ver_como)
    if ver_como.startswith("Admin-"):
        zid = ver_como.split("-", 1)[1].split(" ", 1)[0]
        auth = {**auth_real, "rol": "admin", "zona_id": zid}
    elif ver_como != "Super Admin (todo)":
        auth = {**auth_real, "rol": "manager", "tienda_id": ver_como}
st.sidebar.divider()

tiendas_visibles_df = _tiendas_visibles(auth, tiendas_df)

if auth["rol"] == "manager":
    # DECISION DE PRODUCTO (21-sep-2026): la pantalla de arranque del gerente
    # deja de ser "Cargar datos" y pasa a ser el Calendario (mes -> semana ->
    # día) -- es como el negocio piensa el horario, no un formulario de carga.
    paginas_negocio = ["Calendario", "Vista Tienda", "Simulacros", "Refuerzos entre tiendas", "Cargar datos"]
else:
    paginas_negocio = ["Cargar datos", "Vista Red", "Vista Tienda", "Calendario", "Simulacros", "Refuerzos entre tiendas"]
if auth_real["rol"] in ("admin", "super_admin"):
    paginas_negocio.append("Gestión de usuarios")
usando_datos_propios = bool(st.session_state.get("datos_subidos"))
etiqueta_datos = "Cargar datos (usando tus archivos)" if usando_datos_propios else "Cargar datos (usando datos de ejemplo)"

_PAGINA_SLUG = {
    "Calendario": "calendario", "Vista Tienda": "vista_tienda", "Vista Red": "vista_red",
    "Simulacros": "simulacros", "Refuerzos entre tiendas": "refuerzos",
    "Cargar datos": "cargar_datos", "Gestión de usuarios": "gestion_usuarios",
}
_PAGINA_ICONO = {
    "Calendario": "calendar_month", "Vista Tienda": "storefront", "Vista Red": "hub",
    "Simulacros": "bolt", "Refuerzos entre tiendas": "swap_horiz",
    "Cargar datos": "upload_file", "Gestión de usuarios": "group",
}
_PAGINA_GRUPO = {
    "Calendario": "Operación", "Vista Tienda": "Operación", "Vista Red": "Operación",
    "Simulacros": "Operación", "Refuerzos entre tiendas": "Operación",
    "Cargar datos": "Datos", "Gestión de usuarios": "Administración",
}
_ORDEN_GRUPOS = ["Operación", "Datos", "Administración"]

st.session_state.setdefault("pagina_actual", paginas_negocio[0])
if st.session_state["pagina_actual"] not in paginas_negocio:
    # el rol/ámbito activo cambió (p. ej. "Ver como") y ya no puede ver la
    # página que tenía seleccionada -- cae a la primera disponible.
    st.session_state["pagina_actual"] = paginas_negocio[0]

for _grupo in _ORDEN_GRUPOS:
    _items_grupo = [p for p in paginas_negocio if _PAGINA_GRUPO.get(p) == _grupo]
    if not _items_grupo:
        continue
    st.sidebar.markdown(f"<div class='cal-nav-grupo'>{_grupo}</div>", unsafe_allow_html=True)
    for _p in _items_grupo:
        _es_activa = st.session_state["pagina_actual"] == _p
        _etiqueta = etiqueta_datos if _p == "Cargar datos" else _p
        if st.sidebar.button(
            _etiqueta, key=f"nav_pg_{_PAGINA_SLUG[_p]}", icon=f":material/{_PAGINA_ICONO[_p]}:",
            width='stretch',
        ):
            st.session_state["pagina_actual"] = _p
            st.rerun()
pagina = st.session_state["pagina_actual"]

st.sidebar.markdown(
    "<style>"
    f"div[class*='st-key-nav_pg_{_PAGINA_SLUG[pagina]}'] button {{"
    "background:#eaf3ff !important;color:#0071e3 !important;font-weight:600 !important;"
    "border-color:transparent !important;box-shadow:none !important;}}"
    "</style>",
    unsafe_allow_html=True,
)
# Punto de estado junto a "Cargar datos" (reemplaza el emoji 🟢/🔵 anterior,
# que no encajaba con el resto del menú -- mismo significado: verde = ya
# subiste tus archivos, azul = todavía viendo el ejemplo).
_color_punto_datos = "#34c759" if usando_datos_propios else "#0071e3"
st.sidebar.markdown(
    "<style>"
    "div[class*='st-key-nav_pg_cargar_datos'] button p {position:relative;}"
    "div[class*='st-key-nav_pg_cargar_datos'] button::after {"
    f"content:'';position:absolute;top:9px;right:12px;width:7px;height:7px;"
    f"border-radius:999px;background:{_color_punto_datos};}}"
    "</style>",
    unsafe_allow_html=True,
)

st.sidebar.divider()
anio = st.sidebar.selectbox("Año (régimen legal)", [2025, 2026, 2027, 2028, 2029, 2030], index=2)

st.sidebar.divider()
# Solo admin/super_admin: "Modo avanzado" da acceso a páginas internas
# (Configuración de reglas, Guion de demo) y al slider que reduce cuántas
# tiendas calcula Vista Red -- un Manager no necesita ni debería verlas.
if auth_real["rol"] in ("admin", "super_admin"):
    modo_avanzado = st.sidebar.toggle("Modo avanzado", value=False)
else:
    modo_avanzado = False
if modo_avanzado:
    pagina_tecnica = st.sidebar.selectbox(
        "Página interna", ["(ninguna)", "Configuración de reglas", "Guion de demo"]
    )
    if pagina_tecnica != "(ninguna)":
        pagina = pagina_tecnica
    if st.sidebar.button("Recalcular con datos actuales"):
        st.cache_data.clear()
        st.rerun()

if pagina == "Cargar datos":
    st.header("Cargar datos de tu tienda")
    st.write(
        "Sube tus propios archivos para calcular con datos reales. Si no subes nada, "
        "la herramienta usa un ejemplo con datos sintéticos (marca ficticia) para que "
        "puedas explorarla de inmediato."
    )

    ejemplo = cargar_datos_ejemplo()
    # Etiquetas cortas para el botón -- el detalle (frecuencia, agrupación)
    # va en el tooltip (help=), no en el texto del botón. 5 columnas con
    # etiquetas largas ("Tráfico de clientes (por hora)") se envolvían a
    # 2-3 líneas y, en la primera pintada de la página, se veían
    # sobrepuestas con el subheader de arriba mientras Streamlit terminaba
    # de calcular el alto de cada columna.
    etiquetas = {
        "tiendas": "Catálogo de tiendas",
        "trafico": "Tráfico de clientes",
        "ventas": "Ventas históricas",
        "plantilla": "Plantilla actual",
        "ausentismo": "Ausentismo",
    }
    ayuda = {
        "tiendas": "Catálogo de tiendas. Columnas: {cols}",
        "trafico": "Tráfico de clientes, por hora. Columnas: {cols}",
        "ventas": "Ventas históricas, por hora. Columnas: {cols}",
        "plantilla": "Plantilla actual de empleados. Columnas: {cols}",
        "ausentismo": "Ausentismo, por empleado y día. Columnas: {cols}",
    }

    st.subheader("1. Descarga la plantilla (formato esperado)")
    # 3 columnas (no 5): con etiquetas cortas ya no se envuelven, y con
    # menos columnas cada botón tiene más aire -- se ve bien tanto en
    # pantalla completa como en laptop chica.
    cols_plantillas = st.columns(3)
    for i, nombre in enumerate(ARCHIVOS_DATASET):
        col = cols_plantillas[i % 3]
        col.download_button(
            etiquetas[nombre],
            icon=":material/download:",
            data=ejemplo[nombre].to_csv(index=False).encode("utf-8"),
            file_name=f"{nombre}_ejemplo.csv",
            mime="text/csv",
            help=ayuda[nombre].format(cols=", ".join(ejemplo[nombre].columns)),
            width='stretch',
        )

    st.subheader("2. Sube tus archivos (CSV, mismo formato que la plantilla)")
    subidos_ahora: dict[str, pd.DataFrame] = {}
    cols_uploaders = st.columns(len(ARCHIVOS_DATASET))
    for col, nombre in zip(cols_uploaders, ARCHIVOS_DATASET):
        archivo = col.file_uploader(etiquetas[nombre], type=["csv"], key=f"upload_{nombre}")
        if archivo is not None:
            try:
                df = pd.read_csv(archivo, parse_dates=["fecha"] if nombre in COLUMNAS_CON_FECHA else None)
                subidos_ahora[nombre] = df
                col.success(f"{len(df)} filas cargadas")
            except Exception as e:
                col.error(f"No se pudo leer: {e}")

    c1, c2 = st.columns(2)
    if c1.button("Usar estos archivos", type="primary", disabled=not subidos_ahora):
        st.session_state.setdefault("datos_subidos", {}).update(subidos_ahora)
        st.cache_data.clear()
        st.success("Listo. La herramienta ya está usando tus datos.")
        st.rerun()
    if usando_datos_propios and c2.button("Volver a datos de ejemplo"):
        st.session_state["datos_subidos"] = {}
        st.cache_data.clear()
        st.rerun()

    if usando_datos_propios:
        st.info("Archivos propios en uso: " + ", ".join(
            etiquetas[n] for n in st.session_state["datos_subidos"]
        ))
    else:
        st.info("Usando datos de ejemplo (marca ficticia, 100% sintéticos).")

elif pagina == "Vista Red":
    if auth["rol"] == "admin":
        _alcance = f"zona {usuarios.ZONAS[auth['zona_id']]['nombre']} ({len(tiendas_visibles_df)} tiendas)"
    else:
        _alcance = f"las {len(tiendas_visibles_df)} tiendas"
    st.header(f"Vista Red — consolidado de {_alcance}")
    n_tiendas = len(tiendas_visibles_df)
    if modo_avanzado:
        n_tiendas = st.slider("Tiendas a calcular (modo avanzado: reduce para pruebas rápidas)",
                               1, len(tiendas_visibles_df), min(5, len(tiendas_visibles_df)))
    st.caption(
        "Cada tienda resuelve un problema de optimización de ~10s; calcular la red completa puede "
        "tardar varios minutos. La barra de abajo muestra qué tienda se está calculando. Si navegas "
        "a otra página a la mitad, la barra desaparece, pero las tiendas que ya terminaron quedan en "
        "caché -- al volver y calcular de nuevo, esas no se vuelven a resolver, solo las que faltaban."
    )
    if st.button("Calcular ahorro de la red", type="primary"):
        ids = list(tiendas_visibles_df["tienda_id"].head(n_tiendas))
        resultados = calcular_red(ids, anio, TIEMPO_LIMITE_SEG_DEFAULT, datos)
        consolidado = vista_red.consolidar_resultados(resultados, tiendas_visibles_df)
        st.session_state["consolidado"] = consolidado
        st.session_state["resultados_red"] = resultados
        # Fuerza un rerun limpio al terminar -- el cálculo puede tardar
        # varios minutos en un solo script run; sin este rerun explícito,
        # cualquier clic en la barra lateral hecho mientras corría queda
        # en un estado raro y la navegación puede sentirse "congelada"
        # hasta recargar la página.
        st.rerun()

    if "consolidado" in st.session_state:
        consolidado = st.session_state["consolidado"]
        # Labels cortos + help= para el detalle -- en anchos intermedios
        # (~900-1000px, laptop chica o ventana no maximizada) un label largo
        # como "Ahorro total (MXN/semana)" se truncaba sin forma de ver el
        # resto ("Ahorro total (MXN/se…").
        c1, c2, c3 = st.columns(3)
        c1.metric("Ahorro total", f"${consolidado['ahorro_total_red_mxn']:,.0f}",
                  help="MXN por semana, suma de todas las tiendas calculadas")
        c2.metric("Ahorro %", f"{consolidado['ahorro_pct_red']:.1%}")
        c3.metric("Bajo el mínimo (8%)", len(consolidado["tiendas_bajo_minimo_8pct"]),
                  help="Tiendas que no llegan al 8% mínimo de ahorro exigido")

        st.text(vista_red.resumen_para_demo(consolidado))

        ranking = consolidado["ranking_tiendas"]
        f1, f2 = st.columns(2)
        cluster_sel = f1.selectbox("Filtrar por clúster", ["(todos)"] + sorted(ranking["cluster_id"].dropna().unique().tolist()))
        formato_sel = f2.selectbox("Filtrar por formato", ["(todos)"] + sorted(ranking["formato"].dropna().unique().tolist()))
        filtrado = vista_red.filtrar_por(
            ranking,
            cluster_id=None if cluster_sel == "(todos)" else cluster_sel,
            formato=None if formato_sel == "(todos)" else formato_sel,
        )
        # El status crudo del solver (CP-SAT/OR-Tools) viene en inglés
        # ("FEASIBLE", "OPTIMAL"...); se traduce solo para mostrar/exportar,
        # sin tocar vista_red.py -- el resto de la app está en español.
        if "status_solver" in filtrado.columns:
            _status_es = {
                "OPTIMAL": "Óptimo", "FEASIBLE": "Factible",
                "INFEASIBLE": "Infactible", "MODEL_INVALID": "Modelo inválido",
                "UNKNOWN": "Desconocido",
            }
            filtrado = filtrado.copy()
            filtrado["status_solver"] = filtrado["status_solver"].map(
                lambda s: _status_es.get(s, s)
            )
        st.bar_chart(filtrado.set_index("tienda_id")["ahorro_pct"])
        st.dataframe(
            filtrado, width='stretch', hide_index=True,
            column_config={
                "tienda_id": "Tienda", "cluster_id": "Clúster", "formato": "Formato",
                "ahorro_mxn": st.column_config.NumberColumn("Ahorro (MXN/semana)", format="$%.0f"),
                "ahorro_pct": st.column_config.NumberColumn("Ahorro %", format="percent"),
                "pct_del_techo_capturado": st.column_config.NumberColumn("% del techo capturado", format="percent"),
                "status_solver": "Status del solver",
                "cumple_minimo_8pct": "¿Cumple mínimo 8%?",
            },
        )

        st.download_button(
            "Descargar ranking de tiendas (CSV)",
            icon=":material/download:",
            data=filtrado.to_csv(index=False).encode("utf-8"),
            file_name="ranking_ahorro_tiendas.csv",
            mime="text/csv",
        )

elif pagina == "Vista Tienda":
    st.header("Vista Tienda")
    if auth["rol"] == "manager":
        tienda_id = auth["tienda_id"]
        st.caption(f"Tienda: {tienda_id} (tu tienda)")
    else:
        tienda_id = st.selectbox("Tienda", tiendas_visibles_df["tienda_id"])
    if st.button("Calcular esta tienda") or tienda_id in st.session_state.get("cache_tiendas", {}):
        reporte = calcular_resultado_tienda(
            tienda_id, anio, TIEMPO_LIMITE_SEG_DEFAULT,
            datos["tiendas"], datos["trafico"], datos["ventas"], datos["plantilla"], datos["ausentismo"],
        )
        st.session_state.setdefault("cache_tiendas", {})[tienda_id] = reporte

    reporte = st.session_state.get("cache_tiendas", {}).get(tienda_id)
    if reporte:
        st.subheader(reporte["resumen_ejecutivo"])
        c1, c2, c3 = st.columns(3)
        c1.metric("Costo base (MXN)", f"${reporte['ahorro_semanal']['costo_base_mxn']:,.0f}")
        c2.metric("Costo propuesta (MXN)", f"${reporte['ahorro_semanal']['costo_propuesta_mxn']:,.0f}")
        c3.metric("Ahorro", f"{reporte['ahorro_semanal']['ahorro_pct']:.1%}")

        brecha = reporte["brecha_vs_techo"]
        st.write("**Qué tan cerca está del máximo teórico posible**")
        bc1, bc2 = st.columns(2)
        bc1.metric("% del techo capturado", f"{brecha.get('pct_del_techo_capturado', 0):.1%}")
        bc2.metric("Brecha vs. techo (MXN/semana)", f"${brecha.get('brecha_mxn', 0):,.0f}")

        # La tabla hora-por-hora (fecha/hora/trabajando/en_pausa x cada
        # empleado) es un nivel de detalle de depuración, no lo que un
        # gerente consulta a diario -- Calendario ya resuelve mejor el "quién
        # trabaja hoy" con los chips por turno. Se deja detrás de Modo
        # avanzado, igual que la tabla de trazabilidad de abajo; el botón de
        # descarga sigue disponible siempre por si alguien necesita el CSV
        # completo.
        if modo_avanzado:
            st.write("**Horario propuesto (primeras filas, detalle técnico)**")
            _horario_vista = reporte["propuesta"]["horario_df"].head(50).copy()
            _plantilla_vista = datos["plantilla"].loc[datos["plantilla"]["tienda_id"] == tienda_id]
            if "nombre" in _plantilla_vista.columns and "empleado_id" in _horario_vista.columns:
                _horario_vista.insert(
                    1, "nombre",
                    _horario_vista["empleado_id"].map(dict(zip(_plantilla_vista["empleado_id"], _plantilla_vista["nombre"]))),
                )
            st.dataframe(
                _horario_vista, width='stretch', hide_index=True,
                column_config={
                    "empleado_id": "ID", "nombre": "Nombre", "fecha": "Fecha", "hora": "Hora",
                    "trabajando": "Trabajando", "en_pausa": "En pausa",
                },
            )
        else:
            st.caption("Para ver quién trabaja cada día, usa Calendario. Aquí puedes descargar el "
                       "horario completo o activar Modo avanzado para el detalle hora por hora.")

        dl1, dl2 = st.columns(2)
        dl1.download_button(
            "Descargar horario completo (CSV)",
            icon=":material/download:",
            data=reporte["propuesta"]["horario_df"].to_csv(index=False).encode("utf-8"),
            file_name=f"horario_{tienda_id}.csv", mime="text/csv",
        )
        resumen_cfo = (
            f"Tienda: {tienda_id}\n{reporte['resumen_ejecutivo']}\n\n"
            f"Costo base (MXN/semana): {reporte['ahorro_semanal']['costo_base_mxn']:,.0f}\n"
            f"Costo propuesta (MXN/semana): {reporte['ahorro_semanal']['costo_propuesta_mxn']:,.0f}\n"
            f"Ahorro: {reporte['ahorro_semanal']['ahorro_pct']:.1%}\n"
            f"% del techo capturado: {brecha.get('pct_del_techo_capturado', 0):.1%}\n"
        )
        dl2.download_button(
            "Descargar reporte CFO (TXT)",
            icon=":material/download:",
            data=resumen_cfo.encode("utf-8"),
            file_name=f"reporte_cfo_{tienda_id}.txt", mime="text/plain",
        )

        if modo_avanzado:
            st.write("**Tabla de trazabilidad de reglas (detalle técnico)**")
            st.dataframe(reporte["tabla_trazabilidad"], width='stretch')

elif pagina == "Calendario":
    # Mes -> semana -> día, con edición ligera de turnos (chips) en el día.
    # Regla de producto (ver docstring de jornada40/calendario.py): el mes es
    # navegación visual gratis (solo fechas); los datos reales (costo,
    # ahorro, horario) solo se calculan para la semana que el gerente abre.
    st.header("Calendario")
    if auth["rol"] == "manager":
        tienda_id = auth["tienda_id"]
        st.caption(f"Tienda: {tienda_id} (tu tienda)")
    else:
        tienda_id = st.selectbox("Tienda", tiendas_visibles_df["tienda_id"], key="cal_tienda_sel")

    FECHA_MIN_CAL, FECHA_MAX_CAL = FECHA_INICIO_DEFAULT, FECHA_FIN_DATASET_EJEMPLO
    st.session_state.setdefault("cal_anio", FECHA_MIN_CAL.year)
    st.session_state.setdefault("cal_mes", FECHA_MIN_CAL.month)
    st.session_state.setdefault("cal_vista", "mes")
    st.session_state.setdefault("cache_calendario", {})
    st.markdown(_CSS_CALENDARIO, unsafe_allow_html=True)

    cal_anio, cal_mes = st.session_state["cal_anio"], st.session_state["cal_mes"]
    semanas_calculadas = {clave for clave in st.session_state["cache_calendario"] if clave[0] == tienda_id}

    # Selector Mes/Semana/Día -- estilo Google Calendar: siempre visible, no
    # solo llegable "drilling down". La key incluye el valor actual de
    # cal_vista a propósito: así cuando OTRO control (clic en un día, botón
    # "Ver día") cambia cal_vista y hace un rerun, este widget siempre nace
    # con el `default` correcto en vez de arrastrar un estado de clic viejo.
    _VISTA_LABEL = {"mes": "Mes", "semana": "Semana", "dia": "Día"}
    _VISTA_DESDE_LABEL = {v: k for k, v in _VISTA_LABEL.items()}
    vista_click = st.segmented_control(
        "Vista", list(_VISTA_LABEL.values()), default=_VISTA_LABEL[st.session_state["cal_vista"]],
        key=f"cal_vista_seg_{st.session_state['cal_vista']}", label_visibility="collapsed",
    )
    if vista_click is not None and _VISTA_DESDE_LABEL[vista_click] != st.session_state["cal_vista"]:
        nueva_vista = _VISTA_DESDE_LABEL[vista_click]
        if "cal_semana_sel" not in st.session_state:
            dias_del_mes = [f for fila in calendario.matriz_mes(cal_anio, cal_mes) for f in fila if f]
            candidata = next(
                (f for f in dias_del_mes
                 if calendario.semana_dentro_de_rango(calendario.semana_de(f)[0], FECHA_MIN_CAL, FECHA_MAX_CAL)),
                None,
            )
            st.session_state["cal_semana_sel"] = calendario.semana_de(candidata)[0] if candidata else FECHA_MIN_CAL
        st.session_state.setdefault("cal_dia_sel", st.session_state["cal_semana_sel"])
        st.session_state["cal_vista"] = nueva_vista
        st.rerun()

    if st.session_state["cal_vista"] == "mes":
        nav1, nav2, nav3 = st.columns([1, 4, 1])
        if nav1.button("◀", key="cal_mes_prev"):
            st.session_state["cal_anio"], st.session_state["cal_mes"] = calendario.mes_anterior(cal_anio, cal_mes)
            st.rerun()
        nav2.markdown(f"<h4 style='text-align:center;font-weight:600;color:#1d1d1f'>"
                       f"{calendario.NOMBRES_MES[cal_mes]} {cal_anio}</h4>", unsafe_allow_html=True)
        if nav3.button("▶", key="cal_mes_next"):
            st.session_state["cal_anio"], st.session_state["cal_mes"] = calendario.mes_siguiente(cal_anio, cal_mes)
            st.rerun()

        encabezados = st.columns(7)
        for col, nombre in zip(encabezados, calendario.DIAS_SEMANA_ABREV):
            col.markdown(f"<div class='cal-encabezado-dia'>{nombre}</div>", unsafe_allow_html=True)

        for fila in calendario.matriz_mes(cal_anio, cal_mes):
            cols = st.columns(7)
            for col, fecha in zip(cols, fila):
                if fecha is None:
                    col.markdown("<div class='cal-celda-vacia'></div>", unsafe_allow_html=True)
                    continue
                resumen = calendario.resumen_dia(fecha, tienda_id, FECHA_MIN_CAL, FECHA_MAX_CAL, semanas_calculadas)
                if not resumen["dentro_de_rango"]:
                    col.button(str(fecha.day), key=f"cal_dia_{fecha.isoformat()}_fuera", disabled=True)
                    continue
                _sufijo_estado = "_est-c" if resumen["calculado"] else "_est-p"
                if col.button(str(fecha.day), key=f"cal_dia_{fecha.isoformat()}{_sufijo_estado}"):
                    st.session_state["cal_vista"] = "semana"
                    st.session_state["cal_semana_sel"] = resumen["semana_inicio"]
                    st.rerun()
        st.markdown(
            "<p style='font-size:12px;color:#6e6e73;margin-top:14px;'>"
            "<span style='display:inline-block;width:6px;height:6px;border-radius:999px;"
            "background:#34c759;margin-right:4px;'></span>semana con horario ya calculado"
            "&nbsp;&nbsp;·&nbsp;&nbsp;"
            "<span style='display:inline-block;width:6px;height:6px;border-radius:999px;"
            "background:#0071e3;margin-right:4px;'></span>semana sin calcular — clic en un día "
            "para abrir su semana</p>",
            unsafe_allow_html=True,
        )

    elif st.session_state["cal_vista"] == "semana":
        semana_inicio = st.session_state.get("cal_semana_sel", FECHA_MIN_CAL)
        semana_fin = semana_inicio + timedelta(days=6)
        st.markdown(f"<p style='color:#6e6e73;font-size:0.85rem;margin-bottom:0'>"
                    f"{calendario.NOMBRES_MES[cal_mes]} {cal_anio}</p>", unsafe_allow_html=True)
        st.subheader(f"Semana del {semana_inicio.day:02d}-{calendario.NOMBRES_MES[semana_inicio.month][:3]} "
                     f"al {semana_fin.day:02d}-{calendario.NOMBRES_MES[semana_fin.month][:3]}-{semana_fin.year}")

        clave = (tienda_id, semana_inicio)
        if not calendario.semana_dentro_de_rango(semana_inicio, FECHA_MIN_CAL, FECHA_MAX_CAL):
            st.warning("Esta semana queda fuera del año con datos de ejemplo (1-ene a 31-dic de "
                       f"{FECHA_MIN_CAL.year}).")
        elif clave not in st.session_state["cache_calendario"]:
            with st.container(border=True):
                st.write("Esta semana todavía no se ha calculado (el mes es navegación gratis; el "
                         "cálculo real de horario y ahorro se dispara semana por semana).")
                if st.button("Calcular esta semana", type="primary"):
                    with st.spinner("Calculando horario base, propuesta del optimizador y techo teórico..."):
                        reporte = calcular_resultado_tienda(
                            tienda_id, anio, TIEMPO_LIMITE_SEG_DEFAULT,
                            datos["tiendas"], datos["trafico"], datos["ventas"], datos["plantilla"],
                            datos["ausentismo"], fecha_inicio=semana_inicio,
                        )
                        st.session_state["cache_calendario"][clave] = reporte
                    st.rerun()
        else:
            reporte = st.session_state["cache_calendario"][clave]
            st.write(reporte["resumen_ejecutivo"])
            c1, c2, c3 = st.columns(3)
            c1.metric("Costo base (MXN)", f"${reporte['ahorro_semanal']['costo_base_mxn']:,.0f}")
            c2.metric("Costo propuesta (MXN)", f"${reporte['ahorro_semanal']['costo_propuesta_mxn']:,.0f}")
            c3.metric("Ahorro", f"{reporte['ahorro_semanal']['ahorro_pct']:.1%}")

            st.write("**Días de la semana** (clic en un día para ver y ajustar el turno)")
            horario_df = reporte["propuesta"]["horario_df"]
            dia_cols = st.columns(7)
            for i, dcol in enumerate(dia_cols):
                fecha_d = semana_inicio + timedelta(days=i)
                with dcol.container(border=True):
                    st.markdown(
                        f"<div style='text-align:center'>"
                        f"<span style='font-size:0.7rem;font-weight:600;letter-spacing:.04em;"
                        f"text-transform:uppercase;color:#6e6e73'>{calendario.DIAS_SEMANA_ABREV[i]}</span><br>"
                        f"<span style='font-size:1.4rem;font-weight:600;color:#1d1d1f'>{fecha_d.day}</span></div>",
                        unsafe_allow_html=True,
                    )
                    n_personas = 0
                    if not horario_df.empty:
                        horas_dia = horario_df[pd.to_datetime(horario_df["fecha"]).dt.date == fecha_d]
                        n_personas = horas_dia["empleado_id"].nunique()
                    st.markdown(f"<p style='text-align:center;color:#6e6e73;font-size:0.78rem;margin:0.2rem 0'>"
                                f"{n_personas} personas</p>", unsafe_allow_html=True)
                    if st.button("Ver día", key=f"cal_verdia_{fecha_d.isoformat()}", width='stretch'):
                        st.session_state["cal_vista"] = "dia"
                        st.session_state["cal_dia_sel"] = fecha_d
                        st.rerun()

    else:  # vista == "dia"
        semana_inicio = st.session_state.get("cal_semana_sel", FECHA_MIN_CAL)
        fecha_d = st.session_state.get("cal_dia_sel", semana_inicio)
        nombre_dia = calendario.DIAS_SEMANA_ABREV[(fecha_d.weekday() + 1) % 7]
        _semana_fin_dia = semana_inicio + timedelta(days=6)
        st.markdown(f"<p style='color:#6e6e73;font-size:0.85rem;margin-bottom:0'>"
                    f"Semana del {semana_inicio.day:02d}-{calendario.NOMBRES_MES[semana_inicio.month][:3]} "
                    f"al {_semana_fin_dia.day:02d}-{calendario.NOMBRES_MES[_semana_fin_dia.month][:3]}-{_semana_fin_dia.year}</p>",
                    unsafe_allow_html=True)
        st.subheader(f"{nombre_dia} {fecha_d.day:02d} de {calendario.NOMBRES_MES[fecha_d.month]}, {fecha_d.year}")

        clave = (tienda_id, semana_inicio)
        reporte = st.session_state.get("cache_calendario", {}).get(clave)
        if reporte is None:
            st.warning("Primero calcula la semana completa (cambia a la vista Semana y usa el botón "
                       "\"Calcular esta semana\").")
        else:
            horario_df = reporte["propuesta"]["horario_df"]
            plantilla_t = datos["plantilla"].loc[datos["plantilla"]["tienda_id"] == tienda_id]
            horario_dia = (horario_df[pd.to_datetime(horario_df["fecha"]).dt.date == fecha_d]
                            if not horario_df.empty else horario_df)

            # "Chips" = un turno por empleado ese día (bloque hora_inicio-hora_fin
            # a partir de las horas trabajadas). Edición permitida: SOLO
            # renombrar (reasignar a otro empleado de la plantilla) o
            # intercambiar dos chips -- el CP-SAT ya encontró el óptimo legal,
            # así que cualquier edición manual solo puede alejarse de él; por
            # eso se califica con costos_ahorro.calificar_edicion_manual en
            # vez de resolverse como un problema nuevo.
            #
            # Arrastrar y soltar real (streamlit-sortables, componente de
            # terceros -- Streamlit no lo trae nativo): cada turno del día es
            # su propio contenedor de 1 casilla ("Turno N · HH:MM–HH:MM"),
            # más un contenedor "Plantilla" con el resto de la tienda.
            # Arrastrar un nombre a un turno lo reasigna; el nombre que salga
            # de ese turno cae de vuelta en Plantilla. El resultado se
            # compara contra la asignación original del optimizador para
            # armar el mismo dict `edicion_dia` de siempre (sin tocar la
            # lógica de calificación de abajo).
            if horario_dia.empty:
                st.info("Nadie tiene turno asignado este día en la propuesta.")
            else:
                chips = (horario_dia.groupby("empleado_id")["hora"]
                         .agg(hora_inicio="min", hora_fin="max").reset_index())
                chips["hora_fin"] = chips["hora_fin"] + 1  # la última hora trabajada cubre hasta el fin de esa hora
                chips = chips.sort_values("hora_inicio").reset_index(drop=True)

                # Nombre por empleado_id, con fallback al propio ID -- si el
                # gerente subió su propia plantilla (página "Cargar datos")
                # puede no traer columna "nombre", y la UI no debe romperse
                # por eso.
                if "nombre" in plantilla_t.columns:
                    _nombre_por_id = dict(zip(plantilla_t["empleado_id"], plantilla_t["nombre"]))
                else:
                    _nombre_por_id = {}

                def _nombre(eid: str) -> str:
                    return _nombre_por_id.get(eid, eid)

                # El widget de arrastre (streamlit-sortables) solo puede
                # mostrar el texto que le pasamos como "item" -- no soporta
                # tooltips nativos por elemento. En vez de un hover que no
                # se puede implementar aquí, el chip muestra el nombre Y el
                # ID directamente (dos líneas), y usamos esa misma etiqueta
                # como identidad del chip en el widget: sigue siendo única
                # (el ID nunca se repite) así que toda la lógica de abajo
                # (quién quedó en qué turno) funciona igual, solo que ahora
                # sobre etiquetas "Nombre\nID" en vez de IDs a secas.
                def _etiqueta(eid: str) -> str:
                    return f"{_nombre(eid)}\n{eid}"

                def _id_desde_etiqueta(etiqueta: str) -> str:
                    return etiqueta.rsplit("\n", 1)[-1]

                st.write(f"**{len(chips)} turnos** — arrastra un nombre desde *Plantilla* hacia un turno para reasignarlo. "
                         f"Si el turno ya tenía a alguien, puede quedar visualmente junto al nuevo nombre; "
                         f"el sistema toma al que acabas de soltar como el asignado.")
                empleados_tienda = sorted(plantilla_t["empleado_id"].unique().tolist())
                clave_edicion = (tienda_id, fecha_d)

                # Buscador: con 40+ turnos, encontrar a alguien a puro scroll
                # es lento y aumenta el riesgo de soltar un chip en el turno
                # equivocado (el auto-scroll del navegador cerca del borde
                # de pantalla puede mover el drop). Es solo informativo --
                # no toca los datos del widget de arrastre, así que nunca
                # puede perder un cambio a medio hacer.
                busqueda = st.text_input(
                    "Buscar empleado (nombre o ID) para saber en qué turno está",
                    key=f"cal_busq_{tienda_id}_{fecha_d.isoformat()}",
                    placeholder="ej. Roberto o E00003",
                )
                if busqueda.strip():
                    _q = busqueda.strip().lower()
                    _turno_por_empleado = {
                        row["empleado_id"]: f"Turno {i + 1} · {int(row['hora_inicio'])}:00–{int(row['hora_fin'])}:00"
                        for i, row in chips.iterrows()
                    }
                    _coincidencias = [
                        e for e in empleados_tienda
                        if _q in _nombre(e).lower() or _q in e.lower()
                    ]
                    if not _coincidencias:
                        st.caption("Sin coincidencias.")
                    else:
                        for e in _coincidencias:
                            _donde = _turno_por_empleado.get(e, "Plantilla (sin turno hoy)")
                            st.caption(f"**{_nombre(e)}** ({e}) → {_donde}")

                # Reserva un lugar AQUÍ (antes de los 40+ chips) para el
                # aviso de "Cambios pendientes" -- Streamlit renderiza el
                # contenido que se escriba más abajo en este placeholder
                # dentro de esta posición del layout, no donde se escribe en
                # el código. Antes quedaba hasta el fondo de la página,
                # después de toda la Plantilla, muy lejos de donde ocurrió
                # el cambio.
                aviso_cambios = st.empty()

                slots_originales: dict[str, str] = {}  # slot_id -> etiqueta original
                contenedores: list[dict[str, object]] = []
                for i, chip in chips.iterrows():
                    slot_id = f"Turno {i + 1} · {int(chip['hora_inicio'])}:00–{int(chip['hora_fin'])}:00"
                    etiqueta = _etiqueta(chip["empleado_id"])
                    contenedores.append({"header": slot_id, "items": [etiqueta]})
                    slots_originales[slot_id] = etiqueta

                asignados_hoy = set(chips["empleado_id"])
                contenedores.append({
                    "header": "Plantilla (sin turno hoy)",
                    "items": [_etiqueta(e) for e in empleados_tienda if e not in asignados_hoy],
                })

                resultado_drag = sort_items(
                    contenedores, multi_containers=True, direction="horizontal",
                    key=f"cal_dnd_{tienda_id}_{fecha_d.isoformat()}",
                    custom_style="""
                    .sortable-component{gap:10px;flex-wrap:wrap}
                    .sortable-container{background:#ffffff;border:1px solid #d2d2d7;
                        border-radius:10px;min-width:160px;padding:6px;}
                    .sortable-container-header{font-size:0.7rem;font-weight:600;
                        color:#6e6e73;padding:4px 6px;}
                    .sortable-item{background:#f5f5f7;border:1px solid #ececec;
                        border-radius:12px;padding:6px 12px;font-size:0.82rem;
                        font-weight:600;color:#1d1d1f;margin:3px;cursor:grab;
                        white-space:pre-line;line-height:1.3;text-align:center;}
                    """,
                )

                edicion_dia_etiquetas: dict[str, str] = {}
                if resultado_drag:
                    ocupantes_por_slot = {
                        contenedor["header"]: contenedor["items"] for contenedor in resultado_drag
                    }
                    for slot_id, etq_original in slots_originales.items():
                        ocupante = ocupantes_por_slot.get(slot_id, [])
                        # Si sueltas a alguien en un turno que ya tenía ocupante,
                        # ambos quedan momentáneamente en la misma casilla (el
                        # componente no expulsa al anterior). Gana quien llegó
                        # nuevo: tomamos al primero de la lista que NO sea el
                        # empleado original de ese turno.
                        candidatos_nuevos = [e for e in ocupante if e != etq_original]
                        nuevo_etq = candidatos_nuevos[0] if candidatos_nuevos else None
                        if nuevo_etq and nuevo_etq != etq_original:
                            edicion_dia_etiquetas[etq_original] = nuevo_etq
                # De vuelta a empleado_id puros -- todo lo que sigue (armar
                # editado_df, calificar_edicion_manual) espera IDs, no las
                # etiquetas "Nombre\nID" que solo existen para el widget.
                edicion_dia: dict[str, str] = {
                    _id_desde_etiqueta(orig): _id_desde_etiqueta(nuevo)
                    for orig, nuevo in edicion_dia_etiquetas.items()
                }
                st.session_state.setdefault("cal_ediciones", {})
                st.session_state["cal_ediciones"][clave_edicion] = edicion_dia

                # Todo el aviso de cambios pendientes + calificación vive
                # dentro del placeholder reservado ARRIBA (aviso_cambios),
                # así que aunque este código corre después de dibujar los
                # 40+ chips, Streamlit lo muestra justo debajo del buscador,
                # no hasta el fondo de la página.
                with aviso_cambios.container():
                    if edicion_dia:
                        # Confirmación textual e inequívoca de qué cambió --
                        # el widget de arrastre en sí puede mostrar
                        # momentáneamente dos nombres en la misma casilla
                        # (ver comentario arriba), así que esta lista es la
                        # fuente de verdad sin ambigüedad visual sobre quién
                        # quedó asignado.
                        _slot_por_original_id = {
                            _id_desde_etiqueta(v): k for k, v in slots_originales.items()
                        }
                        _filas_html = "".join(
                            f"<div style='font-size:13px;color:#1d1d1f;padding:3px 0;'>"
                            f"<span style='color:#6e6e73'>{_slot_por_original_id.get(_orig, '?')}:</span>&nbsp; "
                            f"<s style='color:#6e6e73'>{_nombre(_orig)} ({_orig})</s> → "
                            f"<b>{_nombre(_nuevo)} ({_nuevo})</b></div>"
                            for _orig, _nuevo in edicion_dia.items()
                        )
                        st.markdown(
                            "<div style='border:1px solid #d2d2d7;border-radius:10px;"
                            "padding:10px 14px;background:#f9fafb;margin-bottom:10px;'>"
                            "<div style='font-size:12.5px;font-weight:600;color:#1d1d1f;"
                            "margin-bottom:4px;'>Cambios pendientes (aún sin calificar)</div>"
                            f"{_filas_html}</div>",
                            unsafe_allow_html=True,
                        )
                        st.write(f"**{len(edicion_dia)} turno(s) reasignado(s) sin calificar todavía.**")
                        if st.button("Calificar cambios", type="primary"):
                            editado_df = horario_df.copy()
                            mascara_dia = pd.to_datetime(editado_df["fecha"]).dt.date == fecha_d
                            for original, nuevo_emp in edicion_dia.items():
                                editado_df.loc[mascara_dia & (editado_df["empleado_id"] == original),
                                                "empleado_id"] = nuevo_emp
                            calif = costos_ahorro.calificar_edicion_manual(
                                horario_df, editado_df, plantilla_t, reporte["demanda"], anio,
                            )
                            st.session_state[f"cal_calif_{clave_edicion}"] = calif

                    calif = st.session_state.get(f"cal_calif_{clave_edicion}")
                    if calif:
                        color = {"No recomendado": "error", "Costoso": "error", "Caro": "warning",
                                 "Aceptable": "warning", "Neutral": "success"}.get(calif["calificacion"], "info")
                        getattr(st, color)(f"**{calif['calificacion']}** — {calif['mensaje']}")
                        cc1, cc2 = st.columns(2)
                        cc1.metric("Delta costo (MXN/semana)", f"${calif['delta_costo_mxn']:,.0f}")
                        cc2.metric("Horas pico sin cubrir (nuevas)", calif["delta_horas_deficit_pico"])
                        if calif["cambios_por_empleado"]:
                            _tabla_cambios = pd.DataFrame(calif["cambios_por_empleado"])
                            if "empleado_id" in _tabla_cambios.columns:
                                _tabla_cambios.insert(
                                    1, "nombre", _tabla_cambios["empleado_id"].map(_nombre),
                                )
                            st.dataframe(
                                _tabla_cambios, width='stretch', hide_index=True,
                                column_config={
                                    "empleado_id": "ID",
                                    "nombre": "Nombre",
                                    "horas_antes": "Horas antes",
                                    "horas_despues": "Horas después",
                                    "entro_a_triple": "¿Entró a triple?",
                                    "delta_costo_mxn": st.column_config.NumberColumn(
                                        "Delta costo (MXN)", format="$%.2f",
                                    ),
                                },
                            )

            st.caption("Vista de edición ligera del PMV: solo reasignación de turnos ya generados por el "
                       "optimizador, calificada contra el óptimo legal — no reemplaza al optimizador.")

elif pagina == "Simulacros":
    st.header("Simulacros")
    if auth["rol"] == "manager":
        tienda_id = auth["tienda_id"]
        st.caption(f"Tienda: {tienda_id} (tu tienda)")
    else:
        tienda_id = st.selectbox("Tienda a simular", tiendas_visibles_df["tienda_id"])

    escenarios_trafico = {
        "Normal": 1.0, "Alta demanda (+15%, ej. Buen Fin)": 1.15,
        "Temporada alta (+30%)": 1.30, "Temporada baja (-20%)": 0.80,
    }
    col1, col2 = st.columns(2)
    escenario_sel = col1.selectbox("Escenario de tráfico", list(escenarios_trafico))
    mult_trafico = escenarios_trafico[escenario_sel]
    delta_plantilla = col2.number_input("Cambio en plantilla (personas, +/-)", -20, 20, 0)

    if modo_avanzado:
        tasa_ausentismo = col1.slider("Tasa de ausentismo", 0.0, 0.30, 0.06, 0.01)
        anio_regimen = col2.selectbox("Año de régimen (simulacro)", [None, 2025, 2026, 2027, 2028, 2029, 2030])
    else:
        tasa_ausentismo = 0.06
        anio_regimen = None

    if st.button("Correr simulacro", type="primary"):
        palancas = simulacros.Palancas(
            multiplicador_trafico=mult_trafico, delta_plantilla=int(delta_plantilla),
            tasa_ausentismo=tasa_ausentismo, anio_regimen=anio_regimen,
        )
        datos_originales = {
            "tiendas_df": datos["tiendas"], "trafico_df": datos["trafico"], "ventas_df": datos["ventas"],
            "plantilla_df": datos["plantilla"], "ausentismo_df": datos["ausentismo"],
        }
        with st.spinner("Corriendo simulacro..."):
            resultado = simulacros.correr_simulacro(
                tienda_id, palancas, datos_originales, anio,
                fecha_inicio=FECHA_INICIO_DEFAULT, tiempo_limite_seg=TIEMPO_LIMITE_SEG_DEFAULT,
            )
        # Interpretación cualitativa del resultado -- antes solo se veían
        # los dos números pelones y un gerente no sabía si +$7,334/semana
        # era bueno o malo para ese escenario. Es una heurística simple y
        # propia de esta pantalla (no reutiliza los umbrales de
        # costos_ahorro.calificar_edicion_manual, que compara contra el
        # óptimo del día, no contra un escenario hipotético de la semana).
        _delta_costo = resultado["delta_costo_mxn"]
        _delta_he = resultado["delta_horas_extra"]
        if _delta_costo <= 0 and _delta_he <= 0:
            _etiqueta, _color, _msg = ("Favorable", "success",
                                        "El escenario no sube el costo ni las horas extra.")
        elif _delta_costo <= 0 < _delta_he:
            _etiqueta, _color, _msg = ("Mixto", "warning",
                                        "Baja el costo pero sube horas extra -- revisa la carga real del equipo.")
        elif 0 < _delta_costo <= 5000:
            _etiqueta, _color, _msg = ("Manejable", "warning",
                                        "Sube el costo, pero en un rango moderado para una semana.")
        else:
            _etiqueta, _color, _msg = ("Alto impacto", "error",
                                        "Sube el costo de forma importante -- conviene revisar antes de aplicarlo.")
        getattr(st, _color)(f"**{_etiqueta}** — {_msg}")
        c1, c2 = st.columns(2)
        c1.metric("Delta de costo (MXN/semana)", f"${resultado['delta_costo_mxn']:,.0f}")
        c2.metric("Delta de horas extra", f"{resultado['delta_horas_extra']:.0f}")

elif pagina == "Refuerzos entre tiendas":
    st.header("Refuerzos entre tiendas (dentro del mismo clúster)")
    st.info("El traslado de personal entre centros de trabajo requiere acuerdo con la persona "
            "trabajadora. Esta herramienta propone; la decisión y el acuerdo son responsabilidad del cliente.")
    resultados_red = st.session_state.get("resultados_red")
    if not resultados_red:
        st.warning("Calcula primero la Vista Red para tener resultados por tienda.")
    else:
        if auth["rol"] == "manager":
            cluster_sel = tiendas_df.set_index("tienda_id").loc[auth["tienda_id"], "cluster_id"]
            st.caption(f"Clúster: {cluster_sel} (el de tu tienda)")
        else:
            cluster_sel = st.selectbox("Clúster", sorted(tiendas_visibles_df["cluster_id"].unique()))
        ids_cluster = tiendas_visibles_df.loc[tiendas_visibles_df["cluster_id"] == cluster_sel, "tienda_id"]
        propuestas_cluster = {tid: r["propuesta"] for tid, r in resultados_red.items() if tid in ids_cluster.values}
        if len(propuestas_cluster) < 2:
            st.write("Necesitas al menos 2 tiendas calculadas en este clúster.")
        else:
            propuestas = simulacros.simular_refuerzo_entre_tiendas(propuestas_cluster)
            st.dataframe(propuestas, width='stretch')

elif pagina == "Gestión de usuarios":
    st.header("Gestión de usuarios")
    st.caption("Una cuenta de gerente por tienda (el usuario es el propio ID de tienda). Desactívala "
               "si necesitas bloquear el acceso a esa tienda. SADMIN y las 5 cuentas ADMIN (una por "
               "zona) no se listan aquí -- siempre están activas.")
    usuarios_df = st.session_state["usuarios_df"]
    # Un admin regional solo gestiona los gerentes de su propia zona; SADMIN los ve todos.
    tiendas_gestion_df = _tiendas_visibles(auth_real, tiendas_df)
    gerentes_df = usuarios_df[(usuarios_df["rol"] == "manager")
                               & (usuarios_df["tienda_id"].isin(tiendas_gestion_df["tienda_id"]))]
    tienda_filtro = st.selectbox("Filtrar por tienda (opcional)",
                                  ["(todas)"] + list(tiendas_gestion_df["tienda_id"]))
    vista = gerentes_df if tienda_filtro == "(todas)" else gerentes_df[gerentes_df["tienda_id"] == tienda_filtro]

    editado = st.data_editor(
        vista, width='stretch', hide_index=True, disabled=["usuario", "rol", "tienda_id", "zona_id", "etiqueta"],
        column_config={"activo": st.column_config.CheckboxColumn("Activo")},
        key="editor_usuarios",
    )
    if st.button("Guardar cambios de acceso", type="primary"):
        usuarios_df.loc[editado.index, "activo"] = editado["activo"]
        st.session_state["usuarios_df"] = usuarios_df
        _guardar_estado_usuarios(usuarios_df)  # persiste en disco -- ver _usuarios_con_estado
        st.success("Actualizado. Las cuentas desactivadas ya no podrán iniciar sesión (en cualquier sesión).")

    tiendas_sin_acceso = gerentes_df.loc[~gerentes_df["activo"], "tienda_id"].tolist()
    if tiendas_sin_acceso:
        st.error(f"Tiendas sin gerente activo (nadie puede entrar): {', '.join(tiendas_sin_acceso)}")

elif pagina == "Configuración de reglas":
    st.header("Configuración de reglas legales por vigencia")
    st.write(f"Año seleccionado: **{anio}**")
    st.json(reglas.tabla_vigente_para_anio(anio))
    st.write("**Festivos (art. 74 LFT) para este año:**")
    st.write([d.isoformat() for d in reglas.dias_descanso_obligatorio(anio)])
    st.write("**Tabla de trazabilidad legal completa:**")
    tabla = costos_ahorro.armar_tabla_trazabilidad()
    st.dataframe(tabla, width='stretch')
    pendientes = tabla.loc[tabla["estado"] == "pendiente_validacion_legal"]
    if not pendientes.empty:
        st.warning(f"{len(pendientes)} regla(s) pendiente(s) de validación legal:")
        st.dataframe(pendientes, width='stretch')

elif pagina == "Guion de demo":
    st.header("Guion de demo (45 min)")
    guion_path = Path("docs/guion_demo.md")
    if guion_path.exists():
        st.markdown(guion_path.read_text(encoding="utf-8"))
    else:
        st.write("No se encontró docs/guion_demo.md")
