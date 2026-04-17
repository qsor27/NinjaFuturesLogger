// Handles the Appearance card form on /settings.
// PUTs the selected theme to /api/config/theme and reloads on success.

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('theme-form');
  if (!form) return;
  const status = document.getElementById('theme-status');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const value = new FormData(form).get('theme');
    status.textContent = 'Saving\u2026';
    try {
      const resp = await fetch('/api/config/theme', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({theme: value}),
      });
      if (resp.ok) {
        status.textContent = 'Saved. Reloading\u2026';
        location.reload();
      } else {
        status.textContent = 'Save failed.';
      }
    } catch {
      status.textContent = 'Save failed.';
    }
  });
});
