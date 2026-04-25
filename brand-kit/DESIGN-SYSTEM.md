# WineBox Design System

> This document defines the visual and UX language of WineBox. It is a companion to [BRAND.md](BRAND.md) (which covers logo, colour palette, and brand identity rules) — this document covers **design tokens** (spacing, radius, shadows, typography scale), **components** (buttons, forms, cards, modals), and **UX voice**.

## Where things live

| What | Where |
|------|-------|
| Brand identity, logo, colour definitions | [BRAND.md](BRAND.md) |
| Raw brand colours (JSON) | [colors.json](colors.json) |
| Full design tokens (JSON) | [tokens.json](tokens.json) |
| CSS source of truth | `winebox/static/css/style.css` (`:root`) |
| Live component showcase | [`/design-system`](http://localhost:8899/design-system) in the running app |
| Logo & favicon assets | `brand-kit/svg/`, `brand-kit/png/`, `brand-kit/favicon/` |

**Source of truth.** `winebox/static/css/style.css` is the authoritative token store. `tokens.json` documents those tokens. If they drift, the CSS wins and this kit should be updated.

---

## 1. Design Tokens

### 1.1 Colour

The palette is defined in [BRAND.md §Colour Palette](BRAND.md). In CSS it is exposed through `:root` custom properties:

| CSS variable | Value | Typical use |
|---|---|---|
| `--burgundy` | `#5C0A2D` | Nav gradient end, dark primary |
| `--burgundy-light` | `#8B1A4A` | Nav gradient start, primary |
| `--bottle` | `#B82860` | Accents, primary-light |
| `--gold` | `#C49A3C` | Secondary CTA, accents |
| `--gold-light` | `#F0D78C` | Labels, soft highlights |
| `--case-wood` | `#B8956A` | Logo case fill |
| `--cream` | `#FAF7F2` | Page background |
| `--cream-dark` | `#F0EBE3` | Hero gradient end, soft warm fills |
| `--dark-bg` | `#1A0A10` | Dark mode background |

**Semantic aliases** — always prefer these in component CSS over raw brand names. They let us re-theme without touching components:

| CSS variable | Default | Role |
|---|---|---|
| `--primary-color` | `var(--burgundy-light)` | Primary actions, links, focus |
| `--primary-light` | `var(--bottle)` | Primary hover / emphasis |
| `--primary-dark` | `var(--burgundy)` | Primary depressed |
| `--secondary-color` | `var(--gold)` | Secondary actions |
| `--background-color` | `var(--cream)` | Page background |
| `--card-background` | `#ffffff` | Cards, modals, inputs |
| `--text-color` | `#2D1A22` | Body text |
| `--text-muted` | `#8A7A80` | Secondary text, labels |
| `--border-color` | `#E8E0D8` | Input & card borders |
| `--success-color` | `#4a7c59` | Success states |
| `--warning-color` | `#c9a227` | Warning states |
| `--error-color` | `#a63d40` | Errors, destructive actions |
| `--error-dark` | `#8b3235` | Error hover, deep error text |

### 1.2 Typography

| Role | Family | Weight | Size |
|---|---|---|---|
| Logo wordmark | `Playfair Display` | 700 / 400 | contextual |
| Tagline / brand subtitle | `Cormorant Garamond` | 400 / 600 | contextual |
| App headings (`h1`–`h4`) | `Playfair Display`, Georgia, serif | 700 | 1.75rem (h2) |
| App body & UI | `DM Sans`, system stack | 400 / 500 / 700 | 1rem |
| Stat value | `DM Sans` | 700 | 1.6rem |
| Small / label / badge | `DM Sans` | 500 | 0.75–0.875rem |

Serif fonts are used **only** for the logo, taglines, and app headings. UI chrome is system font.

### 1.3 Spacing

Based on a `0.25rem` (4px) unit. Standard values: `0.25 / 0.5 / 0.75 / 1 / 1.25 / 1.5 / 2 rem`. Do not invent one-off values.

### 1.4 Border radius

| Token | Value | Use |
|---|---|---|
| `--radius-sm` | `6px` | Compact controls (select wrappers, progress tracks, image thumbnails) |
| `--radius` | `8px` | Buttons, inputs, nav pills, small cards |
| `--radius-lg` | `12px` | Stat cards, modals, large surfaces |
| — | `2px` | Beta-style badges only |
| — | `4px` | Logo case corners only |
| — | `9999px` | True pills (avatar, tag) |

### 1.5 Elevation (shadows)

| Token | Value | Use |
|---|---|---|
| `--shadow` | `0 2px 8px rgba(0,0,0,0.08)` | Default card, sticky header |
| `--shadow-md` | `0 4px 12px rgba(0,0,0,0.1)` | Mid elevation — image thumbnails, floating controls |
| `--shadow-hover` | `0 4px 16px rgba(0,0,0,0.12)` | Hover / raised state |
| (focus ring) | `0 0 0 3px rgba(139, 26, 74, 0.1)` | Input `:focus` |

### 1.6 Layout

- Main content max-width: **1400px**, centred, padded `2rem`.
- Sticky header at `z-index: 100`, modals at `z-index: 200`.
- Mobile breakpoint in style.css kicks in around 768px.

### 1.7 Motion

- Default transition: `all 0.2s ease` or `all 0.2s` (buttons, nav, inputs).
- Keep it under 300ms for UI feedback — this is a utility app, not a storybook.

### 1.8 Themes (light & dark)

WineBox supports both light and dark themes through semantic-token overrides. Brand colours (`--burgundy`, `--gold`) stay the same; only semantic aliases (`--background-color`, `--card-background`, `--text-color`, etc.) and tinted feedback variables flip.

**Activation**

| State | How |
|---|---|
| Default | Matches the user's OS preference via `@media (prefers-color-scheme: dark)` |
| Force dark | `<html data-theme="dark">` |
| Force light | `<html data-theme="light">` |

The showcase at `/design-system` includes a theme toggle in the header that cycles through *auto / dark / light* and persists the choice in `localStorage` under the key `wb-theme`.

**What changes**

| Token | Light | Dark |
|---|---|---|
| `--background-color` | `--cream` (`#FAF7F2`) | `#14080c` |
| `--card-background` | `#ffffff` | `#241419` |
| `--text-color` | `#2D1A22` | `#f0e6e9` |
| `--text-muted` | `#8A7A80` | `#a89098` |
| `--border-color` | `#E8E0D8` | `#3a2530` |
| `--primary-color` | `--burgundy-light` | `--bottle` (brighter) |
| `--primary-dark` | `--burgundy` | `--burgundy-light` |
| `--shadow*` | low alpha (light shadow) | higher alpha (deeper shadow) |
| `--tint-{success\|warning\|error\|info\|gold}-bg/fg` | low-alpha tint, dark text | higher-alpha tint, light text |

**What stays the same**

- The header burgundy gradient anchors the page in both themes — it uses `--burgundy-light` and `--burgundy` directly, not semantic primaries.
- All brand palette tokens (`--burgundy`, `--gold`, etc.) are theme-independent.
- The wine bottle, gold, and case-wood logo colours never change.

**Authoring rules**

- Always use semantic tokens (`--text-color`, `--card-background`) in component CSS, not raw hex or brand tokens. They flip for free.
- For tinted backgrounds (alerts/toasts/badges), use the `--tint-*` variables — never hardcode `rgba()` of a brand colour.
- If you need a colour that doesn't fit the existing tokens, add a new semantic token in **both** the `:root` and `:root[data-theme="dark"]` blocks (and the `prefers-color-scheme: dark` mirror). Don't just override `[data-theme="dark"] .my-component`.

**Known gaps**

- The landing page hero gradient (`--cream → --cream-dark`) renders too pale in dark mode. Landing is mostly marketing-static and hasn't been audited for dark; treat as a follow-up.
- Native form widgets (date pickers, file pickers) inherit `color-scheme` automatically.

---

## 2. Components

Every component below already exists in `style.css`. Classes are the API — use them verbatim, don't rename.

### 2.1 Buttons — `.btn`

| Class | Role |
|---|---|
| `.btn` | Required base class on every button |
| `.btn-primary` | Primary action — solid burgundy, white text |
| `.btn-secondary` | Secondary — white fill, bordered |
| `.btn-outline` | Tertiary — transparent, burgundy border |
| `.btn-danger` | Destructive — red fill |
| `.btn-small` | Compact size modifier |
| `.btn-full` | Full-width (e.g. inside modals) |

```html
<button class="btn btn-primary">Add bottle</button>
<button class="btn btn-outline btn-small">Cancel</button>
```

**Rules**
- Every page gives at most one primary button per visual group. Everything else is secondary/outline.
- Primary buttons use the burgundy `--primary-color`, not gold. Gold (`--secondary-color`) is reserved for marketing CTAs on the landing page.
- Destructive actions use `.btn-danger` and always confirm via a modal.

### 2.2 Forms

Wrap fields in `.form-group`. Use `.form-grid` for multi-column layouts.

```html
<div class="form-grid">
  <div class="form-group">
    <label for="wine-name">Wine</label>
    <input id="wine-name" type="text" />
  </div>
  <div class="form-group full-width">
    <label for="notes">Tasting notes</label>
    <textarea id="notes"></textarea>
  </div>
</div>
```

**Rules**
- Every input has a visible `<label>`. Placeholders are not labels.
- Inputs render the brand focus ring — do not suppress it.
- Helper text uses `.form-hint`; validation errors use `--error-color` text below the field.
- Image/file uploads use the dashed `.image-upload` pattern.

### 2.3 Cards

| Class | Use |
|---|---|
| `.stat-card` | Dashboard number tile with `.stat-value` + `.stat-label` |
| `.chart-card` | Chart container in dashboard grid |
| `.login-card` | Auth forms (narrower, centred) |

All cards: white background, `--radius-lg` corners, `--shadow`, `1px` border in `--border-color`.

### 2.4 Modals

```html
<div class="modal active">
  <div class="modal-content modal-small">
    <button class="modal-close">&times;</button>
    <!-- body -->
  </div>
</div>
```

Size modifiers: `.modal-small` (≤400px), default (≤800px), `.modal-large` (≤900px). Background scrim is `rgba(0,0,0,0.5)`. Modals trap focus; close on Esc and scrim click.

### 2.5 Navigation

- `.nav-link` — header nav item. `.nav-link.active` marks the current page.
- `.cellar-tab` — second-level tabs within a page; active tab gets a bottom border in `--primary-color`.
- `.page-header` — page title row (title left, primary action button right).

### 2.6 Alerts — `.alert`

Inline status messages paired with a semantic colour. Use for non-blocking feedback inside a page flow (not as toasts — toasts are a separate component we haven't built yet).

```html
<div class="alert alert-success" role="status">
  <div class="alert-body">
    <span class="alert-title">Bottle added</span>
    Château Margaux 2015 is now in your cellar.
  </div>
  <button class="alert-close" aria-label="Dismiss">&times;</button>
</div>
```

| Variant | Use when |
|---|---|
| `.alert-success` | Confirms an action completed (bottle added, cellar saved) |
| `.alert-warning` | Proceed with caution — e.g. "Vintage looks unusual, double-check the label" |
| `.alert-error` | An action failed — always explain what to try next |
| `.alert-info` | Neutral context, like a hint or a tip. Not for important messages |

**Rules**
- Title optional; body is always required.
- Use `role="status"` (success/info) or `role="alert"` (warning/error) for screen readers.
- `.alert-close` is optional — omit for transient alerts that auto-dismiss.

### 2.7 Empty states — `.empty-state`

Shown in place of a list or grid when there is no content. Every list in the app must have one; "No results" on its own is never acceptable.

```html
<div class="empty-state">
  <div class="empty-state-icon">
    <svg viewBox="0 0 24 24" fill="none" stroke-width="1.5" aria-hidden="true">
      <!-- bottle icon -->
    </svg>
  </div>
  <div class="empty-state-title">Your cellar is empty</div>
  <div class="empty-state-description">Start by scanning a bottle's label or importing a spreadsheet of what you already own.</div>
  <div class="empty-state-action">
    <button class="btn btn-primary">Add bottle</button>
    <button class="btn btn-outline">Import cellar</button>
  </div>
</div>
```

**Rules**
- Title is a short noun phrase describing the state, not the action.
- Description explains what belongs here and why it's empty.
- Primary action fills the gap (e.g. "Add bottle"). Up to two actions; more and the user freezes.
- Icon is optional but recommended — use a thin-stroke SVG, not an emoji.

### 2.8 Badges — `.badge`

Small pill labels for categorical status. Use sparingly — one badge per item; more and the list becomes noisy.

```html
<span class="badge badge-primary">Red</span>
<span class="badge badge-success">Drink now</span>
<span class="badge badge-warning">Peak soon</span>
<span class="badge badge-error">Past peak</span>
<span class="badge badge-gold">Reserve</span>
<span class="badge badge-neutral">Unrated</span>
```

| Variant | Use when |
|---|---|
| `.badge-primary` | Categorical label (wine colour, region) |
| `.badge-success` | Positive status (drinkable, in stock) |
| `.badge-warning` | Attention needed (peak approaching, low stock) |
| `.badge-error` | Negative status (past peak, out of stock) |
| `.badge-gold` | Premium / reserve / feature highlight |
| `.badge-neutral` | Default / undefined state |

**Rules**
- Badge text is a short noun or adjective, not a full sentence.
- Never use a badge as the only signal for a number — pair it with a labelled value (see §3.3, no naked numbers).
- Don't combine badges with coloured text for the same meaning — it doubles the visual load.

### 2.9 Icons — `.icon`

All UI icons in WineBox are inline SVGs sharing one canonical style. Apply the `.icon` class to any inline `<svg>`; pair with a size modifier.

```html
<!-- Inline with text — sizes to surrounding font -->
<button class="btn btn-primary">
  <svg class="icon" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 5v14m-7-7h14"/>
  </svg>
  Add bottle
</button>

<!-- Explicit size for standalone use -->
<svg class="icon icon-2xl" viewBox="0 0 24 24" aria-hidden="true"><!-- ... --></svg>
```

| Class | Size | Stroke | Use |
|---|---|---|---|
| `.icon` (no size modifier) | inherits from container | inherit | When a parent class (`.empty-state-icon`, `.password-toggle`) sets the size |
| `.icon icon-text` | `1em` (matches font) | 2 | Inline next to text — a verb icon in a button, a status icon in a row |
| `.icon icon-sm` | 16px | 2 | Small chrome — close buttons, tag dots |
| `.icon icon-md` | 20px | 2 | Default standalone size — toolbar buttons |
| `.icon icon-lg` | 24px | 2 | Section headers, prominent actions |
| `.icon icon-xl` | 32px | 1.5 | Card-level illustrations (entry-path tiles, feature panels) |
| `.icon icon-2xl` | 48px | 1.5 | Empty states, hero illustrations |

**Authoring rules**

- **Always** `viewBox="0 0 24 24"`. The system assumes a 24-unit grid.
- **Always** `fill="none"` on the `<svg>` and use stroked paths. Coloured fills are reserved for the brand logo, not UI icons.
- **Don't** set inline `width`/`height`/`stroke-width` — let the `.icon-*` class do it.
- **Stroke width** is part of the size class — bigger icons get thinner strokes (1.5) so optical weight stays even.
- **Colour** comes from `currentColor`. Set the colour on the parent (`color: var(--primary-color)`) — the icon inherits it. Never hardcode a stroke colour.

**Accessibility**

- Decorative icon (paired with text): `aria-hidden="true"`.
- Meaningful icon (icon-only button): provide an `aria-label` on the button, or a `<title>` element inside the SVG.

**Known follow-ups**
- The eye / eye-off password-toggle icon is duplicated 8× across login forms. A future pass should extract it to a shared `<symbol>` sprite or a small JS helper.

### 2.10 Toasts — `WineBox.toast`

Transient feedback floating outside the page flow. Use a toast — not an alert — when the feedback is **a result of an action**, not part of a form's local state. Use an alert (§2.6) for errors and warnings tied to a specific form or panel.

```js
WineBox.toast.success("Bottle added");
WineBox.toast.error("Couldn't import — three rows missing a wine name.");
WineBox.toast.warning("Vintage looks unusual", { title: "Double-check" });
WineBox.toast.info("Tip — drag a photo onto the scan area");
```

| Method | Default duration | Default role |
|---|---|---|
| `WineBox.toast.success(msg, opts?)` | 4 s | `status` |
| `WineBox.toast.warning(msg, opts?)` | 4 s | `alert` |
| `WineBox.toast.error(msg, opts?)`   | **sticky** | `alert` |
| `WineBox.toast.info(msg, opts?)`    | 4 s | `status` |
| `WineBox.toast.show(msg, opts?)`    | (uses `opts.variant`) | inferred |

`opts` accepts `{ title, duration, dismissible, variant }`. `duration: 0` makes the toast sticky; default for errors is sticky so the user can read them. Returns `{ dismiss(), element }` so callers can dismiss programmatically.

**Rules**
- Errors are sticky by default — never auto-dismiss something the user must act on.
- Body copy is one short sentence. If you need more, link to a page or open a modal instead.
- Don't fire toasts for things the user already sees confirmed in the UI (e.g. "Saved" when the saved row is right there).
- Don't stack more than three toasts at once. If you would, you're using toasts for the wrong thing.
- Toasts share the alert variant colours. They add a `box-shadow` and slide in to signal arrival.

**Mounting** — `index.html` includes a `<div id="toast-container" class="toast-container">` and loads `/static/js/toast.js`. The script is idempotent — calling `WineBox.toast.show()` on a page without the container creates one.

### 2.11 Picking the right feedback component

| You need to… | Reach for |
|---|---|
| Confirm a destructive action before it happens | Modal (§2.4) |
| Tell the user a background action finished | Toast (§2.10) |
| Surface a form-level error or hint that should stay until fixed | Alert (§2.6) |
| Show a categorical status next to an item | Badge (§2.8) |
| Replace a list when there's nothing to show | Empty state (§2.7) |

---

## 3. UX Voice & Tone

These rules extend the project's general UX philosophy (see `CLAUDE.md §UX Philosophy`). They apply to every piece of user-facing copy.

### 3.1 Audience

The reader is a wine enthusiast, **not a developer or data professional**. Assume zero familiarity with schemas, IDs, APIs, or import batches.

### 3.2 Language

- Use **wine vocabulary**: *cellar, bottle, case, label, vintage, varietal*.
- Avoid **system vocabulary**: record, entry, document, batch, row, field, object, endpoint.
- Prefer **active, human phrasing**: "You have 42 bottles" beats "42 records found".
- Errors explain what went wrong **in wine terms** plus what to do next. Never surface raw server errors or stack traces.

### 3.3 Labels & numbers

- **No naked numbers.** Every number has a unit or noun: *"14.5% ABV"*, *"245 bottles"*, *"3.8 (245 ratings)"*.
- **Use sentence case** for labels and buttons: *"Add bottle"*, not *"Add Bottle"* or *"ADD BOTTLE"*.
- Exception: the beta badge and tiny `.stat-label` use `text-transform: uppercase` for a deliberate typographic accent — leave those alone.

### 3.4 Button copy

- Start with a verb: *"Save changes"*, *"Record wine"*, *"Import cellar"*.
- Never use lone *"OK"* / *"Submit"* / *"Click here"*.
- Dangerous actions are specific: *"Delete bottle"*, not *"Delete"*.

### 3.5 Renaming & consistency

When a visible label changes, **the code must follow**. Rename HTML ids, CSS classes, JS functions, API paths, and test references to match. Stale names (`checkin-form` for a "Record Wine" feature) create confusion and are treated as bugs.

### 3.6 Empty states

Every list or dashboard panel has a designed empty state explaining what belongs here and offering the primary action to fill it. "No results" on its own is not acceptable.

---

## 4. Accessibility Baseline

- All interactive elements are reachable by keyboard. `.nav-link:focus-visible` and input focus rings are part of the design — do not remove them.
- Contrast: burgundy-on-cream and white-on-burgundy both pass WCAG AA for body text. Gold (`#C49A3C`) on cream does **not** pass for body text — use it for accents, icons, or on dark backgrounds only.
- Every form control has a programmatically-associated `<label>` (see §2.2).
- Icon-only buttons must have an `aria-label`.

---

## 5. Using the system

### Adding a new screen
1. Start from the tokens, not raw hex values.
2. Compose existing components (`.btn`, `.form-group`, `.stat-card`, `.modal`) before inventing new ones.
3. If you need a new component, document it in §2 and render it in the live showcase page (`winebox/static/design-system.html`).

### Changing a token
1. Edit `:root` in `winebox/static/css/style.css`.
2. Update `brand-kit/tokens.json` to match.
3. Visit `/design-system` in the running app and verify every component still renders correctly.
4. Update this document if the semantics changed.

### Reviewing a design
Use this checklist:
- [ ] Uses tokens, not raw hex values
- [ ] Every number has a unit or noun
- [ ] Button copy starts with a verb
- [ ] No system jargon in UI strings
- [ ] Empty state designed
- [ ] Keyboard-accessible and focus-visible
