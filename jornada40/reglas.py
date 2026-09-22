"""Motor de reglas legales laborales mexicanas parametrizado por año calendario.

Este módulo es el único punto de verdad sobre la normativa laboral vigente
para el PMV de Autoservicio MX (marca ficticia, datos 100% sintéticos).

Qué hace:
  1. Mantiene una tabla de vigencias (VIGENCIAS) con una fila por regla y
     año de entrada en vigor, basada en el Decreto DOF 01-05-2026 que
     reforma la LFT (arts. 58, 59, 61, 66, 67 derogado, 68, 69, 132 fr. XXXIV
     y 994 fr. IV Bis) y sus transitorios.
  2. Expone ``regla_vigente(nombre_regla, fecha)`` para consultar el valor
     de una regla en cualquier fecha.
  3. Expone ``tabla_vigente_para_anio(anio)`` para obtener todas las reglas
     vigentes en un año dado.
  4. Calcula el calendario de días de descanso obligatorio (art. 74 LFT).
  5. Utilidades de semana (domingo a sábado) y detección de domingos.

Cómo autoajustarse ante reformas futuras:
  - Si en 2031+ no hay reforma nueva, el motor hereda la última fila conocida
    (busca la fila con mayor "desde" que sea <= año de la fecha).
  - Si hay reforma, se agrega UNA fila nueva a VIGENCIAS con el nuevo "desde"
    y valor. No se toca código.

Dependencias: solo la librería estándar (datetime). No usa pandas ni OR-Tools.
"""

from __future__ import annotations

from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Tabla de vigencias
# ---------------------------------------------------------------------------
# Cada fila: {"regla": <nombre>, "desde": <año de entrada en vigor>, "valor": <número>}
# La regla vigente para un año dado es la de mayor "desde" <= año.
# Valores "sin cambio por año" tienen una única fila desde 2026 y se heredan
# automáticamente para cualquier año futuro.

