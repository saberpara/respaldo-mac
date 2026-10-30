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
| `--dest` | `~/Desktop/backup_mac_<fecha>` | Carpeta destino del backup |
| `--roots` | `~` | Carpetas donde buscar repos y archivos sensibles |
| `--exclude` | — | Carpetas a excluir del escaneo |
| `--max-mb` | `50` | Tamaño máximo por archivo; los más grandes se omiten y quedan en el manifest |
| `--solo-reporte` | — | Genera el reporte y los inventarios sin copiar archivos. `REPORTE.md` se guarda en `reportes/reporte_YYYYMMDD_HHMM.md` dentro de la raíz del proyecto (junto a `mac_backup.py`) en vez de en `--dest` |
| `--no-copiar-repos` | — | No copia los repos pendientes completos |
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
- Estado: ✅ OK o ⚠️ con el detalle de lo pendiente

> No hace `git fetch`. Si querés que el conteo de commits sin push sea exacto, actualizá los remotos antes de correrlo.

### Archivos sensibles y de configuración
Se buscan por nombre en todas las raíces, estén o no trackeados:

`.env*`, `*.properties`, `*.gradle`, `*.gradle.kts`, `*.keystore`, `*.jks`, `*.p12`, `*.pfx`, `*.pem`, `*.key`, `*.p8`, `*.cer`, `*.crt`, `*.mobileprovision`, `google-services.json`, `GoogleService-Info.plist`, `*service-account*.json`, `*credentials*.json`, `client_secret*.json`, `*firebase*.json`, `.npmrc`, `.yarnrc`, `secrets.*`, `*.local.json`, `application*.yml`, `appsettings*.json`, `*.tfvars`, `terraform.tfstate*`, `id_rsa*`, `*.kdbx`, entre otros.

### Archivos ignorados por git
Todo lo que el `.gitignore` de cada repo deja afuera, **excepto** carpetas regenerables (`node_modules`, `build`, `dist`, `.gradle`, `venv`, `Pods`, `target`, `.next`, etc.) y basura (`.DS_Store`, `*.log`, `*.pyc`, `*.class`, `*.apk`…).
Si una carpeta ignorada tiene más de 3000 archivos, no se copia y queda listada en el reporte para revisarla a mano.

### Dotfiles y configuración del usuario
`.zshrc`, `.zprofile`, `.bashrc`, `.p10k.zsh`, `.oh-my-zsh/custom`, `.gitconfig`, `.ssh`, `.gnupg`, `.aws`, `.kube`, `.netrc`, `.npmrc`, `.m2/settings.xml`, `.gradle/gradle.properties`, `.android/debug.keystore`, `.docker/config.json`, `.config/gcloud`, `.config/gh`, settings, keybindings y snippets de VS Code y Cursor, configuración de JetBrains, `~/Library/Fonts`, entre otros.

---

## Estructura del backup

```
backup_mac_YYYYMMDD_HHMM/
├── REPORTE.md            # resumen legible: repos, herramientas, apps, pasos de restauración
├── reporte.json          # todo el relevamiento en JSON
├── manifest.csv          # cada archivo: origen, destino, bytes, motivo, resultado
├── clonar_repos.sh       # git clone de los repos con remoto, en la misma ruta
├── inventario/           # Brewfile y listados de paquetes/versiones
├── archivos/             # árbol espejo relativo a ~ (rutas fuera de ~ van en _raiz/)
└── repos_pendientes/     # repos sin remoto o con trabajo sin subir, completos con .git
```

En `manifest.csv`, la columna `motivo` puede ser `patron-sensible`, `ignorado-git`, `dotfile-config` o `repo-pendiente`.

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
```

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
| `SENSITIVE` | Patrones de archivos sensibles a copiar |
| `NOISE` | Patrones ignorados que no vale la pena copiar |
| `DOTFILES` | Archivos y carpetas de configuración a copiar |
| `TOOLS` | Herramientas cuya versión se reporta |
| `INVENTARIO_CMDS` | Comandos cuyo output se guarda en `inventario/` |