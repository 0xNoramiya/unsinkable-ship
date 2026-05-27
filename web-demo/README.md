# Unsinkable Ship — Web Demo

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2F0xNoramiya%2Funsinkable-ship&root-directory=web-demo&project-name=unsinkable-demo&repository-name=unsinkable-demo)


A static, client-side mirror of the `unsinkable dashboard` for judges and visitors to play with without installing anything. Pre-canned responses (sourced from a real `unsinkable demo` run) simulate the gateway. No backend.

## Run locally

Just open `index.html` in a browser. Or:

```bash
python3 -m http.server -d web-demo 8080
# then visit http://localhost:8080
```

## Deploy to Vercel

### One-shot (CLI)

```bash
npm i -g vercel              # if not installed
cd web-demo
vercel --prod                # follow prompts; pick "static" / "Other" framework
```

### Git-integrated

1. Push the repo to GitHub (already done — github.com/0xNoramiya/unsinkable-ship).
2. In Vercel: **Add New Project → Import Git Repository** → pick `unsinkable-ship`.
3. Set **Root Directory** to `web-demo`, **Framework Preset** to `Other`, leave build commands empty.
4. Deploy. Vercel hosts `index.html` directly at the assigned URL.

The `vercel.json` here only sets a couple of security headers; there's no build step.
