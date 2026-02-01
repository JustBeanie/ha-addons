# Hyperion.NG (host network)

This add-on runs Hyperion.NG using the upstream image `sirfragalot/hyperion.ng` with host networking enabled.

## UI
Open: http://HOMEASSISTANT_HOST:8090/

## SSL Configuration

This add-on is configured to use Home Assistant's Let's Encrypt certificates. The certs are mounted at `/ssl/` inside the container:

- **Certificate**: `/ssl/certs/fullchain.pem`
- **Private Key**: `/ssl/privkeys/privkey.pem`

To enable HTTPS in Hyperion.NG, configure your web server with these certificate paths. The certificates will be automatically renewed by the Let's Encrypt addon.

### Prerequisites
- Home Assistant's [Let's Encrypt addon](https://github.com/home-assistant/addons/tree/master/letsencrypt) must be installed and running
- Domain must be properly configured in Home Assistant

## Configuration Options

### Ports

| Port | Service | Description |
|------|---------|-------------|
| 8090/tcp | HTTP | Hyperion Web UI |
| 19444/tcp | JSON | Hyperion JSON Server |
| 19445/tcp | Proto | Hyperion Proto Server |

### Storage

- **Hyperion Config**: `/root/.hyperion` - All Hyperion configuration and data files
- **SSL Certs**: `/ssl/` - Let's Encrypt certificates (read-only)

## Hyperion.NG Documentation

- [Hyperion.NG GitHub Repository](https://github.com/hyperion-project/hyperion.ng)
- [Hyperion.NG Documentation](https://docs.hyperion-project.org/)
- [Hyperion.NG Web UI Guide](https://docs.hyperion-project.org/en/latest/user/HyperionUI.html)
- [API Documentation](https://docs.hyperion-project.org/en/latest/developer/APIs.html)
- [Docker Hub Image](https://hub.docker.com/r/sirfragalot/hyperion.ng)

## Notes

- The addon runs with `host_network: true` for direct access to your network
- Configuration persists in the addon storage at `/root/.hyperion`
- Hyperion.NG will auto-start on Home Assistant startup

