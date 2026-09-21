"""Interfaz Streamlit del PMV de AIvena/Jornada40 (Autoservicio MX).

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

from jornada40 import costos_ahorro, datos_sinteticos, demanda_personal, escenario_base, optimizador, reglas, simulacros, vista_red

st.set_page_config(page_title="Jornada40 — Autoservicio MX", layout="wide")

DATA_DIR = Path("data")
RESULTADOS_DIR = DATA_DIR / "resultados"
ANIO_DEFAULT = 2027
FECHA_INICIO_DEFAULT = reglas.semana_domingo_a_sabado(date(ANIO_DEFAULT, 1, 1))[0]
TIEMPO_LIMITE_SEG_DEFAULT = 10.0


# ---------------------------------------------------------------------------
# Carga y cálculo (cacheados)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Generando dataset sintético (primera vez)...")
def cargar_datos() -> dict[str, pd.DataFrame]:
    archivos = ["tiendas", "trafico", "ventas", "plantilla", "ausentismo"]
    if all((DATA_DIR / f"{n}.csv").exists() for n in archivos):
        return {n: pd.read_csv(DATA_DIR / f"{n}.csv", parse_dates=["fecha"] if n in
                                ("trafico", "ventas", "ausentismo") else None)
                for n in archivos}
    return datos_sinteticos.generar_dataset_completo(
        FECHA_INICIO_DEFAULT, FECHA_INICIO_DEFAULT + pd.Timedelta(days=6), seed=42, out_dir=DATA_DIR,
    )


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
# Interfaz
# ---------------------------------------------------------------------------

datos = cargar_datos()
tiendas_df = datos["tiendas"]

st.sidebar.title("Jornada40 — Autoservicio MX")
pagina = st.sidebar.radio("Ir a", ["Vista Red", "Vista Tienda", "Simulacros", "Refuerzos entre tiendas",
                                    "Configuración de reglas", "Guion de demo"])
anio = st.sidebar.selectbox("Año (régimen legal)", [2026, 2027, 2028, 2029, 2030], index=1)
if st.sidebar.button("Recalcular todo (limpia caché)"):
    st.cache_data.clear()
    st.rerun()

if pagina == "Vista Red":
    st.header("Vista Red — consolidado de las 50 tiendas")
    n_tiendas = st.slider("Tiendas a calcular (baja este número para pruebas rápidas; usa 50 en la demo real)",
                           1, len(tiendas_df), min(5, len(tiendas_df)))
    if st.button("Calcular red"):
        ids = list(tiendas_df["tienda_id"].head(n_tiendas))
        resultados = calcular_red(ids, anio, TIEMPO_LIMITE_SEG_DEFAULT, datos)
        consolidado = vista_red.consolidar_resultados(resultados, tiendas_df)
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

elif pagina == "Vista Tienda":
    st.header("Vista Tienda")
    tienda_id = st.selectbox("Tienda", tiendas_df["tienda_id"])
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

        st.write("**Brecha contra el techo teórico**")
        st.json(reporte["brecha_vs_techo"])

        st.write("**Tabla de trazabilidad de reglas**")
        st.dataframe(reporte["tabla_trazabilidad"], width='stretch')

        st.write("**Horario propuesto (primeras filas)**")
        st.dataframe(reporte["propuesta"]["horario_df"].head(50), width='stretch')

elif pagina == "Simulacros":
    st.header("Simulacros")
    tienda_id = st.selectbox("Tienda a simular", tiendas_df["tienda_id"])
    col1, col2 = st.columns(2)
    mult_trafico = col1.slider("Multiplicador de tráfico", 0.5, 2.0, 1.0, 0.05)
    delta_plantilla = col2.number_input("Delta de plantilla (personas)", -20, 20, 0)
    tasa_ausentismo = col1.slider("Tasa de ausentismo", 0.0, 0.30, 0.06, 0.01)
    anio_regimen = col2.selectbox("Año de régimen (simulacro)", [None, 2026, 2027, 2028, 2029, 2030])

    if st.button("Correr simulacro"):
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
        cluster_sel = st.selectbox("Clúster", sorted(tiendas_df["cluster_id"].unique()))
        ids_cluster = tiendas_df.loc[tiendas_df["cluster_id"] == cluster_sel, "tienda_id"]
        propuestas_cluster = {tid: r["propuesta"] for tid, r in resultados_red.items() if tid in ids_cluster.values}
        if len(propuestas_cluster) < 2:
            st.write("Necesitas al menos 2 tiendas calculadas en este clúster.")
        else:
            propuestas = simulacros.simular_refuerzo_entre_tiendas(propuestas_cluster)
            st.dataframe(propuestas, width='stretch')

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
