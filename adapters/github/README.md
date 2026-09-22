# GitHub Actions adapter

Copy `check-kit.yml` into this kit repo (or a product that vendors the kit) as `.github/workflows/check-kit.yml`.

The kit ships the workflow here rather than under `.github/` so a push works without the GitHub `workflow` OAuth scope; install is one copy.

```bash
mkdir -p .github/workflows
cp adapters/github/check-kit.yml .github/workflows/check-kit.yml
```
