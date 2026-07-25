# Local HTTPS

This override runs Caddy in front of the local Docker stack and serves Folioman
at `https://localhost` using Caddy's internal development CA.

From the repository root:

```bash
docker compose -f server/docker-compose.yml \
  -f deploy/local/compose.caddy.yml up -d --build
```

Verify HTTPS without changing the host trust store:

```bash
docker cp server-caddy-1:/data/caddy/pki/authorities/local/root.crt \
  /tmp/folioman-caddy-root.crt

curl --cacert /tmp/folioman-caddy-root.crt \
  https://localhost/api/health
```

To remove the browser certificate warning on macOS, optionally trust that root
in the current user's login keychain:

```bash
security add-trusted-cert -r trustRoot \
  -k "$HOME/Library/Keychains/login.keychain-db" \
  /tmp/folioman-caddy-root.crt
```

The trust command may prompt for confirmation. It changes local certificate
trust, so remove the Folioman/Caddy root from Keychain Access when it is no
longer needed.

Use [`../hosted/`](../hosted/) instead when a public domain points at the server.
The hosted override obtains a publicly trusted certificate and does not use this
development CA.
