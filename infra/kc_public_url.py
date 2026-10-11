"""Добавить публичный адрес стенда в redirect URI клиентов Keycloak уже запущенного стека.

Realm-файлы импортируются только при первом старте Keycloak, поэтому на стенде с существующей БД
новый домен нужно дописать в клиентов отдельно: `make kc-public PUBLIC_URL=https://fsp.prowebcraft.ru`.
Повторный запуск ничего не дублирует.
"""

import json
import subprocess
import sys

KCADM = ["docker", "compose", "exec", "-T", "keycloak", "/opt/keycloak/bin/kcadm.sh"]

# realm → (клиент, путь redirect URI относительно публичного адреса)
CLIENTS = {
    "fsp-jobs": ("fsp-jobs-web", "/*"),
    "fsp-id": ("fsp-jobs-link", "/api/fsp/link/callback"),
}


def kcadm(*args: str, stdin: str | None = None) -> str:
    return subprocess.run([*KCADM, *args], input=stdin, capture_output=True, text=True, check=True).stdout


def main(public_url: str) -> None:
    public_url = public_url.rstrip("/")
    for realm, (client_id, path) in CLIENTS.items():
        (client,) = json.loads(kcadm("get", "clients", "-r", realm, "-q", f"clientId={client_id}", "-q", "exact=true"))
        uri = public_url + path
        if uri in client["redirectUris"]:
            print(f"{realm}/{client_id}: {uri} уже есть")
            continue
        client["redirectUris"].append(uri)
        kcadm("update", f"clients/{client['id']}", "-r", realm, "-f", "-", stdin=json.dumps(client))
        print(f"{realm}/{client_id}: добавлен {uri}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith(("http://", "https://")):
        sys.exit("usage: kc_public_url.py https://fsp.prowebcraft.ru")
    main(sys.argv[1])
