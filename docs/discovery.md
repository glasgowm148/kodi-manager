# Public website and discovery

The website is https://glasgowm148.github.io/kodi-manager/. Its HTML source is in `website/`;
it is separate from the installed dashboard's canonical `web/` assets. Edit the HTML directly.
The existing repository builder adds only explicitly selected synthetic documentation images.
No household configurations, logs, history, screenshots or private output directories are published.

## Reader questions

| Page | Question answered |
| --- | --- |
| Landing page | How do I manage Kodi from a browser and install the service? |
| `edit-kodi-addon-settings-browser/` | Can I find and edit an add-on setting on my phone? |
| `backup-restore-kodi-settings/` | What does a configuration backup restore, and how can I undo it? |
| `kodi-manager-vs-kore-yatse-chorus/` | Do I need a remote, a media web interface or a maintenance dashboard? |

Comparison pages disclose maintainer authorship, link to competitors' primary documentation and
describe where each tool fits. Do not claim comparative speed, universal support, customer results
or independent endorsement without evidence. Keep preview and live-validation limits visible.

## Publishing and checks

The [repository workflow](repository.md) deploys content changes on `main` together with the
checksum-verified published packages. It does not rebuild or replace service releases for a docs change.
Run `scripts/check_website.py` against the complete built artifact. Check desktop/mobile layout,
external links, image descriptions and the installation instructions before publishing.

Every page has server-rendered HTML, a unique title and description, a canonical URL and internal
links. Structured data describes only visible facts; never add invented ratings or review counts.
Update the guide's reviewed date, JSON-LD `dateModified` and sitemap `lastmod` when its content changes.
Keep the existing repository source URL and its direct ZIP link available to Kodi's installer.

GitHub Pages serves this as a project path on a shared origin. Only the origin-root `/robots.txt`
controls crawling; a `robots.txt` inside `/kodi-manager/` would not. At publication the origin-root
file returned 404, which does not block crawling. If an account-level site later adds rules, check
that they allow these pages and OAI-SearchBot. Do not add a redundant project-level robots file.

Google says ordinary search eligibility and useful original content also apply to its AI features;
no special AI files or schema are required. OpenAI identifies OAI-SearchBot as its search crawler.
Being accessible does not guarantee indexing, inclusion, ranking or an assistant recommendation.

- [Google: AI features and your website](https://developers.google.com/search/docs/appearance/ai-features)
- [OpenAI: crawler controls](https://developers.openai.com/api/docs/bots)
- [Public sitemap](https://glasgowm148.github.io/kodi-manager/sitemap.xml)

## Measure the right thing

The site has no analytics scripts or cookies set by project code. GitHub Pages hosting has its own
[data collection](https://docs.github.com/en/pages/getting-started-with-github-pages/about-github-pages#data-collection).
GitHub repository Traffic reports measure repository visits, not visits to this Pages site, installs,
successful setups or signups. A missing ChatGPT referrer in its short report is not proof of zero traffic.

The maintainer can verify the exact Pages URL-prefix property in Google Search Console and submit
`sitemap.xml`; keep verification files separate from private account credentials. This has not been
claimed as completed. Record index coverage and impressions after recrawling, rather than treating
an immediate branded search as a test of indexing.

If privacy-respecting site analytics are deliberately added later, recognize `chatgpt.com` referrers
and `utm_source=chatgpt.com`, which OpenAI documents in its
[publisher FAQ](https://help.openai.com/en/articles/12627856). Never collect TV addresses, tokens,
settings, diagnostic text or personal histories. Keep visits, downloads and completed setups as
separate measures. Do not add tracking solely to manufacture a referral claim.
