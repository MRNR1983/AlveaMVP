"""Los datos de Alvea son archivos.

Cinco archivos, con las columnas de ``TIPOS``:

- ``tiendas.csv`` y ``plantilla.csv``: uno solo cada uno.
- ``trafico``, ``ventas`` y ``ausentismo``: por semana (domingo a sábado),
  en ``<tipo>/<domingo>.csv.gz``.

Hay dos capas: ``archivos/`` (los archivos de arranque que viajan en el repo)
y ``data/archivos/`` (lo que se sube desde la app, que tapa a los de
arranque). Subir un archivo lo **cruza** con lo que ya hay: cada fila cae en
la semana de su fecha y reemplaza solo lo mismo (misma tienda y día; mismo
empleado y día; misma tienda o empleado en los catálogos). Lo demás se queda.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from jornada40 import persistencia

RAIZ_REPO = Path(__file__).resolve().parent.parent
ARRANQUE = RAIZ_REPO / "archivos"            # capa base (en el repo)
SUBIDOS = Path("data") / "archivos"          # capa de archivos subidos (tapa a la base)

TIPOS: dict[str, dict] = {
    "tiendas": {"nombre": "Tiendas", "columnas": ["tienda_id", "cluster_id", "formato", "hora_apertura",
                                                  "hora_cierre", "num_cajas_fisicas", "fte_totales"],
                "llave": ["tienda_id"], "semanal": False},
    "plantilla": {"nombre": "Plantilla", "columnas": ["empleado_id", "nombre", "tienda_id", "rol", "tipo_contrato",
                                                      "salario_diario_mxn", "antiguedad_meses", "disponibilidad"],
                  "llave": ["empleado_id"], "semanal": False},
    "trafico": {"nombre": "Tráfico por hora", "columnas": ["tienda_id", "fecha", "hora", "clientes_estimados"],
                "semanal": True},
    "ventas": {"nombre": "Ventas por hora", "columnas": ["tienda_id", "fecha", "hora", "tickets", "monto_mxn"],
               "semanal": True},
    "ausentismo": {"nombre": "Ausentismo", "columnas": ["empleado_id", "fecha", "ausente"], "semanal": True},
}
SEMANALES = [t for t, i in TIPOS.items() if i["semanal"]]


# ---------------------------------------------------------------------------
# Rutas y lectura
# ---------------------------------------------------------------------------

def domingo_de(f: date) -> date:
    return f - timedelta(days=(f.weekday() + 1) % 7)


def _rel(tipo: str, domingo: date | None = None) -> str:
    return f"{tipo}.csv" if domingo is None else f"{tipo}/{domingo.isoformat()}.csv.gz"


def _ruta(rel: str) -> Path | None:
    for capa in (SUBIDOS, ARRANQUE):
        p = capa / rel
        if p.exists():
            return p
    return None


def firma(domingo: date) -> tuple:
    """Cambia si cambia cualquier archivo que usa esa semana (para cachés)."""
    out = []
    for rel in [_rel("tiendas"), _rel("plantilla")] + [_rel(t, domingo) for t in SEMANALES]:
        p = _ruta(rel)
        out.append((rel, str(p) if p else None, p.stat().st_mtime_ns if p else 0))
    return tuple(out)


def _normalizar(tipo: str, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "fecha" in df.columns:
        df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
    if "hora" in df.columns:
        df["hora"] = df["hora"].astype(int)
    if tipo == "ausentismo":
        df["ausente"] = df["ausente"].astype(str).str.lower().isin(["true", "1", "sí", "si", "x"])
    for c in ("tienda_id", "empleado_id", "cluster_id", "rol"):
        if c in df.columns:
            df[c] = df[c].astype(str)
    return df


def leer(tipo: str, domingo: date | None = None) -> pd.DataFrame:
    p = _ruta(_rel(tipo, domingo))
    if p is None:
        return pd.DataFrame(columns=TIPOS[tipo]["columnas"])
    return _normalizar(tipo, pd.read_csv(p))


def leer_semana(domingo: date) -> dict[str, pd.DataFrame]:
    d = {"tiendas": leer("tiendas"), "plantilla": leer("plantilla")}
    for t in SEMANALES:
        d[t] = leer(t, domingo)
    return d


def semana_completa(datos: dict) -> bool:
    return all(not datos[t].empty for t in ("tiendas", "plantilla", "trafico", "ventas"))


def huella(datos: dict, tienda_id: str) -> str:
    """Identifica exactamente los datos de UNA tienda en UNA semana: si no cambian,
    el resultado del optimizador tampoco (el solver es determinista)."""
    emps = set(datos["plantilla"].loc[datos["plantilla"]["tienda_id"] == tienda_id, "empleado_id"])
    partes = [
        datos["tiendas"][datos["tiendas"]["tienda_id"] == tienda_id],
        datos["plantilla"][datos["plantilla"]["tienda_id"] == tienda_id],
        datos["trafico"][datos["trafico"]["tienda_id"] == tienda_id],
        datos["ventas"][datos["ventas"]["tienda_id"] == tienda_id],
        datos["ausentismo"][datos["ausentismo"]["empleado_id"].isin(emps) & datos["ausentismo"]["ausente"]],
    ]
    h = hashlib.sha1()
    for df in partes:
        df = df.sort_values(list(df.columns)).reset_index(drop=True)
        h.update(df.to_csv(index=False).encode())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Subir: detectar, cruzar, escribir
# ---------------------------------------------------------------------------

def detectar_tipo(df: pd.DataFrame) -> str | None:
    cols = set(df.columns)
    candidatos = [t for t, i in TIPOS.items() if set(i["columnas"]) <= cols]
    return max(candidatos, key=lambda t: len(TIPOS[t]["columnas"])) if candidatos else None


def validar(tipo: str, df: pd.DataFrame) -> str | None:
    faltan = [c for c in TIPOS[tipo]["columnas"] if c not in df.columns]
    if faltan:
        return f"faltan columnas: {', '.join(faltan)}"
    if df.empty:
        return "el archivo está vacío"
    if "fecha" in df.columns:
        try:
            pd.to_datetime(df["fecha"])
        except Exception:
            return "hay fechas que no se entienden (usa AAAA-MM-DD)"
    return None


def _escribir(rel: str, df: pd.DataFrame) -> None:
    p = SUBIDOS / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, compression="gzip" if rel.endswith(".gz") else None)
    persistencia.subir(p)


def cruzar(tipo: str, nuevo: pd.DataFrame) -> dict:
    """Mezcla un archivo subido con lo que ya hay. Regresa un resumen."""
    info = TIPOS[tipo]
    nuevo = _normalizar(tipo, nuevo[info["columnas"]])
    if not info["semanal"]:
        actual = leer(tipo)
        llave = info["llave"]
        reemplazadas = int(actual[llave[0]].isin(set(nuevo[llave[0]])).sum())
        mezcla = pd.concat([actual[~actual[llave[0]].isin(set(nuevo[llave[0]]))], nuevo], ignore_index=True)
        _escribir(_rel(tipo), mezcla)
        return {"tipo": tipo, "filas": len(nuevo), "reemplazadas": reemplazadas,
                "nuevas": len(nuevo) - reemplazadas, "semanas": []}
    plantilla = leer("plantilla")
    tienda_de = dict(zip(plantilla["empleado_id"], plantilla["tienda_id"]))
    semanas = sorted({domingo_de(f) for f in nuevo["fecha"]})
    reemplazadas = 0
    for dom in semanas:
        parte = nuevo[nuevo["fecha"].map(domingo_de) == dom]
        actual = leer(tipo, dom)
        if tipo == "ausentismo":
            # se reemplaza el día completo de las tiendas que trae el archivo
            tiendas = {tienda_de.get(e) for e in parte["empleado_id"]}
            fuera = actual["fecha"].isin(set(parte["fecha"])) & actual["empleado_id"].map(tienda_de).isin(tiendas)
        else:
            pares = set(zip(parte["tienda_id"], parte["fecha"]))
            fuera = pd.Series([(t, f) in pares for t, f in zip(actual["tienda_id"], actual["fecha"])],
                              index=actual.index, dtype=bool)
        reemplazadas += int(fuera.sum())
        mezcla = pd.concat([actual[~fuera], parte], ignore_index=True)
        orden = [c for c in ("tienda_id", "empleado_id", "fecha", "hora") if c in mezcla.columns]
        _escribir(_rel(tipo, dom), mezcla.sort_values(orden).reset_index(drop=True))
    return {"tipo": tipo, "filas": len(nuevo), "reemplazadas": reemplazadas, "semanas": semanas}


def restaurar_originales() -> int:
    """Quita todo lo subido: vuelven los archivos de arranque. Regresa cuántos se quitaron."""
    n = 0
    if SUBIDOS.exists():
        for p in sorted(SUBIDOS.rglob("*")):
            if p.is_file():
                persistencia.borrar(p)
                p.unlink()
                n += 1
    return n


# ---------------------------------------------------------------------------
# Inventario (para la página Datos)
# ---------------------------------------------------------------------------

def inventario() -> pd.DataFrame:
    filas = []
    for tipo, info in TIPOS.items():
        if info["semanal"]:
            doms = sorted({p.name[:10] for capa in (ARRANQUE, SUBIDOS) for p in (capa / tipo).glob("*.csv.gz")})
            subidas = sorted(p.name[:10] for p in (SUBIDOS / tipo).glob("*.csv.gz"))
            cubre = (f"{len(doms)} semanas · {doms[0]} a {doms[-1]}" if doms else "sin archivos")
            cambios = f"{len(subidas)} semana{'s' if len(subidas) != 1 else ''} subida{'s' if len(subidas) != 1 else ''}" \
                if subidas else "—"
        else:
            df = leer(tipo)
            cubre = f"{len(df):,} {'tiendas' if tipo == 'tiendas' else 'personas'}"
            cambios = "subido" if (SUBIDOS / _rel(tipo)).exists() else "—"
        filas.append({"Archivo": info["nombre"], "Cubre": cubre, "Cambios subidos": cambios})
    return pd.DataFrame(filas)


def formato(tipo: str, domingo: date) -> pd.DataFrame:
    """Lo que hay hoy para ese archivo (la semana dada, si es semanal): sirve de formato."""
    return leer(tipo, domingo if TIPOS[tipo]["semanal"] else None)
