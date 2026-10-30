# mac_backup

Script en Python para **relevar y respaldar lo importante de una Mac antes de formatearla**, y poder restaurar todo manualmente después.

Trabaja en dos fases:

1. **Relevamiento**: genera un reporte con las apps, las herramientas de desarrollo, el estado de los repos git y los archivos sensibles o ignorados por git.
2. **Copia** (con confirmación): arma una carpeta con el reporte, los inventarios, un árbol espejo de los archivos importantes y una copia completa de los repos con trabajo pendiente.

---

## Requisitos

- macOS
- Python 3.9 o superior (el que trae Xcode Command Line Tools sirve)
- Terminal con **Acceso total al disco**: *Configuración del Sistema → Privacidad y seguridad → Acceso total al disco*. Sin este permiso macOS bloquea `Documents`, `Desktop`, etc.

No usa dependencias externas, solo la librería estándar.

---

## Uso

```bash
# Solo relevamiento (no copia nada)
python3 mac_backup.py --solo-reporte

# Relevamiento + copia (muestra tamaños y pide confirmación)
python3 mac_backup.py --dest /Volumes/Externo/backup_mac

# Escanear solo tus carpetas de proyectos (más rápido)
python3 mac_backup.py --roots ~/Proyectos ~/dev --dest /Volumes/Externo/backup_mac

# Sin confirmación, con límite de 100 MB por archivo
python3 mac_backup.py --dest /Volumes/Externo/backup_mac --max-mb 100 --yes
```

### Opciones

| Opción | Default | Descripción |
|---|---|---|
| `--dest` | `backup/backup_mac_<fecha>` junto al script | Carpeta destino del backup |
| `--roots` | `~` | Carpetas donde buscar repos y archivos sensibles |
| `--exclude` | — | Carpetas a excluir del escaneo |
| `--max-mb` | `50` | Tamaño máximo por archivo; los más grandes se omiten y quedan en el manifest |
| `--solo-reporte` | — | Genera el reporte y los inventarios sin copiar archivos |
| `--no-copiar-repos` | — | No copia los repos pendientes completos |
| `--rutas` | `rutas_extra.txt` junto al script | Archivo con las rutas extra a copiar tal cual (ver más abajo) |
| `--wifi-claves` | — | Exporta las claves de las redes Wi-Fi guardadas a `inventario/wifi_claves.csv` (macOS pide la contraseña de admin o Touch ID por cada red) |
| `--verificar CARPETA` | — | No hace backup: recalcula los checksums de un backup existente y avisa de archivos alterados o faltantes |
| `--yes` | — | No pide confirmación antes de copiar |

---

## Qué releva

### Aplicaciones
`/Applications` y `~/Applications`, con nombre, versión, bundle ID y origen (**App Store**, **brew cask** o **manual**).

### Herramientas
brew, git, node, npm, yarn, pnpm, bun, deno, nvm, java, javac, gradle, mvn, kotlin, python3, pip, pyenv, pipx, uv, poetry, conda, ruby, go, rust, php, composer, docker, kubectl, terraform, aws, gcloud, firebase, flutter, dart, xcodebuild, cocoapods, VS Code, Cursor, psql, mysql, redis, mongo, eas, gh, claude, ollama, mas.

El script carga el `PATH` de tu shell de login, así detecta lo instalado con nvm, pyenv, sdkman, etc.

### Inventarios (`inventario/`)
- `Brewfile` (taps, formulas, casks, mas, extensiones de VS Code)
- Fórmulas, casks, leaves, taps y servicios de brew
- Apps de App Store (`mas list`)
- Paquetes globales de npm y pnpm, versiones de nvm y globals de cada versión, volta
- pip freeze, pip `--user`, pipx, uv tools, pyenv, entornos conda
- JDKs (`java_home -V`), candidatos de sdkman
- gems, cargo, binarios de Go
- Extensiones de VS Code y Cursor
- Android SDK (platforms, build-tools, ndk)
- Imágenes y volúmenes de Docker
- crontab, LaunchAgents, fuentes del usuario, `/etc/hosts`

### Repos git
Para cada repo encontrado registra:
- Remotos y rama actual
- Archivos modificados sin commit y archivos sin trackear
- Commits que no están en ningún remoto
- Stashes
- Ramas sin upstream y ramas cuyo upstream fue borrado
- Fecha del último commit

El reporte los agrupa en secciones, de lo más urgente a lo más tranquilo:

| Grupo | Qué incluye |
|---|---|
| ❌ Sin remoto | Solo existen en esta Mac |
| ⚠️ Con remoto, falta commit o push | Cambios sin commit, archivos sin trackear o commits que no están en el remoto |
| 🔸 Con remoto, otros pendientes | Stashes, ramas sin upstream o con upstream borrado |
| ✅ Con remoto y al día | Se recuperan con `clonar_repos.sh` |

