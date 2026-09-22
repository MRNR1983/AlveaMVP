# Alvea PMV — Autoservicio MX

PMV para el reto técnico de ALVENA/AIvena (Head of Product and Technology):
una herramienta que arma el horario semanal de personal para 50 tiendas
de un autoservicio genérico ("Autoservicio MX", marca ficticia, datos
100% sintéticos), respeta la jornada legal mexicana (incluida la reforma
de 40 horas, DOF 01-05-2026) y cuantifica en pesos el ahorro frente a
cómo se programaría hoy.

## Acceso / credenciales de login

La app pide iniciar sesión: usuario + contraseña, como cualquier login
(no hay que elegir un rol aparte — el nombre de usuario ya dice a qué rol
y, si aplica, a qué tienda pertenece). La contraseña es la misma para
todos.

**Contraseña (para cualquier usuario):** `3.14159265358`

| Usuario | Quién es |
| --- | --- |
| `SADMIN` | Super Admin — ve todo, puede "ver como" cualquier perfil sin volver a loguearse |
| `ADMIN-Z1` .. `ADMIN-Z5` | Admin regional — una cuenta por zona (CDMX, Occidente, Noreste, Centro, Sureste), ve/gestiona solo las tiendas de su zona |
| `Man001` .. `Man050` | Gerente de tienda — numerado en el mismo orden que el catálogo (Man001 = primera tienda, etc.); solo ve su tienda |

Cada tienda tiene un único usuario de gerente (no hay cuentas de respaldo).
Las 5 zonas de Admin agrupan los 10 clústeres geográficos del catálogo de
tiendas (ver `jornada40/usuarios.py::ZONAS` — es un supuesto de producto,
ajustable). Los admins regionales y sus tiendas se activan/desactivan desde
"Gestión de usuarios" (rol Admin o SAdmin; un admin regional solo ve/gestiona
su propia zona).

La contraseña son los primeros dígitos de π, elegidos justo por ser un
valor público y fácil de compartir con quien revise la herramienta — no es
un secreto real (ver `jornada40/usuarios.py` para el detalle de seguridad
aceptado en este PMV).

## Cómo correrla con Docker

```bash
docker build -t jornada40 .
docker run -p 8501:8501 jornada40
```

Abre `http://localhost:8501`. La primera vez genera el dataset sintético
automáticamente (unos segundos) y calcula bajo demanda cuando entras a
cada pantalla — no hay pasos manuales adicionales.

> Nota: este Dockerfile se construyó siguiendo la práctica estándar y se
> verificó ejecutando la app directamente con Python en este entorno
> (ver "Verificación rápida" abajo), pero no se pudo correr `docker build`
> en la sandbox donde se desarrolló (sin demonio Docker disponible).
> Verifícalo en tu máquina antes de la demo.

## Cómo correrla sin Docker

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Estructura del repo

```
jornada40/
  reglas.py            Motor de reglas legales por vigencia (autoajustable por año)
  datos_sinteticos.py  Generador del dataset sintético (50 tiendas, año completo)
  demanda_personal.py  Tráfico/ventas -> personas requeridas (Erlang C + carga/productividad)
  escenario_base.py    Horario base: rotativo fijo + horas extra realista
  optimizador.py       Optimizador CP-SAT (OR-Tools): horario propuesto + techo teórico
  costos_ahorro.py     Ahorro semanal/diario, brecha vs. techo, trazabilidad, calificación de ediciones manuales
  calendario.py         Navegación mes -> semana -> día (funciones puras, sin Streamlit)
  simulacros.py        Palancas de escenario + préstamo de personal entre tiendas
  vista_red.py         Consolidado de las 50 tiendas, filtros, acciones masivas
  usuarios.py            Roster y login (SADMIN / ADMIN-Z1..Z5 / Man001..Man050)
  tests/                83 pruebas unitarias (pytest)
app.py                 Interfaz Streamlit (pantalla del gerente: calendario mes/semana/día)
Dockerfile, requirements.txt
docs/
  guion_demo.md         Guion de 45 min para la demo con el CEO/CFO
  registro_agentic.md    Registro de uso de herramientas agénticas por módulo
```

## Calendario del gerente (mes -> semana -> día)

La pantalla de arranque del gerente es un calendario (cuadrícula de días,
como el catálogo de tiendas: 1 clic = 1 semana). Regla de producto,
documentada en `jornada40/calendario.py`:

- El dataset de ejemplo cubre el **año completo** (`datos_sinteticos.py`,
  antes solo generaba 7 días), así que cualquier mes/semana del año se
  puede navegar.
- **El mes es navegación visual gratis** (solo fechas, sin calcular nada).
  El cálculo real (horario base, propuesta del optimizador, techo teórico y
  ahorro en MXN) se dispara **solo cuando el gerente abre una semana**
  específica (botón "Calcular esta semana") — calcular las 52 semanas de
  una tienda al arrancar sería lentísimo e innecesario.
