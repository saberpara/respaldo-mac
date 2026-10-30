# AGENTS.md

Contexto del proyecto para asistentes de IA. Es la fuente única de verdad; `CLAUDE.md` solo la importa.

## Qué es

`mac_backup.py` es un script de Python que releva y respalda lo importante de una Mac antes de formatearla. Trabaja en dos fases:

1. **Relevamiento**: apps, herramientas de desarrollo, estado de repos git, archivos sensibles e ignorados por git.
2. **Copia** (con confirmación): arma una carpeta con el reporte, inventarios y un árbol espejo de archivos importantes. Los repos git no se copian: el reporte solo advierte los que tienen trabajo sin subir.

Documentación de uso, opciones, estructura del backup y pasos de restauración: ver `README.md`.

## Estructura del repo

- `mac_backup.py`: todo el código, en un único archivo.
- `README.md`: documentación para el usuario (en español).
- `LICENSE`: licencia del proyecto.
- `.gitignore`: ignora las salidas del backup y secretos.

## Comandos

```bash
# Solo relevamiento (no copia nada); es la forma segura de probar cambios.
# Todo (reporte, inventarios) va a backup/backup_mac_<fecha>/ junto al script, ignorado por git
python3 mac_backup.py --solo-reporte

# Relevamiento + copia (por defecto en backup/backup_mac_<fecha>/; --dest para otro lado)
python3 mac_backup.py --dest /ruta/destino

# Agregar al final del reporte el tamaño estimado por categoría y el espacio libre en el destino
python3 mac_backup.py --solo-reporte --calcular-tamano

# Verificar la integridad de un backup ya hecho (checksums.sha256)
python3 mac_backup.py --verificar backup/backup_mac_<fecha>

# Exportar también las claves de Wi-Fi (macOS pide autorización por red; no ejecutarlo sin que el usuario lo pida)
python3 mac_backup.py --solo-reporte --wifi-claves

# Limitar el escaneo a ciertas carpetas (más rápido)
python3 mac_backup.py --roots ~/Proyectos --solo-reporte
```

El reporte consulta (solo lectura) las bases de PostgreSQL de `localhost:5432`; no modificar ni volcar datos ahí sin que el usuario lo pida.

No hay tests, linter ni build. Requiere macOS y Python 3.9 o superior.

## Convenciones

- **Solo librería estándar.** No agregar dependencias externas.
- Compatible con Python 3.9: evitar `match`, `X | Y` en type hints en runtime y otras sintaxis más nuevas.
- Todo el texto de cara al usuario (mensajes, reporte, README, comentarios) está en **español rioplatense**. Mantenerlo así.
- `rutas_extra.txt` (ignorado por git; plantilla en `rutas_extra.example.txt`) es la lista del usuario de rutas a copiar tal cual, sin límite de tamaño y sin las carpetas de `PRUNE_DIRS` (salvo `.git`). No commitear el archivo real.
- Las listas configurables están al principio de `mac_backup.py` (`PRUNE_DIRS`, `HOME_PRUNE`, `SENSIBLES_INFO` (de ahí se deriva `SENSITIVE`; cada grupo lleva categoría y descripción para el reporte), `NOISE`, `DOTFILES`, `HISTORIALES`, `NAVEGADORES_CHROMIUM`, `FIREFOX_PERFIL`, `TOOLS`, `INVENTARIO_CMDS`). Para ampliar qué se releva o copia, editar esas constantes en vez de tocar la lógica.
- Si se cambian opciones de CLI, constantes o la estructura de salida, actualizar `README.md` en el mismo cambio.

## Seguridad (importante)

- El backup generado contiene **claves privadas, tokens y secretos**. Nunca commitear sus salidas (`backup/`, `backup_mac_*/`, `reporte_*.md`, `reporte.json`, `manifest.csv`, `inventario/`, `archivos/`, `postgres/`, etc.); ya están en `.gitignore`, no quitarlas.
- Al probar, no usar un `--dest` con datos reales dentro del repo ni pegar contenido del reporte en issues, commits o conversaciones.
- El script **no debe modificar ni borrar** nada del origen: solo lee y copia. Mantener esa garantía.
- No ejecutar la fase de copia sin que el usuario lo pida; para verificar cambios usar `--solo-reporte`.