VIGENCIAS: list[dict] = [
    # Año base pre-reforma (2025, decisión de producto 21-sep-2026: usarlo
    # como punto de partida porque ya cerró y hay más información real de
    # ese año para calibrar). El Decreto DOF 01-05-2026 no modificó nada de
    # esto retroactivamente, así que 2025 hereda los MISMOS valores con los
    # que arranca el régimen reformado en 2026 (el primer año de la reforma
    # tampoco bajó horas, solo empezó a contar la reducción escalonada desde
    # 2027). Es una CONVENCIÓN DEL PMV, no un hecho verificado contra un
    # texto legal vigente en 2025 -- ver reglas_README.md.
    {"regla": "jornada_ordinaria_semanal_horas", "desde": 2025, "valor": 48},

    # Jornada ordinaria semanal (art. 58 reformado + Transitorio Segundo):
    # reducción escalonada 2026→2030, congelada en 40 desde 2031 salvo nueva fila.
    {"regla": "jornada_ordinaria_semanal_horas", "desde": 2026, "valor": 48},
    {"regla": "jornada_ordinaria_semanal_horas", "desde": 2027, "valor": 46},
    {"regla": "jornada_ordinaria_semanal_horas", "desde": 2028, "valor": 44},
    {"regla": "jornada_ordinaria_semanal_horas", "desde": 2029, "valor": 42},
    {"regla": "jornada_ordinaria_semanal_horas", "desde": 2030, "valor": 40},

    # Jornada diaria máxima (art. 61). Extendida a 2025 (ver nota de año
    # base arriba); sin cambios por año en ningún caso.
    # Se modela como tres reglas escalares porque regla_vigente() regresa
    # un único número; el optimizador las consulta por tipo de jornada.
    {"regla": "jornada_diaria_max_horas_diurna", "desde": 2025, "valor": 8},
    {"regla": "jornada_diaria_max_horas_nocturna", "desde": 2025, "valor": 7},
    {"regla": "jornada_diaria_max_horas_mixta", "desde": 2025, "valor": 7.5},

    # Tope de tiempo extra al doble, semanal (art. 66 reformado +
    # Transitorio Cuarto): amplía el tramo al doble 2026→2030, hereda 12
    # desde 2031 salvo nueva fila. 2025 hereda el mismo valor con el que
    # arranca 2026 (ver nota de año base arriba).
    {"regla": "extra_tope_doble_semanal_horas", "desde": 2025, "valor": 9},
    {"regla": "extra_tope_doble_semanal_horas", "desde": 2026, "valor": 9},
    {"regla": "extra_tope_doble_semanal_horas", "desde": 2027, "valor": 9},
    {"regla": "extra_tope_doble_semanal_horas", "desde": 2028, "valor": 10},
    {"regla": "extra_tope_doble_semanal_horas", "desde": 2029, "valor": 11},
    {"regla": "extra_tope_doble_semanal_horas", "desde": 2030, "valor": 12},

    # Máximo de días a la semana en que puede haber tiempo extra (art. 66).
    {"regla": "extra_tope_doble_dias_max_semana", "desde": 2025, "valor": 4},

    # Tiempo extra al triple, semanal: horas adicionales por encima del
    # tope al doble (art. 68).
    #
    # INTERPRETACIÓN ADOPTADA (PENDIENTE DE VALIDACIÓN LEGAL):
    # Se fija un tramo al triple de hasta 4 horas semanales sobre el tope
    # al doble, de modo que la jornada semanal máxima efectiva es
    # jornada_ordinaria_semanal + tope_doble + 4. El art. 68 LFT (texto
    # vigente) dispone: "Trabajo no podrá exigirse por más de tres horas
    # diarias ni por más de tres veces en una semana" para el tiempo
    # extraordinario, y en su segundo párrafo prevé el pago al triple para
    # las horas extraordinarias que excedan de nueve semanales. El Decreto
    # DOF 01-05-2026 reforma estos topes (Transitorio Cuarto). La cifra de
    # "4 horas adicionales" adoptada aquí es una convención del PMV para
    # modelar el tramo al triple y NO sustituye asesoría legal: la frase
    # exacta y los límites finales del segundo párrafo del art. 68
    # reformado deben validarse contra el texto publicado en el DOF.
    {"regla": "extra_tope_triple_semanal_horas", "desde": 2025, "valor": 4},
    {"regla": "extra_tope_triple_semanal_horas", "desde": 2026, "valor": 4},

    # Jornada diaria total máxima: ordinaria + extraordinaria (art. 68,
    # último párrafo: la jornada diaria no podrá exceder de doce horas).
    {"regla": "jornada_diaria_total_max_horas", "desde": 2025, "valor": 12},

    # Por cada 6 días de trabajo, 1 de descanso con salario íntegro (art. 69).
    {"regla": "dias_trabajo_maximo_antes_descanso", "desde": 2025, "valor": 6},

    # Prima dominical: 25% sobre el salario diario (art. 71, 2o. párrafo).
    {"regla": "prima_dominical_pct", "desde": 2025, "valor": 0.25},

    # Multiplicadores de pago.
    {"regla": "pago_extra_doble_multiplicador", "desde": 2025, "valor": 2.0},   # art. 66
    {"regla": "pago_extra_triple_multiplicador", "desde": 2025, "valor": 3.0},  # art. 68
    # Día de descanso trabajado: 2x además del salario del descanso (art. 73).
    {"regla": "pago_dia_descanso_trabajado_multiplicador", "desde": 2025, "valor": 2.0},
    # Día festivo trabajado: 2x además del salario del descanso obligatorio
    # (art. 75) → costo total efectivo de 3x ese día (1 propio + 2 extra).
    {"regla": "pago_dia_festivo_trabajado_multiplicador", "desde": 2025, "valor": 2.0},

    # Descanso intrajornada: media hora cuando la jornada es continua (art. 63).
    {"regla": "descanso_intrajornada_minutos", "desde": 2025, "valor": 30},
]

# Regla jornada_diaria_max_horas del enunciado, desagregada por tipo de
# jornada. Mantiene compatibilidad conceptual con la consulta por tipo.
MAPA_JORNADA_DIARIA: dict[str, str] = {
    "diurna": "jornada_diaria_max_horas_diurna",
    "nocturna": "jornada_diaria_max_horas_nocturna",
    "mixta": "jornada_diaria_max_horas_mixta",
}


