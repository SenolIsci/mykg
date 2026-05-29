# Demo input — mixed-format showcase

This folder contains a tiny mixed-format corpus used by the
`Other input formats` section of the top-level README.

Contents:
- `sample.html` — an HTML page with headings, lists, and a table. Converted
  by the in-process `markdownify` path; no MinerU install required.

To add a PDF for the full demo, drop a small (<1 MB) public-domain PDF here
as `sample.pdf`. The `preprocess` step will route it through MinerU once
`pip install 'mykg[mineru]'` is installed.

Quick demo (no MinerU needed for HTML):

```bash
mykg convert -i ./blog_demo_input -o /tmp/mykg-demo-out -w 1
ls /tmp/mykg-demo-out
# expect: sample.md  sample.mineru.json
```
