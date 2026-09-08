# Hyperion.NG

This app publishes a signed multi-architecture image containing the official Hyperion.NG release with the ingress-compatible web client. Explicit port mappings keep the native Hyperion services available to clients, while the web UI is available from the Home Assistant sidebar through ingress.

## UI

Use the **Hyperion.NG** item in the Home Assistant sidebar. Direct access is also available at `http://HOMEASSISTANT_HOST:8090/`.

## SSL Configuration

Home Assistant's ingress proxy terminates HTTPS for the sidebar UI. The add-on also mounts Home Assistant's SSL directory read-only at `/ssl/` for users who enable Hyperion's own HTTPS listener:

- **Certificate**: `/ssl/fullchain.pem`
- **Private Key**: `/ssl/privkey.pem`

Set these paths in Hyperion.NG's Web Configuration settings (`Certificate path` and `Private key path`) and enable its HTTPS port if native Hyperion HTTPS is required. The files are supplied by Home Assistant's certificate management and are refreshed in place.

Hyperion's native HTTPS listener requires an RSA PEM private key. The current Home Assistant Let's Encrypt/Certbot app can create ECDSA keys by default, which produces the `The provided SSL key is invalid or not supported` error. Set the Certbot app option below, renew the certificate, and then restart this add-on:

```yaml
key_type: rsa
```

If the certificate is not due for renewal, temporarily enable `force_renew: true` in the Certbot app, start it once, and then disable `force_renew` again. Home Assistant ingress does not require Hyperion's native HTTPS listener and is unaffected by this RSA requirement.

### Prerequisites
- A certificate must exist in Home Assistant's `/ssl` directory when native Hyperion HTTPS is enabled.

## Configuration Options

### Ports

| Port | Service | Description |
|------|---------|-------------|
| 8090/tcp | HTTP | Hyperion Web UI |
| 8092/tcp | HTTPS | Hyperion Web UI (when native HTTPS is enabled) |
| 19444/tcp | JSON | Hyperion JSON Server |
| 19445/tcp | Proto | Hyperion Proto Server |
| 19400/tcp | FlatBuffers | Hyperion FlatBuffers Server |

### Storage

- **Hyperion Config**: `/root/.hyperion` - All Hyperion configuration and data files
- **SSL Certs**: `/ssl/` - Home Assistant certificates (read-only)

## Hyperion.NG Documentation

- [Hyperion.NG GitHub Repository](https://github.com/hyperion-project/hyperion.ng)
- [Hyperion.NG Documentation](https://docs.hyperion-project.org/)
- [Hyperion.NG Web UI Guide](https://docs.hyperion-project.org/en/latest/user/HyperionUI.html)
- [API Documentation](https://docs.hyperion-project.org/en/latest/developer/APIs.html)
- [Hyperion.NG releases](https://github.com/hyperion-project/hyperion.ng/releases)

## Notes

- The add-on image is rebuilt by this repository when the pinned Hyperion release or app version changes
- Version 3.0.0 uses explicit port mappings instead of the host network. Review custom Hyperion ports and discovery requirements when upgrading.
- The Home Assistant ingress proxy connects to Hyperion's HTTP listener on port 8090
- Configuration persists in the app storage at `/root/.hyperion`
- Hyperion.NG will auto-start on Home Assistant startup
