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
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from jornada40 import costos_ahorro, datos_sinteticos, demanda_personal, escenario_base, optimizador, reglas, simulacros, usuarios, vista_red

st.set_page_config(page_title="Alvea PMV — Autoservicio MX", layout="wide")

DATA_DIR = Path("data")
RESULTADOS_DIR = DATA_DIR / "resultados"
ANIO_DEFAULT = 2027
FECHA_INICIO_DEFAULT = reglas.semana_domingo_a_sabado(date(ANIO_DEFAULT, 1, 1))[0]
TIEMPO_LIMITE_SEG_DEFAULT = 10.0


# ---------------------------------------------------------------------------
# Carga y cálculo (cacheados)
# ---------------------------------------------------------------------------

ARCHIVOS_DATASET = ["tiendas", "trafico", "ventas", "plantilla", "ausentismo"]
COLUMNAS_CON_FECHA = {"trafico", "ventas", "ausentismo"}


@st.cache_data(show_spinner="Generando dataset de ejemplo (primera vez)...")
def cargar_datos_ejemplo() -> dict[str, pd.DataFrame]:
    """Dataset sintético (marca ficticia) que se usa mientras no se sube nada propio."""
    if all((DATA_DIR / f"{n}.csv").exists() for n in ARCHIVOS_DATASET):
        return {n: pd.read_csv(DATA_DIR / f"{n}.csv", parse_dates=["fecha"] if n in
                                COLUMNAS_CON_FECHA else None)
                for n in ARCHIVOS_DATASET}
    return datos_sinteticos.generar_dataset_completo(
        FECHA_INICIO_DEFAULT, FECHA_INICIO_DEFAULT + pd.Timedelta(days=6), seed=42, out_dir=DATA_DIR,
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
) -> dict:
    """Calcula base + propuesta + techo + reporte CFO de UNA tienda.

    Los DataFrames llevan "_" al inicio del nombre para que Streamlit no
    intente hashear su contenido (son estáticos por sesión); el cache se
    invalida por (tienda_id, anio, tiempo_limite_seg). Usa "Recalcular
    todo" en la barra lateral si cambiaste los datos de origen.
    """
    tiendas_t = _normalizar_fechas(_tiendas.loc[_tiendas["tienda_id"] == tienda_id])
    trafico_t = _normalizar_fechas(_trafico.loc[_trafico["tienda_id"] == tienda_id])
    ventas_t = _normalizar_fechas(_ventas.loc[_ventas["tienda_id"] == tienda_id])
    plantilla_t = _plantilla.loc[_plantilla["tienda_id"] == tienda_id]
    empleados_t = set(plantilla_t["empleado_id"])
    ausentismo_t = _normalizar_fechas(_ausentismo.loc[_ausentismo["empleado_id"].isin(empleados_t)])

    demanda = demanda_personal.calcular_demanda_tienda(tienda_id, trafico_t, ventas_t, tiendas_t)
    demanda = demanda_personal.marcar_franjas_pico(demanda)

    base = escenario_base.calcular_horario_base_tienda(
        tienda_id, anio, plantilla_t, ausentismo_t, demanda, fecha_inicio=FECHA_INICIO_DEFAULT,
    )
    propuesta = optimizador.resolver_tienda(
        tienda_id, anio, plantilla_t, demanda, ausentismo_t,
        tiempo_limite_seg=tiempo_limite_seg, fecha_inicio=FECHA_INICIO_DEFAULT,
    )
    techo = optimizador.resolver_techo_teorico(
        tienda_id, anio, plantilla_t, demanda, ausentismo_t,
        tiempo_limite_seg=tiempo_limite_seg, fecha_inicio=FECHA_INICIO_DEFAULT,
    )
    reporte = costos_ahorro.generar_reporte_cfo(tienda_id, base, propuesta, techo, anio)
    reporte["status"] = propuesta["status"]
    reporte["propuesta"] = propuesta
    reporte["base"] = base
    reporte["techo"] = techo
    reporte["demanda"] = demanda
    return reporte


def calcular_red(tiendas_ids: list[str], anio: int, tiempo_limite_seg: float, datos: dict) -> dict[str, dict]:
    resultados = {}
    barra = st.progress(0.0, text="Calculando tiendas...")
    for i, tid in enumerate(tiendas_ids):
        resultados[tid] = calcular_resultado_tienda(
            tid, anio, tiempo_limite_seg,
            datos["tiendas"], datos["trafico"], datos["ventas"], datos["plantilla"], datos["ausentismo"],
        )
        barra.progress((i + 1) / len(tiendas_ids), text=f"Calculando tiendas... {tid} ({i+1}/{len(tiendas_ids)})")
    barra.empty()
    return resultados


# ---------------------------------------------------------------------------
# Autenticacion (sencilla, PMV -- ver jornada40/usuarios.py) + Interfaz
# ---------------------------------------------------------------------------

datos = cargar_datos()
tiendas_df = datos["tiendas"]


@st.cache_data(show_spinner=False)
def _cargar_usuarios(_tiendas: pd.DataFrame) -> pd.DataFrame:
    return usuarios.generar_usuarios(_tiendas, seed=42)


_CSS_LOGIN = """
<style>
div[data-testid="stForm"] {
    border: 1px solid rgba(140, 140, 140, 0.35);
    border-radius: 6px;
    padding: 2rem 2rem 1.25rem 2rem;
}
</style>
"""

