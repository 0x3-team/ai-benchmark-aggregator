const allowedCustomHost = "benchmark.0x3.dev";

export function parsePagesSmokeUrl(value) {
  if (typeof value !== "string") throw new TypeError("Deployment URL must be a string.");

  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error("Deployment URL must be a valid HTTPS URL.");
  }

  const isExactOrigin = value === url.origin || value === `${url.origin}/`;
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.port ||
    url.pathname !== "/" ||
    url.search ||
    url.hash ||
    !isExactOrigin ||
    (url.hostname !== allowedCustomHost && !url.hostname.endsWith(".pages.dev"))
  ) {
    throw new Error("Deployment URL must be an allowed HTTPS origin without credentials, port, path, query, or fragment.");
  }

  return url.origin;
}

if (process.argv[1] === new URL(import.meta.url).pathname) {
  try {
    console.log(parsePagesSmokeUrl(process.argv[2]));
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 2;
  }
}
