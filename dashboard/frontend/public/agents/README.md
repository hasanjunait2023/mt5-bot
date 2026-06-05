# Agent avatars

Drop a **square** image (≥256×256, JPG) named by the agent's personality slug.
It's served at `/agents/<slug>.jpg` and shown as the 3D circular avatar on the
Agent Fleet (and anywhere AgentAvatar is used). If the file is missing, the UI
falls back to a gradient + initials — so the page always looks complete.

Current slugs (must match `avatar` in `dashboard/backend/api/fleet.py`):

| Agent | File to drop |
|-------|--------------|
| Elon Musk (MTF) | `elon-musk.jpg` |
| Warren Buffett (JTCC) | `warren-buffett.jpg` |
| George Soros (Iconic) | `george-soros.jpg` |
| Isaac Newton (Gold Scalp) | `isaac-newton.jpg` |
| Albert Einstein (GS-VP) | `albert-einstein.jpg` |
| Masayoshi Son (Asia) | `masayoshi-son.jpg` |
| Sundar Pichai (Confluence) | `sundar-pichai.jpg` |

After adding/replacing images, rebuild the frontend (`npm run build`) and redeploy
the `dist/` to the VPS. New future agents: add their `avatar` slug in fleet.py and
drop a matching `<slug>.jpg` here.