def _pantalla_login() -> None:
    st.markdown(_CSS_LOGIN, unsafe_allow_html=True)
    _, col_mid, _ = st.columns([1, 1.2, 1])
    with col_mid:
        st.markdown("### Alvea PMV")
        with st.form("form_login", border=False):
            usuario_txt = st.text_input("Usuario", placeholder="Usuario (ej. SADMIN, ADMIN-Z1, T001)",
                                         label_visibility="collapsed")
            password = st.text_input("Contraseña", type="password", placeholder="Contraseña",
                                      label_visibility="collapsed")
            enviado = st.form_submit_button("Entrar", type="primary", width='stretch')

            if enviado:
                usuarios_df = st.session_state.get("usuarios_df", _cargar_usuarios(tiendas_df))
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
st.session_state.setdefault("usuarios_df", _cargar_usuarios(tiendas_df))

def _tiendas_visibles(auth_: dict, tiendas: pd.DataFrame) -> pd.DataFrame:
    """Subconjunto de tiendas que puede ver/operar este perfil: su tienda
    (manager), su zona (admin regional), o todas (super admin)."""
    if auth_["rol"] == "manager":
        return tiendas[tiendas["tienda_id"] == auth_["tienda_id"]]
    if auth_["rol"] == "admin":
        return usuarios.tiendas_de_zona(auth_["zona_id"], tiendas)
    return tiendas


st.sidebar.title("Alvea PMV — Autoservicio MX")
if auth_real["rol"] == "super_admin":
    _etiqueta_ambito = "Super Admin"
elif auth_real["rol"] == "admin":
    _etiqueta_ambito = f"Admin · zona {usuarios.ZONAS[auth_real['zona_id']]['nombre']}"
else:
    _etiqueta_ambito = auth_real["tienda_id"]
st.sidebar.caption(f"👤 {auth_real['nombre']} · {_etiqueta_ambito}")
if st.sidebar.button("Cerrar sesión"):
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
    paginas_negocio = ["Cargar datos", "Vista Tienda", "Simulacros", "Refuerzos entre tiendas"]
else:
    paginas_negocio = ["Cargar datos", "Vista Red", "Vista Tienda", "Simulacros", "Refuerzos entre tiendas"]
if auth_real["rol"] in ("admin", "super_admin"):
    paginas_negocio.append("Gestión de usuarios")
usando_datos_propios = bool(st.session_state.get("datos_subidos"))
etiqueta_datos = "🟢 Cargar datos (usando tus archivos)" if usando_datos_propios else "🔵 Cargar datos (usando datos de ejemplo)"
pagina = st.sidebar.radio(
    "Ir a", paginas_negocio,
    format_func=lambda p: etiqueta_datos if p == "Cargar datos" else p,
)
anio = st.sidebar.selectbox("Año (régimen legal)", [2026, 2027, 2028, 2029, 2030], index=1)

st.sidebar.divider()
modo_avanzado = st.sidebar.toggle("Modo avanzado", value=False)
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
    etiquetas = {
        "tiendas": "Catálogo de tiendas",
        "trafico": "Tráfico de clientes (por hora)",
        "ventas": "Ventas históricas (por hora)",
        "plantilla": "Plantilla actual (empleados)",
        "ausentismo": "Ausentismo (por empleado y día)",
    }

    st.subheader("1. Descarga la plantilla (formato esperado)")
    cols_plantillas = st.columns(len(ARCHIVOS_DATASET))
    for col, nombre in zip(cols_plantillas, ARCHIVOS_DATASET):
        col.download_button(
            f"⬇️ {etiquetas[nombre]}",
            data=ejemplo[nombre].to_csv(index=False).encode("utf-8"),
            file_name=f"{nombre}_ejemplo.csv",
            mime="text/csv",
            help=f"Columnas: {', '.join(ejemplo[nombre].columns)}",
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
    if st.button("Calcular ahorro de la red", type="primary"):
        ids = list(tiendas_visibles_df["tienda_id"].head(n_tiendas))
        resultados = calcular_red(ids, anio, TIEMPO_LIMITE_SEG_DEFAULT, datos)
        consolidado = vista_red.consolidar_resultados(resultados, tiendas_visibles_df)
        st.session_state["consolidado"] = consolidado
        st.session_state["resultados_red"] = resultados

    if "consolidado" in st.session_state:
        consolidado = st.session_state["consolidado"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Ahorro total (MXN/semana)", f"${consolidado['ahorro_total_red_mxn']:,.0f}")
        c2.metric("Ahorro %", f"{consolidado['ahorro_pct_red']:.1%}")
        c3.metric("Tiendas bajo el mínimo de 8%", len(consolidado["tiendas_bajo_minimo_8pct"]))

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
        st.bar_chart(filtrado.set_index("tienda_id")["ahorro_pct"])
        st.dataframe(filtrado, width='stretch')

        st.download_button(
            "⬇️ Descargar ranking de tiendas (CSV)",
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

        st.write("**Horario propuesto (primeras filas)**")
        st.dataframe(reporte["propuesta"]["horario_df"].head(50), width='stretch')

        dl1, dl2 = st.columns(2)
        dl1.download_button(
            "⬇️ Descargar horario completo (CSV)",
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
            "⬇️ Descargar reporte CFO (TXT)",
            data=resumen_cfo.encode("utf-8"),
            file_name=f"reporte_cfo_{tienda_id}.txt", mime="text/plain",
        )

        if modo_avanzado:
            st.write("**Tabla de trazabilidad de reglas (detalle técnico)**")
            st.dataframe(reporte["tabla_trazabilidad"], width='stretch')

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
        anio_regimen = col2.selectbox("Año de régimen (simulacro)", [None, 2026, 2027, 2028, 2029, 2030])
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
        st.success("Actualizado. Las cuentas desactivadas ya no podrán iniciar sesión.")

    tiendas_sin_acceso = gerentes_df.loc[~gerentes_df["activo"], "tienda_id"].tolist()
    if tiendas_sin_acceso:
        st.error(f"⚠️ Tiendas sin gerente activo (nadie puede entrar): {', '.join(tiendas_sin_acceso)}")

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
