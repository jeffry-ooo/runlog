import { defineConfig } from 'astro/config';

// When the custom domain (jeffry.running) is live, set CUSTOM_DOMAIN=true in
// the workflow env (or just delete this conditional and set base back to '/').
const useCustomDomain = process.env.CUSTOM_DOMAIN === 'true';

export default defineConfig({
  site: useCustomDomain ? 'https://jeffry.running' : 'https://jeffry-ooo.github.io',
  base: useCustomDomain ? '/' : '/runlog',
  output: 'static',
});
