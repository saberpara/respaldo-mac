#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mac_backup.py — Inventario + backup antes de formatear macOS.

FASE 1 (relevamiento):
  - Apps (/Applications, ~/Applications) con versión y origen (App Store / brew cask / manual)
  - Herramientas: brew, node, npm, yarn, pnpm, java, gradle, mvn, python, pyenv, docker, flutter, etc.
  - Inventarios: Brewfile, globals de npm/nvm, pip/pipx/conda, sdkman, JDKs, extensiones VS Code/Cursor, crontab...
  - Repos git: remotos, rama, cambios sin commit, commits sin push, stash, ramas sin upstream, SIN REMOTO
  - Archivos sensibles (.env, .properties, gradle, keystore/jks, google-services.json, plist de Google,
    certificados, credenciales) + archivos IGNORADOS por git (excepto node_modules, build, etc.)
FASE 2 (copia, previa confirmación):
  - archivos/          -> árbol espejo relativo a ~ (para restaurar con rsync)
  - inventario/, reporte_<fecha>.md, reporte.json, manifest.csv, checksums.sha256, clonar_repos.sh

  - También: perfiles de Chrome/Brave/Edge/Firefox, historial de terminal y redes Wi-Fi (claves con --wifi-claves)
  - Cada archivo copiado se verifica con SHA-256 y --verificar CARPETA revisa el backup completo

Uso:
  python3 mac_backup.py --solo-reporte
  python3 mac_backup.py --dest /Volumes/Externo/backup_mac
  python3 mac_backup.py --roots ~/Proyectos ~/dev --max-mb 100 --yes
