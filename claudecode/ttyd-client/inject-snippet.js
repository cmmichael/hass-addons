#!/usr/bin/env node
// Splice an HTML snippet into the ttyd client's inline.html, immediately
// before its closing </body>. Runs in the ttyd-client build stage (see
// Dockerfile) after inject-wasm-shim.js; the result is what ttyd serves via
// --index.
//
// Fails loudly instead of producing a silently unpatched page: </body> must
// occur exactly once, and the snippet's first element id must not be in the
// page yet.
//
// Usage: inject-snippet.js <inline.html> <snippet.html>
'use strict';
const fs = require('fs');

const [, , htmlPath, snippetPath] = process.argv;
if (!htmlPath || !snippetPath) {
  console.error('usage: inject-snippet.js <inline.html> <snippet.html>');
  process.exit(2);
}

const html = fs.readFileSync(htmlPath, 'utf8');
const snippet = fs.readFileSync(snippetPath, 'utf8');
const marker = '</body>';

const at = html.indexOf(marker);
if (at < 0 || html.indexOf(marker, at + 1) >= 0) {
  console.error(`inject-snippet: ${JSON.stringify(marker)} must occur exactly once in ${htmlPath}`);
  process.exit(1);
}
const id = (snippet.match(/\sid="([^"]+)"/) || [])[1];
if (!id) {
  console.error(`inject-snippet: ${snippetPath} has no element id to guard against injecting it twice`);
  process.exit(1);
}
if (html.includes(`id="${id}"`)) {
  console.error(`inject-snippet: ${htmlPath} already contains #${id}`);
  process.exit(1);
}

fs.writeFileSync(htmlPath, html.slice(0, at) + snippet + html.slice(at));
console.log(`inject-snippet: inserted ${snippetPath} (#${id}, ${snippet.length} bytes) into ${htmlPath}`);
