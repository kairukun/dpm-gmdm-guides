/**
 * Creates assets/editor-key.json: a GitHub token encrypted with your access code.
 *
 * Run: node make_editor_key.js
 *
 * The token never leaves this machine in readable form. The published site holds
 * only the encrypted blob, which the access code unlocks in the browser.
 */
const fs = require("fs");
const path = require("path");
const readline = require("readline");
const { execFileSync } = require("child_process");
const { webcrypto } = require("crypto");

const ROOT = __dirname;
const OUT = path.join(ROOT, "assets", "editor-key.json");
const ITERATIONS = 600000;
const MIN_CODE_LENGTH = 12;

function ask(question, { mask = false } = {}) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    if (mask) {
      // Echo nothing while typing so the code/token stays off the screen.
      const onData = (char) => {
        if (String(char) === "\r" || String(char) === "\n") return;
        readline.moveCursor(process.stdout, -1, 0);
        readline.clearLine(process.stdout, 1);
      };
      process.stdin.on("data", onData);
      rl.question(question, (answer) => {
        process.stdin.removeListener("data", onData);
        process.stdout.write("\n");
        rl.close();
        resolve(answer.trim());
      });
      return;
    }
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer.trim());
    });
  });
}

function detectRepo() {
  try {
    const url = execFileSync("git", ["remote", "get-url", "origin"], {
      cwd: ROOT,
      encoding: "utf8",
    }).trim();
    const match = url.match(/github\.com[/:]([^/]+\/[^/.]+)(?:\.git)?$/i);
    return match ? match[1] : "";
  } catch {
    return "";
  }
}

async function encrypt(token, code) {
  const enc = new TextEncoder();
  const salt = webcrypto.getRandomValues(new Uint8Array(16));
  const iv = webcrypto.getRandomValues(new Uint8Array(12));
  const baseKey = await webcrypto.subtle.importKey("raw", enc.encode(code), "PBKDF2", false, [
    "deriveKey",
  ]);
  const key = await webcrypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: ITERATIONS, hash: "SHA-256" },
    baseKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt"]
  );
  const data = await webcrypto.subtle.encrypt({ name: "AES-GCM", iv }, key, enc.encode(token));
  const b64 = (buf) => Buffer.from(buf).toString("base64");
  return { salt: b64(salt), iv: b64(iv), data: b64(data) };
}

async function checkToken(token, repo) {
  const res = await fetch(`https://api.github.com/repos/${repo}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" },
  });
  if (!res.ok) return { ok: false, reason: `GitHub returned ${res.status}` };
  const body = await res.json();
  if (!body.permissions || !body.permissions.push) {
    return { ok: false, reason: "token cannot write to this repository" };
  }
  return { ok: true };
}

async function main() {
  console.log("\nSet up the guide editor access code\n");

  // EDITOR_TOKEN / EDITOR_CODE let this run unattended; otherwise it prompts.
  const preset = { token: process.env.EDITOR_TOKEN || "", code: process.env.EDITOR_CODE || "" };
  const detected = detectRepo();
  const repoAnswer = preset.token
    ? ""
    : await ask(detected ? `Repository [${detected}]: ` : "Repository (owner/name): ");
  const repo = repoAnswer || detected;
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) throw new Error("Repository must look like owner/name");

  const branchAnswer = preset.token ? "" : await ask("Branch [main]: ");
  const branch = branchAnswer || process.env.EDITOR_BRANCH || "main";

  const token = preset.token || (await ask("GitHub token (paste, input hidden): ", { mask: true }));
  if (!token) throw new Error("A token is required");

  console.log("Checking the token...");
  const check = await checkToken(token, repo);
  if (!check.ok) throw new Error(`Token rejected: ${check.reason}`);
  console.log("Token looks good.\n");

  console.log(
    `Choose an access code of at least ${MIN_CODE_LENGTH} characters.\n` +
      "Anyone with this code can edit the guides, and because the repository is public\n" +
      "the encrypted token is visible, so pick something long and not reused elsewhere.\n"
  );
  const code = preset.code || (await ask("Access code: ", { mask: true }));
  if (code.length < MIN_CODE_LENGTH) {
    throw new Error(`Access code must be at least ${MIN_CODE_LENGTH} characters`);
  }
  if (!preset.code) {
    const confirm = await ask("Confirm access code: ", { mask: true });
    if (code !== confirm) throw new Error("The codes did not match");
  }

  const payload = {
    v: 1,
    repo,
    branch,
    iterations: ITERATIONS,
    ...(await encrypt(token, code)),
  };
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, `${JSON.stringify(payload, null, 2)}\n`, "utf8");

  console.log(`\nWrote ${path.relative(ROOT, OUT)}`);
  console.log("Publish it with:\n  git add assets/editor-key.json");
  console.log('  git commit -m "Add editor access code"');
  console.log("  git push\n");
  console.log("Then sign in on the published site with the access code.\n");
}

module.exports = { encrypt, ITERATIONS, OUT };

if (require.main === module) {
  main().catch((err) => {
    console.error(`\n${err.message}\n`);
    process.exit(1);
  });
}
