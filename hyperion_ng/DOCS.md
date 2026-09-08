# Hyperion.NG

Hyperion.NG is installed from the official upstream release package into a
published multi-architecture Home Assistant app image. The app supports `amd64` and
`aarch64` Home Assistant systems and uses explicit port and device mappings so
Hyperion's native LED and capture protocols remain reachable without host
network access.

Use the **Hyperion.NG** item in the Home Assistant sidebar for the ingress UI.
Configuration is stored in `/root/.hyperion` and is included in cold backups.
The app maps Home Assistant's persistent `app_config` directory to that
path, so existing Hyperion settings are retained across app restarts and image
updates.

See [README.md](README.md) for ports, SSL configuration, and upstream links.

## License

Hyperion.NG is distributed under the MIT License. See the [upstream license](https://github.com/hyperion-project/hyperion.ng/blob/master/LICENSE).
