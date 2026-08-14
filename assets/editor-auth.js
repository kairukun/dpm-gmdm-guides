/**
 * Access-code editing for the published (static) site.
 *
 * assets/editor-key.json holds a GitHub token encrypted with the access code.
 * The code decrypts it in the browser, and edits are written straight to the
 * repository; a GitHub Action then rebuilds the guide pages.
 */
(function () {
  var KEY_FILE = "assets/editor-key.json";
  var STORE_KEY = "dpmEditorSession";
  var API = "https://api.github.com";

  function bytesToBase64(bytes) {
    var chunk = 0x8000;
    var out = "";
    for (var i = 0; i < bytes.length; i += chunk) {
      out += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(out);
  }

  function base64ToBytes(b64) {
    var raw = atob(String(b64).replace(/\s+/g, ""));
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return bytes;
  }

  function loadKeyFile(prefix) {
    return fetch((prefix || "") + KEY_FILE, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("No access code has been set up yet.");
      return r.json();
    });
  }

  function deriveKey(code, salt, iterations) {
    var enc = new TextEncoder();
    return crypto.subtle
      .importKey("raw", enc.encode(code), "PBKDF2", false, ["deriveKey"])
      .then(function (baseKey) {
        return crypto.subtle.deriveKey(
          { name: "PBKDF2", salt: salt, iterations: iterations, hash: "SHA-256" },
          baseKey,
          { name: "AES-GCM", length: 256 },
          false,
          ["decrypt"]
        );
      });
  }

  function unlock(code, prefix) {
    if (!window.crypto || !crypto.subtle) {
      return Promise.reject(new Error("This browser cannot unlock the editor."));
    }
    return loadKeyFile(prefix).then(function (keyFile) {
      return deriveKey(code, base64ToBytes(keyFile.salt), keyFile.iterations || 600000)
        .then(function (key) {
          return crypto.subtle.decrypt(
            { name: "AES-GCM", iv: base64ToBytes(keyFile.iv) },
            key,
            base64ToBytes(keyFile.data)
          );
        })
        .then(function (plain) {
          return {
            token: new TextDecoder().decode(plain),
            repo: keyFile.repo,
            branch: keyFile.branch || "main",
          };
        })
        .catch(function () {
          throw new Error("That access code didn't work.");
        });
    });
  }

  function setSession(session) {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(session));
  }

  function getSession() {
    try {
      var raw = sessionStorage.getItem(STORE_KEY);
      if (!raw) return null;
      var session = JSON.parse(raw);
      return session && session.token && session.repo ? session : null;
    } catch (e) {
      return null;
    }
  }

  function clearSession() {
    sessionStorage.removeItem(STORE_KEY);
  }

  function request(session, path, options) {
    var opts = options || {};
    return fetch(API + path, {
      method: opts.method || "GET",
      cache: "no-store",
      headers: {
        Authorization: "Bearer " + session.token,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (r) {
      return r
        .json()
        .catch(function () {
          return {};
        })
        .then(function (body) {
          if (r.ok) return body;
          var msg = body.message || "GitHub returned " + r.status;
          if (r.status === 401 || r.status === 403) {
            msg = "The saved access is no longer valid. Sign in again.";
          } else if (r.status === 409) {
            msg = "Someone else saved this guide first. Reload and redo your change.";
          }
          var err = new Error(msg);
          err.status = r.status;
          throw err;
        });
    });
  }

  function verify(session) {
    return request(session, "/repos/" + session.repo).then(function (repo) {
      if (!repo.permissions || !repo.permissions.push) {
        throw new Error("This access code can no longer save changes.");
      }
      return session;
    });
  }

  function contentPath(session, repoPath) {
    return (
      "/repos/" + session.repo + "/contents/" + repoPath.split("/").map(encodeURIComponent).join("/")
    );
  }

  function readJson(session, repoPath) {
    return request(
      session,
      contentPath(session, repoPath) + "?ref=" + encodeURIComponent(session.branch)
    ).then(function (file) {
      var text = new TextDecoder().decode(base64ToBytes(file.content || ""));
      return { data: JSON.parse(text), sha: file.sha };
    });
  }

  function writeJson(session, repoPath, data, message, sha) {
    var text = JSON.stringify(data, null, 1) + "\n";
    return write(session, repoPath, bytesToBase64(new TextEncoder().encode(text)), message, sha);
  }

  function write(session, repoPath, base64Content, message, sha) {
    var body = {
      message: message,
      content: base64Content,
      branch: session.branch,
    };
    if (sha) body.sha = sha;
    return request(session, contentPath(session, repoPath), { method: "PUT", body: body });
  }

  function fileToBase64(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () {
        resolve(bytesToBase64(new Uint8Array(reader.result)));
      };
      reader.onerror = function () {
        reject(new Error("Could not read that file."));
      };
      reader.readAsArrayBuffer(file);
    });
  }

  window.DPMEditor = {
    keyFileExists: function (prefix) {
      return loadKeyFile(prefix).then(
        function () {
          return true;
        },
        function () {
          return false;
        }
      );
    },
    unlock: unlock,
    verify: verify,
    setSession: setSession,
    getSession: getSession,
    clearSession: clearSession,
    readJson: readJson,
    writeJson: writeJson,
    write: write,
    fileToBase64: fileToBase64,
  };
})();
