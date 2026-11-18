# SpinJam branding

## Repo assets

| Path | Use |
| --- | --- |
| [`images/`](../images/) | Source pack: `icon.png`, `icon@2x.png`, `logo-1024.png`, `app-icon-square-512.png`, `spinjam-logo-source.png` |
| [`brand/`](../brand/) | Convenience copies of HA brand filenames |
| [`custom_components/spinjam/brand/`](../custom_components/spinjam/brand/) | Local integration brand images (HA 2026.3+) |
| [`custom_components/spinjam/www/spinjam-icon.png`](../custom_components/spinjam/www/spinjam-icon.png) | Served at `/spinjam/spinjam-icon.png` for Lovelace |

## Home Assistant local brand images (2026.3+)

Home Assistant can load icons from the integration itself:

```text
custom_components/spinjam/brand/
  icon.png
  icon@2x.png
  logo.png
  logo@2x.png
```

No extra manifest key is required. Local files take priority over the brands CDN.

## Older Home Assistant / brands CDN

On HA versions before local `brand/` support, submit the same PNGs to [`home-assistant/brands`](https://github.com/home-assistant/brands) under:

```text
custom_integrations/spinjam/
  icon.png
  icon@2x.png
  logo.png
  logo@2x.png
```

Do **not** use Home Assistant branded artwork. This repo does not open that brands PR automatically — submit separately when ready.

## HACS

`hacs.json` sets `"render_readme": true`, so HACS shows the README logo. `info.md` also embeds `images/logo-1024.png` for older HACS info panes.
