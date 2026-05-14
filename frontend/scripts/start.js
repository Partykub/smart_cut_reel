/**
 * Cross-platform launcher for Next.js dev/start.
 * Loads .env.local (if present) then runs: next <command> --port <FRONTEND_PORT|3000>
 *
 * Replaces the Unix-only `sh -ac '...'` in package.json scripts.
 * Zero extra npm dependencies — works on Windows, macOS, and Linux.
 *
 * Usage (via package.json):
 *   node scripts/start.js dev
 *   node scripts/start.js start
 */

'use strict';

const { execFileSync } = require('child_process');
const { existsSync, readFileSync } = require('fs');
const { resolve } = require('path');

// Load .env.local — only set vars that aren't already in the environment
const envFile = resolve(__dirname, '..', '.env.local');
if (existsSync(envFile)) {
  readFileSync(envFile, 'utf8').split('\n').forEach((line) => {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (m && process.env[m[1]] === undefined) {
      process.env[m[1]] = m[2].replace(/^["'](.*)["']$/, '$1');
    }
  });
}

const command = process.argv[2] || 'dev';
const port = process.env.FRONTEND_PORT || '3000';

// Resolve next binary cross-platform (.cmd on Windows, no extension on Unix)
const isWindows = process.platform === 'win32';
const nextBin = resolve(
  __dirname,
  '..',
  'node_modules',
  '.bin',
  isWindows ? 'next.cmd' : 'next'
);

execFileSync(nextBin, [command, '--port', port], { stdio: 'inherit', shell: isWindows });
