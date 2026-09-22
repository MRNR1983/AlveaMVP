"""Pruebas unitarias del motor de reglas (jornada40/reglas.py)."""

from datetime import date

import pytest

from jornada40.reglas import (
    VIGENCIAS,
    dias_descanso_obligatorio,
    es_anio_transmision_poder_ejecutivo,
    es_domingo,
    regla_vigente,
    semana_domingo_a_sabado,
    tabla_vigente_para_anio,
)


class TestReglaVigente:
    def test_jornada_2026(self):
        assert regla_vigente("jornada_ordinaria_semanal_horas",
                             date(2026, 6, 1)) == 48

    def test_jornada_2027(self):
        assert regla_vigente("jornada_ordinaria_semanal_horas",
                             date(2027, 1, 1)) == 46

    def test_jornada_2030(self):
        assert regla_vigente("jornada_ordinaria_semanal_horas",
                             date(2030, 1, 1)) == 40

    def test_jornada_hereda_2035(self):
        # Sin fila nueva desde 2031: hereda el valor de 2030.
        assert regla_vigente("jornada_ordinaria_semanal_horas",
                             date(2035, 1, 1)) == 40

    def test_extra_tope_doble_2028(self):
        assert regla_vigente("extra_tope_doble_semanal_horas",
                             date(2028, 3, 1)) == 10

    def test_extra_tope_doble_hereda_2031(self):
        assert regla_vigente("extra_tope_doble_semanal_horas",
                             date(2031, 1, 1)) == 12

    def test_regla_constante(self):
        assert regla_vigente("prima_dominical_pct", date(2030, 12, 31)) == 0.25

    def test_2025_anio_base_pre_reforma(self):
        # Decisión de producto 21-sep-2026: 2025 es el año base (ya cerrado,
        # hay más información real de ese año), hereda los mismos valores
        # con los que arranca el régimen reformado en 2026.
        assert regla_vigente("jornada_ordinaria_semanal_horas",
                             date(2025, 6, 1)) == 48
        assert regla_vigente("extra_tope_doble_semanal_horas",
                             date(2025, 6, 1)) == 9

    def test_pre_vigencia_lanza_valueerror(self):
        # 2025 es ahora el año base del PMV (ver test de arriba); un año
        # anterior sigue sin tener fila y debe seguir lanzando el error.
        with pytest.raises(ValueError):
            regla_vigente("jornada_ordinaria_semanal_horas", date(2020, 1, 1))

    def test_regla_inexistente_lanza_valueerror(self):
        with pytest.raises(ValueError):
            regla_vigente("regla_que_no_existe", date(2027, 1, 1))


class TestTablaVigente:
    def test_contiene_todas_las_reglas(self):
        tabla = tabla_vigente_para_anio(2027)
        nombres = {f["regla"] for f in VIGENCIAS}
        assert set(tabla.keys()) == nombres
        assert tabla["jornada_ordinaria_semanal_horas"] == 46
        assert tabla["extra_tope_doble_semanal_horas"] == 9


class TestDiasDescansoObligatorio:
    def test_2027_tiene_7_sin_octubre(self):
        dias = dias_descanso_obligatorio(2027)
        assert len(dias) == 7
        assert date(2027, 10, 1) not in dias

    def test_2030_tiene_8_con_octubre(self):
        dias = dias_descanso_obligatorio(2030)
        assert len(dias) == 8
        assert date(2030, 10, 1) in dias

    def test_2024_incluye_octubre(self):
        assert date(2024, 10, 1) in dias_descanso_obligatorio(2024)

    def test_2036_ciclo_6_anios(self):
        assert date(2036, 10, 1) in dias_descanso_obligatorio(2036)
        assert es_anio_transmision_poder_ejecutivo(2036)

    def test_fechas_fijas(self):
        dias = dias_descanso_obligatorio(2027)
        assert date(2027, 1, 1) in dias
        assert date(2027, 5, 1) in dias
        assert date(2027, 9, 16) in dias
        assert date(2027, 12, 25) in dias

    def test_lunes_conmemorativos_2027(self):
        dias = dias_descanso_obligatorio(2027)
        assert date(2027, 2, 1) in dias    # primer lunes de febrero
        assert date(2027, 3, 15) in dias   # tercer lunes de marzo
        assert date(2027, 11, 15) in dias  # tercer lunes de noviembre


class TestSemana:
    def test_semana_contiene_fecha(self):
        assert semana_domingo_a_sabado(date(2027, 1, 5)) ==             (date(2027, 1, 3), date(2027, 1, 9))

    def test_domingo_devuelve_misma_semana(self):
        assert semana_domingo_a_sabado(date(2027, 1, 3)) ==             (date(2027, 1, 3), date(2027, 1, 9))

    def test_sabado_devuelve_misma_semana(self):
        assert semana_domingo_a_sabado(date(2027, 1, 9)) ==             (date(2027, 1, 3), date(2027, 1, 9))

    def test_es_domingo(self):
        assert es_domingo(date(2027, 1, 3))
        assert not es_domingo(date(2027, 1, 5))
