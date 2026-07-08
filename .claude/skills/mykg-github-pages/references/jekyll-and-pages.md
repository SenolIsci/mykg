# GitHub Pages + Jekyll + Actions — reference details

Background for the choices baked into SKILL.md. Read this when troubleshooting,
or when the user wants to deviate from the defaults (different theme, custom
domain, different trigger paths).

**Official docs**: https://docs.github.com/en/pages — the authoritative
source for anything not covered here or in SKILL.md, especially when
GitHub's Pages behavior changes or a new failure mode shows up that isn't
already documented in this file. Check here before guessing at API shapes
or config semantics; this file's `build_type` guidance below was itself
wrong until corrected against these docs, so treat undocumented assumptions
about Pages behavior with suspicion. Relevant subsections:
- REST API reference: https://docs.github.com/en/rest/pages/pages
- Configuring a publishing source: https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
- Troubleshooting Jekyll build errors: https://docs.github.com/en/pages/setting-up-a-github-pages-site-with-jekyll/troubleshooting-jekyll-build-errors-for-github-pages-sites
- Custom domains: https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site

## Why `gh-pages` + Actions instead of GitHub's native Jekyll build

GitHub Pages can build Jekyll for you automatically ("classic" / `legacy`
build_type, source = a branch + path like `main` + `/docs`). That's simpler,
but couples the *source* branch to the *served* branch — anyone browsing
`main` sees both software and a folder that's really build input for a
website. The `gh-pages` branch approach cleanly separates "what we wrote" from
"what got built," at the cost of one more moving part (a workflow file).

This skill defaults to the `gh-pages` + Actions approach because that's what
the user chose for mykg. If a future user of this skill wants the simpler
native build instead, the difference is:

- No workflow file, no `gh-pages` branch.
- `pages/_config.yml` is the same file either way — the native builder
  honors it too.
- `gh api -X POST repos/{owner}/{repo}/pages -f "source[branch]=main" -f
  "source[path]=/pages" -f "build_type=legacy"` instead of pointing at
  `gh-pages`.
- Theme choice is constrained to GitHub's supported-themes list in native
  mode; the Actions build can use any theme gem from rubygems.org since it's
  a real `bundle install` + `jekyll build`.

**Important:** despite this skill using a custom Actions workflow to *build*
the site, the Pages API `build_type` for it is still `"legacy"`, not
`"workflow"`. GitHub's own docs draw the line at *how the branch gets its
content*, not at whether a workflow was involved in producing it:
- `build_type: "legacy"` = "Deploy from a branch" — Pages watches a branch
  (here, `gh-pages`) and serves whatever's pushed to it, however it got
  there. `peaceiris/actions-gh-pages` pushes a plain git commit to
  `gh-pages`, so from Pages' point of view this is indistinguishable from a
  human running `git push` by hand — hence `legacy`.
- `build_type: "workflow"` = "GitHub Actions" as the *Pages source itself* —
  this expects the workflow to upload a build artifact via
  `actions/upload-pages-artifact` and hand it to Pages via
  `actions/deploy-pages`. There is no branch involved at all in this mode;
  `source.branch` is meaningless and gets ignored/reset.
