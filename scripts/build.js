#!/usr/bin/env node
/**
 * Cloudflare Pages Build Script
 * Injects non-sensitive public environment variables into static HTML files.
 * SECRETS ARE NEVER ACCESSED OR EXPOSED.
 */

const fs = require('fs');
const path = require('path');

// 1. Resolve DOCS_BASE_URL (from process.env, or fallback to .env/default)
let docsBaseUrl = process.env.DOCS_BASE_URL;

if (!docsBaseUrl) {
  const envPath = path.join(__dirname, '..', '.env');
  if (fs.existsSync(envPath)) {
    const lines = fs.readFileSync(envPath, 'utf8').split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('DOCS_BASE_URL=')) {
        docsBaseUrl = trimmed.split('=')[1].trim().replace(/^["']|["']$/g, '');
        break;
      }
    }
  }
}

// Fallback to official docs domain
if (!docsBaseUrl) {
  docsBaseUrl = 'https://docs.sugandhaenterprises.com';
}

console.log(`[build] Injecting public DOCS_BASE_URL: ${docsBaseUrl}`);

// 2. Process public/statutory.html
const statutoryPath = path.join(__dirname, '..', 'public', 'statutory.html');
if (fs.existsSync(statutoryPath)) {
  let content = fs.readFileSync(statutoryPath, 'utf8');
  if (content.includes('{{DOCS_BASE_URL}}')) {
    content = content.replace(/['"]\{\{DOCS_BASE_URL\}\}['"]/g, JSON.stringify(docsBaseUrl));
    fs.writeFileSync(statutoryPath, content, 'utf8');
    console.log('[build] Successfully injected DOCS_BASE_URL into public/statutory.html');
  } else {
    console.log('[build] Note: {{DOCS_BASE_URL}} placeholder not found in statutory.html (already set)');
  }
}

console.log('[build] Build completed successfully.');
