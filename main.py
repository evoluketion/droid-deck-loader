import asyncio
import hashlib
import json
import os
import shutil
import ssl
import time
from pathlib import Path

import aiohttp
import decky

from droid_deck.components import (
    COMPONENTS,
    PROTON,
    install_proton,
    install_turnip,
    installed,
    parse_checksum,
    pick_release,
    remove_old_proton,
    target_dir,
    version_key,
)

HOME = decky.DECKY_USER_HOME or os.path.expanduser("~")
SETTINGS_FILE = Path(decky.DECKY_PLUGIN_SETTINGS_DIR) / "settings.json"
WORK_DIR = Path(decky.DECKY_PLUGIN_RUNTIME_DIR) / "work"
API = "https://api.github.com/repos/{repo}/releases?per_page=30"
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "droid-deck-loader"}
CHUNK = 1 << 20


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class Cancelled(Exception):
    pass


class Plugin:
    async def _main(self):
        self.settings = self._load_settings()
        self.latest = {key: None for key in COMPONENTS}
        self.errors = {key: None for key in COMPONENTS}
        self.jobs = {}
        self.progress = {}
        self.cancel = set()
        self.ssl = _ssl_context()
        shutil.rmtree(WORK_DIR, ignore_errors=True)

    async def _unload(self):
        for task in self.jobs.values():
            task.cancel()

    def _load_settings(self):
        defaults = {"allow_prerelease": {key: False for key in COMPONENTS}}
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            defaults["allow_prerelease"].update(
                {k: bool(v) for k, v in data.get("allow_prerelease", {}).items() if k in COMPONENTS})
        except (OSError, ValueError, AttributeError):
            pass
        return defaults

    def _save_settings(self):
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)

    def _component_state(self, key):
        component = COMPONENTS[key]
        found = installed(component, HOME)
        current = found[0]["version"] if found else None
        latest = self.latest[key]
        return {
            "key": key,
            "label": component.label,
            "repo": component.repo,
            "target": str(target_dir(component, HOME)),
            "installed": found,
            "current": current,
            "latest": latest,
            "update_available": bool(latest) and (
                current is None or version_key(latest["version"]) > version_key(current)),
            "latest_installed": bool(latest) and any(
                version_key(i["version"]) == version_key(latest["version"]) for i in found),
            "allow_prerelease": self.settings["allow_prerelease"][key],
            "error": self.errors[key],
            "busy": key in self.jobs,
            "progress": self.progress.get(key),
        }

    async def get_state(self):
        return await asyncio.to_thread(lambda: {k: self._component_state(k) for k in COMPONENTS})

    async def set_allow_prerelease(self, key, value):
        self.settings["allow_prerelease"][key] = bool(value)
        await asyncio.to_thread(self._save_settings)
        await self._check(key)
        return await self.get_state()

    async def check_updates(self):
        await asyncio.gather(*(self._check(key) for key in COMPONENTS))
        return await self.get_state()

    async def _check(self, key):
        component = COMPONENTS[key]
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
                async with session.get(API.format(repo=component.repo), ssl=self.ssl) as resp:
                    if resp.status == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
                        raise RuntimeError("GitHub rate limit reached, try again later")
                    resp.raise_for_status()
                    releases = await resp.json()
            latest = pick_release(component, releases, self.settings["allow_prerelease"][key])
            self.latest[key] = latest
            self.errors[key] = None if latest else "No matching release found"
        except Exception as exc:
            decky.logger.warning(f"update check for {key} failed: {exc}")
            self.errors[key] = f"Update check failed: {exc}"

    async def install(self, key):
        if key in self.jobs:
            return await self.get_state()
        if not self.latest[key]:
            await self._check(key)
        release = self.latest[key]
        if not release:
            return await self.get_state()
        self.errors[key] = None
        self.cancel.discard(key)
        self.jobs[key] = asyncio.get_running_loop().create_task(self._install(key, release))
        return await self.get_state()

    async def remove_old_versions(self, key):
        if key != PROTON.key or key in self.jobs:
            return await self.get_state()
        try:
            removed = await asyncio.to_thread(remove_old_proton, HOME)
            decky.logger.info(f"removed old proton versions: {removed}")
        except Exception as exc:
            decky.logger.error(f"removing old proton versions failed: {exc}")
            self.errors[key] = f"Remove failed: {exc}"
        return await self.get_state()

    async def cancel_install(self, key):
        if key in self.jobs:
            self.cancel.add(key)
        return await self.get_state()

    async def _report(self, key, stage, done=0, total=0):
        self.progress[key] = {"stage": stage, "done": done, "total": total}
        await decky.emit("dd_progress", key, self.progress[key])

    async def _install(self, key, release):
        component = COMPONENTS[key]
        work = WORK_DIR / key
        try:
            await asyncio.to_thread(shutil.rmtree, work, True)
            work.mkdir(parents=True)
            free = shutil.disk_usage(work).free
            if release["size"] and free < release["size"] * 4:
                raise RuntimeError(
                    f"Not enough free space: need ~{release['size'] * 4 >> 20} MB, have {free >> 20} MB")
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=60)
            async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
                expected = await self._expected_checksum(session, release)
                archive = work / release["asset"]
                await self._download(session, key, release, archive, expected)
            await self._report(key, "installing")
            staging = work / "extract"
            staging.mkdir()
            if component is PROTON:
                dest = await asyncio.to_thread(install_proton, archive, staging, HOME)
            else:
                dest = await asyncio.to_thread(install_turnip, archive, staging, HOME, release["version"])
            decky.logger.info(f"installed {release['tag']} to {dest}")
            await self._report(key, "done")
        except Cancelled:
            await self._report(key, "cancelled")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            decky.logger.error(f"install of {key} failed: {exc}")
            self.errors[key] = f"Install failed: {exc}"
            await self._report(key, "error")
        finally:
            self.jobs.pop(key, None)
            self.cancel.discard(key)
            await asyncio.to_thread(shutil.rmtree, work, True)
            await decky.emit("dd_state_changed", key)

    async def _expected_checksum(self, session, release):
        for checksum in release["checksums"]:
            async with session.get(checksum["url"], ssl=self.ssl) as resp:
                resp.raise_for_status()
                text = await resp.text()
            parsed = parse_checksum(text, release["asset"])
            if parsed:
                return parsed
        if release["checksums"]:
            raise RuntimeError("Checksum file does not list the archive")
        decky.logger.warning(f"{release['tag']} has no checksum file; skipping verification")
        return None

    async def _download(self, session, key, release, archive, expected):
        digest = hashlib.new(expected[0]) if expected else None
        done, last = 0, 0.0
        async with session.get(release["url"], ssl=self.ssl) as resp:
            resp.raise_for_status()
            total = resp.content_length or release["size"]
            with archive.open("wb") as out:
                async for chunk in resp.content.iter_chunked(CHUNK):
                    if key in self.cancel:
                        raise Cancelled()
                    out.write(chunk)
                    if digest:
                        digest.update(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last > 0.5:
                        last = now
                        await self._report(key, "downloading", done, total)
        await self._report(key, "verifying", done, total)
        if digest and digest.hexdigest() != expected[1]:
            raise RuntimeError("Checksum mismatch, download was corrupted")