Setting `build_type: "workflow"` while deploying via a branch push (this
skill's actual setup) doesn't error — the API call succeeds — but Pages
silently does not serve the `gh-pages` content, and a follow-up `GET` shows
`source.branch` reverted away from `gh-pages`. The only symptom is the live
URL 404ing. See "Build logs" below for how to confirm the fix.

## Why the site source is a dedicated `pages/` folder

Publishing straight from a general-purpose folder (whatever it's named)
means maintaining an ever-growing `exclude:` list in `_config.yml` as
unrelated content lands there over time. A dedicated `pages/` folder means
the publish surface is exactly what was deliberately written for the site —
see SKILL.md's "Why a dedicated pages/ folder" section for the full
reasoning. Other repo artifacts (diagrams, screenshots, logo variants) are
still fair game to feature on the site — they're copied into `pages/` only
when the user names them explicitly (see "Sourcing artifacts from the repo"
in SKILL.md), not pulled in wholesale from wherever they happen to live.

## REST API shape for `/repos/{owner}/{repo}/pages`

```
GET    /repos/{owner}/{repo}/pages         → current config, 404 if none
POST   /repos/{owner}/{repo}/pages         → create (409 if already exists)
PUT    /repos/{owner}/{repo}/pages         → update existing config
DELETE /repos/{owner}/{repo}/pages         → turn Pages off entirely
```

Request body (POST/PUT), gh-pages-branch shape — note `build_type: "legacy"`
even though a workflow builds it (see the callout above):

```json
{
  "source": { "branch": "gh-pages", "path": "/" },
  "build_type": "legacy"
}
```

Response body shape (GET/POST) once correctly configured:

```json
{
  "url": "https://api.github.com/repos/OWNER/REPO/pages",
  "status": null,
  "cname": null,
  "custom_404": false,
  "html_url": "https://OWNER.github.io/REPO/",
  "build_type": "legacy",
  "source": { "branch": "gh-pages", "path": "/" },
  "public": true,
  "https_enforced": true
}
```

If a `GET` instead shows `build_type: "workflow"` and/or `source.branch`
pointing at `main` (or anything other than `gh-pages`) after you tried to set
it to `gh-pages`, that's the `build_type` mismatch described above — redo
the `PUT` with `build_type=legacy`.

`status` values per GitHub's API docs: `null` (no build recorded — this is
normal and can persist even on a working legacy-branch site, since branch
deploys don't always populate this field the way the native builder does),
`"queued"`, `"building"`, `"built"`, `"errored"`. Only `"errored"` needs
follow-up. Don't treat a lingering `null` as a sign the fix didn't work —
verify with `curl -I` against the live `html_url` instead; a `200` there is
the real signal, not the `status` field.

Required auth: a token with `repo` scope (classic PAT) or the fine-grained
"Pages: write" permission; repo admin/maintainer role. `gh api` reuses
whatever `gh auth status` already has — check that first if a call 403s
unexpectedly (`gh auth status`, confirm `repo` is in the token scopes).

## Build logs when the Actions build itself is fine but Pages shows errored

Two different failure surfaces exist and it's easy to check the wrong one:

- **The Actions workflow run** (`gh run list --workflow=pages.yml`, `gh run
  view <id> --log-failed`) — covers the Jekyll build step and the
  `actions-gh-pages` push step. Most real build failures show up here. A
  green run here only proves the `gh-pages` branch got updated — it says
  nothing about whether Pages is actually configured to serve it (see the
  `build_type` mismatch above).
- **The Pages build record** (`gh api repos/{owner}/{repo}/pages/builds/latest`)
  — relevant in `build_type: legacy` mode (what this skill uses, per the
  correction above): Pages detects the push to `gh-pages` and does its own
  lightweight "deploy the static files" pass, recorded here. If the Actions
  run is green but this endpoint 404s or errors, or the live site still
  404s, re-check `gh api repos/{owner}/{repo}/pages --jq '{source,
  build_type}'` first — a `build_type: "workflow"` misconfiguration (Pages
  never even looking at `gh-pages`) is a more common cause than an actual
  deploy failure.

## Jekyll front-matter gotcha

Any file under `pages/` starting with `---` on line 1 is parsed by Jekyll as
YAML front matter, even `.md` files that aren't meant to have any. A file
that happens to start with a Markdown horizontal rule (`---`) as its very
first line will break the build with a YAML parse error. If a build fails
with a cryptic Psych/YAML error, check for this first — it's the single most
common cause of "worked yesterday, fails today" after someone edits an
existing page.

## GitHub-supported Jekyll themes (native build only)

`jekyll-theme-minimal`, `jekyll-theme-cayman`, `jekyll-theme-slate`,
`jekyll-theme-architect`, `jekyll-theme-dinky`, `jekyll-theme-hacker`,
`jekyll-theme-leap-day`, `jekyll-theme-merlot`, `jekyll-theme-midnight`,
`jekyll-theme-modernist`, `jekyll-theme-tactile`, `jekyll-theme-time-machine`.
Since mykg uses the Actions build, any theme gem works — this list matters
only if switching back to the native build flow (see above), or if the user
wants to stick to a "no surprises, definitely works" theme choice anyway.

## Custom domain (CNAME)

Two halves, both required, neither sufficient alone:

1. **Repo side** — a `CNAME` file (no extension) containing just the domain,
   placed at `pages/CNAME` (Jekyll copies non-underscore-prefixed files
   verbatim into `_site/`, so it lands at the root of the built output). Or
   set it via the API: `PUT` with `"cname": "example.com"` in the body — but
   the file is more durable since it survives a Pages config reset.
2. **DNS side** — the user creates a `CNAME` record (subdomain) or `A`/`ALIAS`
   records (apex domain) at their registrar pointing at
   `senolisci.github.io`. This is entirely outside GitHub and outside
   anything `gh` or this skill can do — say so plainly rather than implying
   the repo-side change is the whole job.

GitHub re-verifies domain ownership periodically; `protected_domain_state` in
the GET response reflects this (`verified`, `pending`, `unverified`).

## `workflow_dispatch` for manual reruns

The bundled workflow template includes `workflow_dispatch:` specifically so
a content-only fix (typo, broken image path) can be rebuilt without an empty
commit — `gh workflow run pages.yml`. Worth mentioning to the user once,
since it's a small but genuinely convenient escape hatch they might not
discover on their own.
