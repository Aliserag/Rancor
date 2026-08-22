import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import vercel from "@astrojs/vercel";

export default defineConfig({
  // Canonical deployed host (the sitemap publishes absolute URLs, so a
  // placeholder here ships URLs nobody owns — finding N4).
  site: "https://rancor.litai.ca",
  // Pages stay prerendered/static; the adapter exists solely for the
  // /api/live-run server endpoint (prerender=false there).
  adapter: vercel(),
  integrations: [
    sitemap({
      // SPEC §7: transcript pages are excluded from the sitemap;
      // the gated explore browser is excluded for the same reason
      filter: (page) => !page.includes("/transcripts") && !page.includes("/explore"),
    }),
  ],
});
