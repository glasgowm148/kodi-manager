# Publishing the Kodi repository

The user-facing source is **https://glasgowm148.github.io/kodi-manager/**.
Users install `repository.kodi-manager.zip` once, then install Kodi Manager from
**Kodi Manager Repository (preview)**. See [the TV steps](setup.md).

## What is published

- The public landing page, practical guides, sitemap and static styles in `website/`.
- Explicit synthetic documentation images selected by the builder, without private output files.
- The repository installer, also listed in `addons.xml` so Kodi can update it.
- The newest published service ZIP, including releases marked prerelease, with its metadata and artwork.
- Older checksummed release ZIPs, so devices with a cached index can still download their selected version.
- `addons.xml.sha256`, a change indicator for Kodi's repository refresh.

The builder checks the ZIP against the release's `SHA256SUMS`, checks its ID/version/layout,
and copies the exact published ZIP. It never rebuilds service code from `main` for distribution.
The repository definition lives in `repository/addon.xml`; service sources remain canonical in `src/`.
GitHub Pages cannot supply custom package hash headers, so the repository uses HTTPS with
`hashes=false`. Published release checksums are verified during the build; they are not an
independent publisher signature.

## Automatic publication

`.github/workflows/repository.yml` runs after a successful **Release** workflow, when repository
infrastructure changes on `main`, or through **Actions → Publish Kodi repository → Run workflow**.
It selects the highest published numeric version (drafts excluded, previews included), downloads
the release assets, verifies them and deploys the complete Pages artifact. Serialized deployments
and selecting the highest version prevent an older release event from downgrading the index.

The GitHub repository's **Settings → Pages → Source** must be **GitHub Actions**. Workflow permissions
are limited to reading contents in the build job and Pages/OIDC deployment in the deploy job.
No separate hosting token is required. The release workflow's normal `GITHUB_TOKEN` does not
trigger another workflow via a release event; `workflow_run` handles this instead.

## Reproduce locally

Download a published service ZIP and its `SHA256SUMS` into an empty folder, then run:

```sh
python scripts/build_repository.py \
  --addon release/service.kodi.addonadmin-0.7.43.zip \
  --checksums release/SHA256SUMS --output dist/repository
```

The output directory must be empty. Run `python -m pytest -q tests/test_repository.py`
for layout, checksum refusal, version selection and deterministic installer checks.
CI also builds the repository from the checked release artifacts.

Run `python scripts/check_website.py dist/repository` on the complete artifact to check local
links (including the installer), canonical URLs, the sitemap, descriptions and structured data.
The source URL, repository ZIP, add-on index and package URLs remain the same when website
content changes. Do not add client-side routing, authentication or redirects to those paths.
See [website discovery and measurement](discovery.md) for editorial and indexing guidance.

## Recovery and checks

After deployment, check the source page, installer ZIP, `addons.xml`, checksum and every package
and artwork URL referenced by the index. A local archive/HTTP check does not prove installation
on real hardware; perform TV navigation only with authorization and known viewing state.

If publication fails, the previous Pages deployment remains available. Fix the build/deployment
and rerun the workflow. To restore a prior site, rerun its successful deployment job/artifact in
GitHub Actions while investigating; do not silently replace a published service ZIP.
Kodi will not normally downgrade an installed higher version: a deliberate downgrade requires
selecting a known older release manually with appropriate backups. Pause new service releases
while investigating an unsafe update. Users can turn off **Auto-update** for Kodi Manager.
