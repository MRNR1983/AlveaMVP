"""Generación del dataset sintético reproducible de Autoservicio MX (PMV).

Construye el dataset completo de las 50 tiendas: catálogo de tiendas, tráfico
horario estimado de clientes, ventas derivadas, plantilla de 80 FTE por tienda
y ausentismo diario. Todos los datos son 100 % sintéticos (marca ficticia, sin
datos reales de ninguna cadena comercial) y 100 % reproducibles con semilla
fija (42 por defecto) en cada función.

Todos los supuestos numéricos (tasas de conversión, tickets promedio, rangos
salariales, multiplicadores de temporada, ruido) viven en el dict CONFIG al
inicio del archivo, visibles y fáciles de cambiar; no están enterrados en la
lógica.

Dependencias:
- jornada40/reglas.py: convenciones del dominio (semana domingo-sábado, slots
  de 1 hora de 06:00 a 23:00). Se leen de forma defensiva con getattr() para
  no acoplar este módulo a la API interna de reglas.
- numpy y pandas para la construcción de tablas (CSV/JSON como formatos de
  intercambio; nunca pickles ni binarios).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from jornada40 import reglas  # noqa: F401  convenciones compartidas del dominio

__all__ = [
    "CONFIG",
    "guardar_csv",
    "generar_tiendas",
    "generar_trafico",
    "generar_ventas",
    "generar_plantilla",
    "generar_ausentismo",
    "generar_dataset_completo",
]

# ---------------------------------------------------------------------------
# SUPUESTOS NUMÉRICOS DEL NEGOCIO (todo sintético y 100 % configurable)
# ---------------------------------------------------------------------------
CONFIG: dict = {
    "tiendas": {
        "n_default": 50,
        "fte_totales": 80,  # dato duro del reto: 80 FTE por tienda
        "clusters": [  # 10 clústeres geográficos ficticios
            "CDMX-Norte", "CDMX-Sur", "CDMX-Centro", "GDL", "MTY",
            "Puebla", "Leon", "Queretaro", "Toluca", "Merida",
        ],
        "formatos": ["chico", "mediano", "grande"],
        "peso_formato": [0.30, 0.45, 0.25],  # SUPUESTO: mix de formatos
        "apertura_rango": [6, 8],  # SUPUESTO: abre entre 06:00 y 08:00
        "cierre_rango": [21, 23],  # SUPUESTO: cierra entre 21:00 y 23:00
        "cajas_rango": [6, 14],
    },
    "trafico": {
        # SUPUESTO: clientes en la hora pico por formato, calibrado a una
        # tienda de autoservicio urbana de tamaño medio (100 % sintético).
        "clientes_pico_hora": {"chico": 90, "mediano": 150, "grande": 220},
        "pico_manana_hora": 14.0,  # pico de mediodía
        "pico_manana_amp": 1.00,
        "pico_tarde_hora": 19.0,   # segundo pico 18-20 h
        "pico_tarde_amp": 0.85,
        "ancho_gaussiana": 2.5,    # horas, dispersión de cada campana
        "fin_semana_rango": [1.30, 1.50],  # sáb/dom con +30-50 %
        "quincena_dias": [1, 15],          # días de quincena
        "quincena_ventana": 2,             # ±2 días alrededor
        "quincena_rango": [1.20, 1.35],    # +20-35 %
        "buen_fin_rango": [1.50, 1.80],    # tercer viernes de nov + su fin de semana
        "navidad_dias": [1, 24],           # 1-24 dic con multiplicador creciente
        "navidad_incremento_max": 0.40,    # hasta +40 % el 24 de dic
        "regreso_clases_dias": 10,         # últimos 10 días de agosto
        "regreso_clases_mult": 1.20,       # +20 %
        "ruido_std": 0.10,                 # ruido ±10 % normal truncado en 0
    },
    "ventas": {
        "conversion_rango": [0.70, 0.85],  # SUPUESTO: cliente->ticket 70-85 %
        "ticket_promedio_mxn": {  # SUPUESTO: ticket promedio por formato
            "chico": 120.0, "mediano": 160.0, "grande": 220.0,
        },
        "ticket_jitter": 0.10,             # variación ±10 % por tienda
        "monto_ruido_std": 0.05,           # ruido ±5 % por hora/tienda
    },
    "plantilla": {
        "roles": {  # SUPUESTO: distribución fija que suma 80 FTE (reto)
            "cajas": 26,
            "piso_reposicion": 28,
            "perecederos": 14,
            "almacen": 12,
        },
        "salario_diario_rango_mxn": {  # SUPUESTO: rangos 200-450 MXN/día
            "cajas": [220.0, 280.0],
            "piso_reposicion": [210.0, 260.0],
            "perecederos": [230.0, 300.0],
            "almacen": [200.0, 250.0],
        },
        "antiguedad_meses_rango": [0, 120],  # SUPUESTO: 0 a 10 años
        "disponibilidad_completa": 0.85,     # 85 % con disponibilidad completa
    },
    "ausentismo": {
        "tasa_default": 0.06,  # 6 % base (Bernoulli diario, sin patrón en PMV)
    },
}

# Ventana de slots del dominio (06:00-23:00), tomada de jornada40/reglas.py
# con valores por omisión para no acoplar este módulo a su API interna.
_SLOT_INICIO = int(getattr(reglas, "SLOT_HORA_INICIO", 6))
_SLOT_FIN = int(getattr(reglas, "SLOT_HORA_FIN", 23))


def _rng(seed: int) -> np.random.Generator:
    """Generador aleatorio local (sin estado global), reproducible por semilla."""
    return np.random.default_rng(seed)


def guardar_csv(df: pd.DataFrame, ruta: str | Path) -> Path:
    """Escribe un DataFrame a CSV (UTF-8, sin índice) y regresa la ruta."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8")
    return ruta


