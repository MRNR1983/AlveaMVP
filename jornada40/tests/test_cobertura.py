"""Demanda sin cubrir medida igual para los dos horarios, y tope de días con extra en el rol fijo."""
from datetime import date

import pandas as pd

from jornada40 import cobertura, escenario_base

F = date(2026, 9, 28)


def _demanda(filas):
    return pd.DataFrame([{"tienda_id": "T", "fecha": F, "hora": h, "rol": r, "personas_requeridas": n,
                          "es_pico": p} for h, r, n, p in filas])


def test_deficit_propuesta_separa_pico_y_fuera_de_pico():
    plantilla = pd.DataFrame({"empleado_id": ["E1"], "rol": ["cajas"]})
    turnos = pd.DataFrame({"empleado_id": ["E1"], "fecha": [F], "hora_inicio": [7], "hora_fin": [9],
                           "hora_pausa": [8]})
    dem = _demanda([(7, "cajas", 1, False), (8, "cajas", 1, True), (9, "cajas", 2, False)])
    d = cobertura.deficit_propuesta(turnos, dem, plantilla)
    # 7 h cubierta; 8 h es su descanso (falta 1 en pico); 9 h nadie (faltan 2 fuera de pico)
    assert (d["pico"], d["fuera_pico"], d["total"]) == (1, 2, 3)
    assert d["por_dia"] == {F: 3}


def test_deficit_base_usa_las_mismas_franjas():
    rh = pd.DataFrame([{"fecha": F, "hora": 8, "rol": "cajas", "horas_subdotacion": 1},
                       {"fecha": F, "hora": 9, "rol": "cajas", "horas_subdotacion": 2}])
    dem = _demanda([(8, "cajas", 1, True), (9, "cajas", 2, False)])
    d = cobertura.deficit_base({"resultado_horas": rh}, dem)
    assert (d["pico"], d["fuera_pico"]) == (1, 2)


def test_rol_fijo_no_hace_extra_en_mas_de_cuatro_dias():
    dias = [F + pd.Timedelta(days=i) for i in range(6)]
    dias = [d.date() if hasattr(d, "date") else d for d in dias]
    horario = pd.DataFrame([{"tienda_id": "T", "empleado_id": "E1", "rol": "cajas", "fecha": d, "turno": "t",
                             "hora_inicio": 7, "hora_fin": 15} for d in dias])
    # Cada día falta una persona a las 15 h: solo E1 puede quedarse, pero máximo 4 días
    dem = pd.DataFrame([{"tienda_id": "T", "fecha": d, "hora": 15, "rol": "cajas", "personas_requeridas": 1}
                        for d in dias])
    aus = pd.DataFrame(columns=["empleado_id", "fecha", "ausente"]).astype({"ausente": bool})
    r = escenario_base.aplicar_ausentismo_y_demanda_real(horario, aus, dem, 2026)
    con_extra = r[(r["horas_extra_doble"] + r["horas_extra_triple"]) > 0]["fecha"].nunique()
    assert con_extra == 4
    assert int(r["horas_subdotacion"].sum()) == 2
