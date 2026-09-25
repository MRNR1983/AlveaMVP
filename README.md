# Alvea PMV — Autoservicio MX

PMV para el reto técnico de ALVENA/AIvena (Head of Product and Technology):
una herramienta que arma el horario semanal de personal para 50 tiendas
de un autoservicio genérico ("Autoservicio MX", marca ficticia), trabaja
solo con archivos (tiendas, plantilla, tráfico, ventas, ausentismo), respeta la jornada legal mexicana (incluida la reforma
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
"Usuarios" (rol Admin o SAdmin; un admin regional solo ve/gestiona
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

Abre `http://localhost:8501`. Los archivos de arranque vienen en
`archivos/` — no hay pasos manuales adicionales.

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

## Capturas

| | |
| --- | --- |
| ![Semana](docs/tutoriales/img/g02_semana.png) | ![Día](docs/tutoriales/img/g07_calificacion.png) |
| ![Mes](docs/tutoriales/img/g09_mes.png) | ![Resumen de la red](docs/tutoriales/img/s01_resumen_red.png) |

Comparación punto por punto contra el PDF del reto: [`docs/comparacion_pdf.md`](docs/comparacion_pdf.md).

## Estructura del repo

```
jornada40/
  reglas.py            Motor de reglas legales por vigencia (48 h en 2026 -> 40 h en 2030)
  archivos.py          Los datos son archivos: lectura por semana, subir = cruzar por semana/tienda, huella
  datos_sinteticos.py  Generador de los archivos de arranque (lo usa scripts/generar_archivos.py)
  demanda_personal.py  Tráfico/ventas -> personas requeridas (Erlang C + carga/productividad + calibración)
  escenario_base.py    Horario base: rol fijo rotativo + horas extra (cómo se programa hoy)
  optimizador.py       CP-SAT (OR-Tools): cada persona, cada día -> 1 de 4 turnos fijos o descanso
  costos_ahorro.py     Ahorro semanal, brecha vs. techo, trazabilidad legal, calificación de cambios manuales
  calendario.py        Funciones puras de fechas (mes/semana)
  vista_red.py         Consolidado de tiendas (Resumen)
  usuarios.py          Cuentas (SADMIN / ADMIN-Z1..Z5 / Man001..Man050)
  auditoria.py         Historial de acciones
  notificaciones.py    Avisos en la app + correo SMTP
  semana.py            Cálculo completo de 1 tienda x 1 semana (lo usan la app y el precálculo)
  precalculado.py      Lee/escribe semanas ya resueltas (carpeta precalculado/)
  persistencia.py      Respaldo de los datos vivos en la rama datos-app de GitHub
  simulacros.py        (sin interfaz desde 24-sep-2026; se conserva con sus pruebas)
  tests/               pruebas unitarias (pytest)
app.py                 Interfaz Streamlit
archivos_para_subir/   Un juego de archivos para probar Datos (semana 11 de 2027, CDMX +40%)
archivos/              Archivos de arranque: tiendas.csv, plantilla.csv y, por semana, trafico/ ventas/ ausentismo/
scripts/generar_archivos.py  Escribe archivos/ (sep 2026 a dic 2030)
scripts/precalcular.py Precalcula semanas (todas las tiendas de los archivos) -> precalculado/<versión>/
precalculado/          Semanas de demo ya resueltas (2026 y 2030): abren al instante
docs/
  manual.md            Cómo se calcula, límites y lo que se probó (el uso está en tutoriales/)
  tutoriales/          Un tutorial por rol (gerente, admin, sadmin) con capturas
  guion_demo.md        Guion de 45 min para la demo
  registro_agentic.md  Registro de uso de herramientas agénticas
```

## Cómo funciona (resumen)

- **Menú por rol.** Gerente: Horario, Avisos. Admin de zona: Resumen,
  Horario, Avisos (con historial), Usuarios. Super Admin: lo mismo +
  Reglas legales, Datos y "Ver como".
- **El horario empieza hoy y llega a diciembre de 2030.** El régimen
  legal sale solo de la fecha de cada semana (48 h en 2026, 46 en 2027,
  44 en 2028, 42 en 2029, 40 en 2030). Si una semana cruza de año, aplica
  el tope del año nuevo (el más estricto).
- **Turnos fijos.** Cada tienda tiene 4 turnos de 8 h (Apertura,
  Intermedio, Refuerzo pico, Cierre). El optimizador decide quién entra a
  cuál turno cada día (o descansa) y a qué hora toma cada quien su
  descanso (4.ª–6.ª hora), para que ningún turno se vacíe en hora pico.
- **Un rol por vista.** Horario = operación y dinero de una tienda; Resumen = zona o red.
  Solo el gerente cambia turnos; admin y HQ ven el horario en lectura.
- **Se calcula al abrir.** Abrir una semana en Horario la
  calcula; no hay botón escondido. Los datos de cada semana se generan
  bajo demanda y son reproducibles.
- **Cambios manuales.** En la vista Día: persona -> nuevo turno (se
  aplica al elegirlo y queda guardado para el admin). Se bloquea si rompe la ley (7 días seguidos o más horas que el
  máximo legal) y si no, se califica contra el óptimo (costo y cobertura
  en pico). Se puede deshacer.

Método, límites y pruebas en [`docs/manual.md`](docs/manual.md).

**Tutoriales por rol** (con capturas de la app en línea): [Gerente](docs/tutoriales/gerente.md) · [Admin de zona](docs/tutoriales/admin.md) · [Super Admin](docs/tutoriales/sadmin.md).

Checklist de publicación (privacidad, seguridad, móvil, contraste, etc.): [`docs/checklist_publicacion.md`](docs/checklist_publicacion.md).

## Supuestos clave (y de dónde salen)

- **Retailer de referencia**: autoservicio genérico (perfil tipo súper/híper
  mediano), 50 tiendas × 80 FTE cada una, domingo a sábado.
- **Calibración de demanda** (`demanda_personal.py`): tiempo de atención en
  caja (Erlang C), factores de carga por ticket y productividad por rol —
  todos en `CONFIG` al inicio del archivo, marcados como **SUPUESTOS —
  CALIBRAR CON DATOS REALES EN FASE 1**.
- **Archivos de arranque** (`archivos/`, escritos por `datos_sinteticos.py`):
  tasas de conversión, ticket promedio, rangos salariales y temporadas en
  `CONFIG`. Cualquier archivo con las mismas columnas los reemplaza desde
  la página Datos.
- **Valor hora**: `salario_diario / (jornada_horas_semana_vigente / 6)` —
  a menor jornada legal, mayor valor hora (no se puede bajar el salario
  semanal, Transitorio 7 del Decreto).
- **Candado anti-trampa**: si la propuesta deja subdotación nueva que el
  base no tenía, esas horas se penalizan y se restan del ahorro reportado
  (`costos_ahorro.py`, multiplicador 3x documentado como convención de
  negocio del PMV, no cifra legal).

**Calibración (resuelta 24-sep-2026)**: la demanda que sale del archivo de
tráfico solo captura trabajo ligado a tickets y era 30–55% de la
capacidad de 80 FTE, por eso el ahorro salía en 50–70% (irreal). Ahora
`demanda_personal.CONFIG["factor_calibracion"]` escala la demanda por
rol y formato bajo un supuesto explícito: **la plantilla actual opera al
60% de su capacidad a 48 h en una semana promedio** (se probó 85% y la
tienda se quedaba sin gente en la apertura). Con descansos escalonados
por persona, turnos extendibles 2 h y el optimizador en dos pasos, el
resultado con las 50 tiendas es 29% de ahorro en la red en 2026 (50/50
tiendas ≥ 8%, 0 horas pico sin cubrir) y 21.7% en 2030 (50/50 ≥ 8%, 0 horas
pico sin cubrir).

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
- Pronóstico de demanda con machine learning (hoy la demanda sale del
  archivo de tráfico de cada semana).
- Día de jornada electoral del art. 74 fr. IX (depende de un calendario
  electoral externo).
- Turnos nocturnos/mixtos (7 / 7.5 h): el catálogo usa turnos de 8 h
  (tope diurno).
- Editar el catálogo de turnos por tienda desde la interfaz (hoy se
  deriva del horario de la tienda).
- Simulacros de escenario y préstamo de personal entre tiendas: el código
  existe (`simulacros.py`), pero se quitó de la interfaz para mantenerla
  enfocada.

## Nota de rendimiento

Cada tienda-semana es un modelo CP-SAT de ~80 personas × 7 días × 4
turnos. El solver es **determinista** (límite de tiempo por trabajo del
solver, no por reloj, y búsqueda paralela en orden fijo): los mismos datos
dan el mismo horario en cualquier corrida o reinicio.

Las semanas de la demo (esta semana y las 2 siguientes, en 2026 y 2030, más
la semana a la que lleva el salto a 2027–2029) vienen **precalculadas** en
`precalculado/` para las 50 tiendas: abren al instante, también el Resumen
de la red. Cualquier otra semana se calcula al abrirla (~25 s por tienda) y
queda en caché. Para agregar semanas: `python scripts/precalcular.py
AAAA-MM-DD ...` (domingos) y subir la carpeta. Si cambia el modelo, se sube
`VERSION_MODELO` y se vuelve a precalcular.

## Los datos son archivos

Cinco archivos: `tiendas.csv`, `plantilla.csv` y, por semana (domingo a
sábado), `trafico`, `ventas` y `ausentismo`. Los de arranque están en
`archivos/`; lo que se sube en la página **Datos** (solo HQ) se guarda en
`data/archivos/` y tapa a los de arranque, para todos los usuarios.

Subir un archivo lo **cruza** con lo que ya hay: Alvea reconoce cuál es por
sus columnas y la semana por sus fechas; cada fila reemplaza solo lo mismo
(misma tienda y día; mismo empleado y día; misma tienda o empleado en los
catálogos) y lo demás se queda. Cada tienda-semana tiene una **huella** de
sus archivos: si cambia, esa tienda se recalcula; si no, abre al instante.
"Volver a los archivos originales" quita todo lo subido.

## Datos que sobreviven reinicios

Streamlit Cloud borra el disco al reiniciar. Historial, avisos, cambios de
turno, estado de las cuentas y archivos subidos se respaldan en la rama `datos-app` del repo y
se restauran al arrancar. Se activa con un secreto en Streamlit Cloud
(Settings → Secrets):

```toml
github_token = "github_pat_..."   # fine-grained: solo este repo, Contents: Read and write
```

Sin el secreto la app funciona igual, solo sin respaldo.

## Cómo correr las pruebas

```bash
pip install -r requirements.txt
pytest jornada40/tests/ -v
```

96 pruebas, todas pasando.

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
