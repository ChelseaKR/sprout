// Copy the compiled ESM output (`dist/src/*.js`) into `public/assets/` so the static
// site can serve them directly with `<script type="module">` — no bundler. The compiled
// files already use relative `./x.js` imports (Node's NodeNext resolution requires the
// explicit extension), which is exactly what a browser's native ES module loader wants
// too, so no rewriting is needed.
import { mkdirSync, readdirSync, copyFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const srcDir = path.join(root, "dist", "src");
const destDir = path.join(root, "public", "assets");

mkdirSync(destDir, { recursive: true });

const files = readdirSync(srcDir).filter((f) => f.endsWith(".js"));
if (files.length === 0) {
  throw new Error(`no compiled .js files found in ${srcDir} — run \`npm run build\` first`);
}
for (const file of files) {
  copyFileSync(path.join(srcDir, file), path.join(destDir, file));
}
console.log(`Copied ${files.length} compiled module(s) to ${destDir}`);