def generar_tiendas(n: int = 50, seed: int = 42) -> pd.DataFrame:
    """Genera el catálogo de tiendas (sintético, 100 % reproducible).

    Columnas: tienda_id (T001..), cluster_id (clúster geográfico ficticio),
    formato, hora_apertura, hora_cierre, num_cajas_fisicas, fte_totales (80).
    """
    cfg = CONFIG["tiendas"]
    rng = _rng(seed)
    tienda_ids = [f"T{i:03d}" for i in range(1, n + 1)]
    return pd.DataFrame({
        "tienda_id": tienda_ids,
        "cluster_id": rng.choice(cfg["clusters"], size=n),
        "formato": rng.choice(cfg["formatos"], size=n, p=cfg["peso_formato"]),
        "hora_apertura": rng.integers(cfg["apertura_rango"][0], cfg["apertura_rango"][1] + 1, size=n).astype(int),
        "hora_cierre": rng.integers(cfg["cierre_rango"][0], cfg["cierre_rango"][1] + 1, size=n).astype(int),
        "num_cajas_fisicas": rng.integers(cfg["cajas_rango"][0], cfg["cajas_rango"][1] + 1, size=n).astype(int),
        "fte_totales": int(cfg["fte_totales"]),
    })


def _curva_intradia(horas: np.ndarray, cfg: dict) -> np.ndarray:
    """Campana doble (Gaussiana): pico de mediodía + pico 18-20 h.

    SUPUESTO: amplitudes, centros y ancho configurables en CONFIG["trafico"].
    """
    denom = 2.0 * cfg["ancho_gaussiana"] ** 2
    manana = cfg["pico_manana_amp"] * np.exp(-((horas - cfg["pico_manana_hora"]) ** 2) / denom)
    tarde = cfg["pico_tarde_amp"] * np.exp(-((horas - cfg["pico_tarde_hora"]) ** 2) / denom)
    return manana + tarde


def _fechas_quincena(fechas: pd.DatetimeIndex, cfg: dict) -> set[date]:
    """Conjunto de fechas afectadas por quincena (días 1 y 15 ± ventana)."""
    dias: set[date] = set()
    for f in fechas:
        for d in cfg["quincena_dias"]:
            for delta in range(-cfg["quincena_ventana"], cfg["quincena_ventana"] + 1):
                dias.add((f + pd.Timedelta(days=d - (f.day - d))).date())
    return dias


