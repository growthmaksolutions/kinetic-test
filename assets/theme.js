/* ==========================================================================
   Kinetic Motorcycles — Base theme JS
   ========================================================================== */
(function () {
  'use strict';

  // --------- Sticky header shadow on scroll ---------
  const header = document.querySelector('[data-km-header]');
  if (header) {
    const onScroll = () => {
      if (window.scrollY > 20) header.classList.add('is-scrolled');
      else header.classList.remove('is-scrolled');
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  // --------- Mobile menu toggle (drawer + backdrop + mega menu) ---------
  const menuToggle = document.querySelector('[data-km-menu-toggle]');
  const menuPanel = document.querySelector('[data-km-menu]');
  if (menuToggle && menuPanel) {
    const closeMenu = () => {
      menuPanel.classList.remove('is-open');
      menuToggle.setAttribute('aria-expanded', 'false');
      document.body.classList.remove('km-menu-open');
      document.body.style.overflow = '';
    };
    const openMenu = () => {
      menuPanel.classList.add('is-open');
      menuToggle.setAttribute('aria-expanded', 'true');
      document.body.classList.add('km-menu-open');
      document.body.style.overflow = 'hidden';
    };
    menuToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      if (menuPanel.classList.contains('is-open')) closeMenu();
      else openMenu();
    });
    // Click the close ✕ button inside the drawer
    const closeBtn = menuPanel.querySelector('[data-km-menu-close]');
    if (closeBtn) {
      closeBtn.addEventListener('click', closeMenu);
    }
    // Click backdrop (outside drawer) closes too
    document.addEventListener('click', (e) => {
      if (!menuPanel.classList.contains('is-open')) return;
      if (menuPanel.contains(e.target) || menuToggle.contains(e.target)) return;
      closeMenu();
    });
    // Close on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && menuPanel.classList.contains('is-open')) closeMenu();
    });
    // Handle mega menu expansion via separate button on mobile
    menuPanel.querySelectorAll('[data-km-mega-toggle]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const item = btn.closest('.km-header__menu-item--mega');
        if (item) {
          const open = item.classList.toggle('is-mega-open');
          btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        }
      });
    });

    menuPanel.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', (e) => {
        // Normal link inside drawer — close the drawer as it navigates
        if (menuPanel.classList.contains('is-open')) closeMenu();
      });
    });
  }

  // --------- Model chooser tabs ---------
  document.querySelectorAll('[data-km-tabs]').forEach((container) => {
    const tabs = container.querySelectorAll('[data-km-tab]');
    const panels = container.querySelectorAll('[data-km-panel]');
    tabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        const id = tab.dataset.kmTab;
        tabs.forEach((t) => t.classList.toggle('is-active', t.dataset.kmTab === id));
        panels.forEach((p) => p.classList.toggle('is-active', p.dataset.kmPanel === id));
      });
    });
  });

  // --------- Before/After slider ---------
  document.querySelectorAll('[data-km-compare]').forEach((el) => {
    const handle = el.querySelector('[data-km-compare-handle]');
    const after = el.querySelector('[data-km-compare-after]');
    if (!handle || !after) return;

    let rect;
    let dragging = false;
    const setPos = (x) => {
      const r = el.getBoundingClientRect();
      let pct = ((x - r.left) / r.width) * 100;
      pct = Math.max(0, Math.min(100, pct));
      after.style.clipPath = `inset(0 ${100 - pct}% 0 0)`;
      handle.style.left = pct + '%';
    };
    const onMove = (e) => {
      if (!dragging) return;
      const x = e.touches ? e.touches[0].clientX : e.clientX;
      setPos(x);
    };
    const onDown = (e) => {
      dragging = true;
      rect = el.getBoundingClientRect();
      const x = e.touches ? e.touches[0].clientX : e.clientX;
      setPos(x);
    };
    const onUp = () => { dragging = false; };

    handle.addEventListener('mousedown', onDown);
    handle.addEventListener('touchstart', onDown, { passive: true });
    document.addEventListener('mousemove', onMove);
    document.addEventListener('touchmove', onMove, { passive: true });
    document.addEventListener('mouseup', onUp);
    document.addEventListener('touchend', onUp);

    // Allow click anywhere on the image to move the slider
    el.addEventListener('click', (e) => {
      if (e.target === handle) return;
      const x = e.clientX;
      setPos(x);
    });

    // Initial position at 50%
    after.style.clipPath = 'inset(0 50% 0 0)';
    handle.style.left = '50%';
  });

  // --------- FAQ accordion ---------
  document.querySelectorAll('[data-km-faq]').forEach((item) => {
    const trigger = item.querySelector('[data-km-faq-trigger]');
    const panel = item.querySelector('[data-km-faq-panel]');
    if (!trigger || !panel) return;
    trigger.addEventListener('click', () => {
      const open = item.classList.toggle('is-open');
      trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  });

  // --------- Reveal on scroll ---------
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          e.target.classList.add('km-in-view');
          io.unobserve(e.target);
        }
      });
    }, { rootMargin: '0px 0px -10% 0px', threshold: 0 });
    document.querySelectorAll('[data-km-reveal]').forEach((el) => io.observe(el));
  }

  // --------- Horizontal carousel controls ---------
  document.querySelectorAll('[data-km-carousel]').forEach((carousel) => {
    const track = carousel.querySelector('[data-km-track]');
    const prev = carousel.querySelector('[data-km-prev]');
    const next = carousel.querySelector('[data-km-next]');
    if (!track) return;
    const scrollBy = (dir) => {
      const card = track.firstElementChild;
      const step = card ? card.getBoundingClientRect().width + 24 : 300;
      track.scrollBy({ left: dir * step, behavior: 'smooth' });
    };
    if (prev) prev.addEventListener('click', () => scrollBy(-1));
    if (next) next.addEventListener('click', () => scrollBy(1));
  });
  // ---------- Product variant picker (color/size) ----------
  document.querySelectorAll('[data-km-product-form]').forEach((form) => {
    const dataEl = form.querySelector('[data-km-variants]');
    if (!dataEl) return;
    let variants;
    try { variants = JSON.parse(dataEl.textContent); } catch (e) { return; }
    
    const infoContainer = form.closest('.km-pp__info') || document;
    const idInput = form.querySelector('input[name="id"]');
    const addBtn = form.querySelector('.km-pp__add');
    const priceEl = infoContainer.querySelector('.km-pp__price');
    const compareEl = infoContainer.querySelector('.km-pp__compare');
    const mainImg = document.getElementById('km-product-hero-img');
    
    const selected = [];
    form.querySelectorAll('.km-pp__option-values').forEach((group, i) => {
      const active = group.querySelector('.km-pp__option-value.is-active') || group.querySelector('.km-pp__option-value');
      if (active) {
        selected[i] = active.getAttribute('data-option-value');
      }
    });

    // Improved currency detection
    let currencySymbol = '$ ';
    if (priceEl) {
      const text = priceEl.textContent.trim();
      const match = text.match(/^[^0-9\s,.]+/);
      if (match) currencySymbol = match[0].trim() + ' ';
    }

    const formatMoney = (cents) => {
      const amount = (cents / 100).toLocaleString('en-US', { 
        minimumFractionDigits: 2, 
        maximumFractionDigits: 2 
      });
      return currencySymbol + amount;
    };

    const update = () => {
      const match = variants.find(v => {
        return v.options.every((opt, i) => {
          return opt && selected[i] && opt.toString().trim() === selected[i].toString().trim();
        });
      });

      if (match) {
        if (idInput) idInput.value = match.id;
        if (priceEl) priceEl.textContent = formatMoney(match.price);
        
        if (compareEl) {
          if (match.compare_at_price > match.price) {
            compareEl.textContent = formatMoney(match.compare_at_price);
            compareEl.style.display = '';
          } else {
            compareEl.style.display = 'none';
          }
        }
        
        if (addBtn) {
          addBtn.disabled = !match.available;
          addBtn.textContent = match.available ? 'Add to Cart' : 'Sold Out';
        }

        if (match.featured_image && match.featured_image.src && mainImg) {
          mainImg.src = match.featured_image.src;
        }

        try {
          const url = new URL(window.location.href);
          url.searchParams.set('variant', match.id);
          window.history.replaceState({}, '', url);
        } catch (e) {}
      }
    };

    form.querySelectorAll('.km-pp__option-value').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const idx = parseInt(btn.getAttribute('data-option-index'), 10);
        const val = btn.getAttribute('data-option-value');
        
        if (isNaN(idx)) return;
        selected[idx] = val;
        
        const group = btn.closest('.km-pp__option-values');
        if (group) {
          group.querySelectorAll('.km-pp__option-value').forEach(b => b.classList.remove('is-active'));
          btn.classList.add('is-active');
        }
        update();
      });
    });
    
    // Initial sync
    update();
  });

})();
