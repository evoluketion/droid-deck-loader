# Droid Deck Loader

<img src="assets/icon.png" alt="" width="96">

Decky plugin that installs and updates DroidDeck Proton and DroidDeck Turnip from GitHub releases.

| Component | Source | Installed to |
|---|---|---|
| DroidDeck Proton | [Droid-Deck/DroidDeck-Proton](https://github.com/Droid-Deck/DroidDeck-Proton) `DroidDeck-Proton-*-aarch64.tar.gz` | `~/.steam/steam/compatibilitytools.d/<archive folder>` |
| DroidDeck Turnip | [Droid-Deck/Drivers](https://github.com/Droid-Deck/Drivers) `DD-Turnip-v*.zip` (the `linux/` folder) | `~/.local/share/armada/turnip/DD.Turnip.v<version>` |

Each component has its own "Allow pre-releases" toggle. Downloads are checked against the
release's `.sha512sum` / `.sha256` file before anything is installed. Older versions are left
in place so games pinned to them keep working.

## Build

    npm install
    ./scripts/package.sh      # -> out/droid-deck-loader-v<version>.zip

Install the zip from Decky's Developer settings ("Install plugin from ZIP"), or copy
`out/droid-deck-loader/` to `~/homebrew/plugins/` and restart `plugin_loader`.
