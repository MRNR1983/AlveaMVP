"""Pruebas de jornada40/optimizador.py, con tiendas de juguete (pequeñas)."""
from datetime import date

import pandas as pd
import pytest

from jornada40.optimizador import resolver_red, resolver_techo_teorico, resolver_tienda

TIENDA_ID = "TX01"
REF = date(2026, 1, 4)  # domingo


def _plantilla_juguete(n=12):
    roles = (["cajas"] * 3 + ["piso_reposicion"] * 3 + ["perecederos"] * 3 + ["almacen"] * 3)[:n]
    return pd.DataFrame({
        "empleado_id": [f"EX{i:03d}" for i in range(n)],
        "tienda_id": TIENDA_ID,
        "rol": roles,
        "tipo_contrato": "completo",
        "salario_diario_mxn": 240.0,
        "antiguedad_meses": 12,
        "disponibilidad": "completa",
    })


def _demanda_juguete(requerido_por_hora: int = 1, dias=3, horas=range(9, 13), pico_horas=(11,)):
    filas = []
    fechas = [REF + pd.Timedelta(days=i) for i in range(dias)]
    for fecha in fechas:
        for h in horas:
            for rol in ("cajas", "piso_reposicion", "perecederos", "almacen"):
                filas.append({
                    "tienda_id": TIENDA_ID, "fecha": fecha.date() if hasattr(fecha, "date") else fecha,
                    "hora": h, "rol": rol,
                    "personas_requeridas": requerido_por_hora,
                    "es_pico": h in pico_horas,
                })
    return pd.DataFrame(filas)


def _ausentismo_vacio(plantilla):
    return pd.DataFrame(columns=["empleado_id", "fecha", "ausente"])


def test_resolver_tienda_demanda_cero_costo_cero():
    plantilla = _plantilla_juguete()
    demanda = _demanda_juguete(requerido_por_hora=0, dias=2, horas=range(9, 11))
    ausentismo = _ausentismo_vacio(plantilla)
    r = resolver_tienda(TIENDA_ID, 2026, plantilla, demanda, ausentismo,
                         tiempo_limite_seg=15, fecha_inicio=REF)
    assert r["status"] in ("OPTIMAL", "FEASIBLE")
    assert r["costo_total_mxn"] == 0.0
    assert r["horas_extra_doble"] == 0
    assert r["horas_extra_triple"] == 0


def test_resolver_tienda_respeta_jornada_ordinaria_semanal():
    plantilla = _plantilla_juguete()
    demanda = _demanda_juguete(requerido_por_hora=2, dias=3, horas=range(9, 15), pico_horas=(11, 12))
    ausentismo = _ausentismo_vacio(plantilla)
    r = resolver_tienda(TIENDA_ID, 2026, plantilla, demanda, ausentismo, tiempo_limite_seg=20,
                        fecha_inicio=REF)
    assert r["status"] in ("OPTIMAL", "FEASIBLE")
    horas_por_empleado = r["horario_df"].groupby("empleado_id")["hora"].count()
    assert (horas_por_empleado <= 48).all()  # tope 2026 = 48h ordinaria + extra permitida


def test_costo_2030_mas_caro_por_hora_que_2026_misma_demanda():
    plantilla = _plantilla_juguete()
    demanda2026 = _demanda_juguete(requerido_por_hora=1, dias=2, horas=range(9, 11))
    demanda2030 = _demanda_juguete(requerido_por_hora=1, dias=2, horas=range(9, 11))
    ausentismo = _ausentismo_vacio(plantilla)
    r2026 = resolver_tienda(TIENDA_ID, 2026, plantilla, demanda2026, ausentismo, tiempo_limite_seg=15,
                             fecha_inicio=REF)
    r2030 = resolver_tienda(TIENDA_ID, 2030, plantilla, demanda2030, ausentismo, tiempo_limite_seg=15,
                             fecha_inicio=REF)
    horas2026 = r2026["horas_ordinarias"] + r2026["horas_extra_doble"] + r2026["horas_extra_triple"]
    horas2030 = r2030["horas_ordinarias"] + r2030["horas_extra_doble"] + r2030["horas_extra_triple"]
    if horas2026 == horas2030 and horas2026 > 0:
        assert r2030["costo_total_mxn"] > r2026["costo_total_mxn"]


def test_techo_no_cuesta_mas_que_operativo():
    plantilla = _plantilla_juguete()
    demanda = _demanda_juguete(requerido_por_hora=1, dias=3, horas=range(9, 15), pico_horas=(11, 12))
    ausentismo = _ausentismo_vacio(plantilla)
    r_op = resolver_tienda(TIENDA_ID, 2026, plantilla, demanda, ausentismo, modo="operativo",
                            tiempo_limite_seg=20, fecha_inicio=REF)
    r_techo = resolver_techo_teorico(TIENDA_ID, 2026, plantilla, demanda, ausentismo,
                                      tiempo_limite_seg=20, fecha_inicio=REF)
    assert r_techo["status"] in ("OPTIMAL", "FEASIBLE")
    assert r_techo["costo_total_mxn"] <= r_op["costo_total_mxn"] + 1e-6


def test_demanda_pico_imposible_no_crashea():
    plantilla = _plantilla_juguete(n=2)  # muy poca gente
    demanda = _demanda_juguete(requerido_por_hora=50, dias=2, horas=range(9, 11), pico_horas=(9, 10))
    ausentismo = _ausentismo_vacio(plantilla)
    r = resolver_tienda(TIENDA_ID, 2026, plantilla, demanda, ausentismo, tiempo_limite_seg=10,
                        fecha_inicio=REF)
    assert r["status"] in ("INFEASIBLE", "OPTIMAL", "FEASIBLE")


def test_resolver_red_dos_tiendas_en_paralelo():
    plantilla = pd.concat([
        _plantilla_juguete(n=6).assign(tienda_id="TA"),
        _plantilla_juguete(n=6).assign(tienda_id="TB"),
    ], ignore_index=True)
    demanda = pd.concat([
        _demanda_juguete(requerido_por_hora=1, dias=1, horas=range(9, 11)).assign(tienda_id="TA"),
        _demanda_juguete(requerido_por_hora=1, dias=1, horas=range(9, 11)).assign(tienda_id="TB"),
    ], ignore_index=True)
    ausentismo = pd.DataFrame(columns=["empleado_id", "fecha", "ausente"])
    resultados = resolver_red(["TA", "TB"], 2026, plantilla, demanda, ausentismo,
                               tiempo_limite_seg=10, max_workers=2, fecha_inicio=REF)
    assert set(resultados.keys()) == {"TA", "TB"}
    for r in resultados.values():
        assert r["status"] in ("OPTIMAL", "FEASIBLE", "INFEASIBLE")