def _es_fin_semana(fechas: pd.DatetimeIndex) -> np.ndarray:
    """Sábado y domingo (weekday 5 y 6), según convención domingo-sábado."""
    return np.asarray(fechas.dayofweek >= 5)


def _es_buen_fin(fechas: pd.DatetimeIndex) -> np.ndarray:
    """Buen Fin: tercer viernes de noviembre + su fin de semana (vie-dom)."""
    resultado = np.zeros(len(fechas), dtype=bool)
    for anio in fechas.year.unique():
        viernes = [d for d in range(1, 31) if pd.Timestamp(anio, 11, d).weekday() == 4]
        tercer_viernes = pd.Timestamp(anio, 11, viernes[2])
        mascara = (fechas >= tercer_viernes) & (fechas <= tercer_viernes + pd.Timedelta(days=2))
        resultado |= np.asarray(mascara)
    return resultado


def _factor_navidad(fechas: pd.DatetimeIndex, cfg: dict) -> np.ndarray:
    """1-24 dic: multiplicador creciente de 1.0 hasta 1+incremento_max."""
    ini, fin = cfg["navidad_dias"]
    factor = np.ones(len(fechas))
    mascara = np.asarray((fechas.month == 12) & (fechas.day >= ini) & (fechas.day <= fin))
    dias_nav = (np.asarray(fechas.day)[mascara] - ini).astype(float)
    factor[mascara] = 1.0 + cfg["navidad_incremento_max"] * dias_nav / (fin - ini)
    return factor


def _factor_regreso_clases(fechas: pd.DatetimeIndex, cfg: dict) -> np.ndarray:
    """Últimos N días de agosto con multiplicador fijo."""
    factor = np.ones(len(fechas))
    mascara = np.asarray((fechas.month == 8) & (fechas.day > 31 - cfg["regreso_clases_dias"]))
    factor[mascara] = cfg["regreso_clases_mult"]
    return factor


def generar_trafico(
    tiendas_df: pd.DataFrame,
    fecha_inicio: str | date,
    fecha_fin: str | date,
    seed: int = 42,
) -> pd.DataFrame:
    """Genera tráfico horario de clientes (sintético, reproducible).

    Modela: campana intradía de doble pico, +30-50 % en fin de semana,
    +20-35 % en quincena (días 1 y 15 ±2), Buen Fin, Navidad (1-24 dic
    creciente) y regreso a clases (últimos 10 días de agosto). Ruido ±10 %
    normal truncado en 0 por hora/tienda. Fuera del horario de atención o de
    la ventana de slots 06:00-23:00 (jornada40/reglas.py) el tráfico es 0.
    """
    cfg = CONFIG["trafico"]
    rng = _rng(seed)
    fechas = pd.date_range(pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin), freq="D")
    horas = np.arange(24)
    curva = _curva_intradia(horas.astype(float), cfg)

    n_t = len(tiendas_df)
    pico = tiendas_df["formato"].map(cfg["clientes_pico_hora"]).to_numpy(dtype=float)
    apertura = np.maximum(tiendas_df["hora_apertura"].to_numpy(), _SLOT_INICIO)
    cierre = np.minimum(tiendas_df["hora_cierre"].to_numpy(), _SLOT_FIN)
    # factores por tienda (constantes por tienda, reproducibles)
    mult_finde = rng.uniform(*cfg["fin_semana_rango"], size=n_t)
    mult_buenfin = rng.uniform(*cfg["buen_fin_rango"], size=n_t)

    n_d = len(fechas)
    es_finde = _es_fin_semana(fechas)
    es_quincena = np.array([f.date() in _fechas_quincena(fechas, cfg) for f in fechas])
    es_bf = _es_buen_fin(fechas)
    f_quincena = np.where(es_quincena, rng.uniform(*cfg["quincena_rango"], size=n_d), 1.0)
    f_navidad = _factor_navidad(fechas, cfg)
    f_regreso = _factor_regreso_clases(fechas, cfg)

    fuera_de_ventana = (horas[None, :] < apertura[:, None]) | (horas[None, :] >= cierre[:, None])
    fechas_rep = np.repeat(fechas.date, 24)
    horas_rep = np.tile(horas, n_d)

    bloques: list[pd.DataFrame] = []
    for i, tienda in enumerate(tiendas_df.itertuples(index=False)):
        dia = (np.where(es_finde, mult_finde[i], 1.0)
               * f_quincena
               * np.where(es_bf, mult_buenfin[i], 1.0)
               * f_navidad
               * f_regreso)
        base = np.outer(dia * pico[i], curva)  # (n_d, 24)
        ruido = np.maximum(0.0, 1.0 + rng.normal(0.0, cfg["ruido_std"], size=base.shape))
        clientes = np.floor(base * ruido)
        clientes[np.broadcast_to(fuera_de_ventana[i], base.shape)] = 0.0
        bloques.append(pd.DataFrame({
            "tienda_id": tienda.tienda_id,
            "fecha": fechas_rep,
            "hora": horas_rep,
            "clientes_estimados": clientes.ravel().astype(int),
        }))
    return pd.concat(bloques, ignore_index=True)


