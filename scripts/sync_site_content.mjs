/**
 * Regenerate app/data/site.json from portfolio-v2.
 *
 *   node scripts/sync_site_content.mjs [path-to-portfolio-v2]
 *
 * The site's content lives in portfolio-v2/data/site.ts and in each route's
 * metadata export. It is baked into this repo rather than fetched at runtime,
 * because a serverless function that fetches its own reference data pays for it
 * on every cold start, and this content changes about once a month.
 *
 * Node reads the .ts source directly, stripping types, so there is no build
 * step and no second copy of the type definitions to keep in sync.
 *
 * Re-run this when the portfolio's projects or writing change.
 */

import { readFile, readdir, writeFile, mkdir } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "..", "app", "data", "site.json");
const PORTFOLIO = resolve(process.argv[2] ?? join(HERE, "..", "..", "portfolio-v2"));

/** Every directory under app/ holding a page.tsx, as a site route. */
async function findRoutes(appDir) {
  const routes = [];
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        // Route groups and private folders are not real URL segments. Skipping
        // them wholesale is fine here because the site uses neither.
        if (!entry.name.startsWith("_") && !entry.name.startsWith("(")) await walk(full);
      } else if (entry.name === "page.tsx") {
        const url = "/" + relative(appDir, dir).split(/[\\/]/).filter(Boolean).join("/");
        routes.push({ route: url, file: full });
      }
    }
  }
  await walk(appDir);
  return routes.sort((a, b) => a.route.localeCompare(b.route));
}

const SUFFIX = " · ammar hassan";

/** Pull title and description out of a route's `export const metadata` block. */
async function readMetadata(file) {
  const source = await readFile(file, "utf8");
  const block = source.match(/export const metadata[^=]*=\s*\{([\s\S]*?)\n\};/);
  if (!block) return null;
  const body = block[1];
  const title = body.match(/title:\s*"((?:[^"\\]|\\.)*)"/)?.[1];
  const description = body.match(/description:\s*\s*"((?:[^"\\]|\\.)*)"/s)?.[1];
  if (!title) return null;
  return {
    title: title.endsWith(SUFFIX) ? title.slice(0, -SUFFIX.length) : title,
    description: description ?? null,
  };
}

const data = await import(pathToFileURL(join(PORTFOLIO, "data", "site.ts")).href);

const pages = [];
for (const { route, file } of await findRoutes(join(PORTFOLIO, "app"))) {
  const meta = await readMetadata(file);
  if (!meta) {
    console.warn(`  no metadata on ${route}, skipping`);
    continue;
  }
  pages.push({ route, ...meta });
}

const writing = pages.filter((p) => p.route.startsWith("/writing/"));
if (writing.length === 0) throw new Error("no writing pages found, the metadata regex has drifted");

const payload = {
  generated_from: relative(resolve(HERE, ".."), PORTFOLIO).replaceAll("\\", "/"),
  site: data.site,
  projects: data.projects,
  experience: data.experience,
  education: data.education,
  toolbox: data.toolbox,
  pages,
};

await mkdir(dirname(OUT), { recursive: true });
await writeFile(OUT, JSON.stringify(payload, null, 2) + "\n", "utf8");

console.log(`wrote ${relative(process.cwd(), OUT)}`);
console.log(`  ${payload.projects.length} projects, ${pages.length} pages, ${writing.length} essays`);
