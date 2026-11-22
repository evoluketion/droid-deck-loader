import json
import os
import re
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

TURNIP_LIBRARY = "libvulkan_freedreno.so"
PROTON_VDF = "compatibilitytool.vdf"


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    repo: str
    asset: re.Pattern
    tag_prefix: re.Pattern


PROTON = Component(
    key="proton",
    label="DroidDeck Proton",
    repo="Droid-Deck/DroidDeck-Proton",
    # the repo also publishes DroidDeck-Bionic builds, which are a different tool
    asset=re.compile(r"^DroidDeck-Proton-.+-aarch64\.tar\.gz$"),
    tag_prefix=re.compile(r"^DroidDeck-Proton[- ]"),
)
TURNIP = Component(
    key="turnip",
    label="DroidDeck Turnip",
    repo="Droid-Deck/Drivers",
    asset=re.compile(r"^DD-Turnip-v.+\.zip$"),
    tag_prefix=re.compile(r"^DD-Turnip-v"),
)
COMPONENTS = {c.key: c for c in (PROTON, TURNIP)}

TURNIP_FOLDER = re.compile(r"^DD\.Turnip\.v(.+)$")
SAFE_NAME = re.compile(r"^[^/:.\x00][^/:\x00]{0,99}$")


def version_key(version):
    return tuple(int(n) for n in re.findall(r"\d+", version or ""))


def display_version(component, tag):
    return component.tag_prefix.sub("", tag or "")


def proton_dir(home):
    return Path(home) / ".steam" / "steam" / "compatibilitytools.d"


def turnip_dir(home):
    return Path(home) / ".local" / "share" / "armada" / "turnip"


def target_dir(component, home):
    return proton_dir(home) if component is PROTON else turnip_dir(home)


def _proton_version(folder):
    # the "version" file reads "<timestamp> DroidDeck-Proton-11-12.8"
    try:
        parts = (folder / "version").read_text(encoding="utf-8", errors="replace").split()
    except OSError:
        parts = []
    if len(parts) >= 2 and PROTON.tag_prefix.match(parts[1]):
        return display_version(PROTON, parts[1])
    if PROTON.tag_prefix.match(folder.name):
        return display_version(PROTON, folder.name)
    return None


def installed(component, home):
    base = target_dir(component, home)
    found = []
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.is_dir():
            continue
        if component is PROTON:
            if not (entry / PROTON_VDF).is_file():
                continue
            version = _proton_version(entry)
        else:
            match = TURNIP_FOLDER.match(entry.name)
            if not match or not (entry / TURNIP_LIBRARY).is_file():
                continue
            version = match.group(1)
        if version:
            found.append({"version": version, "name": entry.name, "path": str(entry)})
    found.sort(key=lambda item: version_key(item["version"]), reverse=True)
    return found


def remove_old_proton(home):
    """Delete every DroidDeck Proton install except the newest; returns the removed folder names."""
    base = proton_dir(home).resolve()
    removed = []
    for item in installed(PROTON, home)[1:]:
        path = Path(item["path"])
        # only ever a direct child of compatibilitytools.d, never through a symlink
        if path.is_symlink() or path.resolve().parent != base:
            continue
        shutil.rmtree(path)
        removed.append(item["name"])
    return removed


def pick_release(component, releases, allow_prerelease):
    best = None
    for release in releases:
        if release.get("draft") or (release.get("prerelease") and not allow_prerelease):
            continue
        assets = release.get("assets") or []
        archive = next((a for a in assets if component.asset.match(a.get("name", ""))), None)
        if not archive:
            continue
        tag = release.get("tag_name", "")
        candidate = {
            "tag": tag,
            "version": display_version(component, tag),
            "name": release.get("name") or tag,
            "prerelease": bool(release.get("prerelease")),
            "published": release.get("published_at"),
            "page": release.get("html_url"),
            "asset": archive["name"],
            "url": archive["browser_download_url"],
            "size": archive.get("size") or 0,
            "checksums": [
                {"name": a["name"], "url": a["browser_download_url"]}
                for a in assets
                if re.search(r"\.sha(256|512)(sum)?$", a.get("name", ""))
            ],
        }
        if best is None or version_key(candidate["version"]) > version_key(best["version"]):
            best = candidate
    return best


def parse_checksum(text, asset_name):
    """Return (algorithm, hexdigest) for asset_name from a sha*sum-style file, or None."""
    entries = []
    for line in text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if not parts or not re.fullmatch(r"[0-9a-fA-F]{64}|[0-9a-fA-F]{128}", parts[0]):
            continue
        name = parts[1].lstrip("*").strip() if len(parts) > 1 else ""
        entries.append((parts[0].lower(), name))
    for digest, name in entries:
        if name == asset_name or (not name and len(entries) == 1):
            return ("sha256" if len(digest) == 64 else "sha512"), digest
    return None


def _single_root(staging):
    children = [p for p in staging.iterdir()]
    if len(children) != 1 or not children[0].is_dir():
        raise RuntimeError("Archive should contain exactly one top-level folder")
    return children[0]


def _replace(source, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    old = dest.with_name(f".{dest.name}.old")
    if old.exists():
        shutil.rmtree(old)
    if dest.exists():
        dest.rename(old)
    try:
        shutil.move(str(source), str(dest))
    except BaseException:
        if old.exists() and not dest.exists():
            old.rename(dest)
        raise
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)


def install_proton(archive, staging, home):
    with tarfile.open(archive, "r:*") as tar:
        # "data" rejects absolute paths, device nodes and links escaping the folder
        tar.extractall(staging, filter="data")
    root = _single_root(staging)
    if not (root / PROTON_VDF).is_file():
        raise RuntimeError(f"{PROTON_VDF} not found in archive")
    if not SAFE_NAME.match(root.name):
        raise RuntimeError(f"Unexpected folder name: {root.name!r}")
    dest = proton_dir(home) / root.name
    _replace(root, dest)
    return str(dest)


def install_turnip(archive, staging, home, fallback_version):
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            target = (staging / info.filename).resolve()
            if not target.is_relative_to(staging.resolve()):
                raise RuntimeError(f"Unsafe path in archive: {info.filename!r}")
        zf.extractall(staging)
    linux = staging / "linux"
    if not (linux / TURNIP_LIBRARY).is_file():
        raise RuntimeError(f"linux/{TURNIP_LIBRARY} not found in archive")
    version = fallback_version
    try:
        manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
        version = str(manifest.get("version") or version)
    except (OSError, ValueError, AttributeError):
        pass
    name = f"DD.Turnip.v{version}"
    if not SAFE_NAME.match(name) or not TURNIP_FOLDER.match(name):
        raise RuntimeError(f"Unexpected version string: {version!r}")
    for path in linux.rglob("*"):
        if path.is_file():
            os.chmod(path, 0o644)
    dest = turnip_dir(home) / name
    _replace(linux, dest)
    return str(dest)
