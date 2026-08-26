import { spawn } from "node:child_process";
import { once } from "node:events";
import { accessSync, constants } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import WebSocket from "ws";

const vitePort = 4175;
const chromePort = 9224;
const fixturePath = "/browser-test/p11-permalinks.html";
const viteReadyTimeoutMs = 10_000;
const chromeReadyTimeoutMs = 60_000;
const assertionTimeoutMs = 10_000;
const chromeUserDataDir = await mkdtemp(join(tmpdir(), "p11-permalinks-"));
const vite = spawn(
  process.execPath,
  [
    "./node_modules/vite/bin/vite.js",
    "--host",
    "127.0.0.1",
    "--port",
    String(vitePort),
    "--strictPort",
  ],
  { cwd: process.cwd(), stdio: "ignore" }
);
let chrome;

function canExecute(candidate) {
  try {
    accessSync(candidate, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function commandInPath(command) {
  for (const directory of (process.env.PATH ?? "").split(delimiter)) {
    if (!directory) continue;
    const candidate = join(directory, command);
    if (canExecute(candidate)) return candidate;
  }
  return null;
}

function resolveChromeExecutable() {
  const configured = process.env.CHROME_BIN?.trim();
  if (configured) return configured;

  const applicationCandidates =
    process.platform === "darwin"
      ? [
          "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
          "/Applications/Chromium.app/Contents/MacOS/Chromium",
          "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
          "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ]
      : [];
  const application = applicationCandidates.find(canExecute);
  if (application) return application;

  for (const command of [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
  ]) {
    const executable = commandInPath(command);
    if (executable) return executable;
  }
  throw new Error(
    "No headless Chrome executable was found. Set CHROME_BIN to an executable path."
  );
}

async function waitForHttp(url, { description = url, timeoutMs } = {}) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
    } catch (error) {
      lastError = error;
    }
    await sleep(100);
  }
  const detail =
    lastError instanceof Error ? ` Last error: ${lastError.message}` : "";
  throw new Error(
    `Timed out waiting for ${description} after ${timeoutMs}ms.${detail}`,
    { cause: lastError }
  );
}

async function stopChild(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  const exit = once(child, "exit");
  child.kill();
  const exitedGracefully = await Promise.race([
    exit.then(() => true),
    sleep(2_000).then(() => false),
  ]);
  if (exitedGracefully) return;
  child.kill("SIGKILL");
  await exit;
}

function createCdpClient(socket) {
  let nextId = 1;
  return function send(method, params = {}) {
    const id = nextId++;
    const result = new Promise((resolve, reject) => {
      const onMessage = (event) => {
        const message = JSON.parse(event.toString());
        if (message.id !== id) return;
        socket.off("message", onMessage);
        if (message.error) reject(new Error(message.error.message));
        else resolve(message.result);
      };
      socket.on("message", onMessage);
    });
    socket.send(JSON.stringify({ id, method, params }));
    return result;
  };
}

async function evaluate(send, expression) {
  const response = await send("Runtime.evaluate", {
    expression,
    returnByValue: true,
  });
  if (response.exceptionDetails) {
    throw new Error(response.exceptionDetails.text);
  }
  return response.result.value;
}

async function waitForValue(send, expression, accept, description) {
  const deadline = Date.now() + assertionTimeoutMs;
  let lastValue;
  while (Date.now() < deadline) {
    lastValue = await evaluate(send, expression);
    if (accept(lastValue)) return lastValue;
    await sleep(100);
  }
  throw new Error(
    `Timed out waiting for ${description}: ${JSON.stringify(lastValue)}`
  );
}

async function navigate(send, url) {
  await send("Page.navigate", { url });
  await waitForValue(
    send,
    `document.readyState === "complete" && Boolean(document.querySelector("#main-content"))`,
    Boolean,
    `the app at ${url}`
  );
}

const validCanonical = new URLSearchParams();
validCanonical.set("v", "1");
validCanonical.set("q", "beta");
validCanonical.append("vendor", "Southstar");
validCanonical.set("category", "reasoning");
validCanonical.set("open", "1");
validCanonical.set("sort", "p11-reasoning");
validCanonical.set("dir", "desc");
validCanonical.append("compare", "p11-beta");
validCanonical.append("compare", "p11-alpha");
validCanonical.set("model", "p11-beta");
validCanonical.set("zero", "1");
const expectedValidSearch = `?${validCanonical.toString()}`;

const appStateExpression = `(() => {
  const search = document.querySelector('input[type="search"]');
  const vendor = document.querySelector('[aria-label="Filter by vendor Southstar"]');
  const category = document.querySelector('[aria-label="Filter by category Reasoning"]');
  const open = document.querySelector('[aria-label="Open weights only"]');
  const dialog = document.querySelector('[role="dialog"]');
  const compare = Array.from(document.querySelectorAll("button")).find((button) =>
    button.textContent?.includes("Compare")
  );
  return search ? {
    query: location.search,
    search: search.value,
    vendorPressed: vendor?.getAttribute("aria-pressed"),
    categoryPressed: category?.getAttribute("aria-pressed"),
    openChecked: open?.getAttribute("aria-checked"),
    dialogText: dialog?.textContent ?? "",
    compareText: compare?.textContent ?? "",
    bodyText: document.body.textContent ?? "",
  } : null;
})()`;

try {
  await waitForHttp(
    `http://127.0.0.1:${vitePort}${fixturePath}`,
    { description: "the P11 Vite browser fixture", timeoutMs: viteReadyTimeoutMs }
  );

  chrome = spawn(
    resolveChromeExecutable(),
    [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      `--remote-debugging-port=${chromePort}`,
      `--user-data-dir=${chromeUserDataDir}`,
      "about:blank",
    ],
    { stdio: "ignore" }
  );
  const chromeError = once(chrome, "error").then(([error]) =>
    Promise.reject(error)
  );
  const chromeExit = once(chrome, "exit").then(([code, signal]) =>
    Promise.reject(
      new Error(
        `Headless Chrome exited before DevTools was ready: code=${code} signal=${signal}`
      )
    )
  );
  const targetsResponse = await Promise.race([
    waitForHttp(`http://127.0.0.1:${chromePort}/json`, {
      description: "headless Chrome DevTools",
      timeoutMs: chromeReadyTimeoutMs,
    }),
    chromeError,
    chromeExit,
  ]);
  const targets = await targetsResponse.json();
  const target = targets.find((candidate) => candidate.type === "page");
  if (!target?.webSocketDebuggerUrl) {
    throw new Error("Chrome did not expose a debuggable page.");
  }

  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await Promise.race([
    once(socket, "open"),
    once(socket, "error").then(([error]) => Promise.reject(error)),
  ]);
  const send = createCdpClient(socket);
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 900,
    deviceScaleFactor: 1,
    mobile: false,
  });

  const unorderedValidSearch =
    "?unknown=drop-me&compare=p11-beta&vendor=Southstar&q=beta&v=1" +
    "&compare=p11-alpha&category=reasoning&sort=p11-reasoning&dir=desc" +
    "&open=1&model=p11-beta&zero=1";
  await navigate(
    send,
    `http://127.0.0.1:${vitePort}${fixturePath}${unorderedValidSearch}`
  );
  const restored = await waitForValue(
    send,
    appStateExpression,
    (value) =>
      value?.query === expectedValidSearch &&
      value.search === "beta" &&
      value.vendorPressed === "true" &&
      value.categoryPressed === "true" &&
      value.openChecked === "true" &&
      value.dialogText.includes("P11 Beta") &&
      value.compareText.includes("2") &&
      value.bodyText.includes("Sorted by"),
    "valid permalink restoration and canonicalization"
  );

  await send("Page.reload");
  await waitForValue(
    send,
    appStateExpression,
    (value) =>
      value?.query === expectedValidSearch &&
      value.search === "beta" &&
      value.dialogText.includes("P11 Beta"),
    "valid permalink reload"
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });
  const mobile = await evaluate(
    send,
    `({
      documentScrollWidth: document.documentElement.scrollWidth,
      documentClientWidth: document.documentElement.clientWidth,
      dialogWidth: document.querySelector('[role="dialog"]')?.getBoundingClientRect().width ?? 0,
    })`
  );
  if (mobile.documentScrollWidth !== mobile.documentClientWidth) {
    throw new Error(`P11 permalink view overflows at 390px: ${JSON.stringify(mobile)}`);
  }
  if (mobile.dialogWidth <= 0 || mobile.dialogWidth > mobile.documentClientWidth) {
    throw new Error(`P11 model sheet is invalid at 390px: ${JSON.stringify(mobile)}`);
  }

  await navigate(
    send,
    `http://127.0.0.1:${vitePort}${fixturePath}?v=1&model=p11-alpha&benchmark=p11-reasoning`
  );
  await waitForValue(
    send,
    `({ query: location.search, dialog: Boolean(document.querySelector('[role="dialog"]')) })`,
    (value) => value.query === "?v=1" && value.dialog === false,
    "simultaneous sheets to fail closed"
  );

  await navigate(
    send,
    `http://127.0.0.1:${vitePort}${fixturePath}?v=1&compare=missing&model=missing&sort=missing&dir=desc`
  );
  await waitForValue(
    send,
    `({ query: location.search, dialog: Boolean(document.querySelector('[role="dialog"]')) })`,
    (value) => value.query === "?v=1" && value.dialog === false,
    "stale dataset IDs to be removed"
  );

  await navigate(
    send,
    `http://127.0.0.1:${vitePort}${fixturePath}?v=1&q=alpha`
  );
  await waitForValue(
    send,
    `document.querySelector('input[type="search"]')?.value`,
    (value) => value === "alpha",
    "history baseline state"
  );
  await evaluate(
    send,
    `history.pushState(null, "", "${fixturePath}?v=1&q=beta"); dispatchEvent(new PopStateEvent("popstate"));`
  );
  await waitForValue(
    send,
    `document.querySelector('input[type="search"]')?.value`,
    (value) => value === "beta",
    "popstate restoration"
  );
  await evaluate(send, "history.back()");
  await waitForValue(
    send,
    `document.querySelector('input[type="search"]')?.value`,
    (value) => value === "alpha",
    "browser back restoration"
  );
  await evaluate(send, "history.forward()");
  await waitForValue(
    send,
    `document.querySelector('input[type="search"]')?.value`,
    (value) => value === "beta",
    "browser forward restoration"
  );

  socket.close();
  console.log(
    `P11 permalink browser assertions passed: ${JSON.stringify({ restored, mobile })}`
  );
} finally {
  await stopChild(chrome);
  await stopChild(vite);
  await rm(chromeUserDataDir, {
    force: true,
    maxRetries: 10,
    recursive: true,
    retryDelay: 100,
  });
}
