# Archivos para subir

Para probar la página **Datos** (usuario `SADMIN`): suelta los CSV de una carpeta, toca **Aplicar** y abre la tienda y semana indicadas en **Horario**. Al terminar, **Volver a los archivos originales**.

| Carpeta | Qué trae | Dónde verlo | Antes | Después |
| --- | --- | --- | --- | --- |
| `tres_meses_jul_sep_2027` | Empresa de prueba con 3 tiendas (T001 chica CDMX, T005 mediana MTY, T007 grande CDMX): `tiendas_prueba`, `plantilla_prueba` (240 personas) y `trafico_prueba`, `ventas_prueba`, `ausentismo_prueba` de 14 semanas completas (27 jun – 2 oct 2027). Vacaciones de julio +5%, regreso a clases (fines de semana desde el 16 ago) +15%, 15 de septiembre +30% | Sirve encima del ejemplo o tras **Vaciar** (empresa desde cero) | — | Primera semana (27 jun – 3 jul): T001 **$32,503 (25.6%)** · T005 **$27,628 (20.7%)** · T007 **$34,055 (24.6%)**, pico cubierto; las 39 semanas restantes con «Calcular el mes» |
| `semana4oct_2026_promo_cfo` | Promo de fin de semana: tráfico y ventas +35% viernes 9 y sábado 10 oct en T001, T005 y T009; además 10 personas más de T009 faltan el sábado 10 | T001 · T005 · T009, semana 4–10 oct 2026 | $38,546 (30.8%) · $32,238 (24.5%) · $43,586 (34.7%) | **$35,544 (27.8%) · $29,333 (21.7%) · $43,976 (33.8%)** |
| | | T002 (no viene en los archivos) | $41,075 (30.4%) | $41,075, abre al instante |
| `semana27sep_2026_cdmx_mas40` | Tráfico y ventas +40% de las 12 tiendas CDMX, semana 27 sep – 3 oct 2026 (una flecha › desde hoy) | T001 | $37,115 (29.3%) | **$28,887 (21.4%)**, pico cubierto |
| | | T002 (no viene en los archivos) | $38,565 | $38,565, abre al instante |
| `semana27sep_2026_T001_faltas` | Ausentismo de T001: 12 personas más faltan el lunes 28 y el martes 29 | T001, Día lunes 28 | $37,115 | $38,170 (29.8%), pico cubierto; en el Día aparecen las faltas |
| `tienda_nueva_T051` | Tienda nueva T051 (Puebla) con su plantilla de 80 y sus semanas 20 sep y 27 sep | Selector de tienda → T051, semana 20–26 sep | no existe | $40,500 (32.2%) — igual a T017, de la que se copió |
| `semana11_2027_cdmx_mas40` | Tráfico y ventas +40% CDMX, semana 11 de 2027 (14–20 mar) | T001 | $35,159 (27.5%) | $27,006 (19.7%) |

Una tienda o semana con archivos nuevos tarda ~1–2 min la primera vez que se abre; después, al instante.
