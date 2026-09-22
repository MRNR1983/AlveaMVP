"""Pruebas unitarias de navegación de calendario (jornada40/calendario.py)."""

from datetime import date

from jornada40 import calendario


class TestMatrizMes:
    def test_enero_2027_empieza_en_viernes(self):
        # 1-ene-2027 es viernes -> la primera semana (domingo-sabado) incluye
        # dias de diciembre 2026 en las primeras celdas (None).
        filas = calendario.matriz_mes(2027, 1)
        primera_fila = filas[0]
        assert primera_fila[0] is None  # domingo 27-dic-2026, fuera de enero
        assert primera_fila[-1] == date(2027, 1, 2)  # sabado 2-ene-2027

    def test_todos_los_dias_del_mes_aparecen_una_vez(self):
        filas = calendario.matriz_mes(2027, 2)
        dias = [d for fila in filas for d in fila if d is not None]
        assert sorted(dias) == [date(2027, 2, i) for i in range(1, 29)]

    def test_filas_son_semanas_de_7_dias(self):
        for fila in calendario.matriz_mes(2027, 7):
            assert len(fila) == 7

    def test_diciembre_2027_no_se_desborda_a_2028_de_mas(self):
        filas = calendario.matriz_mes(2027, 12)
        dias = sorted(d for fila in filas for d in fila if d is not None)
        assert dias[0] == date(2027, 12, 1)
        assert dias[-1] == date(2027, 12, 31)


class TestSemanaDe:
    def test_domingo_de_una_fecha_entre_semana(self):
        domingo, sabado = calendario.semana_de(date(2027, 7, 7))  # miercoles
        assert domingo == date(2027, 7, 4)
        assert sabado == date(2027, 7, 10)
        assert domingo.weekday() == 6
        assert sabado.weekday() == 5


class TestNavegacionMes:
    def test_mes_anterior_cruza_anio(self):
        assert calendario.mes_anterior(2027, 1) == (2026, 12)

    def test_mes_siguiente_cruza_anio(self):
        assert calendario.mes_siguiente(2027, 12) == (2028, 1)

    def test_mes_anterior_dentro_del_anio(self):
        assert calendario.mes_anterior(2027, 7) == (2027, 6)

    def test_mes_siguiente_dentro_del_anio(self):
        assert calendario.mes_siguiente(2027, 7) == (2027, 8)


class TestRangoDeFechas:
    FECHA_MIN = date(2027, 1, 3)
    FECHA_MAX = date(2027, 12, 31)

    def test_fecha_dentro_de_rango(self):
        assert calendario.fecha_dentro_de_rango(date(2027, 7, 4), self.FECHA_MIN, self.FECHA_MAX)

    def test_fecha_fuera_de_rango(self):
        assert not calendario.fecha_dentro_de_rango(date(2026, 12, 31), self.FECHA_MIN, self.FECHA_MAX)

    def test_semana_completa_dentro_de_rango(self):
        assert calendario.semana_dentro_de_rango(date(2027, 7, 4), self.FECHA_MIN, self.FECHA_MAX)

    def test_semana_a_caballo_fuera_de_rango(self):
        # semana que empieza 26-dic-2027 termina 1-ene-2028, fuera del dataset
        assert not calendario.semana_dentro_de_rango(date(2027, 12, 26), self.FECHA_MIN, self.FECHA_MAX)


class TestSemanaYaCalculada:
    def test_semana_no_calculada_por_default(self):
        assert not calendario.semana_ya_calculada("T001", date(2027, 7, 4), set())

    def test_semana_calculada_si_esta_en_el_set(self):
        calculadas = {("T001", date(2027, 7, 4))}
        assert calendario.semana_ya_calculada("T001", date(2027, 7, 4), calculadas)

    def test_no_se_confunde_entre_tiendas(self):
        calculadas = {("T001", date(2027, 7, 4))}
        assert not calendario.semana_ya_calculada("T002", date(2027, 7, 4), calculadas)


class TestResumenDia:
    FECHA_MIN = date(2027, 1, 3)
    FECHA_MAX = date(2027, 12, 31)

    def test_resumen_dia_no_calculado(self):
        r = calendario.resumen_dia(date(2027, 7, 7), "T001", self.FECHA_MIN, self.FECHA_MAX, set())
        assert r["semana_inicio"] == date(2027, 7, 4)
        assert r["semana_fin"] == date(2027, 7, 10)
        assert r["dentro_de_rango"] is True
        assert r["calculado"] is False
        assert r["es_domingo"] is False

    def test_resumen_dia_domingo(self):
        r = calendario.resumen_dia(date(2027, 7, 4), "T001", self.FECHA_MIN, self.FECHA_MAX, set())
        assert r["es_domingo"] is True

    def test_resumen_dia_calculado(self):
        calculadas = {("T001", date(2027, 7, 4))}
        r = calendario.resumen_dia(date(2027, 7, 7), "T001", self.FECHA_MIN, self.FECHA_MAX, calculadas)
        assert r["calculado"] is True


class TestResumenSemanasDelMes:
    FECHA_MIN = date(2027, 1, 3)
    FECHA_MAX = date(2027, 12, 31)

    def test_semanas_deduplicadas(self):
        resumen = calendario.resumen_semanas_del_mes(
            2027, 7, "T001", self.FECHA_MIN, self.FECHA_MAX, set(),
        )
        inicios = [s["semana_inicio"] for s in resumen]
        assert len(inicios) == len(set(inicios))
        # Julio 2027 empieza jueves 1-jul -> semana previa (domingo 27-jun) y
        # la ultima semana puede seguir en agosto; ambas cuentan una vez.
        assert date(2027, 6, 27) in inicios

    def test_marca_calculado_correctamente(self):
        calculadas = {("T001", date(2027, 7, 4))}
        resumen = calendario.resumen_semanas_del_mes(
            2027, 7, "T001", self.FECHA_MIN, self.FECHA_MAX, calculadas,
        )
        por_inicio = {s["semana_inicio"]: s for s in resumen}
        assert por_inicio[date(2027, 7, 4)]["calculado"] is True
        assert por_inicio[date(2027, 6, 27)]["calculado"] is False
