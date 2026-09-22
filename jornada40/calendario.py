"""Navegación de calendario (mes -> semana -> día) para la pantalla del gerente.

DECISIÓN DE PRODUCTO (21-sep-2026): la pantalla principal del gerente deja
de ser "Cargar datos" y pasa a ser un calendario tipo tabla periódica
(cuadrícula de días clicables, mes -> semana -> día), porque es como el
negocio piensa el horario (LFT exige jornada domingo-a-sábado, no un rango
libre de 7 días). El dataset de ejemplo ya cubre el año completo
(``app.FECHA_INICIO_DEFAULT`` a ``app.FECHA_FIN_DATASET_EJEMPLO``), pero
calcular el horario (CP-SAT) de las 52 semanas de una tienda al iniciar
sería lentísimo e innecesario -- la regla de producto es:

    Mes = navegación visual (gratis, solo fechas). Datos reales
    (costo, ahorro, horas) SOLO en la semana que el gerente abre
    explícitamente -- ahí sí se llama a ``app.calcular_resultado_tienda``.

Este módulo es puro (solo ``datetime``, sin pandas ni Streamlit) para que
sea trivial de probar: solo resuelve "qué día/semana es qué" y "qué celda
ya se calculó", nunca hace cálculo de horario ni de costos.
"""
from __future__ import annotations

from datetime import date, timedelta

from jornada40 import reglas

__all__ = [
    "NOMBRES_MES", "DIAS_SEMANA_ABREV",
    "matriz_mes", "semana_de", "mes_anterior", "mes_siguiente",
    "fecha_dentro_de_rango", "semana_dentro_de_rango",
    "semana_ya_calculada", "resumen_dia", "resumen_semanas_del_mes",
]

NOMBRES_MES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

# La semana del proyecto empieza en domingo (ver reglas.semana_domingo_a_sabado).
DIAS_SEMANA_ABREV = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"]


def semana_de(fecha: date) -> tuple[date, date]:
    """(domingo, sábado) de la semana que contiene ``fecha``. Alias de reglas.py
    para que el resto del calendario solo importe este módulo."""
    return reglas.semana_domingo_a_sabado(fecha)


def matriz_mes(anio: int, mes: int) -> list[list[date | None]]:
    """Cuadrícula del mes: una fila por semana (domingo..sábado), una columna
    por día. Las celdas fuera del mes (relleno de la primera/última semana)
    son ``None`` -- así la UI puede pintarlas vacías sin lógica extra.

    El número de filas varía (4 a 6) según cuántas semanas domingo-sábado
    toca el mes; no se rellena a un tamaño fijo.
    """
    primer_dia = date(anio, mes, 1)
    ultimo_dia = (date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)) - timedelta(days=1)
    domingo_inicial, _ = semana_de(primer_dia)

    filas: list[list[date | None]] = []
    cursor = domingo_inicial
    while cursor <= ultimo_dia:
        fila = [
            (cursor + timedelta(days=i)) if (cursor + timedelta(days=i)).month == mes else None
            for i in range(7)
        ]
        filas.append(fila)
        cursor += timedelta(days=7)
    return filas


def mes_anterior(anio: int, mes: int) -> tuple[int, int]:
    return (anio - 1, 12) if mes == 1 else (anio, mes - 1)


def mes_siguiente(anio: int, mes: int) -> tuple[int, int]:
    return (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def fecha_dentro_de_rango(fecha: date, fecha_min: date, fecha_max: date) -> bool:
    """True si ``fecha`` cae dentro del dataset disponible (año del PMV)."""
    return fecha_min <= fecha <= fecha_max


def semana_dentro_de_rango(fecha_inicio_semana: date, fecha_min: date, fecha_max: date) -> bool:
    """True si la semana completa (domingo a sábado) cabe dentro del dataset --
    una semana a caballo entre dos años del dataset no se puede calcular
    completa, así que se marca fuera de rango."""
    fecha_fin_semana = fecha_inicio_semana + timedelta(days=6)
    return fecha_inicio_semana >= fecha_min and fecha_fin_semana <= fecha_max


def semana_ya_calculada(
    tienda_id: str, fecha_inicio_semana: date, semanas_calculadas: set[tuple[str, date]],
) -> bool:
    """``semanas_calculadas`` es el registro (en session_state) de qué pares
    (tienda_id, domingo_de_la_semana) el gerente ya abrió y disparó el
    cálculo real -- ver regla de producto en el docstring del módulo."""
    return (tienda_id, fecha_inicio_semana) in semanas_calculadas


def resumen_dia(
    fecha: date, tienda_id: str, fecha_min: date, fecha_max: date,
    semanas_calculadas: set[tuple[str, date]],
) -> dict:
    """Estado de una celda del mes para pintarla: a qué semana pertenece, si
    esa semana ya tiene datos reales calculados, y si es domingo (arranque
    de semana operativa, útil para resaltar la cuadrícula)."""
    domingo, sabado = semana_de(fecha)
    return {
        "fecha": fecha,
        "es_domingo": reglas.es_domingo(fecha),
        "semana_inicio": domingo,
        "semana_fin": sabado,
        "dentro_de_rango": fecha_dentro_de_rango(fecha, fecha_min, fecha_max),
        "calculado": semana_ya_calculada(tienda_id, domingo, semanas_calculadas),
    }


def resumen_semanas_del_mes(
    anio: int, mes: int, tienda_id: str, fecha_min: date, fecha_max: date,
    semanas_calculadas: set[tuple[str, date]],
) -> list[dict]:
    """Una fila por semana distinta que toca el mes (deduplicada: la última
    semana de un mes suele seguir en el siguiente). Pensada para un resumen
    tipo lista debajo de la cuadrícula del mes."""
    vistas: set[date] = set()
    resumen = []
    for fila in matriz_mes(anio, mes):
        for fecha in fila:
            if fecha is None:
                continue
            domingo, sabado = semana_de(fecha)
            if domingo in vistas:
                continue
            vistas.add(domingo)
            resumen.append({
                "semana_inicio": domingo,
                "semana_fin": sabado,
                "dentro_de_rango": semana_dentro_de_rango(domingo, fecha_min, fecha_max),
                "calculado": semana_ya_calculada(tienda_id, domingo, semanas_calculadas),
            })
    return resumen