Cada repo cae en un solo grupo, el primero que le corresponde.

> No hace `git fetch`. Si querés que el conteo de commits sin push sea exacto, actualizá los remotos antes de correrlo.

### Archivos sensibles y de configuración
Se buscan por nombre en todas las raíces, estén o no trackeados. El reporte incluye una tabla con la **cantidad hallada por patrón** (por ejemplo `.env` ×12, `*.properties` ×40) y **qué es o qué puede tener** cada tipo:

| Categoría | Patrones |
|---|---|
| Variables de entorno | `.env`, `.env.*`, `*.env` |
| Properties y Gradle | `*.properties`, `*.gradle`, `*.gradle.kts` |
| Keystores de firma de apps | `*.keystore`, `*.jks` |
| Certificados con clave privada (firma digital de PDF) | `*.p12`, `*.pfx`, `*.pkcs12` |
| Claves privadas y accesos a servidores | `*.pem`, `*.key`, `*.ppk`, `id_rsa*`, `id_ed25519*`, `id_ecdsa*`, `id_dsa*` |
| Certificados públicos y firmas | `*.cer`, `*.crt`, `*.der`, `*.p7b`, `*.p7s`, `*.spc`, `*.csr`, `*.crl` |
| Claves y firmas GPG/PGP | `*.gpg`, `*.pgp`, `*.asc`, `*.sig` |
| Apple: provisioning y APNs | `*.mobileprovision`, `*.provisionprofile`, `*.p8` |
| Firebase / Google y service accounts | `google-services.json`, `GoogleService-Info.plist`, `*service-account*.json`, `*credentials*.json`, `client_secret*.json` |
| Tokens, secretos y config local | `.npmrc`, `.yarnrc`, `secrets.*`, `*.local.json`, `application*.yml`, `appsettings*.json` |
| Infra y acceso remoto | `.pgpass`, `.htpasswd`, `*.tfvars`, `terraform.tfstate*`, `*.ovpn` |
| Gestor de contraseñas | `*.kdbx` |

La lista completa y las descripciones están en `SENSIBLES_INFO`, dentro de `mac_backup.py`.

### Navegadores, historial de terminal y Wi-Fi
- **Navegadores** (Chrome, Brave, Edge y Firefox): por perfil se copian marcadores, preferencias, historial, autocompletado y contraseñas guardadas (en Firefox también extensiones y `key4.db`/`logins.json`). No se copian cachés ni cookies. La lista de extensiones queda en `inventario/<navegador>_extensiones.txt`.
  - Las contraseñas de Chrome/Brave/Edge están cifradas con una clave del Llavero y no se pueden leer en otra Mac solo con el archivo: conviene iniciar sesión con la cuenta de sincronización del navegador.
  - **Cerrá los navegadores antes de copiar**: si están abiertos, el script avisa y las bases de datos en uso pueden quedar con checksum distinto.
- **Historial de terminal**: `.zsh_history`, `.zsh_sessions`, `.bash_history` y los de python, node, psql, mysql, sqlite, redis, irb, less, fish y atuin.
- **Wi-Fi**: la lista de redes guardadas va siempre a `inventario/wifi_redes.txt`. Las **claves** solo con `--wifi-claves`, porque macOS pide autorización por cada red. El CSV queda en texto plano con permisos 600.

### Rutas extra (`rutas_extra.txt`)
Para copiar carpetas o archivos puntuales que el relevamiento no encuentra solo (documentos, fotos, notas, un disco de datos...), copiá `rutas_extra.example.txt` como `rutas_extra.txt` (queda ignorado por git) y poné una ruta por línea:

```
# comentarios con #
~/Documents/contratos
Proyectos/cliente-x        # relativa: cuenta desde ~
/Volumes/Datos/fotos
```

- Se copian **tal cual** y **sin límite de tamaño** (`--max-mb` no aplica), con motivo `ruta-extra` en el manifest.
- No se copian las carpetas que se regeneran (`node_modules`, `build`, `dist`, `venv`, `.venv`, `__pycache__`, `target`, `Pods`, `.gradle`, `.next`, `vendor`...; es `PRUNE_DIRS`). La carpeta `.git` **sí** se copia. Tampoco `.DS_Store` ni los symlinks.
- El reporte lista cada ruta con su cantidad de archivos y tamaño, y avisa si alguna no existe.

### Archivos ignorados por git
Todo lo que el `.gitignore` de cada repo deja afuera, **excepto** carpetas regenerables (`node_modules`, `build`, `dist`, `.gradle`, `venv`, `Pods`, `target`, `.next`, etc.) y basura (`.DS_Store`, `*.log`, `*.pyc`, `*.class`, `*.apk`…).
Si una carpeta ignorada tiene más de 3000 archivos, no se copia y queda listada en el reporte para revisarla a mano.

