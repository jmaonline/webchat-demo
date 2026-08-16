# Embedding the chat widget on any website

The support agent can be dropped onto any external website — your main
storefront, a Shopify page, a completely unrelated site — with a single
line of HTML. No account, no build step, no dependency on the host site's
JS framework.

## Usage

```html
<script src="https://<your-app>.onrender.com/embed.js" async></script>
```

Put that anywhere in the page (before `</body>` is conventional). A chat
bubble appears bottom-right; clicking it opens the same Bookly support
agent as the one on your own site.

A working example simulating a totally unrelated site is in
`docs/embed-demo.html` — open it locally (after editing the `<script src>`
to point at your actual backend URL) to see it in action.

## How it works

- `/embed.js` is a small loader script. It injects an `<iframe>` pointing
  at `/embed` on your Bookly backend, fixed to the bottom-right corner of
  whatever page it's on.
- `/embed` is a bare version of the chat widget — just the bubble and chat
  panel, no landing-page chrome (that's what makes it different from the
  main site at `/`, which includes the full Help Center page).
- Because the widget lives inside an iframe, its CSS is fully isolated
  from the host page — nothing on the host site can visually break the
  widget, and the widget can't accidentally break the host site either.
- The iframe starts small (just big enough for the bubble) and resizes to
  chat-panel size when opened, via `postMessage` between the iframe and
  the loader script. This is the same general approach used by widgets
  like Intercom, Drift, and Zendesk Chat.
- All chat requests (`/api/chat`) are made from inside the iframe, so
  they're always same-origin relative to your Bookly backend — no CORS
  configuration needed regardless of which site embeds it.

## Current limitations (fine for a prototype, worth knowing)

- **Position is fixed** to bottom-right; there's no configuration option
  yet for corner, offset, or brand color. If you need that, it's a
  straightforward addition — the loader script would read `data-*`
  attributes off its own `<script>` tag (e.g. `data-position="bottom-left"`)
  and pass them along.
- **No domain allowlist.** `/embed.js` will happily load on any site that
  includes it — there's no mechanism today to restrict embedding to
  approved domains only. For a real deployment where you don't want
  randoms grabbing your `embed.js` URL and putting your support agent on
  their own site, consider checking the iframe's parent origin (via the
  `Referer` header or a signed embed token) before serving `/embed`.
- **Same "propose, never execute" guarantees apply** regardless of where
  the widget is embedded — refunds/returns still always require staff
  approval via `/admin`, since that logic lives in the backend, not the
  widget.
