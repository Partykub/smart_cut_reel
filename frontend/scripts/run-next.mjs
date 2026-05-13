import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";

function readEnvFile(envPath) {
  if (!existsSync(envPath)) {
    return {};
  }

  const result = {};
  const envContent = readFileSync(envPath, "utf8");

  for (const rawLine of envContent.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }

    const separatorIndex = line.indexOf("=");
    if (separatorIndex < 1) {
      continue;
    }

    const name = line.slice(0, separatorIndex).trim();
    let value = line.slice(separatorIndex + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    result[name] = value;
  }

  return result;
}

function resolvePort() {
  if (process.env.FRONTEND_PORT) {
    return process.env.FRONTEND_PORT;
  }

  const envFile = readEnvFile(join(process.cwd(), ".env.local"));
  return envFile.FRONTEND_PORT || "3000";
}

const require = createRequire(import.meta.url);

const subcommand = process.argv[2];
if (subcommand !== "dev" && subcommand !== "start") {
  console.error("Usage: node ./scripts/run-next.mjs <dev|start>");
  process.exit(1);
}

const nextEntryPoint = require.resolve("next/dist/bin/next");
const child = spawn(process.execPath, [nextEntryPoint, subcommand, "--port", resolvePort()], {
  stdio: "inherit",
  env: process.env,
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }

  process.exit(code ?? 0);
});

child.on("error", (error) => {
  console.error(error.message);
  process.exit(1);
});