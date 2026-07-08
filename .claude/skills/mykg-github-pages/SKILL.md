---
name: mykg-github-pages
description: Set up and maintain the GitHub Pages site for the mykg repo (SenolIsci/mykg) — a purpose-built pages/ folder (landing page adapted from README.md, blog posts, diagrams), built by a GitHub Actions workflow that runs Jekyll and deploys the result to a gh-pages branch. Use whenever the user wants to publish project documentation or blog articles as a website, create a landing page, turn the project into a public site, enable/configure/troubleshoot GitHub Pages or the gh-pages branch, add a new page/blog post/diagram to the published site, fix a broken/failing Pages build, or asks things like "can we get a docs site for mykg", "I want a landing page based on README", "publish this blog article", "is Pages enabled yet", "the pages workflow failed", or "add this new doc to the site". Also trigger on custom domain / CNAME requests for the project site. Scoped to the mykg repo's own pages/ folder and its gh-pages publishing pipeline — not for unrelated new project sites.
---

# mykg GitHub Pages

Publishes a purpose-built `pages/` folder from the `SenolIsci/mykg` `main`
branch as a website, via a GitHub Actions workflow that builds it with
Jekyll and pushes the built `_site/` output to a `gh-pages` branch, which is
what GitHub Pages actually serves.

```
main branch                        gh-pages branch
├── src/       ← software          ├── index.html   ← built site
├── pages/     ← Pages source      ├── blog/...
│   ├── _config.yml                └── ...  (generated — never hand-edit)
│   ├── _posts/          (blog articles)
│   ├── index.md         (landing page, adapted from README.md)
│   └── diagrams/
└── .github/workflows/pages.yml

pages.yml: on push to main (pages/** changes) → jekyll build pages/ → _site/
           → peaceiris/actions-gh-pages pushes _site/ to gh-pages
Settings > Pages: source = gh-pages branch
```

## Why a dedicated `pages/` folder

A dedicated `pages/` folder holds *only* content written for the public
site, so there's never anything to accidentally publish. This skill's
default and only source for initial content is `README.md` (see Step 1) —
it never assumes any other folder in the repo is publishable. Any other
repo artifact (a diagram, a logo, a screenshot, an existing doc) is fair
game to feature on the site, but only when the user explicitly points at it
— see "Sourcing artifacts from the repo" below. Don't scan the repo looking
for content to publish; ask instead.

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
- Pages config exists but `build_type` is `"workflow"` while this repo
  deploys via a branch push (i.e. `source.branch` isn't reliably
  `gh-pages`, or the live URL 404s despite green Actions runs) → the
  misconfiguration described in Step 5/6 and Troubleshooting; fix with a
  `PUT` setting `build_type=legacy` before doing anything else.
- `build_type`/`source` look correct, Actions runs are green, `gh-pages` has
  real content, but the live URL still 404s and
  `gh api .../pages --jq .status` is `null` → check whether
  `.github/workflows/pages.yml`'s deploy step uses `secrets.GITHUB_TOKEN`
  instead of a PAT secret. See Step 4a and the matching Troubleshooting
  entry — this is a different bug from the `build_type` one above and looks
  identical from the outside.
- The "Deploy to gh-pages" Actions step itself fails with `remote:
  Permission ... denied` / `403` on `git push origin gh-pages` → the PAT in
  the secret is fine-grained, not classic, or lacks the `repo` scope. See
  Step 4a — this repo's setup only worked with a classic PAT.

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

