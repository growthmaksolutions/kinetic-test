# Migrating a Next.js Storefront to a Shopify (Liquid) Theme

A complete, practical guide for taking an existing Next.js e‑commerce site and rebuilding it
as a native Shopify theme using Liquid, then uploading and developing it inside Shopify.

> This guide assumes the **classic Liquid theme** path (the standard for most stores and agencies),
> not Hydrogen/headless. A short section at the end explains when to choose Hydrogen instead.

---

## 0. The mental model shift (read this first)

This is the single most important section. If you internalize the model, everything else is mechanical.

| Next.js world | Shopify Liquid world | What changes |
|---|---|---|
| React components (`.tsx`) render in browser + server | **Liquid** templates render **only on Shopify's servers**, output static HTML | No client-side rendering of content. JS is layered *on top* of finished HTML (progressive enhancement). |
| `useState`, `useEffect`, hooks, client state | Plain JS in `assets/*.js` + the **Ajax Cart API** | No React runtime. Interactivity = vanilla JS / Alpine / web components. |
| `getServerSideProps` / `fetch()` your own API | Liquid **objects** (`product`, `collection`, `cart`) are injected automatically | You don't fetch data — Shopify hands it to the template. |
| Your own DB / CMS / Stripe | Shopify is the backend: catalog, cart, checkout, customers, payments | You **migrate data into Shopify**, you don't build APIs. |
| `app/` or `pages/` routing | Fixed **template** names mapped to URLs by Shopify | You can't invent arbitrary routes the same way. URLs are structured. |
| `.env`, server secrets | **Theme settings** (`settings_schema.json`) + section schema | Merchants edit content in the Theme Editor, not in code. |
| Tailwind / CSS modules / styled-components | Plain CSS/SCSS in `assets/`, or Tailwind via a build step | CSS is fine; the build pipeline is simpler/optional. |
| Checkout = your Stripe flow | Shopify **Checkout** (not themeable on most plans) | You stop at "Add to cart" → Shopify owns checkout. |

**Golden rule:** In Next.js you build an *app that fetches data*. In Shopify you build *templates that receive data*. Stop thinking "fetch and render," start thinking "Shopify gives me `product`, I lay it out."

---

## 1. Theme anatomy (what folders you'll create)

A Shopify theme has a **fixed folder structure** (this repo is a live example):

```
theme/
├── layout/
│   └── theme.liquid          # The <html> shell. Like Next.js _document.tsx / root layout.
│   └── password.liquid        # Shown when store is password-protected
├── templates/                 # One file per page TYPE. Maps to URLs.
│   ├── index.json             # Homepage          → /
│   ├── product.json           # Product page      → /products/:handle
│   ├── collection.json        # Collection page   → /collections/:handle
│   ├── cart.json              # Cart              → /cart
│   ├── page.json              # Generic CMS page  → /pages/:handle
│   ├── page.about.json        # Custom page tmpl  → /pages/about (alternate template)
│   ├── blog.json / article.json / search.json / 404 ...
├── sections/                  # Reusable, configurable page blocks (the heart of a theme)
│   ├── hero.liquid
│   ├── header.liquid / footer.liquid
│   ├── main-product.liquid    # The product-page body
│   └── *-group.json           # Grouped sections (header-group, footer-group)
├── snippets/                  # Small partials, included with {% render %}
│   └── product-card.liquid    # Like a small presentational React component
├── assets/                    # CSS, JS, images, fonts. Served from Shopify CDN.
│   ├── base.css / theme.js / *.js
├── config/
│   ├── settings_schema.json   # Global theme settings (colors, fonts, logo)
│   └── settings_data.json     # The saved values (auto-managed by the editor)
└── locales/
    └── en.default.json        # Translatable strings (i18n)
```

### How the pieces relate
- **`layout/theme.liquid`** wraps every page. It has `<head>`, global CSS/JS, and a single `{{ content_for_layout }}` where the page's template renders.
- **Templates** (`.json`) are mostly **lists of sections** with saved settings. They decide *which sections appear in what order*.
- **Sections** (`.liquid`) are the real building blocks — markup + a `{% schema %}` describing editable settings. Merchants add/remove/reorder them in the Theme Editor.
- **Snippets** are dumb partials you `{% render 'product-card', product: product %}` — the closest thing to a presentational React component.

