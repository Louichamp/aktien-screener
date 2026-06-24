"""Ein-Befehl-Veröffentlichung: exportiert die Daten und baut die statische Seite.

  python scripts/build_site.py                 # ohne News
  python scripts/build_site.py --with-news      # mit Live-News je Ticker (langsamer)
  python scripts/build_site.py --deploy         # zusätzlich direkt zu Netlify pushen

`--deploy` braucht einmalig die Netlify-CLI + Verknüpfung:
    npm install -g netlify-cli   (einmal)
    netlify login                (einmal)
    netlify link                 (einmal, im Projektordner -> Site wählen)
Danach veröffentlicht jeder Lauf mit --deploy direkt die Live-URL.

Ohne --deploy liegt die fertige Seite in `frontend/out/` — diesen Ordner auf
https://app.netlify.com/drop ziehen.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    argv = sys.argv[1:]
    deploy = "--deploy" in argv
    export_args = [a for a in argv if a != "--deploy"]
    py = sys.executable
    frontend = ROOT / "frontend"
    npm = "npm.cmd" if os.name == "nt" else "npm"
    npx = "npx.cmd" if os.name == "nt" else "npx"
    env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1"}

    print("» Schritt 1: Daten exportieren (export_static.py) …", flush=True)
    subprocess.check_call([py, str(ROOT / "scripts" / "export_static.py"), *export_args])

    print("» Schritt 2: Frontend statisch bauen (npm run build) …", flush=True)
    subprocess.check_call([npm, "run", "build"], cwd=str(frontend), env=env)

    out = frontend / "out"
    if deploy:
        # Vom Projekt-Root deployen, damit netlify.toml + die Edge Function
        # (Passwortschutz) in netlify/edge-functions/ mit hochgeladen werden.
        print("» Schritt 3: zu Netlify deployen (inkl. Passwortschutz-Edge-Function) …", flush=True)
        subprocess.check_call(
            [npx, "--yes", "netlify-cli", "deploy", "--prod", "--dir", "frontend/out"],
            cwd=str(ROOT), env=env)
        print("\n✅ Live deployed.")
    else:
        print(f"\n✅ Fertig. Statische Seite: {out}")
        print("   Hochladen: den Ordner 'out' auf https://app.netlify.com/drop ziehen")
        print("   oder einmalig Netlify-CLI einrichten und künftig:  build_site.py --deploy")


if __name__ == "__main__":
    main()
