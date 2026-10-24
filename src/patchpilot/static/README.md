# PatchPilot dashboard (static frontend)

Plain HTML, CSS, and ES modules served by FastAPI from this folder (no build step).

## Layout

| File | Role |
| --- | --- |
| `index.html` | App shell, landmarks, module entry |
| `styles.css` | Theme tokens, layout, components |
| `js/main.js` | Bootstrap, hash routing, polling, orchestration |
| `js/api.js` | All HTTP calls and mock vs live adapter |
| `js/mock.js` | Scripted demo state and timers (`?mock=1`) |
| `js/state.js` | Single store, subscribe/render hook |
| `js/util.js` | DOM helpers (text-only insertion) |
| `js/views/*.js` | Panel renderers (fleet, run, metrics, recipes, events, demo controls) |

Network paths use relative `/api/...` URLs for FastAPI.

## Mock mode

- Add `?mock=1` to the URL for the scripted demo with no backend.
- Mock fleet includes **four** small businesses (Riverbend Food Pantry, Marco's Family Kitchen, Oak Street Community Clinic, Westside Donations Hub) on `127.0.0.1:8081`–`8084`.

### Preview all tabs

1. Open `?mock=1` and go to **Fleet** (four site cards, summary `0/4`).
2. Click **Approve & repair** on one site (or **Approve & repair all**), confirm in the drawer, and wait for mock playback.
3. Open **View run**, **Recipes**, **Metrics**, and **Event log** to see populated data.

**Full fleet story (manual):** repair **site-a** → **site-b** with **Seed incompatible candidate** enabled (rejection → revision) → **site-c** (recipe reuse from a) → **site-d** (reuse from b). Or use **Approve & repair all** and approve each site in sequence.

**Recovery demos** (activation failure — separate from staging rejection):

- `&scenario=rollback` — repair **site-a** → live rollback → **Restored (still vulnerable / unpatched)**.
- `&scenario=restorefail` — repair **site-a** → **Restoration failed** / needs human help.

If the API fails, use **Use demo data** in the banner to switch to mock mode.

## Demo controls (aside)

- **Seed incompatible candidate** — passes `seed_fault: true` on the next repair (upload-site 2M limit demo on **site-b**).
- **Reset fleet** — `POST /api/reset`; optional **Also clear recipe memory**. Disabled while the busy lock is active.

## Local preview (proposed)

From this directory:

```bash
python -m http.server 8765
```

Open `http://127.0.0.1:8765/?mock=1`. Note: without FastAPI, `/api/*` requests fail unless mock mode is on; mock mode does not require the API.

If the page looks blank or the main panel stays empty, run the server from **this** directory (not the repo root), add `?mock=1`, and check the browser developer **Console** for errors.

## Backend contract

Documented in the product task; all shapes are consumed through `js/api.js` only.
