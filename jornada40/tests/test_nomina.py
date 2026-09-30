"""Regla de pago semanal: tiempo completo cobra su semana; por hora cobra lo trabajado."""
import pandas as pd

from jornada40 import nomina


def _plantilla(contratos):
    return pd.DataFrame({"empleado_id": [f"E{i}" for i in range(len(contratos))],
                         "salario_diario_mxn": [480.0] * len(contratos),
                         "tipo_contrato": contratos})


def test_tiempo_completo_cobra_su_semana_aunque_trabaje_menos():
    p = nomina.costo_por_empleado({"E0": 30}, _plantilla(["completo"]), 2026)["E0"]
    vh = 480 / (48 / 6)
    assert p["ordinaria_pagada"] == 48 and p["ordinaria_trabajada"] == 30
    assert abs(p["costo_mxn"] - 48 * vh) < 1e-6


def test_tiempo_completo_sin_turnos_tambien_cobra():
    pagos = nomina.costo_por_empleado({}, _plantilla(["completo"]), 2026)
    assert pagos["E0"]["costo_mxn"] > 0


def test_por_hora_cobra_solo_lo_trabajado():
    p = nomina.costo_por_empleado({"E0": 30}, _plantilla(["por_hora"]), 2026)["E0"]
    assert p["ordinaria_pagada"] == 30


def test_extra_se_paga_encima_del_sueldo():
    vh = 480 / (48 / 6)
    p = nomina.costo_por_empleado({"E0": 50}, _plantilla(["completo"]), 2026)["E0"]
    assert p["doble"] == 2 and abs(p["costo_mxn"] - (48 * vh + 2 * vh * 2)) < 1e-6


def test_aplicar_piso_reporta_capacidad_liberada():
    turnos = pd.DataFrame({"empleado_id": ["E0", "E0"], "hora_inicio": [7, 7], "hora_fin": [15, 15]})
    res = nomina.aplicar_piso({"costo_total_mxn": 1.0, "turnos_df": turnos},
                              _plantilla(["completo", "completo"]), 2026)
    assert res["horas_capacidad_liberada"] == (48 - 16) + 48
    assert res["costo_sin_piso_mxn"] == 1.0
