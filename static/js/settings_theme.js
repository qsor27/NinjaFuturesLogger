// Handles the Appearance card form on /settings.
// PUTs the selected theme to /api/config/theme and reloads on success.

import { putJSON } from "./api.js";

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('theme-form');
  if (!form) return;
  const status = document.getElementById('theme-status');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const value = new FormData(form).get('theme');
    status.textContent = 'Saving\u2026';
    try {
      await putJSON('/api/config/theme', { theme: value });
      status.textContent = 'Saved. Reloading\u2026';
      location.reload();
    } catch {
      status.textContent = 'Save failed.';
    }
  });
});
