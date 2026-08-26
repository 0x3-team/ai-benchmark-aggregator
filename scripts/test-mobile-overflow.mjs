import { spawn } from "node:child_process";
import { once } from "node:events";
import { accessSync, constants } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import WebSocket from "ws";

const vitePort = 4174;
const chromePort = 9223;
const viteReadyTimeoutMs = 10_000;
const chromeReadyTimeoutMs = 60_000;
const chromeUserDataDir = await mkdtemp(join(tmpdir(), "p10-mobile-overflow-"));
const vite = spawn(
  process.execPath,
  ["./node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"],
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

  for (const command of ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]) {
    const executable = commandInPath(command);
    if (executable) return executable;
  }
  throw new Error("No headless Chrome executable was found. Set CHROME_BIN to an executable path.");
}

async function waitFor(url, { description = url, timeoutMs } = {}) {
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
  const detail = lastError instanceof Error ? ` Last error: ${lastError.message}` : "";
  throw new Error(`Timed out waiting for ${description} after ${timeoutMs}ms.${detail}`, {
    cause: lastError,
  });
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

async function evaluate(socket, expression) {
  const id = evaluate.nextId++;
  const result = new Promise((resolve, reject) => {
    const onMessage = (event) => {
      const message = JSON.parse(event.toString());
      if (message.id !== id) return;
      socket.off("message", onMessage);
      if (message.error) reject(new Error(message.error.message));
      else if (message.result.exceptionDetails) reject(new Error(message.result.exceptionDetails.text));
      else resolve(message.result.result.value);
    };
    socket.on("message", onMessage);
  });
  socket.send(
    JSON.stringify({
      id,
      method: "Runtime.evaluate",
      params: { expression, returnByValue: true },
    })
  );
  return result;
}
evaluate.nextId = 1;

try {
  await waitFor(`http://127.0.0.1:${vitePort}/browser-test/p10-mobile-overflow.html`, {
    description: "the Vite browser fixture",
    timeoutMs: viteReadyTimeoutMs,
  });
  const chromeExecutable = resolveChromeExecutable();
  chrome = spawn(
    chromeExecutable,
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
  const chromeError = once(chrome, "error").then(([error]) => Promise.reject(error));
  const chromeExit = once(chrome, "exit").then(([code, signal]) =>
    Promise.reject(new Error(`Headless Chrome exited before DevTools was ready: code=${code} signal=${signal}`))
  );
  const targetsResponse = await Promise.race([
    waitFor(`http://127.0.0.1:${chromePort}/json`, {
      description: "headless Chrome DevTools",
      timeoutMs: chromeReadyTimeoutMs,
    }),
    chromeError,
    chromeExit,
  ]);
  const targets = await targetsResponse.json();
  const target = targets.find((candidate) => candidate.type === "page");
  if (!target?.webSocketDebuggerUrl) throw new Error("Chrome did not expose a debuggable page.");
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await Promise.race([
    once(socket, "open"),
    once(socket, "error").then(([error]) => Promise.reject(error)),
  ]);
  socket.send(
    JSON.stringify({
      id: 0,
      method: "Emulation.setDeviceMetricsOverride",
      params: { width: 390, height: 844, deviceScaleFactor: 1, mobile: true },
    })
  );
  socket.send(
    JSON.stringify({
      id: -1,
      method: "Page.navigate",
      params: { url: `http://127.0.0.1:${vitePort}/browser-test/p10-mobile-overflow.html` },
    })
  );
  let measurements;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    measurements = await evaluate(
      socket,
      `(() => {
        const table = document.querySelector("table");
        const scroller = table?.parentElement;
        if (!scroller) return null;
        return {
          documentScrollWidth: document.documentElement.scrollWidth,
          documentClientWidth: document.documentElement.clientWidth,
          tableScrollWidth: scroller.scrollWidth,
          tableClientWidth: scroller.clientWidth,
        };
      })()`
    );
    if (measurements) break;
    await sleep(100);
  }
  if (!measurements) throw new Error("The published-fixture score table did not render.");
  if (measurements.documentScrollWidth !== measurements.documentClientWidth) {
    throw new Error(`Document overflow at 390px: ${JSON.stringify(measurements)}`);
  }
  if (measurements.tableScrollWidth <= measurements.tableClientWidth) {
    throw new Error(`Score table did not own horizontal overflow at 390px: ${JSON.stringify(measurements)}`);
  }
  const stickyPositions = await evaluate(
    socket,
    `(() => {
      const table = document.querySelector("table");
      const scroller = table?.parentElement;
      const rank = table?.querySelector("tbody tr td");
      const model = rank?.nextElementSibling;
      const benchmark = table?.querySelector("thead tr:nth-child(2) th");
      if (!scroller || !rank || !model || !benchmark) return null;
      const before = {
        rank: rank.getBoundingClientRect().left,
        model: model.getBoundingClientRect().left,
        benchmark: benchmark.getBoundingClientRect().left,
      };
      scroller.scrollLeft = Math.min(120, scroller.scrollWidth - scroller.clientWidth);
      const after = {
        rank: rank.getBoundingClientRect().left,
        model: model.getBoundingClientRect().left,
        benchmark: benchmark.getBoundingClientRect().left,
        scrollLeft: scroller.scrollLeft,
      };
      return { before, after };
    })()`
  );
  if (!stickyPositions || stickyPositions.after.scrollLeft <= 0) {
    throw new Error("The rendered score table could not be horizontally scrolled at 390px.");
  }
  if (
    Math.abs(stickyPositions.after.rank - stickyPositions.before.rank) > 1 ||
    Math.abs(stickyPositions.after.model - stickyPositions.before.model) > 1 ||
    stickyPositions.after.benchmark >= stickyPositions.before.benchmark - 1
  ) {
    throw new Error(`Sticky columns did not remain pinned at 390px: ${JSON.stringify(stickyPositions)}`);
  }
  socket.close();
  console.log(`390px overflow assertion passed: ${JSON.stringify(measurements)}`);
} finally {
  await stopChild(chrome);
  await stopChild(vite);
  await rm(chromeUserDataDir, { force: true, maxRetries: 10, recursive: true, retryDelay: 100 });
}
