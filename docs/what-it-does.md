# Qué hace el kernel (y qué no)

El kernel es **Claude Code bien configurado para trabajar como agente 24/7**, hablando contigo por el plugin oficial de Telegram. Está hecho con piezas oficiales: Claude Code, el plugin de Telegram de Anthropic e instrucciones en texto (`.md`).

## Qué agrega

- **Tareas programadas que no caducan** (`cron.py`): corren a su hora, sobreviven reinicios y te entregan el resultado por Telegram. Las tareas nativas de Claude Code caducan a los 7 días y pueden llegar hasta 30 min tarde, por eso aquí están desactivadas.
- **La hora exacta** (`clock.py`): Claude Code solo le da al agente la fecha.
- **Latido**: revisa cada 30 s que el agente siga vivo; si no, el contenedor se reinicia.
- **Mensajes enriquecidos**: tablas, imágenes y HTML en Telegram. Si no se pueden activar, Telegram sigue funcionando normal.
- **Reglas de seguridad básicas**: reglas oficiales de Claude Code (managed settings) y una revisión que evita que el agente abra direcciones de la red interna. Son una red de protección extra, no una garantía.
- **Lista de salida a internet (opcional, apagada)**: si tú la activas (`KERNEL_FIREWALL=1`), el agente solo puede conectarse a los sitios de la lista. Viene **apagada** por defecto.

## Qué NO promete

- **No es un producto de seguridad.** Nada de lo que hay aquí garantiza que el agente no se equivoque, no sea engañado o no cause daños.
- **No garantiza disponibilidad** ni que funcione sin errores con cada versión nueva de Claude Code o de Telegram.
- **No reemplaza tus respaldos** ni tu revisión de lo que el agente hace en tus sistemas.

## Cómo actúa el agente

El agente corre con `--dangerously-skip-permissions`: **actúa sin pedirte permiso** en cada paso. Esto es **decisión tuya** como cliente, para que pueda trabajar solo las 24 horas. Por eso te recomendamos darle acceso de solo lectura a tus sistemas hasta que decidas lo contrario, y usar claves con permisos limitados.

## Licencia

El software se entrega **"TAL CUAL" (AS IS)**, sin garantías de ningún tipo, bajo la licencia **Apache 2.0** (ver [`LICENSE`](../LICENSE)).
