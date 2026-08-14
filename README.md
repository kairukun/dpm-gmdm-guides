# Dossani Paradise Management — GM/DM Guides

Internal training guides for Dossani Paradise Management restaurants.

## GitHub Pages preview

https://kairukun.github.io/dpm-gmdm-guides/

The Pages URL is a static preview of the same frontend in this repository. It
shows the email sign-in screen and editor entry points, but GitHub Pages cannot
run `server.js`, so authentication and saving are unavailable there.

## Run the complete application

```bash
npm install
npm start
```

Then open http://127.0.0.1:8899 and sign in with an editor account to change
guides. This is the same application that should be deployed when the site is
ready to go live.

### Adding guides and categories

After signing in:

- Use **New guide** in the top bar, or **Add guide** on a category/system.
- Choose an existing category, or create a new category / subcategory.
- The new guide opens in the editor with one starter step so you can fill it in.

Guide metadata lives in `site-guides.json` and content in `guide-content/`. Saving
rebuilds the HTML pages automatically.

## Production deployment

Deploy the repository to a Node.js host using:

- Build command: `npm install`
- Start command: `npm start`
- Health check: `/api/health`
- Environment: set a strong `SESSION_SECRET`

The server honors the host's `PORT` variable and listens on `0.0.0.0`. Do not
use GitHub Pages as the final host if online sign-in and editing are required.
Because edits update files in `guide-content/` and rebuild the site on disk,
the final host must provide persistent storage; otherwise edits can disappear
when the service restarts or redeploys.
