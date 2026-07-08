---
name: mykg-github-pages
description: Set up and maintain the GitHub Pages site for the mykg repo (SenolIsci/mykg) — a purpose-built pages/ folder (landing page adapted from README.md, blog posts, diagrams), built by a GitHub Actions workflow that runs Jekyll and deploys the result to a gh-pages branch. Use whenever the user wants to publish project documentation or blog articles as a website, create a landing page, turn the project into a public site, enable/configure/troubleshoot GitHub Pages or the gh-pages branch, add a new page/blog post/diagram to the published site, fix a broken/failing Pages build, or asks things like "can we get a docs site for mykg", "I want a landing page based on README", "publish this blog article", "is Pages enabled yet", "the pages workflow failed", or "add this new doc to the site". Also trigger on custom domain / CNAME requests for the project site. Scoped to the mykg repo's own pages/ folder and its gh-pages publishing pipeline — not for unrelated new project sites, and never touches docs/ (that folder is internal/reference material, kept off the published site by design).
---

# mykg GitHub Pages

Publishes a purpose-built `pages/` folder from the `SenolIsci/mykg` `main`
branch as a website, via a GitHub Actions workflow that builds it with
Jekyll and pushes the built `_site/` output to a `gh-pages` branch, which is
what GitHub Pages actually serves.

```
main branch                        gh-pages branch
├── src/       ← software          ├── index.html   ← built site
├── docs/      ← internal/         ├── blog/...
│                 reference only,  └── ...  (generated — never hand-edit)
│                 NEVER published
├── pages/     ← Pages source
│   ├── _config.yml
│   ├── _posts/          (blog articles)
│   ├── index.md         (landing page, adapted from README.md)
│   └── diagrams/
└── .github/workflows/pages.yml

pages.yml: on push to main (pages/** changes) → jekyll build pages/ → _site/
           → peaceiris/actions-gh-pages pushes _site/ to gh-pages
Settings > Pages: source = gh-pages branch
```

## Why `pages/`, not `docs/`

`docs/` already holds a mix of design/architecture material and example
session dumps (full pipeline runs with raw intermediate JSON, logs —
debugging artifacts, not reader-facing content) accumulated over the
project's life. Retrofitting that folder for public consumption means an
ongoing exclusion list that has to be re-checked every time something new
lands in `docs/` — a maintenance burden that grows with the project instead
of shrinking.

A dedicated `pages/` folder sidesteps this entirely: it holds *only* content
written for the public site, so there's never anything to accidentally
publish. `docs/` stays exactly what it already is — internal/reference
material — and this skill never reads from it as a content source, only as
occasional inspiration when adapting something (e.g. pulling the project
description from `README.md` into `pages/index.md`). If a future user of
this skill wants to instead publish `docs/` directly, that's a materially
different setup (see `references/jekyll-and-pages.md` for the tradeoffs) —
don't default to it.

## Check state before doing anything

```bash
gh api repos/SenolIsci/mykg/pages 2>&1
git ls-remote --heads origin gh-pages
cat .github/workflows/pages.yml 2>&1
ls pages/ 2>&1
```

- No `pages/` folder, no `gh-pages` branch, no workflow file → first-time
  setup. Do the full flow: Step 1 through Step 5.
- `pages/` and the workflow already exist → maintenance request (add a page,
  add a blog post, fix a failing build). Skip to the relevant section below.
- Workflow exists but the last run failed → go straight to Troubleshooting.

## Step 1 — Scaffold `pages/` and the landing page

Create `pages/index.md` as the site's landing page, adapted from
`README.md` — not a straight copy. The README carries CI/PyPI/codecov
badges, a long table of contents, and prose written for someone about to
`pip install` and read source code; a landing page is written for someone
deciding whether the project is relevant to them at all. Concretely:

