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
  - repos_pendientes/  -> copia completa (con .git) de repos sin remoto o con trabajo sin subir
  - inventario/, REPORTE.md, reporte.json, manifest.csv, clonar_repos.sh

Uso:
  python3 mac_backup.py --solo-reporte
  python3 mac_backup.py --dest /Volumes/Externo/backup_mac
  python3 mac_backup.py --roots ~/Proyectos ~/dev --max-mb 100 --yes
"""
import argparse
import csv
import fnmatch
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

# Archivos sensibles / de configuración (se copian aunque estén trackeados)
SENSITIVE = [
    ".env", ".env.*", "*.env", "env.*.json", "*.properties", "*.gradle", "*.gradle.kts",
    "*.keystore", "*.jks", "*.p12", "*.pfx", "*.pem", "*.key", "*.p8", "*.cer", "*.crt", "*.der",
    "*.mobileprovision", "*.provisionprofile", "google-services.json", "googleservice-info.plist",
    "*service-account*.json", "*serviceaccount*.json", "*credentials*.json", "client_secret*.json",
    "*firebase*.json", ".firebaserc", ".npmrc", ".yarnrc", ".yarnrc.yml", "secrets.*", "*.secret",
    "*.secrets", "*.local.json", "*.local.yml", "*.local.yaml", "settings.local.*", "config.local.*",
    "application*.yml", "application*.yaml", "appsettings*.json", ".htpasswd", "id_rsa*", "id_ed25519*",
    "*.ovpn", "*.kdbx", "docker-compose.override.yml", ".pgpass", "*.tfvars", "terraform.tfstate*",
]

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
]

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
    "android_sdk.txt": "ls -1 ~/Library/Android/sdk/platforms ~/Library/Android/sdk/build-tools ~/Library/Android/sdk/ndk",
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


def dir_size(p: Path):
    total = 0
    for dp, dn, fn in os.walk(p):
        dn[:] = [d for d in dn if d not in PRUNE_DIRS or d == ".git"]
        for f in fn:
            fp = Path(dp) / f
            if not fp.is_symlink():
                total += fsize(fp)
    return total


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
        # se copia completo si no tiene remoto o hay trabajo que se perdería
        "copiar_completo": bool(not remotes or modificados or sin_trackear or sin_push or stash
                                or (remotes and ramas_sin_upstream)),
    }


# ------------------------------------------------------------------ fase 2
def copy_file(src: Path, dest_root: Path, motivo, manifest, max_bytes):
    try:
        size = fsize(src)
        dst = dest_root / backup_rel(src)
        if size > max_bytes:
            manifest.append([str(src), "", size, motivo, f"OMITIDO > {human(max_bytes)}"])
            return 0
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        manifest.append([str(src), str(dst), size, motivo, "OK"])
        return size
    except Exception as e:
        manifest.append([str(src), "", 0, motivo, f"ERROR: {e}"])
        return 0


def dotfile_paths():
    out = []
    for d in DOTFILES:
        p = HOME / d
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


def write_report(report_path, data):
    L = [f"# Backup Mac — {data['fecha']}", "",
         f"- Equipo: **{data['equipo']}** · macOS {data['macos']} · usuario `{data['usuario']}`",
         f"- Raíces escaneadas: {', '.join(data['roots'])}", ""]
    repos = data["repos"]
    con_prob = [r for r in repos if r["problemas"]]
    L += ["## Resumen", "",
          f"- Apps: {len(data['apps'])}",
          f"- Herramientas detectadas: {len(data['herramientas'])}",
          f"- Repos git: {len(repos)} (con pendientes: {len(con_prob)}, sin remoto: "
          f"{sum(1 for r in repos if not r['remotos'])})",
          f"- Archivos a copiar: {data['n_archivos']} ({human(data['bytes_archivos'])})",
          f"- Repos a copiar completos: {sum(1 for r in repos if r['copiar_completo'])} "
          f"({human(data['bytes_repos'])})", ""]

    L += ["## Repos git", "", "| Repo | Rama | Remoto | Último commit | Estado |", "|---|---|---|---|---|"]
    for r in sorted(repos, key=lambda r: (not r["problemas"], r["rel"].lower())):
        remoto = next(iter(r["remotos"].values()), "—")
        estado = ("⚠️ " if r["problemas"] else "✅ ") + r["estado"]
        L.append(f"| `{md(r['rel'])}` | {md(r['rama'])} | {md(remoto)} | {md(r['ultimo_commit'][:10])} | {md(estado)} |")

    if data["ignorados_omitidos"]:
        L += ["", "### Carpetas ignoradas NO copiadas (demasiados archivos, revisar a mano)", ""]
        L += [f"- `{rel_home(Path(p))}`" for p in data["ignorados_omitidos"]]

    L += ["", "## Herramientas", "", "| Herramienta | Versión | Ruta |", "|---|---|---|"]
    for t in data["herramientas"]:
        L.append(f"| {md(t['herramienta'])} | {md(t['version'])} | `{md(t['ruta'])}` |")

    L += ["", "## Aplicaciones", "", "| App | Versión | Origen | Bundle ID |", "|---|---|---|---|"]
    for a in data["apps"]:
        L.append(f"| {md(a['nombre'])} | {md(a['version'])} | {md(a['origen'])} | {md(a['bundle_id'])} |")

    L += ["", "## Inventarios generados (carpeta `inventario/`)", ""]
    L += [f"- {f}" for f in data["inventario"]]

    L += ["", "## Restaurar (manual)", "",
          "1. Homebrew: `/bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"`",
          "2. Paquetes y apps: `brew bundle --file inventario/Brewfile`",
          "3. Repos con remoto: `bash clonar_repos.sh`",
          "4. Repos pendientes: copiar `repos_pendientes/<ruta>` a `~/<ruta>`",
          "5. Configs/.env/keystores encima de los repos clonados: `rsync -av archivos/ ~/`",
          "6. Permisos SSH: `chmod 700 ~/.ssh && chmod 600 ~/.ssh/id_*`",
          "7. Node/Python/Java: reinstalar versiones según `inventario/` (nvm, pyenv, sdkman/JDKs)",
          "8. Extensiones VS Code: `cat inventario/vscode_extensiones.txt | cut -d@ -f1 | xargs -L1 code --install-extension`",
          ""]
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
    ap.add_argument("--dest", default=str(HOME / "Desktop" / f"backup_mac_{TS}"), help="carpeta destino")
    ap.add_argument("--roots", nargs="+", default=[str(HOME)], help="carpetas a escanear (default ~)")
    ap.add_argument("--exclude", nargs="*", default=[], help="carpetas a excluir")
    ap.add_argument("--max-mb", type=float, default=50, help="tamaño máximo por archivo (default 50 MB)")
    ap.add_argument("--solo-reporte", action="store_true", help="solo relevamiento, no copia")
    ap.add_argument("--no-copiar-repos", action="store_true", help="no copiar repos pendientes completos")
    ap.add_argument("--yes", action="store_true", help="no pedir confirmación")
    a = ap.parse_args()

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
    print(f"   {len(inventario)} archivos en inventario/")

    print("[4/6] Escaneando carpetas (repos + archivos sensibles)...")
    repo_paths, sensibles = scan(a.roots, skip_abs)
    print(f"   {len(repo_paths)} repos, {len(sensibles)} archivos sensibles por patrón")

    print("[5/6] Analizando repos git...")
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
        repos.append(info)
        flag = "⚠️ " if info["problemas"] else "✅"
        print(f"   [{i}/{len(repo_paths)}] {flag} {info['rel']}  ->  {info['estado']}")
    for f in dotfile_paths():
        plan.setdefault(f, "dotfile-config")

    bytes_archivos = sum(min(fsize(p), max_bytes + 1) for p in plan if fsize(p) <= max_bytes)
    a_copiar_repos = [] if a.no_copiar_repos else [r for r in repos if r["copiar_completo"]]
    print("   calculando tamaño de repos pendientes...")
    bytes_repos = sum(dir_size(Path(r["ruta"])) for r in a_copiar_repos)

    data = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "equipo": run(["scutil", "--get", "ComputerName"])[0],
        "macos": run(["sw_vers", "-productVersion"])[0],
        "usuario": os.environ.get("USER", ""),
        "roots": a.roots,
        "apps": apps, "herramientas": herramientas, "inventario": inventario,
        "repos": repos, "ignorados_omitidos": omitidos,
        "n_archivos": len(plan), "bytes_archivos": bytes_archivos, "bytes_repos": bytes_repos,
        "archivos": {str(k): v for k, v in sorted(plan.items(), key=lambda x: str(x[0]))},
    }
    if a.solo_reporte:
        report_path = Path(__file__).resolve().parent / "reportes" / f"reporte_{TS}.md"
    else:
        report_path = dest / "REPORTE.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(report_path, data)
    write_clone_script(dest, repos)
    (dest / "reporte.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n================ RESUMEN ================")
    print(f"Repos: {len(repos)} | con pendientes: {sum(1 for r in repos if r['problemas'])} | "
          f"sin remoto: {sum(1 for r in repos if not r['remotos'])}")
    print(f"Archivos a copiar: {len(plan)} ({human(bytes_archivos)}) — límite por archivo {human(max_bytes)}")
    print(f"Repos a copiar completos: {len(a_copiar_repos)} ({human(bytes_repos)})")
    if omitidos:
        print(f"Carpetas ignoradas omitidas por tamaño: {len(omitidos)} (ver REPORTE.md)")
    print(f"Reporte: {report_path}")

    if a.solo_reporte:
        print("\nModo --solo-reporte: no se copió nada.")
        return
    if not a.yes and input("\n¿Copiar archivos ahora? [s/N] ").strip().lower() not in ("s", "si", "sí", "y"):
        print("Cancelado. El reporte quedó generado.")
        return

    print("\n[6/6] Copiando...")
    manifest = []
    files_root = dest / "archivos"
    total = 0
    for i, (src, motivo) in enumerate(sorted(plan.items(), key=lambda x: str(x[0])), 1):
        total += copy_file(src, files_root, motivo, manifest, max_bytes)
        if i % 500 == 0:
            print(f"   {i}/{len(plan)} archivos ({human(total)})", flush=True)

    for r in a_copiar_repos:
        src = Path(r["ruta"])
        dst = dest / "repos_pendientes" / backup_rel(src)
        print(f"   repo completo: {r['rel']}")
        try:
            shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(*(PRUNE_DIRS - {".git"})))
            manifest.append([str(src), str(dst), "", "repo-pendiente", "OK"])
        except shutil.Error as e:
            manifest.append([str(src), str(dst), "", "repo-pendiente", f"PARCIAL: {len(e.args[0])} errores"])
        except Exception as e:
            manifest.append([str(src), str(dst), "", "repo-pendiente", f"ERROR: {e}"])

    with open(dest / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["origen", "destino", "bytes", "motivo", "resultado"])
        w.writerows(manifest)

    errores = sum(1 for m in manifest if not str(m[4]).startswith("OK"))
    print(f"\nListo. Copiado {human(total)} en archivos/ + {len(a_copiar_repos)} repos completos.")
    print(f"Omitidos/errores: {errores} (ver manifest.csv)")
    print("\n⚠️  El backup contiene claves y secretos. Para guardarlo cifrado:")
    print(f'   hdiutil create -encryption AES-256 -srcfolder "{dest}" -volname backup_mac "{dest}.dmg"')


if __name__ == "__main__":
    main()
