# Dossani Paradise Management — GM/DM Guides

Internal training guides for Dossani Paradise Management restaurants.

## Live site

https://kairukun.github.io/dpm-gmdm-guides/

## Editing on the live site with an access code

Anyone with the access code can edit guides straight from the published site: sign
in, change a guide, save, and the pages rebuild themselves about a minute later.

### One-time setup

1. Create a GitHub token at
   [Fine-grained tokens](https://github.com/settings/personal-access-tokens/new):
   - Repository access: **Only select repositories** → `dpm-gmdm-guides`
   - Permissions: **Contents → Read and write**
   - Set an expiry you're comfortable with (the token has to be replaced when it expires)
2. Run the setup script and follow the prompts:

```bash
node make_editor_key.js
```

3. Publish the file it creates:

```bash
git add assets/editor-key.json
git commit -m "Add editor access code"
git push
```

Now the sign-in page on the live site asks for the access code.

### How saving works

Saving writes the guide's content file to this repository. The **Rebuild guide pages**
GitHub Action then regenerates the HTML and commits it, which republishes the site.
Give it a minute before expecting to see changes.

### Changing or replacing the code

Rerun `node make_editor_key.js` and publish the new `assets/editor-key.json`. Do this
to change the code, or after the GitHub token expires or is revoked.

### What to know about security

The access code protects a GitHub token that can write to this repository, and because
the repository is public, the encrypted token is visible to anyone. The code is what
keeps it unusable, so use a long code, don't reuse it elsewhere, and share it only with
people who should be editing guides.

## Editing on your computer

```bash
npm install
npm start
```

Open http://127.0.0.1:8899 and sign in with an editor account (see `auth-config.json`).
Saving rebuilds the guide pages locally; commit and push to publish them.

## Rebuilding by hand

```bash
python build_site.py
```

Regenerates `index.html` and everything in `guides/` from `guide-content/*.json`.
