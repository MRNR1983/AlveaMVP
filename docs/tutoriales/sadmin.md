# Tutorial · Super Admin (HQ)

**Tu trabajo en Alvea:** ver la red completa, revisar las reglas de ley año por año y cargar datos nuevos.
Tienes todo lo del admin de zona, para las 50 tiendas, más **Ver como**, **Reglas legales** y **Datos**. Usuario: `SADMIN`.

---

## 1. Resumen de la red

Ahorro de la semana de las 50 tiendas, tiendas en meta y tiendas sin horario legal.

![Resumen de la red](img/s01_resumen_red.png)

## 2. Ver como

Arriba del menú, **Ver como** te deja ver la app como una zona o una tienda, sin volver a entrar.

![Ver como](img/s02_ver_como.png)

## 3. Salta a otro año de la reforma

La pastilla **Jornada 48 h · 2026** también es un botón: tócala y elige el año. Alvea abre la misma fecha de ese año con su tope de horas.

![Elegir año](img/s03_anio.png)

En 2030 el tope ya es 40 h y la tienda sigue sin dejar horas pico sin cubrir. Las semanas de la demo (2026 y 2030) vienen precalculadas: el Resumen de las 50 tiendas abre al instante (2030: 21.7% de ahorro, 50 de 50 en meta).

![Semana en 2030](img/s04_2030.png)

## 4. Reglas legales

Cómo baja la jornada de 2026 a 2030, los topes de horas extra y la regla que falta validar con un abogado. **Trazabilidad completa** liga cada regla con el Decreto.

![Reglas legales](img/s05_reglas.png)

## 5. Datos

Alvea arma los horarios con cinco archivos: Tiendas, Plantilla y, por semana, Tráfico, Ventas y Ausentismo. **Archivos en uso** dice qué semanas cubre cada uno y cuántas se han subido.

1. **Descargar archivos**: elige la semana y baja el que quieras; sirve de formato.
2. **Subir archivos**: suelta uno o varios CSV. Alvea reconoce cuál es por sus columnas y la semana por sus fechas, y te lo muestra antes de aplicar.
3. **Aplicar**: cada fila reemplaza solo lo mismo (misma tienda y día); lo demás se queda. Las tiendas que cambiaron se recalculan al abrirlas; las demás abren al instante. Cambia los horarios de todos.
4. **Volver a los archivos originales** quita todo lo subido.

![Datos](img/s06_datos.png)