The README typically references logo/image assets by path or URL. Confirm
with the user which asset(s) to feature and where those files live in the
repo, then copy (don't move) them into `pages/assets/` — the source folder
keeps its own copies since other things may still reference them there. See
"Sourcing artifacts from the repo" below for the general pattern this
follows for any asset, not just the logo.

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

**Diagrams** — create `pages/diagrams/`. See "Sourcing artifacts from the
repo" below for how to decide what goes in it.

## Sourcing artifacts from the repo

Beyond the README (the one default, always-in-scope source for the landing
page's initial copy), this skill does not assume any folder in the repo is
publishable. When a diagram, screenshot, logo variant, or existing doc might
belong on the site: ask the user which specific file(s) to feature and
confirm the path, rather than scanning the repo or defaulting to a folder
that "looks like" documentation. Once confirmed, copy (never move) the file
into the relevant `pages/` subfolder (`pages/assets/`, `pages/diagrams/`,
etc.) — the original stays where it is since other parts of the repo may
still reference it. This keeps the publish surface exactly as big as the
user intends, with no ongoing exclusion list to maintain as the repo grows.

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
- The `github_token` input to `peaceiris/actions-gh-pages` must reference a
  PAT secret (`secrets.PAGES_DEPLOY_TOKEN` in the template), **not**
  `secrets.GITHUB_TOKEN` — see Step 4a, this is not optional.

## Step 4a — Required: a classic PAT with `repo` scope for the deploy step (not `GITHUB_TOKEN`, not a fine-grained PAT)

GitHub does not run a Pages build for commits pushed using the default
`GITHUB_TOKEN` — this is documented, deliberate anti-recursion behavior, not
a bug, but it's easy to miss because nothing errors. The workflow run stays
green, `gh-pages` gets real, valid content, `gh api .../pages` shows the
correct `source.branch`/`build_type`, and the live URL just 404s forever
with the Pages API's `status` field stuck at `null`. This was hit live on
the initial mykg Pages setup and cost a long trial-and-error before the
actual cause (not a `build_type` misconfiguration, despite looking exactly
like one) was found by cross-checking GitHub's own Actions docs.

**Use a classic PAT, not a fine-grained one.** A fine-grained PAT scoped to
just this repo with "Contents: Read and write" was tried first on the mykg
setup and still failed — `git push origin gh-pages` returned `remote:
Permission to <owner>/<repo>.git denied to <owner>` / `403`, even though the
token's stated scope looked correct. Switching to a **classic** PAT with the
`repo` scope (full control of private repositories, which also covers
public ones) resolved the push immediately. Don't spend time re-diagnosing
a fine-grained PAT's exact permission checkboxes if the push 403s — just
have the user create a classic token instead.

The fix: the `peaceiris/actions-gh-pages` step needs this PAT in place of
`secrets.GITHUB_TOKEN`, stored as its own repo secret. Creating a PAT is a
credential-creation action — **do not generate or store one on the user's
behalf**; ask the user to create it themselves and hand back the secret
name:

1. Tell the user to create a **classic** PAT at
   `https://github.com/settings/tokens` (not the fine-grained
   `?type=beta` flow) with the **`repo`** scope checked, and whatever
   expiration they're comfortable with.
2. Tell the user to add it as a repository secret at
   `https://github.com/SenolIsci/mykg/settings/secrets/actions` (any name —
   the bundled template assumes `PAGES_DEPLOY_TOKEN`).
3. Once they confirm the secret exists, set
   `github_token: ${{ secrets.<THEIR_SECRET_NAME> }}` in
   `.github/workflows/pages.yml`'s deploy step (update the name if it
   differs from `PAGES_DEPLOY_TOKEN`).
4. If a fine-grained PAT was already tried and the deploy step 403s
   (`gh run view <id> --log-failed` shows `Permission ... denied` /
   `403` on the `git push origin gh-pages` line), tell the user to replace
   it with a classic `repo`-scope token instead — update the same secret's
   value, no workflow change needed since the secret name doesn't change.

If `pages/` and the workflow already exist and this step was skipped when
they were first created, this is a live-fixable gap — no need to redo Steps
1–4, just add the secret and the one-line workflow change, then re-run
(`gh workflow run pages.yml --ref main`) to get the first PAT-authored push.

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
  -f "build_type=legacy"
```

If this 409s ("already exists"), Pages is already configured — use `PUT`
with the same body instead. **Use `build_type=legacy` here, not
`workflow`** — despite the Actions workflow being the thing that builds the
site, `peaceiris/actions-gh-pages` publishes by pushing a plain commit to
`gh-pages` ("Deploy from a branch" in GitHub's own terms), which is exactly
what `build_type=legacy` + `source.branch=gh-pages` means to the Pages API.
`build_type=workflow` is reserved for the *native* Pages Actions flow
(`actions/upload-pages-artifact` + `actions/deploy-pages`), which this
skill's workflow does not use. Setting `build_type=workflow` here doesn't
error — it just silently ignores `source.branch` (GET afterwards shows it
reset to `main`/default) and the site never actually deploys, so this is
easy to get wrong without noticing until you check the live URL and find a
404. See `references/jekyll-and-pages.md` for the API details and how to
tell the two modes apart if you inherit a misconfigured site.

## Step 6 — Verify

```bash
gh api repos/SenolIsci/mykg/pages --jq '{status, html_url, source, build_type}'
```

Confirm `build_type` is `"legacy"` and `source.branch` is `"gh-pages"` — if
`build_type` came back `"workflow"` and `source.branch` shows anything other
than `gh-pages` (e.g. it reset to `main`), the POST/PUT silently didn't take
per the note in Step 5; redo it with `build_type=legacy`. Only once that
shape is confirmed, tell the user the expected URL
(`https://senolisci.github.io/mykg/`) and that the very first build can take
a few minutes. Don't poll in a sleep loop — check once now, and again only
if the user asks later.

## Maintenance tasks (pages/ + workflow + gh-pages already set up)

**Adding a new page** — drop the file under `pages/`, push to `main`; the
workflow rebuilds and redeploys automatically. Add a link from `index.md` or
the relevant nav — a page with no incoming link still builds and is
reachable by direct URL, but is invisible to a visitor browsing the site.

**Adding a new blog post** — drop it in `pages/_posts/` as
`YYYY-MM-DD-slug.md` with the same front matter shape as existing posts;
`pages/blog.md`'s `site.posts` loop picks it up automatically, no manual
link needed.

**Adding a diagram** — confirm with the user which file and where it lives
in the repo (see "Sourcing artifacts from the repo" above), copy it into
`pages/diagrams/`, and link it from wherever it's relevant.

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

If none of the above explains it, or the failure is on the Pages-serving
side rather than the Jekyll-build side, check the official docs before
guessing further: https://docs.github.com/en/pages (see
`references/jekyll-and-pages.md` for the specific subsections most relevant
to this skill's setup).

**Actions run is green but the site 404s** — this is a Pages *configuration*
problem, not a build problem, and won't show up in `gh run view --log-failed`
at all. Check `gh api repos/SenolIsci/mykg/pages --jq '{source, build_type}'`:
if `build_type` is `"workflow"` instead of `"legacy"`, that's the bug —
see the note in Step 5/6. Fix with the `PUT` call there (`build_type=legacy`,
`source.branch=gh-pages`), no rebuild needed since `gh-pages` already has the
content — Pages just wasn't configured to serve it.

**`build_type`/`source` are already correct, Actions is green, `gh-pages`
genuinely has `index.html` and real assets (confirm with `git ls-tree -r
--name-only origin/gh-pages`), but the URL still 404s and `status` stays
`null` no matter how many times you re-run the workflow** — this is the
`GITHUB_TOKEN` issue from Step 4a, not the `build_type` one above; the two
produce an identical symptom (green build, valid branch, dead site) but have
different causes and different fixes, so don't assume it's the `build_type`
bug just because the symptom matches. GitHub does not trigger a Pages build
for a commit pushed with the default `GITHUB_TOKEN` — confirmed against
GitHub's own Actions token docs. Check
`grep github_token .github/workflows/pages.yml`; if it says
`secrets.GITHUB_TOKEN`, that's the cause. Fix per Step 4a: the user creates
a PAT + repo secret, you update the workflow to reference it, then
`gh workflow run pages.yml --ref main` to get the first PAT-authored push
through.

**The "Deploy to gh-pages" step itself fails** (not green — a real Actions
failure, distinct from the two silent-404 cases above) **with `remote:
Permission to <owner>/<repo>.git denied to <owner>` and exit code 128/403 on
`git push origin gh-pages`** — the PAT in the secret doesn't have write
access to the repo. `permissions: contents: write` in the workflow YAML
only grants the *default* `GITHUB_TOKEN` extra scope — it has no effect on
a PAT supplied via a secret, so don't waste time re-checking that block.
On the mykg setup, a fine-grained PAT scoped to the repo with "Contents:
Read and write" checked still produced this exact 403; switching the same
secret's value to a **classic** PAT with the `repo` scope fixed it
immediately with no other change. If the user reports they used a
fine-grained token, ask them to replace it with a classic one per Step 4a.

## What NOT to do

- Don't hand-edit anything on the `gh-pages` branch — it's fully
  regenerated by the workflow on every push to `main`; manual edits are
  silently overwritten on the next build.
- Don't touch `.github/workflows/ci.yml` or `release.yml` — Pages is
  independent of CI/release and shouldn't be threaded into those pipelines.
- Don't scan the repo for content to publish or assume any folder besides
  `pages/` itself is publishable. `README.md` is the only default source;
  anything else (diagrams, screenshots, other docs) is featured only when
  the user explicitly names it — see "Sourcing artifacts from the repo"
  above.
- Don't invent blog article content — the user supplies it.
