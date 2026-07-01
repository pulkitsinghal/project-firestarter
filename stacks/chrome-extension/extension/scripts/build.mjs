// esbuild bundler for the MV3 extension. Bundles the TS entry points to IIFE
// files in dist/ and copies the static assets (manifest, side-panel HTML/CSS,
// icons). esbuild does NOT type-check — `npm run typecheck` (tsc --noEmit) is the
// separate type gate; CI runs both.
import { build, context } from 'esbuild';
import { cp, mkdir, readdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');
const isWatch = process.argv.includes('--watch');

async function copyStatic() {
  await mkdir(dist, { recursive: true });
  for (const f of ['manifest.json', 'sidebar.html', 'sidebar.css']) {
    await cp(join(root, 'public', f), join(dist, f));
  }
  // Icons are optional in the skeleton — Chrome shows a default puzzle icon if
  // absent. Drop your 16/32/48/128 PNGs in public/icons and wire them into
  // manifest.json to ship real branding.
  try {
    const icons = join(root, 'public', 'icons');
    if ((await readdir(icons)).some((n) => n.endsWith('.png'))) {
      await cp(icons, join(dist, 'icons'), { recursive: true });
    } else {
      console.warn('build: no PNGs in public/icons/ — using Chrome default icon.');
    }
  } catch {
    console.warn('build: public/icons/ missing — using Chrome default icon.');
  }
}

const common = {
  bundle: true,
  minify: false,
  sourcemap: true,
  target: 'es2020',
  outdir: dist,
  format: 'iife',
  platform: 'browser',
  logLevel: 'info',
};

const entryPoints = {
  background: join(root, 'src', 'background.ts'),
  'content-script': join(root, 'src', 'content-script.ts'),
  sidebar: join(root, 'src', 'sidebar.ts'),
};

async function run() {
  await copyStatic();
  if (isWatch) {
    const ctx = await context({ ...common, entryPoints });
    await ctx.watch();
    console.log('Watching for changes…');
  } else {
    await build({ ...common, entryPoints });
    console.log('Build complete → dist/');
  }
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
