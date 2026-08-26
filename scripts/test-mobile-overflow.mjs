import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import WebSocket from "ws";

const vitePort = 4174;
const chromePort = 9223;
const chromeUserDataDir = await mkdtemp(join(tmpdir(), "p10-mobile-overflow-"));
const vite = spawn(
  process.execPath,
  ["./node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"],
  { cwd: process.cwd(), stdio: "ignore" }
);
let chrome;

async function waitFor(url) {
  let lastError;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
    } catch (error) {
      lastError = error;
    }
    await sleep(100);
  }
  throw lastError ?? new Error(`Timed out waiting for ${url}`);
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
  await waitFor(`http://127.0.0.1:${vitePort}/browser-test/p10-mobile-overflow.html`);
  chrome = spawn(
    process.env.CHROME_BIN ?? "google-chrome",
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
  const targets = await (await waitFor(`http://127.0.0.1:${chromePort}/json`)).json();
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
        const scroller = table?.parentElement?.parentElement;
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
  socket.close();
  if (!measurements) throw new Error("The published-fixture score table did not render.");
  if (measurements.documentScrollWidth !== measurements.documentClientWidth) {
    throw new Error(`Document overflow at 390px: ${JSON.stringify(measurements)}`);
  }
  if (measurements.tableScrollWidth <= measurements.tableClientWidth) {
    throw new Error(`Score table did not own horizontal overflow at 390px: ${JSON.stringify(measurements)}`);
  }
  console.log(`390px overflow assertion passed: ${JSON.stringify(measurements)}`);
} finally {
  if (chrome) {
    const exit = once(chrome, "exit");
    chrome.kill();
    await Promise.race([exit, sleep(2_000)]);
  }
  vite.kill();
  await rm(chromeUserDataDir, { force: true, maxRetries: 10, recursive: true, retryDelay: 100 });
}