def regla_vigente(nombre_regla: str, fecha: date) -> float | int:
    """Regresa el valor vigente de una regla en la fecha dada.

    Toma el año de la fecha, busca entre las filas de esa regla la que
    tenga mayor "desde" <= ese año, y regresa su valor (herencia hacia
    adelante: si no hay fila para 2031+, se hereda la última conocida).

    Args:
        nombre_regla: nombre de la regla tal como aparece en VIGENCIAS.
        fecha: fecha de consulta; solo se usa su año calendario.

    Raises:
        ValueError: si la regla no existe o no hay ninguna fila con
            "desde" <= año de la fecha (p. ej., consultar 2020, antes del
            año base que modela el PMV -- ver nota de año base en VIGENCIAS).
    """
    anio = fecha.year
    candidatas = [f for f in VIGENCIAS
                  if f["regla"] == nombre_regla and f["desde"] <= anio]
    if not candidatas:
        raise ValueError(
            f"No hay vigencia para la regla '{nombre_regla}' en el año {anio}."
        )
    return max(candidatas, key=lambda f: f["desde"])["valor"]


def tabla_vigente_para_anio(anio: int) -> dict[str, float | int]:
    """Regresa TODAS las reglas vigentes para un año, como diccionario.

    Para cada regla distinta en VIGENCIAS, aplica la misma lógica de
    herencia que ``regla_vigente`` usando el 1 de enero del año dado.
    """
    return {nombre: regla_vigente(nombre, date(anio, 1, 1))
            for nombre in {f["regla"] for f in VIGENCIAS}}


# ---------------------------------------------------------------------------
# Calendario de días de descanso obligatorio (art. 74 LFT)
# ---------------------------------------------------------------------------
# TODO: falta modelar el fracción IX del art. 74 (día de jornada electoral,
# cuando las autoridades correspondientes determinen). Depende de un
# calendario electoral externo y queda FUERA DEL ALCANCE del PMV a propósito;
# no es un bug, es una decisión de alcance documentada.

def _primer_lunes(anio: int, mes: int) -> date:
    """Primer lunes de un mes y año dados."""
    d = date(anio, mes, 1)
    return d + timedelta(days=(7 - d.weekday()) % 7)  # weekday: lunes=0


def _tercer_lunes(anio: int, mes: int) -> date:
    """Tercer lunes de un mes y año dados."""
    return _primer_lunes(anio, mes) + timedelta(days=14)


def es_anio_transmision_poder_ejecutivo(anio: int) -> bool:
    """True si el año corresponde a transmisión del Poder Ejecutivo Federal.

    Patrón: años donde (año - 2024) % 6 == 0 (2024, 2030, 2036, ...).
    """
    return (anio - 2024) % 6 == 0


def dias_descanso_obligatorio(anio: int) -> list[date]:
    """Días de descanso obligatorio del art. 74 LFT para un año, ordenados.

    Incluye el 1 de octubre de cada seis años cuando corresponde a la
    transmisión del Poder Ejecutivo Federal. Excluye el día de jornada
    electoral (art. 74 fr. IX) por decisión de alcance del PMV (ver TODO).
    """
    dias = [
        date(anio, 1, 1),                 # Año Nuevo
        _primer_lunes(anio, 2),           # conmemora 5 de febrero
        _tercer_lunes(anio, 3),           # conmemora 21 de marzo
        date(anio, 5, 1),                 # Día del Trabajo
        date(anio, 9, 16),                # Independencia
        _tercer_lunes(anio, 11),          # conmemora 20 de noviembre
        date(anio, 12, 25),               # Navidad
    ]
    if es_anio_transmision_poder_ejecutivo(anio):
        dias.append(date(anio, 10, 1))    # transmisión del Poder Ejecutivo
    return sorted(dias)


# ---------------------------------------------------------------------------
# Utilidades de semana (domingo a sábado)
# ---------------------------------------------------------------------------

def es_domingo(fecha: date) -> bool:
    """True si la fecha cae en domingo (weekday: lunes=0 ... domingo=6)."""
    return fecha.weekday() == 6


def semana_domingo_a_sabado(fecha: date) -> tuple[date, date]:
    """Regresa el (domingo, sábado) de la semana que contiene la fecha.

    La semana empieza en domingo y termina en sábado, según la convención
    del proyecto.
    """
    dias_desde_domingo = (fecha.weekday() + 1) % 7
    domingo = fecha - timedelta(days=dias_desde_domingo)
    return domingo, domingo + timedelta(days=6)