"""
import argparse
import csv
import fnmatch
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HOME = Path.home().resolve()
SCRIPT_DIR = Path(__file__).resolve().parent
RUTAS_EXTRA = SCRIPT_DIR / "rutas_extra.txt"
TS = datetime.now().strftime("%Y%m%d_%H%M")

# Carpetas pesadas / regenerables: no se recorren ni se copian
PRUNE_DIRS = {
    "node_modules", ".gradle", "build", "dist", ".next", ".nuxt", ".output", "Pods", "DerivedData",
    "venv", ".venv", "__pycache__", "target", ".dart_tool", ".pub-cache", ".cache", ".npm", ".yarn",
    ".pnpm-store", ".terraform", "vendor", "coverage", ".expo", ".turbo", ".parcel-cache", ".angular",
    "bower_components", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages", ".cxx",
    "intermediates", ".svelte-kit", ".vercel", ".serverless", ".git",
}

# Rutas relativas a ~ que no se recorren (los archivos importantes de acá van por DOTFILES)
HOME_PRUNE = {
    "Library", "Applications", ".Trash", "Pictures", "Music", "Movies", "Public",
    ".nvm", ".pyenv", ".sdkman", ".rustup", ".cargo", ".m2", ".gradle", ".npm", ".cache", ".docker",
    ".android", ".cocoapods", ".pub-cache", ".vscode", ".cursor", ".local", ".conda", "miniconda3",
    "anaconda3", ".oh-my-zsh", ".expo", ".bun", ".deno", ".volta", ".orbstack", "OrbStack", ".colima",
    ".lima", "go/pkg", "VirtualBox VMs", "Parallels", "Google Drive", "OneDrive", "Dropbox", ".Trash",
    ".vscode-server", ".gem", ".kotlin", ".konan", ".flutter", "flutter", ".config/gcloud/logs",
}

# Archivos sensibles / de configuración (se copian aunque estén trackeados).
# (patrones, categoría, qué es / qué puede tener). El orden importa: un archivo cuenta en el primer grupo que coincide.
SENSIBLES_INFO = [
    ((".env", ".env.*", "*.env", "env.*.json"), "Variables de entorno",
     "Config de apps con API keys, tokens, URLs y credenciales de base de datos o de terceros (Stripe, AWS, Firebase...)."),
    (("*.properties", "*.gradle", "*.gradle.kts"), "Properties y Gradle",
     "Config de Java/Android/Gradle: `local.properties` (ruta del SDK), `gradle.properties` y signing configs con "
     "contraseñas de keystore, repositorios Maven con credenciales."),
    (("*.keystore", "*.jks"), "Keystores de firma de apps",
     "Almacenes de claves Java/Android para firmar APK/AAB. Si se pierden no se puede actualizar una app ya publicada."),
    (("*.p12", "*.pfx", "*.pkcs12"), "Certificados con clave privada (firma digital)",
     "Contenedor PKCS#12 con certificado + clave privada, protegido por contraseña. Se usa para firma digital de PDF y "
     "documentos, certificados de cliente y firma de código (Apple/Windows)."),
    (("*.pem", "*.key", "*.ppk", "*.pvk", "*.pub", "id_rsa*", "id_ed25519*", "id_ecdsa*", "id_dsa*", "*_rsa", "*_ed25519"),
     "Claves privadas y accesos a servidores",
     "Claves SSH/TLS para entrar a servidores (VPS, EC2, GitHub), claves PuTTY y llaves de firma. "
     "`*.pub` son las claves públicas SSH (pueden traer algún falso positivo)."),
    (("*.cer", "*.crt", "*.cert", "*.der", "*.p7b", "*.p7c", "*.p7s", "*.spc", "*.csr", "*.crl"),
     "Certificados públicos y firmas",
     "Certificados X.509, cadenas de confianza, solicitudes (CSR) y firmas separadas (`.p7s`). Son parte de la firma "
     "digital de PDF; sin la clave privada (`.p12`/`.pfx`) no alcanzan para firmar."),
    (("*.gpg", "*.pgp", "*.asc", "*.sig"), "Claves y firmas GPG/PGP",
     "Claves exportadas, archivos cifrados o firmas para firmar commits/correos y verificar descargas."),
    (("*.mobileprovision", "*.provisionprofile", "*.p8"), "Apple: provisioning y APNs",
     "Perfiles de aprovisionamiento iOS/macOS y claves `.p8` de APNs, App Store Connect o Sign in with Apple."),
    (("google-services.json", "googleservice-info.plist", "*firebase*.json", ".firebaserc"), "Config de Firebase/Google",
     "IDs de proyecto y API keys de Firebase para Android/iOS; en `*firebase*.json` puede haber reglas o credenciales."),
    (("*service-account*.json", "*serviceaccount*.json", "*credentials*.json", "client_secret*.json", "*.googleusercontent.com.json"),
     "Service accounts y credenciales cloud",
     "Claves de cuentas de servicio (GCP/Firebase) y client secrets de OAuth: acceso programático a servicios en la nube."),
    ((".npmrc", ".yarnrc", ".yarnrc.yml"), "Tokens de gestores de paquetes",
     "Tokens de registros npm/GitHub Packages y registros privados."),
    (("secrets.*", "*.secret", "*.secrets", "*.local.json", "*.local.yml", "*.local.yaml", "settings.local.*", "config.local.*"),
     "Secretos y config local",
     "Archivos de secretos o config específica de tu máquina que normalmente no se versiona."),
    (("application*.yml", "application*.yaml", "appsettings*.json"), "Config de apps (Spring/.NET)",
     "Cadenas de conexión a BD, puertos y credenciales según el perfil (dev/prod)."),
    ((".pgpass", ".htpasswd", "*.tfvars", "terraform.tfstate*", "docker-compose.override.yml", "*.ovpn"),
     "Infra y acceso remoto",
     "Contraseñas de Postgres/htaccess, variables y estado de Terraform (pueden traer secretos), overrides de Docker, "
     "perfiles VPN."),
    (("*.kdbx",), "Gestor de contraseñas",
     "Bases de KeePass con todas tus contraseñas."),
]
SENSITIVE = [pat for pats, _, _ in SENSIBLES_INFO for pat in pats]

# Basura que no vale la pena copiar aunque esté ignorada
NOISE = [".ds_store", "*.log", "*.pyc", "*.pyo", "*.class", "*.o", "*.tmp", "*.swp", "*.iml",
         "thumbs.db", "*.hprof", "*.dSYM", "*.apk", "*.aab", "*.ipa"]

# Dotfiles / config del usuario (archivo o carpeta, relativos a ~)
DOTFILES = [
    ".zshrc", ".zprofile", ".zshenv", ".zlogin", ".bashrc", ".bash_profile", ".profile", ".p10k.zsh",
    ".oh-my-zsh/custom", ".config/fish", ".config/starship.toml", ".gitconfig", ".gitignore_global",
    ".gitignore", ".config/git", ".config/gh", ".ssh", ".gnupg", ".aws", ".kube", ".netrc", ".pgpass",
    ".my.cnf", ".npmrc", ".yarnrc", ".condarc", ".pip/pip.conf", ".config/pip", ".pypirc",
    ".m2/settings.xml", ".m2/settings-security.xml", ".gradle/gradle.properties", ".gradle/init.gradle",
    ".gradle/init.d", ".android/debug.keystore", ".docker/config.json", ".config/gcloud",
    ".sdkman/etc/config", ".vimrc", ".tmux.conf", ".wakatime.cfg", ".editorconfig", ".huggingface/token",
    ".config/rclone", ".terraformrc", ".expo/state.json",
    "Library/Application Support/Code/User/settings.json",
    "Library/Application Support/Code/User/keybindings.json",
    "Library/Application Support/Code/User/snippets",
    "Library/Application Support/Cursor/User/settings.json",
    "Library/Application Support/Cursor/User/keybindings.json",
    "Library/Application Support/JetBrains",  # filtrado por tamaño
    "Library/Fonts",
    "Library/Application Support/Google/AndroidStudio*",  # settings, keymaps y plugins de Android Studio
]

# Historial de terminal y de herramientas de línea de comandos (relativos a ~)
HISTORIALES = [
    ".zsh_history", ".zhistory", ".bash_history", ".zsh_sessions", ".python_history", ".node_repl_history",
    ".psql_history", ".mysql_history", ".sqlite_history", ".rediscli_history", ".irb_history", ".lesshst",
    ".local/share/fish/fish_history", ".local/share/atuin",
]

# Navegadores Chromium: carpeta de datos relativa a ~
NAVEGADORES_CHROMIUM = {
    "Chrome": "Library/Application Support/Google/Chrome",
    "Brave": "Library/Application Support/BraveSoftware/Brave-Browser",
    "Edge": "Library/Application Support/Microsoft Edge",
}
# Archivos que se copian de cada perfil Chromium (sin cachés ni cookies)
CHROMIUM_PERFIL = ["Bookmarks", "Preferences", "Login Data", "Login Data For Account", "Web Data", "History"]
PROCESOS_NAVEGADOR = {"Chrome": "Google Chrome", "Brave": "Brave Browser", "Edge": "Microsoft Edge",
                      "Firefox": "firefox"}

FIREFOX_BASE = "Library/Application Support/Firefox"
# Archivos (patrones) y carpetas que se copian de cada perfil de Firefox
FIREFOX_PERFIL = [
    "places.sqlite*", "favicons.sqlite*", "formhistory.sqlite*", "permissions.sqlite*", "key4.db", "logins.json",
    "cert9.db", "pkcs11.txt", "prefs.js", "user.js", "extensions.json", "extension-settings.json",
    "extension-preferences.json", "containers.json", "handlers.json", "search.json.mozlz4", "xulstore.json",
]
FIREFOX_DIRS = ["extensions", "chrome", "bookmarkbackups"]

TOOLS = {
    "brew": ["brew", "--version"], "git": ["git", "--version"], "node": ["node", "-v"],
    "npm": ["npm", "-v"], "npx": ["npx", "-v"], "yarn": ["yarn", "-v"], "pnpm": ["pnpm", "-v"],
    "bun": ["bun", "-v"], "deno": ["deno", "--version"], "nvm (dir)": ["ls", str(HOME / ".nvm")],
    "java": ["java", "-version"], "javac": ["javac", "-version"], "gradle": ["gradle", "--version"],
    "mvn": ["mvn", "-v"], "kotlin": ["kotlin", "-version"], "python3": ["python3", "--version"],
    "pip3": ["pip3", "--version"], "pyenv": ["pyenv", "--version"], "pipx": ["pipx", "--version"],
    "uv": ["uv", "--version"], "poetry": ["poetry", "--version"], "conda": ["conda", "--version"],
    "ruby": ["ruby", "-v"], "go": ["go", "version"], "rustc": ["rustc", "--version"],
    "cargo": ["cargo", "--version"], "php": ["php", "-v"], "composer": ["composer", "--version"],
    "docker": ["docker", "--version"], "kubectl": ["kubectl", "version", "--client"],
    "terraform": ["terraform", "-version"], "aws": ["aws", "--version"], "gcloud": ["gcloud", "--version"],
    "firebase": ["firebase", "--version"], "flutter": ["flutter", "--version"], "dart": ["dart", "--version"],
    "xcodebuild": ["xcodebuild", "-version"], "pod": ["pod", "--version"], "code": ["code", "--version"],
    "cursor": ["cursor", "--version"], "psql": ["psql", "--version"], "mysql": ["mysql", "--version"],
    "redis-server": ["redis-server", "--version"], "mongod": ["mongod", "--version"],
    "eas": ["eas", "--version"], "gh": ["gh", "--version"], "claude": ["claude", "--version"],
    "ollama": ["ollama", "--version"], "mas": ["mas", "version"],
}

INVENTARIO_CMDS = {
    "brew_formulas.txt": "brew list --formula --versions",
    "brew_casks.txt": "brew list --cask --versions",
    "brew_leaves.txt": "brew leaves",
    "brew_taps.txt": "brew tap",
    "brew_services.txt": "brew services list",
    "mas_appstore.txt": "mas list",
    "npm_global.txt": "npm ls -g --depth=0",
    "pnpm_global.txt": "pnpm ls -g",
    "nvm_node_versions.txt": "ls -1 ~/.nvm/versions/node",
    "nvm_globals_por_version.txt": 'for v in ~/.nvm/versions/node/*; do echo "== $v"; ls -1 "$v/lib/node_modules"; done',
    "volta.txt": "volta list all",
    "pip_freeze.txt": "python3 -m pip freeze",
    "pip_user.txt": "python3 -m pip list --user",
    "pipx.txt": "pipx list --short",
    "uv_tools.txt": "uv tool list",
    "pyenv_versions.txt": "pyenv versions",
    "conda_envs.txt": "conda env list",
    "java_home.txt": "/usr/libexec/java_home -V",
    "jvms.txt": "ls -1 /Library/Java/JavaVirtualMachines",
    "sdkman_candidatos.txt": 'for c in ~/.sdkman/candidates/*; do echo "== $c"; ls -1 "$c"; done',
    "gems.txt": "gem list --local",
    "cargo_install.txt": "cargo install --list",
    "go_bin.txt": "ls -1 ~/go/bin",
    "vscode_extensiones.txt": "code --list-extensions --show-versions",
    "cursor_extensiones.txt": "cursor --list-extensions --show-versions",
    "android_sdk.txt": 'for d in platforms build-tools ndk cmake platform-tools emulator system-images; do '
                       '[ -d ~/Library/Android/sdk/$d ] && { echo "== $d"; ls -1 ~/Library/Android/sdk/$d; }; done; true',
    "android_sdk_instalado.txt": "~/Library/Android/sdk/cmdline-tools/latest/bin/sdkmanager --list_installed",
    "android_avds.txt": "ls -1 ~/.android/avd | grep '\\.ini$' | sed 's/\\.ini$//'",
    "xcode_version.txt": "xcodebuild -version",
    "xcode_sdks.txt": "xcodebuild -showsdks",
    "ios_runtimes.txt": "xcrun simctl list runtimes",
    "ios_simuladores.txt": "xcrun simctl list devices available",
    "ios_dispositivos_fisicos.txt": "xcrun devicectl list devices",
    "docker_images.txt": "docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}'",
    "docker_volumes.txt": "docker volume ls",
    "crontab.txt": "crontab -l",
    "launch_agents.txt": "ls -1 ~/Library/LaunchAgents",
    "fuentes_usuario.txt": "ls -1 ~/Library/Fonts",
    "etc_hosts.txt": "cat /etc/hosts",
}


# ------------------------------------------------------------------ utilidades
def run(cmd, timeout=90, shell=False):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout,
                           shell=shell, executable="/bin/bash" if shell else None,
                           stdin=subprocess.DEVNULL)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", "no encontrado", 127
    except subprocess.TimeoutExpired:
        return "", "timeout", 124
    except Exception as e:  # noqa
        return "", str(e), 1


def load_login_path():
    """Carga el PATH del shell de login (nvm, pyenv, sdkman, brew...)."""
    shell = os.environ.get("SHELL", "/bin/zsh")
    o, _, _ = run([shell, "-lic", "echo __PATH__$PATH"], timeout=25)
    m = re.search(r"__PATH__(.*)", o)
    extra = ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin"]
    base = m.group(1).strip() if m else ""
    os.environ["PATH"] = ":".join(filter(None, [base, *extra, os.environ.get("PATH", "")]))


def git(repo, *args, timeout=120):
    return run(["git", "-c", "safe.directory=*", "-C", str(repo), *args], timeout=timeout)[0]


def match_any(name, patterns):
    n = name.lower()
    return any(fnmatch.fnmatch(n, p.lower()) for p in patterns)


def rel_home(p: Path) -> str:
    try:
        return str(p.relative_to(HOME))
    except ValueError:
        return str(p)


def backup_rel(p: Path) -> Path:
    try:
        return p.relative_to(HOME)
    except ValueError:
        return Path("_raiz") / p.relative_to("/")


def human(n):
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def fsize(p):
    try:
        return p.stat().st_size
    except OSError:
        return 0


def md(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


# ------------------------------------------------------------------ fase 1
def brew_cask_apps():
    if not shutil.which("brew"):
        return {}
    o, _, _ = run(["brew", "info", "--cask", "--json=v2", "--installed"], timeout=240)
    m = {}
    try:
        for cask in json.loads(o or "{}").get("casks", []):
            for art in cask.get("artifacts", []):
                if isinstance(art, dict) and "app" in art:
                    for a in art["app"]:
                        if isinstance(a, str):
                            m[Path(a).name] = cask.get("token", "")
    except Exception:
        pass
    return m


def list_apps():
    casks = brew_cask_apps()
    seen, apps = set(), []
    for base in [Path("/Applications"), HOME / "Applications"]:
        if not base.exists():
            continue
        for app in sorted(list(base.glob("*.app")) + list(base.glob("*/*.app")), key=lambda p: p.name.lower()):
            if app in seen:
                continue
            seen.add(app)
            info = {}
            try:
                with open(app / "Contents" / "Info.plist", "rb") as fh:
                    info = plistlib.load(fh)
            except Exception:
                pass
            if (app / "Contents" / "_MASReceipt").exists():
                origen = "App Store"
            elif app.name in casks:
                origen = f"brew cask ({casks[app.name]})"
            else:
                origen = "manual"
            apps.append({
                "nombre": app.stem,
                "version": str(info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or "?"),
                "bundle_id": info.get("CFBundleIdentifier", ""),
                "origen": origen,
                "ruta": str(app),
            })
    return apps


def tool_versions():
    res = []
    for name, cmd in TOOLS.items():
        path = shutil.which(cmd[0])
        if not path or (name == "nvm (dir)" and not (HOME / ".nvm").exists()):
            continue
        if name == "nvm (dir)":
            vers = sorted(p.name for p in (HOME / ".nvm/versions/node").glob("*"))
            res.append({"herramienta": "nvm", "version": ", ".join(vers) or "?", "ruta": str(HOME / ".nvm")})
            continue
        o, e, _ = run(cmd, timeout=60)
        txt = (o + "\n" + e).strip()
        line = next((l.strip() for l in txt.splitlines() if re.search(r"\d", l)), txt[:100])
        res.append({"herramienta": name, "version": line[:140], "ruta": path})
    return res


def dump_inventario(inv_dir: Path):
    inv_dir.mkdir(parents=True, exist_ok=True)
    generados = []
    if shutil.which("brew"):
        o, e, c = run(f'brew bundle dump --file="{inv_dir / "Brewfile"}" --force', timeout=300, shell=True)
        if c == 0:
            generados.append("Brewfile")
    for fname, cmd in INVENTARIO_CMDS.items():
        o, e, c = run(cmd, timeout=180, shell=True)
        txt = "\n".join(x for x in (o, e) if x)
        if c == 0 and txt.strip():
            (inv_dir / fname).write_text(txt + "\n", encoding="utf-8")
            generados.append(fname)
    return generados


def scan(roots, skip_abs):
    repos, sensibles = set(), set()
    ndirs = 0
    for root in roots:
        root = Path(root).expanduser().resolve()
        if not root.exists():
            print(f"   ! no existe: {root}")
            continue
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            dp = Path(dirpath)
            ndirs += 1
            if ndirs % 5000 == 0:
                print(f"   ... {ndirs} carpetas, {len(repos)} repos, {len(sensibles)} sensibles", flush=True)
            if ".git" in dirnames or ".git" in filenames:
                repos.add(dp)
            keep = []
            for d in dirnames:
                full = dp / d
                if d in PRUNE_DIRS or full in skip_abs or full.is_symlink():
                    continue
                if full.is_relative_to(HOME) and rel_home(full) in HOME_PRUNE:
                    continue
                keep.append(d)
            dirnames[:] = keep
            for f in filenames:
                if match_any(f, SENSITIVE):
                    p = dp / f
                    if p.is_file() and not p.is_symlink():
                        sensibles.add(p)
    return sorted(repos), sensibles


def resumen_sensibles(sensibles):
    """Cuenta los archivos sensibles por categoría y patrón, usando el primer grupo que coincide."""
    grupos = [{"categoria": c, "descripcion": d, "cantidad": 0, "bytes": 0, "patrones": {}}
              for _, c, d in SENSIBLES_INFO]
    for p in sensibles:
        n = p.name.lower()
        for g, (pats, _, _) in zip(grupos, SENSIBLES_INFO):
            hit = next((x for x in pats if fnmatch.fnmatch(n, x.lower())), None)
            if hit:
                g["cantidad"] += 1
                g["bytes"] += fsize(p)
                g["patrones"][hit] = g["patrones"].get(hit, 0) + 1
                break
    return [g for g in grupos if g["cantidad"]]


def git_ignored_files(repo, max_files_dir=3000):
    o = git(repo, "ls-files", "-o", "-i", "--exclude-standard", "--directory", "-z", timeout=240)
    out, omitidos = [], []
    for it in filter(None, o.split("\0")):
        rel = Path(it.rstrip("/"))
        if set(rel.parts) & PRUNE_DIRS or match_any(rel.name, NOISE):
            continue
        p = repo / rel
        if p.is_symlink():
            continue
        if p.is_dir():
            files = []
            for dp, dn, fn in os.walk(p):
                dn[:] = [d for d in dn if d not in PRUNE_DIRS]
                files += [Path(dp) / f for f in fn if not match_any(f, NOISE)]
                if len(files) > max_files_dir:
                    break
            if len(files) > max_files_dir:
                omitidos.append(str(p))
            else:
                out += [f for f in files if f.is_file() and not f.is_symlink()]
        elif p.is_file():
            out.append(p)
    return out, omitidos


def repo_info(repo: Path):
    remotes = {}
    for line in git(repo, "remote", "-v").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            remotes.setdefault(parts[0], parts[1])
    status = git(repo, "status", "--porcelain").splitlines()
    sin_trackear = sum(1 for l in status if l.startswith("??"))
    modificados = len(status) - sin_trackear
    sin_push = len(git(repo, "log", "--branches", "--not", "--remotes", "--oneline").splitlines())
    stash = len(git(repo, "stash", "list").splitlines())
    ramas, ramas_sin_upstream, ramas_gone = [], [], []
    for line in git(repo, "for-each-ref", "--format=%(refname:short)\t%(upstream:short)\t%(upstream:track)",
                    "refs/heads").splitlines():
        b, up, track = (line.split("\t") + ["", "", ""])[:3]
        ramas.append(b)
        if not up:
            ramas_sin_upstream.append(b)
        elif "gone" in track:
            ramas_gone.append(b)

    problemas = []
    if not remotes:
        problemas.append("SIN REMOTO")
    if modificados:
        problemas.append(f"{modificados} modificados sin commit")
    if sin_trackear:
        problemas.append(f"{sin_trackear} sin trackear")
    if sin_push and remotes:
        problemas.append(f"{sin_push} commits sin push")
    if stash:
        problemas.append(f"{stash} stash")
    if remotes and ramas_sin_upstream:
        problemas.append(f"ramas sin upstream: {', '.join(ramas_sin_upstream[:5])}")
    if ramas_gone:
        problemas.append(f"upstream borrado: {', '.join(ramas_gone[:5])}")

    return {
        "ruta": str(repo),
        "rel": rel_home(repo),
        "rama": git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "?",
        "remotos": remotes,
        "ultimo_commit": git(repo, "log", "-1", "--format=%ci"),
        "modificados": modificados,
        "sin_trackear": sin_trackear,
        "commits_sin_push": sin_push,
        "stash": stash,
        "ramas": ramas,
        "ramas_sin_upstream": ramas_sin_upstream,
        "problemas": problemas,
        "estado": "OK" if not problemas else "; ".join(problemas),
    }


# ------------------------------------------------------------------ fase 2
def sha256_file(p, bufsize=1024 * 1024):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_file(src: Path, dest_root: Path, motivo, manifest, max_bytes):
    try:
        size = fsize(src)
        dst = dest_root / backup_rel(src)
        if size > max_bytes:
            manifest.append([str(src), "", size, motivo, f"OMITIDO > {human(max_bytes)}", ""])
            return 0
        dst.parent.mkdir(parents=True, exist_ok=True)
        sha_src = sha256_file(src)
        shutil.copy2(src, dst)
        sha_dst = sha256_file(dst)
        if sha_src != sha_dst:
            manifest.append([str(src), str(dst), size, motivo, "ERROR: checksum distinto (¿archivo en uso?)", ""])
            return 0
        manifest.append([str(src), str(dst), size, motivo, "OK", sha_dst])
        return size
    except Exception as e:
        manifest.append([str(src), "", 0, motivo, f"ERROR: {e}", ""])
        return 0


def dotfile_paths(lista=None):
    out = []
    candidatos = []
    for d in (DOTFILES if lista is None else lista):
        candidatos += sorted(HOME.glob(d)) if any(c in d for c in "*?[") else [HOME / d]
    for p in candidatos:
        if p.is_symlink() and not p.exists():
            continue
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            for dp, dn, fn in os.walk(p):
                dn[:] = [x for x in dn if x not in PRUNE_DIRS and x not in ("logs", "caches", "Caches", "log")]
                for f in fn:
                    fp = Path(dp) / f
                    if fp.is_file() and not fp.is_symlink() and not match_any(f, NOISE):
                        out.append(fp)
    return out


def historial_paths():
    return dotfile_paths(HISTORIALES)


def rutas_extra(archivo: Path):
    """Lee la lista de rutas extra (una por línea, # comenta, ~ se expande; las relativas cuentan desde ~).
    Se copian tal cual, salvo carpetas regenerables (node_modules, build, venv...; .git sí se copia) y .DS_Store.
    Devuelve [{"ruta", "existe", "archivos"}]."""
    if not archivo.is_file():
        return []
    prune = PRUNE_DIRS - {".git"}
    out = []
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        p = Path(linea).expanduser()
        p = p if p.is_absolute() else HOME / p
        archivos = []
        if p.is_file() and not p.is_symlink():
            archivos.append(p)
        elif p.is_dir():
            for dp, dn, fn in os.walk(p):
                dn[:] = [d for d in dn if d not in prune and not (Path(dp) / d).is_symlink()]
                archivos += [Path(dp) / f for f in fn
                             if f != ".DS_Store" and (Path(dp) / f).is_file() and not (Path(dp) / f).is_symlink()]
        out.append({"ruta": linea, "path": p.resolve(), "existe": p.exists(), "archivos": archivos})
    return out


def _perfiles_chromium(base: Path):
    return [d for d in sorted(base.iterdir()) if d.is_dir() and (d.name == "Default" or d.name.startswith("Profile "))]


def _nombre_perfil_chromium(base: Path, dirname):
    try:
        info = json.loads((base / "Local State").read_text(encoding="utf-8"))["profile"]["info_cache"][dirname]
        extra = " · ".join(x for x in (info.get("name"), info.get("user_name")) if x)
        return f"{dirname} ({extra})" if extra else dirname
    except Exception:
        return dirname


def navegador_paths():
    """Perfiles y archivos a copiar de Chrome/Brave/Edge/Firefox: {navegador: {perfiles, archivos}}."""
    res = {}
    for nombre, rel in NAVEGADORES_CHROMIUM.items():
        base = HOME / rel
        if not base.is_dir():
            continue
        perfiles, archivos = [], []
        if (base / "Local State").is_file():
            archivos.append(base / "Local State")
        for prof in _perfiles_chromium(base):
            perfiles.append(_nombre_perfil_chromium(base, prof.name))
            archivos += [prof / f for f in CHROMIUM_PERFIL
                         if (prof / f).is_file() and not (prof / f).is_symlink()]
        res[nombre] = {"perfiles": perfiles, "archivos": archivos}
    fx = HOME / FIREFOX_BASE
    if fx.is_dir():
        perfiles, archivos = [], [fx / f for f in ("profiles.ini", "installs.ini") if (fx / f).is_file()]
        pdir = fx / "Profiles"
        for prof in sorted(pdir.iterdir()) if pdir.is_dir() else []:
            if not prof.is_dir():
                continue
            perfiles.append(prof.name)
            for it in sorted(prof.iterdir()):
                if it.is_file() and not it.is_symlink() and match_any(it.name, FIREFOX_PERFIL):
                    archivos.append(it)
                elif it.is_dir() and it.name in FIREFOX_DIRS:
                    for dp, dn, fn in os.walk(it):
                        archivos += [Path(dp) / f for f in fn
                                     if (Path(dp) / f).is_file() and not (Path(dp) / f).is_symlink()]
        res["Firefox"] = {"perfiles": perfiles, "archivos": archivos}
    return res


def navegadores_abiertos():
    return [n for n, proc in PROCESOS_NAVEGADOR.items() if run(["pgrep", "-x", proc])[2] == 0]


def inventario_navegadores(inv_dir: Path):
    """Lista de extensiones de cada navegador (para reinstalarlas). Devuelve los archivos generados."""
    generados = []
    for nombre, rel in NAVEGADORES_CHROMIUM.items():
        base = HOME / rel
        if not base.is_dir():
            continue
        lineas = []
        for prof in _perfiles_chromium(base):
            ext = prof / "Extensions"
            if not ext.is_dir():
                continue
            lineas.append(f"== {prof.name}")
            for e in sorted(x for x in ext.iterdir() if x.is_dir()):
                nom = ""
                vers = sorted(v for v in e.iterdir() if v.is_dir())
                if vers:
                    try:
                        nom = json.loads((vers[-1] / "manifest.json").read_text(encoding="utf-8")).get("name", "")
                    except Exception:
                        pass
                lineas.append(f"{e.name}\t{'(ver en la tienda)' if not nom or nom.startswith('__MSG_') else nom}")
        if lineas:
            fname = f"{nombre.lower()}_extensiones.txt"
            (inv_dir / fname).write_text("\n".join(lineas) + "\n", encoding="utf-8")
            generados.append(fname)
    lineas = []
    for ej in sorted((HOME / FIREFOX_BASE / "Profiles").glob("*/extensions.json")):
        try:
            addons = json.loads(ej.read_text(encoding="utf-8"))["addons"]
        except Exception:
            continue
        lineas.append(f"== {ej.parent.name}")
        lineas += [f"{ad.get('id')}\t{(ad.get('defaultLocale') or {}).get('name', '')}\t"
                   f"{'activa' if ad.get('active') else 'inactiva'}"
                   for ad in addons if ad.get("type") == "extension"]
    if lineas:
        (inv_dir / "firefox_extensiones.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
        generados.append("firefox_extensiones.txt")
    return generados


def wifi_redes():
    """SSIDs de las redes Wi-Fi guardadas (no requiere contraseña)."""
    o, _, _ = run(["networksetup", "-listallhardwareports"])
    m = re.search(r"Hardware Port: (?:Wi-Fi|AirPort)\s*\nDevice: (\w+)", o)
    if not m:
        return []
    o, _, c = run(["networksetup", "-listpreferredwirelessnetworks", m.group(1)])
    if c != 0:
        return []
    return [l.strip() for l in o.splitlines() if l[:1] in ("\t", " ") and l.strip()]


def exportar_wifi_claves(redes, inv_dir: Path):
    """Pide cada clave al Llavero (macOS pide la contraseña de admin o Touch ID por red). Devuelve cuántas obtuvo."""
    print("   macOS va a pedir tu contraseña (o Touch ID) por cada red; cancelá el diálogo para saltear una.")
    filas = []
    for i, ssid in enumerate(redes, 1):
        o, e, c = run(["security", "find-generic-password", "-wa", ssid], timeout=120)
        filas.append([ssid, o if c == 0 else "", "OK" if c == 0 else f"NO OBTENIDA: {e[:80]}"])
        print(f"   [{i}/{len(redes)}] {ssid}: {filas[-1][2][:12]}", flush=True)
    fd = os.open(inv_dir / "wifi_claves.csv", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ssid", "clave", "resultado"])
        w.writerows(filas)
    return sum(1 for f in filas if f[2] == "OK")


def write_checksums(dest: Path, conocidos):
    """Escribe checksums.sha256 (compatible con `shasum -a 256 -c`) de archivos/ y postgres/."""
    n = 0
    with open(dest / "checksums.sha256", "w", encoding="utf-8") as fh:
        for sub in ("archivos", "postgres"):
            base = dest / sub
            if not base.is_dir():
                continue
            for dp, dn, fn in os.walk(base):
                dn.sort()
                for f in sorted(fn):
                    fp = Path(dp) / f
                    if fp.is_symlink() or not fp.is_file():
                        continue
                    try:
                        h = conocidos.get(str(fp)) or sha256_file(fp)
                    except OSError:
                        continue
                    fh.write(f"{h}  {fp.relative_to(dest)}\n")
                    n += 1
    return n


def verificar_backup(carpeta):
    """Recalcula los checksums de un backup y avisa de archivos faltantes o alterados. Devuelve el exit code."""
    carpeta = Path(carpeta).expanduser().resolve()
    cs = carpeta / "checksums.sha256"
    if not cs.is_file():
        print(f"No existe {cs}. Tiene que ser la carpeta de un backup que haya hecho la copia.")
        return 2
    lineas = [l for l in cs.read_text(encoding="utf-8").splitlines() if l.strip()]
    faltan, distintos, ok = [], [], 0
    print(f"Verificando {len(lineas)} archivos en {carpeta} ...")
    for i, l in enumerate(lineas, 1):
        h, _, rel = l.partition("  ")
        fp = carpeta / rel
        if not fp.is_file():
            faltan.append(rel)
        else:
            try:
                if sha256_file(fp) == h:
                    ok += 1
                else:
                    distintos.append(rel)
            except OSError as e:
                distintos.append(f"{rel} (no se pudo leer: {e})")
        if i % 1000 == 0:
            print(f"   {i}/{len(lineas)}", flush=True)
    print(f"\nOK: {ok} | alterados: {len(distintos)} | faltantes: {len(faltan)}")
    if distintos or faltan:
        detalle = [f"ALTERADO  {r}" for r in distintos] + [f"FALTANTE  {r}" for r in faltan]
        for d in detalle[:50]:
            print(f"   {d}")
        if len(detalle) > 50:
            print(f"   ... y {len(detalle) - 50} más")
        out = carpeta / f"verificacion_{TS}.txt"
        out.write_text("\n".join(detalle) + "\n", encoding="utf-8")
        print(f"Detalle completo: {out}")
        return 1
    print("✅ El backup está íntegro.")
    return 0


MOTIVOS_NOMBRE = {
    "patron-sensible": "Archivos sensibles", "ignorado-git": "Ignorados por git", "dotfile-config": "Dotfiles y configuración",
    "navegador": "Navegadores", "historial-terminal": "Historial de terminal", "ruta-extra": "Rutas extra",
}


ENTORNO_ARCHIVOS = {
    "vscode": "vscode_extensiones.txt", "cursor": "cursor_extensiones.txt",
    "xcode": "xcode_version.txt", "ios_sdks": "xcode_sdks.txt", "ios_runtimes": "ios_runtimes.txt",
    "ios_simuladores": "ios_simuladores.txt", "ios_fisicos": "ios_dispositivos_fisicos.txt",
    "android_sdk": "android_sdk.txt", "android_sdk_instalado": "android_sdk_instalado.txt",
    "android_avds": "android_avds.txt",
    "java_home": "java_home.txt", "jvms": "jvms.txt", "sdkman": "sdkman_candidatos.txt",
}
IDES = ["Xcode", "Android Studio", "Visual Studio Code", "Cursor", "IntelliJ", "PyCharm", "WebStorm", "PhpStorm",
        "GoLand", "Rider", "CLion", "DataGrip", "RubyMine", "Sublime", "Zed", "Windsurf"]


def resumen_entorno(inv_dir: Path, apps):
    """Lee los inventarios de IDEs/SDKs para mostrarlos en el reporte: {clave: [líneas]}."""
    env = {}
    for k, fname in ENTORNO_ARCHIVOS.items():
        f = inv_dir / fname
        env[k] = [l.rstrip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.is_file() else []
    env["ios_simuladores"] = [re.sub(r"\s*\([0-9A-F]{8}-[0-9A-F-]{27}\)", "", l) for l in env["ios_simuladores"]]
    fis = [l for l in env["ios_fisicos"] if "simulated" not in l]
    env["ios_fisicos"] = fis if len(fis) > 2 else []  # solo quedan encabezado y separador
    env["ides"] = [f"{a['nombre']} {a['version']}".strip() for a in apps if any(k.lower() in a["nombre"].lower() for k in IDES)]
    return env


PG_PUERTO = "5432"
PG_BASES_SQL = ("SELECT datname || '|' || pg_database_size(datname) FROM pg_database "
                "WHERE NOT datistemplate ORDER BY pg_database_size(datname) DESC")


def postgres_5432():
    """Bases de datos del servidor PostgreSQL en localhost:5432 y lo que pesa cada una (solo lectura, sin contraseña).
    Devuelve {"version", "datadir", "bases": [{"nombre", "bytes"}]} o {"error"}."""
    candidatos = [Path("/Applications/Postgres.app/Contents/Versions/latest/bin/psql"),
                  *sorted(Path("/opt/homebrew/opt").glob("postgresql*/bin/psql")),
                  *sorted(Path("/usr/local/opt").glob("postgresql*/bin/psql"))]
    psql = shutil.which("psql") or next((str(c) for c in candidatos if c.is_file()), None)
    if not psql:
        return {"error": "no se encontró `psql` (Postgres.app o Homebrew)"}
    ultimo_error = ""
    for usuario in (None, "postgres"):
        cmd = [psql, "-h", "localhost", "-p", PG_PUERTO, "-w", "-At", "-d", "postgres"] + (["-U", usuario] if usuario else [])
        o, e, c = run(cmd + ["-c", PG_BASES_SQL], timeout=30)
        if c != 0:
            ultimo_error = (e.splitlines() or ["sin respuesta"])[0]
            continue
        bases = []
        for linea in o.splitlines():
            nombre, _, tam = linea.rpartition("|")
            if nombre and tam.isdigit():
                bases.append({"nombre": nombre, "bytes": int(tam)})
        version = run(cmd + ["-c", "show server_version"], timeout=30)[0]
        datadir = run(cmd + ["-c", "show data_directory"], timeout=30)[0]  # solo superusuarios; si falla queda vacío
        return {"version": version, "datadir": datadir, "bases": bases, "psql": psql, "usuario": usuario}
    return {"error": f"no se pudo conectar a localhost:{PG_PUERTO} sin contraseña ({ultimo_error})"}


def volcar_postgres(dest: Path, pg, manifest):
    """Un pg_dump -Fc por base + roles (pg_dumpall --globals-only) en postgres/. Devuelve los bytes escritos."""
    out = dest / "postgres"
    out.mkdir(parents=True, exist_ok=True)
    bindir = Path(pg["psql"]).parent
    conn = ["-h", "localhost", "-p", PG_PUERTO, "-w"] + (["-U", pg["usuario"]] if pg["usuario"] else [])
    trabajos = [("roles y permisos (globals)", str(bindir / "pg_dumpall"), conn + ["--globals-only", "-f"], "globales.sql", None)]
    for b in pg["bases"]:
        trabajos.append((b["nombre"], str(bindir / "pg_dump"), conn + ["-Fc", "-d", b["nombre"], "-f"],
                         re.sub(r"[^\w.-]", "_", b["nombre"]) + ".dump", b["bytes"]))
    total = 0
    for i, (nombre, exe, args, fname, est) in enumerate(trabajos, 1):
        dst = out / fname
        print(f"   [{i}/{len(trabajos)}] {nombre}" + (f" (~{human(est)} en disco)" if est else ""), flush=True)
        _, e, c = run([exe, *args, str(dst)], timeout=6 * 3600)
        if c != 0:
            dst.unlink(missing_ok=True)
            manifest.append([f"postgres://localhost:{PG_PUERTO}/{nombre}", "", "", "postgres-dump",
                             f"ERROR: {(e.splitlines() or ['falló'])[-1][:120]}", ""])
            print(f"      ERROR: {(e.splitlines() or ['falló'])[-1][:120]}")
            continue
        size = fsize(dst)
        total += size
        manifest.append([f"postgres://localhost:{PG_PUERTO}/{nombre}", str(dst), size, "postgres-dump", "OK", sha256_file(dst)])
        print(f"      OK {human(size)}")
    return total


def agrupar_repos(repos):
    """Reparte los repos en grupos excluyentes, de lo más urgente a lo más tranquilo."""
    sin_remoto = [r for r in repos if not r["remotos"]]
    con = [r for r in repos if r["remotos"]]
    falta_commit_push = [r for r in con if r["modificados"] or r["sin_trackear"] or r["commits_sin_push"]]
    ids = {id(r) for r in falta_commit_push}
    otros = [r for r in con if id(r) not in ids and r["problemas"]]
    ids |= {id(r) for r in otros}
    al_dia = [r for r in con if id(r) not in ids]
    return [
        ("❌ Sin remoto", "Solo existen en esta Mac: si no los subes a un remoto (o los incluyes en `rutas_extra.txt`) se pierden al formatear.",
         sin_remoto),
        ("⚠️ Con remoto, falta commit o push",
         "Tienen cambios sin commit, archivos sin trackear o commits que no están en el remoto. Haz commit y push antes de formatear (o incluye la ruta en `rutas_extra.txt`).",
         falta_commit_push),
        ("🔸 Con remoto, otros pendientes",
         "Todo está subido, pero hay stashes, ramas sin upstream o con upstream borrado. Revísalos antes de formatear.",
         otros),
        ("✅ Con remoto y al día", "Se recuperan con `clonar_repos.sh`; no hace falta copiarlos.", al_dia),
    ]


def write_report(report_path, data):
    L = [f"# Backup Mac — {data['fecha']}", "",
         f"- Equipo: **{data['equipo']}** · macOS {data['macos']} · usuario `{data['usuario']}`",
         f"- Raíces escaneadas: {', '.join(data['roots'])}", ""]
    repos = data["repos"]
    L += ["## Resumen", "",
          f"- Apps: {len(data['apps'])}",
          f"- Herramientas detectadas: {len(data['herramientas'])}",
          f"- Repos git: {len(repos)} (" + ", ".join(
              f"{t.split(' ', 1)[1].lower()}: {len(g)}" for t, _, g in agrupar_repos(repos)) + ")",
          f"- Archivos a copiar: {data['n_archivos']} ({human(data['bytes_archivos'])})",
          f"- Archivos sensibles por patrón: {sum(g['cantidad'] for g in data['resumen_sensibles'])}", ""]

    L += ["## Archivos sensibles encontrados", "",
          "Cantidad por tipo de archivo y qué contiene o puede contener cada uno.", "",
          "| Categoría | Hallados | Tamaño | Qué es / qué puede tener |", "|---|---|---|---|"]
    for g in data["resumen_sensibles"]:
        det = ", ".join(f"`{md(k)}` ×{v}" for k, v in sorted(g["patrones"].items(), key=lambda kv: -kv[1]))
        L.append(f"| **{md(g['categoria'])}** | {g['cantidad']}: {det} | {human(g['bytes'])} | {md(g['descripcion'])} |")
    if not data["resumen_sensibles"]:
        L.append("| — | 0 | — | No se encontraron archivos sensibles por patrón |")
    L.append("")

    L += ["## Repos git", "",
          "> ⚠️ Los repos **no se copian** en el backup (solo los que estén dentro de `rutas_extra.txt`): "
          "este reporte solo avisa cuáles tienen trabajo que se perdería. Súbelos antes de formatear.", ""]
    for titulo, desc, grupo in agrupar_repos(repos):
        cubiertos = sum(1 for r in grupo if r.get("en_rutas_extra"))
        L += [f"### {titulo} ({len(grupo)})", "", desc, ""]
        if cubiertos:
            L += [f"📌 {cubiertos} de {len(grupo)} están dentro de `rutas_extra.txt` y se copian completos ahí.", ""]
        if not grupo:
            L += ["_Ninguno._", ""]
            continue
        L += ["| Repo | Rama | Remoto | Último commit | Detalle |", "|---|---|---|---|---|"]
        for r in sorted(grupo, key=lambda r: r["rel"].lower()):
            remoto = next(iter(r["remotos"].values()), "—")
            L.append(f"| `{md(r['rel'])}` | {md(r['rama'])} | {md(remoto)} | {md(r['ultimo_commit'][:10])} | "
                     f"{'📌 en rutas_extra · ' if r.get('en_rutas_extra') else ''}{md(r['estado'])} |")
        L.append("")

    L += ["## Navegadores, historial de terminal y Wi-Fi", ""]
    if data.get("navegadores_abiertos"):
        L += [f"> ⚠️ Estaban abiertos: {', '.join(data['navegadores_abiertos'])}. Cerralos antes de copiar: "
              "las bases de datos en uso pueden copiarse inconsistentes (el manifest marca los archivos con checksum distinto).", ""]
    if data.get("navegadores"):
        L += ["| Navegador | Perfiles | Archivos | Tamaño |", "|---|---|---|---|"]
        for n in data["navegadores"]:
            L.append(f"| **{md(n['nombre'])}** | {md(', '.join(n['perfiles']) or '—')} | {n['archivos']} | {human(n['bytes'])} |")
        L += ["",
              "Se copian marcadores, preferencias, historial, autocompletado, contraseñas guardadas y extensiones "
              "(Firefox), sin cachés ni cookies. La lista de extensiones queda en `inventario/*_extensiones.txt`.",
              "Las contraseñas de Chrome/Brave/Edge están cifradas con una clave del Llavero: en la Mac nueva no se "
              "pueden leer solo con el archivo. Conviene iniciar sesión con la cuenta de sincronización del navegador. "
              "Las de Firefox sí se recuperan copiando `key4.db` + `logins.json` (si no hay contraseña maestra).", ""]
    else:
        L += ["_No se encontraron perfiles de Chrome, Brave, Edge ni Firefox._", ""]
    h = data.get("historial_terminal", {"archivos": 0, "bytes": 0})
    L += [f"- Historial de terminal y de herramientas (zsh, bash, psql, mysql, python, node...): "
          f"{h['archivos']} archivos ({human(h['bytes'])})"]
    redes = data.get("wifi_redes", [])
    L += [f"- Redes Wi-Fi guardadas: {len(redes)} (lista en `inventario/wifi_redes.txt`)"]
    if data.get("wifi_claves"):
        L += [f"- Claves de Wi-Fi exportadas: {data['wifi_claves']} de {len(redes)} en `inventario/wifi_claves.csv` "
              "(texto plano, permisos 600)"]
    else:
        L += ["- Claves de Wi-Fi: no exportadas. Para guardarlas, correr con `--wifi-claves` "
              "(macOS pide la contraseña de admin por cada red)."]
    L += [""]

    L += ["## Rutas extra (`rutas_extra.txt`)", ""]
    if data.get("rutas_extra"):
        L += ["Se copian tal cual, sin límite de tamaño, salvo carpetas regenerables (node_modules, build, venv...).", "",
              "| Ruta | Archivos | Tamaño |", "|---|---|---|"]
        for e in data["rutas_extra"]:
            L.append(f"| `{md(e['ruta'])}` | " + (f"{e['archivos']} | {human(e['bytes'])} |" if e["existe"] else "⚠️ no existe | — |"))
        L.append("")
    else:
        L += ["_Sin rutas extra. Agregalas en `rutas_extra.txt` (una por línea)._", ""]

    if data["ignorados_omitidos"]:
        L += ["", "### Carpetas ignoradas NO copiadas (demasiados archivos, revisar a mano)", ""]
        L += [f"- `{rel_home(Path(p))}`" for p in data["ignorados_omitidos"]]

    L += ["", "## Herramientas", "", "| Herramienta | Versión | Ruta |", "|---|---|---|"]
    for t in data["herramientas"]:
        L.append(f"| {md(t['herramienta'])} | {md(t['version'])} | `{md(t['ruta'])}` |")

    L += ["", "## Aplicaciones", "", "| App | Versión | Origen | Bundle ID |", "|---|---|---|---|"]
    for a in data["apps"]:
        L.append(f"| {md(a['nombre'])} | {md(a['version'])} | {md(a['origen'])} | {md(a['bundle_id'])} |")

    env = data.get("entorno") or {}

    def lista(titulo, lineas, vacio="_No detectado._"):
        if not lineas:
            return [f"**{titulo}**: {vacio}", ""]
        return [f"<details><summary><b>{titulo}</b> ({len(lineas)})</summary>", "", "```", *lineas, "```", "</details>", ""]

    L += ["", "## Entorno de desarrollo", "",
          "Para reinstalar el mismo entorno. El detalle crudo está en `inventario/`.", ""]
    L += lista("IDEs y editores instalados", env.get("ides", []))
    L += lista("Extensiones de VS Code", env.get("vscode", []), "_VS Code no detectado o sin extensiones._")
    L += lista("Extensiones de Cursor", env.get("cursor", []), "_Cursor no detectado o sin extensiones._")
    L += ["### Java", ""]
    L += lista("JDKs registrados (`java_home -V`)", env.get("java_home", []), "_No se detectó ningún JDK._")
    L += lista("JDKs en `/Library/Java/JavaVirtualMachines`", env.get("jvms", []))
    L += lista("Candidatos de SDKMAN (java, gradle, maven, kotlin...)", env.get("sdkman", []), "_SDKMAN no detectado._")
    L += ["### iOS / Xcode", ""]
    L += lista("Xcode", env.get("xcode", []))
    L += lista("SDKs de Xcode (`xcodebuild -showsdks`)", env.get("ios_sdks", []))
    L += lista("Runtimes de iOS instalados (simuladores)", env.get("ios_runtimes", []))
    L += lista("Simuladores iOS disponibles", env.get("ios_simuladores", []))
    L += lista("Dispositivos iOS físicos conocidos por Xcode", env.get("ios_fisicos", []),
               "_Ninguno (o `devicectl` no disponible: requiere Xcode 15+)._")
    L += ["### Android Studio / SDK", ""]
    L += lista("Componentes en `~/Library/Android/sdk`", env.get("android_sdk", []), "_Android SDK no encontrado._")
    L += lista("Paquetes instalados (`sdkmanager --list_installed`)", env.get("android_sdk_instalado", []),
               "_`sdkmanager` no disponible (instalar cmdline-tools)._")
    L += lista("Emuladores (AVDs)", env.get("android_avds", []))
    L += ["La configuración y los plugins de Android Studio se copian como `dotfile-config` "
          "(`~/Library/Application Support/Google/AndroidStudio*`).", ""]

    pg = data.get("postgres")
    L += ["", f"## PostgreSQL (localhost:{PG_PUERTO})", ""]
    if not pg or pg.get("error"):
        L += [f"_{(pg or {}).get('error', 'No consultado')}._", ""]
    else:
        L += [f"- Versión: {md(pg['version'])}",
              f"- Directorio de datos: `{md(pg['datadir'] or '(no visible: hace falta superusuario)')}`",
              f"- Bases de datos: {len(pg['bases'])} · peso total {human(sum(b['bytes'] for b in pg['bases']))}", "",
              "| Base de datos | Tamaño |", "|---|---|"]
        L += [f"| `{md(b['nombre'])}` | {human(b['bytes'])} |" for b in pg["bases"]]
        L += ["", "Los datos de PostgreSQL **no** se copian salvo que corras con `--dump-postgres`, que hace un "
              "`pg_dump -Fc` por base y un `globales.sql` (roles) en `postgres/`. Para restaurar:", "",
              "```bash",
              "psql -h localhost -p 5432 -d postgres -f postgres/globales.sql      # roles primero",
              "createdb -h localhost -p 5432 NOMBRE",
              "pg_restore -h localhost -p 5432 -d NOMBRE postgres/NOMBRE.dump      # una base",
              "```", ""]

    L += ["", "## Inventarios generados (carpeta `inventario/`)", ""]
    L += [f"- {f}" for f in data["inventario"]]

    L += ["", "## Restaurar (manual)", "",
          "1. Homebrew: `/bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"`",
          "2. Paquetes y apps: `brew bundle --file inventario/Brewfile`",
          "3. Repos con remoto: `bash clonar_repos.sh`",
          "4. Configs/.env/keystores encima de los repos clonados: `rsync -av archivos/ ~/`",
          "5. Permisos SSH: `chmod 700 ~/.ssh && chmod 600 ~/.ssh/id_*`",
          "6. Node/Python/Java: reinstalar versiones según `inventario/` (nvm, pyenv, sdkman/JDKs)",
          "7. Wi-Fi (si se exportaron las claves): `networksetup -addpreferredwirelessnetworkatindex en0 \"SSID\" 0 WPA2 \"clave\"`",
          "8. Navegadores: cerrar el navegador antes del paso 4; en Chrome/Brave/Edge iniciar sesión para sincronizar contraseñas",
          "9. PostgreSQL (si se usó `--dump-postgres`): ver la sección PostgreSQL de este reporte",
          "10. Extensiones VS Code: `cat inventario/vscode_extensiones.txt | cut -d@ -f1 | xargs -L1 code --install-extension`",
          ""]
    t = data.get("tamanos")
    if t:
        L += ["", "## Tamaño estimado del backup (`--calcular-tamano`)", "",
              "| Concepto | Archivos | Tamaño |", "|---|---|---|"]
        for m in t["por_motivo"]:
            L.append(f"| {md(MOTIVOS_NOMBRE.get(m['motivo'], m['motivo']))} (`{m['motivo']}`) | {m['archivos']} | {human(m['bytes'])} |")
        L.append(f"| **Total estimado** | | **{human(t['total'])}** |")
        L += ["", f"- Omitidos por superar `--max-mb` (no incluidos arriba): {t['omitidos']['archivos']} archivos "
                  f"({human(t['omitidos']['bytes'])})",
              f"- Espacio libre en el destino (`{md(t['destino'])}`): {human(t['libre_destino'])} → "
              + ("✅ alcanza" if t["libre_destino"] > t["total"] else "⚠️ NO alcanza"),
              "- No incluye `inventario/`, `reporte.json`, `manifest.csv` ni `checksums.sha256` (pocos MB).", ""]
    report_path.write_text("\n".join(L), encoding="utf-8")


def write_clone_script(dest, repos):
    lines = ["#!/bin/bash", "# Clona los repos que tenían remoto, en la misma ruta relativa a ~", "set -u", ""]
    for r in sorted(repos, key=lambda r: r["rel"]):
        url = r["remotos"].get("origin") or next(iter(r["remotos"].values()), None)
        if not url:
            continue
        target = f'$HOME/{r["rel"]}'
        lines.append(f'[ -d "{target}/.git" ] || {{ mkdir -p "$(dirname "{target}")" && git clone "{url}" "{target}"; }}')
        for name, u in r["remotos"].items():
            if u != url:
                lines.append(f'git -C "{target}" remote add {name} "{u}" 2>/dev/null')
    p = dest / "clonar_repos.sh"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    p.chmod(0o755)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="Inventario + backup antes de formatear macOS")
    ap.add_argument("--dest", default=str(SCRIPT_DIR / "backup" / f"backup_mac_{TS}"),
                    help="carpeta destino (default: backup/backup_mac_<fecha> junto al script)")
    ap.add_argument("--roots", nargs="+", default=[str(HOME)], help="carpetas a escanear (default ~)")
    ap.add_argument("--exclude", nargs="*", default=[], help="carpetas a excluir")
    ap.add_argument("--max-mb", type=float, default=50, help="tamaño máximo por archivo (default 50 MB)")
    ap.add_argument("--solo-reporte", action="store_true", help="solo relevamiento, no copia")
    ap.add_argument("--yes", action="store_true", help="no pedir confirmación")
    ap.add_argument("--rutas", default=str(RUTAS_EXTRA), metavar="ARCHIVO",
                    help="lista de rutas extra a copiar tal cual (default: rutas_extra.txt junto al script)")
    ap.add_argument("--dump-postgres", action="store_true",
                    help="volcar las bases de PostgreSQL de localhost:5432 (una por una, pg_dump -Fc) a postgres/")
    ap.add_argument("--calcular-tamano", action="store_true",
                    help="agrega al final del reporte el tamaño estimado del backup por categoría")
    ap.add_argument("--wifi-claves", action="store_true",
                    help="exportar las claves de Wi-Fi del Llavero (macOS pide la contraseña por cada red)")
    ap.add_argument("--verificar", metavar="CARPETA",
                    help="verificar la integridad de un backup (checksums.sha256) y salir")
    a = ap.parse_args()

    if a.verificar:
        sys.exit(verificar_backup(a.verificar))

    if sys.version_info < (3, 9):
        sys.exit("Requiere Python 3.9+")

    dest = Path(a.dest).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    max_bytes = int(a.max_mb * 1024 * 1024)
    skip_abs = {dest} | {Path(e).expanduser().resolve() for e in a.exclude}

    print(f"Destino: {dest}\n")
    load_login_path()

    print("[1/6] Aplicaciones...")
    apps = list_apps()
    print(f"   {len(apps)} apps")

    print("[2/6] Herramientas...")
    herramientas = tool_versions()
    for t in herramientas:
        print(f"   {t['herramienta']:<14} {t['version']}")

    print("[3/6] Inventarios (brew, npm, pip, sdkman, extensiones...)...")
    inventario = dump_inventario(dest / "inventario")
    inventario += inventario_navegadores(dest / "inventario")
    redes = wifi_redes()
    if redes:
        (dest / "inventario" / "wifi_redes.txt").write_text("\n".join(redes) + "\n", encoding="utf-8")
        inventario.append("wifi_redes.txt")
    wifi_claves_n = 0
    if a.wifi_claves and redes:
        wifi_claves_n = exportar_wifi_claves(redes, dest / "inventario")
        inventario.append("wifi_claves.csv")
    entorno = resumen_entorno(dest / "inventario", apps)
    pg = postgres_5432()
    print("   PostgreSQL :5432 -> " + (pg["error"] if pg.get("error") else
          f"{len(pg['bases'])} bases ({human(sum(b['bytes'] for b in pg['bases']))})"))
    print(f"   {len(inventario)} archivos en inventario/ ({len(redes)} redes Wi-Fi)")

    print("[4/6] Escaneando carpetas (repos + archivos sensibles)...")
    repo_paths, sensibles = scan(a.roots, skip_abs)
    print(f"   {len(repo_paths)} repos, {len(sensibles)} archivos sensibles por patrón")

    print("[5/6] Analizando repos git...")
    extras = rutas_extra(Path(a.rutas).expanduser())
    repos, plan, omitidos = [], {}, []
    for p in sensibles:
        plan[p] = "patron-sensible"
    for i, rp in enumerate(repo_paths, 1):
        info = repo_info(rp)
        ign, omit = git_ignored_files(rp)
        info["ignorados"] = len(ign)
        omitidos += omit
        for f in ign:
            plan.setdefault(f, "ignorado-git")
        info["en_rutas_extra"] = any(e["existe"] and (rp == e["path"] or rp.is_relative_to(e["path"])) for e in extras)
        repos.append(info)
        flag = "⚠️ " if info["problemas"] else "✅"
        if info["en_rutas_extra"]:
            flag += "📌"
        print(f"   [{i}/{len(repo_paths)}] {flag} {info['rel']}  ->  {info['estado']}")
    for f in dotfile_paths():
        plan.setdefault(f, "dotfile-config")
    navegadores = navegador_paths()
    for info in navegadores.values():
        for f in info["archivos"]:
            plan.setdefault(f, "navegador")
    for e in extras:
        for f in e["archivos"]:
            plan[f] = "ruta-extra"  # sin límite de --max-mb: las pediste explícitamente
        print(f"   ruta extra {e['ruta']}: " + (f"{len(e['archivos'])} archivos" if e["existe"] else "NO EXISTE"))
    historial = historial_paths()
    for f in historial:
        plan.setdefault(f, "historial-terminal")
    abiertos = navegadores_abiertos()
    if abiertos:
        print(f"   ⚠️  Navegadores abiertos: {', '.join(abiertos)} (cerralos antes de copiar)")

    bytes_archivos = sum(fsize(p) for p, m in plan.items() if m == "ruta-extra" or fsize(p) <= max_bytes)
    tamanos = None
    if a.calcular_tamano:
        print("   calculando tamaños por categoría...")
        por, omit_n, omit_b = {}, 0, 0
        for pth, mot in plan.items():
            sz = fsize(pth)
            if mot != "ruta-extra" and sz > max_bytes:
                omit_n, omit_b = omit_n + 1, omit_b + sz
                continue
            d = por.setdefault(mot, [0, 0])
            d[0], d[1] = d[0] + 1, d[1] + sz
        tamanos = {
            "por_motivo": [{"motivo": k, "archivos": v[0], "bytes": v[1]}
                           for k, v in sorted(por.items(), key=lambda kv: -kv[1][1])],
            "omitidos": {"archivos": omit_n, "bytes": omit_b},
            "total": bytes_archivos,
            "libre_destino": shutil.disk_usage(dest).free, "destino": str(dest),
        }

    data = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "equipo": run(["scutil", "--get", "ComputerName"])[0],
        "macos": run(["sw_vers", "-productVersion"])[0],
        "usuario": os.environ.get("USER", ""),
        "roots": a.roots,
        "apps": apps, "herramientas": herramientas, "inventario": inventario,
        "repos": repos, "ignorados_omitidos": omitidos,
        "resumen_sensibles": resumen_sensibles(sensibles),
        "navegadores": [{"nombre": n, "perfiles": i["perfiles"], "archivos": len(i["archivos"]),
                         "bytes": sum(fsize(f) for f in i["archivos"])} for n, i in navegadores.items()],
        "navegadores_abiertos": abiertos,
        "rutas_extra": [{"ruta": e["ruta"], "existe": e["existe"], "archivos": len(e["archivos"]),
                         "bytes": sum(fsize(f) for f in e["archivos"])} for e in extras],
        "historial_terminal": {"archivos": len(historial), "bytes": sum(fsize(f) for f in historial)},
        "wifi_redes": redes, "wifi_claves": wifi_claves_n,
        "tamanos": tamanos, "entorno": entorno, "postgres": pg,
        "n_archivos": len(plan), "bytes_archivos": bytes_archivos,
        "archivos": {str(k): v for k, v in sorted(plan.items(), key=lambda x: str(x[0]))},
    }
    report_path = dest / f"reporte_{TS}.md"
    write_report(report_path, data)
    write_clone_script(dest, repos)
    (dest / "reporte.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n================ RESUMEN ================")
    print(f"Repos: {len(repos)} | con pendientes: {sum(1 for r in repos if r['problemas'])} | "
          f"sin remoto: {sum(1 for r in repos if not r['remotos'])}")
    print(f"Archivos a copiar: {len(plan)} ({human(bytes_archivos)}) — límite por archivo {human(max_bytes)}")
    sin_subir = [r for r in repos if r["problemas"] and not r.get("en_rutas_extra")]
    if sin_subir:
        print(f"⚠️  {len(sin_subir)} repos con trabajo pendiente NO se copian (ver el reporte); súbelos antes de formatear.")
    if tamanos:
        print(f"Tamaño total estimado: {human(tamanos['total'])} | libre en destino: {human(tamanos['libre_destino'])}")
    if omitidos:
        print(f"Carpetas ignoradas omitidas por tamaño: {len(omitidos)} (ver el reporte)")
    print(f"Reporte: {report_path}")

    if a.dump_postgres:
        if pg.get("error"):
            print(f"PostgreSQL: no se podrá volcar ({pg['error']})")
        else:
            print(f"PostgreSQL: se volcarán {len(pg['bases'])} bases una por una a postgres/ "
                  f"(~{human(sum(b['bytes'] for b in pg['bases']))} en disco, comprimen con -Fc)")
    if a.solo_reporte:
        print("\nModo --solo-reporte: no se copió nada." + (" (--dump-postgres se ignora)" if a.dump_postgres else ""))
        return
    if not a.yes and input("\n¿Copiar archivos ahora? [s/N] ").strip().lower() not in ("s", "si", "sí", "y"):
        print("Cancelado. El reporte quedó generado.")
        return

    print("\n[6/6] Copiando...")
    manifest = []
    files_root = dest / "archivos"
    total = 0
    for i, (src, motivo) in enumerate(sorted(plan.items(), key=lambda x: str(x[0])), 1):
        total += copy_file(src, files_root, motivo, manifest, float("inf") if motivo == "ruta-extra" else max_bytes)
        if i % 500 == 0:
            print(f"   {i}/{len(plan)} archivos ({human(total)})", flush=True)

    if a.dump_postgres and not pg.get("error"):
        print("\n   Volcando PostgreSQL...")
        total += volcar_postgres(dest, pg, manifest)
    elif a.dump_postgres:
        manifest.append(["postgres", "", "", "postgres-dump", f"ERROR: {pg['error']}", ""])

    with open(dest / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["origen", "destino", "bytes", "motivo", "resultado", "sha256"])
        w.writerows(manifest)

    print("   calculando checksums...")
    n_hash = write_checksums(dest, {m[1]: m[5] for m in manifest if m[1] and m[5]})
    print(f"   {n_hash} archivos en checksums.sha256")

    errores = sum(1 for m in manifest if not str(m[4]).startswith("OK"))
    print(f"\nListo. Copiado {human(total)} en archivos/.")
    print(f"Omitidos/errores: {errores} (ver manifest.csv)")
    print(f'\nPara verificar la integridad (conviene tras volver a conectar el disco): python3 {Path(__file__).name} --verificar "{dest}"')
    print("\n⚠️  El backup contiene claves y secretos. Para guardarlo cifrado:")
    print(f'   hdiutil create -encryption AES-256 -srcfolder "{dest}" -volname backup_mac "{dest}.dmg"')


if __name__ == "__main__":
    main()
