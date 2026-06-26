"""Setzt/ändert das Website-Passwort (Netlify-Env SITE_PASSWORD) — lokal vom PC.

  python scripts/set_password.py "meinGeheimesPasswort"
  python scripts/set_password.py "pass" --user lukas      # optional anderer Benutzername

Voraussetzung (einmalig): Netlify-CLI + Verknüpfung
  npm install -g netlify-cli
  netlify login
  netlify link            # im Projektordner die Site wählen

Das neue Passwort gilt ab dem nächsten Deploy. Sofort aktiv machen:
  python scripts/build_site.py --deploy
(Der tägliche Auto-Lauf übernimmt es ohnehin.)
"""
from __future__ import annotations

import os
import subprocess
import sys


def main() -> None:
    args = [a for a in sys.argv[1:]]
    user = None
    if "--user" in args:
        i = args.index("--user")
        user = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    if not args:
        print(__doc__)
        raise SystemExit(2)
    password = args[0]
    npx = "npx.cmd" if os.name == "nt" else "npx"

    def env_set(key: str, value: str) -> None:
        subprocess.check_call([npx, "--yes", "netlify-cli", "env:set", key, value])

    env_set("SITE_PASSWORD", password)
    if user:
        env_set("SITE_USER", user)
    print("\n[OK] Passwort gesetzt. Aktiv ab dem nächsten Deploy "
          "(z. B. `python scripts/build_site.py --deploy`).")


if __name__ == "__main__":
    main()
