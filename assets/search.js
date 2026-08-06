/*
 * ------------------------------------------------------------
 * Predictive Search Functionality
 * ------------------------------------------------------------
 */
(function () {
  const searchRoots = document.querySelectorAll('[data-km-search]');
  if (!searchRoots.length) return;

  searchRoots.forEach(root => {
    const input = root.querySelector('[data-km-search-input]');
    const panel = root.querySelector('[data-km-search-results]');
    const inner = root.querySelector('[data-km-search-inner]');
    let debounceTimer = null;
    let activeIndex = -1;
    let lastQuery = '';

    function escHtml(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function formatMoney(value) {
      if (!value) return '';
      if (/[^\d.,]/.test(String(value))) return String(value);
      const n = Number(value);
      if (isNaN(n)) return '';
      return '$' + n.toFixed(2);
    }

    function closePanel() {
      panel.hidden = true;
      panel.style.display = 'none';
      inner.innerHTML = '';
      activeIndex = -1;
    }

    function openPanel() {
      panel.hidden = false;
      panel.style.display = 'block';
    }

    function renderResults(q, products) {
      if (!products || products.length === 0) {
        inner.innerHTML = '<div class="km-search-empty">No products found for &ldquo;' + escHtml(q) + '&rdquo;</div>';
        openPanel();
        return;
      }

      let html = '';
      products.forEach(function (p) {
        const img = p.featured_image || p.image;
        let imgSrc = '';
        if (img) {
          imgSrc = typeof img === 'string' ? img : (img.url || '');
        }
        
        const price = formatMoney(p.price);
        const compare = p.compare_at_price_min && p.compare_at_price_min > p.price_min
          ? formatMoney(p.compare_at_price_min) : '';

        html += `
          <a class="km-search-result" href="${escHtml(p.url)}">
            ${imgSrc ? `<img class="km-search-result__img" src="${escHtml(imgSrc)}" alt="${escHtml(p.title)}" loading="lazy">` : '<span class="km-search-result__img"></span>'}
            <div class="km-search-result__body">
              <div class="km-search-result__name">${escHtml(p.title)}</div>
            </div>
            <div class="km-search-result__price">
              ${compare ? `<span class="km-search-result__price-compare">${compare}</span>` : ''}
              ${price}
            </div>
          </a>
        `;
      });

      html += `<a class="km-search-footer" href="/search?q=${encodeURIComponent(q)}&type=product">See all results for &ldquo;${escHtml(q)}&rdquo; →</a>`;
      inner.innerHTML = html;
      openPanel();
    }

    function fetchResults(q) {
      const url = `/search/suggest.json?q=${encodeURIComponent(q)}&resources[type]=product&resources[limit]=8&resources[options][unavailable_products]=last`;
      
      fetch(url)
        .then(r => r.json())
        .then(data => {
          if (lastQuery !== q) return;
          const products = (data && data.resources && data.resources.results && data.resources.results.products) || [];
          renderResults(q, products);
        })
        .catch(() => { /* ignore errors */ });
    }

    input.addEventListener('input', function () {
      const q = input.value.trim();
      lastQuery = q;
      clearTimeout(debounceTimer);
      if (q.length < 2) {
        closePanel();
        return;
      }
      debounceTimer = setTimeout(function () {
        fetchResults(q);
      }, 250);
    });

    input.addEventListener('focus', function () {
      if (input.value.trim().length >= 2 && inner.innerHTML) {
        openPanel();
      }
    });

    document.addEventListener('click', function (e) {
      if (!root.contains(e.target)) {
        closePanel();
      }
    });

    input.addEventListener('keydown', function (e) {
      const items = inner.querySelectorAll('.km-search-result');
      if (e.key === 'Escape') {
        closePanel();
        input.blur();
        return;
      }
      if (!items.length) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        activeIndex = Math.min(activeIndex + 1, items.length - 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        activeIndex = Math.max(activeIndex - 1, -1);
      } else if (e.key === 'Enter' && activeIndex >= 0) {
        e.preventDefault();
        window.location.href = items[activeIndex].getAttribute('href');
        return;
      } else {
        return;
      }

      items.forEach((el, i) => {
        el.classList.toggle('is-active', i === activeIndex);
      });

      if (activeIndex >= 0) {
        items[activeIndex].scrollIntoView({ block: 'nearest' });
      }
    });
  });
})();
