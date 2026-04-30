#!/usr/bin/env node

const { spawn } = require('child_process');

// Dynamic import for open package
async function openUrl(url) {
  const open = await import('open');
  return open.default(url);
}

// Start Next.js dev server
const nextProcess = spawn('npx', ['next', 'dev', '-p', '3022'], {
  stdio: 'inherit',
  shell: false,
});

// Open browser after a short delay to let the server start
setTimeout(() => {
  openUrl('http://localhost:3022').catch(() => { });
}, 2000);

// Handle process termination
process.on('SIGINT', () => {
  nextProcess.kill('SIGINT');
});

process.on('SIGTERM', () => {
  nextProcess.kill('SIGTERM');
});

nextProcess.on('close', (code) => {
  process.exit(code);
});