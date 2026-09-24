# Writing evaluators — code, LLM-judge, and rubric patterns

Three shapes, all from `phoenix.evals`, confirmed working end-to-end against
a live Phoenix instance. See SKILL.md's "Writing evaluators" for the
one-line decision rule on which to reach for; this file has the actual code.

## Code-based

Deterministic, no LLM call — cheap, exact, use whenever the check is a real
assertion rather than a judgment call:
```python
from phoenix.evals import create_evaluator, evaluate_dataframe

@create_evaluator(name="edge_endpoints_exist", kind="code")
def edge_endpoints_exist(output: dict, metadata: dict) -> bool:
    node_ids = {n["id"] for n in metadata["nodes"]}
    return output["from"] in node_ids and output["to"] in node_ids

results_df = evaluate_dataframe(dataframe=df, evaluators=[edge_endpoints_exist])
```
`evaluate_dataframe` takes **keyword args only** now (`dataframe=`,
`evaluators=` — positional args are deprecated and print a warning). The
decorated function's parameter names (`output`, `input`, `expected`,
`metadata` — any subset, any order) are matched against columns of the same
name in the DataFrame you pass in; Phoenix injects by name via introspection,
so name your DataFrame columns to match what the evaluator function expects.
Result lands in a new `<name>_score` column, a dict:
`{name, score, label, metadata, kind, direction}`.

## LLM-as-judge (binary or simple multi-class) — the default for judgment calls

Use when the check requires judgment ("is this grounded in the text", "is
this relationship type plausible") — not just "does this exist / does this
equal that":
```python
from phoenix.evals import ClassificationEvaluator, LLM

llm = LLM(provider="openai", model="gpt-5.4-mini-2026-03-17")  # match the target pipeline's active model, or use a cheaper judge model deliberately

judge = ClassificationEvaluator(
    name="edge_type_plausible",
    llm=llm,
    prompt_template=(
        "Source text: {text}\n"
        "Extracted edge: {edge_type} from {edge_from} to {edge_to}\n"
        "Is this edge type a plausible relationship given the source text? "
        "Answer only: plausible or implausible."
    ),
    choices={"plausible": 1.0, "implausible": 0.0},
    include_explanation=True,  # default True — keep it, explanations are what make a failing eval debuggable
)
results_df = evaluate_dataframe(dataframe=df, evaluators=[judge])
```
`{placeholders}` in `prompt_template` are filled from DataFrame columns of
the same name — same column-name-matching mechanism as code evaluators.
`choices` maps the judge's answer label to a numeric score; a 3-way
classification (e.g. `{"fully_grounded": 1.0, "partially_grounded": 0.5,
"hallucinated": 0.0}`) is still this same pattern, just with a third label —
reach for it when binary genuinely loses a distinction worth keeping, before
jumping all the way to a full rubric.

Use `bind_evaluator(evaluator, input_mapping)` when the span DataFrame's
column names don't already match the evaluator's expected parameter/template
names (e.g. mapping `attributes.llm.output_messages` → `output`) instead of
renaming columns by hand every time — it's reusable across runs.

## Rubric-based judging — the fallback when one axis can't capture it

**Default to plausible/implausible (or another simple 2-3 way
classification) first — only reach for a full rubric when one axis
genuinely can't capture the judgment.** Most per-item checks really are one
binary question, and a plain classification judge is cheaper to write,
cheaper to run, and easier to read in aggregate (a pass rate) than a rubric
would be for the same question. Escalate past binary only when the thing
you're really asking "how good is this, overall" about has more than one
genuinely independent dimension — e.g. schema quality is not one question,
it's at least "does it cover what's in the corpus" (completeness) and "does
it avoid inventing things" (precision), and a schema can score high on one
while scoring low on the other. Forcing those two into one binary judgment
collapses information the eval exists to surface — the score tells you
*that* something's off without telling you *what*, and "what" is the
actionable part. That's the one case for a rubric: **use it when you can
name more than one axis the same input could independently succeed or fail
on**, not as a default upgrade over binary judging.

A rubric, when it's warranted, asks the judge to score each dimension
separately, against explicit written criteria for what a low/medium/high
score on that dimension actually looks like — the same reason a detailed
grading rubric produces more consistent, more actionable grades from a
human reviewer than "rate this 1-10" does.

Concretely, this is still a `ClassificationEvaluator` per dimension (not a
new API) — the rubric is the discipline of writing several of these instead
of one all-purpose judge, each with criteria specific enough that two
different judge calls would reach the same verdict on the same input:

```python
schema_completeness_judge = ClassificationEvaluator(
    name="schema_completeness",
    llm=llm,
    prompt_template=(
        "Corpus excerpt: {corpus_sample}\n"
        "Induced schema concepts: {concepts}\n"
        "Induced schema properties: {properties}\n\n"
        "Rate schema COMPLETENESS against this rubric:\n"
        "- excellent: every entity type and relationship type visible in the "
        "excerpt has a corresponding schema concept/property; nothing "
        "obvious is missing\n"
        "- adequate: the main entity/relationship types are covered, but "
        "some secondary or less-obvious ones from the excerpt are missing\n"
        "- poor: significant entity or relationship types visible in the "
        "excerpt have no corresponding schema element\n"
        "Answer only: excellent, adequate, or poor."
    ),
    choices={"excellent": 1.0, "adequate": 0.6, "poor": 0.0},
    include_explanation=True,
)

schema_precision_judge = ClassificationEvaluator(
    name="schema_precision",  # a SEPARATE dimension -- completeness and
    llm=llm,                  # precision can move independently: a schema
    prompt_template=(         # can be complete but also bloated with
        "Corpus excerpt: {corpus_sample}\n"          # concepts nothing in
        "Induced schema concepts: {concepts}\n\n"    # the corpus actually
        "Rate schema PRECISION against this rubric:\n"  # needs
        "- excellent: every concept/property is clearly grounded in "
        "something present in the excerpt; nothing feels invented or "
        "overly narrow (e.g. a named-entity masquerading as a type)\n"
        "- adequate: mostly grounded, with one or two concepts that feel "
        "speculative or too narrow\n"
        "- poor: multiple concepts don't correspond to anything actually "
        "visible in the excerpt, or are so narrow they're really instances\n"
        "Answer only: excellent, adequate, or poor."
    ),
    choices={"excellent": 1.0, "adequate": 0.6, "poor": 0.0},
    include_explanation=True,
)
```
Run both, report both separately (don't average them into one number unless
the user specifically wants a single pass/fail gate) — a schema that's
`excellent` on completeness but `poor` on precision is a genuinely different
problem (over-generation) than the reverse (under-extraction), and
collapsing them loses exactly the information that makes the eval useful
for deciding what to fix. When choosing rubric levels, prefer 3-4 named
levels with a one-sentence description of each over a bare 1-10 numeric
scale — a judge (like a human) is far more consistent picking the best-fit
description than picking a number, since "adequate" has a specific written
meaning but "6" doesn't.
