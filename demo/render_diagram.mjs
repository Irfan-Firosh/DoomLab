// Render the Mermaid source once. The public page needs no Mermaid runtime.
import { createServer } from "node:http";
import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
process.env.PLAYWRIGHT_BROWSERS_PATH ??= path.join(here, ".playwright");
const { chromium } = await import("playwright");
const chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const server = createServer(async (request, response) => {
  try {
    const requested = new URL(request.url, "http://localhost").pathname;
    if (requested === "/") {
      response.setHeader("Content-Type", "text/html");
      response.end('<!doctype html><html lang="en"><head><meta charset="utf-8"><link rel="stylesheet" href="/styles.css"></head><body></body></html>');
      return;
    }
    const filename = path.resolve(here, "." + decodeURIComponent(requested));
    if (!filename.startsWith(here + path.sep)) throw new Error("Invalid path");
    const mime = { ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".woff2": "font/woff2" }[path.extname(filename)];
    response.setHeader("Content-Type", mime ?? "application/octet-stream");
    response.end(await readFile(filename));
  } catch {
    response.writeHead(404).end();
  }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({ headless: true, ...(existsSync(chrome) ? { executablePath: chrome } : {}) });
try {
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.evaluate(() => document.fonts.load('400 14px "Space Grotesk"'));
  const source = await readFile(path.join(here, "harness.mmd"), "utf8");
  let svg = await page.evaluate(async source => {
    const { default: mermaid } = await import("/node_modules/mermaid/dist/mermaid.esm.min.mjs");
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      fontFamily: '"Space Grotesk", sans-serif',
      themeVariables: { fontFamily: '"Space Grotesk", sans-serif', fontSize: "14px", lineColor: "#878279", textColor: "#292824", primaryTextColor: "#292824", edgeLabelBackground: "#faf9f6", background: "#faf9f6" },
      flowchart: { htmlLabels: false, curve: "linear", nodeSpacing: 24, rankSpacing: 36, padding: 13, useMaxWidth: true },
    });
    return (await mermaid.render("doomlab-harness", source)).svg;
  }, source);
  // Mermaid uses HTML-style <br> labels inside XHTML foreignObjects. Close
  // them so the standalone SVG remains valid XML and works in an <img> tag.
  svg = svg.replaceAll("<br>", "<br/>");
  const font = await readFile(path.join(here, "assets/space-grotesk-latin.woff2"));
  svg = svg.replace("<style>", `<style>@font-face{font-family:'Space Grotesk';font-style:normal;font-weight:300 700;src:url(data:font/woff2;base64,${font.toString("base64")}) format('woff2');}`);
  await writeFile(path.join(here, "assets/harness-flow.svg"), svg);
  console.log("Rendered assets/harness-flow.svg from harness.mmd");
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
