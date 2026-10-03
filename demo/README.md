# DoomLab portfolio demo

A static, responsive project report with Space Grotesk, a single reading column, and restrained evidence figures. Everything needed to host the page is inside `demo/`.
No API calls or credentials are used by the page itself.

From the repository root:

```sh
python3 -m http.server 4173 --bind 127.0.0.1 --directory demo
```

Open http://127.0.0.1:4173. Deploy the `demo/` directory with any static host.

## Update the page

Edit `template.html`, `styles.css`, or `app.js`, then run:

```sh
python3 demo/build.py
```

The build reads the committed `results/summary.json`, improvement verdict, and
test trace archive. It writes both `index.html` and the existing `page.html`
entry point, plus downloadable evidence under `demo/data/`. The results table,
survival distributions, verbatim lessons, validation pairs, and commander
timeline are rendered at build time. Core content remains readable without JS.

The repository's original `uv run doomlab demo` generator still uses its original
template and will overwrite these two HTML files. Run `python3 demo/build.py`
afterwards to restore this presentation. The experiment code is unchanged.

## Replay media

The supplied captioned WebP replays are preserved. Controllable MP4 derivatives
preserve their frame durations, including repeated-frame holds. They already run
at 2× game speed; the browser plays them at its normal playback rate. Each set
autoplays and loops independently, so short clips never hold on a final frame.
Select any clip to pause or resume its comparison group.

To regenerate the MP4s and lossless initial-frame posters (Pillow + ffmpeg):

```sh
.venv/bin/python demo/prepare_media.py
```

## Browser checks

With the preview server running:

```sh
npm install --prefix demo
npm run check --prefix demo
```

The check uses Chrome on macOS if installed, or Playwright Chromium otherwise.
For the latter, install a browser within the demo directory:

```sh
cd demo
PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright" npx playwright install chromium
```

It checks responsive overflow, evidence values, autoplay and continuous replay
loops, theme-transition click locking, the rendered flowchart, per-seed hover
labels, keyboard access, copy commands, downloads, and accessibility.
Screenshots are not saved by the automated check. Any temporary visual-review
screenshots must be deleted immediately after inspection.

## Presentation and editorial sources

The page is an article, with a first-person introduction, a short TL;DR,
plain tables, and a narrative of the failed improvement trial. The lessons
section incorporates `docs/persona-noted.md`, checked against the findings,
pilot notes, and implementation. The blogEO example supplied in the conversation
informed the narrative structure; none of its projects, affiliations, or results
are presented as DoomLab facts.

The evidence figures are supplied replays, per-seed score distributions, a
commander timeline, and a rendered Mermaid flowchart. `harness.mmd` is the flowchart
source. `render_diagram.mjs` renders its static SVG with the locally installed
Mermaid package. The theme toggle follows the circle reveal used by [Magic UI’s animated theme toggle](https://magicui.design/docs/components/animated-theme-toggler), reviewed through the [21st.dev animated toggle directory](https://21st.dev/community/components/s/animated-theme-toggle), and adapts it to this static page with a View Transition circle; the button stays disabled until
the transition finishes so repeat clicks cannot stack transitions. The component
package itself expects a React and Tailwind project, so only its documented
interaction is adapted here. Replays autoplay and loop continuously.

Space Grotesk is self-hosted; its SIL Open Font License is in `assets/`.