> **Map it to Next.js:** `theme.liquid` ≈ root `layout.tsx`; a template `.json` ≈ a page that composes sections; a `section` ≈ a configurable layout component; a `snippet` ≈ a small reusable component; `assets/` ≈ `public/` + your client JS.

---

## 2. Tooling & local setup

### Install the Shopify CLI
```bash
# macOS
brew install shopify-cli
# or via npm
npm install -g @shopify/cli @shopify/theme

shopify version
```

### Create a fresh theme to build into
You have two starting points:

**A. Start from Shopify's reference theme (recommended)** — gives you working cart, product, search, customer accounts for free, so you only re-skin:
```bash
shopify theme init my-store-theme   # pulls Dawn (Shopify's reference theme)
cd my-store-theme
```

**B. Start empty** — only if you truly want full control and will rebuild cart/search/account plumbing yourself (more work, more bugs).

### Connect to a dev store and run live preview
```bash
shopify theme dev --store your-store.myshopify.com
```
This:
- Opens a local URL with **hot reload** (edit `.liquid` → browser updates).
- Renders against **real store data** (products, collections you've created).

This is your `next dev` equivalent. Keep it running while you port pages.

> If you don't have a store yet, create a free **Shopify Partner** account → create a **development store** (free, unlimited time for building).

---

## 3. The migration plan (recommended order)

Do it in this sequence — each step unblocks the next:

1. **Data first** — get products/collections/pages into Shopify so templates have something to render.
2. **Global shell** — `theme.liquid`, header, footer, fonts, global CSS, design tokens.
3. **Reusable snippets** — product card, buttons, icons (your shared components).
4. **Homepage** — usually the most "designed," but uses snippets you just built.
5. **Collection (PLP)** and **Product (PDP)** — the commerce core.
6. **Cart** + add-to-cart JS.
7. **Content pages** — about, contact, FAQ, blog.
8. **Search, 404, customer account** — often inheritable from Dawn.
9. **Settings/theme editor wiring** — expose content as schema so the merchant can edit.
10. **QA, performance, launch.**

---

## 4. Migrating your DATA into Shopify

Your Next.js site got data from a DB/CMS/Stripe. In Shopify, that data must live in Shopify.

| Your Next.js data | Where it goes in Shopify | How |
|---|---|---|
| Products (name, price, variants, images) | **Products** | CSV import (Admin → Products → Import), or Admin API, or an app like Matrixify |
| Categories | **Collections** (manual or automated by tag/condition) | Admin UI or API |
| Marketing pages (About, FAQ) | **Pages** (Online Store → Pages) | Paste content, or API |
| Blog posts | **Blog / Articles** | Import or API |
| Customers | **Customers** | CSV import (passwords don't transfer — they re-set) |
| Orders (historical) | Orders (import is limited) | Usually via Matrixify/app; keep old system read-only |
| Reviews | Review **app** (Judge.me, Loox, etc.) | This repo integrates Judge.me — see `sections/judgeme-widget.liquid` |
| Arbitrary structured content | **Metafields** / **Metaobjects** | Admin → Settings → Custom data, or API |

### Key idea: Metafields & Metaobjects = your custom CMS fields
Anything in your Next.js data model that isn't a native Shopify field (e.g. "compatible motorcycle models," "spec sheet," "ingredient list") becomes a **metafield** on the product/collection, or a **metaobject** (a custom content type). You read them in Liquid:

```liquid
{{ product.metafields.custom.spec_sheet.value }}
{{ collection.metafields.custom.banner_image | image_url: width: 1600 | image_tag }}
```

> Plan your metafield namespace/keys early — it's the schema bridge between your old data model and Liquid.

---

## 5. Migrating the global shell (`layout/theme.liquid`)

Your Next.js root layout → `layout/theme.liquid`. Minimal shape:

```liquid
<!doctype html>
<html lang="{{ request.locale.iso_code }}">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ page_title }}</title>
    {{ content_for_header }}   {%- comment -%} REQUIRED: Shopify injects analytics, etc. {%- endcomment -%}

    {{ 'base.css' | asset_url | stylesheet_tag }}
    <script src="{{ 'theme.js' | asset_url }}" defer></script>
  </head>
  <body>
    {% sections 'header-group' %}     {%- comment -%} announcement bar + header {%- endcomment -%}

    <main>
      {{ content_for_layout }}        {%- comment -%} the page template renders here {%- endcomment -%}
    </main>

    {% sections 'footer-group' %}
  </body>
</html>
```

- `{{ content_for_header }}` **must** be present (Shopify injects required scripts).
- `{{ content_for_layout }}` is where the active template renders — your `{children}`.
- Global CSS/JS go through `asset_url` so they're served from the CDN and cache-busted.

### Design tokens / fonts
- Port your CSS variables straight into a global stylesheet (`assets/base.css`). CSS is CSS.
- Tailwind: you *can* use it — run a build step that outputs a single CSS file into `assets/`. But many Shopify devs drop Tailwind in favor of plain CSS + theme-setting-driven variables, because Tailwind's purge/build adds friction with the Theme Editor. Decide based on how much your design depends on it.
- Fonts: upload to `assets/` and `@font-face`, or use Shopify's `font_picker` settings + `font_face` filter.

---

## 6. Converting components → snippets & sections

This is the bulk of the work. The conversion rules:

### React presentational component → **snippet**
A pure component that takes props and renders markup becomes a snippet. Props become arguments.

**Next.js:**
```tsx
function ProductCard({ product, className }) {
  return (
    <article className={className}>
      <a href={`/products/${product.handle}`}>
        {product.compareAtPrice > product.price && <span className="badge">SALE</span>}
        <img src={product.featuredImage} alt={product.title} loading="lazy" />
      </a>
      <h3>{product.title}</h3>
      <span>{formatMoney(product.price)}</span>
    </article>
  );
}
```

**Liquid (`snippets/product-card.liquid`)** — see the real one in this repo:
```liquid
{%- comment -%} Accepts: product {Object}, class {String} {%- endcomment -%}
<article class="{{ class | default: 'product-card' }}">
  <a href="{{ product.url }}">
    {%- if product.compare_at_price > product.price -%}
      <span class="badge">SALE</span>
    {%- endif -%}
    {{ product.featured_image | image_url: width: 1200 | image_tag: loading: 'lazy', alt: product.title }}
  </a>
  <h3>{{ product.title }}</h3>
  <span>{{ product.price | money }}</span>
</article>
```
Call it with: `{% render 'product-card', product: product, class: 'grid-card' %}`

Conversion cheatsheet:
- `{condition && <X/>}` → `{%- if condition -%}...{%- endif -%}`
- `array.map(...)` → `{%- for item in array -%}...{%- endfor -%}`
- `formatMoney(x)` → `{{ x | money }}` (Liquid **filters** replace your util functions)
- `<img src loading="lazy">` → `image_url` + `image_tag` filters (gives you responsive `srcset` for free)
- Props → arguments passed in the `render` tag

### A configurable page block → **section**
If a component should be **editable by the merchant** (text, image, toggle), make it a section with a `{% schema %}`. The schema is what generates Theme Editor controls.

```liquid
{%- comment -%} sections/hero.liquid {%- endcomment -%}
<section class="hero" style="min-height: {{ section.settings.min_height }}px">
  <p class="eyebrow">{{ section.settings.eyebrow }}</p>
  <h1>{{ section.settings.heading }}</h1>
  <p>{{ section.settings.subtext }}</p>
  <a href="{{ section.settings.cta_url }}" class="btn">{{ section.settings.cta_label }}</a>

  {%- comment -%} Repeatable child items = "blocks" (like mapping over an array) {%- endcomment -%}
  <div class="chips">
    {%- for block in section.blocks -%}
      <a href="{{ block.settings.url }}" {{ block.shopify_attributes }}>{{ block.settings.label }}</a>
    {%- endfor -%}
  </div>
</section>

{% schema %}
{
  "name": "Hero",
  "settings": [
    { "type": "text",  "id": "heading",   "label": "Heading",  "default": "Precision Performance." },
    { "type": "text",  "id": "subtext",   "label": "Subtext" },
    { "type": "text",  "id": "cta_label", "label": "CTA label", "default": "Shop now" },
    { "type": "url",   "id": "cta_url",   "label": "CTA URL" },
    { "type": "range", "id": "min_height","label": "Min height","min": 300, "max": 800, "step": 20, "default": 540, "unit": "px" }
  ],
  "blocks": [
    { "type": "chip", "name": "Model chip", "settings": [
      { "type": "text", "id": "label", "label": "Label" },
      { "type": "url",  "id": "url",   "label": "Link" }
    ]}
  ],
  "presets": [ { "name": "Hero" } ]   // makes it addable from the editor
}
{% endschema %}
```

**Schema concepts (these have no Next.js equivalent — they're the "make it editable" layer):**
- `settings` → fields shown in the editor; read via `section.settings.<id>`.
- `blocks` → repeatable sub-items (slides, FAQ rows, chips). Loop with `section.blocks`.
- `presets` → makes the section addable to any page from the editor.
- `{{ block.shopify_attributes }}` → **must** be on each block's root element so the editor can select it.
- Setting types: `text`, `richtext`, `image_picker`, `url`, `color`, `range`, `select`, `checkbox`, `collection`, `product`, `font_picker`, `video`, etc.

> **Decision rule:** Static markup reused in code → **snippet**. Content a non-developer should edit in the admin → **section** with schema. A section can `{% render %}` snippets internally (this repo does exactly this — e.g. `sections/hero.liquid` + `snippets/section-hero.liquid`).

---

## 7. Routing & templates mapping

Shopify URLs are **fixed and resource-based**. You map your Next.js routes to template files:

| Next.js route | Shopify URL | Template file | Data object available |
|---|---|---|---|
| `app/page.tsx` | `/` | `templates/index.json` | — (compose sections) |
| `app/products/[handle]/page.tsx` | `/products/:handle` | `templates/product.json` → `sections/main-product.liquid` | `product` |
| `app/collections/[handle]/page.tsx` | `/collections/:handle` | `templates/collection.json` → `sections/main-collection.liquid` | `collection`, `collection.products` |
| `app/cart/page.tsx` | `/cart` | `templates/cart.json` | `cart` |
| `app/about/page.tsx` | `/pages/about` | `templates/page.about.json` | `page` |
| `app/blog/page.tsx` | `/blogs/:blog` | `templates/blog.json` | `blog`, `blog.articles` |
| `app/blog/[slug]/page.tsx` | `/blogs/:blog/:article` | `templates/article.json` | `article` |
| `/search` | `/search` | `templates/search.json` | `search` |
| `not-found.tsx` | any 404 | `templates/404.json` | — |

**Alternate templates** (your way to have multiple page layouts): `templates/page.about.json`, `templates/page.contact.json` — assigned per-page in the admin via the "Theme template" dropdown. This is how you get "custom layouts" without inventing routes.

> You **cannot** create arbitrary routes like `/dashboard/settings` in a Liquid theme. If you need that, it's an app or headless. For content, you're limited to products, collections, pages, blogs, articles, and their templates.

### Why templates are `.json` not `.liquid`
JSON templates are just an ordered list of sections + their saved settings — so merchants can reorder them in the editor. The real markup lives in the `main-*` section the JSON references. (Legacy `.liquid` templates exist but JSON is the modern standard.)

---

## 8. Data & business logic: Liquid objects + filters

You stop writing data-fetching code. Shopify injects **objects**; you read them.

```liquid
{{ product.title }}
{{ product.price | money }}
{{ product.description }}
{%- for variant in product.variants -%} {{ variant.title }} — {{ variant.price | money }} {%- endfor -%}

{%- for product in collection.products -%}
  {% render 'product-card', product: product %}
{%- endfor -%}

{{ cart.item_count }} items — {{ cart.total_price | money }}
```

Key objects: `product`, `collection`, `cart`, `customer`, `shop`, `blog`, `article`, `page`, `search`, `request`, `routes`, `settings`, `section`, `block`, `linklists` (menus).

**Filters replace your utility functions** — money formatting, image transforms, string ops, dates:
```liquid
{{ product.featured_image | image_url: width: 800 | image_tag: loading: 'lazy' }}
{{ 'now' | date: '%Y' }}
{{ product.title | escape | truncate: 40 }}
```

**Logic limits (important):** Liquid is intentionally limited — no arbitrary computation, no defining functions, no external `fetch`. Loops are capped (default 50 iterations unless you paginate). If your Next.js page did heavy client computation, you'll move it to:
- Liquid filters where possible,
- the **Storefront API** (client JS calling Shopify's GraphQL for dynamic data),
- or an embedded **app** for true backend logic.

---

## 9. Interactivity & state (replacing React)

No React runtime. Interactivity is **progressive enhancement**: server renders HTML, your JS in `assets/` enhances it. Common approaches:

- **Vanilla JS / Web Components** — what Dawn uses (`<product-form>`, `<cart-drawer>` custom elements). Clean and dependency-free.
- **Alpine.js** — lightweight, declarative, popular for Shopify if you miss JSX-ish reactivity.
- **Avoid** bundling all of React just to manage a dropdown.

### Cart = the Ajax Cart API (this is your "state management")
Add-to-cart, cart drawer, quantity updates all hit Shopify's cart endpoints from JS:
```js
// Add to cart
await fetch('/cart/add.js', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ id: variantId, quantity: 1 }),
});
// Read cart state
const cart = await (await fetch('/cart.js')).json();
// Update / change quantities
await fetch('/cart/change.js', { method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({ id: lineKey, quantity: 2 }) });
```
Endpoints: `/cart/add.js`, `/cart.js`, `/cart/change.js`, `/cart/update.js`, `/cart/clear.js`. This replaces your cart context/store.

### Dynamic product data on the client
Use the **Storefront API** (GraphQL) from JS for things like live inventory, predictive search, or anything that must update without a page reload.

---

## 10. Theme settings (replacing `.env` / config)

Global, merchant-editable settings live in `config/settings_schema.json` and are read via `settings.*`:
```liquid
<img src="{{ settings.logo | image_url: width: 300 }}">
<style>:root { --brand: {{ settings.brand_color }}; }</style>
```
This is where colors, logo, social links, typography go — so the merchant controls branding without touching code. `settings_data.json` holds the saved values and is managed by the editor (don't hand-edit casually).

---

## 11. Uploading & developing inside Shopify

### During development
```bash
shopify theme dev --store your-store.myshopify.com   # hot-reload local preview
```

### Push your theme to the store
```bash
# Upload as an UNPUBLISHED theme (safe — doesn't affect live site)
shopify theme push --unpublished --store your-store.myshopify.com

# Push to a specific existing theme (overwrites it)
shopify theme push --theme <THEME_ID>

# Pull changes a merchant made in the editor back into your code
shopify theme pull
```
Then in **Admin → Online Store → Themes**, you'll see your uploaded theme. Use **"Customize"** to open the Theme Editor (your sections/settings appear here), and **"Preview"** to view it. **"Publish"** makes it live.

### Editor vs. code (avoid drift)
The Theme Editor writes back to `templates/*.json`, `config/settings_data.json`, and section settings. To avoid conflicts:
- Treat **content/settings** as editor-owned (`pull` before you start).
- Treat **markup/CSS/JS/schema** as code-owned (`push` from git).
- Commit `.json` template changes deliberately; they can be overwritten by the editor (note the "auto-generated" warning at the top of `templates/index.json`).

### Version control
Git works normally. Keep the theme in a repo (this project is one). Use `shopify theme pull`/`push` as your sync, branch per feature, and consider connecting **GitHub integration** (Admin → Themes → Connect from GitHub) so merchant edits commit back automatically.

---

## 12. Things that will NOT migrate (set expectations)

- **Checkout** — Shopify owns it. You build up to "add to cart"; checkout is configured in admin (and only deeply customizable on Shopify Plus via Checkout Extensions). Don't try to port your Stripe checkout UI.
- **Custom backend routes / API routes** — no `app/api/*`. Use an embedded app (Remix + App Bridge) or the Storefront API instead.
- **Server-side secrets in the theme** — themes are client-visible. Secrets live in apps.
- **Arbitrary URL structures** — you're bound to Shopify's resource URLs + alternate templates.
- **SSR of your own data sources** — Liquid can't `fetch` external APIs at render time. Move that to client JS (Storefront API) or an app.
- **Auth/customer accounts UI** — exists but is Shopify's system (classic or new customer accounts); you skin it, you don't rebuild auth.
- **React component libraries** — they won't drop in. You re-implement UI in Liquid + CSS (+ optional light JS framework).

---

## 13. Performance & SEO parity

- **Images:** always use `image_url` + `image_tag` (auto `srcset`/`sizes`, WebP, CDN). Don't hardcode `<img>` with full-size sources.
- **CSS/JS:** ship through `asset_url`; `defer` scripts; avoid one giant bundle. Section-scoped CSS keeps things lean.
- **Lazy load** below-the-fold images (`loading="lazy"`) and consider `{% render %}` only what's needed.
- **SEO:** Shopify generates canonical URLs, sitemap.xml, robots.txt automatically. Add JSON-LD via a snippet, set `<title>`/meta from `page_title`/`page_description`, and **set up 301 redirects** (Admin → Navigation → URL Redirects, or bulk import) from your old Next.js URLs to the new Shopify URLs — critical to preserve SEO.
- **Core Web Vitals:** server-rendered HTML usually wins here vs. a heavy React bundle — lean into it; don't reintroduce a giant JS payload.

---

## 14. Classic Liquid theme vs. Hydrogen (headless) — quick decision

| Choose **Liquid theme** (this guide) if… | Choose **Hydrogen/headless** if… |
|---|---|
| You want fast time-to-launch & merchant-editable site | You need a fully custom React app / keep your Next.js-style stack |
| Standard storefront, app ecosystem, low maintenance | Complex custom UX, multiple data sources, your own infra |
| Small/medium team, no dedicated frontend infra | You have the team to own a React frontend + deploys |
| You want the Theme Editor / no-code content | You're fine building all content tooling yourself |

If keeping React is a hard requirement, look at **Hydrogen** (Shopify's React framework on Remix) + **Oxygen** hosting + **Storefront API**. That's a different migration (more "swap the data layer" than "rewrite in Liquid"), but you lose the Theme Editor and app simplicity.

---

## 15. Suggested step-by-step execution checklist

1. [ ] Create Partner account + dev store.
2. [ ] Install Shopify CLI; `shopify theme init` (start from Dawn).
3. [ ] Import products, collections, pages, blogs. Define metafields for custom data.
4. [ ] `shopify theme dev` — confirm live preview works against your data.
5. [ ] Port global shell: `theme.liquid`, header, footer, design tokens, fonts.
6. [ ] Build shared **snippets** (product card, buttons, icons).
7. [ ] Build **sections** with schemas for each homepage block; assemble `index.json`.
8. [ ] Build collection + product templates/sections; wire variant selection JS.
9. [ ] Wire cart (Ajax Cart API) + cart drawer/page.
10. [ ] Port content pages (about/contact/FAQ) as sections + alternate templates.
11. [ ] Add reviews/search/blog; inherit 404 + customer account from Dawn.
12. [ ] Expose branding via `settings_schema.json`.
13. [ ] Set up 301 redirects from old URLs.
14. [ ] QA in Theme Editor; test on mobile; check Web Vitals.
15. [ ] `shopify theme push --unpublished` → preview → **Publish**.

---

### Reference files in THIS repo (real working examples to copy patterns from)
- Global shell: `layout/theme.liquid`
- Homepage composition: `templates/index.json`
- Section with schema + blocks + presets: `sections/hero.liquid`
- Snippet (presentational component): `snippets/product-card.liquid`
- Section→snippet pattern: `sections/hero.liquid` calling `snippets/section-hero.liquid`
- Third-party app integration: `sections/judgeme-widget.liquid` (reviews)
- Theme settings: `config/settings_schema.json`

Study these alongside the guide — they show exactly how the concepts above look in production.
