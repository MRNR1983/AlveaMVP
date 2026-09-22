# Registro de uso de herramientas agénticas

Evidencia del proceso de construcción del PMV: qué se usó, qué se asumió,
qué quedó pendiente, por módulo.

## jornada40/reglas.py
Construido con Kimi a partir de un prompt detallado con el texto del
Decreto DOF 01-05-2026 y sus transitorios. Interpretación del art. 66/68
(tramo al triple de 4h) marcada como pendiente de validación legal en
`reglas_README.md`.

## jornada40/datos_sinteticos.py
Construido con Kimi. Revisión posterior (Claude) encontró y corrigió un
bug real: `generar_ventas` fallaba con menos de 3 tiendas (`pd.qcut` no
tolera menos de 3 bins) — se agregó una ruta alterna con umbrales fijos
de `CONFIG["trafico"]["clientes_pico_hora"]` para ese caso.

## jornada40/demanda_personal.py
Construido por Claude (Kimi dejó de estar disponible durante la sesión).
Erlang C implementado a mano (sin librería externa). Supuestos de
calibración (tiempo de atención, productividad por rol) documentados en
`CONFIG` y marcados como pendientes de calibrar con datos reales.

## jornada40/escenario_base.py
Construido por Claude. Simplificación documentada: la asignación de horas
extra a empleados específicos no garantiza contigüidad horaria con su
turno original (el optimizador de optimizador.py sí la modela).

## jornada40/optimizador.py
Construido por Claude con OR-Tools CP-SAT. Simplificaciones documentadas
en el docstring del módulo: jornada diaria colapsada a un tope genérico
(diurna) en vez de diurna/nocturna/mixta por turno; clasificación
ordinaria/extra a nivel semanal, no día por día. El "techo teórico" se
implementa como el mismo modelo sin penalización de sobrestaffing ni de
déficit fuera de pico — se demuestra en el docstring que esto garantiza
costo_techo <= costo_operativo.

**Nota de rendimiento**: cada tienda resuelve un problema de ~80 empleados
x 7 días x 17 horas; correr las 50 tiendas completas toma varios minutos
incluso con paralelismo. Documentado en app.py y en el README.

## jornada40/costos_ahorro.py
Construido por Claude. El "candado anti-trampa" (penalización por
subdotación nueva que la propuesta introduce y el base no tenía) usa un
multiplicador de 3x como convención de negocio del PMV, no una cifra
legal — está documentado como tal en el código.

## jornada40/simulacros.py
Construido por Claude. El préstamo de personal entre tiendas es una
PROPUESTA (no modifica horarios automáticamente) y nunca deja a la tienda
origen con menos margen del que ella misma reportó como excedente.

## jornada40/vista_red.py
Construido por Claude. El techo de red (pool teórico) es una cota
superior, no una propuesta operativa — está documentado explícitamente
en el docstring del módulo.

## app.py / Docker / README
Construido por Claude. Decisión de diseño: el cálculo por tienda es bajo
demanda y cacheado en sesión (no se resuelven las 50 tiendas de forma
eager al arrancar), por el tiempo que toma CP-SAT a escala completa. La
Vista Red deja elegir cuántas tiendas calcular para permitir pruebas
rápidas antes de correr las 50 completas.

## Verificación
Las 62 pruebas unitarias (`pytest jornada40/tests/ -v`) pasan sobre el
conjunto completo de módulos, incluyendo los casos de esquina descritos
en el diseño original (fechas de festivos, topes de jornada por año,
cuadre exacto del desglose diario contra el semanal, techo <= operativo,
préstamos que nunca dejan a la tienda origen en déficit propio).

## Sesión 21-sep-2026: calendario real de quincena, calificación de ediciones, autenticación por rol
Construido por Claude, con las decisiones de negocio confirmadas por Mauricio en la conversación:

- **`jornada40/datos_sinteticos.py`**: se quitó el esquema de quincena por
  "días fijos ± ventana" y se reemplazó por un calendario real (`_calendario_quincenas`):
  paga el 15 y el último día real del mes (28/29/30/31, no fijo en 30);
  si cae sábado/domingo/festivo se adelanta al viernes hábil anterior
  (fuente: LFT, vía comparabien.com.mx y cronista.com — el salario debe
  pagarse en día laborable); si cae viernes se traslapa con el fin de
  semana, si cae lunes NO se traslapa con el fin de semana previo; se
  diluye el incremento si el periodo entre pagos es más largo de 15 días.
  Multiplicadores de Buen Fin (+30%) y Navidad (+60% el 24-dic) ajustados
  con fuentes reales (NielsenIQ vía retailers.mx, Cámara de Comercio de
  Guadalajara) en vez de supuestos sin respaldo — quincena queda como
  supuesto declarado sin fuente pública. Se corrigió de paso un bug de
  rendimiento real preexistente (O(n_fechas²) en el cálculo de quincena)
  que causaba timeout al generar varios años de una tienda.
- **`jornada40/costos_ahorro.calificar_edicion_manual`**: compara un
  horario editado a mano (renombrar/intercambiar/borrar un turno) contra
  el óptimo del CP-SAT — costo extra en MXN, déficit de cobertura pico
  nuevo, y castigo cuando la edición empuja a alguien a horas extra
  triples. Como el optimizador ya encontró el costo mínimo legal, por
  construcción cualquier edición manual sólo puede alejarse de ese óptimo.
- **`jornada40/usuarios.py` + login en `app.py`**: autenticación
  simplificada (documentada como tal, no apta para producción) con 3
  roles — Gerente de tienda (solo su tienda, sin Vista Red), Admin/HQ
  (las 50 tiendas + gestión de usuarios), Super Admin (todo, más un
  selector "Ver como" para simular cualquier perfil sin re-loguearse).
  Cada tienda tiene 3 cuentas genéricas (U1/U2/U3, activables/desactivables
  desde HQ) para capturar horas de personal cuya alta individual aún no
  se completa, en vez de perderlas. Contraseñas de demo documentadas como
  brecha de seguridad conocida y aceptada para el PMV (con fallback a
  `st.secrets` si se configuran en Streamlit Cloud).

## Revisión de código antes de desplegar (21-sep-2026)
Auditoría propia antes de subir a producción, pedida explícitamente:
encontrado y corregido código muerto en `usuarios.py` (import sin usar),
un bug real donde `app.py` seguía referenciando columnas viejas
(`nombre`/`rol_tienda`) tras el rediseño de `usuarios.py` (se habría roto
en producción, atrapado con `AppTest` antes de desplegar), y la ausencia
de `.gitignore` — sin él, `data/` (150MB de CSV regenerables, incluidas
las 50 tiendas × 2025-2030) se habría subido al repo público.