def generar_ventas(trafico_df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Deriva ventas del tráfico: tickets = clientes x conversión (70-85 %).

    El ticket promedio se infiere por tienda a partir de su tráfico (tercil
    chico/mediano/grande) con jitter ±10 % por tienda (SUPUESTO documentado en
    CONFIG). El monto incluye ruido ±5 % y se redondea a 2 decimales (MXN).
    """
    cfg = CONFIG["ventas"]
    rng = _rng(seed)
    pico_por_tienda = trafico_df.groupby("tienda_id")["clientes_estimados"].max()
    if len(pico_por_tienda) >= 3:
        formato_tienda = pd.qcut(pico_por_tienda.rank(method="first"), 3,
                                 labels=["chico", "mediano", "grande"])
    else:
        # FIX (revisión Claude): con menos de 3 tiendas (subconjuntos de
        # prueba), pd.qcut no puede partir en terciles y lanza
        # "Bin edges must be unique". Con pocas tiendas se clasifica contra
        # los umbrales fijos de clientes_pico_hora en CONFIG["trafico"],
        # que es la misma escala que ya usa generar_trafico.
        umbrales = CONFIG["trafico"]["clientes_pico_hora"]

        def _clasificar(v: float) -> str:
            if v <= umbrales["chico"]:
                return "chico"
            if v <= umbrales["mediano"]:
                return "mediano"
            return "grande"

        formato_tienda = pico_por_tienda.apply(_clasificar)
    ticket_base = formato_tienda.map(cfg["ticket_promedio_mxn"]).astype(float)
    ticket_tienda = (ticket_base * rng.uniform(1 - cfg["ticket_jitter"],
                                               1 + cfg["ticket_jitter"],
                                               size=len(ticket_base)))
    conversion_tienda = pd.Series(
        {t: rng.uniform(*cfg["conversion_rango"]) for t in pico_por_tienda.index})

    ventas = trafico_df[["tienda_id", "fecha", "hora"]].copy()
    conversion = ventas["tienda_id"].map(conversion_tienda)
    ticket = ventas["tienda_id"].map(ticket_tienda)
    clientes = trafico_df["clientes_estimados"].to_numpy(dtype=float)
    ventas["tickets"] = np.floor(clientes * conversion.to_numpy()).astype(int)
    ruido = np.maximum(0.0, 1.0 + rng.normal(0.0, cfg["monto_ruido_std"], size=len(ventas)))
    ventas["monto_mxn"] = np.round(ventas["tickets"].to_numpy() * ticket.to_numpy() * ruido, 2)
    return ventas


def generar_plantilla(tiendas_df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Genera la plantilla: exactamente 80 empleados por tienda (4000 filas).

    Distribución fija de roles por tienda (CONFIG["plantilla"]["roles"],
    suma 80): cajas=26, piso_reposicion=28, perecederos=14, almacen=12.
    Salario diario por rol en rango 200-450 MXN (supuesto documentado),
    antigüedad 0-120 meses y 85 % de disponibilidad completa.
    """
    cfg = CONFIG["plantilla"]
    rng = _rng(seed)
    roles_fijos = np.array([rol for rol, n in cfg["roles"].items() for _ in range(n)])
    if len(roles_fijos) != int(CONFIG["tiendas"]["fte_totales"]):
        raise ValueError("La distribución de roles debe sumar fte_totales (80).")

    filas: list[pd.DataFrame] = []
    seq = 1
    for tienda in tiendas_df.itertuples(index=False):
        if int(tienda.fte_totales) != len(roles_fijos):
            raise ValueError(f"{tienda.tienda_id}: fte_totales != suma de roles.")
        roles = roles_fijos.copy()
        rng.shuffle(roles)
        n = len(roles)
        salario = np.array([rng.uniform(*cfg["salario_diario_rango_mxn"][r]) for r in roles]).round(2)
        antiguedad = rng.integers(cfg["antiguedad_meses_rango"][0],
                                  cfg["antiguedad_meses_rango"][1] + 1, size=n)
        parcial = rng.choice(["parcial_manana", "parcial_tarde"], size=n)
        disponibilidad = np.where(rng.random(n) < cfg["disponibilidad_completa"], "completa", parcial)
        filas.append(pd.DataFrame({
            "empleado_id": [f"E{seq + k:05d}" for k in range(n)],
            "tienda_id": tienda.tienda_id,
            "rol": roles,
            "tipo_contrato": "completo",
            "salario_diario_mxn": salario,
            "antiguedad_meses": antiguedad.astype(int),
            "disponibilidad": disponibilidad,
        }))
        seq += n
    return pd.concat(filas, ignore_index=True)


def generar_ausentismo(
    plantilla_df: pd.DataFrame,
    fecha_inicio: str | date,
    fecha_fin: str | date,
    tasa: float = 0.06,
    seed: int = 42,
) -> pd.DataFrame:
    """Ausentismo diario por empleado: Bernoulli independiente (tasa=6 % PMV).

    Sin patrón adicional en el PMV (sin correlación por día/persona).
    """
    rng = _rng(seed)
    fechas = pd.date_range(pd.Timestamp(fecha_inicio), pd.Timestamp(fecha_fin), freq="D").date
    idx = pd.MultiIndex.from_product(
        [plantilla_df["empleado_id"].to_numpy(), fechas],
        names=["empleado_id", "fecha"],
    )
    ausente = rng.random(len(idx)) < tasa
    return pd.DataFrame({"ausente": ausente}, index=idx).reset_index()


def generar_dataset_completo(
    fecha_inicio: str | date,
    fecha_fin: str | date,
    seed: int = 42,
    out_dir: str | Path = "data/",
) -> dict[str, pd.DataFrame]:
    """Orquesta la generación de las 5 tablas y escribe los CSV a out_dir.

    Orden: tiendas -> trafico -> ventas -> plantilla -> ausentismo.
    Nombres de archivo: tiendas.csv, trafico.csv, ventas.csv, plantilla.csv,
    ausentismo.csv. Regresa el dict de DataFrames generados.
    """
    tiendas = generar_tiendas(seed=seed)
    trafico = generar_trafico(tiendas, fecha_inicio, fecha_fin, seed=seed)
    ventas = generar_ventas(trafico, seed=seed)
    plantilla = generar_plantilla(tiendas, seed=seed)
    ausentismo = generar_ausentismo(plantilla, fecha_inicio, fecha_fin, seed=seed)
    tablas: dict[str, pd.DataFrame] = {
        "tiendas": tiendas,
        "trafico": trafico,
        "ventas": ventas,
        "plantilla": plantilla,
        "ausentismo": ausentismo,
    }
    out = Path(out_dir)
    for nombre, df in tablas.items():
        guardar_csv(df, out / f"{nombre}.csv")
    return tablas


if __name__ == "__main__":
    generar_dataset_completo(date(2027, 1, 3), date(2027, 1, 9))