### Dotfiles y configuración del usuario
`.zshrc`, `.zprofile`, `.bashrc`, `.p10k.zsh`, `.oh-my-zsh/custom`, `.gitconfig`, `.ssh`, `.gnupg`, `.aws`, `.kube`, `.netrc`, `.npmrc`, `.m2/settings.xml`, `.gradle/gradle.properties`, `.android/debug.keystore`, `.docker/config.json`, `.config/gcloud`, `.config/gh`, settings, keybindings y snippets de VS Code y Cursor, configuración de JetBrains, `~/Library/Fonts`, entre otros.

---

## Estructura del backup

```
backup_mac_YYYYMMDD_HHMM/
├── reporte_YYYYMMDD_HHMM.md # resumen legible: repos, herramientas, apps, pasos de restauración
├── reporte.json          # todo el relevamiento en JSON
├── manifest.csv          # cada archivo: origen, destino, bytes, motivo, resultado, sha256
├── checksums.sha256      # SHA-256 de archivos/ y repos_pendientes/ (para --verificar o `shasum -a 256 -c`)
├── clonar_repos.sh       # git clone de los repos con remoto, en la misma ruta
├── inventario/           # Brewfile y listados de paquetes/versiones
├── archivos/             # árbol espejo relativo a ~ (rutas fuera de ~ van en _raiz/)
└── repos_pendientes/     # repos sin remoto o con trabajo sin subir, completos con .git
```

En `manifest.csv`, la columna `motivo` puede ser `patron-sensible`, `ignorado-git`, `dotfile-config`, `ruta-extra`, `navegador`, `historial-terminal` o `repo-pendiente`. Cada archivo se copia y se compara su SHA-256 contra el original; si no coincide queda como `ERROR` en `resultado`.

---

## Verificar el backup

```bash
python3 mac_backup.py --verificar /Volumes/Externo/backup_mac_YYYYMMDD_HHMM
```

Recalcula el SHA-256 de cada archivo y lo compara con `checksums.sha256`. Si hay alterados o faltantes, los lista (y guarda el detalle en `verificacion_<fecha>.txt` dentro del backup) y termina con código 1. Conviene correrlo después de desconectar y volver a conectar el disco externo, así no lee desde la caché. También sirve `cd <backup> && shasum -a 256 -c checksums.sha256`.

> Los repos de `repos_pendientes/` entran en `checksums.sha256` con el hash de lo que quedó en el destino, pero no se comparan contra el original al copiarlos.

---

## Restaurar

```bash
cd /Volumes/Externo/backup_mac_YYYYMMDD_HHMM

# 1. Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Paquetes, casks y apps de App Store
brew bundle --file inventario/Brewfile

# 3. Repos con remoto (misma ruta que antes)
bash clonar_repos.sh

# 4. Repos pendientes: copiarlos a su ruta original
rsync -av repos_pendientes/ ~/

# 5. Configs, .env, keystores y dotfiles encima de los repos clonados
rsync -av archivos/ ~/

# 6. Permisos de SSH
chmod 700 ~/.ssh && chmod 600 ~/.ssh/id_*

# 7. Extensiones de VS Code
cut -d@ -f1 inventario/vscode_extensiones.txt | xargs -L1 code --install-extension

# 8. Wi-Fi (si exportaste las claves con --wifi-claves)
networksetup -addpreferredwirelessnetworkatindex en0 "NOMBRE_RED" 0 WPA2 "clave"
```

Los navegadores se restauran con el paso 5; cerralos antes. Para Chrome/Brave/Edge iniciá sesión para sincronizar las contraseñas.

Después reinstalá las versiones de Node, Python y Java según `inventario/` (nvm, pyenv, sdkman/JDKs).

> Conviene hacer el paso 5 **después** del 3 y el 4, así los `.env` y keystores caen dentro de los repos ya clonados.

---

## Seguridad

El backup contiene **claves privadas, tokens y secretos**. Guardalo cifrado:

```bash
hdiutil create -encryption AES-256 -srcfolder backup_mac_YYYYMMDD_HHMM \
  -volname backup_mac backup_mac_YYYYMMDD_HHMM.dmg
```

Después borrá la carpeta sin cifrar y no lo subas a ningún repo ni a la nube sin cifrar.

---

## Personalizar

Las listas están al principio de `mac_backup.py`:

| Constante | Para qué sirve |
|---|---|
| `PRUNE_DIRS` | Carpetas que nunca se recorren ni se copian |
| `HOME_PRUNE` | Rutas relativas a `~` que no se escanean |
| `SENSIBLES_INFO` | Patrones de archivos sensibles a copiar, con su categoría y descripción para el reporte |
| `NOISE` | Patrones ignorados que no vale la pena copiar |
| `DOTFILES` | Archivos y carpetas de configuración a copiar |
| `TOOLS` | Herramientas cuya versión se reporta |
| `INVENTARIO_CMDS` | Comandos cuyo output se guarda en `inventario/` |