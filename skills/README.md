# Skills library

Skills teach the app how a kind of business runs: what to read in its statements, what healthy looks like, which
leaks to look for and what to ask a new owner. Each skill is one `*.skill.md` file. The format is documented in
[docs/skills/FORMAT.md](../docs/skills/FORMAT.md).

| File | Business type | Badge | Built in |
|---|---|---|---|
| [grocery.skill.md](grocery.skill.md) | Corner stores, mini-marts | Verified | yes |
| [fashion.skill.md](fashion.skill.md) | Clothing, shoes, accessories | Verified | yes |
| [general.skill.md](general.skill.md) | Any other shop (the fallback) | Verified | yes |
| [bakery.skill.md](bakery.skill.md) | Bakeries, patisseries, cake shops | Community, unverified | no: upload it |

The built-in skills are signed with the library key and load at startup. Every other skill is uploaded on the
opening screen ("Upload your own skill.md"), previewed, and only then used for a new business.

## Writing a skill

1. Copy the minimal example from [FORMAT.md](../docs/skills/FORMAT.md#minimal-example), or a skill here that is
   close to your business type, and give it its own `id`.
2. Describe your categories with keywords that appear in real statement rows, set the KPI healthy ranges, pick the
   built-in detectors that matter and set their thresholds.
3. Write the questions an experienced advisor for this business would ask, each with a one-line "why I'm asking".
4. Write the Markdown body for owners: what the business type is, what the skill watches and what it asks.

A skill holds settings, never code or instructions: it can only configure built-in detectors, and it cannot touch
policy, tiers, caps, mandates or the gateway. Money amounts do not belong in a skill (use ratios, counts and days).

## Validating

```text
make validate-skill FILE=skills/bakery.skill.md
```

It runs the same checks as an upload and prints the badge, the sha256 and what the skill asks and watches, or every
problem it found.

## Submitting

Open a pull request that adds your `*.skill.md` here, with a line in the table above. Say which kind of business it
is for and where its healthy ranges come from (they are shown to owners as synthetic benchmarks). Once reviewed, a
maintainer signs it with the library key (`scripts/sign_skill.py`), and it shows as Verified. Any later edit to a
signed file makes it unverified until it is signed again.
