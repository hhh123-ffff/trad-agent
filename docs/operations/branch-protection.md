# Branch Protection

Use this checklist to protect `main` after the CI workflow has run at least once.

## Recommended Rule

Create a branch rule or ruleset targeting:

```text
main
```

Enable:

- Require a pull request before merging
- Require status checks to pass before merging
- Require branches to be up to date before merging
- Block force pushes
- Block deletions

## Required Status Check

Select the GitHub Actions check created by `.github/workflows/ci.yml`:

```text
Backend and frontend checks
```

Depending on GitHub UI wording, it may appear as:

```text
CI / Backend and frontend checks
```

## Merge Discipline

Before merging product changes, confirm the PR has:

- backend tests passing;
- Python compile check passing;
- frontend production build passing;
- a short explanation of data-source and compliance impact.

For this product, PRs must preserve the boundary that MarketLens is a replay and information-organization tool. It must not become a trade execution, buy/sell recommendation, target-price, position-sizing, or guaranteed-return product.
