# Jornada40 — Autoservicio MX

PMV para el reto técnico de ALVENA/AIvena (Head of Product and Technology):
una herramienta que arma el horario semanal de personal para 50 tiendas
de un autoservicio genérico ("Autoservicio MX", marca ficticia, datos
100% sintéticos), respeta la jornada legal mexicana (incluida la reforma
de 40 horas, DOF 01-05-2026) y cuantifica en pesos el ahorro frente a
cómo se programaría hoy.

## Acceso / credenciales de login

La app pide iniciar sesión. Es un autenticador simple de PMV: **una sola
contraseña compartida** para los 3 roles, elige el rol en la misma
pantalla de login.

| Rol | Contraseña |
| --- | --- |
| Manager (elige tienda y cuenta U1/U2/U3) | `3.14159265358` |
| Admin | `3.14159265358` |
| SAdmin (Super Admin — ve todo, puede "ver como" cualquier perfil) | `3.14159265358` |

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
  datos_sinteticos.py  Generador del dataset sintético (50 tiendas)
  demanda_personal.py  Tráfico/ventas -> personas requeridas (Erlang C + carga/productividad)
  escenario_base.py    Horario base: rotativo fijo + horas extra realista
  optimizador.py       Optimizador CP-SAT (OR-Tools): horario propuesto + techo teórico
  costos_ahorro.py     Ahorro semanal/diario, brecha vs. techo, tabla de trazabilidad
  simulacros.py        Palancas de escenario + préstamo de personal entre tiendas
  vista_red.py         Consolidado de las 50 tiendas, filtros, acciones masivas
  tests/                62 pruebas unitarias (pytest)
app.py                 Interfaz Streamlit
Dockerfile, requirements.txt
docs/
  guion_demo.md         Guion de 45 min para la demo con el CEO/CFO
  registro_agentic.md    Registro de uso de herramientas agénticas por módulo
```

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
- Horizonte de más de una semana.
- Día de jornada electoral del art. 74 fr. IX (depende de un calendario
  electoral externo).
- Distinción de jornada diurna/nocturna/mixta por turno en el optimizador
  (usa un tope diario genérico; ver docstring de `optimizador.py`).

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
