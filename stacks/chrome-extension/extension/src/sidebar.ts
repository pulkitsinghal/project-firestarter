// {{ project_name }} — side panel entry. Bundled to dist/sidebar.js and loaded
// by sidebar.html. Keep this a thin view over the logic in your pure modules.
import { greeting } from './greeting';

const el = document.getElementById('greeting');
if (el) {
  el.textContent = greeting();
}