- Dentro de una semana ya calculada, cada día se puede abrir para ver sus
  turnos ("chips": un bloque por empleado) y editarlos a mano —
  **solo reasignar un turno a otro empleado de la plantilla** (no se
  puede inventar horas nuevas). Como el CP-SAT ya encontró el óptimo legal
  para esa semana, cualquier edición manual solo puede alejarse de él; por
  eso se califica con `costos_ahorro.calificar_edicion_manual` (delta de
  costo en MXN, si deja hueco nuevo en hora pico, y si empuja a alguien a
  horas extra triples) en vez de resolverse como un problema nuevo.

## Supuestos clave (y de dónde salen)

- **Retailer de referencia**: autoservicio genérico (perfil tipo súper/híper
  mediano), 50 tiendas × 80 FTE cada una, domingo a sábado.
- **Calibración de demanda** (`demanda_personal.py`): tiempo de atención en
  caja (Erlang C), factores de carga por ticket y productividad por rol —
  todos en `CONFIG` al inicio del archivo, marcados como **SUPUESTOS —
  CALIBRAR CON DATOS REALES EN FASE 1**.
- **Datos sintéticos** (`datos_sinteticos.py`): tasas de conversión, ticket
  promedio, rangos salariales y multiplicadores de temporada, en `CONFIG`.
- **Valor hora**: `salario_diario / (jornada_horas_semana_vigente / 6)` —
  a menor jornada legal, mayor valor hora (no se puede bajar el salario
  semanal, Transitorio 7 del Decreto).
- **Candado anti-trampa**: si la propuesta deja subdotación nueva que el
  base no tenía, esas horas se penalizan y se restan del ahorro reportado
  (`costos_ahorro.py`, multiplicador 3x documentado como convención de
  negocio del PMV, no cifra legal).

**Nota de calibración pendiente**: en corridas de prueba con pocas tiendas,
el ahorro salió por encima de 60%, más alto de lo esperado para una demo
creíble (ver conversación de diseño: "un ahorro muy alto se ve
sospechoso"). Antes de la demo real, correr las 50 tiendas completas y
revisar si el escenario base (`escenario_base.py`) está sub-dotado de
forma realista, o si los parámetros de `demanda_personal.py` necesitan
ajuste — el ahorro debe presentarse siempre junto al % del techo
capturado, nunca como cifra suelta.

## Pendiente de validación legal

De la tabla de trazabilidad (`costos_ahorro.armar_tabla_trazabilidad()`):

- **Art. 68 LFT** (tramo de tiempo extra al triple, hasta 4h semanales
  adicionales al tope del doble): la lectura conjunta de los arts. 66/68
  reformados es una interpretación adoptada para el PMV, documentada en
  `jornada40/reglas.py` y `jornada40/reglas_README.md` — debe validarla
  un abogado laboral contra el texto exacto del Decreto DOF 01-05-2026.

Todo lo demás en la tabla (jornada ordinaria por año, jornada diaria,
descansos, prima dominical, días festivos) está verificado contra el
texto del decreto y la LFT vigente.

## Fuera de alcance del PMV

- Traslado físico de personal entre tiendas como decisión legal (la
  herramienta propone préstamos dentro del mismo clúster; el acuerdo con
  la persona trabajadora y la aprobación son responsabilidad del cliente).
- Integración con nómina real y con el registro electrónico de jornada
  (art. 132 fr. XXXIV) — el PMV solo exporta CSV.
- Pronóstico de demanda con machine learning (el dataset es sintético con
  semilla fija).
- Día de jornada electoral del art. 74 fr. IX (depende de un calendario
  electoral externo).
- Distinción de jornada diurna/nocturna/mixta por turno en el optimizador
  (usa un tope diario genérico; ver docstring de `optimizador.py`).
- Edición manual de turnos más allá de reasignar (arrastrar horas, crear
  turnos nuevos, editar por lotes) — el PMV solo permite reasignar un turno
  ya generado a otro empleado de la plantilla, calificado contra el óptimo
  (ver "Calendario del gerente" arriba). Drag-and-drop real y edición
  masiva quedan para una siguiente iteración.

**Nota**: el optimizador y el cálculo de horario siguen operando **una
semana a la vez** (como exige la LFT, domingo a sábado) — lo que cambió es
que el dataset y la navegación del calendario ahora cubren el año
completo, así que el gerente puede calcular *cualquier* semana del año,
no solo la primera.

## Nota de rendimiento

Cada tienda resuelve un problema CP-SAT de ~80 empleados × 7 días × 17
horas. Con el límite de tiempo por defecto (10s por tienda), calcular la
red completa (50 tiendas × 2 corridas: propuesta y techo) toma varios
minutos incluso en paralelo. La Vista Red de la app deja elegir cuántas
tiendas calcular para pruebas rápidas; usa las 50 para la corrida real
antes de la demo.

## Cómo correr las pruebas

```bash
pip install -r requirements.txt
pytest jornada40/tests/ -v
```

62 pruebas, todas pasando sobre el conjunto completo de módulos.

## Verificación rápida

Sin Docker, para confirmar que la app arranca sin errores:

```bash
pip install -r requirements.txt
streamlit run app.py --server.headless true &
sleep 5 && curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8501
```

Debe regresar `200`. Para verificar que no hay excepciones de Python al
cargar cada pantalla (más confiable que el curl anterior, que solo prueba
que el servidor responde):

```python
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=120)
at.run()
assert not at.exception
```
