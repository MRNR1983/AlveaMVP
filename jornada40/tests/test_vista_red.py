"""Pruebas de jornada40/vista_red.py."""
import pandas as pd
import pytest

from jornada40.vista_red import (
    calcular_techo_red_pool,
    consolidar_resultados,
    filtrar_por,
    resumen_para_demo,
)

ANIO = 2026


def _tiendas_prueba():
    return pd.DataFrame({
        "tienda_id": ["T01", "T02", "T03"],
        "cluster_id": ["CDMX-Norte", "CDMX-Norte", "GDL"],
        "formato": ["chico", "mediano", "grande"],
    })


def _reporte(ahorro_total, costo_base, costo_propuesta, ahorro_pct, pct_techo, status="OPTIMAL"):
    return {
        "ahorro_semanal": {
            "ahorro_total_mxn": ahorro_total, "costo_base_mxn": costo_base,
            "costo_propuesta_mxn": costo_propuesta, "ahorro_pct": ahorro_pct,
            "cumple_minimo_8pct": ahorro_pct >= 0.08,
            "horas_extra_doble_evitadas": 5, "horas_extra_triple_evitadas": 1,
        },
        "brecha_vs_techo": {"pct_del_techo_capturado": pct_techo},
        "status": status,
    }


def test_consolidar_resultados_suma_exacta():
    resultados = {
        "T01": _reporte(100, 1000, 900, 0.10, 0.8),
        "T02": _reporte(50, 1000, 950, 0.05, 0.6),
        "T03": _reporte(200, 1000, 800, 0.20, 0.9),
    }
    consolidado = consolidar_resultados(resultados, _tiendas_prueba())
    assert consolidado["ahorro_total_red_mxn"] == pytest.approx(100 + 50 + 200)


def test_tiendas_bajo_minimo_8pct_correctas():
    resultados = {
        "T01": _reporte(100, 1000, 900, 0.10, 0.8),
        "T02": _reporte(50, 1000, 950, 0.05, 0.6),
        "T03": _reporte(200, 1000, 800, 0.20, 0.9),
    }
    consolidado = consolidar_resultados(resultados, _tiendas_prueba())
    assert consolidado["tiendas_bajo_minimo_8pct"] == ["T02"]


def test_filtrar_por_cluster():
    resultados = {
        "T01": _reporte(100, 1000, 900, 0.10, 0.8),
        "T02": _reporte(50, 1000, 950, 0.05, 0.6),
        "T03": _reporte(200, 1000, 800, 0.20, 0.9),
    }
    consolidado = consolidar_resultados(resultados, _tiendas_prueba())
    filtrado = filtrar_por(consolidado["ranking_tiendas"], cluster_id="CDMX-Norte")
    assert set(filtrado["tienda_id"]) == {"T01", "T02"}


def test_techo_red_pool_nunca_mas_caro_que_suma_tiendas():
    techos = {
        "T01": {"costo_total_mxn": 700, "horas_ordinarias_totales": 100,
                "horas_extra_doble_totales": 0, "horas_extra_triple_totales": 0,
                "horas_subdotacion_totales": 0, "horas_sobrestaffing": 0},
        "T02": {"costo_total_mxn": 650, "horas_ordinarias_totales": 100,
                "horas_extra_doble_totales": 0, "horas_extra_triple_totales": 0,
                "horas_subdotacion_totales": 0, "horas_sobrestaffing": 0},
    }
    propuestas = {
        "T01": {"costo_total_mxn": 800, "horas_ordinarias": 100, "horas_extra_doble": 5,
                "horas_extra_triple": 0, "horas_subdotacion_pico": 20, "horas_sobrestaffing": 0},
        "T02": {"costo_total_mxn": 700, "horas_ordinarias": 100, "horas_extra_doble": 0,
                "horas_extra_triple": 0, "horas_subdotacion_pico": 0, "horas_sobrestaffing": 15},
    }
    resultado = calcular_techo_red_pool(["T01", "T02"], techos, propuestas, ANIO)
    assert resultado["techo_red_pool_mxn"] <= resultado["techo_suma_tiendas_mxn"] + 1e-6


def test_resumen_para_demo_contiene_porcentaje():
    resultados = {"T01": _reporte(100, 1000, 900, 0.10, 0.8)}
    consolidado = consolidar_resultados(resultados, _tiendas_prueba())
    texto = resumen_para_demo(consolidado)
    assert isinstance(texto, str) and len(texto) > 0
    assert "%" in texto
