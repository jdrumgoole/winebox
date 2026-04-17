// OG-image preview capture (extracted from og-preview.html so the page is
// CSP-compliant: no inline <script>, no inline onclick handlers).

async function captureOG() {
  const frame = document.getElementById('og-frame');
  try {
    const dataUrl = await domToImage(frame);
    document.getElementById('linkedin-preview').src = dataUrl;

    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = 'og-preview.png';
    a.click();
  } catch (e) {
    alert('To capture: right-click the preview above \u2192 Inspect \u2192 select the .frame div \u2192 screenshot node in DevTools (or use shot-scraper)');
  }
}

// Minimal dom-to-image using SVG foreignObject.
async function domToImage(node) {
  const { width, height } = node.getBoundingClientRect();
  const clone = node.cloneNode(true);
  clone.style.width = width + 'px';
  clone.style.height = height + 'px';

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
    <foreignObject width="100%" height="100%">
      <div xmlns="http://www.w3.org/1999/xhtml">${clone.outerHTML}</div>
    </foreignObject>
  </svg>`;

  const img = new window.Image();
  img.width = width;
  img.height = height;

  return new Promise((resolve) => {
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = width * 2;
      canvas.height = height * 2;
      const ctx = canvas.getContext('2d');
      ctx.scale(2, 2);
      ctx.drawImage(img, 0, 0);
      resolve(canvas.toDataURL('image/png'));
    };
    img.src = 'data:image/svg+xml,' + encodeURIComponent(svg);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('capture-btn');
  if (btn) {
    btn.addEventListener('click', captureOG);
  }
});
