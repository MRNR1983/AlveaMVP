# Checklist antes de publicar (20 puntos)

Revisión del 24-sep-2026 sobre alveamvp.streamlit.app. ✅ cumple · ⚠️ cumple con límite · — no aplica (con razón).

| # | Punto | Estado | Qué se hizo / por qué |
|---|---|---|---|
| 1 | Política de privacidad | ✅ | "Privacidad y términos" en el menú: qué se guarda, para qué, cookies, cómo borrar el correo |
| 2 | Términos y condiciones | ✅ | En el mismo diálogo: prototipo que propone horarios con los archivos cargados; la decisión legal del horario es de la empresa |
| 3 | API y secretos | ⚠️ | Sin tokens ni llaves en el repo; SMTP va en `st.secrets`. La contraseña de demo es compartida y pública a propósito para evaluadores: cambiar a contraseñas individuales con hash antes de uso real |
| 4 | Forzar HTTPS | ✅ | Streamlit Cloud sirve solo HTTPS |
| 5 | Banner de cookies | — | Solo cookies de sesión necesarias, sin rastreo ni publicidad (declarado en Privacidad) |
| 6 | Metadescripciones | ⚠️ | Título "Alvea". Streamlit Cloud no deja editar meta tags; app privada con login, no busca SEO |
| 7 | Vista previa del enlace | ⚠️ | Misma limitación de Streamlit Cloud (usa su vista previa genérica) |
| 8 | Favicon | ✅ | Ícono de calendario |
| 9 | Sitemap y robots.txt | — | App con login; no debe indexarse |
| 10 | Texto ALT en imágenes | ✅ | Todas las imágenes de docs y tutoriales tienen ALT; la app no usa imágenes |
| 11 | Comprimir imágenes | ✅ | Capturas de 2.0 MB a 1.5 MB |
| 12 | Velocidad de carga | ⚠️ | Semanas ya calculadas abren al instante (caché compartida). Una semana nueva tarda ~1 min por tienda la primera vez |
| 13 | Contraste de color | ✅ | Grises, verde, ámbar y la pastilla azul ajustados a ≥ 4.5:1 (WCAG AA) |
| 14 | Web en móvil | ✅ | Probado a 390 px: sin scroll horizontal, tarjetas en 2 columnas |
| 15 | Página 404 | — | Una sola URL; Streamlit Cloud maneja rutas |
| 16 | Enlaces rotos | ✅ | 0 en README y docs |
| 17 | Validar formularios | ✅ | Login vacío, formato de correo, CSV de Datos (lectura, columnas y vacío) |
| 18 | Seguro contra spam / fuerza bruta | ✅ | 5 intentos fallidos = bloqueo de 5 min por usuario; mensaje único que no revela si el usuario existe |
| 19 | Analítica (GA4) | — | Decisión: no. El Historial interno mide el uso; GA4 obligaría a banner de cookies y a sacar datos de la empresa |
| 20 | CTA claro | ✅ | Un botón principal por pantalla: Entrar, Cambiar, Guardar, Usar mis archivos |
