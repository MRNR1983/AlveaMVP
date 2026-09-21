"""Pruebas de jornada40/costos_ahorro.py."""
from datetime import date

import pandas as pd
import pytest

from jornada40.costos_ahorro import (
    armar_tabla_trazabilidad,
    calcular_ahorro_semanal,
    calcular_brecha_vs_techo,
    desglosar_por_dia,
    generar_reporte_cfo,
)

ANIO = 2026


def _resultado(costo, horas_ord=40, horas_ed=0, horas_et=0, horas_sub=0, horas_sobre=0, costo_ord=None):
    return {
        "horas_ordinarias_totales": horas_ord,
        "horas_extra_doble_totales": horas_ed,
        "horas_extra_triple_totales": horas_et,
        "horas_subdotacion_totales": horas_sub,
        "horas_sobrestaffing": horas_sobre,
        "costo_ordinario_mxn": costo_ord if costo_ord is not None else costo,
        "costo_total_mxn": costo,
    }


def test_ahorro_cero_si_base_igual_propuesta():
    r = _resultado(1000, horas_ord=40, horas_ed=5)
    ahorro = calcular_ahorro_semanal(r, r, ANIO)
    assert ahorro["ahorro_total_mxn"] == 0
    assert ahorro["cumple_minimo_8pct"] is False


def test_penalizacion_por_subdotacion_nueva_resta_del_ahorro():
    base = _resultado(1000, horas_sub=0)
    propuesta = _resultado(900, horas_sub=10)  # ahorra $100 en papel, pero deja 10h sin cubrir
    ahorro = calcular_ahorro_semanal(base, propuesta, ANIO)
    assert ahorro["penalizacion_subdotacion_no_cubierta_mxn"] > 0
    assert ahorro["ahorro_total_mxn"] < (1000 - 900)


def test_desglosar_por_dia_cuadra_con_semanal():
    fechas = [date(2026, 1, 4 + i) for i in range(7)]
    base_diario = {f: _resultado(150, horas_ord=48 / 7, costo_ord=150) for f in fechas}
    propuesta_diario = {f: _resultado(130, horas_ord=48 / 7, costo_ord=130) for f in fechas}
    df = desglosar_por_dia(base_diario, propuesta_diario, ANIO)
    assert len(df) == 8  # 7 días + total
    fila_total = df.iloc[-1]
    assert fila_total["fecha"] == "TOTAL"
    suma_manual = df.iloc[:-1]["ahorro_total_mxn"].sum()
    assert abs(suma_manual - fila_total["ahorro_total_mxn"]) < 0.01


def test_brecha_vs_techo_propuesta_igual_techo():
    base = _resultado(1000)
    techo = _resultado(700)
    propuesta = _resultado(700)
    brecha = calcular_brecha_vs_techo(base, propuesta, techo)
    assert brecha["pct_del_techo_capturado"] == pytest.approx(1.0)
    assert brecha["brecha_mxn"] == pytest.approx(0.0)


def test_tabla_trazabilidad_14_filas_sin_nulos():
    tabla = armar_tabla_trazabilidad()
    assert len(tabla) == 14
    assert not tabla[["regla", "articulo_fuente", "tipo", "estado"]].isna().any().any()


def test_generar_reporte_cfo_llaves_esperadas():
    base = _resultado(1000)
    propuesta = _resultado(900)
    techo = _resultado(850)
    reporte = generar_reporte_cfo("T001", base, propuesta, techo, ANIO)
    for llave in ("resumen_ejecutivo", "ahorro_semanal", "brecha_vs_techo", "tabla_trazabilidad"):
        assert llave in reporte