- Lead with what myKG does and why (the first paragraph or two of the
  README's intro is usually the right seed).
- Keep the logo.
- Drop CI/coverage/PyPI-version badges — they're repo-maintenance signals,
  not landing-page content. A "View on GitHub" / "PyPI" link pair is enough.
- Link out to: the blog (once it exists — see Step 2), the GitHub repo, and
  PyPI. Don't try to reproduce the README's full command reference — link to
  it on GitHub instead of duplicating it.
- Ask the user to review the draft copy before moving on — this is the page
  a stranger sees first, worth a second pair of eyes rather than shipping
  silently.

Bring over the logo assets referenced from the README
(`docs/mykg-logo-*.{png,svg}`) into `pages/assets/` — copy, don't move;
`docs/` keeps its own copies since other things may still reference them
there.

## Step 2 — Blog articles

Use Jekyll's built-in posts collection so the blog listing is
auto-generated rather than hand-maintained — this matters once there's more
than one or two articles.

- Articles live at `pages/_posts/YYYY-MM-DD-slug.md` — the date in the
  filename is what Jekyll uses to sort and route the post. Use the
  article's actual publish date (e.g. its original Medium publish date), not
  today's date.
- Each post needs front matter:
  ```yaml
  ---
  layout: post
  title: "Building a Knowledge Graph Pipeline"
  date: 2026-06-05
  ---
  ```
- Add `pages/blog.md` as the listing page:
  ```liquid
  ---
  layout: default
  title: Blog
  ---
  <ul>
  {% for post in site.posts %}
    <li><a href="{{ post.url | relative_url }}">{{ post.title }}</a> — {{ post.date | date: "%B %-d, %Y" }}</li>
  {% endfor %}
  </ul>
  ```
- Link `pages/blog.md` from `pages/index.md`'s nav.
- The user supplies the actual article content (paste, or point at a
  source) — don't invent article text. If no articles are ready yet, it's
  fine to scaffold `_posts/` empty and `blog.md` with a "coming soon" note;
  say so explicitly rather than silently leaving the folder missing.

## Step 3 — Jekyll config

Write `pages/_config.yml`:

```yaml
title: myKG
description: AI workflow that turns documents into a confidence-scored knowledge graph with an induced RDFS/OWL ontology
theme: jekyll-theme-minimal
show_downloads: false
```

- `theme:` — show the user 2-3 named options
  (`jekyll-theme-minimal`, `-cayman`, `-slate`, etc.) rather than picking
  silently; it's the single biggest visual decision here. Because this is an
  Actions build (not GitHub's native Jekyll runner), any theme on
  rubygems.org works — but stick to a GitHub-supported theme unless asked
  for something specific, since it needs no extra Gemfile entries.
- Reuse the title/description strings already in `pyproject.toml`/
  `README.md` rather than inventing new copy.
- No `exclude:` list needed by default — `pages/` only ever contains what
  was deliberately put there. If diagrams or other supporting assets get
  added later that shouldn't build as standalone pages (raw source files for
  an image, say), add `exclude:` then, not preemptively.

**Gemfile** — bundle `references/Gemfile.template` as `pages/Gemfile`,
adjusting the theme gem to match whatever was chosen above.

**Diagrams** — create `pages/diagrams/` and copy over (don't move) whichever
`docs/diagrams/*.png` / `*.html` the user wants featured on the site, linked
from `index.md` or the relevant post. Not every diagram in `docs/diagrams/`
needs to be public — ask which ones are relevant rather than copying the
whole folder by default, same reasoning as the docs/ vs pages/ split above.

## Step 4 — Write the Actions workflow

Copy `assets/pages.yml` to `.github/workflows/pages.yml`, adjusting the
`pages/**` path filter and theme/Ruby version only if Step 3's choices
require it. Don't touch `ci.yml` or `release.yml` — this is a new,
independent workflow.

Key properties of the template (see `references/jekyll-and-pages.md` for the
full rationale on each):

- Triggers on push to `main` with a `paths: ["pages/**"]` filter, plus
  `workflow_dispatch` so it can be re-run manually without an empty commit.
- Builds with `ruby/setup-ruby` + `bundle install` + `jekyll build --source
  pages --destination _site`.
- Deploys via `peaceiris/actions-gh-pages@v4` with `publish_dir: ./_site`,
  `publish_branch: gh-pages` — this action force-pushes a fresh commit to
  `gh-pages` each run, so nobody should ever hand-edit that branch.
- Needs `permissions: contents: write` (the action pushes a branch) — flag
  this explicitly to the user before the first push, since it's a workflow
  gaining write access to the repo, worth a second look even in a repo they
  own.

## Step 5 — First push and enabling Pages

Committing the new `pages/` folder and workflow to `main`, and enabling a
public URL, are both visible/hard-to-quietly-undo actions — confirm with the
user before pushing and before the enable call. State plainly what each step
does.

```bash
gh repo view --json nameWithOwner   # confirm this really is SenolIsci/mykg first
git add pages/ .github/workflows/pages.yml
git commit -m "Add GitHub Pages site (pages/ + Actions build)"
git push
```

Pushing to `main` triggers the workflow, which creates `gh-pages` on its
first successful run. Watch it once:

```bash
gh run watch --exit-status
```

Once `gh-pages` exists, point Pages at it:

```bash
gh api -X POST repos/SenolIsci/mykg/pages \
  -f "source[branch]=gh-pages" \
  -f "source[path]=/" \
  -f "build_type=workflow"
```

If this 409s ("already exists"), Pages is already configured — use `PUT`
with the same body instead. `build_type=workflow` is correct here (as
opposed to `legacy`) because the actual Jekyll build already happened in
Actions; Pages is just serving the pre-built `gh-pages` branch as static
files, not building anything itself.

## Step 6 — Verify

```bash
gh api repos/SenolIsci/mykg/pages --jq '{status, html_url, source}'
```

Tell the user the expected URL (`https://senolisci.github.io/mykg/`) and
that the very first build can take a few minutes. Don't poll in a sleep
loop — check once now, and again only if the user asks later.

## Maintenance tasks (pages/ + workflow + gh-pages already set up)

**Adding a new page** — drop the file under `pages/`, push to `main`; the
workflow rebuilds and redeploys automatically. Add a link from `index.md` or
the relevant nav — a page with no incoming link still builds and is
reachable by direct URL, but is invisible to a visitor browsing the site.

**Adding a new blog post** — drop it in `pages/_posts/` as
`YYYY-MM-DD-slug.md` with the same front matter shape as existing posts;
`pages/blog.md`'s `site.posts` loop picks it up automatically, no manual
link needed.

**Adding a diagram** — copy the source file from `docs/diagrams/` into
`pages/diagrams/` (never point the site at `docs/` directly — see "Why
pages/, not docs/" above) and link it from wherever it's relevant.

**Custom domain** — only act on this if the user explicitly asks; it
touches DNS outside the repo. Needs a `pages/CNAME` file (survives the
Jekyll build since Jekyll copies non-`_`-prefixed files verbatim) plus a DNS
record the user creates at their registrar — say plainly that the DNS half
is entirely outside this skill's reach, don't imply the repo-side change
alone finishes it. See `references/jekyll-and-pages.md`.

## Troubleshooting a failing build

```bash
gh run list --workflow=pages.yml --limit 5
gh run view <run-id> --log-failed
```

Common causes, roughly in order of likelihood:
- A file in `pages/` with front-matter-looking content (starts with `---`)
  that isn't valid YAML — Jekyll tries to parse it as front matter and fails.
- A `Gemfile` gem version mismatch after a Ruby version bump in the workflow.
- A broken relative link or missing include that a stricter theme's Liquid
  templating chokes on.
- `permissions: contents: write` missing from the workflow (the
  `actions-gh-pages` push fails with a 403).

## What NOT to do

- Don't hand-edit anything on the `gh-pages` branch — it's fully
  regenerated by the workflow on every push to `main`; manual edits are
  silently overwritten on the next build.
- Don't touch `.github/workflows/ci.yml` or `release.yml` — Pages is
  independent of CI/release and shouldn't be threaded into those pipelines.
- Don't point the Pages workflow at `docs/`, copy its example/session dumps
  into `pages/`, or otherwise treat `docs/` as a content source beyond
  occasional copy-and-adapt (like the README → landing page, or a specific
  named diagram). `docs/` holds internal reference material and pipeline
  session dumps that were explicitly decided against publishing — see "Why
  pages/, not docs/" above.
- Don't invent blog article content — the user supplies it.
