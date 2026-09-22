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

## Rediseño del login: contraseña única (21-sep-2026)
Simplificación pedida por el negocio: "super sencillo, cuadrito en medio
de la pantalla tipo GitHub" — un solo autenticador con **una contraseña
compartida** (`3.14159265358`, primeros dígitos de π, elegidos por ser
un valor público) para los 3 roles (Manager, Admin, SAdmin, nombres
cortos), en vez de 3 contraseñas distintas. `jornada40/usuarios.py` se
redujo a una sola función `password_login()`; el rol se sigue eligiendo
en la misma pantalla y la navegación después del login sigue igual de
segmentada por rol (Manager solo ve su tienda, Admin/SAdmin ven las 50).
Verificado con `AppTest` para los 3 roles (contraseña correcta e
incorrecta) antes de subir. Se documentaron las credenciales en
README.md y docs/index.md — brecha detectada en la revisión contra el
PDF: el reviewer no tenía forma de entrar a la app sin esto, lo cual
hubiera incumplido el Entregable 1 ("debe correr de extremo a extremo
sin el candidato presente").

## Corrección: login por usuario (no por rol elegido) + rebranding (21-sep-2026)
El negocio corrigió dos cosas del rediseño anterior:
1. El login NO debe dejar elegir el rol con un selector — el rol lo debe
   dar el nombre de usuario, como cualquier login real. Se cambió el
   formulario a usuario + contraseña; `jornada40/usuarios.py` ahora genera
   un roster completo (`ADMIN`, `SADMIN`, y `<tienda>-U1/U2/U3` por cada
   tienda) y `buscar_usuario()` resuelve rol y tienda a partir del nombre
   de usuario. Esto también resuelve, de paso, cómo saber "en qué tienda
   estoy" como gerente sin un selector aparte (va codificado en el
   usuario) — Admin/SAdmin no lo necesitan porque ven todo. Se confirmó
   de nuevo (ya lo estaba, no fue una corrección) que las 3 cuentas por
   tienda son flotantes/genéricas, de uso opcional del gerente, no
   cuentas de personas fijas.
2. Todo el texto de cara al usuario ("Jornada40") se renombró a "Alvea
   PMV": título de la página, encabezado de la barra lateral, pantalla de
   login, README, docs/index.md, docs/_config.yml. El nombre interno del
   paquete Python (`jornada40/`) se dejó igual a propósito — es una
   referencia de implementación, no algo que el reviewer vea; si se
   necesita renombrar también el paquete, es un cambio aparte más grande
   (toca todos los imports) y se puede hacer si se pide explícitamente.

Verificado con `AppTest`: usuario inexistente, contraseña incorrecta,
ADMIN/SADMIN/T001-U1 correctos, y que Manager no ve "Vista Red" ni
"Gestión de usuarios". Documentación de acceso actualizada en README.md
y docs/index.md con el nuevo formato de usuario.

## Retiro de las cuentas U1/U2/U3 + jerarquía Sadmin/Admin-por-zona/Manager-por-tienda (21-sep-2026)
El negocio pidió confirmar qué eran realmente las cuentas U1/U2/U3 antes de
seguir adivinando (ya iba dos veces mal). Decisión final, distinta a lo que
se había construido: **se retiraron por completo** -- no aportan nada al
negocio en esta etapa. Estructura nueva de usuarios:
- **1 SADMIN**: ve y puede simular cualquier perfil.
- **5 ADMIN regionales** (`ADMIN-Z1`..`ADMIN-Z5`), uno por zona geográfica.
  Las zonas agrupan los 10 clústeres ficticios del catálogo de tiendas en
  5 (`jornada40/usuarios.py::ZONAS`) -- supuesto de producto, documentado
  y fácil de ajustar si el negocio prefiere otra agrupación. Cada admin
  regional ve y opera solo las tiendas de su zona (Vista Red, Vista
  Tienda, Simulacros, Refuerzos y Gestión de usuarios quedan filtrados a
  su zona), no las 50.
- **1 MANAGER por tienda** (usuario = el propio `tienda_id`, ej. `T001`):
  ya no hay cuentas de respaldo/flotantes por tienda -- una tienda, un
  usuario.

Se agregó `_tiendas_visibles(auth, tiendas_df)` en `app.py` como punto
único de scoping: decide qué tiendas ve cada perfil (su tienda / su zona /
todas) y se usa en todas las páginas que antes mostraban las 50 tiendas
sin filtrar. Verificado con `AppTest`: SADMIN ve las 5 zonas en "Ver
como", ADMIN-Z1 ve solo sus ~12 tiendas (CDMX) en Vista Red, un manager
(`T001`) no ve "Vista Red" ni "Gestión de usuarios", y el usuario viejo
estilo `T001-U1` ya no existe. Roster total: 56 usuarios (1 + 5 + 50),
antes eran 152. README.md y docs/index.md actualizados con el nuevo
formato de credenciales.

## Ajuste: usuarios de gerente "Man001".."Man050" (21-sep-2026)
Corrección sobre el commit anterior: el usuario del gerente ya no es el
propio `tienda_id` (`T001`) -- ahora es `Man001`..`Man050`, numerado en el
mismo orden que el catálogo de tiendas (Man001 = primera tienda del
catálogo, etc.). `generar_usuarios()` genera el número por posición
(`enumerate` sobre `tiendas_df`), no por el `tienda_id` en sí. El nombre
mostrado en la sidebar tras loguearse sigue siendo el `tienda_id` real
(no `Man001`), así que el gerente sigue viendo claramente en qué tienda
está. Verificado con `AppTest`: `Man001` -> tienda de la primera fila del
catálogo, `man050` (minúsculas) también entra, `T001` ya no es un usuario
válido.
